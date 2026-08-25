#!/usr/bin/env bash
# fbot-heartbeat.sh — UserPromptSubmit hook 모듈 (matcher: 없음 · dispatch-userpromptsubmit.sh 자식), Issue436_3
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: env **FBOT_ID 가 있고** 직전 heartbeat 로부터 FBOT_HEARTBEAT_SEC(기본 60초)가
#       지났을 때만. lease 를 갱신해 크래시한 봇이 "작업중"으로 영원히 남지 않게 한다
#       (계약 fbot-arch.md §상태 기계 — lease 만료 시 강제 퇴근의 데이터 원천).
# no-op: FBOT_ID 부재(= 일반 세션) → 첫 줄 즉시 exit 0 · 봇이라도 간격 미도래면 stat 1회로 종료.
#
# ⚠️ 이 훅은 **매 턴 차단 경로**(UserPromptSubmit)에 있다. 예산 여유가 가장 적은 자리다
#   (hook-budget.tsv: 200ms 상한, 실측 145~170ms). 그래서 두 겹으로 막는다:
#     ① env 문자열 비교 — 비봇 세션 비용 사실상 0
#     ② mtime 스로틀 — 봇이어도 python3(≈40ms) 기동은 간격당 1회뿐
#   lease TTL(출발값 300초, 계약 🚧)의 1/5 주기라 만료 전에 충분히 갱신된다.
#
# 출력 없음 — 컨텍스트 주입 훅이 아니다. 상태 전이도 하지 않는다(heartbeat 전용).

set -uo pipefail

[ -n "${FBOT_ID:-}" ] || exit 0          # ← 규칙3 무비용 가드

STATE_PY="$HOME/.claude/hooks/fbot-state.py"
[ -f "$STATE_PY" ] || exit 0             # 상태 헬퍼 부재 = 배관 미완 → 조용히 no-op

STAMP_DIR="$HOME/.claude/.fbot-handoff"
STAMP="$STAMP_DIR/$FBOT_ID.hb"
INTERVAL="${FBOT_HEARTBEAT_SEC:-60}"

# 스로틀: 스탬프가 INTERVAL 초 이내면 아무 것도 하지 않는다(자기 상태 파일 — 규칙8 예외)
if [ -f "$STAMP" ]; then
  now=${EPOCHSECONDS:-$(date +%s)}
  # ⚠️ stat 은 쓰지 않는다 — BSD(`-f %m`)와 GNU(`-c %Y`)의 플래그가 반대라, 폴백 체인을
  #   엮으면 실패한 쪽이 stdout 에 부분 출력을 남겨 값이 오염된다(실측: gnubin stat 이
  #   PATH 앞이면 "File: ..." 가 섞여 산술 오류). `date -r` 은 양쪽에서 같은 뜻이다.
  mt=$(date -r "$STAMP" +%s 2>/dev/null || echo 0)
  [ $(( now - mt )) -lt "$INTERVAL" ] && exit 0
fi

mkdir -p "$STAMP_DIR" 2>/dev/null && : > "$STAMP"
python3 "$STATE_PY" heartbeat --bot-id "$FBOT_ID" >/dev/null 2>&1 || true
exit 0
