#!/usr/bin/env bash
# fbot 상주 tick 래퍼 (Issue436_3 s0) — launchd 가 부르는 단일 진입점.
#
# 왜 래퍼인가 (QA 발견 A·C, 2026-08-23):
#   A. `worker.py run` 은 pending 잡을 **소비만** 한다. 생산자(enqueue)가 없어 launchd 가
#      30분마다 "처리 0건" 만 남기고 끝났다 — 배관이 영구 공회전. enqueue→run 을 잇는다.
#   C. launchd 리다이렉트 로그에는 시각이 없고 회전도 없다. 여기서 타임스탬프·회전을 준다.
set -u

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
#   ⚠️ 개인 절대경로였다(`/Users/nowage/…`) — fbot-arch §범용 배포 요건 위반이었고,
#      사용자명이 다른 머신에서는 그 자체로 죽는다.
#   launchd 는 셸 프로파일을 읽지 않는다 → plist EnvironmentVariables 가 데이터 위치를 준다.
#   코드는 $HOME/.claude 사본을 쓴다(모듈 구성 동일). 데이터 위치와 코드 위치는 별개 축이다.
# 스케줄 판정 TZ 고정 (Issue454 함정 ①) — 플랫폼 간 동작 분기 차단.
#   아래 게이트 2종은 벽시계에 의존한다: 매뉴얼 개정(`date +%u` 월요일)·daily report
#   (`date +%Y-%m-%d` 날짜 경계). macOS launchd 는 **로컬 TZ**(jm4 실측 Asia/Seoul)로 돌지만
#   Linux user 세션은 **`Etc/UTC`** 다(fg1 실측) — 그대로 두면 같은 코드가 **9시간 갈린다**.
#   TZ 를 여기서 명시해 양쪽을 일치시킨다. jm4 는 이미 Asia/Seoul 이라 **값이 안 바뀐다**(무회귀).
#   ⚠️ 타이머 발화 주기(30분·15분)는 TZ 무관이다 — 어긋나는 것은 tick 안의 날짜 판정뿐이다.
export TZ="${FBOT_TZ:-Asia/Seoul}"

AOA_DIR="${AOA_MEMORY_DIR:-$HOME/.claude/data/aoa}"
SRC="${AOA_HOME:-$HOME/.claude/mcp/aoa-memory}"
# python3 해석 (Issue451 ①) — 절대경로 하드코딩 금지.
#   `/opt/homebrew/bin/python3` 는 macOS Homebrew 전용이라 Linux 소비자에서 그대로 죽는다.
#   순서: ① FBOT_PYTHON(정식 설정 — plist 가 생성 시점 해석값을 박아 준다)
#         ② PATH 의 python3   ③ 관례 경로 3종   ④ 없으면 fail-loud(exit 127)
#   ⚠️ launchd 는 셸 프로파일을 읽지 않는다 — ②가 성립하려면 plist 의 PATH env 가 필요하다.
#      그래서 fbot-worker-plist.sh 가 FBOT_PYTHON 을 **절대경로로 박아** ①에서 끝나게 한다.
resolve_python() {
  local c
  if [ -n "${FBOT_PYTHON:-}" ]; then printf '%s' "$FBOT_PYTHON"; return 0; fi
  c="$(command -v python3 2>/dev/null || true)"
  [ -n "$c" ] && { printf '%s' "$c"; return 0; }
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    [ -x "$c" ] && { printf '%s' "$c"; return 0; }
  done
  return 1
}
PY="$(resolve_python)" || {
  printf '[fbot-tick] 🚨 python3 미발견 — FBOT_PYTHON 을 절대경로로 설정하라 (PATH=%s)\n' "${PATH:-}" >&2
  exit 127
}

