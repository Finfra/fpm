#!/usr/bin/env bash
# board-real-worker.sh — board L3 실 worker E2E (Issue544 M3). **출고 전 1회** — 실 claude 를 띄운다.
#
# 합성 worker(L2)가 못 보는 것을 본다 — 실 claude TUI 의 pane 상태 판정(worker_ready·busy/idle),
#   권한 처리, sentinel 실기록, 선행 결과 주입({{id.result}}). 큐는 s4 축약 3단계
#   (tdd/fixtures/board/real-worker.queue.yaml).
#
# 운영과 같은 경로로 띄운다 — WORKER_CMD 를 비워 supervisor 기본값(`claude`, 사용자 기본 권한 모드)을
#   그대로 쓴다. 래퍼를 쓰면 supervisor 가 합성 worker 로 보고 worker_ready 게이트를 건너뛰어
#   검증 대상이 바뀐다. 간격도 운영 기본값(board_policy 부재 → active 3초·idle 20초).
# 격리는 L2 하네스와 같다(전용 tmux 소켓·임시 루트·hub 스텁). 단 실 claude 는 사용자 훅을 싣고
#   도므로 운영 hub 에 board worker 세션 카드가 잠깐 생긴다 — 이것이 L3 가 개발 재생목록에
#   없는 이유 중 하나다(board-scenario-kit.md "L3 를 개발 재생목록에 넣지 않는 이유").
#
# 신뢰 대화상자: 임시 폴더는 workspace trust 기록이 없어 claude 가 «이 폴더를 신뢰하는가» 를 묻는다.
#   운영 worker 는 이미 신뢰된 프로젝트 폴더에서 돌므로 이 대화상자를 만나지 않는다 — 여기서는
#   감시 루프가 기본 선택(Yes)으로 수락해 운영 조건을 재현한다. 수락 시각은 watcher.log 에 남긴다.
#
# 사용: bash tdd/board-real-worker.sh --yes      (--yes 없으면 skip — 실수로 과금되지 않게)
# 출력: 마지막 줄 ok:board-real-worker / FAIL:board-real-worker. 실패 시 임시 루트를 보존한다
#   (pane 스냅샷 cap/·supervisor 로그 — 진단용).

set -uo pipefail
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export REPO_DIR
ORIG_FPM_BASE="${FPM_BASE:-}"
# shellcheck source=/dev/null
source "$REPO_DIR/tdd/lib/board-harness.sh"

[ "${1:-}" = --yes ] || bh_skip "실 claude worker 를 띄운다(사용 한도 소모·운영 hub 세션 카드) — 의도했으면 --yes"
command -v claude >/dev/null 2>&1 || bh_skip "claude CLI 없음"

LIMIT="${BOARD_L3_LIMIT:-600}"     # 큐 완주 상한(초)

bh_setup board-real-worker
# worker pane 의 훅이 사용자 스크립트를 찾도록 FPM_BASE 를 되돌린다(하네스는 board 스크립트 기본값
#   격리용으로 임시 루트를 넣는다 — board 스크립트는 BOARD_POLICY·PROJECTS_DIR 를 명시로 받으므로 무관)
if [ -n "$ORIG_FPM_BASE" ]; then
  command tmux -L "$BOARD_TMUX_SOCKET" set-environment -g FPM_BASE "$ORIG_FPM_BASE"
else
  command tmux -L "$BOARD_TMUX_SOCKET" set-environment -gu FPM_BASE
fi
# 부모 Claude 세션의 신원·중첩 표식을 worker 에 물려주지 않는다 — 격리 tmux 서버는 이 스크립트를
#   부른 프로세스의 환경을 복사한다. 남기면 ① `CLAUDECODE` 로 중첩 실행 차단에 걸리고 ② 부모의
#   세션 ID·메시징 소켓을 worker 가 제 것으로 써 hub 가 두 세션을 하나로 본다. 운영 board 는
#   사용자 tmux 서버(사람이 띄운 셸 환경)에서 worker 를 띄우므로 이런 변수가 없다
for v in $(env | sed -n -E 's/^((CLAUDE|MCP_)[A-Za-z0-9_]*)=.*/\1/p'); do
  command tmux -L "$BOARD_TMUX_SOCKET" set-environment -gu "$v"
done
bh_prj 1
W="$BH_ROOT/w/1"
mkdir -p "$BH_ROOT/cap"

