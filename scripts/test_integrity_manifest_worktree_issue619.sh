#!/usr/bin/env bash
# test_integrity_manifest_worktree_issue619.sh — Issue619 회귀 테스트
#
# 명제: linked worktree 에서 번들 파일을 커밋할 때 pre-commit `[integrity]` 가 정상 번들을 거부하지 않는다.
#   git 은 linked worktree 훅에 `GIT_DIR=<common>/.git/worktrees/<name>` 만 넘기고 `GIT_WORK_TREE` 는 넘기지 않는다.
#   그 env 에서 `git -C <bundle> ls-files` 는 번들을 작업트리 루트로 간주해 저장소 루트 기준 경로를 낸다 →
#   번들 상대 경로와 하나도 안 맞아 전 항목 REMOVED(«removed 204», 2026-10-05 실측).
#
# 임시 repo 에 실제 sh/gen-integrity-manifest.sh·scripts/install-precommit-integrity.sh 를 복사해 훅까지 실물로 돈다.
# 실행: bash scripts/test_integrity_manifest_worktree_issue619.sh
set -u

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL $1"; }
check(){ if [ "$2" = 0 ]; then ok "$1"; else bad "$1"; fi; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
R="$T/repo"; W="$T/wt"
# 바깥 git 문맥(이 테스트를 훅 안에서 돌릴 때)을 끊는다 — 픽스처 repo 를 대상으로만
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX
G() { git -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }

mkdir -p "$R/sh" "$R/scripts" "$R/plugins/fpm-core/.claude-plugin" "$R/plugins/fpm-core/hooks"
cp "$SRC/sh/gen-integrity-manifest.sh" "$R/sh/"
cp "$SRC/scripts/install-precommit-integrity.sh" "$R/scripts/"
echo '{"name":"fpm-core","version":"9.9.9"}' > "$R/plugins/fpm-core/.claude-plugin/plugin.json"
for i in 1 2 3; do echo "echo $i" > "$R/plugins/fpm-core/hooks/h$i.sh"; done
G -C "$R" init -q -b main
G -C "$R" add -A && G -C "$R" commit -qm init
bash "$R/sh/gen-integrity-manifest.sh" >/dev/null
G -C "$R" add -A && G -C "$R" commit -qm manifest
bash "$R/scripts/install-precommit-integrity.sh" >/dev/null
G -C "$R" worktree add -q "$W" -b wt 2>/dev/null

echo "▶ ① 메인 작업트리 — env 없음 (회귀)"
out="$(bash "$R/sh/gen-integrity-manifest.sh" --check 2>&1)"; check "main --check OK ($out)" $?

echo "▶ ② linked worktree — 훅과 같은 env(GIT_DIR 만 주입)에서 --check"
WGD="$(git -C "$W" rev-parse --absolute-git-dir)"
out="$(cd "$W" && GIT_DIR="$WGD" bash "$W/sh/gen-integrity-manifest.sh" --check 2>&1)"; rc=$?
check "worktree GIT_DIR --check OK ($(echo "$out" | tail -1))" $rc

echo "▶ ③ linked worktree — 실제 훅으로 번들 파일 커밋 (매니페스트 재생성 포함)"
echo "echo 4" > "$W/plugins/fpm-core/hooks/h4.sh"
G -C "$W" add plugins/fpm-core/hooks/h4.sh
bash "$W/sh/gen-integrity-manifest.sh" >/dev/null
G -C "$W" add plugins/fpm-core/.fpm-integrity.json
out="$(G -C "$W" commit -qm add-h4 2>&1)"; rc=$?
check "worktree 훅 통과 커밋 ($(echo "$out" | head -1))" $rc

echo "▶ ④ 진짜 불일치는 여전히 거부 (게이트가 무력화되지 않았나)"
echo "echo changed" > "$W/plugins/fpm-core/hooks/h1.sh"
G -C "$W" add plugins/fpm-core/hooks/h1.sh
G -C "$W" commit -qm tamper >/dev/null 2>&1; rc=$?
[ "$rc" -ne 0 ]; check "매니페스트 미갱신 변경은 거부(rc=$rc)" $?

echo "▶ ⑤ 부분 커밋(git commit <path>) — 임시 인덱스(GIT_INDEX_FILE) 기준 추적 판정"
G -C "$W" reset -q --hard
echo "echo 5" > "$W/plugins/fpm-core/hooks/h5.sh"
G -C "$W" add plugins/fpm-core/hooks/h5.sh
bash "$W/sh/gen-integrity-manifest.sh" >/dev/null
out="$(G -C "$W" commit -qm add-h5 -- plugins/fpm-core/hooks/h5.sh plugins/fpm-core/.fpm-integrity.json 2>&1)"; rc=$?
check "worktree 부분 커밋 통과 ($(echo "$out" | head -1))" $rc

echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
