#!/bin/bash
# fpm-hub-session-register.sh — SessionStart hook: claude 세션을 hub live 카드로 등록
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/_git/___pm/_doc_arch/hub_htm.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue121: hub 📡 활성 세션 카드는 Mode C dashboard 세션만 노출했음. 일반 claude
# 세션(예: tmux pm window 1)을 per-window live 카드로 노출하려면 SessionStart 시점에
# sid + cwd 를 ___pm hub /session/register (content_type=live) 로 등록해야 함.
# hook-feed 는 cwd 단위(sid 없음)라 동일 cwd 다중 window 구분 불가 → sid 등록 필요.
#
# 동작:
#   1. stdin JSON 에서 session_id + cwd + source 추출
#   2. healthz 200 확인 (서버 미기동 → silent exit 0, SessionStart 비블로킹)
#   3. POST /session/register?cwd=<abs> body={sid, content_type:"live", capabilities:{...}}
#   4. fire-and-forget (--max-time 2, 백그라운드) — Claude Code 시작 지연 방지
#
# 서버측 content_type=live liveness 게이트·카드 렌더는 prj1 ___pm#Issue98 소관.
# 본 훅의 POST 는 서버가 live 를 아직 무시해도 무해 (sid entry 등록만 수행).

input=$(cat)

# Issue122: pid 추출 — stdin JSON 의 pid 필드(존재 시) 우선, 없으면 $PPID(훅 부모=claude).
# pid 는 서버(Issue99) live 카드 dedup·liveness(사망 즉시 prune) 권위 신호 — content_type=live 필수.
read -r SID CWD SRC PID_JSON <<< "$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', ''), d.get('cwd', ''), d.get('source', ''), d.get('pid', ''))
except Exception:
    print('', '', '', '')
")"

[ -z "$SID" ] && exit 0

# pid: JSON 값이 있고 정수면 사용, 아니면 훅 부모 pid(=claude 세션) fallback
PID="$PID_JSON"
case "$PID" in ''|*[!0-9]*) PID="$PPID" ;; esac
[ -z "$CWD" ] && CWD="$PWD"
case "$CWD" in /*) ;; *) exit 0 ;; esac   # 절대경로만

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
[ "$health" = "200" ] || exit 0

# tmux window index (가능 시) — 동일 cwd 다중 window 구분용 (Issue122 T3)
# $TMUX 가 훅 env 로 전파되면 정확. 미전파여도 단일 client 면 display-message 가 fallback 으로 동작.
TMUX_WIN=$(tmux display-message -p '#{window_index}' 2>/dev/null)

CWD_ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$CWD")
REG_URL="http://127.0.0.1:${SERVER_PORT}/session/register?cwd=${CWD_ENC}"

# Issue177: 세션 출처 신호 — Claude Code 가 세팅하는 CLAUDE_CODE_ENTRYPOINT
#   (VSCode 확장=claude-vscode, 터미널 CLI=cli). 훅 subprocess env 로 전파됨.
#   서버가 capabilities.entrypoint 로 hub 카드 출처 배지(🆚/⌨️)를 분기.
ENTRY="${CLAUDE_CODE_ENTRYPOINT:-}"

BODY=$(python3 -c "
import json, sys
sid, src, win, pid, entry = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
caps = {'tmux_window': win, 'source': src, 'kind': 'live'}
if entry:
    caps['entrypoint'] = entry   # Issue177: 출처 배지용 (claude-vscode|cli|...)
body = {'sid': sid, 'content_type': 'live', 'capabilities': caps}
try:
    body['pid'] = int(pid)   # Issue122: 서버 계약 pid(int) 필수
except (ValueError, TypeError):
    pass
print(json.dumps(body))
" "$SID" "$SRC" "$TMUX_WIN" "$PID" "$ENTRY")

curl -s --max-time 2 \
  -X POST "$REG_URL" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  >/dev/null 2>&1 &

exit 0
