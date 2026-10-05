#!/usr/bin/env bash
# aoa-mq-progress.sh — 큐 항목 **진행 3종**(claimed_by·progress·result) 기록 단일 지점, prj3#Issue643
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): 본 script 는 aoa-mq(prj3) 전용 진행 기록 도구.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md "진행 가시성 — claimed_by·progress·result"
#
# 왜 (Issue643 — 사용자 지적 *"진행 상태를 모르겠음. 결과는 더더욱 모르고"*):
#   `/mq` 에서 [진행] 을 눌러도 그 뒤가 보이지 않았다. 큐 스키마에 **누가 집었는지·무엇을
#   하고 있는지·결과가 무엇인지**를 담을 자리가 하나도 없었기 때문이다. 화면(prj1#Issue506)이
#   보여줄 것이 생기려면 담을 곳이 먼저 있어야 한다 — 이 스크립트가 그 담을 곳에 쓰는 유일한 경로다.
#
# 🔑 claimed_by 는 **잠금이 아니라 표식이다**:
#   선점 잠금으로 만들면 Issue633·Issue644 가 겪은 *"잡은 것이 언제 풀리는지 아무도 보지 않는다"*
#   를 하나 더 만든다 — 세션이 죽으면 고아 claim 이 남고, 해제 경로가 없으면 그 항목은 아무도
#   손대지 못한다. 그래서 여기서는 **누가 집었는지 보여줄 뿐 착수를 막지 않는다.**
#   다른 주체가 이미 적혀 있어도 작업은 그대로 진행할 수 있고, 인계는 `--force` 로 명시한다.
#
# 사용법:
#   aoa-mq-progress.sh claim  <id> --by <주체> [--force]   # 집은 주체 기록 (비었을 때만 / --force 는 인계)
#   aoa-mq-progress.sh note   <id> --text "<진행 1줄>"     # 진행 메모 갱신 (진행 불가 사유도 여기에)
#   aoa-mq-progress.sh result <id> --text "<결과 요약>"    # 결과 기록 (종결 전후 모두 가능)
#   aoa-mq-progress.sh release <id>                        # 집은 표식 해제
#   aoa-mq-progress.sh show   <id>                         # 진행 3종 조회 (없으면 "-")
#
#   ── Issue770 — 대기·사람 몫·대상 prj ──
#   aoa-mq-progress.sh wait   <id> --for "<조건|mq:<id>>" [--recheck <+Nd|+Nh|YYYY-MM-DD|ISO>]
#                                                          # ⏳ 대기 진입 (in_progress·due·pending → waiting)
#   aoa-mq-progress.sh resume <id> [--via "<사유>"]         # 대기 해제 → **원래 상태**(wait_from)로만 복귀
#   aoa-mq-progress.sh need   <id> --text "decide:…|act:…" # 🙋 사람 몫 추가 (중복 무시 · 접두 필수)
#   aoa-mq-progress.sh need-done <id> (--index N|--text "<항목>") [--by <주체>]  # 사람 몫 해소 → 이력
#   aoa-mq-progress.sh target <id> [--json]                # 대상 prj·cwd 판정 (lib 단일 지점 노출 — hub 가 부른다)
#   aoa-mq-progress.sh retarget <id> --to prj<N> [--by <주체>]  # 대상 prj 정정 (Issue925) — 형식·매핑 검증, 이력 target_prev
#   aoa-mq-progress.sh launch <id> [--dry-run] [--force]   # 즉시 기동 — hub [진행] 직후 대상 cwd 에서 claude -p
#                                                          #   rc 0 기동(또는 dry-run) · 3 거부(판정·잠금·쿨다운·게이트) · 1 오류
#
# 락 대기 상한: env `AOA_MQ_LOCK_WAIT`(초, 기본 10). **차단 경로에서 부르는 호출자는 짧게 준다** —
#   UserPromptSubmit hook 이 tick 과 겹치면 사용자 입력이 그 시간만큼 멎는다(session-inbox 는 3초 + 백그라운드).
#
# 보장: 큐 JSON 만 읽고 쓴다(이동 없음). 원자적 쓰기(.tmp→mv) + tick 과 같은 락.
#   ⚠️ **in_progress 를 새로 세우지 않는다** — in_progress 진입은 사람의 [진행] 클릭(tick `start`,
#   approved_ts 기록) 하나뿐이라는 전제가 tick 7.8 자동 기동의 근거다(aoa-mq.md).
#   wait/resume 이 status 를 바꾸지만 **waiting ↔ 직전 상태(wait_from)** 왕복뿐이다 — resume 은
#   원래 상태로만 돌리므로 due 였던 항목이 in_progress 가 되는 경로는 없다(Issue770).

