#!/usr/bin/env bash
# board-cases.sh — board L2 headless 시나리오 케이스 (Issue544 M2-3~6)
#
# 사용: bash tdd/lib/board-cases.sh <case-id>      (tdd/cases/board.yml 이 부른다)
#       bash tdd/lib/board-cases.sh --all [--serial] (전 케이스 — 기본 병렬)
# 출력: 마지막 줄 `ok:<case-id>` = 통과 / `FAIL:<case-id>` / `skip <사유>`
#
# 판정 한 줄: 시나리오는 fixture 이고, 테스트는 그 fixture 가 만드는 **상태 전이**를 단언한다.
#   브라우저 렌더가 아니라 dash.yaml·queue.yaml·추적 로그를 본다(열린 질문 5 → (b) dash.yaml 직접).
# 시간 단언은 상한으로만 쓴다 — 판정은 상태 전이·순서·iter 수로 한다(flaky 회피).

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/board-harness.sh"

# ── s1 대량 순차 파일 생성 — 순수 모니터링 runner + 합성 worker 완주 ──────────
case_s1_complete() {
  bh_setup board-s1-complete
  mkdir -p "$BH_ROOT/out"
  # 합성 worker: 파일 10개 생성 후 1.5초 더 산다 — runner 가 완료 직후 값을 최소 1회 평가하게
  ( for i in 1 2 3 4 5 6 7 8 9 10; do : > "$BH_ROOT/out/f$i"; sleep 0.1; done; sleep 1.5 ) &
  BH_WORKER_PID=$!; bh_track "$BH_WORKER_PID"
  local df="$BH_ROOT/s1.dash.yaml"
  bh_fixture s1-build.dash.yaml "$df"
  DATA_FILE="$df" TOPIC=s1 WIN_NAME=_s1 INTERVAL=0.3 \
    bash "$BH_AGENTS/fpm-board-runner.sh" > "$BH_ROOT/s1.runner.out" 2>&1 &
  local rp=$!; bh_track "$rp"
  bh_true "worker 종료 후 runner 가 status=done 으로 마감" \
    bh_wait 15 bh_status_is "$df" done
  bh_check "progress 100 (완주 값)" 100 "$(bh_yget "$df" "[w for w in d['widgets'] if w['id']=='progress'][0].get('value')")"
  bh_check "생성 수 10" 10 "$(bh_yget "$df" "[w for w in d['widgets'] if w['id']=='count'][0].get('value')")"
  bh_true "runner 는 done 마감 후 스스로 종료" bh_wait 5 bh_dead "$rp"
  BH_EXPECT_REGISTER=1
  bh_finish
}

# ── s2 크로스 프로젝트 위임 — DAG fan-out/fan-in 순서 ────────────────────────
case_s2_dag_order() {
  bh_setup board-s2-dag-order
  bh_prj 1 2 3
  bh_queue s2-dag.queue.yaml s2dag
  bh_true "큐 완주 (state=done)" bh_wait 60 bh_qdone s2dag
  bh_check "b 는 a 완료 뒤 시작" yes "$(bh_trace_py after b a)"
  bh_check "c 는 a 완료 뒤 시작" yes "$(bh_trace_py after c a)"
  bh_check "d(fan-in)는 b·c 둘 다 완료 뒤 시작" yes "$(bh_trace_py after d b c)"
  bh_check "전 항목 done" "done done done done" \
    "$(bh_yget "$BH_ROOT/s2dag.queue.yaml" "' '.join(i['status'] for i in d['items'])")"
  bh_check "d 결과가 sentinel 요약(ok-d)으로 기록" ok-d "$(bh_item s2dag d result)"
  bh_finish
}

