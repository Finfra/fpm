#!/bin/bash
# hub-session-end.sh — SessionEnd hook: claude 세션 종료를 hub 에 통지 (live 카드 prune 신호)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/_git/___pm/_doc_arch/hub_htm.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue121 [T3]: SessionStart 가 등록한 live 세션을 종료 시 terminal 마킹.
# /session/unregister 전용 엔드포인트가 없으므로 기존 /hook-event 로 event=session_end
# + sid 를 전송 → 서버(prj1 ___pm#Issue98)가 sid 단위 terminal 마킹 또는 TTL prune 에 활용.
# 서버가 session_end 를 아직 처리 안 해도 무해 (활동 피드 1건으로만 적재).

input=$(cat)

read -r SID CWD RSN <<< "$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', ''), d.get('cwd', ''), d.get('reason', ''))
except Exception:
    print('', '', '')
")"

[ -z "$SID" ] && exit 0
[ -z "$CWD" ] && CWD="$PWD"
case "$CWD" in /*) ;; *) exit 0 ;; esac

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
[ "$health" = "200" ] || exit 0

command -v jq >/dev/null 2>&1 || exit 0
curl -s --max-time 2 -X POST "http://127.0.0.1:${SERVER_PORT}/hook-event" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg c "$CWD" --arg sid "$SID" --arg r "$RSN" \
        '{event:"session_end",cwd:$c,sid:$sid,summary:("세션 종료 ("+$r+")"),detail:"",ts:(now|floor)}')" \
  >/dev/null 2>&1 &

exit 0
