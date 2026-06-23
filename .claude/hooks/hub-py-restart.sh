#!/bin/bash
# hub-py-restart.sh — services/hub/*.py 편집 시 hub 서버 자동 restart (Issue194 후속)
#
# PostToolUse(Write|Edit|MultiEdit) 에서 호출. stdin = tool 이벤트 JSON.
#   - 편집 파일이 services/hub/*.py 가 아니면 즉시 종료(no-op).
#   - trailing debounce: 연속 편집(버스트)은 마지막 1회만 restart (restart storm·SSE 재연결 폭주 방지).
#   - py_compile 통과 시에만 restart (구문 오류 코드로 살아있는 서버를 죽이지 않음).
#   - 백그라운드 디바운서 → 훅은 즉시 반환(Claude 비차단).

f=$(jq -r '.tool_input.file_path // ""' 2>/dev/null)
case "$f" in
  */services/hub/*.py) ;;
  *) exit 0 ;;
esac

SRV="$HOME/_git/___pm/services/hub/server.py"
STATE=/tmp/___pm/claude-htm-server
mkdir -p "$STATE"

# trailing-edge debounce: 매 편집마다 고유 토큰 기록 → 2s 뒤 내가 여전히 최신이면 restart.
#   버스트 중 이전 디바운서들은 토큰 불일치로 스스로 종료 → 마지막 편집만 1회 restart.
TOKEN="$(date +%s%N)-$$"
echo "$TOKEN" > "$STATE/.restart_token"

(
  sleep 2
  [ "$(cat "$STATE/.restart_token" 2>/dev/null)" = "$TOKEN" ] || exit 0   # 더 최신 편집 있음 → 양보
  if ! python3 -m py_compile "$SRV" 2>"$STATE/py-restart.err"; then
    echo "⚠️ hub server.py 구문 오류 — restart 보류: $(tail -1 "$STATE/py-restart.err")" >&2
    exit 0
  fi
  PID=$(cat "$STATE/pid" 2>/dev/null)
  [ -n "$PID" ] && kill "$PID" 2>/dev/null
  sleep 1
  nohup python3 "$SRV" >"$STATE/stdout.log" 2>&1 &
) >/dev/null 2>&1 &

echo "♻️ hub 서버 restart 예약 (server.py 편집, 2s 디바운스)" >&2
exit 0