# ── s4·s5 선형 파이프라인 — 선언 순서가 아니라 depends 순서 + 완주 후 레이아웃 ──
case_s4_linear_queue() {
  bh_setup board-s4-linear-queue
  bh_prj 1 2
  bh_queue s4-pipeline.queue.yaml s4pipe runner
  bh_queue s5-goal.queue.yaml s5goal
  bh_true "s4 6단계 완주" bh_wait 90 bh_qdone s4pipe
  bh_true "s5 3단계 완주" bh_wait 30 bh_qdone s5goal
  bh_check "s4 실행 순서 = depends 순서(선언 순서 무관)" yes \
    "$(bh_trace_py order p1-needs p2-brief p3-plan p4-task p5-verify p6-report)"
  bh_check "s5 마일스톤 순서" yes "$(bh_trace_py order m1 m2 m3)"
  local df="$BH_ROOT/s4pipe.dash.yaml"
  bh_true "queue-runner 가 완주 후 status=done 마감" \
    bh_wait 15 bh_status_is "$df" done
  bh_check "완주 후 progress 100" 100 "$(bh_yget "$df" "[w for w in d['widgets'] if w['id']=='queue-progress'][0].get('value')")"
  bh_check "완주 후 레이아웃 규칙 위반 0" "" "$(bh_layout_violations "$df")"
  BH_EXPECT_REGISTER=1
  bh_finish
}

# ── s6 Task 병렬 — 실동시 running 최대 = min(concurrency, prj 종수) ─────────────
case_s6_concurrency() {
  bh_setup board-s6-concurrency
  bh_prj 1 2
  bh_queue s6-parallel.queue.yaml s6par
  bh_true "큐 완주" bh_wait 60 bh_qdone s6par
  bh_check "실동시 최대 = min(concurrency 3, prj 2종) = 2" 2 "$(bh_trace_py maxconc)"
  bh_check "4항목 전부 done" "done done done done" \
    "$(bh_yget "$BH_ROOT/s6par.queue.yaml" "' '.join(i['status'] for i in d['items'])")"
  bh_finish
}

# ── s7·s8 infinite heartbeat — N iter 후에도 done 아님, stop 으로만 정지 ─────
case_s7_heartbeat_alive() {
  bh_setup board-s7-heartbeat-alive
  local n pids=() df
  for n in s7-health s8-schedule; do
    df="$BH_ROOT/$n.dash.yaml"
    bh_fixture "$n.dash.yaml" "$df"
    DATA_FILE="$df" TOPIC="$n" WIN_NAME="_$n" INTERVAL=0.2 \
      bash "$BH_AGENTS/fpm-board-runner.sh" > "$BH_ROOT/$n.runner.out" 2>&1 &
    pids+=("$!"); bh_track "$!"
  done
  bh_true "s7 heartbeat 5 iter 이상" bh_wait 15 bh_ticks_ge s7 5
  bh_true "s8 heartbeat 5 iter 이상" bh_wait 15 bh_ticks_ge s8 5
  bh_check "s7 5 iter 후에도 running" running "$(bh_yget "$BH_ROOT/s7-health.dash.yaml" "d.get('status')")"
  bh_check "s8 5 iter 후에도 running" running "$(bh_yget "$BH_ROOT/s8-schedule.dash.yaml" "d.get('status')")"
  bh_check "s8 table 행이 매 iter 갱신(dynamic_eval)" yes \
    "$(bh_yget "$BH_ROOT/s8-schedule.dash.yaml" "'yes' if 'backup' in str([w for w in d['widgets'] if w['id']=='schedule'][0].get('value')) else 'no'")"
  kill -TERM "${pids[0]}" "${pids[1]}" 2>/dev/null
  bh_true "stop(TERM) 후 s7 status=stopped" \
    bh_wait 5 bh_status_is "$BH_ROOT/s7-health.dash.yaml" stopped
  bh_true "stop(TERM) 후 s8 status=stopped" \
    bh_wait 5 bh_status_is "$BH_ROOT/s8-schedule.dash.yaml" stopped
  BH_EXPECT_REGISTER=1
  bh_finish
}

