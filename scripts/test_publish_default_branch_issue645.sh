#!/bin/bash
# test_publish_default_branch_issue645.sh — Issue645 회귀 테스트
#
# deploy --with-marketplace 가 prj20 의 «현재 브랜치»에만 push 하고 «publish 완료» 를 보고했다 —
# prj20 이 release/* 에 앉아 있으면 소비자 install.sh 가 받는 기본 브랜치(main)는 갱신되지 않은 채였다
# (v0.8.3 재출고 실측 2026-10-17, 수동 FF 로 해소). push 뒤 «HEAD 가 origin/<기본 브랜치>에 들어 있는가» 를 본다.
#
#   ① 기본 브랜치(main)에서 push 한 뒤 → 반영됨 (rc 0)
#   ② release/* 에 앉아 push 만 했고 main 이 뒤처짐 → 미반영 (rc 1) + 기본 브랜치 이름이 출력된다
#   ③ main 을 FF 한 뒤 같은 release/* HEAD → 반영됨 (rc 0)
#   ④ origin/HEAD 가 없어도 main 으로 폴백해 판정한다
#   ⑤ origin 에 닿지 못하면 확인 불가 (rc 2) — 거짓 «반영됨» 으로 넘기지 않는다
#   ⑥ do_publish 배선(정적): push 성공 뒤에만 검사 · 미반영이면 «publish 완료» 로그 앞에서 중단 · 우회 변수 FPM_MKT_BRANCH_ONLY
#
# 격리: 임시 bare origin + clone. 대상 함수는 실물 scripts/fpm-sync.sh 에서 **추출**해 eval 한다(재구현 금지).
# 실행: bash scripts/test_publish_default_branch_issue645.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SYNC="$REPO/scripts/fpm-sync.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/pub-branch.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

echo "[test_publish_default_branch_issue645]"
export GIT_CONFIG_GLOBAL=/dev/null

FUNCS="$SB/funcs.sh"
for fn in publish_default_branch_check; do
    awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {p=1} p {print} p && /^}/ {p=0}' "$SYNC" >> "$FUNCS"
done

O="$SB/origin.git"; W="$SB/prj20"
G() { git -C "$1" -c user.name=t -c user.email=t@t "${@:2}"; }
git init -q --bare -b main "$O"
git clone -q "$O" "$W" 2>/dev/null
echo a > "$W/f"; G "$W" add -A; G "$W" commit -q -m c0; G "$W" push -q origin main
git -C "$W" remote set-head origin main >/dev/null 2>&1

run() { ( . "$FUNCS"; "$@" ); }

# ── ① main 에서 push → 반영됨 ──
echo b > "$W/f"; G "$W" commit -qam c1; G "$W" push -q origin main
out="$(run publish_default_branch_check "$W" 2>&1)"; rc=$?
check "① main push 뒤 → rc 0" "$rc" "0"

# ── ② release/* 에서만 push → 미반영 ──
G "$W" checkout -q -b release/0.1.0
echo c > "$W/f"; G "$W" commit -qam c2; G "$W" push -q origin release/0.1.0
out="$(run publish_default_branch_check "$W" 2>&1)"; rc=$?
check "② release/* 만 push · main 뒤처짐 → rc 1" "$rc" "1"
case "$out" in *main*) ok "② 출력에 기본 브랜치 이름(main)" ;; *) fail "② 출력에 main 없음: $out" ;; esac

# ── ③ main FF 뒤 → 반영됨 ──
G "$W" push -q origin release/0.1.0:main
out="$(run publish_default_branch_check "$W" 2>&1)"; rc=$?
check "③ main FF 뒤 → rc 0" "$rc" "0"

# ── ④ origin/HEAD 없음 → main 폴백 ──
echo d > "$W/f"; G "$W" commit -qam c3; G "$W" push -q origin release/0.1.0
git -C "$W" remote set-head origin -d >/dev/null 2>&1
out="$(run publish_default_branch_check "$W" 2>&1)"; rc=$?
check "④ origin/HEAD 없음 · main 뒤처짐 → main 폴백으로 rc 1" "$rc" "1"

# ── ⑤ origin 불통 → 확인 불가 ──
git -C "$W" remote set-url origin "$SB/없는경로.git"
out="$(run publish_default_branch_check "$W" 2>&1)"; rc=$?
check "⑤ origin 불통 → rc 2" "$rc" "2"

# ── ⑥ 배선(정적) ──
body="$(awk '/^do_publish\(\) \{/ {p=1} p {print} p && /^}/ {p=0}' "$SYNC")"
case "$body" in *publish_default_branch_check*) ok "⑥ do_publish 가 검사를 부른다" ;; *) fail "⑥ do_publish 에 검사 호출 없음" ;; esac
case "$body" in *FPM_MKT_BRANCH_ONLY*) ok "⑥ 우회 변수 FPM_MKT_BRANCH_ONLY" ;; *) fail "⑥ 우회 변수 없음" ;; esac
chk_line="$(printf '%s\n' "$body" | grep -n 'publish_default_branch_check' | head -1 | cut -d: -f1)"
done_line="$(printf '%s\n' "$body" | grep -n 'publish 완료: fpm-core' | head -1 | cut -d: -f1)"
push_line="$(printf '%s\n' "$body" | grep -n 'prj20 push 완료' | head -1 | cut -d: -f1)"
if [ -n "$chk_line" ] && [ -n "$done_line" ] && [ -n "$push_line" ] && [ "$push_line" -lt "$chk_line" ] && [ "$chk_line" -lt "$done_line" ]; then
    ok "⑥ 순서: push 완료 → 검사 → publish 완료"
else
    fail "⑥ 순서 위반 (push=$push_line chk=$chk_line done=$done_line)"
fi

# fpm-sync.sh 는 set -e — 호출이 rc 를 || 로 받지 않으면 미반영(rc 1)에서 안내 로그 없이 조용히 죽는다
case "$body" in *'publish_default_branch_check "$MKT20_DIR")" && rc=0 || rc=$?'*) ok "⑥ set -e 안전: rc 를 || 로 수집" ;; *) fail "⑥ set -e 에서 rc 수집 누락" ;; esac

echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
