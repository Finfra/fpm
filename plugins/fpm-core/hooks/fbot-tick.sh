#!/usr/bin/env bash
# fbot 상주 tick 래퍼 (Issue436_3 s0) — launchd 가 부르는 단일 진입점.
#
# 왜 래퍼인가 (QA 발견 A·C, 2026-08-23):
#   A. `worker.py run` 은 pending 잡을 **소비만** 한다. 생산자(enqueue)가 없어 launchd 가
#      30분마다 "처리 0건" 만 남기고 끝났다 — 배관이 영구 공회전. enqueue→run 을 잇는다.
#   C. launchd 리다이렉트 로그에는 시각이 없고 회전도 없다. 여기서 타임스탬프·회전을 준다.
set -u

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
#   ⚠️ 개인 절대경로였다(`$HOME/…`) — fbot-arch §범용 배포 요건 위반이었고,
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
    # prj3#Issue518 (2026-09-03) — `review` 만 부르면 draft 가 고립된다.
    #   F5 루프는 review → propose → ACK → apply 4단인데 자동 경로가 1단뿐이었다.
    #   실측: draft 5건이 2026-08-31 생성 후 3일간 mq 컨펌 0건·job 레코드 0건.
    #   `propose` 는 **본사 팀장 인박스** 적재만 하고(권한 경계 role 포함 — prj3#Issue757_1) 정본을 건드리지 않는다(write_canonical 은
    #   승인 레코드 — 총괄 `apply --by` 전결 기록 또는 mq ACK — 를 인자로 요구, prj3#Issue756).
    #   draft 0건이면 정상 no-op(rc=0) 이라 별도 분기가 필요 없다.
    if ! "$PY" "$HOOKS_DIR/fbot-manual-review.py" propose; then
      log "⚠️ manual-review propose 실패 rc=$? — draft 는 남는다(다음 tick 재시도)"
    fi
    printf '%s\n' "$day" > "$MANUAL_REVIEW_MARKER"
  else
    mrc=$?
    log "⚠️ manual-review 실패 rc=$mrc — tick 계속(fail-soft, 마커 미갱신 → 다음 tick 재시도)"
  fi
  return 0
}

# ── 총괄핀봇 daily report 게이트 (Issue438 ②) ──────────────────────────────
# 왜 tick 편입인가 — `fbot-chief-report.py daily` 는 구현돼 있는데 launchd·cron 어디에도
#   안 걸려 있어 **자동 보고가 실제로는 0회**였다(Issue438 실측). 별도 launchd 를 더
#   만들지 않고 이미 도는 worker tick 에 1일 1회 게이트로 얹는다 — 위 매뉴얼 개정 루프
#   (주 1회)와 같은 패턴이다. 마커에 날짜를 남겨 같은 날 재실행을 막는다.
# ⚠️ `--dry-run` 은 붙이지 않는다 — 폴백 사다리(Discord 미설정이면 hub→파일 보고)가
#   정상 경로다. dry-run 을 박으면 "돌긴 도는데 산출이 없는" 공회전이 된다.
#   실패해도 tick 은 계속한다(fail-soft) — 마커를 갱신하지 않으므로 다음 tick 이 재시도한다.
# ── instinct 승격 결정 티어 게이트 (prj3#Issue853) ────────────────────────────
# 학습 3단 티어(Issue850)의 «결정 = opus» 를 instinct 축에 배선한다 — promote-instinct 초안을 총괄 인박스로.
#   주기·마커·fail-soft 는 manual_review_gate 와 같다(월요일 첫 tick · 같은 날 중복 차단). 산출은 인박스 요청 1건까지 —
#   결정(reject/recommend)은 총괄 몸체가, 활성화(mv)는 사람이 한다. 봇이 commands/*.md 를 만드는 경로는 없다.
INSTINCT_PROMOTE_MARKER="$HOME/.claude/data/fbot/.last-instinct-promote"
instinct_promote_gate() {
  local dow day marker irc
  dow="${FBOT_TICK_DOW_OVERRIDE:-$(date +%u)}"
  day="$(date +%Y-%m-%d)"
  if [ "$dow" != "1" ]; then
    log "instinct-promote skip — 월요일 아님(dow=$dow)"
    return 0
  fi
  marker="$(cat "$INSTINCT_PROMOTE_MARKER" 2>/dev/null || true)"
  if [ "$marker" = "$day" ]; then
    log "instinct-promote skip — 오늘 이미 실행($day)"
    return 0
  fi
  log "tick worker — instinct-promote (주 1회)"
  if "$PY" "$HOOKS_DIR/fbot-instinct-gate.py" propose; then
    printf '%s\n' "$day" > "$INSTINCT_PROMOTE_MARKER"
  else
    irc=$?
    log "⚠️ instinct-promote 실패 rc=$irc — tick 계속(fail-soft, 마커 미갱신 → 다음 tick 재시도)"
  fi
  return 0
}

