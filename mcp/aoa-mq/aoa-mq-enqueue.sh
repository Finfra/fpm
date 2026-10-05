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
#   aoa-mq-enqueue.sh --job <잡> [--arg V] --due <…> [--message <msg>]           # 잡 지목 예약 (prj3#Issue691)
#             선언된 잡(schedule.sh)만 지목 가능 — 등록 시 존재 검증, 없으면 exit≠0.
#             kind 는 post 고정. due 가 오면 tick 이 `schedule.sh dispatch --job` 으로 실행하고
#             결과(result·rc)를 항목에 기록한 뒤 done_unacked 로 올린다. --message 는 생략 가능(자동 생성)
#   공통 옵션: --on-response '<json>'  — 응답 후속 행동 선언 (handoff passthrough, prj3#Issue12)
#   공통 옵션: --from-bot <bot_id> / --to-bot <bot_id> — 봇 귀속 (prj3#Issue436_3 s4)
#             봇 컨텍스트 발신·수신 시만 지정. 미지정 시 필드 자체 미기록(null 기록 금지) = 비봇(세션·사람) 발신.
#             기존 --source 는 세션 표기라 불변·공존
#   공통 옵션: --target prj<N> — 이 항목을 수행할 프로젝트 (prj3#Issue770). 넛지 범위·기동 cwd 의 1순위 근거.
#             생략하면 message 첫 prjN 토큰 → source 프로젝트 순으로 판정한다(aoa-mq-lib.sh aoa_mq_target).
#             번호는 ~/_git/___pm/projects/{N} 에 있어야 한다 — 매핑 없는 번호는 거부(오타가 곧 방송이 되므로)
#   공통 옵션: --json — 성공 출력을 산문 대신 1줄 JSON 으로 (prj3#Issue808 · 명세 prj3#Issue811)
#             {"id","path","type","kind","due","source","target"} — 호출자가 경로를 splitext 로 자르지 않게 한다
#             (cwd 이름의 `.`(`.claude`)에서 잘못 잘리던 함정). 실패 경로(stderr+exit≠0)는 불변
#   공통 옵션: --kind pre|post  (기본 pre) — 사전(결정·컨펌 대기) / 사후(due 시 자동 처리) 구분 (prj3#Issue20)
#             post + message 가 셸 명령이면 tick 이 whitelist 게이트로 spawn, 슬래시(/…) 면 handoff 위임
#   alert 등록 주체는 즉시성 필요 시 enqueue 직후 aoa-mq-tick.sh 를 1회 직접 kick (설계 SSOT "역할 범위")
#
# 보장:
#   temp 쓰기 → mv 원자 등장 / id 충돌 시 seq 재시도 / 등록 후 존재+jq 파싱 검증
#   성공: "enqueued: <경로>" 1줄 echo (exit 0) — --json 이면 1줄 JSON / 실패: stderr 사유 + exit≠0 (silent 실패 금지)
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
FROM_BOT="" TO_BOT="" JOB="" JOB_ARG="" TARGET_PRJ="" OUT_JSON=""
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
    --job)         JOB="${2:-}";     shift 2 ;;
    --arg)         JOB_ARG="${2:-}"; shift 2 ;;
    --target)      TARGET_PRJ="${2:-}"; shift 2 ;;
    --json)        OUT_JSON=1;       shift 1 ;;
    *) die "알 수 없는 인자: $1" ;;
  esac
done

