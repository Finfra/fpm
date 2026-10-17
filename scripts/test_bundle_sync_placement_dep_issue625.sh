#!/bin/bash
# test_bundle_sync_placement_dep_issue625.sh — Issue625 회귀 테스트 (tdd playlist #85 bundle-sync-placement-dep)
#
# scripts/fpm-bundle-sync.sh 가 **원본 배치에 의존하는 테스트**를 반출하지 않는지 검증한다.
#   원본 배치 의존 = 테스트가 상대경로로 부르는 파일이 라이브 루트(~/.claude)에는 있고
#   목적지 루트(번들 = plugins/fpm-core · mcp 유닛 = repo)에는 없다.
#   2026-10-09 실발생: issue-map tests/test-zero-remaining.py(→ commands/issue-closer-g.md)·
#   aoa-mq test-aoa-mq-{create-policy,progress}.sh(→ hooks/session-inbox.sh) 가 번들에서 FileNotFound·FAIL.
#
# 격리: 임시 git repo + 임시 HOME(라이브 = $HOME/.claude, git repo 아님 → 작업트리 원본). 실 저장소 무접촉.
#   검사 대상 스크립트는 **실물을 복사**해 쓴다 — 재구현을 검사하면 회귀를 못 잡는다.
#
# 실행: bash scripts/test_bundle_sync_placement_dep_issue625.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/bundle-placedep.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
has()   { if [ -e "$2" ]; then ok "$1"; else fail "$1 (없음: ${2#$SB/})"; fi; }
hasnt() { if [ -e "$2" ]; then fail "$1 (있음: ${2#$SB/})"; else ok "$1"; fi; }
says()  { if printf '%s\n' "$2" | grep -qF -- "$3"; then ok "$1"; else fail "$1 (출력에 '$3' 없음)"; fi; }

R="$SB/repo"; H="$SB/home"; L="$H/.claude"
B="$R/plugins/fpm-core"
mkdir -p "$R/scripts" "$B/services/hub" "$B/hooks" "$B/skills/fpm-issue-map/tests" "$R/mcp/aoa-mq" \
         "$L/skills/issue-map/tests" "$L/mcp/aoa-mq" "$L/commands" "$L/hooks"
cp "$REPO/scripts/fpm-bundle-sync.sh" "$R/scripts/"
echo "# hub" > "$B/services/hub/server.py"
mkdir -p "$R/services" && ln -s ../plugins/fpm-core/services/hub "$R/services/hub"

# 번들(목적지) 기준선 — 번들에는 hooks/shipped.sh 만 있다(commands/closer.md·hooks/inbox.sh 는 미배송)
echo "shipped" > "$B/hooks/shipped.sh"
echo "# map" > "$B/skills/fpm-issue-map/build.py"
echo "old" > "$R/mcp/aoa-mq/lib.sh"
git -C "$R" init -q
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base

# 라이브(원본)
echo "# closer" > "$L/commands/closer.md"
echo "inbox"    > "$L/hooks/inbox.sh"
echo "shipped"  > "$L/hooks/shipped.sh"
echo "# map" > "$L/skills/issue-map/build.py"
cat > "$L/skills/issue-map/tests/test-dep.py" <<'EOF'
from pathlib import Path
HERE = Path(__file__).resolve().parent
CLOSER = HERE.parents[2] / "commands" / "closer.md"
EOF
cat > "$L/skills/issue-map/tests/test-ok.py" <<'EOF'
from pathlib import Path
HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "build.py"
EOF
cat > "$L/skills/issue-map/tests/test-shipped.py" <<'EOF'
from pathlib import Path
HOOK = Path(__file__).resolve().parents[2] / "hooks" / "shipped.sh"
EOF
echo "new" > "$L/mcp/aoa-mq/lib.sh"
printf 'HERE="$(cd "$(dirname "$0")" && pwd)"\nINBOX="$HERE/../../hooks/inbox.sh"\n' > "$L/mcp/aoa-mq/test-dep.sh"
printf 'HERE="$(cd "$(dirname "$0")" && pwd)"\n. "$HERE/lib.sh"\n'                   > "$L/mcp/aoa-mq/test-ok.sh"

echo "[test_bundle_sync_placement_dep_issue625]"
echo "- 동기"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" 2>&1)"; rc=$?
check "동기 exit 0" "$rc" "0"
hasnt "skills: 원본 배치 의존 테스트 미반출 — test-dep.py"      "$B/skills/fpm-issue-map/tests/test-dep.py"
has   "skills: 유닛 내부 의존 테스트는 반출 — test-ok.py"       "$B/skills/fpm-issue-map/tests/test-ok.py"
has   "skills: 목적지에 있는 파일 의존 테스트는 반출(대조) — test-shipped.py" "$B/skills/fpm-issue-map/tests/test-shipped.py"
hasnt "mcp: 원본 배치 의존 테스트 미반출 — test-dep.sh"         "$R/mcp/aoa-mq/test-dep.sh"
has   "mcp: 유닛 내부 의존 테스트는 반출 — test-ok.sh"          "$R/mcp/aoa-mq/test-ok.sh"
check "mcp: 일반 파일은 그대로 동기 — lib.sh" "$(cat "$R/mcp/aoa-mq/lib.sh")" "new"
says  "제외 고지 — 경로와 의존 파일을 함께" "$out" "skills/issue-map/tests/test-dep.py → commands/closer.md"
says  "제외 고지 — mcp 유닛도"             "$out" "mcp/aoa-mq/test-dep.sh → hooks/inbox.sh"

echo "- 커밋 후 --check"
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m sync
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "제외 테스트는 표류로 세지 않는다 — --check exit 0" "$rc" "0"

echo "- 이미 반출된 사본(stale)"
printf 'HERE="$(cd "$(dirname "$0")" && pwd)"\nINBOX="$HERE/../../hooks/inbox.sh"\n' > "$R/mcp/aoa-mq/test-dep.sh"
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m stale
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "목적지에 남은 원본 배치 의존 테스트는 --check exit 1" "$rc" "1"
says  "--check 가 남은 사본을 이름으로 고지" "$out" "STALE mcp/aoa-mq/test-dep.sh"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" 2>&1)"; rc=$?
has   "동기는 남은 사본을 지우지 않는다(삭제는 사람이 git rm)" "$R/mcp/aoa-mq/test-dep.sh"
check "남은 사본이 있으면 동기도 exit 1 (조용히 성공하지 않는다)" "$rc" "1"
says  "동기가 git rm 조치를 안내" "$out" "git rm mcp/aoa-mq/test-dep.sh"

echo
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