# ── 종결 job·통지 표식 GC 게이트 (prj3#Issue938) ─────────────────────────────
# 왜 tick 편입인가 — `worker.py gc` 는 구현돼 있는데 launchd·cron 어디에도 안 걸려 있어 **job 테이블이 한 번도 정리되지
#   않았다**(2026-10-04 실측: 15k행·30일 경과 579건 잔존). 새 launchd 를 만들지 않고 이미 도는 worker tick 에 1일 1회
#   게이트로 얹는다 — 위 daily report 와 같은 패턴(날짜 마커 · fail-soft).
# ⚠️ `gc --jobs` 만 건다 — `--jobs` 없는 `gc --apply` 는 **관측(learn.db) 에이징도 실행**하고 learn.db 전체(수백 MB)를
#   백업한다. raw 관측 삭제는 별개 결정(요약 소화·유예·백업 이력)이라 무인 정기 경로에 싣지 않는다.
#   `--jobs` 는 job 허용 목록(consolidation·index)의 종결 행과 통지 표식만 지우고 fbot 원장·sel_event 는 건드리지 않는다.
#   실패해도 tick 은 계속한다(fail-soft) — 마커를 갱신하지 않으므로 다음 tick 이 재시도한다.
JOB_GC_MARKER="$HOME/.claude/data/fbot/.last-job-gc"
job_gc_gate() {
  local day marker grc
  day="$(date +%Y-%m-%d)"
  marker="$(cat "$JOB_GC_MARKER" 2>/dev/null || true)"
  if [ "$marker" = "$day" ]; then
    log "job-gc skip — 오늘 이미 실행($day)"
    return 0
  fi
  log "tick worker — job-gc (1일 1회)"
  if "$PY" "$SRC/worker.py" gc --jobs --apply; then
    mkdir -p "$(dirname "$JOB_GC_MARKER")"
    printf '%s\n' "$day" > "$JOB_GC_MARKER"
  else
    grc=$?
    log "⚠️ job-gc 실패 rc=$grc — tick 계속(fail-soft, 마커 미갱신 → 다음 tick 재시도)"
  fi
  return 0
}

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
  if "$PY" "$HOOKS_DIR/fbot-chief-report.py" daily; then
    mkdir -p "$(dirname "$DAILY_REPORT_MARKER")"
    printf '%s\n' "$day" > "$DAILY_REPORT_MARKER"
  else
    drc=$?
    log "⚠️ daily-report 실패 rc=$drc — tick 계속(fail-soft, 마커 미갱신 → 다음 tick 재시도)"
  fi
  return 0
}

