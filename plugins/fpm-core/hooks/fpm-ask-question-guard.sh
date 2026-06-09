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
#   - .hub-mode-active 플래그 없음        → exit 0 (평소)
#   - stop_hook_active true               → exit 0 (무한 루프 방지)
#   - Mode D 마커(htm-form:auto:v1) 존재  → exit 0 (Mode D 가 정당 처리)
#   - 직전 assistant 응답이 평문 결정 질문 패턴 매칭
#     → decision:"block" + reason 주입 (AskUserQuestion 재호출 지시)
#
# 탐지 휴리스틱 (보수적 — false positive 회피):
#   결정 요청 문구를 anchor 로 항상 요구. 추가로 둘 중 하나 충족 시 발동:
#     (A) 강한 신호: 번호/문자/bullet 옵션 2~4개 나열  (Issue16_3 승격 조건)
#     (B) 약한 신호: 짧은 응답(≤800자) + '?' 종결       (단순 binary confirm)
#   code fence 내부는 분석 제외 (코드 dump false positive 차단).
#
# 이력:
#   - Issue72 (2026-05-20): 초기 도입. Mode B 평문 우회 가드.

set -u

FLAG_MODE="$HOME/.claude/.hub-mode-active"
if [ ! -f "$FLAG_MODE" ]; then
  exit 0
fi

input=$(cat)

transcript_path=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('transcript_path',''))
except Exception:
    pass" 2>/dev/null)

# 무한 루프 방지
stop_hook_active=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('stop_hook_active', False))
except Exception:
    pass" 2>/dev/null)
if [ "$stop_hook_active" = "True" ] || [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

if [ -z "$transcript_path" ] || [ ! -f "$transcript_path" ]; then
  exit 0
fi

# 마지막 assistant 메시지의 text content 추출 + 평문 결정 질문 패턴 판정
verdict=$(TRANSCRIPT_PATH="$transcript_path" python3 <<'PYEOF' 2>/dev/null
import json, os, re, sys

path = os.environ.get('TRANSCRIPT_PATH', '')
if not path or not os.path.exists(path):
    sys.exit(0)

# transcript JSONL — 마지막 assistant turn 의 text block 만 수집
last_assistant_text = []
try:
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get('type') == 'assistant':
                msg = ev.get('message', {})
                content = msg.get('content', [])
                if isinstance(content, list):
                    txt = [c.get('text', '') for c in content
                           if isinstance(c, dict) and c.get('type') == 'text']
                    if txt:
                        last_assistant_text = txt
except Exception:
    sys.exit(0)

if not last_assistant_text:
    sys.exit(0)

joined = '\n'.join(last_assistant_text)

# Mode D 마커 존재 시 Mode D 가 정당 처리 — 가드 무동작
if 'htm-form:auto:v1:BEGIN' in joined:
    sys.exit(0)

stripped = joined.strip()
if not stripped:
    sys.exit(0)

# code fence 제거 후 분석 (코드 dump false positive 차단)
analysis = re.sub(r'```.*?```', '', stripped, flags=re.DOTALL)
low = analysis.lower()

has_q = ('?' in analysis) or ('？' in analysis)
if not has_q:
    sys.exit(0)

# 결정 요청 문구 (anchor — 항상 필요). htm.md Issue16_3 cond 3 + binary confirm 보강
decision_phrases = [
    '선택해', '선택하세요', '선택할', '어느 옵션', '어느 쪽', '어느 것',
    '어떤 방식', '어떤 걸', '어떤 것', '골라', '번호로', '둘 중', '중 선택',
    'y/n', 'yes/no', 'a/b', '진행할까', '커밋할까', '할까요', '할까?',
    '할까 ', '하시겠', '어떻게 할까', '계속할까', '적용할까', '만들까',
]
has_decision = any(p in low for p in decision_phrases)
if not has_decision:
    sys.exit(0)

# (A) 강한 신호: 옵션 2~4개 나열
opt_lines = re.findall(r'(?m)^\s*(?:\d+[.)]|[A-Da-d][.)]|[-*])\s+\S', analysis)
strong = 2 <= len(opt_lines) <= 4

# (B) 약한 신호: 짧은 응답 + '?' 종결
tail = analysis.rstrip()
ends_q = bool(re.search('[?？]\\s*$', tail))
binary = ends_q and (len(stripped) <= 800)

if not (strong or binary):
    sys.exit(0)

print('FIRE')
PYEOF
)

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