# ── 공통 — sentinel DONE 기록 → 다음 iter 에 완료 감지 ─────────────────────
case_sentinel_done() {
  bh_setup board-sentinel-done
  bh_prj 1
  export MAX_ATTEMPTS=1
  bh_queue sentinel.queue.yaml sent
  bh_true "항목이 running 으로 디스패치" bh_wait 20 bh_item_is sent ok1 status running
  bh_true "worker 가 sentinel 없이 idle 복귀(manual)" bh_wait 10 bh_trace_has end ok1
  local sid sdir
  sid=$(python3 -c 'import hashlib,sys; print(hashlib.md5(sys.argv[1].encode()).hexdigest()[:12])' "$BH_ROOT/sent.queue.yaml")
  sdir="$FPM_TMP_ROOT/___pm/$sid.sentinel"
  bh_true "sentinel 디렉토리가 격리 임시 루트 안에 있다" test -d "$sdir"
  printf 'DONE\t0\tmanual-result\n' > "$sdir/sent.ok1.done"
  bh_true "sentinel 기록 → done 감지" bh_wait 10 bh_item_is sent ok1 status done
  bh_check "rc 0 기록" 0 "$(bh_item sent ok1 rc)"
  bh_check "result 가 sentinel 요약" manual-result "$(bh_item sent ok1 result)"
  bh_true "소비한 sentinel 파일은 제거(재오감지 차단)" test ! -e "$sdir/sent.ok1.done"
  bh_true "큐 state=done" bh_wait 10 bh_qdone sent
  bh_finish
}

# ── 공통 — 상태 변화 0 이 STUCK_SECS 지속 → stuck 자가 진단 ────────────────
case_stuck_detect() {
  bh_setup board-stuck-detect
  bh_prj 1
  export STUCK_SECS=3 NOSENT_STRIKES=1000
  bh_queue stuck.queue.yaml stk runner
  bh_true "항목 running (worker hang)" bh_wait 20 bh_item_is stk h1 status running
  bh_true "STUCK_SECS 경과 후 queue.yaml stuck_since 기록" \
    bh_wait 15 bh_stuck_set stk
  bh_true "dash 배지가 error + STUCK 표기" bh_wait 10 bh_stuck_badge
  bh_check "stuck 이어도 항목은 done 으로 위장되지 않음" running "$(bh_item stk h1 status)"
  BH_EXPECT_REGISTER=1
  bh_finish
}

# ── s3·s8·s9 렌더 비중 위젯 — runner 왕복 후 authoring(type·width) 보존 + 규칙 ─
case_hub_json_widgets() {
  bh_setup board-hub-json-widgets
  local n df
  for n in s3-tree s8-schedule s9-transfer; do
    df="$BH_ROOT/$n.dash.yaml"
    bh_fixture "$n.dash.yaml" "$df"
    cp "$df" "$df.orig"
    DATA_FILE="$df" TOPIC="$n" WIN_NAME="_$n" INTERVAL=0.2 \
      bash "$BH_AGENTS/fpm-board-runner.sh" > "$BH_ROOT/$n.runner.out" 2>&1 &
    bh_track "$!"
  done
  bh_true "runner 3종 모두 2 iter 이상 기록(pid·status 주입)" bh_wait 10 bh_all_running s3-tree s8-schedule s9-transfer
  sleep 0.6
  for n in s3-tree s8-schedule s9-transfer; do
    df="$BH_ROOT/$n.dash.yaml"
    bh_check "$n: 위젯 type·width 가 authoring 그대로" "$(bh_layout_sig "$df.orig")" "$(bh_layout_sig "$df")"
    bh_check "$n: 레이아웃 규칙 위반 0" "" "$(bh_layout_violations "$df")"
  done
  bh_check "s3: graph(tree) 노드·엣지 보존" "3/2" \
    "$(bh_yget "$BH_ROOT/s3-tree.dash.yaml" "'%d/%d' % (len(d['widgets'][0]['nodes']), len(d['widgets'][0]['edges']))")"
  bh_check "s9: chart value 가 시계열 JSON(points)" "[0, 3, 7, 10]" \
    "$(bh_yget "$BH_ROOT/s9-transfer.dash.yaml" "__import__('json').loads([w for w in d['widgets'] if w['id']=='files-chart'][0]['value'])['points']")"
  BH_EXPECT_REGISTER=1
  bh_finish
}