# ── 원격 머신 보고 회수 게이트 (Issue468) ──────────────────────────────────
# 왜 필요한가 (2026-08-30 실측): fg1 상주 봇이 매일 보고를 만드는데 폴백 사다리가
#   rung1(openclaw 미탐지) → rung2(hub OFF) → **rung3 file** 로 끝나, 3일치가 그 머신
#   로컬에만 쌓이고 사용자에게 한 번도 닿지 않았다. 사다리의 세 단이 전부 그 머신
#   기준이라 어느 단으로 떨어져도 산출물이 머신을 벗어나지 못한다.
#
# 🔑 **미는 것이 아니라 당긴다** — 원격이 jm4 로 push 하려면 그쪽에 이 머신의 경로·권한
#   지식이 필요해 결합이 커진다. 수집자가 당기면 원격은 파일만 만들면 된다.
# 🔑 **봇을 합치지 않고 산출물만 옮긴다** — "봇은 머신에 귀속" 판정(prj3#Issue461)과
#   충돌하지 않는다. 파일명에 `_on-<host>` 를 박아 출처를 잃지 않는다.
# ⚠️ 원본은 지우지 않는다 — 그 머신의 이력이다. 회수는 복제다.
#
# 설정: data/fbot/remote-hosts.txt (한 줄 1 호스트, `#` 주석 허용).
#   파일이 없으면 **완전 no-op** — 원격이 없는 머신에 배포돼도 비용 0이다.
REMOTE_HOSTS_FILE="$HOME/.claude/data/fbot/remote-hosts.txt"
REMOTE_PULL_MARKER="$HOME/.claude/data/fbot/.last-remote-pull"
remote_report_pull_gate() {
  [ -f "$REMOTE_HOSTS_FILE" ] || return 0          # ← 무비용 가드
  local day marker host n=0 dest
  day="$(date +%Y-%m-%d)"
  marker="$(cat "$REMOTE_PULL_MARKER" 2>/dev/null || true)"
  if [ "$marker" = "$day" ]; then
    log "remote-report-pull skip — 오늘 이미 회수($day)"
    return 0
  fi
  dest="$HOME/.claude/data/fbot/reports"
  mkdir -p "$dest" 2>/dev/null || true
  while IFS= read -r host; do
    host="${host%%#*}"; host="$(printf '%s' "$host" | tr -d '[:space:]')"
    [ -n "$host" ] || continue
    # 원격 보고를 로컬 이름공간으로 옮겨 담는다 — `<날짜>_on-<host>.md`.
    #   scp 로 통째 가져와 rename 하면 이름 충돌·부분 전송이 섞이므로 파일별로 처리한다.
    local names f base
    names="$(ssh -o ConnectTimeout=8 -o BatchMode=yes "$host" \
             'ls -1 ~/.claude/data/fbot/reports/*.md 2>/dev/null' 2>/dev/null || true)"
    [ -n "$names" ] || { log "remote-report-pull — $host: 보고 없음/접속 불가(건너뜀)"; continue; }
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      base="$(basename "$f" .md)"
      local out="$dest/${base}_on-${host%%.*}.md"
      [ -f "$out" ] && continue                     # 이미 회수 — 중복 0
      if scp -q -o ConnectTimeout=8 -o BatchMode=yes "$host:$f" "$out" 2>/dev/null; then
        n=$((n+1))
      fi
    done <<< "$names"
  done < "$REMOTE_HOSTS_FILE"
  log "remote-report-pull — 신규 $n 건 회수"
  printf '%s\n' "$day" > "$REMOTE_PULL_MARKER"
  return 0
}

# ── prj3#Issue538 s6: 머신 간 봇 메시지 회수 ────────────────────────────
# 보고 회수(위)와 **같은 방향**이다 — 원격이 밀지 않고 이쪽이 당긴다. 미는 쪽에
#   수집자의 경로·권한 지식을 요구하면 결합이 커진다(Issue468 근거 계승).
# ⚠️ 보고와 달리 **매 tick** 돈다. 보고는 하루 1건이지만 봇 메시지는 요청이라
#   하루 지연이 곧 조직 정지다(실측 종단 ≈15분 = tick 주기의 절반).
# 원본은 상대 머신에서 지운다 — 보고와 반대다. 보고는 그 머신의 이력이지만
#   메시지는 **한 번 배달되면 끝**이고, 남겨두면 다음 tick 이 또 접수한다.
# prj3#Issue689: 유휴 팀 휴직(org_sweep_gate, Issue538)은 **제거**했다. 자리에 앉은 팀장은
#   Issue609 상비 보호로 휴직이 거부돼 9/9 이후 매 tick 15건 전부 실패했고, 게이트가
#   오류를 버려 기록도 없었다. 「구성 중」 은 이제 fbot-org.py team_formed 가 활동 시각에서
#   파생하는 표시 판정이다 — tick 이 할 일이 없다. 해산은 보드의 사용자 버튼이 한다.

