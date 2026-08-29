#!/usr/bin/env bash
# aoa-mq-enqueue.sh — aoa-mq 큐 메시지 등록 helper (prj5 prj3#Issue10 / prj3 prj3#Issue192)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): 본 helper 는 모든 프로젝트가 공유(prj3 소유 — prj3#Issue436_3 이관).
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   절차: ~/.claude/rules/global-scar-change-rules.md
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md. 규약: ~/.claude/mcp/aoa-mq/aoa-mq.md
#
# 사용법:
#   aoa-mq-enqueue.sh --message <msg> --due <ISO8601|+Nd>    [--source <name>]   # scheduled
#   aoa-mq-enqueue.sh --message <msg> --watch <topic>        [--source <name>]   # watch (board_status)
#   aoa-mq-enqueue.sh --message <msg> --watch-pane <tmux_target> [--source <name>] # watch (pane_regex, prj3#Issue14)
#   aoa-mq-enqueue.sh --message <msg> --alert                [--source <name>]   # alert (즉시 done_unacked, prj3#Issue13)
#   aoa-mq-enqueue.sh --reschedule <id> --due <ISO8601|+Nd|YYYY-MM-DD>           # 재스케줄 (prj3#Issue63)
#   공통 옵션: --on-response '<json>'  — 응답 후속 행동 선언 (handoff passthrough, prj3#Issue12)
#   공통 옵션: --from-bot <bot_id> / --to-bot <bot_id> — 봇 귀속 (prj3#Issue436_3 s4)
#             봇 컨텍스트 발신·수신 시만 지정. 미지정 시 필드 자체 미기록(null 기록 금지) = 비봇(세션·사람) 발신.
#             기존 --source 는 세션 표기라 불변·공존
#   공통 옵션: --kind pre|post  (기본 pre) — 사전(결정·컨펌 대기) / 사후(due 시 자동 처리) 구분 (prj3#Issue20)
#             post + message 가 셸 명령이면 tick 이 whitelist 게이트로 spawn, 슬래시(/…) 면 handoff 위임
#   alert 등록 주체는 즉시성 필요 시 enqueue 직후 aoa-mq-tick.sh 를 1회 직접 kick (설계 SSOT "역할 범위")
#
# 보장:
#   temp 쓰기 → mv 원자 등장 / id 충돌 시 seq 재시도 / 등록 후 존재+jq 파싱 검증
#   성공: "enqueued: <경로>" 1줄 echo (exit 0) / 실패: stderr 사유 + exit≠0 (silent 실패 금지)
#
# ── 재스케줄 (--reschedule, prj3#Issue63) ────────────────────────────────
#   due_ts 를 바꾸는 **1급 경로**. 종전에는 queue/<id>.json 을 손으로 고치고 digest 를 따로
#   돌리는 2단계였고 그 사이에 tick 이 진입하면 queue·digest 가 어긋난 상태가 노출됐다.
#
#   원자성 (prj3#Issue63 확정 ②): temp→mv 만으로는 부족하다. mv 는 **파일 1개**의 원자성만 보장하는데
#     이 이슈의 증상은 "JSON 갱신 ↔ digest 재생성" **구간**에 tick 이 끼어드는 것이다.
#     따라서 tick 과 같은 `.tick.lock`(mkdir 원자 락)을 잡아 상호배제한다.
#     tick 이 자기 lock 을 쥔 채 본 helper 를 부르는 경우(snooze 위임)만 AOA_MQ_LOCK_HELD=1 로 재진입.
#   시각 보존 (prj3#Issue63 확정 ①): `+Nd` 는 **기존 due 의 시각을 유지**하고 날짜만 옮긴다.
#     기준일 = max(오늘, 기존 due 날짜) — 지난 건은 "오늘부터 N일 뒤", 미래 건은 "N일 더 미룸".
#     기존 due 가 없으면 09:00:00. `YYYY-MM-DD` 도 같은 규칙으로 기존 시각을 물려받는다.
#     tick 의 snooze 가 본 경로를 재구현이 아니라 **위임**으로 쓰므로 시각 보존이 그쪽에도 함께 적용된다.
#   ask_count 는 보존한다 — 채널 에스컬레이션은 "몇 번 물었나"의 이력이라 시각 변경으로 지워지지 않는다.

set -u

