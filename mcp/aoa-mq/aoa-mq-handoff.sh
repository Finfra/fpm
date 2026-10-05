#!/usr/bin/env bash
# aoa-mq-handoff.sh — aoa-mq handoff(응답 스냅샷) 소비자 CLI (prj5 prj3#Issue25)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): 본 script 는 aoa-mq(prj3) 전용 handoff 소비 도구.
#   글로벌 SCAR — 실행체 소유는 prj3(~/.claude). cwd ≠ ~/.claude 면 즉시 수정 금지 →
#   ~/.claude/Issue.md 이슈 등록 후 처리 (rules/global-scar-change-rules.md).
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md "응답 액션 모델 — handoff". 규약: mcp/aoa-mq/aoa-mq.md
#
# 배경: tick 은 headless 라 "확인(confirm)" ACK 후 실제 작업을 실행하지 못하고
#   handoff/<id>.json 에 응답 스냅샷만 남긴다. 소비자가 없어 14건이 무기한 적체(2026-07-05~).
#   본 스크립트가 그 소비 규약(열람 → 처리 → 소비 / 보류 .hold)을 실행 가능한 형태로 제공한다.
#
# 사용법:
#   aoa-mq-handoff.sh                      # = list — 미소비 handoff 목록 (기본)
#   aoa-mq-handoff.sh list [--json]        # 목록 (--json = 원본 배열 출력)
#   aoa-mq-handoff.sh show <id>            # 단건 상세 JSON
#   aoa-mq-handoff.sh done <id> [--note "..."]   # 처리 완료 → z_consumed/ 이관(목록에서 제거)
#   aoa-mq-handoff.sh hold <id> [--note "..."]   # 보류 → <id>.json.hold rename (목록에서 제외)
#   aoa-mq-handoff.sh unhold <id>          # 보류 해제 (.hold → .json)
#   aoa-mq-handoff.sh count                # 미소비 건수만 출력 (hook·tick 용, 숫자 1줄)
#   aoa-mq-handoff.sh promote <id> [--note "..."] [--dry-run]   # 이슈 승격 → 대상 prj Issue.md 🌱 이슈후보 (prj3#Issue26)
#   aoa-mq-handoff.sh promote-stale [--days N] [--dry-run]      # stale 초과분 일괄 승격 (tick 용, prj3#Issue26)
#   aoa-mq-handoff.sh audit [--restore]    # 승격분이 대상 Issue.md 에 아직 있는지 감사 (유실분 재등록)
#   aoa-mq-handoff.sh audit --dismiss <id> --note "..."         # 유실분 무효 판정 종결 (감사 대상 제외, prj3#Issue504)
#
# 보장: 큐(queue/·queue_done/)는 건드리지 않음 — handoff/ 하위만 읽기·이동.
#   삭제 대신 z_consumed/ 이관(감사 추적 보존). silent 실패 금지 — 오류는 stderr + exit≠0.
#
# 승격(promote) 규약 (prj3#Issue26 — F1 "고립 우편함" 해소):
#   handoff/ 는 어떤 워크플로우에도 편입되지 않은 우편함이라 아무도 열지 않는다. 승격은 그 항목을
#   사람이 매일 보는 곳(대상 prj Issue.md)으로 옮겨 유실을 막는다.
#   · 대상 해석: source(`claude@<basename>`) → ~/_git/___pm/Projects.md 경로 basename 매칭.
#     못 찾으면 AOA_MQ_CWD(미설정 시 ~/.claude) 의 Issue.md 로 fallback (유실 금지 — 조용한 drop 없음)
#   · 삽입 위치: `# 🌱 이슈후보` 섹션 말미. **번호 발급·HWM 갱신 안 함** (issue-g 규칙5) —
#     타 프로젝트 이슈 번호를 headless 로 채번하면 충돌하므로 후보 리스트까지만 올린다
#   · 승격 후 handoff 는 z_consumed/ 이관 (promoted_to·consumed_note 기록)

set -u