OUTBOX_ROOT="$HOME/.claude/data/fbot/outbox"
# prj3#Issue552 — 매니저 인박스 방치 에스컬레이션 (소비 경로 ②tick).
#   매니저가 출근하지 않으면 요청은 영원히 안 읽힌다 — 임계(기본 30분, FBOT_INBOX_ESCALATE_MIN)
#   초과 open 요청을 aoa-mq alert 로 사람에게 묶음 1회 올린다. 요청을 대신 처리하지 않는다.
#   재알림 방지는 payload.escalated_at (fbot-inbox.py 단일 지점) — 큐 파일을 뒤지지 않는다.
inbox_escalate_gate() {
  [ -f "$HOME/.claude/hooks/fbot-inbox.py" ] || return 0     # ← 무비용 가드
  local out n
  out="$(python3 "$HOME/.claude/hooks/fbot-inbox.py" escalate --apply 2>/dev/null || true)"
  n="$(printf '%s' "$out" | python3 -c 'import json,sys;print(len(json.load(sys.stdin).get("alerted") or []))' 2>/dev/null || echo 0)"
  [ "${n:-0}" -gt 0 ] && log "inbox-escalate — 매니저 미응답 요청 $n 건 alert"
  return 0
}

# prj3#Issue734 — 매니저 인박스 자동 기상 안전망. `send` 가 깨우지 못한 퇴근 매니저(발신 환경에
#   tmux·fpm-do 가 없었거나 잠금 유예가 끝남)를 다시 깨운다. escalate **앞**에 두어 사람에게 올리기 전
#   한 번 더 스스로 해결을 시도한다. 판정·잠금은 fbot-inbox.py 단일 지점 — 여기서 복제하지 않는다.
inbox_wake_gate() {
  [ -f "$HOOKS_DIR/fbot-inbox.py" ] || return 0     # ← 무비용 가드
  local out n
  out="$("$PY" "$HOOKS_DIR/fbot-inbox.py" wake-pending --apply 2>/dev/null || true)"
  n="$(printf '%s' "$out" | "$PY" -c 'import json,sys;print(len(json.load(sys.stdin).get("woken") or []))' 2>/dev/null || echo 0)"
  [ "${n:-0}" -gt 0 ] && log "inbox-wake — 퇴근 매니저 $n 명 기상"
  return 0
}