# 경로 계약 (prj3#Issue450) — AOA_MQ_DIR 은 sandbox 전용이 아니라 **정식 설정**이다.
#   미설정 시 제품 중립 기본으로 떨어진다 (prj5 미클론 머신 대응).
MQ_DIR="${AOA_MQ_DIR:-$HOME/.claude/data/aoa/mq}"
QUEUE_DIR="$MQ_DIR/queue"

die() { echo "aoa-mq-enqueue ERROR: $*" >&2; exit 1; }

JQ=$(command -v jq || echo /usr/bin/jq)
[ -x "$JQ" ] || die "jq 미설치 — brew install jq 후 재시도"
[ -d "$QUEUE_DIR" ] || die "큐 디렉토리 없음: $QUEUE_DIR — aoa-mq 미초기화. AOA_MQ_DIR 확인 또는 'mkdir -p' 로 생성"

MESSAGE="" DUE="" WATCH="" WATCH_PANE="" ALERT="" SOURCE="" ONRESP="" KIND="" RESCHED=""
FROM_BOT="" TO_BOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --message)     MESSAGE="${2:-}"; shift 2 ;;
    --due)         DUE="${2:-}";     shift 2 ;;
    --watch)       WATCH="${2:-}";   shift 2 ;;
    --watch-pane)  WATCH_PANE="${2:-}"; shift 2 ;;
    --alert)       ALERT=1;          shift 1 ;;
    --source)      SOURCE="${2:-}";  shift 2 ;;
    --from-bot)    FROM_BOT="${2:-}"; shift 2 ;;
    --to-bot)      TO_BOT="${2:-}";  shift 2 ;;
    --on-response) ONRESP="${2:-}";  shift 2 ;;
    --kind)        KIND="${2:-}";    shift 2 ;;
    --reschedule)  RESCHED="${2:-}"; shift 2 ;;
    *) die "알 수 없는 인자: $1" ;;
  esac
done