# 경로 계약 (prj3#Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본.
MQ_DIR="${AOA_MQ_DIR:-$HOME/.claude/data/aoa/mq}"
HANDOFF="$MQ_DIR/handoff"
CONSUMED="$HANDOFF/z_consumed"

die() { echo "aoa-mq-handoff ERROR: $*" >&2; exit 1; }
JQ=$(command -v jq || echo /usr/bin/jq)
# BSD 고정 (tick.sh 와 동일 규약) — brew coreutils 가 PATH 앞에 오면 -f 포맷 의미가 달라짐
DATE=/bin/date
STAT=/usr/bin/stat
[ -x "$JQ" ] || die "jq 미설치 — brew install jq"
[ -d "$HANDOFF" ] || die "handoff 디렉토리 없음: $HANDOFF"

NOW_ISO=$("$DATE" '+%Y-%m-%dT%H:%M:%S')
NOW_EPOCH=$("$DATE" +%s)

# 미소비 파일 목록 (오래된 순). .hold / z_consumed 는 제외
pending_files() {
  find "$HANDOFF" -maxdepth 1 -type f -name '*.json' 2>/dev/null | sort
}

age_days() { # $1=file → 경과 일수
  local m; m=$("$STAT" -f %m "$1" 2>/dev/null || echo "$NOW_EPOCH")
  echo $(( (NOW_EPOCH - m) / 86400 ))
}

resolve() { # $1=id → 파일 경로 (없으면 die)
  local id="$1" f="$HANDOFF/$1.json"
  [ -f "$f" ] || f="$HANDOFF/$1"
  [ -f "$f" ] || die "handoff 없음: $id (목록은 'aoa-mq-handoff.sh list')"
  printf '%s' "$f"
}

# ── 승격 (promote) 지원 (prj3#Issue26) ──────────────────────────────────
PROJECTS_MD="$HOME/_git/___pm/Projects.md"
# 해석 실패 시 최후 착지점 — 유실 금지가 목적이므로 반드시 실재하는 곳이어야 한다.
FALLBACK_ISSUE="${AOA_MQ_CWD:-$HOME/.claude}/Issue.md"

target_issue_md() { # $1=source → 대상 Issue.md 경로 (해석 실패 시 fallback)
  local src="$1" cand path
  cand="${src#claude@}"                       # claude@social → social
  [ -n "$cand" ] || { printf '%s' "$FALLBACK_ISSUE"; return; }
  if [ -f "$PROJECTS_MD" ]; then
    case "$cand" in
      prj[0-9]*)
        # 사람이 지정한 source (ex: prj1-issue258-hold) → 앞머리 prj<N> 을 id 칸으로 해석
        pn=$(printf '%s' "$cand" | sed -E 's/^prj([0-9]+).*/\1/')
        path=$(awk -F'|' -v n="$pn" '
          /^\|/ { i = $2; gsub(/ /, "", i)
                  if (i == n) { p = $6; gsub(/[` ]/, "", p); if (p != "") { print p; exit } } }' "$PROJECTS_MD")
        ;;
    esac
    # Projects.md 표의 경로 칸(백틱 래핑)에서 basename 이 cand 와 일치하는 행을 찾는다
    [ -n "${path:-}" ] || path=$(awk -F'|' -v c="$cand" '
      /^\|/ {
        p = $6; gsub(/[` ]/, "", p)
        if (p == "") next
        n = split(p, a, "/")
        if (a[n] == c) { print p; exit }
      }' "$PROJECTS_MD")
  fi
  if [ -n "${path:-}" ]; then
    path="${path/#\~/$HOME}"
    [ -f "$path/Issue.md" ] && { printf '%s' "$path/Issue.md"; return; }
  fi
  printf '%s' "$FALLBACK_ISSUE"
}

# `# 🌱 이슈후보` 섹션 말미에 한 줄 append (번호는 섹션 내 기존 최대+1).
# 섹션이 없으면 die — 임의 섹션 신설 금지(대상 파일 구조를 헤집지 않음).
append_candidate() { # $1=Issue.md $2=본문 1줄
  ISSUE_MD="$1" CAND_LINE="$2" python3 - <<'PY'
import os, re, sys
p, line = os.environ["ISSUE_MD"], os.environ["CAND_LINE"]
src = open(p, encoding="utf-8").read()
lines = src.split("\n")
start = next((i for i, l in enumerate(lines) if l.strip().startswith("# 🌱 이슈후보")), None)
if start is None:
    sys.stderr.write("이슈후보 섹션 없음: %s\n" % p); sys.exit(3)
end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("# ")), len(lines))
body = lines[start + 1:end]
nums = [int(m.group(1)) for l in body if (m := re.match(r"\s*(\d+)\.\s", l))]
nxt = max(nums) + 1 if nums else 1
ins = end
while ins > start + 1 and lines[ins - 1].strip() == "":
    ins -= 1