remote_msg_pull_gate() {
  [ -f "$REMOTE_HOSTS_FILE" ] || return 0          # ← 무비용 가드(보고 회수와 동일)
  local host me n=0 names f base
  me="${FBOT_MACHINE:-$(hostname -s)}"
  while IFS= read -r host; do
    host="${host%%#*}"; host="$(printf '%s' "$host" | tr -d '[:space:]')"
    [ -n "$host" ] || continue
    # 상대 머신의 outbox 에서 **나에게 온 것만** 당긴다
    names="$(ssh -o ConnectTimeout=8 -o BatchMode=yes "$host" \
             "ls -1 ~/.claude/data/fbot/outbox/$me/*.json 2>/dev/null" 2>/dev/null || true)"
    [ -n "$names" ] || continue
    mkdir -p "$OUTBOX_ROOT/$me" 2>/dev/null || true
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      base="$(basename "$f")"
      [ -f "$OUTBOX_ROOT/$me/$base" ] && continue
      if scp -q -o ConnectTimeout=8 -o BatchMode=yes "$host:$f" "$OUTBOX_ROOT/$me/$base" 2>/dev/null; then
        ssh -o ConnectTimeout=8 -o BatchMode=yes "$host" "rm -f '$f'" 2>/dev/null || true
        n=$((n+1))
      fi
    done <<< "$names"
  done < "$REMOTE_HOSTS_FILE"
  [ "$n" -gt 0 ] && log "remote-msg-pull — $n 건 회수"
  # 접수는 로컬 처리다 — 당겨온 것 + 이전에 남은 것을 함께 소화한다
  if [ -x "$HOME/.claude/hooks/fbot-outbox.py" ] || [ -f "$HOME/.claude/hooks/fbot-outbox.py" ]; then
    python3 "$HOME/.claude/hooks/fbot-outbox.py" consume --apply >/dev/null 2>&1 \
      || log "remote-msg-consume 실패(다음 tick 재시도)"
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
    # maint: 종결 job·통지 표식 GC (prj3#Issue938 — 1일 1회, 관측 에이징 제외)
    job_gc_gate
    # maint: lease 만료 봇 강제 퇴근 (계약 §상태 기계 — 크래시 봇이 "작업중" 영구 잔류 차단)
    log "tick worker — reap"
    "$PY" "$HOOKS_DIR/fbot-state.py" reap --apply || { rc=$?; log "⚠️ reap 실패 rc=$rc"; }
    # maint: 고아 agent 마커 GC (Issue751_5) — reap **뒤**여야 방금 강제 퇴근된 봇의 마커까지 거둔다
    log "tick worker — $(bash "$HOOKS_DIR/fbot-agent-done.sh" --gc 2>&1 | tail -1)"
    # maint: 배분 완료 감지·통지 (Issue438 ④ — 상태 전이 시점 통지. 묶음 1회)
    #   watch 가 아니라 sweep 을 건다 — sweep 은 완료만 판정·통지하고 에스컬레이션은 하지
    #   않는다. 무인 주기에 얹기에 부작용이 가장 작은 단위다.
    #   예외 1종(prj3#Issue947): «완료 미확인» 통지가 재통지 상한에 닿은 배분은 mq 경보(묶음)를 낸다 — 정상 배분당 1회, 경보 실패·표지 고착 시 백오프 뒤 재경보.
    log "tick worker — dispatch sweep"
    "$PY" "$HOOKS_DIR/fbot-lead.py" sweep >/dev/null || {
      src=$?; log "⚠️ sweep 실패 rc=$src — tick 계속(fail-soft)"; }
    # maint: 승격된 미룬 배분 몸체 기동 (prj3#Issue904) — sweep 이 open 으로 당기며 spawn_pending 을 남긴 행만.
    #   sweep 에 싣지 않는다(최소 부작용 단위 유지) — 배치 판정은 dispatch 와 같은 HR 게이트 경유
    log "tick worker — deferred spawn"
    "$PY" "$HOOKS_DIR/fbot-lead.py" spawn --pending >/dev/null || {
      src=$?; log "⚠️ spawn --pending 실패 rc=$src — tick 계속(fail-soft)"; }
    # maint: 매뉴얼 개정 루프 (계약 §매뉴얼 체계 — 산출은 draft 까지, 정본 반영은 사람 승인 후)
    manual_review_gate
    # maint: instinct 승격 초안 → 총괄 결정 티어 (prj3#Issue853 — 주 1회, 매뉴얼 개정 루프와 같은 주기)
    instinct_promote_gate
    # maint: 총괄핀봇 daily report (Issue438 ② — 1일 1회)
    # Issue468 — 원격 보고 회수는 daily report **앞**에 둔다. 그래야 오늘 보고가
    #   회수분까지 반영한 상태로 만들어진다. 순서를 뒤집으면 하루 늦게 반영된다.
    remote_report_pull_gate
    # prj3#Issue538 s6 — 봇 메시지 회수·접수. 보고 회수와 달리 **매 tick** 돈다:
    #   보고는 하루 1건이지만 메시지는 요청이라 하루 지연이 곧 조직 정지다.
    remote_msg_pull_gate
    # prj3#Issue552 — 매니저 인박스 방치분 에스컬레이션. 메시지 회수(remote_msg_pull) 뒤에 두어
    #   방금 도착한 원격 요청은 임계를 새로 세기 시작한다.
    inbox_wake_gate
    inbox_escalate_gate
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
