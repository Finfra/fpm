#!/usr/bin/env bash
# fpm-board-policy.test.sh — board-policy-precedence 회귀 픽스처 (Issue727 · Issue152)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 테스트는 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/board.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 회귀 차단 — (1) 같은 키를 env·board_policy.yml·기본값 셋에 다르게 두면 env > yml > 기본값
#   (supervisor·runner·queue-runner 3종 모두. yml 값 뒤 `# 주석`·공백 허용).
#   (2) 격리 env (Issue727) — FPM_TMP_ROOT 가 yml sentinel_base 보다 우선 · BOARD_TMUX_SOCKET
#   이 supervisor 의 모든 tmux 호출을 전용 서버로 보낸다 · PROJECTS_DIR/FPM_BASE 로 프로젝트
#   맵을 바꾼다. L2 headless 하네스가 운영 tmux·/tmp/___pm 을 건드리지 않기 위한 전제다.
# 실행: bash ~/.claude/agents/fpm-board-policy.test.sh
#   BOARD_SUPERVISOR·BOARD_RUNNER·BOARD_QUEUE_RUNNER 로 대상 스크립트를 바꿀 수 있다 (red 확인용)

set -uo pipefail
SELFDIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SV="${BOARD_SUPERVISOR:-$SELFDIR/fpm-board-supervisor.sh}"
RN="${BOARD_RUNNER:-$SELFDIR/fpm-board-runner.sh}"
QR="${BOARD_QUEUE_RUNNER:-$SELFDIR/fpm-board-queue-runner.sh}"
# shellcheck source=/dev/null
source "$SELFDIR/fpm-board-test-lib.sh"

hub_stub_start "$TL_TMP/hub.log" || exit 1
export BOARD_HUB_URL="$HUB_STUB_URL"

POL="$TL_TMP/policy.yml"
cat > "$POL" <<YAML
# 테스트 정책 — 운영 값과 겹치지 않는 숫자
interval_default: 7        # runner
interval_active: 4
interval_idle_supervisor: 21
interval_idle_runner: 16   # queue-runner
stuck_secs: 42
sentinel_base: $TL_TMP/yml-sentinel
YAML
NOPOL="$TL_TMP/absent.policy.yml"
ISO_VARS=(INTERVAL INTERVAL_ACTIVE INTERVAL_IDLE STUCK_SECS SENTINEL_DIR FPM_TMP_ROOT
          PROJECTS_DIR FPM_BASE BOARD_TMUX_SOCKET SID)

