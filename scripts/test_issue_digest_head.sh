#!/usr/bin/env bash
# test_issue_digest_head.sh — digest --check 가 반출 기준(HEAD)으로 판정하는지 검증 (Issue603)
#   forward 는 `git archive HEAD` 를 반출한다. 작업트리 Issue.md 만 바뀐 상태(타 세션 미커밋)는
#   반출물과 무관하므로 --check 가 통과해야 하고, Issue.md 가 커밋되면 stale(rc 3)이어야 한다.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/scripts"; cp "$HERE/fpm-issue-digest.sh" "$T/scripts/"
cd "$T"
git init -q . && git config user.email t@t && git config user.name t
printf '# Issue Management\n\n## Issue1: 첫 이슈\n* 목적: 테스트\n* 구현 명세:\n    - 항목\n' > Issue.md
echo 'x // Issue1' > code.txt
git add -A && git commit -qm init
bash scripts/fpm-issue-digest.sh >/dev/null 2>&1 || { echo "FAIL: 초기 digest 생성 실패"; exit 1; }
git add -A && git commit -qm digest
fail=0
bash scripts/fpm-issue-digest.sh --check || { echo "FAIL: 신선 상태 rc!=0"; fail=1; }
# 1) 작업트리 Issue.md 만 수정(미커밋) → rc 0
printf '\n## Issue2: 미커밋 등록\n* 목적: 타 세션\n' >> Issue.md
bash scripts/fpm-issue-digest.sh --check >/dev/null 2>&1; rc=$?
[ "$rc" = 0 ] || { echo "FAIL: 미커밋 Issue.md 수정에 rc=$rc (기대 0)"; fail=1; }
# 2) Issue.md 커밋 → rc 3
git add Issue.md && git commit -qm issue2
bash scripts/fpm-issue-digest.sh --check >/dev/null 2>&1; rc=$?
[ "$rc" = 3 ] || { echo "FAIL: 커밋 후 rc=$rc (기대 3)"; fail=1; }
[ "$fail" = 0 ] && echo "PASS: digest --check HEAD 기준"
exit "$fail"
