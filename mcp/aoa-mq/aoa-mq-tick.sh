#!/bin/bash
# aoa-mq-tick.sh — aoa-mq 메시지 큐 tick 처리기 (설계 SSOT: _doc_arch/aoa-mq.md)
#
# 호출 계약: 기본은 시간 게이트 없음 — 호출되면 무조건 실행. `--gate <sec>` 를 준 호출자에
# 한해 공유 게이트 파일(.last-tick)로 억제한다(옵트인 — prj3#Issue37 F3-4).
# 자체 가드는 .tick.lock(동시 실행 방지) 하나뿐.
# 트리거: hub 타이머(htm-server daemon thread, 주 구동자) · jmDashboard aoaMqGate() spawn
#         (prj57 prj3#Issue6, 보조) · 수동 직접 실행.
#
# 처리 순서: lock → register → inbox 소비 → watch 폴링 → due 판정 → 질의 렌더
#            → 과다 누적 경고 → queue_done retention
#
# 시간축/통지축 분리 (prj3#Issue37 F3-3): MCP 승격(F3-2) 이후 통지 계층은 세션이 살아 있을 때
# 중복이다 — session-inbox.sh 넛지와 MCP `aoa_mq_list` 가 같은 사실을 이미 전달한다.
# 세션 활성 시에는 통지(inbox 소비·폼 렌더·누적 경고)를 건너뛰고 시간축 고유 처리
# (watch 폴링·due 판정·post 실행·handoff 전이·retention)만 수행한다.
# 완전 제거하지 않는 이유: 세션이 하나도 안 열린 기간은 세션 이벤트 트리거의 사각지대다.

set -u

# ── 0. 인자 파싱 ────────────────────────────────────────────────────
GATE_SEC=0          # >0 이면 .last-tick 기준 그 초 이내 재실행 억제
FORCE_RENDER=0      # 세션 활성이어도 통지 계층 강제 수행
# --consume-only (prj1#Issue423): inbox 소비만 하고 즉시 종료한다.
#   hub /mq 페이지가 액션을 접수한 직후 호출한다 — 종전엔 정규 tick(5분 주기 · 1회 3분
#   소요)을 기다려야 해서 "눌렀는데 목록에서 안 사라진다" 로 보였다. 상태 전이 로직을
#   복제하지 않고 **같은 consume_inbox() 를 태우므로** 소유는 여전히 tick 하나다.
CONSUME_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --gate)         GATE_SEC="${2:-0}"; shift 2 ;;
    --force-render) FORCE_RENDER=1; shift ;;
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
# 외부(tailnet) 기기용 광고 host — MagicDNS hostname 우선 (.Self.DNSName, ex host.tailnet.ts.net).
# IP 무관 고정·전 tailnet 기기 해석·가독성. 과거 raw IP 우회(commit 9031c44)는 jm4 자기해석
# 실패 때문이었으나, 근본원인=macOS 시스템 resolver 의 ts.net split-DNS 누락(tailscaled·MagicDNS
# 정상)으로 재진단되어 /etc/resolver/ts.net(→100.100.100.100) 영속 수리 → hostname 부활.
# hub advertise_host(prj1 prj3#Issue267)와 통일. tailscaled 미가용 시 .local fallback.
TS_BIN=$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)
TS_HOST=$("$TS_BIN" status --json 2>/dev/null | "$JQ" -r '.Self.DNSName // empty' 2>/dev/null | sed 's/\.$//')
ADVERTISE_HOST="${TS_HOST:-host-1.local}"

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

# ── 1. lock (mkdir 원자 락, stale 탈취) ─────────────────────────────
if ! mkdir "$LOCK" 2>/dev/null; then
  lock_age_min=$(( ( $("$DATE" +%s) - $("$STAT" -f %m "$LOCK" 2>/dev/null || echo 0) ) / 60 ))
  if [ "$lock_age_min" -ge "$LOCK_STALE_MINS" ]; then
    log "lock stale (${lock_age_min}m) — 탈취"
    rm -rf "$LOCK"
    mkdir "$LOCK" 2>/dev/null || { log "lock 재획득 실패 — 종료"; exit 0; }
  else
    log "lock 보유 tick 진행 중 (${lock_age_min}m) — 즉시 종료"
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

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
  "$JQ" --arg action "$st" \
    '{id:.id, type:.type, message:.message, source:.source, action:$action, ack_ts:.ack_ts, on_response:(.on_response // null)}' \
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
  if [ "$(pol notify_on_response false)" = "true" ] && oc_ready; then
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
  [ -n "$HASH" ] || return 0
  local INBOX="/tmp/___pm/claude-htm-inbox/$HASH/aoa-mq"
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
        jupd "$mf" --arg ts "$NOW_ISO" '.status="in_progress" | .started_at=$ts'
        log "착수(in_progress): $id" ;;
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