set -u

# 경로 계약 (prj3#Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본.
MQ_DIR="${AOA_MQ_DIR:-$HOME/.claude/data/aoa/mq}"
QUEUE="$MQ_DIR/queue"
QDONE="$MQ_DIR/queue_done"

die() { echo "aoa-mq-progress ERROR: $*" >&2; exit 1; }
JQ=$(command -v jq || echo /usr/bin/jq)
[ -x "$JQ" ] || die "jq 미설치 — brew install jq"
[ -d "$MQ_DIR" ] || die "큐 디렉토리 없음: $MQ_DIR"

# shellcheck source=/dev/null
. "$(dirname "$0")/aoa-mq-lock.sh"
# shellcheck source=/dev/null
. "$(dirname "$0")/aoa-mq-lib.sh"       # 대상 prj 판정 단일 지점 (Issue770)

POLICY="$MQ_DIR/policy.yml"
pol() { # $1=key $2=default — tick 과 같은 flat 파서
  local v
  v=$(grep -E "^[[:space:]]*$1:" "$POLICY" 2>/dev/null | head -1 \
      | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
  printf '%s' "${v:-$2}"
}

NOW_ISO=$(/bin/date '+%Y-%m-%dT%H:%M:%S')

resolve() { # $1=id → 큐 파일 경로. queue/ 우선, 없으면 queue_done/
  # 종결분도 대상에 넣는 이유: `result` 는 ACK 뒤에 채워 넣는 일이 있다(세션이 종결권 없이
  # 작업만 한 경우). claim·note 는 호출부에서 queue/ 로 한정한다.
  local id="$1"
  [ -f "$QUEUE/$id.json" ] && { printf '%s' "$QUEUE/$id.json"; return; }
  [ -f "$QDONE/$id.json" ] && { printf '%s' "$QDONE/$id.json"; return; }
  die "큐에 없음: $id (목록: aoa_mq_list 또는 ls $QUEUE)"
}

jupd() { # $1=file $2...=jq args — 원자 교체. 실패는 fail-loud (조용한 유실 금지)
  local f="$1"; shift
  local tmp="$f.tmp.$$"
  "$JQ" "$@" "$f" > "$tmp" 2>/dev/null || { rm -f "$tmp"; die "jq 갱신 실패: $f"; }
  mv "$tmp" "$f"
}

# 1줄 정규화 + **문자 기준** 400자 상한. 개행이 들어오면 digest·hub 표가 깨진다.
#
# ⚠️ `cut -c` 를 쓰지 않는다 (prj3#Issue651 — 실측 2026-09-19):
#   macOS BSD `cut -c` 는 문자가 아니라 **바이트**를 센다. 한글은 3바이트라 134자째 경계
#   중간에서 끊기고, 깨진 UTF-8 이 그대로 ① jq 로 들어가 파일에 U+FFFD 로 굳고
#   ② stdout 으로 흘러 server.py 의 `subprocess.run(text=True)` decode 를 죽인다.
#   호출자는 «실패» 를 보는데 파일에는 **깨진 채로 남는** 최악의 조합이었다.
#
#   jq 문자열 슬라이스는 유니코드 **코드포인트** 단위라 로케일·바이트 경계 문제가 없고
#   (digest.sh 가 같은 이유로 이미 jq 를 쓴다), server.py 의 ack 경로 `str[:400]` 과
#   셈 단위가 같아진다 — **같은 400 이 같은 뜻**이 된다.
#
#   잘랐으면 말하지 않고 자르지 않는다 — 끝에 `…` 를 붙여 호출자가 절단을 안다(총 길이는 400 유지).
oneline() {
  "$JQ" -nr --arg s "$1" '
    ($s | gsub("[\n\r]"; " ")) as $x
    | if ($x | length) > 400 then ($x[0:399] + "\u2026") else $x end'
}

# 시각 명세 → ISO (대기 재확인 시각). 과거 시각도 허용한다 — «지금 바로 다시 보라» 는 뜻이다.
when_iso() { # $1 = +Nd | +Nh | YYYY-MM-DD | YYYY-MM-DDTHH:MM[:SS]
  local w="$1" n out=""
  case "$w" in
    +[0-9]d|+[0-9][0-9]d|+[0-9][0-9][0-9]d)
      n="${w#+}"; n="${n%d}"
      out=$(/bin/date -v "+${n}d" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null) \
        || out=$(date -d "+${n} days" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null) ;;
    +[0-9]h|+[0-9][0-9]h|+[0-9][0-9][0-9]h)
      n="${w#+}"; n="${n%h}"
      out=$(/bin/date -v "+${n}H" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null) \
        || out=$(date -d "+${n} hours" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null) ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])                            out="${w}T09:00:00" ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9])      out="${w}:00" ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]) out="$w" ;;
  esac
  [ -n "$out" ] || die "--recheck 형식 오류: '$w' (허용: +Nd | +Nh | YYYY-MM-DD | YYYY-MM-DDTHH:MM[:SS])"
  printf '%s' "$out"
}