# ── 감시 루프 — 신뢰 대화상자 수락 + pane 스냅샷(진단 증거) ────────────────
watcher() {
  local t0 now n=0 pane cap
  t0=$(date +%s)
  while :; do
    now=$(date +%s); [ $((now - t0)) -ge "$LIMIT" ] && break
    while read -r pane; do
      cap=$(command tmux -L "$BOARD_TMUX_SOCKET" capture-pane -p -t "$pane" 2>/dev/null) || continue
      # 2.1.x 형식(실측 2026-09-27): "Is this a project you created or one you trust?" 아래
      #   `❯ No, exit` / `Yes, I trust this folder` — **기본 선택이 No** 다. 그대로 Enter 면 worker 가
      #   종료된다(1차 실행 실측). 선택을 Yes 로 옮긴 것을 화면으로 확인한 뒤에만 Enter 를 누른다
      if printf '%s' "$cap" | grep -q 'Yes, I trust this folder'; then
        if printf '%s' "$cap" | grep -qE '❯ *Yes, I trust this folder'; then
          command tmux -L "$BOARD_TMUX_SOCKET" send-keys -t "$pane" Enter
          printf '%s trust 대화상자 수락 pane=%s\n' "$(date '+%H:%M:%S')" "$pane" >> "$BH_ROOT/watcher.log"
          sleep 1
        else
          command tmux -L "$BOARD_TMUX_SOCKET" send-keys -t "$pane" Down
        fi
        continue
      fi
      if [ $((n % 25)) -eq 0 ]; then
        printf '%s\n' "$cap" > "$BH_ROOT/cap/$(date +%H%M%S)-${pane#%}.txt"
      fi
    done < <(command tmux -L "$BOARD_TMUX_SOCKET" list-panes -a -F '#{window_name} #{pane_id}' 2>/dev/null \
               | awk '$1 != "main" {print $2}')
    n=$((n + 1))
    sleep 0.2
  done
}
watcher &
bh_track $!

export BH_WORKER_CMD=""              # → supervisor 기본값 claude
export INTERVAL_ACTIVE=3 INTERVAL_IDLE=20
T0=$(date +%s)
bh_queue real-worker.queue.yaml l3real runner

bh_qend() { case "$(bh_qstate l3real)" in done|halted) return 0 ;; esac; return 1; }
bh_true "큐가 상한 ${LIMIT}초 안에 종료" bh_wait "$LIMIT" bh_qend
ELAPSED=$(( $(date +%s) - T0 ))
bh_check "큐 state=done (halted 아님)" done "$(bh_qstate l3real)"
bh_check "3단계 전부 done" "done done done" \
  "$(bh_yget "$BH_ROOT/l3real.queue.yaml" "' '.join(i['status'] for i in d['items'])")"
bh_check "3단계 rc 0" "0 0 0" \
  "$(bh_yget "$BH_ROOT/l3real.queue.yaml" "' '.join(str(i.get('rc')) for i in d['items'])")"
bh_check "순서 r1 → r2 → r3 (ended_at ≤ 다음 started_at)" yes \
  "$(bh_yget "$BH_ROOT/l3real.queue.yaml" "(lambda b: 'yes' if b['r1'].get('ended_at') and b['r1']['ended_at'] <= b['r2'].get('started_at','') and b['r2']['ended_at'] <= b['r3'].get('started_at','') else 'no')({i['id']:i for i in d['items']})")"
bh_check "산출물 step1.txt = one" one "$(cat "$W/step1.txt" 2>/dev/null)"
bh_check "산출물 step2.txt = two" two "$(cat "$W/step2.txt" 2>/dev/null)"
bh_true "r3 결과 요약이 두 파일 내용(one·two)을 담는다" \
  bash -c '[[ "$1" == *one*two* ]]' _ "$(bh_item l3real r3 result)"
bh_check "sentinel 실기록 3건 (supervisor 로그 DONE rc=0)" 3 \
  "$(grep -c 'sentinel DONE rc=0' "$BH_ROOT/l3real.supervisor.log" 2>/dev/null)"
bh_true "queue-runner 완주 마감(status=done)" bh_wait 15 bh_status_is "$BH_ROOT/l3real.dash.yaml" done
bh_check "완주 후 레이아웃 규칙 위반 0" "" "$(bh_layout_violations "$BH_ROOT/l3real.dash.yaml")"

# ── 요약 (증거) ───────────────────────────────────────────────────────────
echo "── L3 요약 ──"
echo "  소요: ${ELAPSED}초 (상한 ${LIMIT}초)"
echo "  시도: $(bh_yget "$BH_ROOT/l3real.queue.yaml" "' '.join('%s=%s' % (i['id'], i.get('attempts')) for i in d['items'])")"
echo "  결과: $(bh_yget "$BH_ROOT/l3real.queue.yaml" "' | '.join('%s: %s' % (i['id'], i.get('result')) for i in d['items'])")"
echo "  trust 수락: $(grep -c '' "$BH_ROOT/watcher.log" 2>/dev/null || echo 0)회"
echo "  Enter 재송신: $(grep -c 'Enter 재송신' "$BH_ROOT/l3real.supervisor.log" 2>/dev/null)회 · 무sentinel 재시도: $(grep -c '무sentinel → 재시도' "$BH_ROOT/l3real.supervisor.log" 2>/dev/null)회"
[ "$BH_FAILS" -gt 0 ] && BH_KEEP=1
BH_EXPECT_REGISTER=1
bh_finish
