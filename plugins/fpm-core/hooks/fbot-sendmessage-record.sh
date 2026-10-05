#!/usr/bin/env bash
# fbot-sendmessage-record.sh — PostToolUse hook (matcher: SendMessage), prj3#Issue739 M1-3
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 왜 (설계 fbot-org §이슈 축 연동 결정 2): `SendMessage` 로 넘긴 지시는 사후 `dispatch-record` 를 잊으면 원장에
#   영구 누락된다 — 캐스케이드·이슈맵·봇 카드가 모두 원장을 읽는데 그 자리가 빈다.
# 발동: 전송 성공(`"success": true`) + 본문에 이슈 식별자(`Issue<N>`) 또는 `[지시]` → `fbot-state.py sendmessage-record`
#   (판정 단일 지점 — 송신·수신·지시형 3조건, 보고 방향 제외, 기록은 dispatch-record 재사용). 판정 불가 지시형은
#   additionalContext 1줄(원장 오염이 공백보다 비싸다 — 적지 않고 알린다)
#   단 송신·수신 양쪽 다 봇이 아니면 알림도 없다(Issue806 — 비봇 세션 간 대화 오탐, 판정은 fbot-state.py 단일 지점)
# no-op: 지시형 아님·전송 실패 (fork 0회 — 문자열 판정만) · 상태 헬퍼 부재
#
# sync — 알림(additionalContext)을 소비하므로 async 로 둘 수 없다. 기록 성공은 조용히 끝난다. 실패는 fail-soft.
set -uo pipefail

input=$(cat)
case "$input" in
  *Issue[0-9]*|*'[지시]'*) ;;
  *) exit 0 ;;
esac
[[ "$input" =~ \"success\"[[:space:]]*:[[:space:]]*true ]] || exit 0

STATE_PY="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/fbot-state.py"
[ -f "$STATE_PY" ] || exit 0

out=$(printf '%s' "$input" | python3 "$STATE_PY" sendmessage-record 2>/dev/null) || exit 0
printf '%s' "$out" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
n = d.get("notice")
if n:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": n}}, ensure_ascii=False))
' 2>/dev/null
exit 0