# 형제 hook 경로 (Issue451) — `$HOME/.claude/hooks` 하드코딩이었다.
#   소비자는 SCAR 를 **플러그인**으로 받는다(~/.claude/plugins/marketplaces/…/fpm-core/hooks/).
#   그 환경에서 `~/.claude/hooks` 는 아예 없어서 reap·sweep·report 가 전부 rc=2 로 죽었다
#   — fail-soft 라 tick 은 살아 있고 로그만 남아, 무신호에 가까운 실패였다(2026-08-26 fg1 실측).
#   자기 위치가 곧 형제들의 위치다. 개발 머신(prj3 ~/.claude/hooks)에서도 같은 값이 나온다.
HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
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
# 로그 위치 플랫폼 분기 (Issue454) — `~/Library/Logs` 는 macOS 전용 규약이다.
#   launchd: plist 의 StandardOutPath/ErrorPath 가 그 파일로 리다이렉트하므로 회전이 필요하다.
#   systemd: stdout 을 **journald** 가 받는다(파일 리다이렉트 없음) → 아래 경로는 보통
#            존재하지 않고 rotate 는 무해하게 통과한다. 회전은 journald 가 소유한다.
case "$(uname -s)" in
  Darwin) FBOT_LOG_DIR="${FBOT_LOG_DIR:-$HOME/Library/Logs/fbot}" ;;
  *)      FBOT_LOG_DIR="${FBOT_LOG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/fbot}" ;;
esac
rotate "$FBOT_LOG_DIR/aoa-${unit}.out.log"
rotate "$FBOT_LOG_DIR/aoa-${unit}.err.log"

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
  if "$PY" "$HOOKS_DIR/fbot-manual-review.py" review; then
    printf '%s\n' "$day" > "$MANUAL_REVIEW_MARKER"
  else
    mrc=$?
    log "⚠️ manual-review 실패 rc=$mrc — tick 계속(fail-soft, 마커 미갱신 → 다음 tick 재시도)"
  fi
  return 0
}

# ── 중역핀봇 daily report 게이트 (Issue438 ②) ──────────────────────────────
# 왜 tick 편입인가 — `fbot-exec-report.py daily` 는 구현돼 있는데 launchd·cron 어디에도
#   안 걸려 있어 **자동 보고가 실제로는 0회**였다(Issue438 실측). 별도 launchd 를 더
#   만들지 않고 이미 도는 worker tick 에 1일 1회 게이트로 얹는다 — 위 매뉴얼 개정 루프
#   (주 1회)와 같은 패턴이다. 마커에 날짜를 남겨 같은 날 재실행을 막는다.
# ⚠️ `--dry-run` 은 붙이지 않는다 — 폴백 사다리(Discord 미설정이면 hub→파일 보고)가
#   정상 경로다. dry-run 을 박으면 "돌긴 도는데 산출이 없는" 공회전이 된다.
#   실패해도 tick 은 계속한다(fail-soft) — 마커를 갱신하지 않으므로 다음 tick 이 재시도한다.
DAILY_REPORT_MARKER="$HOME/.claude/data/fbot/.last-daily-report"
daily_report_gate() {
  local day marker drc
  day="$(date +%Y-%m-%d)"
  marker="$(cat "$DAILY_REPORT_MARKER" 2>/dev/null || true)"
  if [ "$marker" = "$day" ]; then
    log "daily-report skip — 오늘 이미 발신($day)"
    return 0
  fi
  log "tick worker — daily-report (1일 1회)"
  if "$PY" "$HOOKS_DIR/fbot-exec-report.py" daily; then
    mkdir -p "$(dirname "$DAILY_REPORT_MARKER")"
    printf '%s\n' "$day" > "$DAILY_REPORT_MARKER"
  else
    drc=$?
    log "⚠️ daily-report 실패 rc=$drc — tick 계속(fail-soft, 마커 미갱신 → 다음 tick 재시도)"
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
    "$PY" "$HOOKS_DIR/fbot-state.py" reap --apply || { rc=$?; log "⚠️ reap 실패 rc=$rc"; }
    # maint: 배분 완료 감지·통지 (Issue438 ④ — 상태 전이 시점 통지. 묶음 1회)
    #   watch 가 아니라 sweep 을 건다 — sweep 은 완료만 판정·통지하고 에스컬레이션은 하지
    #   않는다. 무인 주기에 얹기에 부작용이 가장 작은 단위다.
    log "tick worker — dispatch sweep"
    "$PY" "$HOOKS_DIR/fbot-taskmgr.py" sweep >/dev/null || {
      src=$?; log "⚠️ sweep 실패 rc=$src — tick 계속(fail-soft)"; }
    # maint: 매뉴얼 개정 루프 (계약 §매뉴얼 체계 — 산출은 draft 까지, 정본 반영은 사람 승인 후)
    manual_review_gate
    # maint: 중역핀봇 daily report (Issue438 ② — 1일 1회)
    daily_report_gate
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
