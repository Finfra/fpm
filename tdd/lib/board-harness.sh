#!/usr/bin/env bash
# board-harness.sh — board L2 headless 시나리오 격리 하네스 (Issue544 M2-1, source 전용)
#
# 설계: _doc_arch/board-scenario-kit.md "자동 검증 (TDD) — 3층 구조" · 격리 env 계약은
#   prj3 _doc_arch/board.md "격리 env (prj3#Issue727)"
#
# 격리가 전제다 — L2 는 운영 tmux·hub·임시 경로를 절대 건드리지 않는다:
#   * tmux     : 전용 소켓 BOARD_TMUX_SOCKET(`tmux -L`) — supervisor 가 모든 tmux 호출을 이 소켓으로 보낸다
#   * 임시 경로 : FPM_TMP_ROOT = 케이스 임시 루트 안 (sentinel 이 운영 /tmp/___pm 에 생기지 않는다)
#   * hub      : BOARD_HUB_URL = 임의 포트 스텁 (운영 9876 무접촉 — 등록 요청은 스텁이 받아 기록한다)
#   * 정책     : BOARD_POLICY = 존재하지 않는 경로 → 스크립트 기본값 (운영 board_policy.yml 무접촉)
#   * prj 맵   : PROJECTS_DIR = 임시 루트 안 (worker cwd 가 실 프로젝트가 되지 않는다)
# 위 중 하나라도 운영 값을 가리키면 bh_guard 가 즉시 abort 한다. teardown 은 EXIT trap —
#   실패 경로에서도 스텁·daemon·tmux 서버·임시 루트를 정리한다.
#
# 대상 스크립트: 기본은 이 repo 의 번들 사본(plugins/fpm-core/agents). BOARD_AGENTS_DIR 로
#   바꿀 수 있다 — red 확인용 변형본을 가리킬 때 쓴다.

BH_REPO="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BH_AGENTS="${BOARD_AGENTS_DIR:-$BH_REPO/plugins/fpm-core/agents}"
BH_FIX="$BH_REPO/tdd/fixtures/board"
BH_PIDS=()
BH_TOPICS=()
BH_FAILS=0
BH_ROOT=""

bh_skip()  { echo "skip $*"; exit 0; }
bh_abort() { echo "ABORT(격리 위반) $*"; exit 3; }
bh_ok()    { printf '  ok   %s\n' "$1"; }
bh_ng()    { printf '  FAIL %s\n' "$1"; BH_FAILS=$((BH_FAILS + 1)); }
bh_check() { # bh_check <desc> <기대> <실제>
  if [ "$2" = "$3" ]; then bh_ok "$1"; else bh_ng "$1 (기대 [$2] 실제 [$3])"; fi
}
bh_true()  { # bh_true <desc> <명령...>
  local d="$1"; shift
  if "$@"; then bh_ok "$d"; else bh_ng "$d"; fi
}

# 판정 결과 한 줄 — run-tdd.sh 는 `contains:ok:<case>` 로 본다
bh_finish() {
  bh_assert_no_leak
  if [ "$BH_FAILS" -eq 0 ]; then echo "ok:$BH_CASE"; exit 0; fi
  echo "FAIL:$BH_CASE (${BH_FAILS}건)"; exit 1
}

# ── 전제 — 이 머신이 board 를 돌릴 수 있는가 (역할이 아니면 skip) ──────────
bh_require() {
  command -v tmux >/dev/null 2>&1 || bh_skip "tmux 없음 — board 는 tmux 기반이라 이 머신의 역할이 아니다"
  local bv
  bv=$(bash -c 'echo "${BASH_VERSINFO[0]}"')
  [ "${bv:-0}" -ge 4 ] || bh_skip "PATH 의 bash 가 $bv — supervisor 는 bash 4+ 필요"
  python3 -c 'import yaml' >/dev/null 2>&1 || bh_skip "python3 pyyaml 없음 — board 스크립트 전제"
  [ -f "$BH_AGENTS/fpm-board-supervisor.sh" ] || bh_skip "board 스크립트 부재: $BH_AGENTS"
}

# disown — teardown 의 강제 종료가 "Killed: 9" 작업 제어 메시지로 출력을 오염시키지 않게
bh_track() { BH_PIDS+=("$1"); disown "$1" 2>/dev/null || true; }

