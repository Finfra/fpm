#!/bin/bash
# fpm-ask-question-guard.sh — Stop hook (Issue72, 2026-05-20)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/hub-mode-arch.md (Mode B 우회 가드). 절차:
#   ~/.claude/rules/global-scar-change-rules.md
#
# 배경 (Issue72):
#   hub Mode B(AskUserQuestion PreToolUse intercept → Firefox 폼 자동 회수)는
#   fpm-ask-intercept.sh 가 AskUserQuestion 도구 호출만 가로챔. Claude 가 결정
#   질문을 *평문*으로 출력하면 인터셉트 대상이 없어 Mode B 가 조용히 우회됨.
#   설계상 한계(코드 버그 아님)이며, 본 hook 이 재발 방지 가드 역할.
#
# 동작:
#   - FPM_SESSION_ORIGIN=pm-do(-p 몸체)     → exit 0 — 도구가 없다, 봇 질문은 중계 [Issue749]
#   - .hub-active/<hash> 없음 or effective=off → exit 0 (평소) [Issue283]
#   - stop_hook_active true               → exit 0 (무한 루프 방지)
#   - Mode D 마커(htm-form:auto:v1) 존재  → exit 0 (Mode D 가 정당 처리)
#   - 직전 assistant 응답이 평문 결정 질문 패턴 매칭
#     → decision:"block" + reason 주입 (AskUserQuestion 재호출 지시)
#
# 탐지 휴리스틱 — 정본은 hooks/lib/decision-question.py (Issue749 단일 지점, 보수적 — false positive 회피):
#   결정 요청 문구를 anchor 로 항상 요구. 추가로 둘 중 하나 충족 시 발동:
#     (A) 강한 신호: 번호/문자/bullet 옵션 2~4개 나열  (Issue16_3 승격 조건)
#     (B) 약한 신호: 짧은 응답(≤800자) + '?' 종결       (단순 binary confirm)
#   code fence 내부는 분석 제외 (코드 dump false positive 차단).
#
# 이력:
#   - Issue72 (2026-05-20): 초기 도입. Mode B 평문 우회 가드.
#   - Issue749 (2026-09-28): 판정을 lib/decision-question.py 로 추출(봇 질문 중계와 공용) +
#     한 줄 안 `1) … 2) …` 선택지 인식 + pm-do 몸체 예외.

set -u

# prj3#Issue749 — pm-do 가 띄운 `claude -p` 몸체에는 AskUserQuestion 도구가 **없다**(M0 실측: 도구 213개 중 부재).
#   block 하면 없는 도구 재호출을 지시하게 되고, 몸체가 «도구 없음» 으로 이어 말해 2차 Stop 에서 질문을 덮는다.
#   그 몸체의 질문은 fbot-idle.sh → fbot-inbox.py defer 가 의뢰 세션으로 중계한다(같은 판정 함수).
[ "${FPM_SESSION_ORIGIN:-}" = "pm-do" ] && { cat >/dev/null; exit 0; }

. "$HOME/.claude/hooks/hub-scope.sh"
# Issue370: stdin 파싱을 단일 지점으로 — 종전엔 **같은 JSON 을 python3 로 3번** 파싱했다
#   (transcript_path·cwd·stop_hook_active 각 1회). no-op 경로에서도 전부 물어서
#   인터프리터 콜드 스타트를 3배로 냈다. jq 1회면 같은 값을 한 번에 얻는다(F2-1 과 같은 교훈).
# shellcheck source=/dev/null
. "$HOME/.claude/hooks/hook-input.sh"

input=$(< /dev/stdin)   # prj3#Issue921 — cat fork 제거(부하 시 CPU 경합 몫)
hook_input_parse "$input"
transcript_path="${HOOK_TRANSCRIPT:-}"
cwd="${HOOK_CWD:-}"

# Issue283: cwd 스코프 플래그 + effective 재판정 (전역 플래그 세션 간 누수 차단)
FLAG_MODE=$(hub_flag_file "$cwd")
if [ ! -f "$FLAG_MODE" ]; then
  exit 0
fi
if [ "$(hub_effective "$cwd")" = "off" ]; then
  exit 0
fi

# 무한 루프 방지 (Issue370: hook-input 이 "true"/"" 로 정규화해 준다)
if [ "${HOOK_STOP_ACTIVE:-}" = "true" ]; then
  exit 0
fi

if [ -z "$transcript_path" ] || [ ! -f "$transcript_path" ]; then
  exit 0
fi

# 마지막 assistant 텍스트의 평문 결정 질문 판정 — 공용 단일 지점(prj3#Issue749).
#   fbot-inbox.py defer(봇 질문 중계)와 같은 함수다. 휴리스틱을 여기 두면 두 벌이 되어 갈라진다.
verdict=$(python3 "$(dirname "${BASH_SOURCE[0]:-$0}")/lib/decision-question.py" --transcript "$transcript_path" 2>/dev/null)

if [ "$verdict" != "FIRE" ]; then
  exit 0
fi

# decision: block + AskUserQuestion 재호출 지시 주입
python3 <<'PYEOF'
import json
reason = (
    "## hub 모드 활성 — 평문 결정 질문 감지 (Issue72)\n\n"
    "직전 응답이 사용자 결정을 요구하는 질문을 **평문**으로 출력했습니다. "
    "hub Mode B 는 `AskUserQuestion` 도구 호출만 가로채므로, 평문 질문은 "
    "Firefox 폼 자동 회수(Mode B)를 우회합니다.\n\n"
    "### 조치\n"
    "- 동일 결정 질문을 `AskUserQuestion` 도구로 재호출하세요. intercept hook "
    "(`fpm-ask-intercept.sh`)이 자동으로 Firefox 폼 + 서버 회수로 분기합니다.\n"
    "- 옵션은 2~4개로 정리 (5개 이상이면 핵심 4개로 압축).\n"
    "- 단순 confirm(yes/no)도 `AskUserQuestion` 2-option 으로 정형화 권장.\n"
    "- **오탐인 경우**(결정 질문이 아닌 정보성 응답): 질문 표현을 제거하고 "
    "응답을 평서문으로 마무리하세요. AskUserQuestion 강제 아님.\n\n"
    "상세 규칙: `commands/fpm-hub.md` '선택지 자동 승격' 섹션."
)
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
PYEOF

exit 0