# sv_var <VAR> [KEY=VAL...] — supervisor 를 SELFTEST 로 source 한 뒤 VAR 값을 출력
sv_var() {
  local var="$1"; shift
  (
    unset "${ISO_VARS[@]}"
    export SUPERVISOR_SELFTEST=1 QUEUE_FILE="$TL_TMP/sv/q.yaml" TOPIC=pol BOARD_POLICY="$POL"
    [ $# -gt 0 ] && export "$@"
    mkdir -p "$TL_TMP/sv"
    # shellcheck source=/dev/null
    source "$SV" >/dev/null 2>&1
    printf '%s' "${!var}"
  )
}

echo "[precedence] supervisor"
check "stuck_secs env > yml"       "9"   "$(sv_var STUCK_SECS STUCK_SECS=9)"
check "stuck_secs yml(주석 제거)"  "42"  "$(sv_var STUCK_SECS)"
# 정책 부재 케이스도 FPM_TMP_ROOT 를 묶는다 — 안 묶으면 sentinel 이 기본 /tmp/___pm 로 가고
#   supervisor 가 SELFTEST 반환 전에 mkdir 해 운영 경로에 빈 디렉토리를 남긴다
check "stuck_secs 기본값"          "600" "$(sv_var STUCK_SECS BOARD_POLICY="$NOPOL" FPM_TMP_ROOT="$TL_TMP/deflt")"
check "yml 키 부재 → 기본값"       "2"   "$(sv_var MAX_ATTEMPTS)"
check "interval_idle yml"          "21"  "$(sv_var INTERVAL_IDLE)"

echo "[precedence] sentinel 경로 — SENTINEL_DIR > FPM_TMP_ROOT > yml > /tmp/___pm"
sid=$(python3 -c 'import hashlib,sys; print(hashlib.md5(sys.argv[1].encode()).hexdigest()[:12])' "$TL_TMP/sv/q.yaml")
check "yml sentinel_base"          "$TL_TMP/yml-sentinel/$sid.sentinel" "$(sv_var SENTINEL_DIR)"
check "FPM_TMP_ROOT env > yml"     "$TL_TMP/root/___pm/$sid.sentinel" \
  "$(sv_var SENTINEL_DIR FPM_TMP_ROOT="$TL_TMP/root")"
check "SENTINEL_DIR env 최우선"    "$TL_TMP/explicit" \
  "$(sv_var SENTINEL_DIR SENTINEL_DIR="$TL_TMP/explicit" FPM_TMP_ROOT="$TL_TMP/root")"

echo "[isolation] 프로젝트 맵 경로"
check "PROJECTS_DIR env"           "$TL_TMP/projs"          "$(sv_var PROJECTS_DIR PROJECTS_DIR="$TL_TMP/projs")"
check "FPM_BASE 파생"              "$TL_TMP/base/projects"  "$(sv_var PROJECTS_DIR FPM_BASE="$TL_TMP/base")"

# runner_interval <KEY=VAL...> — runner 기동 로그의 interval= 값 (dead worker → 1 iter 후 종료)
runner_interval() {
  local df="$TL_TMP/rn.dash.yaml" log="$TL_TMP/rn.log" pid
  sleep 0 & local dead_pid=$!; wait "$dead_pid"
  printf 'title: rn\nworker_pid: %s\nwidgets: []\n' "$dead_pid" > "$df"
  (
    unset "${ISO_VARS[@]}"
    export BOARD_POLICY="$POL" DATA_FILE="$df" TOPIC=rn WIN_NAME=_rn
    [ $# -gt 0 ] && export "$@"
    exec bash "$RN"
  ) > "$log" 2>&1 &
  pid=$!; tl_track "$pid"
  wait_until 10 dead "$pid"
  sed -nE 's/.*interval=([^ ]+).*/\1/p' "$log" | head -1
}

echo "[precedence] runner INTERVAL"
check "env > yml"   "3" "$(runner_interval INTERVAL=3)"
check "yml"         "7" "$(runner_interval)"
check "기본값"      "5" "$(runner_interval BOARD_POLICY="$NOPOL")"

# qr_intervals <KEY=VAL...> — queue-runner 기동 로그의 "active/idle" 값 (state=done → 1 iter)
qr_intervals() {
  local qf="$TL_TMP/qr.yaml" log="$TL_TMP/qr.log" pid
  printf 'title: qr\nstate: done\nitems: []\n' > "$qf"
  (
    unset "${ISO_VARS[@]}"
    export BOARD_POLICY="$POL" QUEUE_FILE="$qf" DATA_FILE="$TL_TMP/qr.dash.yaml"
    [ $# -gt 0 ] && export "$@"
    exec bash "$QR"
  ) > "$log" 2>&1 &
  pid=$!; tl_track "$pid"
  wait_until 10 dead "$pid"
  sed -nE 's/.*interval_active=([^ ]+) interval_idle=([^ ]+).*/\1\/\2/p' "$log" | head -1
}

echo "[precedence] queue-runner INTERVAL_ACTIVE/IDLE"
check "env > yml"   "1/2"  "$(qr_intervals INTERVAL_ACTIVE=1 INTERVAL_IDLE=2)"
check "yml"         "4/16" "$(qr_intervals)"
check "기본값"      "3/15" "$(qr_intervals BOARD_POLICY="$NOPOL")"

echo "[isolation] BOARD_TMUX_SOCKET — supervisor 의 tmux 호출이 전용 서버로 간다"
if command -v tmux >/dev/null 2>&1; then
  SOCK="tdd-board-$$"
  PROBE="tdd-probe-$$"
  (
    unset "${ISO_VARS[@]}"
    export SUPERVISOR_SELFTEST=1 QUEUE_FILE="$TL_TMP/sv/q.yaml" TOPIC=pol BOARD_POLICY="$POL" \
      BOARD_TMUX_SOCKET="$SOCK"
    # shellcheck source=/dev/null
    source "$SV" >/dev/null 2>&1
    tmux new-session -d -s "$PROBE" "sleep 30"
  )
  if command tmux -L "$SOCK" has-session -t "$PROBE" 2>/dev/null; then
    ok "전용 소켓 서버에 세션 생성"
  else
    ng "전용 소켓 서버에 세션 없음"
  fi
  if command tmux has-session -t "$PROBE" 2>/dev/null; then
    ng "운영(기본) tmux 서버로 샜음"
    command tmux kill-session -t "$PROBE" 2>/dev/null   # 누수분 회수 (고유 이름이라 안전)
  else
    ok "운영(기본) tmux 서버 무접촉"
  fi
  command tmux -L "$SOCK" kill-server 2>/dev/null
else
  echo "  skip tmux 미설치"
fi

echo "[isolation] 테스트 자신이 운영 sentinel 경로를 남기지 않는다"
if [ -e "/tmp/___pm/$sid.sentinel" ]; then
  ng "/tmp/___pm/$sid.sentinel 생성됨 — 격리 누수"
  rmdir "/tmp/___pm/$sid.sentinel" 2>/dev/null
else
  ok "/tmp/___pm/$sid.sentinel 없음"
fi

echo
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
