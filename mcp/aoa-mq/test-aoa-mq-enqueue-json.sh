#!/usr/bin/env bash
# test-aoa-mq-enqueue-json.sh — `--json` 기계 파싱용 출력 회귀 (prj3#Issue808 · 중복 명세 prj3#Issue811)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md
#
# 무엇을 지키나 — helper 성공 출력이 산문(`enqueued: <경로> (type=…)`)뿐이면 호출자가 id 를 얻으려고
#   경로를 `splitext` 로 자르게 되고, cwd 이름에 `.`(`.claude`)이 있으면 잘못 잘린다(Issue773 red 단계 발견).
#   `--json` 은 id 를 **helper 가 직접** 준다 — 확장자 `.json` 만 정확히 벗긴 값. 기존 산문·exit code 는 불변.
# 실행: bash ~/.claude/mcp/aoa-mq/test-aoa-mq-enqueue-json.sh   (exit 0 = 전부 PASS)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ENQ="$HERE/aoa-mq-enqueue.sh"
JQ=$(command -v jq || echo /usr/bin/jq)
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
# cwd 이름에 `.` 이 있는 재현 조건 — source 기본값(claude@<basename cwd>)·경로에 `.claude` 가 섞인다
mkdir -p "$TMP/mq/queue" "$TMP/mq/queue_done" "$TMP/home/.claude"
export AOA_MQ_DIR="$TMP/mq"
cd "$TMP/home/.claude" || exit 1
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL $1"; }
ID_RE='^[0-9]{8}-[0-9]{6}-[0-9]{3}$'

echo "== --json 기계 파싱용 출력 (Issue808) =="
"$ENQ" --json --message "prj3 Issue808 재현" --due +0d >"$TMP/out" 2>"$TMP/err"; rc=$?
[ "$rc" = 0 ] && ok "🔑 --json 수용(rc 0)" || bad "🔑 --json 수용 — rc=$rc · $(head -c 200 "$TMP/err")"
[ "$(wc -l <"$TMP/out" | tr -d ' ')" = 1 ] && ok "출력 1줄" || bad "출력 1줄 — $(wc -l <"$TMP/out") 줄"
"$JQ" -e . "$TMP/out" >/dev/null 2>&1 && ok "유효 JSON" || bad "유효 JSON — $(head -c 200 "$TMP/out")"
grep -q '^enqueued:' "$TMP/out" && bad "--json 이면 산문 미출력" || ok "--json 이면 산문 미출력"
id=$("$JQ" -r '.id // ""' "$TMP/out" 2>/dev/null)
[[ "$id" =~ $ID_RE ]] && ok "🔑 id 형식 YYYYMMDD-HHMMSS-NNN ($id)" || bad "🔑 id 형식 — '$id'"
path=$("$JQ" -r '.path // ""' "$TMP/out" 2>/dev/null)
[ -f "$path" ] && ok "path 가 실재 큐 파일" || bad "path 가 실재 큐 파일 — '$path'"
[ "$path" = "$TMP/mq/queue/$id.json" ] && ok "🔑 id == basename(path) 에서 .json 만 벗긴 값(.claude cwd 무관)" || bad "🔑 id ↔ path 불일치 — id=$id path=$path"
[ "$("$JQ" -r .id "$path")" = "$id" ] && ok "큐 파일 안 id 와 일치" || bad "큐 파일 안 id 와 일치"
for k in type kind due source target; do
  "$JQ" -e "has(\"$k\")" "$TMP/out" >/dev/null 2>&1 && ok "필드 존재: $k" || bad "필드 존재: $k"
done
[ "$("$JQ" -r .type "$TMP/out")" = scheduled ] && ok "type=scheduled" || bad "type=scheduled"
[ "$("$JQ" -r .kind "$TMP/out")" = pre ] && ok "kind=pre(기본)" || bad "kind=pre(기본)"
[ "$("$JQ" -r .source "$TMP/out")" = "claude@.claude" ] && ok "source 기본값에 .claude 그대로" || bad "source 기본값 — $("$JQ" -r .source "$TMP/out")"
"$JQ" -e '.target == null' "$TMP/out" >/dev/null 2>&1 && ok "미지정 target 은 null" || bad "미지정 target 은 null"
"$JQ" -e '.due | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T09:00:00$")' "$TMP/out" >/dev/null 2>&1 && ok "due 정규화 값" || bad "due 정규화 값 — $("$JQ" -r .due "$TMP/out")"

echo "-- 모드별"
"$ENQ" --json --message "알림" --alert >"$TMP/out" 2>"$TMP/err" \
  && [ "$("$JQ" -r .type "$TMP/out" 2>/dev/null)" = alert ] && "$JQ" -e '.due == null' "$TMP/out" >/dev/null 2>&1 \
  && ok "--alert: type=alert · due null" || bad "--alert — $(head -c 200 "$TMP/out") $(head -c 200 "$TMP/err")"
"$ENQ" --json --message "감시" --watch some-topic --kind post >"$TMP/out" 2>"$TMP/err" \
  && [ "$("$JQ" -r .type "$TMP/out" 2>/dev/null)" = watch ] && [ "$("$JQ" -r .kind "$TMP/out")" = post ] \
  && ok "--watch: type=watch · kind=post" || bad "--watch — $(head -c 200 "$TMP/out") $(head -c 200 "$TMP/err")"
"$ENQ" --message "x" --due +0d --json --source "fbot-lead@.claude" >"$TMP/out" 2>"$TMP/err" \
  && [ "$("$JQ" -r .source "$TMP/out" 2>/dev/null)" = "fbot-lead@.claude" ] \
  && ok "--json 위치 무관(뒤에 와도) · --source 반영" || bad "--json 위치 무관 — $(head -c 200 "$TMP/out") $(head -c 200 "$TMP/err")"

echo "-- 기존 계약 불변"
"$ENQ" --message "산문" --due +0d >"$TMP/out" 2>"$TMP/err"; rc=$?
[ "$rc" = 0 ] && grep -q '^enqueued: .*\.json (type=scheduled, kind=pre, due=' "$TMP/out" \
  && ok "🔑 --json 없으면 종전 산문 1줄 그대로" || bad "🔑 종전 산문 — rc=$rc · $(head -c 200 "$TMP/out")"
"$ENQ" --json --message "거부" >"$TMP/out" 2>"$TMP/err"; rc=$?
[ "$rc" != 0 ] && [ ! -s "$TMP/out" ] && grep -q "ERROR" "$TMP/err" \
  && ok "실패는 여전히 stderr + exit≠0 · stdout 비움" || bad "실패 경로 — rc=$rc out='$(head -c 100 "$TMP/out")'"
n=$(ls "$TMP/mq/queue" | wc -l | tr -d ' ')
[ "$n" = 5 ] && ok "큐 파일 수 = 성공 5건(--json 4 + 산문 1)" || bad "큐 파일 수 — $n (기대 5)"

echo "-- 재스케줄도 --json"
"$ENQ" --json --reschedule "$id" --due +1d >"$TMP/out" 2>"$TMP/err"; rc=$?
[ "$rc" = 0 ] && "$JQ" -e --arg i "$id" '.id == $i and (.due|type) == "string" and .status == "pending"' "$TMP/out" >/dev/null 2>&1 \
  && ok "--reschedule --json: id·due·status" || bad "--reschedule --json — rc=$rc · $(head -c 200 "$TMP/out") $(head -c 200 "$TMP/err")"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
