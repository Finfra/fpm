#!/bin/bash
# test_hub_trigger_columns_issue550.sh — Issue550 회귀 테스트 (tdd playlist #25 hub-list-columns-by-header)
#
# plugins/fpm-core/hooks/fpm-hub-trigger.sh 의 `..hub list` 가 Projects.md 이모지를 **헤더 명칭**으로
# 찾는지 검증한다. 종전 `cells[6]` 위치 인덱스는 tdd 컬럼이 이모지 앞에 끼자 이모지 자리에
# tdd 상태(🆕·➖)를 찍었고, license 컬럼(Issue550)이 더 끼어도 같은 자리를 가리킨다.
# server.py 는 먼저 헤더 기반으로 고쳤지만 이 hook 은 남아 있었다(반쪽 수정).
#
# 격리: Projects.md 는 FPM_PROJECTS_MD 로 임시 파일을 준다(실 표 무접촉). hook 은 **실물을 실행**한다 —
#   재구현을 검사하면 회귀를 못 잡는다. hook-input.sh·jq·~/.claude/.hub-state 는 실환경 것을 읽기만 한다.
#
# 실행: bash scripts/test_hub_trigger_columns_issue550.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$REPO/plugins/fpm-core/hooks/fpm-hub-trigger.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/hub-trigger-i550.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
has()  { case "$2" in *"$3"*) ok "$1";; *) fail "$1 (got='$2')";; esac; }
hasnt(){ case "$2" in *"$3"*) fail "$1 (got='$2')";; *) ok "$1";; esac; }

# hook 실행 → additionalContext 표 문자열. 표가 안 나오면 stderr 를 그대로 보여 준다.
run_list() {  # $1=Projects.md 경로
  local out ctx
  out="$(printf '%s' '{"prompt":"..hub list","cwd":"/tmp/i550/none","session_id":"t550"}' \
        | FPM_PROJECTS_MD="$1" bash "$HOOK" 2>"$SB/err")"
  ctx="$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)"
  if [ -z "$ctx" ]; then
    echo "  (hook 출력에 표 없음) stdout=$(printf '%s' "$out" | head -c 300) stderr=$(head -c 300 "$SB/err")" >&2
  fi
  printf '%s' "$ctx"
}

# A. 현행 표 — tdd·license 두 컬럼이 이모지 앞에 있다
cat > "$SB/Projects.md" <<'MD'
| id  | 프로젝트명 | 한국어명칭 | Dmn | 경로            | 설명 | tdd  | license | 이모지 | color   |
| --- | :--------- | ---------- | :-- | :-------------- | :--- | :--: | :------ | :----- | :------ |
| 2   | obsidian   | 옵시디언   | g   | `/tmp/i550/doc` | 문서 | 🆕   | —       | 💜     | #cfedd9 |
| 8   | fpm        | 에프피엠   | g   | `/tmp/i550/fpm` | 미러 | ➖   | A①      | 🔌     | #eeeedd |
MD
ctx="$(run_list "$SB/Projects.md")"
row2="$(printf '%s\n' "$ctx" | grep '^| 2 |' || true)"
row8="$(printf '%s\n' "$ctx" | grep '^| 8 |' || true)"
has   "A1 임시 Projects.md 를 읽는다 (FPM_PROJECTS_MD)"         "$row2" "obsidian"
has   "A2 이모지는 이모지 컬럼에서(💜)"                            "$row2" "💜 obsidian"
hasnt "A3 tdd 상태(🆕)가 이모지 자리에 섞이지 않는다"              "$row2" "🆕"
hasnt "A4 license 값(—)이 이모지 자리에 섞이지 않는다"             "$row2" "| — obsidian"
has   "A5 두 번째 행도 이모지 컬럼(🔌)"                            "$row8" "🔌 fpm"
hasnt "A6 실 Projects.md 행(prj1 pm)이 섞이지 않는다"              "$ctx"  "| 1 |"

# B. 구 8컬럼 표(헤더 명칭이 달라도) — 위치 fallback 으로 기존 동작 유지
cat > "$SB/legacy.md" <<'MD'
| No | Name   | S | Domain | Path              | Desc   | Icon | Color   |
| 1  | legacy | - | g      | /tmp/i550/legacy  | 테스트 | 🎮   | #aabbcc |
MD
ctx="$(run_list "$SB/legacy.md")"
row1="$(printf '%s\n' "$ctx" | grep '^| 1 |' || true)"
has "B1 구 표는 cells[6] 위치 fallback(🎮)" "$row1" "🎮 legacy"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
