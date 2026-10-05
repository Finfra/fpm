#!/usr/bin/env bash
# aoa-mq-digest.sh — aoa-mq 큐 → 읽기용 digest(루트 Aoa-mq-list.md) 재생성 + 월단위 archive append (prj5 prj3#Issue20)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): 본 script 는 모든 프로젝트가 공유(prj3 소유 — prj3#Issue436_3 이관).
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   절차: ~/.claude/rules/global-scar-change-rules.md
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md "읽기용 digest·archive". 규약: ~/.claude/mcp/aoa-mq/aoa-mq.md
#
# 사용법:
#   aoa-mq-digest.sh                          # queue/*.json → Aoa-mq-list.md 재생성 (상단 최신 archive 링크 + 미종결 표)
#   aoa-mq-digest.sh --archive <done_json>    # 종결 항목 1건을 ack_ts 월 기준 z_done/Aoa-mq-list-old-YYYY.MM.md 에 append 후 목록 재생성
#
# 보장: temp 쓰기 → mv 원자 교체. jq 미설치·큐 디렉토리 부재 시 stderr + exit≠0 (silent 실패 금지)
# 참조 무해: 읽기(queue/·queue_done/) + 쓰기(Aoa-mq-list.md·z_done/) 만. 큐 JSON 은 건드리지 않음.

set -u

# 경로 계약 (prj3#Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본.
MQ_DIR="${AOA_MQ_DIR:-$HOME/.claude/data/aoa/mq}"
QUEUE="$MQ_DIR/queue"
ZDONE="$MQ_DIR/z_done"