# 거부(판정 결과) — 오류(1)와 구분한다. hub 는 rc 3 이면 사유를 사람에게 그대로 보여 준다
refuse() { echo "aoa-mq-progress REFUSED: $*" >&2; exit 3; }

iso_epoch() { # ISO → epoch(초). 모르면 0 — tick iso2epoch 와 같은 규칙(BSD·GNU 양쪽)
  /bin/date -j -f '%Y-%m-%dT%H:%M:%S' "$1" +%s 2>/dev/null \
    || /bin/date -j -f '%Y-%m-%dT%H:%M' "$1" +%s 2>/dev/null \
    || date -d "$1" +%s 2>/dev/null || echo 0
}

CMD="${1:-}"; [ -n "$CMD" ] || die "하위명령 필요 (claim|note|result|release|show|wait|resume|need|need-done|target|retarget|launch)"
shift
ID="${1:-}"; [ -n "$ID" ] || die "$CMD 은 <id> 필요"
shift || true

BY=""; TEXT=""; FORCE=0; FOR=""; RECHECK=""; VIA=""; IDX=""; JSON=0; DRY=0; TO=""
while [ $# -gt 0 ]; do
  # 값을 받는 옵션이 끝 인자로 값 없이 오면 `shift 2` 가 실패하고 $1 이 그대로라 루프가 멎지 않는다 (Issue925 리뷰)
  case "$1" in
    --by|--to|--text|--for|--recheck|--via|--index) [ $# -ge 2 ] || die "$CMD: $1 은 값이 필요하다" ;;
  esac
  case "$1" in
    --by)      BY="${2:-}"; shift 2 ;;
    --to)      TO="${2:-}"; shift 2 ;;
    --text)    TEXT="${2:-}"; shift 2 ;;
    --force)   FORCE=1; shift ;;
    --for)     FOR="${2:-}"; shift 2 ;;
    --recheck) RECHECK="${2:-}"; shift 2 ;;
    --via)     VIA="${2:-}"; shift 2 ;;
    --index)   IDX="${2:-}"; shift 2 ;;
    --json)    JSON=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) die "$CMD: 알 수 없는 인자 $1" ;;
  esac
done

F=$(resolve "$ID")