# ── 재스케줄 모드 (--reschedule, prj3#Issue63) ──────────────────────────
# 신규 등록과 완전히 다른 경로다. 여기서 처리하고 종료한다.
if [ -n "$RESCHED" ]; then
  # 등록 전용 인자와 섞이면 의도가 갈린다 — 조용히 무시하지 않고 즉시 거절
  for pair in "message:$MESSAGE" "watch:$WATCH" "watch-pane:$WATCH_PANE" \
              "alert:$ALERT" "kind:$KIND" "on-response:$ONRESP" \
              "from-bot:$FROM_BOT" "to-bot:$TO_BOT" "job:$JOB" "target:$TARGET_PRJ"; do
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

  # ── lock: tick 과 상호배제 (prj3#Issue63 확정 ② · Issue643 라이브러리화) ──
  # temp→mv 는 파일 1개의 원자성만 준다. 막아야 하는 것은 "JSON 갱신 ↔ digest 재생성" 구간에
  # tick 이 끼어들어 옛 due_ts 로 질의를 띄우거나 digest 를 옛 상태로 덮는 것이므로,
  # tick 이 쓰는 것과 **같은 락**(mkdir 원자 락)을 잡아야 한다.
  #
  # ⚠️ 구현은 [aoa-mq-lock.sh](aoa-mq-lock.sh) 로 옮겼다 (Issue643) — 큐를 **짧게 고치고 빠지는**
  #   쓰기 주체가 `--reschedule` 과 `aoa-mq-progress.sh` 둘이 되면서, 각자 구현하면 고아 락
  #   판정·탈취 임계가 갈린다. 재진입(AOA_MQ_LOCK_HELD)·고아 탈취·trap 해제는 종전과 동일하다.
  # shellcheck source=/dev/null
  . "$(dirname "$0")/aoa-mq-lock.sh"
  aoa_mq_lock_acquire 10

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
  # 대기 잔재 제거 (prj3#Issue770) — 연기는 «날짜가 오면 다시 묻는다» 로 대기를 대체한다.
  #   wait_for 가 남으면 hub 가 pending 항목을 «대기 중» 으로 오표시한다.
  "$JQ" --arg d "$NEW_DUE" '.due_ts=$d | .status="pending" | del(.wait_for, .recheck_ts, .wait_from, .waited_ts)' "$TARGET" > "$RTMP" \
    || { rm -f "$RTMP"; die "jq 갱신 실패: $TARGET"; }
  "$JQ" -e --arg d "$NEW_DUE" '.due_ts==$d and .id and .message' "$RTMP" >/dev/null 2>&1 \
    || { rm -f "$RTMP"; die "갱신본 사후 검증 실패 — 원본 보존: $TARGET"; }
  mv "$RTMP" "$TARGET" || { rm -f "$RTMP"; die "원자 교체 실패: $TARGET"; }

  # digest 재생성까지가 한 묶음이다 — 여기서 끝내야 queue·digest 가 어긋난 창이 안 생긴다
  DIGEST="$(dirname "$0")/aoa-mq-digest.sh"
  if [ -x "$DIGEST" ]; then
    "$DIGEST" >/dev/null 2>&1 || echo "aoa-mq-enqueue WARN: digest 재생성 실패 — Aoa-mq-list.md 가 구 상태일 수 있음" >&2
  fi

  if [ -n "$OUT_JSON" ]; then
    "$JQ" -nc --arg id "$RESCHED" --arg path "$TARGET" --arg due "$NEW_DUE" --arg old "$OLD_DUE" \
      '{id:$id, path:$path, due:$due, old_due:(if $old=="" then null else $old end), status:"pending"}'
  else
    echo "rescheduled: $TARGET (id=$RESCHED, due: ${OLD_DUE:--} → $NEW_DUE, status=pending)"
  fi
  exit 0
fi

# kind 정규화: 미지정=pre(사전). pre|post 만 허용 (prj3#Issue20)
KIND_RAW="$KIND"      # --job 판정용 — 기본값(pre) 채우기 전 원본
[ -z "$KIND" ] && KIND="pre"
case "$KIND" in
  pre|post) ;;
  *) die "--kind 는 pre|post 만 허용 (받음: '$KIND')" ;;
esac

# ── 잡 지목 (--job, prj3#Issue691) ─────────────────────────────────────
#   큐는 잡을 **지목할 뿐**이다(schedule-arch.md «dispatch --job» 경계) — 무엇을 실행하는지는 schedule 선언이 정본이다.
#   존재 검증은 등록 시점에 한다. 실행 시점에 없으면 tick 이 결과로 기록하지만, 오타를 due 까지
#   묵혀 두면 «예약했는데 안 돌았다» 가 며칠 뒤에야 드러난다.
if [ -n "$JOB" ] || [ -n "$JOB_ARG" ]; then
  [ -n "$JOB" ] || die "--arg 는 --job 과 함께만 쓴다"
  [ -n "$DUE" ] || die "--job 은 --due 와 함께 쓴다 (잡 지목은 예약이다)"
  [ -z "$WATCH$WATCH_PANE$ALERT" ] || die "--job 은 --watch·--watch-pane·--alert 와 함께 쓸 수 없다"
  [ -z "$KIND_RAW" ] || [ "$KIND_RAW" = post ] || die "--job 항목의 kind 는 post 고정이다 (받음: $KIND_RAW)"
  KIND="post"
  SCHED_SH="${AOA_MQ_SCHEDULE_SH:-$HOME/.claude/hooks/schedule.sh}"
  [ -f "$SCHED_SH" ] || die "schedule.sh 없음: $SCHED_SH"
  jobs_json=$(bash "$SCHED_SH" catalog --json 2>/dev/null) || die "잡 목록 조회 실패 (schedule.sh catalog)"
  printf '%s' "$jobs_json" | "$JQ" -e --arg j "$JOB" '[.jobs[].name] | index($j) != null' >/dev/null 2>&1 \
    || die "선언에 없는 잡: $JOB — schedule.sh 에 선언된 잡만 지목할 수 있다"
  [ -n "$MESSAGE" ] || MESSAGE="잡 실행: ${JOB}${JOB_ARG:+ ⟨${JOB_ARG}⟩}"
