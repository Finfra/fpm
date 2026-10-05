#!/usr/bin/env bash
# test-aoa-mq-confirm-gate.sh — `[컨펌]` 등록 게이트 회귀 (prj3#Issue756)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.
#   설계 SSOT: ~/.claude/_doc_arch/decision-authority.md
#
# 무엇을 지키나 — mq `[컨펌]` 은 H 등급(사람만 정할 수 있는 것) 전용 창구다. 태그 없는 [컨펌] 이
#   섞이면 2026-09-28 실측처럼 사람에게 온 결정의 75% 가 C·L 이 되어 H 가 묻힌다.
# 실행: bash ~/.claude/mcp/aoa-mq/test-aoa-mq-confirm-gate.sh   (exit 0 = 전부 PASS)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ENQ="$HERE/aoa-mq-enqueue.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/mq/queue" "$TMP/mq/queue_done"
cat > "$TMP/policy.yml" <<'EOF'
h_categories: 배포,스토어,방침
exempt_sources: hub-board
EOF
export AOA_MQ_DIR="$TMP/mq" AOA_DECISION_POLICY="$TMP/policy.yml"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL $1"; }
run()  { # $1=기대 rc  $2=이름  나머지=인자
  local want="$1" name="$2"; shift 2
  local n0; n0=$(ls "$TMP/mq/queue" | wc -l)
  "$ENQ" "$@" >"$TMP/out" 2>"$TMP/err"; local rc=$?
  local n1; n1=$(ls "$TMP/mq/queue" | wc -l)
  if [ "$rc" = "$want" ]; then
    if [ "$want" = 0 ] && [ "$n1" -ne $((n0+1)) ]; then bad "$name — rc 0 인데 큐 파일 미생성"; return; fi
    if [ "$want" != 0 ] && [ "$n1" -ne "$n0" ]; then bad "$name — 거부했는데 큐 파일 생성"; return; fi
    ok "$name"
  else
    bad "$name — rc=$rc (기대 $want) · $(head -c 200 "$TMP/err")"
  fi
}

echo "== [컨펌] 등록 게이트 (Issue756) =="
run 5 "🔑 태그 없는 [컨펌] 거부"                   --message "[컨펌] prj3 이슈 등록할지?" --due +0d
grep -q "decision-authority" "$TMP/err" && ok "거부 사유에 권한표 안내" || bad "거부 사유에 권한표 안내 — $(cat "$TMP/err")"
run 5 "목록 밖 분류 거부"                          --message "[컨펌] [H:잡담] 아무거나" --due +0d
run 0 "H 분류 태그 통과"                            --message "[컨펌] [H:배포] prj26 Homebrew 반영" --due +0d
run 0 "태그 앞뒤 공백 허용"                         --message "[컨펌]  [H:스토어]  App Store 제출" --due +0d
run 5 "태그가 본문 중간이면 거부(머리에 있어야 분류가 보인다)" --message "[컨펌] 결정 요청 [H:배포]" --due +0d
run 0 "hub 발신(사람이 누른 요청)은 게이트 밖"      --message "[컨펌] 핀봇 wake 요청 — x" --alert --source hub-board
run 0 "[컨펌] 아닌 메시지는 무관"                   --message "prj5 Issue95 재개 여부 확인" --due +0d
AOA_DECISION_POLICY="$TMP/nope.yml" run 1 "정책 파일 부재 → fail-loud(조용히 통과 금지)" --message "[컨펌] [H:배포] x" --due +0d

echo "-- 독립 검토 반영 (codex 지적)"
run 5 "🔑 hub 접두 흉내(--source hubris-bot) 우회 차단 — 정확 일치만 예외" --message "[컨펌] x" --due +0d --source hubris-bot
run 5 "🔑 앞 공백 우회 차단"                          --message "  [컨펌] x" --due +0d
run 5 "🔑 앞 이모지 우회 차단"                        --message "🔴 [컨펌] x" --due +0d
run 0 "앞 공백 + H 태그는 통과"                       --message "  [컨펌] [H:배포] x" --due +0d
run 0 "태그 안 공백 허용([H: 배포])"                  --message "[컨펌] [H: 배포] x" --due +0d
run 0 "본문 중간의 [컨펌] 언급은 무관(머리 아님)"      --message "리마인드 — 어제 올린 [컨펌] 항목 확인" --due +0d
printf 'h_categories: 배포\r\nexempt_sources: hub-board\r\n' > "$TMP/crlf.yml"
AOA_DECISION_POLICY="$TMP/crlf.yml" run 0 "CRLF 정책 파일 — 정상 태그 통과" --message "[컨펌] [H:배포] x" --due +0d
AOA_DECISION_POLICY="$TMP/crlf.yml" run 0 "CRLF 정책 파일 — hub 예외 유지" --message "[컨펌] x" --alert --source hub-board
printf 'h_categories: 배포\n' > "$TMP/noex.yml"
AOA_DECISION_POLICY="$TMP/noex.yml" /bin/bash "$ENQ" --message "[컨펌] [H:배포] x" --due +0d >/dev/null 2>"$TMP/err" && ok "bash 3.2 — 예외 목록 없어도 정상 태그 통과" || bad "bash 3.2 — 예외 목록 없어도 정상 태그 통과 · $(head -c 200 "$TMP/err")"

echo; echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