# ── 케이스 보조 판정 ────────────────────────────────────────────────────────
bh_dead()      { ! kill -0 "$1" 2>/dev/null; }
bh_ticks_ge()  { [ -f "$BH_ROOT/$1.ticks" ] && [ "$(wc -l < "$BH_ROOT/$1.ticks" | tr -d ' ')" -ge "$2" ]; }
bh_trace_has() { grep -q " $1 $2\$" "$FAKE_TRACE"; }
bh_stuck_badge() {
  [ "$(bh_yget "$BH_ROOT/stk.dash.yaml" "[w for w in d['widgets'] if w['id']=='queue-state'][0].get('state')")" = error ] &&
  bh_yget "$BH_ROOT/stk.dash.yaml" "[w for w in d['widgets'] if w['id']=='queue-state'][0].get('label')" | grep -q STUCK
}
bh_all_running() {
  local n
  for n in "$@"; do
    [ "$(bh_yget "$BH_ROOT/$n.dash.yaml" "d.get('status')")" = running ] || return 1
  done
}
bh_layout_sig() { bh_yget "$1" "'|'.join('%s:%s:%s' % (w.get('id'), w.get('type'), w.get('width', 1)) for w in d.get('widgets', []))"; }

CASES="board-s1-complete board-s2-dag-order board-s4-linear-queue board-s6-concurrency
board-s7-heartbeat-alive board-sentinel-done board-stuck-detect board-hub-json-widgets"

run_case() {
  case "$1" in
    board-s1-complete)        case_s1_complete ;;
    board-s2-dag-order)       case_s2_dag_order ;;
    board-s4-linear-queue)    case_s4_linear_queue ;;
    board-s6-concurrency)     case_s6_concurrency ;;
    board-s7-heartbeat-alive) case_s7_heartbeat_alive ;;
    board-sentinel-done)      case_sentinel_done ;;
    board-stuck-detect)       case_stuck_detect ;;
    board-hub-json-widgets)   case_hub_json_widgets ;;
    *) echo "FAIL: 알 수 없는 케이스 '$1' (목록: $(echo $CASES))"; exit 2 ;;
  esac
}

# --all: 케이스를 **병렬**로 돌린다 — 케이스마다 tmux 소켓·임시 루트·hub 스텁 포트가 따로라
#   서로 간섭하지 않는다(그 자체가 격리 검증이다). 바닥 소요는 supervisor 의 주입당 고정 2초
#   (send_prompt Enter 유실 가드)라 순차면 80초 안팎, 병렬이면 가장 긴 케이스 하나다.
#   --serial 을 붙이면 순차 — 타이밍 의심 시 대조용.
if [ "${1:-}" = --all ]; then
  rc=0; t0=$(date +%s); outd=$(mktemp -d "${TMPDIR:-/tmp}/board-l2-all.XXXXXX")
  for c in $CASES; do
    if [ "${2:-}" = --serial ]; then
      ( s=$(date +%s); bash "${BASH_SOURCE[0]}" "$c" > "$outd/$c.out" 2>&1; echo "$? $(( $(date +%s) - s ))" > "$outd/$c.rc" )
    else
      ( s=$(date +%s); bash "${BASH_SOURCE[0]}" "$c" > "$outd/$c.out" 2>&1; echo "$? $(( $(date +%s) - s ))" > "$outd/$c.rc" ) &
    fi
  done
  wait
  skips=0
  for c in $CASES; do
    read -r r secs < "$outd/$c.rc"
    printf '%-26s rc=%s %3ss  %s\n' "$c" "$r" "$secs" "$(tail -1 "$outd/$c.out")"
    [ "$r" -eq 0 ] || { rc=1; sed 's/^/    /' "$outd/$c.out"; }
    case "$(head -1 "$outd/$c.out")" in skip*) skips=$((skips + 1)) ;; esac
  done
  # skip 은 통과가 아니다 — 실패 없이 건너뛴 케이스가 있으면 rc 3(partial, tdd/playlist-run.py 규약)
  [ "$rc" -eq 0 ] && [ "$skips" -gt 0 ] && rc=3
  printf '전체 %ss (%s)\n' "$(( $(date +%s) - t0 ))" "$([ "${2:-}" = --serial ] && echo 순차 || echo 병렬)"
  rm -rf "$outd"
  exit "$rc"
fi
run_case "${1:?case-id 필요 — --all 또는 $(echo $CASES)}"