lines.insert(ins, "%d. %s" % (nxt, line))
open(p, "w", encoding="utf-8").write("\n".join(lines))
print("%d" % nxt)
PY
}

# 승격 1줄 본문 — promote_one 과 audit --restore 가 동일 문구를 쓰도록 단일화.
# 끝의 "handoff <id>" 가 도착 검증 marker (audit 이 이 문자열로 존재를 확인)
candidate_line() { # $1=파일 → 이슈후보 1줄
  local f="$1" id src msg ack
  id=$("$JQ" -r '.id' "$f"); src=$("$JQ" -r '.source // "-"' "$f")
  ack=$("$JQ" -r '.ack_ts // "-"' "$f")
  # 이슈후보는 한 줄 리스트 — 긴 메시지는 컷하고 전문은 z_consumed 레코드에 보존
  msg=$("$JQ" -r '.message | gsub("\n"; " ") | if length > 150 then .[0:150] + "…" else . end' "$f")
  printf '[mq] %s (출처 %s · ACK %s · handoff %s → 전문은 handoff/z_consumed/%s.json)' \
    "$msg" "$src" "$ack" "$id" "$id"
}

promote_one() { # $1=파일 $2=note $3=dry(1|0) → stdout 요약 1줄
  local f="$1" note="${2:-}" dry="${3:-0}" id src target line num base
  id=$("$JQ" -r '.id' "$f"); src=$("$JQ" -r '.source // "-"' "$f")
  target=$(target_issue_md "$src")
  line=$(candidate_line "$f")
  if [ "$dry" = "1" ]; then
    echo "DRY $id → $target"
    return 0
  fi
  num=$(append_candidate "$target" "$line") || die "이슈후보 append 실패: $id → $target"
  # 도착 검증 (prj3#Issue26 후속): append 성공 보고를 믿지 않고 대상 파일에서 marker 를 되읽는다.
  # 실패 시 handoff 를 소비하지 않고 중단 — 도착 못 한 항목을 z_consumed 로 치우면 조용한 유실이 된다
  grep -Fq "handoff $id" "$target" \
    || die "승격 도착 검증 실패: $id → $target (marker 부재) — handoff 미소비 유지"
  mkdir -p "$CONSUMED"
  base=$(basename "$f")
  tmp="$f.tmp.$$"
  if "$JQ" --arg ts "$NOW_ISO" --arg to "$target" --arg n "$num" --arg note "$note" \
      '. + {consumed_ts:$ts, promoted_to:($to + " 🌱 이슈후보 " + $n),
            consumed_note:(if $note=="" then "prj3#Issue26 승격" else $note end)}' \
      "$f" > "$tmp" 2>/dev/null; then
    mv "$tmp" "$CONSUMED/$base"; rm -f "$f"
  else
    rm -f "$tmp"; die "jq 갱신 실패 — 승격 기록 중단: $base"
  fi
  echo "승격 $id → $target (🌱 이슈후보 $num)"
}