# ── 재스케줄 모드 (--reschedule, prj3#Issue63) ──────────────────────────
# 신규 등록과 완전히 다른 경로다. 여기서 처리하고 종료한다.
if [ -n "$RESCHED" ]; then
  # 등록 전용 인자와 섞이면 의도가 갈린다 — 조용히 무시하지 않고 즉시 거절
  for pair in "message:$MESSAGE" "watch:$WATCH" "watch-pane:$WATCH_PANE" \
              "alert:$ALERT" "kind:$KIND" "on-response:$ONRESP" \
              "from-bot:$FROM_BOT" "to-bot:$TO_BOT"; do
    [ -n "${pair#*:}" ] && die "--reschedule 과 --${pair%%:*} 는 함께 쓸 수 없음 (재스케줄은 due_ts 만 바꾼다)"
  done
  [ -n "$DUE" ] || die "--reschedule 에는 --due 필수 (허용: +Nd | YYYY-MM-DD | YYYY-MM-DDTHH:MM[:SS])"

  TARGET="$QUEUE_DIR/$RESCHED.json"
  if [ ! -f "$TARGET" ]; then
    if [ -f "$MQ_DIR/queue_done/$RESCHED.json" ]; then
      die "이미 종결된 항목: $RESCHED (queue_done/ — 재스케줄 대상 아님. 새로 등록할 것)"
    fi
    die "대상 없음: $RESCHED (경로: $TARGET)"
  fi

  # ── lock: tick 과 상호배제 (prj3#Issue63 확정 ②) ──────────────────────
  # temp→mv 는 파일 1개의 원자성만 준다. 막아야 하는 것은 "JSON 갱신 ↔ digest 재생성" 구간에
  # tick 이 끼어들어 옛 due_ts 로 질의를 띄우거나 digest 를 옛 상태로 덮는 것이므로,
  # tick 이 쓰는 것과 **같은 락**(mkdir 원자 락)을 잡아야 한다.
  LOCK="$MQ_DIR/.tick.lock"
  POLICY="$MQ_DIR/policy.yml"
  LOCK_STALE_MINS=$(grep -E "^[[:space:]]*lock_stale_mins:" "$POLICY" 2>/dev/null | head -1 \
      | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
  LOCK_STALE_MINS="${LOCK_STALE_MINS:-30}"

  # AOA_MQ_LOCK_HELD=1 — 호출자가 이미 lock 을 쥔 경우(tick 의 snooze 위임). 재진입 허용.
  if [ -z "${AOA_MQ_LOCK_HELD:-}" ]; then
    # mtime 조회는 BSD(/usr/bin/stat -f) 절대경로 우선 → GNU(-c) fallback → 0.
    # ⚠️ PATH 의 stat 이 coreutils 면 `-f` 가 --file-system 이라 `File: "…"` 같은 **비숫자**를
    #   뱉는다. 그대로 산술 확장에 넣으면 set -u 아래서 "File: 바인딩 해제한 변수" 로 죽는다
    #   (실측 2026-08-16). 그래서 절대경로 + 숫자 검증 두 겹으로 막는다.
    lock_mtime_of() {
      local m
      m=$(/usr/bin/stat -f %m "$LOCK" 2>/dev/null) || m=""
      case "$m" in ''|*[!0-9]*) m=$(stat -c %Y "$LOCK" 2>/dev/null) || m="" ;; esac
      case "$m" in ''|*[!0-9]*) m=0 ;; esac
      printf '%s' "$m"
    }
    waited=0
    while ! mkdir "$LOCK" 2>/dev/null; do
      lock_mtime=$(lock_mtime_of)
      lock_age_min=$(( ( $(date +%s) - lock_mtime ) / 60 ))
      # stale 탈취 기준은 tick 과 동일 (policy lock_stale_mins, 기본 30분)
      [ "$lock_age_min" -ge "$LOCK_STALE_MINS" ] && rm -rf "$LOCK" 2>/dev/null
      waited=$((waited+1))
      [ "$waited" -gt 10 ] && die "tick 진행 중(lock ${lock_age_min}m) — 10초 대기 후 포기. 잠시 뒤 재시도"
      sleep 1
    done
    trap 'rmdir "$LOCK" 2>/dev/null' EXIT
  fi

  # ── 새 due 산출: 기존 **시각 보존** (prj3#Issue63 확정 ①) ─────────────
  OLD_DUE=$("$JQ" -r '.due_ts // ""' "$TARGET" 2>/dev/null) || die "대상 JSON 파싱 실패: $TARGET"
  OLD_TIME="09:00:00"
  case "$OLD_DUE" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*) OLD_TIME="${OLD_DUE:11:8}" ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9])             OLD_TIME="${OLD_DUE:11:5}:00" ;;
  esac
  TODAY=$(date '+%Y-%m-%d')
  NEW_DUE=""
  case "$DUE" in
    +[0-9]d|+[0-9][0-9]d|+[0-9][0-9][0-9]d)
      n="${DUE#+}"; n="${n%d}"
      # 기준일 = max(오늘, 기존 due 날짜). 지난 건은 "오늘부터 N일 뒤"(= snooze 의미),
      # 미래 건은 "N일 더 미룸". 어느 쪽도 과거로 되돌아가지 않는다.
      base="${OLD_DUE:0:10}"
      if [ -z "$base" ] || [[ "$base" < "$TODAY" ]]; then base="$TODAY"; fi
      nd=$(date -j -v "+${n}d" -f '%Y-%m-%d' "$base" '+%Y-%m-%d' 2>/dev/null) \
        || nd=$(date -d "$base +${n} days" '+%Y-%m-%d' 2>/dev/null) \
        || die "date 계산 실패: base=$base +${n}d"
      NEW_DUE="${nd}T${OLD_TIME}" ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])
      NEW_DUE="${DUE}T${OLD_TIME}" ;;                    # 날짜만 주면 시각은 물려받는다
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]*)
      NEW_DUE="$DUE" ;;                                  # 명시 지정이 최우선
    *) die "--due 형식 오류: '$DUE' (허용: +Nd | YYYY-MM-DD | YYYY-MM-DDTHH:MM[:SS])" ;;
  esac

  # ── JSON 갱신: temp→mv 원자 교체. ask_count 는 보존(에스컬레이션 이력) ──
  RTMP="$TARGET.resched.$$"
  "$JQ" --arg d "$NEW_DUE" '.due_ts=$d | .status="pending"' "$TARGET" > "$RTMP" \
    || { rm -f "$RTMP"; die "jq 갱신 실패: $TARGET"; }
  "$JQ" -e --arg d "$NEW_DUE" '.due_ts==$d and .id and .message' "$RTMP" >/dev/null 2>&1 \
    || { rm -f "$RTMP"; die "갱신본 사후 검증 실패 — 원본 보존: $TARGET"; }
  mv "$RTMP" "$TARGET" || { rm -f "$RTMP"; die "원자 교체 실패: $TARGET"; }

  # digest 재생성까지가 한 묶음이다 — 여기서 끝내야 queue·digest 가 어긋난 창이 안 생긴다
  DIGEST="$(dirname "$0")/aoa-mq-digest.sh"
  if [ -x "$DIGEST" ]; then
    "$DIGEST" >/dev/null 2>&1 || echo "aoa-mq-enqueue WARN: digest 재생성 실패 — Aoa-mq-list.md 가 구 상태일 수 있음" >&2
  fi

  echo "rescheduled: $TARGET (id=$RESCHED, due: ${OLD_DUE:--} → $NEW_DUE, status=pending)"
  exit 0
