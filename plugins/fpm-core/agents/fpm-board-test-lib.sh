#!/usr/bin/env bash
# fpm-board-test-lib.sh — board L1 단위 테스트 공통 헬퍼 (Issue727, source 전용)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 파일은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/board.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 격리 원칙 — 테스트는 운영 자원을 건드리지 않는다:
#   * 임시 루트 TL_TMP (mktemp) · BOARD_POLICY 는 테스트가 지정한 파일만
#   * hub 는 임의 포트 스텁(hub_stub_start) — 운영 127.0.0.1:9876 무접촉
#   * EXIT trap 이 스텁·자식 프로세스·임시 루트를 정리한다 (실패 경로 포함)

TL_TMP=$(mktemp -d "${TMPDIR:-/tmp}/board-l1.XXXXXX")
TL_PIDS=()
PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
ng() { FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$1"; }
check() { # check <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1"; else ng "$1 (기대 [$2] 실제 [$3])"; fi
}

tl_cleanup() {
  local p
  for p in "${TL_PIDS[@]:-}"; do
    [ -n "$p" ] && kill -TERM "$p" 2>/dev/null
  done
  sleep 0.2
  for p in "${TL_PIDS[@]:-}"; do
    [ -n "$p" ] && kill -KILL "$p" 2>/dev/null
  done
  rm -rf "$TL_TMP"
}
trap tl_cleanup EXIT

tl_track() { TL_PIDS+=("$1"); }

# wait_until <초> <명령...> — 조건이 참이 될 때까지 0.1초 간격 폴링. 시간 초과 시 1
wait_until() {
  local limit=$(( $1 * 10 )) i=0
  shift
  while [ "$i" -lt "$limit" ]; do
    "$@" && return 0
    sleep 0.1
    i=$((i + 1))
  done
  return 1
}

alive() { kill -0 "$1" 2>/dev/null; }
dead() { ! kill -0 "$1" 2>/dev/null; }

# yget <yaml> <python 식(d=문서)> — 값 1개를 문자열로
yget() {
  python3 -c "import yaml,sys; d=yaml.safe_load(open(sys.argv[1])) or {}; v=eval(sys.argv[2]); print('' if v is None else v)" "$1" "$2" 2>/dev/null
}

# hub_stub_start <기록파일> — 임의 포트에 POST 기록 스텁 기동. HUB_STUB_URL 설정
hub_stub_start() {
  local out="$1"
  : > "$out"
  python3 - "$out" <<'PY' &
import http.server, sys
out = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n).decode('utf-8', 'replace')
        with open(out, 'a') as f:
            f.write('%s %s\n' % (self.path, body))
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self, *a):
        pass
s = http.server.HTTPServer(('127.0.0.1', 0), H)
with open(out + '.port', 'w') as f:
    f.write(str(s.server_address[1]))
s.serve_forever()
PY
  tl_track $!
  wait_until 5 test -s "$out.port" || { echo "hub 스텁 기동 실패" >&2; return 1; }
  HUB_STUB_URL="http://127.0.0.1:$(cat "$out.port")"
}