case "$CMD" in
  show)
    # 읽기 전용 — 락 불필요
    "$JQ" -r '"claimed_by: \(.claimed_by // "-")",
              "progress:   \(.progress // "-")\(if .progress_ts then "  (" + .progress_ts + ")" else "" end)",
              "result:     \(.result // "-")\(if .result_ts then "  (" + .result_ts + ")" else "" end)"' "$F"
    ;;

  claim)
    [ -n "$BY" ] || die "claim 은 --by <주체> 필요 (세션 sid 또는 bot_id)"
    case "$F" in "$QDONE"/*) die "종결된 항목은 claim 대상 아님: $ID" ;; esac
    cur=$("$JQ" -r '.claimed_by // ""' "$F")
    if [ -n "$cur" ] && [ "$cur" = "$BY" ]; then
      echo "already-mine: $ID ← $cur"; exit 0      # 매 턴 다시 쓰지 않는다(넛지가 반복 호출한다)
    fi
    if [ -n "$cur" ] && [ "$FORCE" = 0 ]; then
      # ⚠️ 실패가 아니다 — 표식일 뿐이므로 착수를 막지 않는다. 호출자가 인계할지 판단한다.
      echo "already: $ID ← $cur (인계하려면 --force)"; exit 0
    fi
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    if [ -n "$cur" ]; then
      jupd "$F" --arg by "$BY" --arg ts "$NOW_ISO" --arg prev "$cur" \
        '.claimed_by=$by | .claimed_ts=$ts | .claimed_prev=$prev'
      echo "claimed(인계): $ID ← $BY (이전 $cur)"
    else
      jupd "$F" --arg by "$BY" --arg ts "$NOW_ISO" '.claimed_by=$by | .claimed_ts=$ts'
      echo "claimed: $ID ← $BY"
    fi
    ;;

  note)
    [ -n "$TEXT" ] || die "note 는 --text \"<진행 1줄>\" 필요"
    case "$F" in "$QDONE"/*) die "종결된 항목은 note 대상 아님: $ID (결과는 result 로 남긴다)" ;; esac
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" --arg t "$(oneline "$TEXT")" --arg ts "$NOW_ISO" '.progress=$t | .progress_ts=$ts'
    echo "progress: $ID ← $(oneline "$TEXT")"
    ;;

  result)
    [ -n "$TEXT" ] || die "result 는 --text \"<결과 요약>\" 필요"
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" --arg t "$(oneline "$TEXT")" --arg ts "$NOW_ISO" '.result=$t | .result_ts=$ts'
    echo "result: $ID ← $(oneline "$TEXT")"
    ;;

  release)
    case "$F" in "$QDONE"/*) die "종결된 항목은 release 대상 아님: $ID" ;; esac
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" 'del(.claimed_by, .claimed_ts)'
    echo "released: $ID"
    ;;

  target)
    # 읽기 전용 — 락 불필요. 판정은 lib 한 곳(aoa_mq_target)이다 — tick·session-inbox·hub 가 같은 답을 본다
    { IFS= read -r t_tgt; IFS= read -r t_src; IFS= read -r t_msg; } < <("$JQ" -r \
        '(.target // ""), (.source // ""), ((.message // "") | gsub("[\n\r\t]"; " "))' "$F")
    aoa_mq_target "$t_tgt" "$t_msg" "$t_src"
    if [ "$JSON" = 1 ]; then
      "$JQ" -nc --arg id "$ID" --arg p "$MQ_T_PRJ" --arg c "$MQ_T_CWD" --arg v "$MQ_T_VIA" --arg r "$MQ_T_RESOLVED" \
        '{id:$id, target:$p, cwd:$c, via:$v, resolved:($r=="1")}'
    else
      printf '%s\t%s\t%s\t%s\n' "${MQ_T_PRJ:--}" "$MQ_T_CWD" "$MQ_T_VIA" "$MQ_T_RESOLVED"
    fi
    ;;

  retarget)
    # 대상 prj 정정 (Issue925) — 잘못 박힌 target 을 고치는 **유일한 쓰기 경로**(큐 직접 Write 금지의 짝).
    #   실례: 총괄 [컨펌] 이 요청 prj 로 target 돼 [진행] 뒤 넛지가 엉뚱한 prj 세션에만 가 아무도 집지 않았다.
    #   검증은 enqueue `--target` 과 같은 규칙 — 오타를 받아 두면 판정 ①단이 «경로 없음» 으로 영영 멈춘다.
    #   status·승인 기록은 건드리지 않는다. 구 대상 세션의 claim 은 풀어 claimed_prev 로 남긴다 —
    #   그 표식이 남으면 새 대상 세션이 «이미 누가 집음» 으로 읽는다(claim 은 비었을 때만 세운다).
    [ -n "$TO" ] || die "retarget 은 --to prj<N> 필요"
    case "$F" in "$QDONE"/*) die "종결된 항목은 retarget 대상 아님: $ID" ;; esac
    aoa_mq_check_target "$TO" || die "--to $MQ_TV_ERR"
    cur=$("$JQ" -r '.target // ""' "$F")
    if [ "$cur" = "$TO" ]; then
      echo "already: $ID → $TO"; exit 0      # 이력(target_prev)을 같은 값으로 덮지 않는다
    fi
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" --arg to "$TO" --arg ts "$NOW_ISO" --arg by "${BY:-unknown}" '
      .target_prev = (.target // null) | .target = $to | .retargeted_ts = $ts | .retargeted_by = $by
      | if .claimed_by then .claimed_prev = .claimed_by | del(.claimed_by, .claimed_ts) else . end'
    echo "retargeted: $ID ${cur:-미상} → $TO"
    ;;

  wait)
    # ⏳ 대기 진입 (Issue770 원인 ①) — «조건이 풀리면 다시» 를 담는 상태.
    #   재확인 시각은 **반드시** 남긴다: 감시 주체 없는 비종결 상태를 만들지 않는다(Issue638 계약).
    #   생략하면 policy wait_default_recheck_days(기본 3일) 뒤로 잡는다.
    [ -n "$FOR" ] || die "wait 은 --for \"<조건 1줄>\" 필요 (선행 mq 항목이면 --for mq:<id>)"
    case "$F" in "$QDONE"/*) die "종결된 항목은 wait 대상 아님: $ID" ;; esac
    st=$("$JQ" -r '.status // ""' "$F")
    case "$st" in
      in_progress|due|pending|waiting) ;;
      *) die "wait 은 in_progress·due·pending 항목만 (현재 status=$st): $ID" ;;
    esac
    case "$FOR" in
      mq:*)
        dep="${FOR#mq:}"
        [ -n "$dep" ] && [ "$dep" != "$ID" ] || die "wait --for mq:<id> — 자기 자신·빈 id 는 선행이 될 수 없다"
        [ -f "$QUEUE/$dep.json" ] || [ -f "$QDONE/$dep.json" ] || die "선행 mq 항목 없음: $dep (오타면 영원히 기다린다 — 거부)" ;;
    esac
    if [ -z "$RECHECK" ]; then
      d=$(pol wait_default_recheck_days 3); case "$d" in ''|*[!0-9]*) d=3 ;; esac
      RECHECK="+${d}d"
    fi
    rts=$(when_iso "$RECHECK") || exit 1
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" --arg f "$(oneline "$FOR")" --arg r "$rts" --arg ts "$NOW_ISO" '
      .wait_from = (if .status == "waiting" then (.wait_from // "in_progress") else .status end)
      | .status = "waiting" | .wait_for = $f | .recheck_ts = $r | .waited_ts = $ts'
    echo "waiting: $ID ← $(oneline "$FOR") (재확인 $rts · 해제 시 $("$JQ" -r '.wait_from' "$F") 복귀)"
    ;;

  resume)
    # 대기 해제 — **원래 상태로만** 돌린다. in_progress 를 새로 세우는 경로가 아니다(위 «보장»).
    case "$F" in "$QDONE"/*) die "종결된 항목은 resume 대상 아님: $ID" ;; esac
    st=$("$JQ" -r '.status // ""' "$F")
    [ "$st" = waiting ] || die "resume 은 waiting 항목만 (현재 status=$st): $ID"
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" --arg ts "$NOW_ISO" --arg via "${VIA:-manual}" '
      .last_wait = {for: .wait_for, since: .waited_ts, from: .wait_from, resumed_ts: $ts, via: $via}
      | .status = (.wait_from // "in_progress")
      | del(.wait_for, .recheck_ts, .wait_from, .waited_ts)'
    echo "resumed: $ID → $("$JQ" -r '.status' "$F") (${VIA:-manual})"
    ;;

  need)
    # 🙋 사람 몫 (Issue770 원인 ⑥) — 산문에 묻히던 «사람이 해야 할 것» 을 필드로 올린다.
    #   접두로 종류를 가른다: decide: = 결정 · act: = 사람의 물리 행동. 접두가 없으면 거부한다 —
    #   hub 가 결정과 행동을 다른 버튼으로 받기 때문이다.
    [ -n "$TEXT" ] || die "need 는 --text \"decide:<결정>\" 또는 \"act:<행동>\" 필요"
    case "$TEXT" in
      decide:?*|act:?*) ;;
      *) die "need 항목은 decide: 또는 act: 로 시작해야 한다 (받음: '$TEXT')" ;;
    esac
    case "$F" in "$QDONE"/*) die "종결된 항목은 need 대상 아님: $ID" ;; esac
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" --arg t "$(oneline "$TEXT")" --arg ts "$NOW_ISO" '
      .needs_human = ((.needs_human // []) | if any(.[]; . == $t) then . else . + [$t] end)
      | .needs_human_ts = $ts'
    echo "needs_human: $ID ← $(oneline "$TEXT") ($("$JQ" -r '.needs_human | length' "$F")건)"
    ;;

  need-done)
    # 사람 몫 해소 — 목록에서 빼고 이력(needs_human_done)에 남긴다. hub 의 «개별 승인» 클릭이 여기로 온다.
    case "$F" in "$QDONE"/*) die "종결된 항목은 need-done 대상 아님: $ID" ;; esac
    [ -n "$IDX$TEXT" ] || die "need-done 은 --index N(1부터) 또는 --text \"<항목>\" 필요"
    case "$IDX" in ''|*[!0-9]*) [ -z "$IDX" ] || die "--index 는 1 이상의 정수" ;; esac
    item=$("$JQ" -r --arg i "${IDX:-0}" --arg t "$TEXT" '
      (.needs_human // []) as $n
      | if ($i|tonumber) > 0 then ($n[($i|tonumber) - 1] // empty) else ($n | map(select(. == $t)) | .[0] // empty) end' "$F")
    [ -n "$item" ] || die "해당 사람 몫 없음: $ID (${IDX:+index $IDX}${TEXT:+'$TEXT'}) — 목록: $("$JQ" -c '.needs_human // []' "$F")"
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" --arg it "$item" --arg ts "$NOW_ISO" --arg by "${BY:-unknown}" '
      .needs_human = ((.needs_human // []) | map(select(. != $it)))
      | .needs_human_done = ((.needs_human_done // []) + [{item: $it, ts: $ts, by: $by}])
      | if (.needs_human | length) == 0 then del(.needs_human) else . end'
    echo "need-done: $ID ← $item (남은 사람 몫 $("$JQ" -r '(.needs_human // []) | length' "$F")건)"
    ;;

  launch)
    # 즉시 기동 (Issue770 원인 ② — «[진행] 을 눌러도 대상 prj 에서 아무것도 시작되지 않는다»).
    #   hub [진행] 순서 계약: start ACK → aoa-mq-tick.sh --consume-only(승인 기록) → 이 명령.
    #   판정·프롬프트·HR 게이트·spawn 은 tick 7.8 과 **같은 lib 한 벌**이다 — 둘이 갈라지면
    #   «자동으로는 뜨는데 눌러서는 안 뜬다» 가 된다. 7.8 과 다른 것은 셋뿐이다:
    #     ① 경과 임계 없음(대기 0h) ② 게이트 키가 다르다 — 7.8 은 allow_wip_autostart(무인, 기본 닫음),
    #        여기는 allow_start_launch(사람 클릭, 기본 열림) ③ 재클릭 쿨다운(start_launch_cooldown_mins)
    #   wake_count·woken_at 은 **공유**한다 — 사람이 띄운 직후 7.8 이 또 띄우지 않게.
    case "$F" in "$QDONE"/*) refuse "종결된 항목은 launch 대상 아님: $ID" ;; esac
    [ "$(pol allow_start_launch true)" = true ] || refuse "launch 잠금 — policy allow_start_launch=false ($MQ_DIR/policy.yml)"
    { IFS= read -r l_st; IFS= read -r l_msg1; IFS= read -r l_appr; IFS= read -r l_tgt; IFS= read -r l_src
      IFS= read -r l_need; IFS= read -r l_woke; IFS= read -r l_cnt; } < <("$JQ" -r '
        (.status // ""), ((.message // "") | gsub("[\n\r]"; " ")), (.approved_ts // ""), (.target // ""),
        ((.source // "") | gsub("[\n\r]"; " ")), ((.needs_human // []) | join(" / ") | gsub("[\n\r]"; " ")),
        (.woken_at // ""), ((.wake_count // 0) | tostring)' "$F")
    [ "$l_st" = in_progress ] || refuse "launch 는 in_progress 항목만 (현재 status=$l_st) — hub [진행](start) 으로 착수 승인한 뒤 부른다: $ID"
    if aoa_mq_launch_blocked "$l_msg1" "$l_appr"; then
      refuse "[컨펌] 항목인데 승인 기록(approved_ts)이 없다 — hub /mq 에서 [진행] 을 다시 눌러 착수 승인을 기록한 뒤 기동한다: $ID"
    fi
    if [ -n "$l_woke" ] && [ "$FORCE" = 0 ]; then
      cd_min=$(pol start_launch_cooldown_mins 10); case "$cd_min" in ''|*[!0-9]*) cd_min=10 ;; esac
      l_ep=$(iso_epoch "$l_woke"); case "$l_ep" in ''|*[!0-9]*) l_ep=0 ;; esac
      if [ "$l_ep" -gt 0 ] && [ $(( $(/bin/date +%s) - l_ep )) -lt $(( cd_min * 60 )) ]; then
        refuse "방금 기동됨($l_woke, 쿨다운 ${cd_min}분) — 중복 기동 방지. 그래도 띄우려면 --force: $ID"
      fi
    fi
    aoa_mq_target "$l_tgt" "$l_msg1" "$l_src"
    [ -n "$MQ_T_CWD" ] && [ -d "$MQ_T_CWD" ] \
      || refuse "대상 경로 없음(${MQ_T_PRJ:-미상}/${MQ_T_VIA}: ${MQ_T_CWD:-매핑 없음}) — 이 머신에서 기동할 곳이 없다: $ID"
    aoa_mq_claude_bin || die "claude 실행 실패(PATH·설치 확인): $MQ_CLAUDE_BIN"
    l_prompt=$(aoa_mq_prompt start "$ID" "$("$JQ" -r '.message // ""' "$F")" "$l_src" 0 "$l_need")
    if [ "$DRY" = 1 ]; then
      printf 'dry-run: %s → 대상 %s (%s) cwd=%s · bin=%s · wake_count=%s\n' "$ID" "${MQ_T_PRJ:-미상}" "$MQ_T_VIA" "$MQ_T_CWD" "$MQ_CLAUDE_BIN" "$l_cnt"
      printf -- '--- prompt ---\n%s\n' "$l_prompt"
      exit 0
    fi
    # HR 게이트 — fail-closed (부재·거부·오류면 띄우지 않는다). 판정 로직은 게이트에만 있다
    aoa_mq_hr_gate "$MQ_DIR/exec.log"; l_g=$?
    [ "$l_g" -eq 2 ] && refuse "HR 게이트 부재(fail-closed) — 기동 안 함: $ID"
    [ "$l_g" -ne 0 ] && refuse "HR 게이트 거부·오류(fail-closed) — 기동 안 함: $ID ($MQ_DIR/exec.log)"
    aoa_mq_spawn "$MQ_T_CWD" "$ID" "$l_prompt" "$MQ_DIR/exec.log" "$("$JQ" -r '.message // ""' "$F")" || die "spawn 실패(cwd=$MQ_T_CWD): $ID"   # Issue863_7
    aoa_mq_lock_acquire "${AOA_MQ_LOCK_WAIT:-10}"
    jupd "$F" --arg ts "$NOW_ISO" '.woken_at=$ts | .wake_count=((.wake_count // 0) + 1) | .woken_by="launch"'
    # tick.log 에도 남긴다 — 무인 기동(7.8)과 같은 자리에서 «누가 언제 띄웠나» 를 되짚게
    printf '%s %s\n' "$NOW_ISO" "launch(사람 클릭 즉시 기동): $ID → ${MQ_T_PRJ:-미상}/${MQ_T_VIA} cwd=$MQ_T_CWD bin=$MQ_CLAUDE_BIN" >> "$MQ_DIR/tick.log"
    echo "launched: $ID → ${MQ_T_PRJ:-미상} (${MQ_T_VIA}) cwd=$MQ_T_CWD"
    ;;

  *) die "알 수 없는 하위명령: $CMD (claim|note|result|release|show|wait|resume|need|need-done|target|launch)" ;;
esac
