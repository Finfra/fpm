#!/usr/bin/env bash
# fbot 상주 tick 래퍼 (Issue436_3 s0) — launchd 가 부르는 단일 진입점.
#
# 왜 래퍼인가 (QA 발견 A·C, 2026-08-23):
#   A. `worker.py run` 은 pending 잡을 **소비만** 한다. 생산자(enqueue)가 없어 launchd 가
#      30분마다 "처리 0건" 만 남기고 끝났다 — 배관이 영구 공회전. enqueue→run 을 잇는다.
#   C. launchd 리다이렉트 로그에는 시각이 없고 회전도 없다. 여기서 타임스탬프·회전을 준다.
set -u

AOA_DIR="${AOA_MEMORY_DIR:-$HOME/_git/___common/data/aoa}"
SRC="$HOME/_git/___common/mcp/aoa-memory"
PY="${FBOT_PYTHON:-/opt/homebrew/bin/python3}"
LOG_MAX_BYTES="${FBOT_LOG_MAX_BYTES:-1048576}"   # 1MB 초과 시 1회 회전(.1 보관)

unit="${1:-}"
[ -n "$unit" ] || { echo "usage: fbot-tick.sh {worker|ingest}" >&2; exit 2; }

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# 로그 회전 — launchd 는 append 만 하므로 여기서 상한을 건다
rotate() {
  local f="$1"
  [ -f "$f" ] || return 0
  local sz
  sz=$(wc -c < "$f" 2>/dev/null | tr -d ' ')
  [ -n "$sz" ] && [ "$sz" -gt "$LOG_MAX_BYTES" ] && mv -f "$f" "$f.1"
  return 0
}
rotate "$HOME/Library/Logs/fbot/aoa-${unit}.out.log"
rotate "$HOME/Library/Logs/fbot/aoa-${unit}.err.log"

export AOA_MEMORY_DIR="$AOA_DIR"
rc=0

# ── 매뉴얼 개정 루프 게이트 (Issue436_3 s5) ─────────────────────────────────
# 계약 미해결 표 s5 확정행: 실행 주체 = worker tick 편입, 주기 = 주 1회(월요일 첫 tick).
#   왜 주 1회인가 — 매뉴얼은 관측이 쌓여야 개정 근거가 생긴다. 30분 주기로 돌리면
#   같은 표본을 반복 판정할 뿐이고, 산출은 어차피 draft 까지라 서둘러 얻을 것이 없다.
#   마커에 실행 날짜를 남겨 같은 월요일의 중복 실행을 막는다(첫 tick 만).
#   실패해도 tick 전체는 계속한다(fail-soft) — 마커를 갱신하지 않으므로 다음 tick 이 재시도한다.
MANUAL_REVIEW_MARKER="$HOME/.claude/data/fbot/.last-manual-review"
manual_review_gate() {
  local dow day marker mrc
  dow="${FBOT_TICK_DOW_OVERRIDE:-$(date +%u)}"   # 1=월요일. override 는 smoke 전용
  day="$(date +%Y-%m-%d)"
  if [ "$dow" != "1" ]; then
    log "manual-review skip — 월요일 아님(dow=$dow)"
    return 0
  fi
  marker="$(cat "$MANUAL_REVIEW_MARKER" 2>/dev/null || true)"
  if [ "$marker" = "$day" ]; then
    log "manual-review skip — 오늘 이미 실행($day)"
    return 0
  fi
  log "tick worker — manual-review (주 1회)"
  if "$PY" "$HOME/.claude/hooks/fbot-manual-review.py" review; then
    printf '%s\n' "$day" > "$MANUAL_REVIEW_MARKER"
  else
    mrc=$?
    log "⚠️ manual-review 실패 rc=$mrc — tick 계속(fail-soft, 마커 미갱신 → 다음 tick 재시도)"
  fi
  return 0
}

case "$unit" in
  worker)
    # 생산자 → 소비자. enqueue 실패 시에도 run 은 시도한다(이전 주기 잔여 잡 소비)
    log "tick worker — enqueue"
    "$PY" "$SRC/worker.py" enqueue || { rc=$?; log "⚠️ enqueue 실패 rc=$rc"; }
    log "tick worker — run"
    "$PY" "$SRC/worker.py" run || { rc=$?; log "⚠️ run 실패 rc=$rc"; }
    # maint: lease 만료 봇 강제 퇴근 (계약 §상태 기계 — 크래시 봇이 "작업중" 영구 잔류 차단)
    log "tick worker — reap"
    "$PY" "$HOME/.claude/hooks/fbot-state.py" reap --apply || { rc=$?; log "⚠️ reap 실패 rc=$rc"; }
    # maint: 매뉴얼 개정 루프 (계약 §매뉴얼 체계 — 산출은 draft 까지, 정본 반영은 사람 승인 후)
    manual_review_gate
    ;;
  ingest)
    log "tick ingest — observations 적재"
    "$PY" "$SRC/ingest_obs.py" --quiet || { rc=$?; log "⚠️ ingest 실패 rc=$rc"; }
    ;;
  *)
    echo "unknown unit: $unit" >&2; exit 2 ;;
esac

log "tick $unit 종료 rc=$rc"
exit "$rc"
