#!/bin/bash
# aoa-mq-tick.sh — aoa-mq 메시지 큐 tick 처리기 (설계 SSOT: _doc_arch/aoa-mq.md)
#
# 호출 계약: 기본은 시간 게이트 없음 — 호출되면 무조건 실행. `--gate <sec>` 를 준 호출자에
# 한해 공유 게이트 파일(.last-tick)로 억제한다(옵트인 — prj3#Issue37 F3-4).
# 자체 가드는 .tick.lock(동시 실행 방지) 하나뿐.
# 트리거: hub 타이머(htm-server daemon thread, 주 구동자) · jmDashboard aoaMqGate() spawn
#         (prj57 prj3#Issue6, 보조) · 수동 직접 실행.
#
# 처리 순서: lock → register → inbox 소비 → watch 폴링 → due 판정 → 대기 재확인(5.1)
#            → 질의 렌더 → 과다 누적 경고 → in_progress 적체·기동 → queue_done retention
#
# 시간축/통지축 분리 (prj3#Issue37 F3-3): MCP 승격(F3-2) 이후 통지 계층은 세션이 살아 있을 때
# 중복이다 — session-inbox.sh 넛지와 MCP `aoa_mq_list` 가 같은 사실을 이미 전달한다.
# 세션 활성 시에는 통지(inbox 소비·폼 렌더·누적 경고)를 건너뛰고 시간축 고유 처리
# (watch 폴링·due 판정·post 실행·handoff 전이·retention)만 수행한다.
# 완전 제거하지 않는 이유: 세션이 하나도 안 열린 기간은 세션 이벤트 트리거의 사각지대다.

set -u

# ── 봇 정체성 env 차단 (prj3#Issue679) ──────────────────────────────
# tick 은 봇 세션의 자식으로 기동될 수 있다(enqueue 직후 직접 kick 경로). 아래 세 곳이
#   자식 프로세스를 띄우는데(post whitelist spawn 2곳 · in_progress 자동 기동의
#   `claude -p` 1곳), 봇 env 를 상속한 채 claude 가 뜨면 출근 훅이 **그 봇을 결속**해
#   인격을 빼앗는다(Issue679 실발생 — 관측기 경로에서 동일 결함).
# ⚠️ 여기서 한 번 끊으면 세 spawn 이 모두 덮인다 — spawn 마다 덧대면 다음 spawn 에서 재발한다.
#   tick 자체는 FBOT_*·TMUX_PANE 를 **읽지 않으므로**(2026-09-23 전수 grep 0건) 무해하다.
_FBOT_SCRUB="${CLAUDE_DIR:-$HOME/.claude}/hooks/fbot-env-scrub.sh"
if [ -r "$_FBOT_SCRUB" ]; then . "$_FBOT_SCRUB" && fbot_env_scrub; fi

# ── 0. 인자 파싱 ────────────────────────────────────────────────────
GATE_SEC=0          # >0 이면 .last-tick 기준 그 초 이내 재실행 억제
FORCE_RENDER=0      # 세션 활성이어도 통지 계층 강제 수행
NO_ASK_WAIT=0       # 1이면 렌더 뒤 ask-wait 셀프 폴링을 건너뛴다 (prj3#Issue593 — 진단·수동 호출용)
# --consume-only (prj1#Issue423): inbox 소비만 하고 즉시 종료한다.
#   hub /mq 페이지가 액션을 접수한 직후 호출한다 — 종전엔 정규 tick(5분 주기 · 1회 3분
#   소요)을 기다려야 해서 "눌렀는데 목록에서 안 사라진다" 로 보였다. 상태 전이 로직을
#   복제하지 않고 **같은 consume_inbox() 를 태우므로** 소유는 여전히 tick 하나다.
CONSUME_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --gate)         GATE_SEC="${2:-0}"; shift 2 ;;
    --force-render) FORCE_RENDER=1; NO_ASK_WAIT=1; shift ;;   # prj3#Issue593: 진단 호출은 ask-wait 로 3분 잡지 않는다
    --no-ask-wait)  NO_ASK_WAIT=1; shift ;;
    --consume-only) CONSUME_ONLY=1; shift ;;
    *)              shift ;;
  esac
done
# 경로 계약 (prj3#Issue450) — prj5(___common) 를 전제하지 않는다.
#   AOA_MQ_DIR 은 sandbox 전용이 아니라 **정식 설정**이다. 미설정 시 제품 중립 기본으로 떨어진다.
MQ_DIR="${AOA_MQ_DIR:-$HOME/.claude/data/aoa/mq}"
QUEUE="$MQ_DIR/queue"
QDONE="$MQ_DIR/queue_done"
HANDOFF="$MQ_DIR/handoff"
LOCK="$MQ_DIR/.tick.lock"
LOCK_PID="$MQ_DIR/.tick.lock.pid"                        # 락 보유 PID (형제 파일 — 아래 1절 주석)
POLICY="$MQ_DIR/policy.yml"
LOG="$MQ_DIR/tick.log"
# 렌더 대상 프로젝트 — htm 산출물과 /answer 회수의 cwd 가 된다.
#   AOA_MQ_CWD 로 지정하고, 없으면 $HOME/.claude 로 떨어진다(prj5 미클론 머신 대응).
CWD="${AOA_MQ_CWD:-$HOME/.claude}"
CWD_NAME="$(basename "$CWD")"
# 렌더 산출물 폴더 — 활성 htm/ → legacy z_htm/ → htm/ 신규 (prj1#Issue289 / prj3#Issue258).
# 판정 규칙은 fpm-hub-trigger.sh `_htm_dir_of()` 와 동일. z_htm 하드코딩은 마이그레이션 후에도
# 폴더를 매 tick 재생성하는 원인이었음 (mq 20260719-201758-001).
if [ -d "$CWD/_doc_work/htm" ]; then HTM_DIR="$CWD/_doc_work/htm"
elif [ -d "$CWD/_doc_work/z_htm" ]; then HTM_DIR="$CWD/_doc_work/z_htm"
else HTM_DIR="$CWD/_doc_work/htm"
fi
PORT="${HTM_SERVER_PORT:-9876}"
JQ=/usr/bin/jq
DATE=/bin/date
STAT=/usr/bin/stat
# ── 외부 링크 base — **hub 에 물어서** 만든다 (prj1#Issue469 / fpm-identity 조항 1) ──
# 정본 패턴: plugins/fpm-core/hooks/fbot-exec-report.py `hub_links()`.
#   `/healthz` 의 `advertise_url` 을 그대로 쓰고, 값이 없으면 **링크를 만들지 않는다**.
#   hub 는 이미 tailscale MagicDNS·설정값을 종합해 advertise_host 를 계산하므로,
#   여기서 tailscale 을 다시 조회하는 것은 같은 규약의 재발명이었다(성숙도만 갈림).
# ⚠️ 종전엔 tailscale 조회가 비면 `<hostname>.local` 로 떨어졌다. 그 폴백의 성질:
#   `.local` 은 mDNS 라 LAN 한정이다. 셀룰러로 Discord 알림을 받은 폰에서는 열리지 않는다.
#   그런데 이 결함은 **발신 머신에서 테스트하면 정상 동작한다** — 죽는 것은 받는 쪽에서만이라
#   만든 사람이 끝까지 모른다. prj3#Issue505(`command -v openclaw` 가 실행 실패를 못 잡음)와
#   같은 계열, 즉 **검사하는 지점과 실패하는 지점이 어긋난** 구조다.
# 반환: "http://host:port" 또는 빈 문자열(= 링크 만들지 않음)
hub_base() {
  curl -s --max-time 3 "http://127.0.0.1:$PORT/healthz" 2>/dev/null \
    | "$JQ" -r '.advertise_url // empty' 2>/dev/null
}

mkdir -p "$QUEUE" "$QDONE" "$HANDOFF" "$HTM_DIR"

log() { printf '%s %s\n' "$("$DATE" '+%Y-%m-%dT%H:%M:%S')" "$*" >> "$LOG"; }

# policy 파서 (flat key: value — board_policy.yml _bp 패턴 동일)
# ── openclaw 발신 래퍼 (prj3#Issue505) ────────────────────────────────────
# 왜 필요한가: 종전 가드는 `command -v openclaw` 였는데, openclaw 는 homebrew 심볼릭
#   링크이고 shebang 이 `#!/usr/bin/env node` 라 **PATH 에 node 가 없으면 탐지는 통과하고
#   실행만 127 로 죽는다**. launchd(hub) 프로세스 PATH 에 nvm 이 빠져 있어 정시 tick 의
#   Discord 발송이 3일간 전부 실패했는데, 호출부가 stderr 를 >/dev/null 로 버려
#   로그에는 "실패(무시)" 만 남았다. 검사하는 것과 실패하는 것이 어긋난 가드였다.
# 따라서 ① 가드를 **실행 기반**으로 바꾸고 ② 실패 시 stderr 마지막 줄과 exit code 를 남긴다.
OC_ERRTAIL=""            # 직전 oc_send 실패의 stderr 마지막 줄 (호출부가 log 에 병기)
oc_ready() { openclaw --version >/dev/null 2>&1; }
oc_send() {              # $@ = openclaw 인자. 성공 0 / 실패 비0 + OC_ERRTAIL 설정
  local _err _rc
  _err=$(openclaw "$@" 2>&1 >/dev/null); _rc=$?
  if [ "$_rc" -ne 0 ]; then
    OC_ERRTAIL="rc=$_rc: $(printf '%s' "$_err" | tail -1)"
  else
    OC_ERRTAIL=""
  fi
  return "$_rc"
}

pol() { # $1=key $2=default
  local v
  v=$(grep -E "^[[:space:]]*$1:" "$POLICY" 2>/dev/null | head -1 \
      | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
  printf '%s' "${v:-$2}"
}

LAST_TICK="$MQ_DIR/.last-tick"                         # 공유 게이트 파일 (prj3#Issue37 F3-4)
SESSION_TOUCH="$MQ_DIR/.last-session-touch"            # MCP 가 갱신하는 세션 활성 마커 (F3-3)

LOCK_STALE_MINS=$(pol lock_stale_mins 30)
RENDER_MAX=$(pol render_max_items 30)
OVERFLOW=$(pol overflow_warn_count 20)
RETENTION=$(pol done_retention_days 0)
ALLOW_POST_EXEC=$(pol allow_post_exec false)          # 사후 셸 자동 spawn 게이트 1/2 (prj3#Issue20)
POST_WL=$(pol post_exec_whitelist "" | tr -d ' ')     # 사후 셸 게이트 2/2 — basename 쉼표 목록
DIGEST_SH="$(dirname "$0")/aoa-mq-digest.sh"           # 읽기용 digest 재생성기 (prj3#Issue20)
ENQUEUE_SH="$(dirname "$0")/aoa-mq-enqueue.sh"         # 등록·재스케줄 helper — snooze 가 --reschedule 로 위임 (prj3#Issue63)
SESSION_WINDOW=$(pol session_active_window 5400)       # 세션 활성 판정 창(초, 기본 90분 — F3-3)

# ── 판정 단일 지점 라이브러리 (prj3#Issue770) ── 대상 prj·승인 술어·기동 한 벌.
#   부재(번들 부분 동기 등)면 그 판정을 쓰는 절(5.1 대기·7.8 기동)만 건너뛰고 나머지는 돈다 —
#   due 전이·inbox 회수까지 멈추면 큐 전체가 선다.
LIB_OK=0
if [ -r "$(dirname "$0")/aoa-mq-lib.sh" ]; then
  # shellcheck source=/dev/null
  . "$(dirname "$0")/aoa-mq-lib.sh" && LIB_OK=1
fi
PROGRESS_SH="$(dirname "$0")/aoa-mq-progress.sh"      # 대기 해제(resume) 단일 경로 — 5.1 이 위임한다

# CSV 멤버십: $1=쉼표목록 $2=값 (사후 whitelist 판정 등)
in_csv() { case ",$1," in *",$2,"*) return 0 ;; *) return 1 ;; esac; }