fi

[ -n "$MESSAGE" ] || die "--message 또는 --job 중 하나는 필수"
# 모드 4종 택1: --due / --watch / --watch-pane / --alert
mode_count=0
[ -n "$DUE" ]        && mode_count=$((mode_count+1))
[ -n "$WATCH" ]      && mode_count=$((mode_count+1))
[ -n "$WATCH_PANE" ] && mode_count=$((mode_count+1))
[ -n "$ALERT" ]      && mode_count=$((mode_count+1))
[ "$mode_count" -eq 1 ] || die "--due | --watch <topic> | --watch-pane <tmux_target> | --alert 중 정확히 하나 필수"
[ -z "$SOURCE" ] && SOURCE="claude@$(basename "$PWD")"

# ── 대상 prj (prj3#Issue770) — 형식 + 매핑 검증. 조용히 받아 두면 오타 항목이 «대상 미상» 으로
#   떨어져 전 세션 넛지(방송)가 된다 — 이 이슈가 고치려는 바로 그 증상이다.
if [ -n "$TARGET_PRJ" ]; then
  # shellcheck source=/dev/null
  . "$(dirname "$0")/aoa-mq-lib.sh"
  aoa_mq_check_target "$TARGET_PRJ" || die "--target $MQ_TV_ERR"   # 검증 단일 지점 — retarget 과 같은 규칙(Issue925)
fi

# ── [컨펌] 등록 게이트 (prj3#Issue756) ─────────────────────────────────
#   mq [컨펌] 은 H 등급(사람만 정할 수 있는 것) 전용 창구다. C(총괄 전결)·L(팀장 전결)이
#   같은 창구로 오면 H 가 묻힌다 — 2026-09-28 실측: 사람에게 온 결정의 75% 가 C·L 이었다.
#   그래서 머리에 `[H:<분류>]` 가 없으면 등록하지 않는다. 분류 목록은 정책 파일이 정본이다.
#   exit 5 = 등급 게이트 거부(인자 오류 1 과 구분 — 호출자가 «C·L 로 처리하라» 로 읽는다).
#   예외: 사람이 hub 화면에서 누른 요청(정책 `exempt_sources` 와 **정확히 같은** --source)은 이미 사람의 행동이다.
#   머리 판정은 앞 공백·장식(이모지 등)을 무시한다 — 소비처(tick·mq-send)는 [컨펌] 을 «포함» 으로 읽으므로
#   «🔴 [컨펌] …» 이 게이트를 비켜 가면 사람 창구에 태그 없는 항목이 다시 선다(독립 검토 지적).
_pol() { sed -n "s/^$1:[[:space:]]*//p" "$POLICY" | head -1 | tr -d '\r'; }
_head="${MESSAGE#"${MESSAGE%%[![:space:]]*}"}"                       # 앞 공백 제거
_pre="${_head%%\[컨펌\]*}"                                          # [컨펌] 앞 장식
case "$_head" in *"[컨펌]"*) _is_confirm=1 ;; *) _is_confirm=0 ;; esac
[ "$_is_confirm" = 1 ] && [ "${#_pre}" -gt 12 ] && _is_confirm=0      # 본문 중간 언급은 [컨펌] 항목이 아니다(12 = 이모지 2개 바이트까지 — C 로케일 대비)
if [ "$_is_confirm" = 1 ]; then
  POLICY="${AOA_DECISION_POLICY:-$HOME/.claude/data/decision-authority.yml}"
  [ -f "$POLICY" ] || die "결정 권한 정책 없음: $POLICY — [컨펌] 등급 판정 불가(조용히 통과시키지 않는다)"
  gate=1
  exempt="$(_pol exempt_sources)"
  if [ -n "$exempt" ]; then
    IFS=',' read -r -a _ex <<< "$exempt"
    for p in "${_ex[@]}"; do p="${p// /}"; [ -n "$p" ] && [ "$SOURCE" = "$p" ] && gate=0; done
  fi
  if [ "$gate" = 1 ]; then
    cats="$(_pol h_categories)"
    [ -n "$cats" ] || die "결정 권한 정책에 h_categories 없음: $POLICY"
    rest="${_head#*\[컨펌\]}"; rest="${rest#"${rest%%[![:space:]]*}"}"   # 태그 앞 공백 제거
    tag=""
    case "$rest" in "[H:"*"]"*) tag="${rest#\[H:}"; tag="${tag%%\]*}"; tag="${tag// /}" ;; esac
    hit=0
    IFS=',' read -r -a _cats <<< "$cats"
    for c in "${_cats[@]}"; do [ -n "$tag" ] && [ "${c// /}" = "$tag" ] && hit=1; done
    if [ "$hit" != 1 ] || [ -n "$_pre" ]; then
      echo "aoa-mq-enqueue ERROR: [컨펌] 은 H 등급 전용이다 — 메시지 **맨 앞**에 '[컨펌] [H:<분류>]' 가 필요하다 (받음: '${tag:-태그 없음}'${_pre:+ · 앞 장식 '$_pre'})." >&2
      echo "  H 분류: $cats" >&2
      echo "  H 가 아니면 mq 에 올리지 않는다 — C(다른 prj 이슈 등록·배분·매뉴얼·내부 정책)는 총괄 전결, L(자기 prj 내부)은 팀장 전결." >&2
      echo "  결정 후 기록: ~/.claude/hooks/fbot-state.py decide --by <bot> --grade C|L --topic … --decision …" >&2
      echo "  권한표: ~/.claude/_doc_arch/decision-authority.md" >&2
      exit 5
    fi
  fi