bh_teardown() {
  local p
  for p in "${BH_PIDS[@]}"; do kill -TERM "$p" 2>/dev/null; done
  # supervisor 는 TERM 을 sleep 이 끝난 뒤 처리한다 — 최대 2초 기다린 뒤 남은 것만 KILL
  local i=0 alive
  while [ "$i" -lt 10 ]; do
    alive=0
    for p in "${BH_PIDS[@]}"; do kill -0 "$p" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 0.2; i=$((i + 1))
  done
  for p in "${BH_PIDS[@]}"; do kill -KILL "$p" 2>/dev/null; done
  [ -n "${BOARD_TMUX_SOCKET:-}" ] && command tmux -L "$BOARD_TMUX_SOCKET" kill-server 2>/dev/null
  # tmux 3.7 은 kill-server 뒤에도 소켓 파일을 남긴다 — 하네스가 만든 이름일 때만 지운다
  case "${BH_SOCK_PATH:-}" in */tdd-board-*) rm -f "$BH_SOCK_PATH" ;; esac
  if [ -n "$BH_ROOT" ] && [ -d "$BH_ROOT" ]; then
    if [ "${BH_KEEP:-0}" = 1 ]; then echo "  (BH_KEEP=1 — 임시 루트 보존: $BH_ROOT)" >&2
    else rm -rf "$BH_ROOT"; fi
  fi
}

# 임의 포트 hub 스텁 — POST 본문을 기록한다. 운영 9876 대신 이것이 register-doc 을 받는다
bh_hub_stub() {
  local out="$BH_ROOT/hub-stub.log"
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
  bh_track $!
  bh_wait 5 test -s "$out.port" || { bh_ng "hub 스텁 기동 실패"; return 1; }
  export BOARD_HUB_URL="http://127.0.0.1:$(cat "$out.port")"
}

