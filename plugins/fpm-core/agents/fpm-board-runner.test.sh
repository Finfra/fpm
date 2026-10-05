#!/usr/bin/env bash
# fpm-board-runner.test.sh — board-runner-pid-guard 회귀 픽스처 (Issue727 · Issue142)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 테스트는 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/board.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 회귀 차단 — (1) worker 없는 보드(infinite heartbeat)는 worker_pid 가 키 부재·null·'None'
#   문자열 어느 쪽이어도 첫 iter 후 status=done 으로 가지 않는다 (Issue142: 과거 'None'
#   으로 읽혀 heartbeat 가 즉시 파괴됨). 대조군 — 살아 있는 worker 는 running 유지, 죽으면 done.
#   (2) 기동 시 register-doc 은 BOARD_HUB_URL 로 간다 — 운영 hub(9876) 무접촉 (Issue727 격리).
# 실행: bash ~/.claude/agents/fpm-board-runner.test.sh
#   BOARD_RUNNER=<경로> 로 대상 스크립트를 바꿀 수 있다 (red 확인용 변형본)

set -uo pipefail
SELFDIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SUT="${BOARD_RUNNER:-$SELFDIR/fpm-board-runner.sh}"
# shellcheck source=/dev/null
source "$SELFDIR/fpm-board-test-lib.sh"

export BOARD_POLICY="$TL_TMP/none.policy.yml"   # 부재 → 스크립트 기본값 (운영 정책 무접촉)
hub_stub_start "$TL_TMP/hub.log" || exit 1
export BOARD_HUB_URL="$HUB_STUB_URL"
unset INTERVAL

# start_runner <name> <worker_pid 줄(빈 문자열이면 키 부재)> — RUNNER_PID·DF 설정
start_runner() {
  local name="$1" wline="$2"
  DF="$TL_TMP/$name.dash.yaml"
  {
    echo "title: $name"
    echo "status: init"
    [ -n "$wline" ] && echo "$wline"
    echo "widgets:"
    echo "- id: tick"
    echo "  type: text"
    echo "  dynamic_eval: \"echo x >> $TL_TMP/$name.iter; echo ok\""
  } > "$DF"
  DATA_FILE="$DF" TOPIC="$name" WIN_NAME="_$name" INTERVAL=0.2 \
    bash "$SUT" > "$TL_TMP/$name.log" 2>&1 &
  RUNNER_PID=$!
  tl_track "$RUNNER_PID"
}
iters() { [ -f "$TL_TMP/$1.iter" ] && wc -l < "$TL_TMP/$1.iter" | tr -d ' ' || echo 0; }
iters_ge() { [ "$(iters "$1")" -ge "$2" ]; }
# running_now — runner 생존 + status=running. 러너 write_data 는 truncate 후 쓰므로 iter 직후
#   단발 읽기는 빈 파일을 볼 수 있다(Issue804 플래키) → 판정은 wait_until 로 폴링한다
running_now() { alive "$RUNNER_PID" && [ "$(yget "$DF" "d.get('status')")" = "running" ]; }

# ── (1) worker 없는 보드 3표본 — 3 iter 이상 돌고도 running 이어야 한다 ──
echo "[pid-guard] worker 없는 보드는 heartbeat 를 유지한다"
for sample in "absent|" "null|worker_pid: null" "None|worker_pid: None"; do
  name="hb-${sample%%|*}"
  start_runner "$name" "${sample#*|}"
  wait_until 10 iters_ge "$name" 3
  if wait_until 3 running_now; then
    ok "$name → iter $(iters "$name") 후에도 running"
  else
    ng "$name → heartbeat 파괴 (iter $(iters "$name"), status=$(yget "$DF" "d.get('status')"))"
  fi
  kill -TERM "$RUNNER_PID" 2>/dev/null
  wait_until 5 dead "$RUNNER_PID"
  check "$name → TERM 후 stopped" "stopped" "$(yget "$DF" "d.get('status')")"
done

# ── 대조군 — worker_pid 가 실제 PID 면 생존 감시가 동작해야 한다 ──
echo "[pid-guard] 대조군 — 실 worker 생존 감시"
sleep 30 & WORKER=$!
tl_track "$WORKER"
start_runner "live" "worker_pid: $WORKER"
wait_until 10 iters_ge live 2
if wait_until 3 running_now; then
  ok "live worker → running"
else
  ng "live worker → running (status=$(yget "$DF" "d.get('status')"))"
fi
kill -KILL "$WORKER" 2>/dev/null; wait "$WORKER" 2>/dev/null
if wait_until 5 dead "$RUNNER_PID"; then
  check "worker 사망 → done" "done" "$(yget "$DF" "d.get('status')")"
else
  ng "worker 사망 후에도 runner 가 종료하지 않음"
fi

# ── (2) register-doc 은 BOARD_HUB_URL 로 간다 ──
echo "[isolation] hub 등록 경로"
if grep -q "^/register-doc .*hb-absent.dash.yaml" "$TL_TMP/hub.log"; then
  ok "register-doc → 주입한 BOARD_HUB_URL 스텁 수신"
else
  ng "register-doc 이 BOARD_HUB_URL 로 오지 않음 (운영 hub 로 샜을 수 있음)"
fi

echo
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