# ── 0.5 시간 게이트 (옵트인 — prj3#Issue37 F3-4) ─────────────────────────
# 기본(GATE_SEC=0)은 종전 계약 그대로 "호출되면 무조건 실행"이다. 수동 실행·alert kick 이
# 즉시 도는 성질을 깨지 않기 위해서다(설계 SSOT "책임 분리" 절의 근거).
# 게이트를 건 호출자(hub 타이머)만 억제되며, 게이트 파일은 **어느 경로로 실행하든** 갱신되므로
# jmDashboard 가 자기 게이트로 먼저 돌린 tick 도 hub 타이머의 다음 실행을 그만큼 미룬다
# → prj57 을 수정하지 않고도 총 빈도가 ~1회/시간으로 수렴한다.
if [ "$GATE_SEC" -gt 0 ] 2>/dev/null; then
  last_tick_epoch=$("$STAT" -f %m "$LAST_TICK" 2>/dev/null || echo 0)
  elapsed=$(( $("$DATE" +%s) - last_tick_epoch ))
  if [ "$elapsed" -lt "$GATE_SEC" ]; then
    exit 0                                             # 무음 종료 — 로그를 남기면 게이트가 곧 노이즈
  fi
fi

# ── 1. lock (mkdir 원자 락 · 고아 즉시 탈취 → 나이 탈취는 폴백) ─────
# 종전 판정은 **나이만** 봤다. 락을 쥔 프로세스가 죽었다는 사실 자체는 어디서도 확인하지
# 않아, SIGKILL 한 번이면 `lock 보유 tick 진행 중 (0m)` 이 찍히는 동안 실제로는 그 PID 가
# 존재하지 않는 상태가 LOCK_STALE_MINS(30분)까지 이어졌다. 그 사이 정규 tick 까지 전부
# 튕겨 예약 큐 전체가 멈춘다 (2026-09-19 jm4 실측 — prj3#Issue633).
# 처방은 dashboard 의 3-gate eviction(terminal status·heartbeat·liveness)과 같은 것이다.
# 새 설계가 아니라 **적용 누락**이었다.
#
# ⚠️ PID 를 락 디렉토리 **안**이 아니라 형제 파일에 쓰는 이유: prj1 hub 의 고아 락 회수
#    (`_mq_reap_orphan_lock`)가 `os.rmdir` 을 쓰면서 *"락은 빈 디렉토리 — 비어 있지 않으면
#    그건 락이 아니다"* 를 안전 가드로 삼는다. 안에 파일을 만들면 그 회수가 ENOTEMPTY 로
#    죽어, 고치려던 고아 락을 오히려 회수 불능으로 만든다.
mtime_of() {                                          # $1=경로 → epoch(초). 모르면 0
  local m
  m=$("$STAT" -f %m "$1" 2>/dev/null) || m=""         # BSD
  case "$m" in ''|*[!0-9]*) m=$(stat -c %Y "$1" 2>/dev/null) || m="" ;; esac   # GNU 폴백
  case "$m" in ''|*[!0-9]*) m=0 ;; esac
  printf '%s' "$m"
}
lock_owner_pid() {                                    # 락 보유 PID. 모르면 빈 문자열
  local pid
  [ -f "$LOCK_PID" ] || return 0
  # 이전 소유자가 남긴 pid 파일을 현 소유자의 것으로 오인하지 않는다 — pid 는 mkdir 직후
  # 쓰이므로 항상 락 디렉토리와 같거나 더 새롭다. 더 오래됐으면 남의 잔여물이다.
  if [ "$(mtime_of "$LOCK_PID")" -lt "$(mtime_of "$LOCK")" ]; then return 0; fi
  pid=$(cat "$LOCK_PID" 2>/dev/null)
  case "$pid" in ''|*[!0-9]*) return 0 ;; esac
  printf '%s' "$pid"
}
release_lock() {
  # pid 파일은 **내 것일 때만** 지운다 — 탈취당한 뒤라면 그것은 다음 소유자의 것이다.
  if [ "$(cat "$LOCK_PID" 2>/dev/null)" = "$$" ]; then rm -f "$LOCK_PID"; fi
  rmdir "$LOCK" 2>/dev/null
  return 0
}
if ! mkdir "$LOCK" 2>/dev/null; then
  lock_age_min=$(( ( $("$DATE" +%s) - $(mtime_of "$LOCK") ) / 60 ))
  owner_pid=$(lock_owner_pid)
  if [ -n "$owner_pid" ] && ! kill -0 "$owner_pid" 2>/dev/null; then
    log "lock 고아 (pid ${owner_pid} 부재, ${lock_age_min}m) — 나이와 무관하게 즉시 탈취"
    rm -rf "$LOCK"; rm -f "$LOCK_PID"
    mkdir "$LOCK" 2>/dev/null || { log "lock 재획득 실패 — 종료"; exit 0; }
  elif [ "$lock_age_min" -ge "$LOCK_STALE_MINS" ]; then
    # 나이 탈취는 이제 **폴백**이다 — ⓐ 생사를 모를 때(pid 파일 부재·손상·구버전 락)
    # ⓑ 살아는 있으나 멎은 tick. ⓑ 를 남겨 두는 이유는 liveness 만으로 판정하면
    # 교착한 프로세스가 락을 영원히 쥐는 새 고장 모드가 생기기 때문이다.
    log "lock stale (${lock_age_min}m, 보유 pid ${owner_pid:-미상}) — 탈취"
    rm -rf "$LOCK"; rm -f "$LOCK_PID"
    mkdir "$LOCK" 2>/dev/null || { log "lock 재획득 실패 — 종료"; exit 0; }
  else
    log "lock 보유 tick 진행 중 (pid ${owner_pid:-미상}, ${lock_age_min}m) — 즉시 종료"
    exit 0
  fi
fi
printf '%s' "$$" > "$LOCK_PID"
# INT·TERM 도 함께 받는다 — prj1 이 SIGKILL 대신 SIGTERM 을 먼저 보내므로(prj1#Issue502)
# 정상 경로에서는 이 trap 만으로 락이 남지 않는다. EXIT 하나로는 신호를 못 받았다.
trap 'release_lock; exit 143' TERM
trap 'release_lock; exit 130' INT
trap release_lock EXIT

NOW_EPOCH=$("$DATE" +%s)
NOW_ISO=$("$DATE" '+%Y-%m-%dT%H:%M:%S')
: > "$LAST_TICK"                                       # 게이트 파일 갱신 — 호출 경로 무관 (F3-4)
log "tick 시작"

# ── 1.5 세션 활성 판정 (F3-3) ───────────────────────────────────────
# 마커는 MCP 서버(mcp/aoa-mq/server.py)가 initialize·tools/call 마다 갱신한다.
# 활성이면 통지 계층을 건너뛴다 — 세션 쪽 session-inbox 넛지가 같은 사실을 매 프롬프트 전달하므로
# 폼까지 띄우면 같은 알림이 두 경로로 중복된다.
# fail-safe: 마커가 없거나 읽지 못하면 **비활성으로 본다**(통지 수행) — 알림 누락보다 중복이 낫다.
SESSION_ACTIVE=0
# --consume-only 는 통지를 하지 않으므로 이 판정 자체가 불필요하다 — 건너뛴다.
# (판정은 pgrep·tmux 조회를 포함해 수 초가 든다. hub 가 사용자 액션 직후 호출하는 경로라
#  그 시간이 곧 "눌렀는데 안 사라지는 시간" 이 된다.)
if [ "$CONSUME_ONLY" = 0 ] && [ "$FORCE_RENDER" -eq 0 ]; then
  touch_epoch=$("$STAT" -f %m "$SESSION_TOUCH" 2>/dev/null || echo 0)
  if [ "$touch_epoch" -gt 0 ] && [ $(( NOW_EPOCH - touch_epoch )) -lt "$SESSION_WINDOW" ]; then
    SESSION_ACTIVE=1
    log "세션 활성($(( (NOW_EPOCH - touch_epoch) / 60 ))m 전 MCP 접촉) — 통지 계층 skip, 시간축 처리만 수행"
  fi
fi

# due_ts 는 초(:SS) 유무 양쪽 허용 — enqueue helper 는 분 단위(YYYY-MM-DDTHH:MM)도 기록
iso2epoch() {
  # prj3#Issue476: BSD(-j -f) 와 GNU(-d) 를 **둘 다** 시도한다.
  #   종전은 BSD 전용이라 Linux 에서 **항상 0** 을 반환했다 → due 판정이 절대 성립하지
  #   않아 예약이 영원히 pending 에 머문다. fg1 실측(2026-08-30): 5분 뒤 due 항목이
  #   tick 을 지나도 pending 그대로였고 로그에 "due 도달" 이 한 줄도 없었다.
  #   ⚠️ 조용한 실패였다 — `2>/dev/null || echo 0` 이 오류를 삼키고 0 을 내놓는데,
  #      0 은 "1970년" 이라 `<= NOW` 를 만족하지 않아 **아무 일도 안 일어난 것처럼** 보인다.
  "$DATE" -j -f '%Y-%m-%dT%H:%M:%S' "$1" +%s 2>/dev/null \
    || "$DATE" -j -f '%Y-%m-%dT%H:%M' "$1" +%s 2>/dev/null \
    || "$DATE" -d "$1" +%s 2>/dev/null \
    || echo 0
}

# in_progress 착수 기준 시각 — 7.7(통지)·7.8(자동 기동)의 **판정 단일 지점** (prj3#Issue638_2)
#   두 절이 같은 경과를 각자 계산하면 임계가 갈린다("6h 이 넘었다고 통지했는데 기동 쪽은
#   아니라고 본다"). 이 스크립트가 반복해 겪은 *한쪽만 갱신되어 갈라진 계약*이 그것이라
#   계산을 함수 하나로 모은다.
#   `started_at` 이 없거나 파싱 불가면 **파일 mtime 으로 떨어진다** — 기준 시각 부재가 곧
#   감시 면제가 되어서는 안 된다. 그것조차 없으면 0 을 반환하고 호출부가 판정 불가로 로그한다.
wip_base_epoch() { # $1=queue json → 착수 기준 epoch(초). 모르면 0
  local _at _ep=0
  _at=$("$JQ" -r '.started_at // empty' "$1" 2>/dev/null)
  [ -n "$_at" ] && _ep=$(iso2epoch "$_at")
  case "$_ep" in ''|*[!0-9]*|0) _ep=$(mtime_of "$1") ;; esac
  case "$_ep" in ''|*[!0-9]*) _ep=0 ;; esac
  printf '%s' "$_ep"
}