bh_guard() {
  case "${BOARD_TMUX_SOCKET:-}" in ''|default) bh_abort "tmux 소켓이 운영 기본 서버" ;; esac
  case "${FPM_TMP_ROOT:-}" in "$BH_ROOT"/*) ;; *) bh_abort "FPM_TMP_ROOT 가 임시 루트 밖: ${FPM_TMP_ROOT:-<빈값>}" ;; esac
  case "${BOARD_POLICY:-}" in "$BH_ROOT"/*) ;; *) bh_abort "BOARD_POLICY 가 임시 루트 밖" ;; esac
  case "${PROJECTS_DIR:-}" in "$BH_ROOT"/*) ;; *) bh_abort "PROJECTS_DIR 가 임시 루트 밖" ;; esac
  case "${BOARD_HUB_URL:-}" in
    http://127.0.0.1:9876*|http://localhost:9876*|'') bh_abort "hub URL 이 운영 포트 또는 미지정: ${BOARD_HUB_URL:-<빈값>}" ;;
  esac
}

# bh_setup <case-id> — 격리 환경 구성. 이후 모든 board 스크립트는 이 env 를 상속한다
bh_setup() {
  BH_CASE="$1"
  bh_require
  unset TMUX TMUX_PANE
  BH_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/board-l2.XXXXXX") || { echo "FAIL: mktemp"; exit 1; }
  BH_ROOT=$(cd "$BH_ROOT" && pwd -P)      # macOS /var → /private/var — 경로 비교를 실경로로
  trap bh_teardown EXIT
  export FPM_TMP_ROOT="$BH_ROOT/tmp"
  export BOARD_TMUX_SOCKET="tdd-board-$$"
  export BOARD_POLICY="$BH_ROOT/absent.policy.yml"
  export PROJECTS_DIR="$BH_ROOT/projects"
  export FAKE_TRACE="$BH_ROOT/trace.log"
  export FPM_BASE="$BH_ROOT"               # 스크립트의 $FPM_BASE 파생 기본값도 임시 루트로
  mkdir -p "$FPM_TMP_ROOT" "$PROJECTS_DIR"
  : > "$FAKE_TRACE"
  bh_hub_stub || exit 1
  bh_guard
  # 사용자 ~/.tmux.conf·셸 rc 를 싣지 않는다 — worker pane 은 깨끗한 bash
  command tmux -L "$BOARD_TMUX_SOCKET" -f /dev/null new-session -d -s tdd -n main -x 240 -y 80 \
    || { echo "FAIL: 격리 tmux 서버 기동 실패"; exit 1; }
  command tmux -L "$BOARD_TMUX_SOCKET" set-option -g default-command "bash --noprofile --norc" >/dev/null
  BH_SOCK_PATH=$(command tmux -L "$BOARD_TMUX_SOCKET" display-message -p '#{socket_path}' 2>/dev/null)
}

# bh_prj <번호...> — prj 번호 → 임시 작업 폴더 매핑
bh_prj() {
  local n
  for n in "$@"; do
    mkdir -p "$BH_ROOT/w/$n"
    printf '%s\n' "$BH_ROOT/w/$n" > "$PROJECTS_DIR/$n"
  done
}

# bh_fixture <fixture> <dest> — @ROOT@·@WORKER_PID@ 자리 채움
bh_fixture() {
  sed -e "s|@ROOT@|$BH_ROOT|g" -e "s|@WORKER_PID@|${BH_WORKER_PID:-}|g" "$BH_FIX/$1" > "$2"
}

# bh_wait <초> <명령...> — 참이 될 때까지 0.2초 간격 폴링. 시간 초과 시 1
bh_wait() {
  local limit=$(( $1 * 5 )) i=0
  shift
  while [ "$i" -lt "$limit" ]; do
    "$@" && return 0
    sleep 0.2
    i=$((i + 1))
  done
  return 1
}

# bh_yget <yaml> <python 식(d=문서)> — 값 1개를 문자열로
#   ⚠️ runner·queue-runner 는 dash.yaml 을 원자적으로 쓰지 않는다(`>` 리다이렉트·open('w') — 비우고
#   다시 씀). 쓰는 순간 읽으면 빈 문서가 보이므로, 빈 문서·파싱 실패는 짧게 재시도한다.
#   유효한 board 파일은 비어 있을 수 없어 재시도가 진짜 결함을 가리지 않는다.
bh_yget() {
  python3 -c "import yaml,sys,json,time
d = {}
for _ in range(20):
    try:
        d = yaml.safe_load(open(sys.argv[1])) or {}
    except Exception:
        d = {}
    if d:
        break
    time.sleep(0.05)
v=eval(sys.argv[2])
print('' if v is None else (json.dumps(v, ensure_ascii=False) if isinstance(v,(list,dict)) else v))" "$1" "$2" 2>/dev/null
}

# ── 큐 모드 기동 — supervisor(+ queue-runner) 를 격리 소켓의 전용 window 에 붙인다 ──
# bh_queue <fixture> <topic> [runner] — 호출 전에 export 한 env(STUCK_SECS 등)가 전달된다
#   worker 는 기본 합성 worker. BH_WORKER_CMD= (빈 값)이면 supervisor 기본값 = 실 claude (L3 전용)
bh_queue() {
  local fx="$1" topic="$2" with_runner="${3:-}"
  local qf="$BH_ROOT/$topic.queue.yaml"
  bh_fixture "$fx" "$qf"
  BH_TOPICS+=("$topic")
  command tmux -L "$BOARD_TMUX_SOCKET" new-window -d -t tdd -n "dash-$topic"
  QUEUE_FILE="$qf" TOPIC="$topic" SESSION=tdd WINDOW="dash-$topic" \
    WORKER_CMD="${BH_WORKER_CMD-bash $BH_FIX/fake-worker.sh}" \
    INTERVAL_ACTIVE="${INTERVAL_ACTIVE:-0.5}" INTERVAL_IDLE="${INTERVAL_IDLE:-0.5}" \
    bash "$BH_AGENTS/fpm-board-supervisor.sh" > "$BH_ROOT/$topic.sup.out" 2>&1 &
  bh_track $!
  if [ "$with_runner" = runner ]; then
    QUEUE_FILE="$qf" DATA_FILE="$BH_ROOT/$topic.dash.yaml" \
      SUPERVISOR_LOG="$BH_ROOT/$topic.supervisor.log" WIN_NAME="dash-$topic" \
      INTERVAL_ACTIVE=0.5 INTERVAL_IDLE=0.5 \
      bash "$BH_AGENTS/fpm-board-queue-runner.sh" > "$BH_ROOT/$topic.qr.out" 2>&1 &
    bh_track $!
  fi
}

bh_status_is() { [ "$(bh_yget "$1" "d.get('status')")" = "$2" ]; }
bh_item_is()   { [ "$(bh_item "$1" "$2" "$3")" = "$4" ]; }
bh_stuck_set() { [ -n "$(bh_yget "$BH_ROOT/$1.queue.yaml" "d.get('stuck_since')")" ]; }
bh_qstate()   { bh_yget "$BH_ROOT/$1.queue.yaml" "d.get('state')"; }
bh_qdone()    { [ "$(bh_qstate "$1")" = done ]; }
bh_item()     { bh_yget "$BH_ROOT/$1.queue.yaml" "{i['id']:i for i in d.get('items',[])}['$2'].get('$3')"; }

# 추적 로그 → 항목별 [start, end] 구간
bh_trace_py() {
  python3 - "$FAKE_TRACE" "$@" <<'PY'
import sys
tr, op = sys.argv[1], sys.argv[2]
args = sys.argv[3:]
st, en = {}, {}
for line in open(tr):
    p = line.split()
    if len(p) != 3:
        continue
    t, kind, i = float(p[0]), p[1], p[2]
    (st if kind == 'start' else en).setdefault(i, t)
if op == 'order':          # order <id...> — 주어진 순서대로 앞 항목 end ≤ 뒤 항목 start
    ok = all(i in st and i in en for i in args) and \
         all(en[a] <= st[b] for a, b in zip(args, args[1:]))
    print('yes' if ok else 'no')
elif op == 'after':        # after <뒤> <앞...> — 뒤 항목 start ≥ 모든 앞 항목 end
    b, prev = args[0], args[1:]
    print('yes' if b in st and all(a in en and en[a] <= st[b] for a in prev) else 'no')
elif op == 'maxconc':      # 동시 실행 최대 수
    ev = sorted([(t, 1) for t in st.values()] + [(t, -1) for t in en.values()],
                key=lambda x: (x[0], x[1]))
    cur = mx = 0
    for _, d in ev:
        cur += d
        mx = max(mx, cur)
    print(mx)
elif op == 'started':
    print(' '.join(sorted(st, key=st.get)))
PY
}

# 위젯 레이아웃 규칙 — board-scenario-kit.md "위젯 레이아웃 규칙 (검증 도출)" 표가 기대값
#   graph/dag/tree → width ≥ 2 · log → width full · table → 2 또는 full · 로그 성격 위젯은 type log
bh_layout_violations() {
  python3 - "$1" <<'PY'
import sys, yaml, time
d = {}
for _ in range(20):          # 비원자 쓰기 중 빈 문서 재시도 (bh_yget 주석 참조)
    try:
        d = yaml.safe_load(open(sys.argv[1])) or {}
    except Exception:
        d = {}
    if d:
        break
    time.sleep(0.05)
bad = [] if d.get('widgets') else ['위젯 0개 — 빈 문서를 «위반 없음» 으로 통과시키지 않는다']
for w in d.get('widgets', []):
    t, wd, wid = w.get('type'), w.get('width', 1), str(w.get('id', ''))
    wide = wd == 'full' or (isinstance(wd, int) and wd >= 2)
    if t in ('graph', 'dag', 'tree') and not wide:
        bad.append('%s: %s 인데 width=%s' % (wid, t, wd))
    if t == 'log' and wd != 'full':
        bad.append('%s: log 인데 width=%s' % (wid, wd))
    if t == 'table' and wd not in (2, 'full'):
        bad.append('%s: table 인데 width=%s' % (wid, wd))
    if t == 'text' and 'log' in wid:
        bad.append('%s: 로그가 type text' % wid)
print('; '.join(bad))
PY
}

# ── 무접촉 음성 검증 (M2-8) — 모든 케이스가 끝에서 부른다 ──────────────────
#   ① 운영 tmux(기본 서버)에 이 케이스의 window 가 없다
#   ② 운영 sentinel 루트(/tmp/___pm)에 이 케이스 큐의 sentinel 디렉토리가 없다
#   ③ 운영 hub 등록부에 이 케이스 임시 루트 경로가 없다
#   ④ 기동 등록(register-doc)은 스텁이 받았다 — 등록 경로가 격리 URL 로 갔다는 양성 증거
bh_assert_no_leak() {
  local t sid wins reg
  wins=$(command tmux list-windows -a -F '#{window_name}' 2>/dev/null)
  for t in "${BH_TOPICS[@]}"; do
    case "$wins" in *"dash-$t"*) bh_ng "무접촉 ①: 운영 tmux 에 dash-$t window 가 생겼다" ;; esac
    sid=$(python3 -c 'import hashlib,sys; print(hashlib.md5(sys.argv[1].encode()).hexdigest()[:12])' "$BH_ROOT/$t.queue.yaml")
    [ -e "/tmp/___pm/$sid.sentinel" ] && bh_ng "무접촉 ②: 운영 /tmp/___pm/$sid.sentinel 생성"
  done
  reg="$BH_REPO/data/hub/dash-registry.json"
  if [ -f "$reg" ] && grep -qF "$BH_ROOT" "$reg"; then bh_ng "무접촉 ③: 운영 hub 등록부에 임시 루트 경로"; fi
  if [ "${BH_EXPECT_REGISTER:-0}" = 1 ]; then
    grep -q '/register-doc' "$BH_ROOT/hub-stub.log" 2>/dev/null \
      || bh_ng "무접촉 ④: register-doc 이 스텁에 도착하지 않았다(격리 URL 미사용 의심)"
  fi
  [ "$BH_FAILS" -eq 0 ] && bh_ok "무접촉 — 운영 tmux·sentinel·hub 등록부 무변화"
}