fi

# kind 정규화: 미지정=pre(사전). pre|post 만 허용 (prj3#Issue20)
[ -z "$KIND" ] && KIND="pre"
case "$KIND" in
  pre|post) ;;
  *) die "--kind 는 pre|post 만 허용 (받음: '$KIND')" ;;
esac

[ -n "$MESSAGE" ] || die "--message 필수"
# 모드 4종 택1: --due / --watch / --watch-pane / --alert
mode_count=0
[ -n "$DUE" ]        && mode_count=$((mode_count+1))
[ -n "$WATCH" ]      && mode_count=$((mode_count+1))
[ -n "$WATCH_PANE" ] && mode_count=$((mode_count+1))
[ -n "$ALERT" ]      && mode_count=$((mode_count+1))
[ "$mode_count" -eq 1 ] || die "--due | --watch <topic> | --watch-pane <tmux_target> | --alert 중 정확히 하나 필수"
[ -z "$SOURCE" ] && SOURCE="claude@$(basename "$PWD")"
# on_response: 자유 JSON passthrough (prj3#Issue12) — tick 은 해석·실행 안 함, handoff 로 전달만
if [ -n "$ONRESP" ]; then
  printf '%s' "$ONRESP" | "$JQ" -e . >/dev/null 2>&1 || die "--on-response 가 유효한 JSON 이 아님"
fi

# due 정규화: +Nd → N일 후 09:00 / YYYY-MM-DD → T09:00:00 부여 / ISO8601 그대로
DUE_TS=""
if [ -n "$DUE" ]; then
  case "$DUE" in
    +[0-9]d|+[0-9][0-9]d|+[0-9][0-9][0-9]d)
      n="${DUE#+}"; n="${n%d}"
      # BSD(-v) 우선, GNU(-d) fallback — PATH 의 coreutils date 대비
      DUE_TS=$(date -v "+${n}d" '+%Y-%m-%dT09:00:00' 2>/dev/null) \
        || DUE_TS=$(date -d "+${n} days" '+%Y-%m-%dT09:00:00' 2>/dev/null) \
        || die "date 계산 실패: $DUE" ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])
      DUE_TS="${DUE}T09:00:00" ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]*)
      DUE_TS="$DUE" ;;
    *) die "--due 형식 오류: '$DUE' (허용: +Nd | YYYY-MM-DD | YYYY-MM-DDTHH:MM[:SS])" ;;
  esac
fi

NOW_ISO=$(date '+%Y-%m-%dT%H:%M:%S')
BASE=$(date '+%Y%m%d-%H%M%S')

if [ -n "$WATCH" ]; then
  TYPE="watch"; STATUS="watching"; SIGNAL="board_status"; TOPIC="$WATCH"
elif [ -n "$WATCH_PANE" ]; then
  TYPE="watch"; STATUS="watching"; SIGNAL="pane_regex"; TOPIC="$WATCH_PANE"
elif [ -n "$ALERT" ]; then
  TYPE="alert"; STATUS="done_unacked"; SIGNAL=""; TOPIC=""
else
  TYPE="scheduled"; STATUS="pending"; SIGNAL=""; TOPIC=""
fi