# ── 5.5 사후(kind=post) due 자동 처리 (prj3#Issue20) ─────────────────────
# post 항목은 폼 질의를 거치지 않는다:
#   · 슬래시 명령(/…)      → headless bash 실행 불가 → handoff 위임(판단 가능한 세션이 소비·실행) 후 종결
#   · 셸 명령(whitelist 통과) → detached spawn 실행 후 종결
#   · 셸 명령(게이트 미통과)  → due 로 남겨 아래 질의 렌더(사전과 동일 컨펌 폼)로 fallback ("차등")
for mf in "$QUEUE"/*.json; do
  [ -f "$mf" ] || continue
  [ "$("$JQ" -r '.status' "$mf")" = "due" ] || continue
  [ "$("$JQ" -r '.kind // "pre"' "$mf")" = "post" ] || continue
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

if [ -n "$pending_items" ] && [ "$SESSION_ACTIVE" -eq 1 ]; then
  log "폼 렌더 skip(세션 활성) — 대기 $(printf '%s\n' "$pending_items" | grep -c .)건은 세션 넛지·MCP list 로 전달"
  pending_items=""
fi

if [ -n "$pending_items" ] && [ -n "$TOKEN" ]; then
  TS=$("$DATE" '+%Y%m%d_%H%M%S')
  FORM="$HTM_DIR/hub_htm_${TS}_b_aoa-mq-ask.htm"
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

  # 채널 에스컬레이션 (prj3#Issue267 후속): 배치 내 최대 ask_count 기준 시간당 1단계씩 승급
  #   0회째(첫 due) → discord 만 · 1회째 → 무통지(hub 등록만, 조용히 대기) · 2회째+ → vscode 강제
  # register-doc(hub 등록)은 ack 폼 자체라 단계 무관 항상 실행.
  max_asks=0
  while read -r mf; do
    a=$("$JQ" -r '.ask_count' "$mf")
    [ "$a" -gt "$max_asks" ] && max_asks=$a
  done <<< "$pending_items"

  # snooze action 은 "snooze:1" 형태 — question 은 aoa-mq-ack:<id>:snooze:1 (cut -f3=snooze, -f4=1)
  curl -s --max-time 5 -X POST "http://127.0.0.1:$PORT/register-doc" \
    -H 'Content-Type: application/json' \
    -d "$("$JQ" -n --arg p "$FORM" --arg c "$CWD" '{type:"htm",path:$p,cwd:$c,title:"aoa-mq 확인 요청"}')" >/dev/null 2>&1
  if [ "$max_asks" -ge 2 ]; then
    curl -s --max-time 5 -X POST "http://127.0.0.1:$PORT/open-simple-browser" \
      -H 'Content-Type: application/json' \
      -d "$("$JQ" -n --arg p "$FORM" '{path:$p}')" >/dev/null 2>&1
  else
    log "open-simple-browser skip — 에스컬레이션 단계 미도달(max_asks=$max_asks, hub 등록만)"
  fi

  echo "$pending_items" | while read -r mf; do
    jupd "$mf" --arg ts "$NOW_ISO" '.ask_count=(.ask_count+1) | .last_ask_ts=$ts'
  done
  log "질의 렌더: $(echo "$pending_items" | grep -c .) 건 → $FORM"

  # Discord 질의 통지 (notify_on_ask=true 시) — 1단계(첫 due)에서만. 질문 요약 + 폼 링크. ACK 는 폼에서.
  if [ "$max_asks" -eq 0 ] && [ "$(pol notify_on_ask false)" = "true" ] && oc_ready; then
    DC_ACCOUNT=$(pol discord_account "")
    DC_TARGET=$(pol discord_target "")
    if [ -n "$DC_ACCOUNT" ] && [ -n "$DC_TARGET" ]; then
      SUMMARY=$(echo "$pending_items" | while read -r mf; do
        "$JQ" -r '"• [\(.status)] \(.message)"' "$mf" 2>/dev/null; done | head -10)
      FORM_URL="http://$ADVERTISE_HOST:$PORT/htm-doc?path=$FORM"
      # 처리 링크를 먼저 준다 (prj3#Issue493) — 폼은 스냅샷일 뿐이고 버튼은 /mq 에만 있다.
      MQ_URL="http://$ADVERTISE_HOST:$PORT/mq"
      oc_send message send --channel discord --account "$DC_ACCOUNT" --target "$DC_TARGET" \
        --message "📬 aoa-mq 확인 요청 ($NOW_ISO)
$SUMMARY
처리: $MQ_URL
이 회차 스냅샷: $FORM_URL" \
        && log "Discord 질의 통지 발송: $DC_TARGET" \
        || log "Discord 질의 통지 실패 — $OC_ERRTAIL (폼 렌더는 정상)"
    else
      log "Discord 통지 skip — discord_account/discord_target 미설정"
    fi
  fi

  # ask-wait 셀프 폴링 — 렌더 직후 잠깐 inbox 를 재확인해 빠른 클릭을 즉시 종결
  # (없으면 클릭 응답이 다음 tick(최대 1h)까지 queue 에 잔류 — 2026-07-05 실사용 마찰 2회로 신설)
  ASK_WAIT=$(pol ask_wait_secs 180)
  if [ "$ASK_WAIT" -gt 0 ] 2>/dev/null; then
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
