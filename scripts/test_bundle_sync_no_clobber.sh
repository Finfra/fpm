#!/bin/bash
# test_bundle_sync_no_clobber.sh — Issue519 회귀 테스트 (tdd playlist #11 bundle-sync-no-clobber)
#
# scripts/fpm-bundle-sync.sh 가 목적지의 **미커밋 변경**(수정·미추적 신규)을 라이브 원본으로
# 덮지 않는지 검증한다. 2026-09-20 실발생: 타 세션의 미커밋 `mcp/aoa-mq/` 작업이 통째로 덮여
# git 에도 없어 복구 불가였다.
#
# 격리: 임시 git repo + 임시 HOME(라이브 = $HOME/.claude). 실 저장소·실 ~/.claude 무접촉.
#   검사 대상 스크립트는 **실물을 복사**해 쓴다 — 재구현을 검사하면 회귀를 못 잡는다.
#
# 실행: bash scripts/test_bundle_sync_no_clobber.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/bundle-noclobber.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

R="$SB/repo"; H="$SB/home"; L="$H/.claude"
mkdir -p "$R/scripts" "$R/plugins/fpm-core/services/hub" "$R/plugins/fpm-core/hooks" "$R/mcp/aoa-mq" \
         "$L/hooks" "$L/mcp/aoa-mq"
cp "$REPO/scripts/fpm-bundle-sync.sh" "$R/scripts/"
echo "# hub" > "$R/plugins/fpm-core/services/hub/server.py"
ln -s ../plugins/fpm-core/services/hub "$R/services-hub-tmp" && mkdir -p "$R/services" \
  && mv "$R/services-hub-tmp" "$R/services/hub"

# 번들(목적지) 커밋 기준선
echo "old-a" > "$R/plugins/fpm-core/hooks/a.sh"
echo "old-b" > "$R/plugins/fpm-core/hooks/b.sh"
echo "old-x" > "$R/mcp/aoa-mq/x.py"
git -C "$R" init -q
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base

# 라이브(원본) — 전부 새 내용
echo "live-a" > "$L/hooks/a.sh"
echo "live-b" > "$L/hooks/b.sh"
echo "live-x" > "$L/mcp/aoa-mq/x.py"
echo "live-y" > "$L/mcp/aoa-mq/y.py"

# 타 세션의 in-flight 작업 (미커밋 수정 2 + 미추적 신규 1)
echo "WIP-a" > "$R/plugins/fpm-core/hooks/a.sh"
echo "WIP-x" > "$R/mcp/aoa-mq/x.py"
echo "WIP-y" > "$R/mcp/aoa-mq/y.py"

echo "[test_bundle_sync_no_clobber]"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" 2>&1)"; rc=$?

check "미커밋 수정(파일 단위 sync) 보존 — hooks/a.sh" "$(cat "$R/plugins/fpm-core/hooks/a.sh")" "WIP-a"
check "미커밋 수정(rsync 디렉토리) 보존 — mcp/aoa-mq/x.py" "$(cat "$R/mcp/aoa-mq/x.py")" "WIP-x"
check "미추적 신규 파일 보존 — mcp/aoa-mq/y.py" "$(cat "$R/mcp/aoa-mq/y.py")" "WIP-y"
check "clean 파일은 정상 동기 — hooks/b.sh" "$(cat "$R/plugins/fpm-core/hooks/b.sh")" "live-b"
check "건너뛴 대상이 있으면 exit 1 (조용히 성공하지 않는다)" "$rc" "1"
n_skip="$(printf '%s\n' "$out" | grep -c 'SKIP(dirty)')"
check "SKIP(dirty) 3건 고지" "$n_skip" "3"
if printf '%s\n' "$out" | grep -q '미커밋 변경 3 건을 건너뛰었다'; then ok "끝에 건너뛴 건수 요약"; else fail "끝에 건너뛴 건수 요약"; fi
if printf '%s\n' "$out" | grep -q '부분 동기 — 무결성 매니페스트 재생성을 건너뛴다'; then
  ok "부분 동기에서는 매니페스트를 봉인하지 않는다"
else
  fail "부분 동기에서는 매니페스트를 봉인하지 않는다"
fi

# 대조: 커밋하면(=dirty 해소) 그때는 동기된다 — 가드가 «항상 막기» 로 공허하지 않음
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m wip
HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" >/dev/null 2>&1; rc2=$?
check "dirty 해소 후 재실행은 exit 0" "$rc2" "0"
check "dirty 해소 후 a.sh 동기" "$(cat "$R/plugins/fpm-core/hooks/a.sh")" "live-a"

echo
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