# JSON 은 jq -n 으로 생성 (이스케이프 보장 — 즉흥 heredoc 조립 금지)
# from_bot/to_bot (prj3#Issue436_3 s4): 지정 시만 최상위 필드로 기록 — 미지정 시 필드 자체 미기록
# (null 기록 금지). 부재 = 비봇(세션·사람) 발신 해석의 근거이므로 빈 값·null 을 남기면 판정이 흐려진다.
build_json() { # $1=id
  "$JQ" -n \
    --arg id "$1" --arg type "$TYPE" --arg kind "$KIND" --arg created "$NOW_ISO" \
    --arg due "$DUE_TS" --arg msg "$MESSAGE" --arg signal "$SIGNAL" --arg topic "$TOPIC" \
    --arg status "$STATUS" --arg source "$SOURCE" \
    --arg fbot "$FROM_BOT" --arg tbot "$TO_BOT" \
    --argjson onresp "${ONRESP:-null}" \
    '{id:$id, type:$type, kind:$kind, created_ts:$created,
      due_ts:(if $due=="" then null else $due end),
      message:$msg,
      watch:(if $type=="watch" then {signal_type:$signal, topic:$topic} else null end),
      on_response:$onresp, status:$status, ask_count:0, last_ask_ts:null,
      acked:false, ack_ts:null, source:$source}
     + (if $fbot=="" then {} else {from_bot:$fbot} end)
     + (if $tbot=="" then {} else {to_bot:$tbot} end)'
}

# id 채번 + temp→mv 원자 등장 (충돌 시 seq 재시도, 최대 999)
DEST=""
seq=1
while [ $seq -le 999 ]; do
  ID=$(printf '%s-%03d' "$BASE" "$seq")
  CAND="$QUEUE_DIR/$ID.json"
  # queue_done/ 도 충돌 검사 — 같은 초에 등록→종결→재등록 시 이력 덮어쓰기 방지
  if [ ! -e "$CAND" ] && [ ! -e "$MQ_DIR/queue_done/$ID.json" ]; then
    TMP=$(mktemp "$QUEUE_DIR/.enqueue.XXXXXX") || die "temp 생성 실패: $QUEUE_DIR"
    build_json "$ID" > "$TMP" || { rm -f "$TMP"; die "JSON 생성 실패 (jq)"; }
    mv -n "$TMP" "$CAND" 2>/dev/null
    if [ -e "$TMP" ]; then rm -f "$TMP"; seq=$((seq+1)); continue; fi   # 충돌 — 재시도
    DEST="$CAND"; break
  fi
  seq=$((seq+1))
done
[ -n "$DEST" ] || die "id 채번 실패 (seq 999 초과): $BASE"

# 사후 검증: 존재 + jq 파싱 + 필수 필드
[ -s "$DEST" ] || die "등록 후 파일 부재/빈 파일: $DEST"
"$JQ" -e '.id and .type and .message and .status' "$DEST" >/dev/null 2>&1 \
  || { echo "aoa-mq-enqueue ERROR: 사후 jq 검증 실패 — 손상 파일 격리: $DEST.bad" >&2; mv "$DEST" "$DEST.bad"; exit 1; }

# 봇 귀속 표기 — 있는 항목만 (prj3#Issue436_3 s4)
BOT_NOTE=""
[ -n "$FROM_BOT" ] && BOT_NOTE="$BOT_NOTE, from_bot=$FROM_BOT"
[ -n "$TO_BOT" ]   && BOT_NOTE="$BOT_NOTE, to_bot=$TO_BOT"
case "$TYPE" in
  scheduled) echo "enqueued: $DEST (type=scheduled, kind=$KIND, due=$DUE_TS, source=$SOURCE$BOT_NOTE)" ;;
  watch)     echo "enqueued: $DEST (type=watch, kind=$KIND, signal=$SIGNAL, topic=$TOPIC, source=$SOURCE$BOT_NOTE)" ;;
  alert)     echo "enqueued: $DEST (type=alert, kind=$KIND, status=done_unacked, source=$SOURCE$BOT_NOTE) — 즉시 통지 원하면 aoa-mq-tick.sh 1회 kick" ;;
esac

# 읽기용 digest(Aoa-mq-list.md) 재생성 — 등록 즉시 현황 반영 (prj3#Issue20). 실패해도 등록 자체는 성공 유지
DIGEST="$(dirname "$0")/aoa-mq-digest.sh"
[ -x "$DIGEST" ] && "$DIGEST" >/dev/null 2>&1 || true
