#!/bin/bash
# test_decision_policy_seed_issue566.sh — Issue566 회귀 테스트 (tdd playlist `decision-policy-shipped`)
#
# prj3#Issue756 이 mq 등록 helper(`mcp/aoa-mq/aoa-mq-enqueue.sh`)에 `[컨펌] [H:<분류>]` 게이트를
# 넣었고, 게이트는 정책 파일 `${AOA_DECISION_POLICY:-~/.claude/data/decision-authority.yml}` 을
# 읽는다(부재 = fail-loud exit 1). 이 저장소는 helper 를 배송하면서 정책 파일은 배송하지 않았다 —
# 소비자 머신에서는 모든 `[컨펌]` 이 «결정 권한 정책 없음» 으로 거부된다.
#
# 무엇을 지키나 (3축)
#   A. scripts/fpm-bundle-sync.sh 가 라이브 정책을 repo 템플릿 `data/template/decision-authority.yml`
#      로 동기하고, 어긋나면 --check 가 표류로 잡는다
#   B. sh/fbot-bootstrap.sh 가 소비자의 정책 자리에 템플릿을 **비파괴**로 놓는다
#      (부재 → 복사 · 존재 → 한 줄도 건드리지 않는다)
#   C. 이 저장소가 배송하는 helper 로 소비자 `[컨펌] [H:배포]` 가 실제로 등록된다(종단)
#
# 격리: 임시 git repo·임시 HOME·임시 AOA_MEMORY_DIR·임시 AOA_MQ_DIR. 실 ~/.claude·실 큐 무접촉.
#   검사 대상 스크립트는 **실물**을 쓴다 — 재구현을 검사하면 회귀를 못 잡는다.
#
# 실행: bash scripts/test_decision_policy_seed_issue566.sh
set -u
unset AOA_DECISION_POLICY AOA_MQ_DIR

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/decision-seed.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

TPL_REL="data/template/decision-authority.yml"

# ── A. 번들 동기 → repo 템플릿 ──────────────────────────────────────
echo "[A] fpm-bundle-sync.sh 가 정책을 repo 템플릿으로 싣는다"
R="$SB/repo"; H="$SB/home"; L="$H/.claude"
mkdir -p "$R/scripts" "$R/plugins/fpm-core/services/hub" "$R/data/template" "$L/data"
cp "$REPO/scripts/fpm-bundle-sync.sh" "$R/scripts/"
echo "# hub" > "$R/plugins/fpm-core/services/hub/server.py"
mkdir -p "$R/services" && ln -s ../plugins/fpm-core/services/hub "$R/services/hub"
echo "placeholder" > "$R/data/template/keep.txt"
git -C "$R" init -q && git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base
printf 'h_categories: 배포,방침\nexempt_sources: hub-board\n' > "$L/data/decision-authority.yml"

HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" >/dev/null 2>&1
if cmp -s "$R/$TPL_REL" "$L/data/decision-authority.yml"; then ok "동기 후 템플릿 = 라이브"; else fail "동기 후 템플릿 = 라이브 (템플릿 부재 또는 내용 불일치)"; fi

git -C "$R" add -A && git -C "$R" -c user.name=t -c user.email=t@t commit -q -m synced >/dev/null 2>&1
printf 'h_categories: 배포,방침,보안\nexempt_sources: hub-board\n' > "$L/data/decision-authority.yml"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "라이브가 바뀌면 --check exit 1" "$rc" "1"
if printf '%s\n' "$out" | grep -q "DRIFT $TPL_REL"; then ok "--check 가 템플릿 표류를 이름으로 고지"; else fail "--check 가 템플릿 표류를 이름으로 고지"; fi

# ── B. bootstrap → 소비자 정책 자리 ─────────────────────────────────
echo "[B] fbot-bootstrap.sh 가 소비자 정책을 비파괴로 놓는다"
C="$SB/consumer"; mkdir -p "$C/.claude"
HOME="$C" AOA_MEMORY_DIR="$C/.claude/data/aoa" bash "$REPO/sh/fbot-bootstrap.sh" >"$SB/b1.log" 2>&1; rc=$?
check "bootstrap rc 0" "$rc" "0"
if [ -f "$REPO/$TPL_REL" ] && cmp -s "$C/.claude/data/decision-authority.yml" "$REPO/$TPL_REL"; then
  ok "부재 → 템플릿 복사"
else
  fail "부재 → 템플릿 복사 ($(tail -2 "$SB/b1.log" | tr '\n' ' '))"
fi

C2="$SB/consumer2"; mkdir -p "$C2/.claude/data"
printf 'h_categories: 운영자가정한값\n' > "$C2/.claude/data/decision-authority.yml"
HOME="$C2" AOA_MEMORY_DIR="$C2/.claude/data/aoa" bash "$REPO/sh/fbot-bootstrap.sh" >/dev/null 2>&1
check "존재 → 한 줄도 건드리지 않는다" "$(cat "$C2/.claude/data/decision-authority.yml")" "h_categories: 운영자가정한값"

# ── C. 종단: 배송된 helper 로 소비자 [컨펌] ──────────────────────────
echo "[C] 이 저장소가 배송하는 helper 로 소비자 [컨펌] 이 등록된다"
ENQ="$REPO/mcp/aoa-mq/aoa-mq-enqueue.sh"
MQ="$SB/mq"; mkdir -p "$MQ/queue" "$MQ/queue_done"
enq() { # $1=HOME  나머지=인자 → rc 출력
  (cd "$SB" && HOME="$1" AOA_MQ_DIR="$MQ" bash "$ENQ" "${@:2}" >/dev/null 2>"$SB/enq.err"); echo $?
}
n0=$(ls "$MQ/queue" | wc -l | tr -d ' ')
check "배송 helper 가 태그 없는 [컨펌] 을 거부(게이트 탑재)" "$(enq "$C" --message "[컨펌] 태그 없음" --due +0d)" "5"
check "정책 없는 머신은 [컨펌] 을 조용히 통과시키지 않는다" "$(enq "$SB/bare" --message "[컨펌] [H:배포] x" --due +0d)" "1"
check "seed 된 소비자의 [컨펌] [H:배포] 등록" "$(enq "$C" --message "[컨펌] [H:배포] 종단 확인" --due +0d)" "0"
check "큐 파일은 정확히 1건 생성" "$(ls "$MQ/queue" | wc -l | tr -d ' ')" "$((n0 + 1))"

echo
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