# json 갱신 헬퍼: jq 필터 적용 후 원자 교체
jupd() { # $1=file $2...=jq args
  local f="$1"; shift
  local tmp="$f.tmp.$$"
  if "$JQ" "$@" "$f" > "$tmp" 2>/dev/null; then mv "$tmp" "$f"; else rm -f "$tmp"; log "jq 갱신 실패: $f"; fi
}

finalize() { # $1=file $2=terminal_status  — 종결: 상태 기록 → handoff 기록 → queue_done/ mv → confirm spawn → 결과 통지 (prj3#Issue12/15)
  local f="$1" st="$2" base exec_note=""
  jupd "$f" --arg st "$st" --arg ts "$NOW_ISO" '.status=$st | .acked=true | .ack_ts=$ts'
  base=$(basename "$f")
  # handoff: 응답 스냅샷 + on_response passthrough — spawn 게이트 통과분 외에는 tick 이 해석·실행 안 함
  #   진행 3종(Issue643)을 **있는 것만** 싣는다. 종전 스냅샷은 원본 요청 + 종결 상태뿐이라
  #   *"무엇을 했는가"* 가 0건이었고, 그래서 종결된 뒤에는 결과를 되짚을 길이 아예 없었다.
  #   null 로 채우지 않는 이유는 list·hub 표시와 같다 — 부재가 정상이고 마이그레이션이 없다.
  "$JQ" --arg action "$st" \
    '{id:.id, type:.type, message:.message, source:.source, action:$action, ack_ts:.ack_ts, on_response:(.on_response // null)}
     + (if .claimed_by then {claimed_by:.claimed_by} else {} end)
     + (if .progress   then {progress:.progress}     else {} end)
     + (if .result     then {result:.result, result_ts:(.result_ts // null)} else {} end)' \
    "$f" > "$HANDOFF/$base" 2>/dev/null || log "handoff 기록 실패(무시): $base"
  mv "$f" "$QDONE/$base"
  log "종결($st) → queue_done: $base (handoff 기록)"
  # on_response confirm 자동 실행 (prj3#Issue15) — 이중 게이트: allow_on_confirm_exec(기본 false) + exec_whitelist(기본 빈 값)
  if [ "$st" = "confirmed" ]; then
    local kind cmd wl cmd_base hr_gate
    kind=$("$JQ" -r '.on_response.confirm.kind // empty' "$QDONE/$base" 2>/dev/null)
    cmd=$("$JQ" -r '.on_response.confirm.cmd // empty' "$QDONE/$base" 2>/dev/null)
    if [ "$kind" = "spawn" ] && [ -n "$cmd" ]; then
      if [ "$(pol allow_on_confirm_exec false)" = "true" ]; then
        wl=$(pol exec_whitelist "" | tr -d ' ')
        cmd_base=$(basename "$(printf '%s' "$cmd" | awk '{print $1}')")
        case ",$wl," in
          *",$cmd_base,"*)
            # 스폰 판정 단일 SSOT = fbot-hr-gate (prj3#Issue436_3 s2) — 2단 게이트는 집행층.
            # fail 방향 = fail-closed (계약 축 ⓐ 명령 실행 스폰 — s4 정합화): 게이트 파일 부재·오류
            # 시에도 spawn 취소. 임의 명령이 detached 로 뜨는 경로라 가용성보다 차단이 우선이다.
            hr_gate="$HOME/.claude/hooks/fbot-hr-gate.py"
            if [ ! -f "$hr_gate" ]; then
              log "confirm spawn 취소 — HR 게이트 부재(fail-closed): $cmd_base ($base)"
              exec_note=" · spawn 취소(게이트 부재)"
            elif ! python3 "$hr_gate" check --parent - --depth 0 >> "$MQ_DIR/exec.log" 2>&1; then
              log "confirm spawn 취소 — HR 게이트 거부·오류(fail-closed): $cmd_base ($base)"
              exec_note=" · spawn 취소(HR 게이트)"
            else
              nohup /bin/bash -c "$cmd" >> "$MQ_DIR/exec.log" 2>&1 &
              log "confirm spawn 실행: $cmd_base — $cmd ($base)"
              exec_note=" · spawn 실행: $cmd_base"
            fi ;;
          *)
            log "confirm spawn 거부 — exec_whitelist 미등록: $cmd_base ($base)"
            exec_note=" · spawn 거부(whitelist)" ;;
        esac
      else
        log "confirm spawn 잠금(allow_on_confirm_exec=false) — handoff 기록만: $base"
      fi
    fi
  fi
  # 응답 결과 Discord 통지 (notify_on_response)
  # prj3#Issue574: `post_executed` 는 **기본 억제**한다. 잡을 detached 로 띄우므로
  #   (위 post 블록의 `nohup … &`) tick 은 결과를 알 수 없고, 결과는 **잡이 스스로**
  #   보고한다. 둘 다 보내면 같은 초에 2건이 간다(2026-09-06 실측 — 디스크 보고 +
  #   "응답 접수" 가 16:28:54 에 나란히). 종전 동작이 필요하면 policy 에
  #   `notify_on_post_executed: true`.
  #   ⚠️ 발신 로직이 없는 post 잡은 아무 통지도 안 간다 — 그 책임은 잡에 있다.
  local _notify=1
  if [ "$st" = "post_executed" ] && [ "$(pol notify_on_post_executed false)" != "true" ]; then
    _notify=0
    log "응답 통지 억제(post_executed) — 결과는 잡이 보고한다: $base"
  fi
  if [ "$_notify" = "1" ] && [ "$(pol notify_on_response false)" = "true" ] && oc_ready; then
    local acct tgt m
    acct=$(pol discord_account ""); tgt=$(pol discord_target "")
    if [ -n "$acct" ] && [ -n "$tgt" ]; then
      m=$("$JQ" -r '.message' "$QDONE/$base" 2>/dev/null)
      oc_send message send --channel discord --account "$acct" --target "$tgt" \
        --message "🟢 aoa-mq 응답 접수: \"$m\" → $st ($NOW_ISO)$exec_note" \
        || log "응답 통지 실패: $base — $OC_ERRTAIL"
    fi
  fi
  # 읽기용 digest: 종결 항목을 월단위 archive 에 append + Aoa-mq-list 재생성 (prj3#Issue20)
  [ -x "$DIGEST_SH" ] && "$DIGEST_SH" --archive "$QDONE/$base" >/dev/null 2>&1 || true
}

# ── 2. register (서버 다운 시 fail-soft: 렌더·inbox 만 skip) ────────
TOKEN=""; HASH=""
health=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:$PORT/healthz" 2>/dev/null)
if [ "$health" = "200" ]; then
  cwd_enc=$("$JQ" -rn --arg s "$CWD" '$s|@uri')
  reg=$(curl -s --max-time 5 -X POST "http://127.0.0.1:$PORT/register?cwd=$cwd_enc" 2>/dev/null)
  TOKEN=$(printf '%s' "$reg" | "$JQ" -r '.token // empty' 2>/dev/null)
  HASH=$(printf '%s' "$reg" | "$JQ" -r '.cwd_hash // empty' 2>/dev/null)
fi
[ -z "$TOKEN" ] && log "htm-server 미가용(healthz=$health) — inbox·렌더 skip, 상태 전이만 수행"

# ── 3. inbox 소비 (sid=aoa-mq 격리 + 시그니처 이중 방어) ────────────
consume_inbox() {
  # AOA_MQ_INBOX_DIR — **테스트 전용** 주입구(hub 없이 inbox 소비 경로를 태운다). 운영은 미설정.
  [ -n "$HASH" ] || [ -n "${AOA_MQ_INBOX_DIR:-}" ] || return 0
  local INBOX="${AOA_MQ_INBOX_DIR:-/tmp/___pm/claude-htm-inbox/$HASH/aoa-mq}"
  local f q id action arg mf days new_due
  for f in "$INBOX"/*.json; do
    [ -f "$f" ] || continue
    q=$("$JQ" -r 'if type=="array" then .[0].question else (.question // empty) end' "$f" 2>/dev/null)
    case "$q" in
      aoa-mq-ack:*) ;;
      *) continue ;;  # 자기 시그니처 아님 — 남겨둠 (동시 소비 계약)
    esac
    id=$(printf '%s' "$q" | cut -d: -f2)
    action=$(printf '%s' "$q" | cut -d: -f3)
    arg=$(printf '%s' "$q" | cut -d: -f4)   # snooze 일수 등
    mf="$QUEUE/$id.json"
    if [ ! -f "$mf" ]; then
      log "ACK 대상 없음(이미 종결?): $id — inbox 파일만 제거"
      rm -f "$f"; continue
    fi
    case "$action" in
      start)
        # prj1#Issue424: 착수 — **종결이 아니다**. 큐에 남되 status 만 in_progress 로 바꾼다.
        #   tick 은 headless 라 작업을 스스로 실행할 수 없다(handoff 주석 참조). 그래서
        #   "실행" 이 아니라 **세션에 넘길 표식**을 세우는 것이 이 액션의 전부다 —
        #   session-inbox 넛지가 in_progress 를 "지금 착수할 작업" 으로 올려 세션이 집는다.
        #   질의 대상 선별(pending_items)은 due·done_unacked 만 보므로 진행 중 항목은
        #   자동으로 재질의에서 빠진다 — 하는 중인데 계속 묻는 일이 없다.
        # 🔑 prj3#Issue770 — **승인 기록 단일 지점**. 사람의 [진행] 클릭은 착수 승인이다
        #   (사용자 결정 2026-09-28: [컨펌] 도 착수만 승인 — 비가역 단계는 needs_human 에서 개별 승인).
        #   종전엔 이 사실을 어디에도 남기지 않아 7.8 은 [컨펌] 을 통째로 제외했고, 세션은 [H:*] 를 보면
        #   사람에게 되돌려 **교착**이 났다(20260928-120452-001). 7.8·launch·넛지는 approved_ts 를 읽는다.
        #   승인 주체는 인자(`start:<by>`)로 받을 수 있고, 없으면 hub 클릭으로 기록한다.
        #   대기 잔재(wait_for 등)는 지운다 — 다시 착수했으면 그 대기는 끝났다.
        jupd "$mf" --arg ts "$NOW_ISO" --arg by "${arg:-human:/mq}" \
          '.status="in_progress" | .started_at=$ts | .approved_by=$by | .approved_ts=$ts
           | del(.wait_for, .recheck_ts, .wait_from, .waited_ts)'
        log "착수(in_progress · 승인 ${arg:-human:/mq}): $id" ;;
      confirm) finalize "$mf" confirmed ;;
      dismiss) finalize "$mf" dismissed ;;
      ack)     finalize "$mf" acked_done ;;
      defer)   log "defer(닫기·다음 tick 재표시): $id" ;;  # 비종결 — 상태 유지, 다음 tick 재노출. inbox 파일만 제거(하단 rm)
      snooze)
        # prj3#Issue63: snooze 를 재구현하지 않고 --reschedule 에 **위임**한다.
        #   종전에는 여기서 "지금 시각 +Nd" 를 직접 계산해 원래 시각(19:00 등)이 매번 소실됐다.
        #   due_ts 를 바꾸는 경로를 하나로 모으면 시각 보존이 그쪽 규칙으로 공짜로 따라온다.
        #   AOA_MQ_LOCK_HELD=1 — 이 tick 이 이미 .tick.lock 을 쥐고 있으므로 helper 는 락을 다시 잡지 않는다.
        days="${arg:-1}"
        if AOA_MQ_LOCK_HELD=1 "$ENQUEUE_SH" --reschedule "$id" --due "+${days}d" >/dev/null 2>&1; then
          new_due=$("$JQ" -r '.due_ts // "?"' "$mf" 2>/dev/null)
          log "snooze +${days}d → $new_due: $id (reschedule 위임 · 시각 보존)"
        else
          # fail-loud: 조용히 넘기면 사용자는 "내일 다시"를 눌렀는데 오늘 또 뜬다
          log "snooze 실패 — reschedule helper 오류(due 변경 없음): $id"
        fi ;;
      *) log "알 수 없는 action: $q — skip" ; continue ;;
    esac
    rm -f "$f"
  done
}
consume_inbox
# --consume-only: 여기까지가 상태 전이의 전부다. 이후 단계(watch 폴링·렌더·통지)는
# 사용자 액션과 무관하고 수 분이 걸리므로 태우지 않는다.
if [ "$CONSUME_ONLY" = 1 ]; then log "consume-only 완료 (hub /mq 즉시 반영)"; exit 0; fi

# ── 4. watch 폴링 (board_status + pane_regex — prj3#Issue14) ─────────────
SENT_BASE=$(grep -E '^[[:space:]]*sentinel_base:' "$HOME/_git/___pm/data/board_policy.yml" 2>/dev/null \
            | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
SENT_BASE="${SENT_BASE:-/tmp/___pm}"
# pane_regex 판정용 — fpm-board supervisor IDLE_BOX_RE/BUSY_RE 읽기 전용 차용 (원본 SSOT:
# ~/_git/___pm/plugins/fpm-core/agents/fpm-board-supervisor.sh — 값 변경 시 그쪽 먼저)
IDLE_BOX_RE='╭|╰|❯|⏵⏵'
BUSY_RE='esc to interrupt|esc 로 중단|Running…|Waiting…|shells? still running|tokens·'
TMUX_BIN=$(command -v tmux || echo /opt/homebrew/bin/tmux)
for mf in "$QUEUE"/*.json; do
  [ -f "$mf" ] || continue
  [ "$("$JQ" -r '.status' "$mf")" = "watching" ] || continue
  sig=$("$JQ" -r '.watch.signal_type // empty' "$mf")
  topic=$("$JQ" -r '.watch.topic // empty' "$mf")
  if [ "$sig" = "board_status" ] && [ -n "$topic" ]; then
    # 주의: ls 에 글롭 2개를 함께 주면 한쪽 불일치만으로 exit≠0 → OR 로 분리
    if ls "$SENT_BASE/$topic".*.done >/dev/null 2>&1 || ls "$SENT_BASE/$topic".*.withdrawn >/dev/null 2>&1; then
      jupd "$mf" '.status="done_unacked"'
      log "watch 완료 감지 → done_unacked: $(basename "$mf")"
    fi
  elif [ "$sig" = "pane_regex" ] && [ -n "$topic" ]; then
    # 완료 판정 2경로: (a) 대상 pane 부재(세션 종료) (b) idle 마커 존재 + busy 마커 부재
    # 시간 단위 tick 이므로 단발 판정 (strike 누적 없음 — aoa-mq 는 굵은 감시 소관)
    if [ ! -x "$TMUX_BIN" ]; then
      log "tmux 미가용 — pane_regex 판정 skip: $(basename "$mf")"
    # 존재 확인은 list-panes 사용 — display-message -p 는 대상 부재에도 exit 0 (오판)
    elif ! "$TMUX_BIN" list-panes -t "$topic" >/dev/null 2>&1; then
      jupd "$mf" '.status="done_unacked"'
      log "watch(pane_regex) 대상 부재 → done_unacked: $(basename "$mf") (target=$topic)"
    else
      cap=$("$TMUX_BIN" capture-pane -p -t "$topic" 2>/dev/null | tail -40)
      if printf '%s' "$cap" | grep -qE "$IDLE_BOX_RE" \
         && ! printf '%s' "$cap" | grep -qE "$BUSY_RE"; then
        jupd "$mf" '.status="done_unacked"'
        log "watch(pane_regex) idle 감지 → done_unacked: $(basename "$mf") (target=$topic)"
      fi
    fi
  else
    log "미지원 watch signal_type($sig): $(basename "$mf") — skip"
  fi
done

# ── 5. due 판정 ─────────────────────────────────────────────────────
for mf in "$QUEUE"/*.json; do
  [ -f "$mf" ] || continue
  [ "$("$JQ" -r '.status' "$mf")" = "pending" ] || continue
  due=$("$JQ" -r '.due_ts // empty' "$mf")
  [ -n "$due" ] || continue
  if [ "$(iso2epoch "$due")" -le "$NOW_EPOCH" ] && [ "$(iso2epoch "$due")" -gt 0 ]; then
    jupd "$mf" '.status="due"'
    log "due 도달: $(basename "$mf")"
  fi
done

# ── 5.1 대기(waiting) — 선행 mq 해소 · 재확인 시각 재부상 (prj3#Issue770) ─────
# waiting 은 «조건이 풀리면 다시» 다. 이 절이 그 상태를 **보는 유일한 주체**다 — 모든 비종결 상태에는
#   그것을 보는 절이 하나 있어야 한다(Issue638 계약). 7.7 적체·7.8 기동·넛지는 in_progress 만 보므로
#   waiting 은 거기서 구조적으로 빠진다(틀린 적체 통지·전 세션 주입이 실례 ⓐ 였다).
#   ① wait_for=mq:<id> — 선행이 queue/ 에 없으면(=종결) resume. resume 은 helper 한 경로로 위임한다
#      (원래 상태로만 복귀 — in_progress 를 새로 세우지 않는다는 보장이 거기 있다)
#   ② recheck_ts 도달 — due 로 올려 사람에게 다시 묻는다(재부상). wait_for 는 맥락으로 남긴다
for mf in "$QUEUE"/*.json; do
  [ -f "$mf" ] || continue
  [ "$("$JQ" -r '.status' "$mf")" = "waiting" ] || continue
  wbase=$(basename "$mf"); wid_="${wbase%.json}"
  wfor=$("$JQ" -r '.wait_for // ""' "$mf")
  case "$wfor" in
    mq:*)
      wdep="${wfor#mq:}"
      if [ -n "$wdep" ] && [ ! -f "$QUEUE/$wdep.json" ]; then
        wdst=$("$JQ" -r '.status // "?"' "$QDONE/$wdep.json" 2>/dev/null || echo "?")
        if AOA_MQ_LOCK_HELD=1 bash "$PROGRESS_SH" resume "$wid_" --via "mq:$wdep 종결(${wdst:-?})" >/dev/null 2>&1; then
          log "대기 해제(선행 mq:$wdep 종결 · ${wdst:-?}) → $("$JQ" -r '.status' "$mf" 2>/dev/null): $wbase"
          continue
        else
          log "대기 해제 실패 — resume helper 오류(대기 유지): $wbase"
        fi
      fi ;;
  esac
  wrc=$("$JQ" -r '.recheck_ts // empty' "$mf")
  if [ -z "$wrc" ]; then
    log "⚠️ waiting 인데 recheck_ts 없음 — 즉시 재부상(감시 주체 없는 대기 금지): $wbase"
    jupd "$mf" --arg ts "$NOW_ISO" '.status="due" | .resurfaced_ts=$ts'
    continue
  fi
  wrc_ep=$(iso2epoch "$wrc")
  if [ "$wrc_ep" -gt 0 ] && [ "$wrc_ep" -le "$NOW_EPOCH" ]; then
    jupd "$mf" --arg ts "$NOW_ISO" '.status="due" | .resurfaced_ts=$ts | del(.recheck_ts)'
    log "대기 재확인 시각 도달 → due 재부상: $wbase (조건: $wfor)"
  fi
done

# ── 5.5 사후(kind=post) due 자동 처리 (prj3#Issue20) ─────────────────────
# post 항목은 폼 질의를 거치지 않는다:
#   · 슬래시 명령(/…)      → headless bash 실행 불가 → handoff 위임(판단 가능한 세션이 소비·실행) 후 종결
#   · 셸 명령(whitelist 통과) → detached spawn 실행 후 종결
#   · 셸 명령(게이트 미통과)  → due 로 남겨 아래 질의 렌더(사전과 동일 컨펌 폼)로 fallback ("차등")
for mf in "$QUEUE"/*.json; do
  [ -f "$mf" ] || continue
  [ "$("$JQ" -r '.status' "$mf")" = "due" ] || continue
  [ "$("$JQ" -r '.kind // "pre"' "$mf")" = "post" ] || continue
  # ── 잡 지목 항목 (prj3#Issue691) — whitelist 게이트 대신 schedule 선언을 거친다 ──
  #   선언된 잡만 실행되므로 그 자체가 whitelist 다. 결과는 **동기로** 받아 항목에 남기고
  #   done_unacked 로 올린다 — 사람이 결과를 보고 ACK 한다(조용히 삼키지 않는다).
  #   ⚠️ 동기라 긴 잡은 그동안 tick 을 점유한다. 상한은 잡 선언의 timeout 이다.
  #   멈춘(paused) 잡은 실행되지 않고 사유가 result 에 남는다.
  pjob=$("$JQ" -r '.job // empty' "$mf")
  if [ -n "$pjob" ]; then
    pbase_f=$(basename "$mf"); pid_="${pbase_f%.json}"
    parg=$("$JQ" -r '.job_arg // empty' "$mf")
    SCHED_SH="${AOA_MQ_SCHEDULE_SH:-$HOME/.claude/hooks/schedule.sh}"
    jargs=(dispatch --job "$pjob" --event "mq-$pid_" --json)
    [ -n "$parg" ] && jargs+=(--arg "$parg")
    log "post(job) due → dispatch --job $pjob ($pbase_f)"
    jres=$(bash "$SCHED_SH" "${jargs[@]}" 2>>"$MQ_DIR/exec.log"); jx=$?
    if [ "$jx" -eq 0 ] && printf '%s' "$jres" | "$JQ" -e '.result' >/dev/null 2>&1; then
      jupd "$mf" --argjson r "$jres" --arg ts "$NOW_ISO" \
        '.status="done_unacked" | .job_result=$r.result | .job_rc=$r.rc
         | .result=(if $r.result=="paused" then "잡 \($r.job) 멈춤 상태 — 실행 안 함(paused)"
                    else "잡 \($r.job) → \($r.result) (rc=\($r.rc), 스텝 \($r.steps|length))" end)
         | .result_ts=$ts'
      log "post(job) 결과: $pjob → $(printf '%s' "$jres" | "$JQ" -r '.result') ($pbase_f)"
    else
      jupd "$mf" --arg ts "$NOW_ISO" --arg x "$jx" \
        '.status="done_unacked" | .job_result="error" | .job_rc=($x|tonumber)
         | .result="잡 실행 실패 — schedule.sh dispatch rc=\($x) (exec.log 참조)" | .result_ts=$ts'
      log "post(job) dispatch 실패 rc=$jx: $pjob ($pbase_f)"
    fi
    continue
  fi
  pcmd=$("$JQ" -r '.message' "$mf")
  pfirst=$(printf '%s' "$pcmd" | awk '{print $1}')
  pbase_f=$(basename "$mf")
  case "$pfirst" in
    /*)
      log "post(slash) due → handoff 위임: $pbase_f ($pcmd)"
      finalize "$mf" post_delegated ;;
    *)
      pcmd_base=$(basename "$pfirst")
      if [ "$ALLOW_POST_EXEC" = "true" ] && in_csv "$POST_WL" "$pcmd_base"; then
        # 스폰 판정 단일 SSOT = fbot-hr-gate (prj3#Issue436_3 s4) — 2단 게이트(allow_post_exec+
        # post_exec_whitelist)는 집행층, 판정 로직 복제 금지. fail 방향 = fail-closed (계약 축 ⓐ
        # 명령 실행 스폰): 게이트 파일 부재·오류 시에도 spawn 취소 → 항목은 due 잔류(컨펌 폼 fallback)
        hr_gate="$HOME/.claude/hooks/fbot-hr-gate.py"
        if [ ! -f "$hr_gate" ]; then
          log "post(shell) spawn 취소 — HR 게이트 부재(fail-closed) → 컨펌 폼 fallback: $pcmd_base ($pbase_f)"
        elif ! python3 "$hr_gate" check --parent - --depth 0 >> "$MQ_DIR/exec.log" 2>&1; then
          log "post(shell) spawn 취소 — HR 게이트 거부·오류(fail-closed) → 컨펌 폼 fallback: $pcmd_base ($pbase_f)"
        else
          nohup /bin/bash -c "$pcmd" >> "$MQ_DIR/exec.log" 2>&1 &
          log "post(shell) 자동 spawn: $pcmd_base — $pcmd ($pbase_f)"
          finalize "$mf" post_executed
        fi
      else
        log "post(shell) 게이트 미통과($pcmd_base) → 컨펌 폼 fallback: $pbase_f"
      fi ;;
  esac
done

# ── 6. 질의 렌더 (due + done_unacked → 폼 1장, ACK 전까지 매 tick 재노출) ──
# F3-3: 세션 활성 시 skip — session-inbox 넛지가 매 프롬프트 같은 사실을 전달하므로 중복이다.
# 상태(due/done_unacked)는 이미 위에서 전이됐으므로 다음 tick 이나 MCP `aoa_mq_list` 에서
# 그대로 보인다. 즉 skip 은 **통지만** 미루는 것이지 큐를 정체시키지 않는다.
pending_items=$(ls "$QUEUE"/*.json 2>/dev/null | while read -r mf; do
  st=$("$JQ" -r '.status' "$mf")
  [ "$st" = "due" ] || [ "$st" = "done_unacked" ] && echo "$mf"
done | head -n "$RENDER_MAX")

# prj3#Issue676 — 대기 0건이면 Discord 백오프 카운터를 리셋한다. 이 줄이 없으면 시퀀스가
#   소진된 채로 남아, 다음에 들어온 **새 항목이 첫 통지부터 조용히** 묻힌다.
#   반드시 아래 세션-skip 보다 **먼저** 와야 한다 — skip 은 pending 을 인위적으로 비우므로
#   그 뒤에서 판정하면 "세션이 켜져 있다" 는 이유만으로 카운터가 리셋된다.
[ -z "$pending_items" ] && rm -f "$MQ_DIR/.ask_nag" 2>/dev/null

if [ -n "$pending_items" ] && [ "$SESSION_ACTIVE" -eq 1 ]; then
  log "폼 렌더 skip(세션 활성) — 대기 $(printf '%s\n' "$pending_items" | grep -c .)건은 세션 넛지·MCP list 로 전달"
  pending_items=""
fi

if [ -n "$pending_items" ] && [ -n "$TOKEN" ]; then
  # prj3#Issue676 — **고정 파일명이다. 타임스탬프를 되돌리지 마라.**
  #   종전 `hub_htm_${TS}_b_aoa-mq-ask.htm` 은 회차마다 새 파일을 냈다. 그런데 이 문서의
  #   역할은 아래 주석대로 "그 회차 스냅샷 + 처리 진입점" 이고 **액션이 없다** — 과거 회차를
  #   여는 사람이 없다. 큐 이력은 queue_done/·handoff/·tick.log 가 이미 보존한다.
  #   2026-09-22 실측: 같은 9건이 149회 재노출되며 htm 1340개(17MB)·registry 903엔트리.
  #   고정 이름이 성립하는 근거는 소비처 3곳이 이미 그렇게 돼 있기 때문이다 —
  #     ① /register-doc 는 "동일 path 재등록 시 갱신(dedup)" ② hub 카드 정렬은 전부 mtime
  #     기준이라 덮어쓰면 최상단 ③ 서버에 hub_htm_ 파일명 파서가 없다(타임스탬프 미참조).
  #   부수 효과로 Discord 가 보낸 링크가 항상 최신을 가리킨다(종전엔 회차마다 죽은 링크 1개).
  FORM="$HTM_DIR/hub_htm_b_aoa-mq-ask.htm"
  # ⚠️ 처리 UI 를 여기 두지 않는다 (prj3#Issue493) — hub `/mq` 하나가 소유한다.
  #   종전엔 이 heredoc 이 ACK 버튼까지 자체 렌더했다. prj1#Issue420 이 `/mq` 를 만들면서도
  #   이쪽을 폐기하지 않아 **렌더러가 둘**이 됐고, 뒤이은 prj1#Issue423(즉시 소비)·prj1#Issue424(진행→
  #   완료 2단계)가 `/mq` 만 고쳐 알림으로 열린 화면이 몇 세대 전 동작을 하게 됐다.
  #   2026-09-01 실측: 같은 큐인데 `/mq` 는 진행/완료/연기(N일)/취소, 이 폼은 확인/내일다시/
  #   닫기/드롭 — 사용자에겐 "왜 예전 버전이 뜨나" 로 보인다.
  # 이 문서의 역할은 **그 회차 스냅샷 + 처리 화면 진입점** 둘뿐이다. 액션을 다시 여기 넣으면
  # 같은 표류가 반복된다.
  # 링크는 same-origin 상대경로 — 페이지를 연 host(.local/tailnet MagicDNS 무관)를 그대로 따라간다.
  # file:// 직접 열람 시에만 127.0.0.1 보정 (prj3#Issue17 — 구 하드코딩은 폰에서 "서버 미응답")
  {
    cat <<HTMLHEAD
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" href="/fpm-icon.png">
<title>${CWD_NAME} — aoa-mq 확인 요청</title>
<style>
 body{font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;max-width:820px;margin:0 auto;padding:1rem 1.2rem 3rem;line-height:1.7;color:#222;background:#fff;}
 h1{font-size:1.2rem;background:hsl(186,72%,80%);color:#1a1a1a;padding:0.8rem 1.2rem;border-radius:8px;}
 .lead{color:#555;font-size:0.9rem;margin:0.2rem 0 0;}
 .cta{display:block;text-align:center;margin:1rem 0 1.4rem;padding:0.85rem 1.2rem;border-radius:10px;
  background:hsl(186,72%,85%);border:1px solid hsl(186,50%,50%);color:#0b3a4a;font-size:1.02rem;font-weight:700;text-decoration:none;}
 .cta:hover{background:hsl(186,72%,76%);}
 .card{border:1px solid #ccc;border-radius:10px;padding:0.7rem 1.1rem;margin:0.7rem 0;}
 .card.done{border-color:#7cb87c;background:#f5faf5;}
 .meta{font-size:0.82rem;color:#777;}
 .meta .src{font-weight:700;color:#0b5a7a;background:#e8f4fa;padding:0.05rem 0.45rem;border-radius:4px;}
 @media (prefers-color-scheme:dark){body{background:#16181a;color:#ddd;}.card{border-color:#444;}.card.done{background:#1c2b1c;}
  .lead{color:#aaa;}.meta .src{color:#8fd7ff;background:#173a4a;}
  .cta{background:#1d4f60;border-color:#3d8ba5;color:#d8f2fb;}.cta:hover{background:#246074;}}
</style>
</head>
<body>
<h1>📬 aoa-mq 확인 요청 (${NOW_ISO})</h1>
<p class="lead">아래는 <b>이 시각의 스냅샷</b>입니다. 확인·연기·취소 등 <b>처리는 관리 페이지에서</b> 하십시오 — 목록이 실시간이고 진행→완료 2단계·연기 일수 지정이 됩니다.</p>
<a class="cta" href="/mq">▶ aoa-mq 관리 페이지에서 처리하기</a>
HTMLHEAD
    echo "$pending_items" | while read -r mf; do
      id=$("$JQ" -r '.id' "$mf"); st=$("$JQ" -r '.status' "$mf")
      msg=$("$JQ" -r '.message' "$mf" | sed 's/</\&lt;/g'); typ=$("$JQ" -r '.type' "$mf")
      due=$("$JQ" -r '.due_ts // "-"' "$mf"); asks=$("$JQ" -r '.ask_count' "$mf")
      src=$("$JQ" -r '.source' "$mf" | sed 's/</\&lt;/g')
      if [ "$st" = "due" ]; then
        cat <<CARD
<div class="card"><b>📅 $msg</b>
<div class="meta">id: $id · type: $typ · 발신: <span class="src">$src</span> · 예정: $due · 질의 $asks 회째</div></div>
CARD
      elif [ "$typ" = "alert" ]; then
        cat <<CARD
<div class="card done"><b>🔔 알림: $msg</b>
<div class="meta">id: $id · type: $typ · 발신: <span class="src">$src</span> · 질의 $asks 회째 · 상위 AOA 이벤트</div></div>
CARD
      else
        cat <<CARD
<div class="card done"><b>✅ 완료됨: $msg</b>
<div class="meta">id: $id · type: $typ · 발신: <span class="src">$src</span> · 질의 $asks 회째 · 장기 작업 종료 통지</div></div>
CARD
      fi
    done
    cat <<HTMLTAIL
<a class="cta" href="/mq">▶ aoa-mq 관리 페이지에서 처리하기</a>
<script>
 // file:// 로 직접 열었을 때만 절대 URL 보정. http 로 열렸으면 열린 host 를 그대로 쓴다.
 if(location.protocol==='file:')document.querySelectorAll('.cta').forEach(function(a){a.href='http://127.0.0.1:${PORT}/mq';});
</script>
</body></html>
HTMLTAIL
  } > "$FORM"

  # 채널 에스컬레이션 (prj3#Issue267 → prj3#Issue676 에서 **방향 반전**)
  #   종전: 0회째 → discord 만 · 1회째 → 무통지 · **2회째+ → vscode 강제**.
  #   즉 반복될수록 시끄러워지는 단조 증가였고, 상한이 2 라 149회째까지 매 tick(5분)
  #   브라우저가 강제로 열렸다. 정작 Discord 는 `-eq 0` 이라 149회 중 1번만 갔다 —
  #   조용해야 할 채널이 무한이고 반복 알려야 할 채널이 1회인, 정확히 뒤집힌 상태였다.
  #   현행: **브라우저는 첫 회차 1번만**(사람 주의를 끄는 것은 1회로 족하다) ·
  #         **Discord 는 백오프 시퀀스로 재알림**(아래 ask_nag_backoff_days).
  #   반복 질의 자체는 유지한다 — ACK 전 재노출은 유실 방지가 목적이라 없애면 우회다.
  #   줄어드는 것은 **채널 발화**이지 큐 판정이 아니다.
  # register-doc(hub 등록)은 상태판 갱신 그 자체라 단계 무관 항상 실행.
  max_asks=0
  while read -r mf; do
    a=$("$JQ" -r '.ask_count' "$mf")
    [ "$a" -gt "$max_asks" ] && max_asks=$a
  done <<< "$pending_items"

  # snooze action 은 "snooze:1" 형태 — question 은 aoa-mq-ack:<id>:snooze:1 (cut -f3=snooze, -f4=1)
  curl -s --max-time 5 -X POST "http://127.0.0.1:$PORT/register-doc" \
    -H 'Content-Type: application/json' \
    -d "$("$JQ" -n --arg p "$FORM" --arg c "$CWD" '{type:"htm",path:$p,cwd:$c,title:"aoa-mq 확인 요청"}')" >/dev/null 2>&1
  if [ "$max_asks" -eq 0 ]; then
    curl -s --max-time 5 -X POST "http://127.0.0.1:$PORT/open-simple-browser" \
      -H 'Content-Type: application/json' \
      -d "$("$JQ" -n --arg p "$FORM" '{path:$p}')" >/dev/null 2>&1
    log "open-simple-browser 발화 — 첫 회차(max_asks=0)"
  else
    log "open-simple-browser skip — 재노출 회차(max_asks=$max_asks): 상태판 갱신만"
  fi

  echo "$pending_items" | while read -r mf; do
    jupd "$mf" --arg ts "$NOW_ISO" '.ask_count=(.ask_count+1) | .last_ask_ts=$ts'
  done
  log "질의 렌더: $(echo "$pending_items" | grep -c .) 건 → $FORM"

  # Discord 질의 통지 (notify_on_ask=true 시) — 질문 요약 + 처리 링크. ACK 는 /mq 에서.
  # prj3#Issue676: 종전 조건은 `max_asks -eq 0`, 즉 **첫 due 단 1회**였다. 그래서 149회
  #   재노출되는 동안 Discord 는 처음 한 번만 울렸고, 정작 사람은 "messaging 이 계속
  #   전달하고 있다" 고 여겼다. 여기에 §7.5 handoff 와 **같은 백오프 패턴**을 건다 —
  #   유실 방지(재알림)와 도배 방지(간격·상한)를 한 장치로 동시에 만족시킨다.
  ASK_NAG_STATE="$MQ_DIR/.ask_nag"          # "<last_epoch> <count>" 1줄 — 7.5 NAG_STATE 와 동형
  ask_notify=0; anag_cnt=0
  if [ "$(pol notify_on_ask false)" = "true" ]; then
    ASK_BACKOFF=$(pol ask_nag_backoff_days "0,1,3,7")
    anag_last=0
    [ -f "$ASK_NAG_STATE" ] && read -r anag_last anag_cnt < "$ASK_NAG_STATE" 2>/dev/null
    anag_last=${anag_last:-0}; anag_cnt=${anag_cnt:-0}
    astep=$(printf '%s' "$ASK_BACKOFF" | cut -d, -f$((anag_cnt+1)))
    if [ -z "$astep" ]; then
      log "Discord 질의 통지 백오프 상한 도달(${anag_cnt}회) — 상태판 갱신만, 미발송"
    elif [ $(( $("$DATE" +%s) - anag_last )) -lt $(( astep * 86400 )) ]; then
      log "Discord 질의 통지 백오프 대기(${astep}일 간격, ${anag_cnt}회 발송됨)"
    else
      ask_notify=1
    fi
  fi
  if [ "$ask_notify" -eq 1 ] && oc_ready; then
    DC_ACCOUNT=$(pol discord_account "")
    DC_TARGET=$(pol discord_target "")
    if [ -n "$DC_ACCOUNT" ] && [ -n "$DC_TARGET" ]; then
      SUMMARY=$(echo "$pending_items" | while read -r mf; do
        "$JQ" -r '"• [\(.status)] \(.message)"' "$mf" 2>/dev/null; done | head -10)
      # 링크 블록 — advertise_url 이 없으면 **줄을 빼고 그 사실을 본문에 남긴다** (prj1#Issue469).
      #   localhost 로 때우면 폰에서 안 열리는 링크가 가고, 받는 쪽은 그것이 죽은 링크인지
      #   hub 가 꺼진 것인지 구분할 수 없다. 조용한 누락도 같은 이유로 금지.
      HUB_BASE=$(hub_base)
      if [ -n "$HUB_BASE" ]; then
        # 처리 링크를 먼저 준다 (prj3#Issue493) — 폼은 스냅샷일 뿐이고 버튼은 /mq 에만 있다.
        LINKS="처리: $HUB_BASE/mq
현재 대기 목록: $HUB_BASE/htm-doc?path=$FORM"
      else
        LINKS="(링크 없음 — hub 외부 주소 미설정. hub_setting.yml 의 advertise_host 를 채우면 링크가 붙는다)"
        log "Discord 질의 통지: advertise_url 부재 — 링크 줄 생략(fpm-identity 조항1)"
      fi
      oc_send message send --channel discord --account "$DC_ACCOUNT" --target "$DC_TARGET" \
        --message "📬 aoa-mq 확인 요청 ($NOW_ISO)
$SUMMARY
$LINKS" \
        && { printf '%s %s\n' "$("$DATE" +%s)" "$((anag_cnt+1))" > "$ASK_NAG_STATE"
             log "Discord 질의 통지 발송(${anag_cnt}→$((anag_cnt+1))회): $DC_TARGET"; } \
        || log "Discord 질의 통지 실패 — $OC_ERRTAIL (상태판 렌더는 정상, 다음 tick 재시도)"
    else
      log "Discord 통지 skip — discord_account/discord_target 미설정"
    fi
  fi

  # ask-wait 셀프 폴링 — 렌더 직후 잠깐 inbox 를 재확인해 빠른 클릭을 즉시 종결
  # (없으면 클릭 응답이 다음 tick(최대 1h)까지 queue 에 잔류 — 2026-07-05 실사용 마찰 2회로 신설)
  ASK_WAIT=$(pol ask_wait_secs 180)
  # prj3#Issue593 — 로그 침묵이 "정지" 오진을 낳았다(Issue591 S7). 진입·종료를 반드시 남기고,
  #   진단 경로(--force-render·--no-ask-wait)는 아예 들어가지 않는다.
  if [ "$NO_ASK_WAIT" = "1" ]; then
    log "ask-wait skip (진단 호출) — 클릭 응답은 다음 tick 이 회수한다"
    ASK_WAIT=0
  fi
  if [ "$ASK_WAIT" -gt 0 ] 2>/dev/null; then
    log "ask-wait ${ASK_WAIT}s 진입 — 이 동안 tick 은 반환하지 않는다(5초 간격 inbox 재확인)"
    waited=0
    while [ "$waited" -lt "$ASK_WAIT" ]; do
      sleep 5; waited=$((waited+5))
      consume_inbox
      remain=0
      for mf in "$QUEUE"/*.json; do
        [ -f "$mf" ] || continue
        st=$("$JQ" -r '.status' "$mf")
        if [ "$st" = "due" ] || [ "$st" = "done_unacked" ]; then remain=1; break; fi
      done
      if [ "$remain" = 0 ]; then log "ask-wait: 전원 ACK — ${waited}s 만에 즉시 종결"; break; fi
    done
    [ "$remain" = 1 ] && log "ask-wait ${ASK_WAIT}s 만료 — 미확인 잔여는 다음 tick 재노출"
  fi
fi

# ── 7. 과다 누적 경고 ───────────────────────────────────────────────
# F3-3: 세션 활성 시 skip — 누적 건수는 session-inbox 넛지가 매 프롬프트 숫자로 보여 준다.
qcount=$(ls "$QUEUE"/*.json 2>/dev/null | grep -c . || true)
if [ "${qcount:-0}" -gt "$OVERFLOW" ] && [ "$SESSION_ACTIVE" -eq 0 ]; then
  log "경고: 미종결 ${qcount}건 > ${OVERFLOW} — 과다 누적"
  # 실발송은 openclaw CLI 존재 + 사용자 확인 정책(FIXME: dry-run 무시 특성) 고려해 로그 우선.
fi

# ── 7.5 미소비 handoff — stale 상태 전이 + nag 백오프 (prj3#Issue25 신설 / prj3#Issue26 개편) ──
# prj3#Issue25 는 적체를 "감지·통지"만 했다. 상태가 안 변하니 매 tick 동일 문구가 반복됐고(무한 nag),
# 결국 사용자가 통지를 껐다 — 알림이 행동을 못 만들면 알림 자체가 무력해진다.
# prj3#Issue26 은 두 축을 바꾼다:
#   ① stale 초과분은 **상태를 전이**시킨다 (기본 promote — 대상 prj Issue.md 🌱 이슈후보로 승격).
#      할 일이 우편함이 아니라 사람이 매일 보는 곳에 도착하므로 적체 자체가 해소된다.
#   ② 그래도 남은 잔여분 통지는 **백오프**한다 (1일 → 3일 → 7일 → 중단, 로그만).
HO_SH="$(dirname "$0")/aoa-mq-handoff.sh"
NAG_STATE="$MQ_DIR/.handoff_nag"      # "<last_epoch> <count>" 1줄
HOCOUNT=$(find "$HANDOFF" -maxdepth 1 -type f -name '*.json' 2>/dev/null | grep -c . || true)

if [ "${HOCOUNT:-0}" -eq 0 ]; then
  rm -f "$NAG_STATE"                  # 적체 해소 → 백오프 카운터 리셋
else
  HO_STALE_DAYS=$(pol handoff_stale_days 3)
  HO_STALE=$(find "$HANDOFF" -maxdepth 1 -type f -name '*.json' -mtime +"$HO_STALE_DAYS" 2>/dev/null | grep -c . || true)
  HO_ACTION=$(pol handoff_stale_action promote)

  # ① stale 상태 전이
  if [ "${HO_STALE:-0}" -gt 0 ] && [ -x "$HO_SH" ]; then
    case "$HO_ACTION" in
      promote)
        if [ "$(pol allow_auto_promote true)" = "true" ]; then
          promo=$("$HO_SH" promote-stale --days "$HO_STALE_DAYS" 2>&1 | tail -1)
          log "stale 전이(promote): $promo"
        else
          log "stale 전이 잠금(allow_auto_promote=false) — ${HO_STALE}건 잔류"
        fi ;;
      hold)
        while IFS= read -r hf; do
          [ -n "$hf" ] || continue
          "$HO_SH" hold "$(basename "$hf" .json)" --note "stale ${HO_STALE_DAYS}일 초과 자동 보류" >/dev/null 2>&1 \
            || log "자동 hold 실패(무시): $(basename "$hf")"
        done < <(find "$HANDOFF" -maxdepth 1 -type f -name '*.json' -mtime +"$HO_STALE_DAYS" 2>/dev/null)
        log "stale 전이(hold): ${HO_STALE}건 → .hold" ;;
      dismiss)
        while IFS= read -r hf; do
          [ -n "$hf" ] || continue
          "$HO_SH" 'done' "$(basename "$hf" .json)" --note "stale ${HO_STALE_DAYS}일 초과 자동 dismiss" >/dev/null 2>&1 \
            || log "자동 dismiss 실패(무시): $(basename "$hf")"
        done < <(find "$HANDOFF" -maxdepth 1 -type f -name '*.json' -mtime +"$HO_STALE_DAYS" 2>/dev/null)
        log "stale 전이(dismiss): ${HO_STALE}건 → z_consumed" ;;
      none) log "stale 전이 없음(handoff_stale_action=none) — ${HO_STALE}건 잔류" ;;
      *)    log "stale 전이 스킵 — 알 수 없는 handoff_stale_action='$HO_ACTION'" ;;
    esac
    HOCOUNT=$(find "$HANDOFF" -maxdepth 1 -type f -name '*.json' 2>/dev/null | grep -c . || true)
  fi

  # ② 잔여분 통지 — 백오프 (간격 미도달·상한 초과 시 로그만, Discord 미발송)
  if [ "${HOCOUNT:-0}" -eq 0 ]; then
    rm -f "$NAG_STATE"
    log "미소비 handoff 0건 — 전이·소비 완료"
  else
    log "미소비 handoff ${HOCOUNT}건 (${HO_STALE_DAYS}일 초과: ${HO_STALE:-0}건) — 소비: /mq-handoff"
    BACKOFF=$(pol handoff_nag_backoff_days "1,3,7")
    nag_last=0; nag_cnt=0
    [ -f "$NAG_STATE" ] && read -r nag_last nag_cnt < "$NAG_STATE" 2>/dev/null
    nag_last=${nag_last:-0}; nag_cnt=${nag_cnt:-0}
    step=$(printf '%s' "$BACKOFF" | cut -d, -f$((nag_cnt+1)))
    if [ -z "$step" ]; then
      log "handoff 통지 백오프 상한 도달(${nag_cnt}회) — 로그만, Discord 미발송"
    elif [ $(( $("$DATE" +%s) - nag_last )) -lt $(( step * 86400 )) ]; then
      log "handoff 통지 백오프 대기(${step}일 간격, ${nag_cnt}회 발송됨)"
    elif [ "$(pol notify_on_handoff_stale true)" = "true" ] && oc_ready; then
      ho_acct=$(pol discord_account ""); ho_tgt=$(pol discord_target "")
      if [ -n "$ho_acct" ] && [ -n "$ho_tgt" ]; then
        if oc_send message send --channel discord --account "$ho_acct" --target "$ho_tgt" \
             --message "📥 aoa-mq 미소비 handoff ${HOCOUNT}건 — 응답은 접수됐으나 실제 작업 미착수. 세션에서 \`/mq-handoff\` 실행 요망 (다음 통지는 백오프 적용)"; then
          # 발송 성공분만 카운트 — 실패를 카운트하면 미발송인데 백오프가 벌어진다
          printf '%s %s\n' "$("$DATE" +%s)" "$((nag_cnt+1))" > "$NAG_STATE"
          log "handoff 적체 통지 발송(${nag_cnt}→$((nag_cnt+1))회)"
        else
          log "handoff 적체 통지 실패 — $OC_ERRTAIL"
        fi
      fi
    fi
  fi
fi

# ── 7.6 승격 사후 감사 (prj3#Issue26 후속) ───────────────────────────────
# 승격분은 타 repo 의 uncommitted 작업본이라 다른 세션이 stale 사본으로 덮어쓰면 조용히 사라진다
# (2026-07-20 social 3건 실제 소실 — 승격은 성공했는데 10분 뒤 목적지에서 증발).
# 여기서는 탐지·로깅만 한다. 복구(재등록)는 타 repo 쓰기라 무인 실행하지 않고 사용자에게 위임.
if [ -x "$HO_SH" ]; then
  # 파이프로 받으면 종료코드가 tail 것이 되어 이상을 못 잡는다 — 먼저 받고 나서 자른다
  audit_raw=$("$HO_SH" audit 2>&1); audit_rc=$?
  if [ "$audit_rc" -ne 0 ]; then
    log "승격 감사 이상 — $(printf '%s' "$audit_raw" | tail -1) (복구: aoa-mq-handoff.sh audit --restore)"
  fi
fi

# ── 7.7 in_progress 적체 — 경과 집계 + nag 백오프 (prj3#Issue638_1) ───────
# `/mq` [진행] 은 status 를 in_progress 로 세우고 끝난다. 그런데 질의 대상 선별(6절
# pending_items)은 due·done_unacked 만 보고, stale 정리(7.5)는 handoff/ 만 본다.
# 즉 in_progress 는 시스템 안에서 **감시 주체가 없는 유일한 상태**였다 — 살아 있는 세션이
# 없으면 그 작업은 조용히 유실된다(2026-09-19 실측: 2건이 착수 기록만 남고 무전이 잔류).
# 여기서는 경과를 **알리기만** 한다. 상태 전이·자동 기동은 Issue638_2 의 몫이다 — 통지만으로
# "조용히" 는 사라지고, 헤드리스 세션 기동은 예산이 걸린 별도 결정이기 때문이다.
# 백오프가 필수인 이유는 7.5 와 같다: 매 tick 동일 문구를 보내면 통지 자체가 무력해진다(prj3#Issue26).
# ⚠️ SESSION_ACTIVE 로 억제하지 않는다 — 이 절이 겨냥하는 실패가 정확히 **세션 부재**이고,
#    스크립트의 기존 fail-safe 방향(1.5절 "알림 누락보다 중복이 낫다")과도 같은 쪽이다.
WIP_STALE_HOURS=$(pol wip_stale_hours 6)
WIP_NAG_STATE="$MQ_DIR/.wip_nag"        # "<last_epoch> <count>" 1줄 — 7.5 NAG_STATE 와 같은 형식
WIP_TOTAL=0; WIP_STALE=0; WIP_OLDEST_H=0; WIP_OLDEST_ID=""
WIP_HUMAN=0     # 🙋 사람 차례(needs_human 1건+) 적체 — «아무도 안 집었다» 가 아니라 «사람 몫이 남았다» (Issue770)
for mf in "$QUEUE"/*.json; do
  [ -f "$mf" ] || continue
  # ⚠️ waiting 은 여기 오지 않는다 — status 가 in_progress 인 것만 센다(Issue770 실례 ⓐ 의 틀린 적체 통지)
  [ "$("$JQ" -r '.status' "$mf")" = "in_progress" ] || continue
  WIP_TOTAL=$((WIP_TOTAL+1))
  # 기준 시각 산출은 wip_base_epoch() 단일 지점이다 (prj3#Issue638_2 — 7.8 과 공유)
  wip_ep=$(wip_base_epoch "$mf")
  case "$wip_ep" in ''|*[!0-9]*|0) log "in_progress 경과 판정 불가(기준 시각 없음): $(basename "$mf")"; continue ;; esac
  wip_age_h=$(( (NOW_EPOCH - wip_ep) / 3600 ))
  [ "$wip_age_h" -ge "$WIP_STALE_HOURS" ] || continue
  WIP_STALE=$((WIP_STALE+1))
  [ "$("$JQ" -r '(.needs_human // []) | length' "$mf" 2>/dev/null)" -gt 0 ] 2>/dev/null && WIP_HUMAN=$((WIP_HUMAN+1))
  if [ "$wip_age_h" -gt "$WIP_OLDEST_H" ]; then
    WIP_OLDEST_H=$wip_age_h; WIP_OLDEST_ID=$("$JQ" -r '.id // empty' "$mf" 2>/dev/null)
  fi
done

if [ "$WIP_STALE" -eq 0 ]; then
  [ -f "$WIP_NAG_STATE" ] && { rm -f "$WIP_NAG_STATE"; log "in_progress 적체 해소 — 백오프 카운터 리셋"; }
else
  log "in_progress 적체 ${WIP_STALE}건/착수 ${WIP_TOTAL}건 (사람 차례 ${WIP_HUMAN}건 · 최장 ${WIP_OLDEST_H}h: ${WIP_OLDEST_ID}, 임계 ${WIP_STALE_HOURS}h)"
  WIP_BACKOFF=$(pol wip_nag_backoff_hours "0,24,72")
  wnag_last=0; wnag_cnt=0
  [ -f "$WIP_NAG_STATE" ] && read -r wnag_last wnag_cnt < "$WIP_NAG_STATE" 2>/dev/null
  wnag_last=${wnag_last:-0}; wnag_cnt=${wnag_cnt:-0}
  wstep=$(printf '%s' "$WIP_BACKOFF" | cut -d, -f$((wnag_cnt+1)))
  if [ -z "$wstep" ]; then
    log "in_progress 통지 백오프 상한 도달(${wnag_cnt}회) — 로그만, Discord 미발송"
  elif [ $(( NOW_EPOCH - wnag_last )) -lt $(( wstep * 3600 )) ]; then
    log "in_progress 통지 백오프 대기(${wstep}시간 간격, ${wnag_cnt}회 발송됨)"
  elif [ "$(pol notify_on_wip_stale true)" = "true" ] && oc_ready; then
    wip_acct=$(pol discord_account ""); wip_tgt=$(pol discord_target "")
    if [ -n "$wip_acct" ] && [ -n "$wip_tgt" ]; then
      if oc_send message send --channel discord --account "$wip_acct" --target "$wip_tgt" \
           --message "🔨 aoa-mq 착수 후 정체 ${WIP_STALE}건(그중 🙋 사람 차례 ${WIP_HUMAN}건 — needs_human 확인) — 최장 ${WIP_OLDEST_H}시간(${WIP_OLDEST_ID}). hub \`/mq\` 에서 처리하거나 세션에서 착수 요망 (다음 통지는 백오프 적용)"; then
        # 발송 성공분만 카운트 — 실패를 카운트하면 미발송인데 백오프가 벌어진다 (7.5 와 동일)
        printf '%s %s\n' "$NOW_EPOCH" "$((wnag_cnt+1))" > "$WIP_NAG_STATE"
        log "in_progress 적체 통지 발송(${wnag_cnt}→$((wnag_cnt+1))회)"
      else
        log "in_progress 적체 통지 실패 — $OC_ERRTAIL"
      fi
    else
      log "in_progress 적체 통지 skip — discord_account/target 미설정"
    fi
  fi
fi

# ── 7.8 in_progress 자동 기동 — 헤드리스 세션 spawn (prj3#Issue638_2 · Issue770) ──────
# 7.7 은 경과를 **알리기만** 한다. 사람이 며칠 자리를 비우면 통지가 쌓일 뿐 작업은 그대로
# 멈춰 있다. 이 절이 마지막 한 칸이다 — 임계를 더 넘긴 항목에 `claude -p` 세션을 직접 띄운다.
# 판정은 fbot-hr-gate(5.5 post spawn·finalize confirm spawn 에 이은 **세 번째 호출자**), 기동 형태는
# rules-ondemand/session-delegation-rules.md 의 기동 표준(`-p` + skip-permissions) 그대로다.
#
# 🔴 **게이트 기본값은 닫음이다.** 이 경로는 사람이 그 자리에 없는 상태에서
#   `--dangerously-skip-permissions` 세션을 띄운다 — fbot-org §권한 세탁 금지가 봇
#   자동 기동을 막는 바로 그 형태다. 여기서 그것이 성립하는 근거는 하나뿐이다:
#   **in_progress 는 사람의 [진행] 클릭으로만 진입한다**(tick `start` — approved_ts 기록).
#   waiting 에서의 resume 은 **원래 상태로만** 돌리므로 이 전제를 깨지 않는다(Issue770).
#
# 🔑 **[컨펌] 은 «미승인» 일 때만 제외한다** (Issue770 — 사용자 결정 2026-09-28).
#   종전엔 [컨펌] 을 통째로 제외했다. 그런데 사람이 [진행] 을 눌렀으면 **착수는 승인된 것**이다 —
#   통째 제외가 20260928-120452-001 교착의 한 축이었다(승인했는데 아무도 안 움직인다).
#   비가역 단계(게시·제출)는 세션이 needs_human 에 올리고 멈춘다 — 그 규약은 프롬프트가 싣는다.
#   술어는 lib `aoa_mq_launch_blocked` 하나다(helper `launch`·넛지와 같은 답).
#
# 🙋 **사람 차례(needs_human 1건+)는 띄우지 않는다** — 공이 사람에게 있는데 세션을 띄우면 예산만 샌다.
# ⏳ **waiting 은 status 필터에서 이미 빠진다** — 여기 오지 않는다.
#
# 기동 cwd 는 **대상 prj** 다(lib `aoa_mq_target` — Issue770 원인 ④). 종전엔 $CWD(~/.claude) 고정이라
#   열어도 엉뚱한 곳에서 떴다. 대상 경로가 이 머신에 없으면 띄우지 않는다(엉뚱한 곳보다 안 뜨는 게 낫다).
#
# ⚠️ SESSION_ACTIVE 로 억제하지 않는다 — 7.7 과 같은 이유이고, 임계가 기본 24h 라 살아 있는
#   세션이 하루를 두고 집지 않았다면 "그 세션이 집을 것" 이라는 기대는 이미 틀렸다.
WIP_AUTOSTART=$(pol allow_wip_autostart false)
WIP_WOKE=0
if [ "$WIP_AUTOSTART" != "true" ]; then
  [ "$WIP_STALE" -gt 0 ] && log "in_progress 자동 기동 잠금(allow_wip_autostart=false) — 통지만: 적체 ${WIP_STALE}건"
elif [ "$LIB_OK" != 1 ]; then
  log "in_progress 자동 기동 불가 — aoa-mq-lib.sh 부재(판정 단일 지점 없음, fail-closed)"
elif [ "$WIP_TOTAL" -gt 0 ]; then
  WIP_START_HOURS=$(pol wip_autostart_hours 24)
  WIP_WAKE_BACKOFF=$(pol wip_wake_backoff_hours 24)
  WIP_WAKE_MAX=$(pol wip_wake_max 2)
  WIP_TICK_MAX=$(pol wip_autostart_max_per_tick 1)
  case "$WIP_START_HOURS"  in ''|*[!0-9]*) WIP_START_HOURS=24 ;; esac
  case "$WIP_WAKE_BACKOFF" in ''|*[!0-9]*) WIP_WAKE_BACKOFF=24 ;; esac
  case "$WIP_WAKE_MAX"     in ''|*[!0-9]*) WIP_WAKE_MAX=2 ;; esac
  case "$WIP_TICK_MAX"     in ''|*[!0-9]*) WIP_TICK_MAX=1 ;; esac
  # 기동 임계가 통지 임계보다 이르면 "알리기 전에 띄운다" 가 된다. 값을 조용히 바로잡지
  # 않는다 — 고쳐 주면 policy 파일이 실동작과 갈려 거짓이 된다. 로그로 드러내고 그대로 쓴다.
  [ "$WIP_START_HOURS" -lt "$WIP_STALE_HOURS" ] && \
    log "⚠️ policy 순서 이상 — wip_autostart_hours(${WIP_START_HOURS}h) < wip_stale_hours(${WIP_STALE_HOURS}h): 통지보다 기동이 먼저 온다"
  # claude 바이너리는 **실행으로 확인한다**(lib aoa_mq_claude_bin — Issue505 전례)
  if ! aoa_mq_claude_bin; then
    log "in_progress 자동 기동 불가 — claude 실행 실패(PATH·설치 확인): $MQ_CLAUDE_BIN"
  else
    for mf in "$QUEUE"/*.json; do
      [ -f "$mf" ] || continue
      if [ "$WIP_WOKE" -ge "$WIP_TICK_MAX" ]; then
        log "in_progress 자동 기동 tick 상한 도달(${WIP_TICK_MAX}건) — 나머지는 다음 tick"; break
      fi
      [ "$("$JQ" -r '.status' "$mf")" = "in_progress" ] || continue
      wbase=$(basename "$mf")
      wep=$(wip_base_epoch "$mf")
      case "$wep" in ''|*[!0-9]*|0) continue ;; esac   # 판정 불가는 7.7 이 이미 로그했다
      wage_h=$(( (NOW_EPOCH - wep) / 3600 ))
      [ "$wage_h" -ge "$WIP_START_HOURS" ] || continue
      # 판정 재료는 jq 1회로 — 한 줄에 하나(개행은 공백으로 접는다)
      { IFS= read -r wmsg1; IFS= read -r wappr; IFS= read -r wtgt; IFS= read -r wsrc; IFS= read -r wneed; } < <("$JQ" -r '
          ((.message // "") | gsub("[\n\r]"; " ")), (.approved_ts // ""), (.target // ""),
          ((.source // "") | gsub("[\n\r]"; " ")), ((.needs_human // []) | join(" / ") | gsub("[\n\r]"; " "))' "$mf")
      if aoa_mq_launch_blocked "$wmsg1" "$wappr"; then
        log "in_progress 자동 기동 제외([컨펌] 미승인 — approved_ts 없음, [진행] 재클릭 필요): $wbase (${wage_h}h)"; continue
      fi
      if [ -n "$wneed" ]; then
        log "in_progress 자동 기동 제외(🙋 사람 차례 — needs_human: ${wneed}): $wbase"; continue
      fi
      # ── 중복 기동 방지 ── 5분 tick 이 같은 항목에 매번 세션을 띄우면 예산이 조용히 샌다.
      #   총 기동 상한(wake_count)과 간격(woken_at) 둘 다 본다 — 상한만 두면 그 안에서
      #   연속 5분 간격 기동이 가능하고, 간격만 두면 영구히 반복된다. launch(사람 클릭)도 같은 카운터를 쓴다.
      wcnt=$("$JQ" -r '.wake_count // 0' "$mf")
      case "$wcnt" in ''|*[!0-9]*) wcnt=0 ;; esac
      if [ "$wcnt" -ge "$WIP_WAKE_MAX" ]; then
        log "in_progress 자동 기동 상한 도달(${wcnt}/${WIP_WAKE_MAX}회) — 기동 안 함: $wbase (${wage_h}h)"; continue
      fi
      wwoke_at=$("$JQ" -r '.woken_at // empty' "$mf")
      if [ -n "$wwoke_at" ]; then
        wwoke_ep=$(iso2epoch "$wwoke_at")
        case "$wwoke_ep" in ''|*[!0-9]*) wwoke_ep=0 ;; esac
        # 기록은 있는데 시각을 못 읽으면 **띄우지 않는다**. 백오프 재료가 없는 상태에서 띄우면
        # 매 tick 새 세션이 뜬다 — 여기서는 fail-closed 가 예산을 지키는 쪽이다.
        if [ "$wwoke_ep" -eq 0 ]; then
          log "in_progress 자동 기동 보류 — woken_at 파싱 불가(fail-closed): $wbase ($wwoke_at)"; continue
        fi
        if [ $(( NOW_EPOCH - wwoke_ep )) -lt $(( WIP_WAKE_BACKOFF * 3600 )) ]; then
          log "in_progress 자동 기동 백오프 대기(${WIP_WAKE_BACKOFF}h 간격, ${wcnt}회 기동됨): $wbase"; continue
        fi
      fi
      # 대상 prj 의 cwd (lib 단일 지점) — 이 머신에 없으면 띄우지 않는다
      aoa_mq_target "$wtgt" "$wmsg1" "$wsrc"
      if [ ! -d "$MQ_T_CWD" ]; then
        log "in_progress 자동 기동 취소 — 대상 경로 없음(${MQ_T_PRJ:-미상}/${MQ_T_VIA}: $MQ_T_CWD): $wbase"; continue
      fi
      # ── 판정 단일 SSOT = fbot-hr-gate — 판정 로직을 여기 복제하지 않는다 (prj3#Issue638 명세) ──
      #   fail 방향 = fail-closed. 부재·거부·오류면 띄우지 않고 항목은 in_progress 로 잔류하며,
      #   7.7 의 통지가 계속 나가므로 **조용히 사라지지는 않는다**.
      aoa_mq_hr_gate "$MQ_DIR/exec.log"; wg=$?
      if [ "$wg" -eq 2 ]; then
        log "in_progress 자동 기동 취소 — HR 게이트 부재(fail-closed): $wbase"; continue
      elif [ "$wg" -ne 0 ]; then
        log "in_progress 자동 기동 취소 — HR 게이트 거부·오류(fail-closed): $wbase"; continue
      fi
      wid=$("$JQ" -r '.id // empty' "$mf")
      wmsg=$("$JQ" -r '.message // ""' "$mf")           # 프롬프트엔 원문(개행 보존)
      # 프롬프트는 lib 한 벌(aoa_mq_prompt) — launch(사람 클릭 즉시 기동)와 같은 규약을 싣는다.
      #   argv 로 넘기고 셸을 한 겹도 거치지 않는다(message 는 사용자 자연어라 문자열 조립이 곧 주입 경로).
      wprompt=$(aoa_mq_prompt auto "$wid" "$wmsg" "$wsrc" "$wage_h" "$wneed")
      if ! aoa_mq_spawn "$MQ_T_CWD" "$wid" "$wprompt" "$MQ_DIR/exec.log" "$wmsg"; then   # Issue863_7 — 메시지로 Jev 모델 선택
        log "in_progress 자동 기동 실패 — spawn 불가(cwd=$MQ_T_CWD): $wbase"; continue
      fi
      jupd "$mf" --arg ts "$NOW_ISO" '.woken_at=$ts | .wake_count=((.wake_count // 0) + 1) | .woken_by="tick-7.8"'
      WIP_WOKE=$((WIP_WOKE+1))
      log "in_progress 자동 기동: $wbase (${wage_h}h, ${wcnt}→$((wcnt+1))회, 대상=${MQ_T_PRJ:-미상}/${MQ_T_VIA}, cwd=$MQ_T_CWD, bin=$MQ_CLAUDE_BIN)"
    done
  fi
fi

# ── 8. queue_done retention ────────────────────────────────────────
if [ "$RETENTION" -gt 0 ] 2>/dev/null; then
  find "$QDONE" -name '*.json' -mtime +"$RETENTION" -delete 2>/dev/null
fi

# 읽기용 digest 최종 재생성 — due 전이 등 이번 tick 의 상태 변화 반영 (prj3#Issue20)
[ -x "$DIGEST_SH" ] && "$DIGEST_SH" >/dev/null 2>&1 || true

# 로그 로테이션 (최근 500줄 유지)
[ -f "$LOG" ] && tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
log "tick 종료"
exit 0