# 읽기용 digest 출력 위치 — 운영은 **프로젝트 루트에 직접 생성**한다.
#   구: data/aoa/mq/MQ_LIST.md 를 루트 Aoa-mq-list.md 심링크로 노출 → 에디터가 심링크
#   타깃 변경을 늦게 감지해 "고쳤는데 화면은 옛 내용" 마찰이 반복됐다(2026-08-03).
#   샌드박스(AOA_MQ_DIR 지정)는 격리 유지 위해 그 디렉토리 안에 쓴다.
# ARCH_REL: LIST 파일 위치 기준 z_done 상대경로 (상단 archive 링크용)
#   판정축 (prj3#Issue458, 2026-08-29) — **MQ_DIR 이 정본 기본값인가**.
#   prj3#Issue450 은 판정축을 AOA_MQ_CWD 로 옮겼었다. 그때는 운영이 AOA_MQ_DIR 을 항상 설정해
#   "설정 여부" 로는 운영과 샌드박스를 못 갈랐기 때문이다. prj3#Issue458 로 그 전제가 사라졌다 —
#   정본이 기본값과 같아져 운영은 env 를 아예 두지 않는다. 그래서 원래 의도(운영=프로젝트
#   루트 / 샌드박스=격리)를 기본값 대조로 되살린다. AOA_MQ_CWD 명시 지정은 계속 최우선.
MQ_DEFAULT="$HOME/.claude/data/aoa/mq"
CWD="${AOA_MQ_CWD:-$HOME/.claude}"   # tick.sh 와 동일 기본값
if [ -n "${AOA_MQ_CWD:-}" ] || [ "$MQ_DIR" = "$MQ_DEFAULT" ]; then
  LIST="$CWD/Aoa-mq-list.md"
  case "$MQ_DIR/" in
    "$CWD"/*) ARCH_REL="${MQ_DIR#$CWD/}/z_done" ;;
    *)        ARCH_REL="$MQ_DIR/z_done" ;;
  esac
else
  # 샌드박스: AOA_MQ_DIR 로 정본 아닌 곳을 가리켰고 렌더 대상도 미지정 → 그 안에 격리
  LIST="$MQ_DIR/Aoa-mq-list.md"; ARCH_REL="z_done"
fi

die() { echo "aoa-mq-digest ERROR: $*" >&2; exit 1; }
JQ=$(command -v jq || echo /usr/bin/jq)
[ -x "$JQ" ] || die "jq 미설치 — brew install jq"
[ -d "$QUEUE" ] || die "큐 디렉토리 없음: $QUEUE"
mkdir -p "$ZDONE"

NOW_ISO=$(date '+%Y-%m-%dT%H:%M:%S')
TODAY=$(date '+%Y-%m-%d')

# 셀 값 안전화: 파이프·개행 이스케이프 (markdown 표 깨짐 방지)
cell() { printf '%s' "$1" | tr '\n' ' ' | sed 's/|/\\|/g'; }

# kind → 사전/사후 (필드 부재 = 사전 기본)
kind_ko() { case "$1" in post) echo "사후" ;; *) echo "사전" ;; esac; }

# message → 표용 한 줄 요약. 첫 문장(". ") 또는 80자 중 먼저 오는 지점에서 자른다.
# jq 문자열 슬라이스는 유니코드 문자 단위라 로케일·바이트 경계 문제가 없다 (cut -c 회피).
# ⚠️ index(". ") 를 쓰지 않는다 — jq 의 문자열 index 는 UTF-8 **바이트** 오프셋이라
#   문자 단위인 .[a:b] 와 혼용하면 한글에서 어긋난다(첫 문장이 있는데도 80자 컷으로 샘).
#   split 결과의 length 는 문자 수이므로 두 축이 일치한다.
SUMM_JQ='def summ: (. // "") | gsub("[\n\r\t]"; " ") | gsub(" +"; " ") | . as $m
  | ($m | split(". ")[0]) as $f
  | (if ($f | length) < ($m | length) and ($f | length) <= 80 then ($f + ".")
     elif ($m | length) > 80 then ($m[0:80] + "…")
     else $m end);
'

# ── --archive: 종결 1건을 월 archive 에 append ────────────────────────
if [ "${1:-}" = "--archive" ]; then
  SRC="${2:-}"
  [ -n "$SRC" ] && [ -f "$SRC" ] || die "--archive 대상 파일 없음: ${SRC:-<빈값>}"
  ack=$("$JQ" -r '.ack_ts // empty' "$SRC" 2>/dev/null)
  # 월 산출: ack_ts(YYYY-MM-...) 앞 7자 → YYYY.MM, 부재 시 오늘
  if [ -n "$ack" ]; then ym="${ack:0:4}.${ack:5:2}"; else ym=$(date '+%Y.%m'); fi
  ARCH="$ZDONE/Aoa-mq-list-old-$ym.md"
  if [ ! -f "$ARCH" ]; then
    cat > "$ARCH" <<HEAD
---
name: Aoa-mq-list-old-$ym
description: aoa-mq $ym 종결 큐 이력 (자동 append — 직접 편집 금지)
date: $TODAY
---

| ack | id | 구분 | type | 종결 | message | source |
| :-- | :- | :--- | :--- | :--- | :------ | :----- |
HEAD
  fi
  # source 칸: 봇 귀속(from_bot/to_bot) 있으면 함께 표시 — 있는 항목만 (prj3#Issue436_3 s4)
  row=$("$JQ" -r '[.ack_ts // "-", .id, .kind // "pre", .type, .status, .message,
    ((.source // "-") + (if (.from_bot // .to_bot) then " [bot " + (.from_bot // "-") + "→" + (.to_bot // "-") + "]" else "" end))] | @tsv' "$SRC" 2>/dev/null)
  if [ -n "$row" ]; then
    IFS=$'\t' read -r a_ack a_id a_kind a_type a_st a_msg a_src <<<"$row"
    printf '| %s | %s | %s | %s | %s | %s | %s |\n' \
      "$(cell "$a_ack")" "$(cell "$a_id")" "$(kind_ko "$a_kind")" "$(cell "$a_type")" \
      "$(cell "$a_st")" "$(cell "$a_msg")" "$(cell "$a_src")" >> "$ARCH"
  fi
fi

# ── Aoa-mq-list.md 재생성 (미종결 표 + 상단 최신 archive 링크) ─────────────
# 최신(가장 최근 수정) archive 파일 → 상단 링크
latest_arch=$(ls -t "$ZDONE"/Aoa-mq-list-old-*.md 2>/dev/null | head -1)
if [ -n "$latest_arch" ]; then
  arch_link="📁 최근 종결 이력: [$(basename "$latest_arch")]($ARCH_REL/$(basename "$latest_arch"))"
else
  arch_link="📁 최근 종결 이력: (아직 없음)"
fi

# ── inbox 미소비 응답 수집 (prj3#Issue28) ──────────────────────────────────
# 폼 클릭 → inbox 파일 생성 → 다음 tick 의 consume_inbox 가 소비. 그 사이 구간이
# 사람 눈에 안 보이던 사각지대라 digest 가 대기분을 함께 표시한다.
# 읽기 전용 — 소비(삭제·상태전이)는 tick 고유 책임 (이중 소비 금지).
# cwd 해시를 모르므로 sid 폴더(aoa-mq)로 glob — 서버 없이도 동작.
INBOX_GLOB="${AOA_MQ_INBOX_GLOB:-/tmp/___pm/claude-htm-inbox/*/aoa-mq}"
pending_count=0
pending_map=""   # "<id>=<action[:arg]>" 줄 모음
for d in $INBOX_GLOB; do
  [ -d "$d" ] || continue
  for pf in "$d"/*.json; do
    [ -f "$pf" ] || continue
    pq=$("$JQ" -r 'if type=="array" then .[0].question else (.question // empty) end' "$pf" 2>/dev/null)
    case "$pq" in aoa-mq-ack:*) ;; *) continue ;; esac   # 자기 시그니처만
    pid=$(printf '%s' "$pq" | cut -d: -f2)
    pact=$(printf '%s' "$pq" | cut -d: -f3-)
    pending_count=$((pending_count+1))
    pending_map="$pending_map$pid=$pact"$'\n'
  done
done

pending_note=""
[ "$pending_count" -gt 0 ] && pending_note=" · 미소비 응답 ${pending_count}건(다음 tick 반영)"

# id → 대기 액션 (없으면 빈 문자열)
pending_for() {
  [ -n "$pending_map" ] || return 0
  printf '%s' "$pending_map" | grep -m1 "^$1=" 2>/dev/null | cut -d= -f2-
}

# 미종결 항목 수집 (created_ts 오름차순 = 파일명 정렬)
# 표에는 요약만 넣고 전문은 아래 "상세 내용" 섹션에 개행 그대로 둔다 — 표 셀에 수백 자가
# 들어가면 사람이 훑을 수 없다(prj3#Issue38). 별도 파일로 쪼개지 않는 이유: 지금 갱신은
# temp→mv 원자 교체 1회로 끝나고 종결 시 항목이 자동 소멸한다. 파일을 나누면 고아 정리
# 책임이 새로 생긴다.
count=0
rows=""
details=""
for f in $(ls "$QUEUE"/*.json 2>/dev/null | sort); do
  [ -f "$f" ] || continue
  count=$((count+1))
  # source 칸: 봇 귀속(from_bot/to_bot) 있으면 함께 표시 — 있는 항목만 (prj3#Issue436_3 s4)
  r=$("$JQ" -r "$SUMM_JQ"'[.id, .kind // "pre", .type, .status, (.due_ts // "-"), .ask_count, (.message | summ),
    ((.source // "-") + (if (.from_bot // .to_bot) then " [bot " + (.from_bot // "-") + "→" + (.to_bot // "-") + "]" else "" end))] | @tsv' "$f" 2>/dev/null) || continue
  IFS=$'\t' read -r id kind type st due asks summ src <<<"$r"
  # 전문은 @tsv 를 거치지 않고 따로 읽는다 (@tsv 가 개행을 리터럴 \n 으로 이스케이프함)
  msg_full=$("$JQ" -r '.message // ""' "$f" 2>/dev/null)
  pend=$(pending_for "$id")

  # 상태·시각 칸: 평시엔 due 만 짧게, 이상 상태만 눈에 띄게
  case "$due" in
    ????-??-??T*) when="${due:5:5} ${due:11:5}" ;;   # 2026-08-03T19:00 → 08-03 19:00
    -)            when="$type" ;;                    # due 없는 타입(watch 등)
    *)            when="$due" ;;
  esac
  [ "$st" != "pending" ] && when="$when ⚠️$st"
  [ -n "$pend" ] && when="$when ⏳$pend"

  rows="$rows| $(cell "$when") | $(cell "$summ") | $(cell "${src#claude@}") | $(cell "$id") |"$'\n'

  meta="$(kind_ko "$kind") · $type · $st"
  [ "$due" != "-" ] && meta="$meta · ⏰ $due"
  meta="$meta · asks $asks · $src"
  [ -n "$pend" ] && meta="$meta · ⏳ 미소비 응답: $pend"
  details="$details### $id"$'\n'"$meta"$'\n\n'"$msg_full"$'\n\n'
done

TMP="$LIST.tmp.$$"
{
  cat <<HEAD
---
name: Aoa-mq-list
description: aoa-mq 미종결 큐 현황 (자동 생성 — 직접 편집 금지, enqueue·tick 이 갱신)
date: $TODAY
ssot: data/aoa/mq/queue/*.json
generator: mcp/aoa-mq/aoa-mq-digest.sh
---

> ⚠️ **본 파일은 미러다.** 실제 상태(due_ts·status)는 SSOT \`data/aoa/mq/queue/*.json\` 에 있고 tick 은 그쪽만 본다.
> 여기를 고쳐도 동작은 안 바뀌며 다음 재생성 때 덮어써진다. 재스케줄은 **\`aoa-mq-enqueue.sh --reschedule <id> --due <+Nd|YYYY-MM-DD|ISO8601>\`** 1급 경로를 쓴다(prj3#Issue63 — JSON 갱신·digest 재생성·tick 상호배제가 한 묶음). 손으로 JSON 을 고치지 말 것.

$arch_link

_갱신: $NOW_ISO · 미종결 ${count}건${pending_note}. 등록 \`/mq-send\` · 조회 \`/mq-list\` · 응답은 tick 폼/Discord._

| 상태·시각 | 내용 | source | id |
| :-------- | :--- | :----- | :- |
HEAD
  if [ "$count" -gt 0 ]; then
    printf '%s' "$rows"
    printf '\n## 상세 내용\n\n'
    printf '%s' "$details"
  else
    echo "| _(미종결 없음)_ |  |  |  |"
  fi
} > "$TMP" && mv "$TMP" "$LIST" || { rm -f "$TMP"; die "Aoa-mq-list.md 쓰기 실패"; }

echo "digest 갱신: $LIST (미종결 ${count}건)"