CMD="${1:-list}"; [ $# -gt 0 ] && shift

case "$CMD" in
  count)
    pending_files | wc -l | tr -d ' '
    ;;

  list)
    if [ "${1:-}" = "--json" ]; then
      printf '['
      first=1
      while IFS= read -r f; do
        [ -n "$f" ] || continue
        [ "$first" = 1 ] || printf ','
        first=0
        "$JQ" -c '.' "$f"
      done < <(pending_files)
      printf ']\n'
      exit 0
    fi
    n=$(pending_files | wc -l | tr -d ' ')
    if [ "$n" = 0 ]; then
      echo "미소비 handoff 없음 — 전건 처리 완료"
      hold_n=$(find "$HANDOFF" -maxdepth 1 -type f -name '*.hold' 2>/dev/null | wc -l | tr -d ' ')
      [ "$hold_n" != 0 ] && echo "(보류 ${hold_n}건 — 'aoa-mq-handoff.sh unhold <id>' 로 복귀)"
      exit 0
    fi
    echo "미소비 handoff ${n}건 (오래된 순):"
    echo
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      d=$(age_days "$f")
      "$JQ" -r --arg d "$d" '
        "── \(.id)  [\(.action)]  \($d)일 경과",
        "   메시지: \(.message)",
        "   출처: \(.source // "-")   ACK: \(.ack_ts // "-")",
        (if .on_response then "   on_response: \(.on_response | tostring)" else empty end),
        ""' "$f"
    done < <(pending_files)
    hold_n=$(find "$HANDOFF" -maxdepth 1 -type f -name '*.hold' 2>/dev/null | wc -l | tr -d ' ')
    [ "$hold_n" != 0 ] && echo "보류(.hold) ${hold_n}건 별도 존재"
    echo "처리 완료: aoa-mq-handoff.sh done <id> [--note \"...\"]"
    ;;

  show)
    id="${1:-}"; [ -n "$id" ] || die "show 는 <id> 필요"
    "$JQ" '.' "$(resolve "$id")"
    ;;

  done)
    id="${1:-}"; [ -n "$id" ] || die "done 은 <id> 필요"; shift
    note=""
    [ "${1:-}" = "--note" ] && { note="${2:-}"; shift 2; }
    f=$(resolve "$id")
    mkdir -p "$CONSUMED"
    base=$(basename "$f")
    tmp="$f.tmp.$$"
    if "$JQ" --arg ts "$NOW_ISO" --arg note "$note" \
        '. + {consumed_ts:$ts, consumed_note:(if $note=="" then null else $note end)}' \
        "$f" > "$tmp" 2>/dev/null; then
      mv "$tmp" "$CONSUMED/$base"
      rm -f "$f"
    else
      rm -f "$tmp"; die "jq 갱신 실패 — 이관 중단: $base"
    fi
    echo "소비 완료 → $CONSUMED/$base"
    echo "잔여 미소비: $(pending_files | wc -l | tr -d ' ')건"
    ;;

  hold)
    id="${1:-}"; [ -n "$id" ] || die "hold 는 <id> 필요"; shift
    note=""
    [ "${1:-}" = "--note" ] && { note="${2:-}"; shift 2; }
    f=$(resolve "$id")
    tmp="$f.tmp.$$"
    if "$JQ" --arg ts "$NOW_ISO" --arg note "$note" \
        '. + {hold_ts:$ts, hold_note:(if $note=="" then null else $note end)}' \
        "$f" > "$tmp" 2>/dev/null; then
      mv "$tmp" "$f.hold"
      rm -f "$f"
    else
      rm -f "$tmp"; die "jq 갱신 실패 — hold 중단: $(basename "$f")"
    fi
    echo "보류 → $f.hold (복귀: aoa-mq-handoff.sh unhold $id)"
    ;;

  unhold)
    id="${1:-}"; [ -n "$id" ] || die "unhold 는 <id> 필요"
    h="$HANDOFF/$id.json.hold"
    [ -f "$h" ] || die "보류 파일 없음: $h"
    mv "$h" "$HANDOFF/$id.json"
    echo "보류 해제 → $HANDOFF/$id.json"
    ;;

  promote)
    id="${1:-}"; [ -n "$id" ] || die "promote 는 <id> 필요"; shift
    note=""; dry=0
    while [ $# -gt 0 ]; do
      case "$1" in
        --note)    note="${2:-}"; shift 2 ;;
        --dry-run) dry=1; shift ;;
        *) die "promote: 알 수 없는 인자 $1" ;;
      esac
    done
    promote_one "$(resolve "$id")" "$note" "$dry"
    [ "$dry" = 1 ] || echo "잔여 미소비: $(pending_files | wc -l | tr -d ' ')건"
    ;;

  promote-stale)
    days=3; dry=0
    while [ $# -gt 0 ]; do
      case "$1" in
        --days)    days="${2:-3}"; shift 2 ;;
        --dry-run) dry=1; shift ;;
        *) die "promote-stale: 알 수 없는 인자 $1" ;;
      esac
    done
    n=0
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      promote_one "$f" "stale ${days}일 초과 자동 승격 (prj3#Issue26)" "$dry" || true
      n=$((n+1))
    done < <(find "$HANDOFF" -maxdepth 1 -type f -name '*.json' -mtime +"$days" 2>/dev/null | sort)
    if [ "$n" = 0 ]; then
      echo "stale(${days}일 초과) handoff 없음 — 승격 대상 0건"
    else
      echo "승격 ${n}건 완료 (stale ${days}일 초과). 잔여 미소비: $(pending_files | wc -l | tr -d ' ')건"
    fi
    ;;

  audit)
    # 승격 사후 감사 (prj3#Issue26 후속 · 판정 2단화 prj3#Issue504).
    # 승격분은 타 repo 의 uncommitted 작업본이라, 다른 세션이 stale 사본으로 덮어쓰면 조용히 사라진다
    # (2026-07-20 social 3건 실제 소실).
    #
    # ⚠️ 마커 부재 ≠ 유실 (prj3#Issue504) — 이슈후보 줄은 정식 이슈로 승격되거나 불필요 판정되면
    #   지워지는 것이 정상이다(issue-g 규칙4). 1단계(마커 grep)만으로는 그 정상 경로와
    #   덮어쓰기 유실이 구분되지 않아 2026-09-01 실측에서 16건 중 10건이 오탐이었다.
    #   2단계 판별: 대상 repo git 이력에 그 마커가 **한 번이라도 커밋된 적 있으면 소비된 것**이다.
    #   덮어쓰기 유실은 append 가 커밋 전에 사라지므로 이력에 흔적이 남지 않는다.
    # --restore 는 유실(lost)분만 재등록한다 — 소비분을 되살리면 Issue.md 가 오염된다.
    restore=0; dismiss_id=""; dismiss_note=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --restore) restore=1; shift ;;
        --dismiss) dismiss_id="${2:-}"; [ -n "$dismiss_id" ] || die "audit --dismiss: id 누락"; shift 2 ;;
        --note)    dismiss_note="${2:-}"; shift 2 ;;
        *) die "audit: 알 수 없는 인자 $1" ;;
      esac
    done
    # 무효 판정 종결 (prj3#Issue504) — 유실은 사실이나 대상 이슈가 취소·완료됐거나 요구 기능이
    # 이미 구현되어 재등록이 무의미한 건을 닫는다. 없으면 같은 경고가 매 tick 영구 반복된다.
    if [ -n "$dismiss_id" ]; then
      dcf="$CONSUMED/$dismiss_id.json"
      [ -f "$dcf" ] || die "audit --dismiss: 레코드 없음 — $dcf"
      [ -n "$dismiss_note" ] || die "audit --dismiss: --note 필수 (무효 판정 근거를 남긴다)"
      tmpf="$dcf.tmp.$$"
      "$JQ" --arg n "$dismiss_note" --arg t "$(date +%Y-%m-%dT%H:%M:%S)" \
        '.audit_dismissed = {note:$n, ts:$t}' "$dcf" > "$tmpf" \
        || { rm -f "$tmpf"; die "audit --dismiss: jq 실패 — $dismiss_id"; }
      mv "$tmpf" "$dcf"
      echo "⊘ $dismiss_id  무효 판정 종결 — $dismiss_note"
      exit 0
    fi
    [ -d "$CONSUMED" ] || die "z_consumed 디렉토리 없음: $CONSUMED"
    okc=0      # 정상 잔존 — 대상 Issue.md 에 마커 그대로
    used=0     # 소비 완료 — 마커는 없으나 git 이력에 존재 (이슈 승격·불필요 판정)
    lost=0     # 유실 — 마커도 이력도 없음 (덮어쓰기 의심)
    undet=0    # 판정 불가 — 대상이 git repo 가 아니거나 파일 부재
    dism=0     # 무효 판정 종결 — 유실이나 재등록 무의미 (--dismiss 로 닫음)
    fixed=0
    while IFS= read -r cf; do
      [ -n "$cf" ] || continue
      pt=$("$JQ" -r '.promoted_to // empty' "$cf")
      [ -n "$pt" ] || continue                       # 일반 소비(done)분은 감사 대상 아님
      if [ "$("$JQ" -r '.audit_dismissed.note // empty' "$cf")" != "" ]; then
        dism=$((dism+1)); continue                   # 무효 판정 종결분 (prj3#Issue504)
      fi
      id=$("$JQ" -r '.id' "$cf")
      tgt="${pt% 🌱 이슈후보 *}"                      # "…/Issue.md 🌱 이슈후보 3" → 경로만
      if [ ! -f "$tgt" ]; then
        echo "⚠ $id  판정 불가 — 대상 파일 없음: $tgt"; undet=$((undet+1)); continue
      fi
      if grep -Fq "handoff $id" "$tgt"; then
        okc=$((okc+1)); continue
      fi
      # 2단계 — git 이력 판별
      repo=$(dirname "$tgt")
      if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
        echo "⚠ $id  판정 불가 — 마커 부재이나 대상이 git repo 아님: $tgt"; undet=$((undet+1)); continue
      fi
      hits=$(git -C "$repo" log -S "handoff $id" --oneline -- "$(basename "$tgt")" 2>/dev/null | wc -l | tr -d ' ')
      if [ "${hits:-0}" -gt 0 ]; then
        used=$((used+1)); continue                   # 커밋된 적 있음 → 정상 소비
      fi
      lost=$((lost+1))
      if [ "$restore" = 1 ]; then
        n=$(append_candidate "$tgt" "$(candidate_line "$cf")") \
          || { echo "✗ $id  재등록 실패: $tgt" >&2; continue; }
        grep -Fq "handoff $id" "$tgt" \
          || { echo "✗ $id  재등록 후에도 marker 부재: $tgt" >&2; continue; }
        echo "↺ $id  재등록 → $tgt (🌱 이슈후보 $n)"; fixed=$((fixed+1))
      else
        echo "✗ $id  유실 (마커·git 이력 모두 부재): $tgt"
      fi
    done < <(find "$CONSUMED" -maxdepth 1 -type f -name '*.json' 2>/dev/null | sort)
    summary="승격 감사: 잔존 ${okc}건 · 소비 ${used}건 · 유실 ${lost}건 · 무효종결 ${dism}건 · 판정불가 ${undet}건"
    if [ "$restore" = 1 ]; then
      echo "$summary → 재등록 ${fixed}건"
      [ "$fixed" = "$lost" ] || exit 1
    elif [ "$lost" = 0 ]; then
      echo "$summary — 유실 없음"
    else
      echo "$summary (복구: audit --restore — 유실분만 재등록 / 무의미분: audit --dismiss <id> --note \"...\")"
      exit 1
    fi
    ;;

  *)
    die "알 수 없는 하위명령: $CMD (list|show|done|hold|unhold|count|promote|promote-stale|audit)"
    ;;
esac