fi
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
    --arg job "$JOB" --arg jarg "$JOB_ARG" --arg tgt "$TARGET_PRJ" \
    --argjson onresp "${ONRESP:-null}" \
    '{id:$id, type:$type, kind:$kind, created_ts:$created,
      due_ts:(if $due=="" then null else $due end),
      message:$msg,
      watch:(if $type=="watch" then {signal_type:$signal, topic:$topic} else null end),
      on_response:$onresp, status:$status, ask_count:0, last_ask_ts:null,
      acked:false, ack_ts:null, source:$source}
     + (if $fbot=="" then {} else {from_bot:$fbot} end)
     + (if $tbot=="" then {} else {to_bot:$tbot} end)
     + (if $job=="" then {} else {job:$job} end)
     + (if $jarg=="" then {} else {job_arg:$jarg} end)
     + (if $tgt=="" then {} else {target:$tgt} end)'
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
if [ -n "$OUT_JSON" ]; then
  # 기계 파싱용 1줄 (prj3#Issue808) — id 는 채번값 그대로(= basename 에서 `.json` 만 벗긴 값).
  #   호출자가 경로를 자르지 않게 하는 것이 목적이므로 산문과 병행 출력하지 않는다(1줄 계약).
  "$JQ" -nc --arg id "$ID" --arg path "$DEST" --arg type "$TYPE" --arg kind "$KIND" \
    --arg due "$DUE_TS" --arg source "$SOURCE" --arg tgt "$TARGET_PRJ" \
    '{id:$id, path:$path, type:$type, kind:$kind,
      due:(if $due=="" then null else $due end), source:$source,
      target:(if $tgt=="" then null else $tgt end)}' \
    || die "JSON 출력 실패 (jq) — 등록은 완료: $DEST"
else
case "$TYPE" in
  scheduled) echo "enqueued: $DEST (type=scheduled, kind=$KIND, due=$DUE_TS, source=$SOURCE$BOT_NOTE${TARGET_PRJ:+, target=$TARGET_PRJ}${JOB:+, job=$JOB}${JOB_ARG:+, arg=$JOB_ARG})" ;;
  watch)     echo "enqueued: $DEST (type=watch, kind=$KIND, signal=$SIGNAL, topic=$TOPIC, source=$SOURCE$BOT_NOTE)" ;;
  alert)     echo "enqueued: $DEST (type=alert, kind=$KIND, status=done_unacked, source=$SOURCE$BOT_NOTE) — 즉시 통지 원하면 aoa-mq-tick.sh 1회 kick" ;;
esac
fi

# 읽기용 digest(Aoa-mq-list.md) 재생성 — 등록 즉시 현황 반영 (prj3#Issue20). 실패해도 등록 자체는 성공 유지
DIGEST="$(dirname "$0")/aoa-mq-digest.sh"
[ -x "$DIGEST" ] && "$DIGEST" >/dev/null 2>&1 || true
