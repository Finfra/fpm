#!/bin/bash
# test_bundle_sync_lib_deps_issue561.sh — Issue561 회귀 테스트 (tdd playlist `bundle-sync-lib-deps`)
#
# scripts/fpm-bundle-sync.sh 의 «신규 파일은 수동 편입» 원칙이 **이미 편입된 훅의 lib 의존**까지
# 막았다. 훅은 `$(dirname "$0")/lib/<x>` 로 부르므로 번들에 lib 이 없으면 소비자 머신에서 조용히
# 실패한다(2026-09-28 실측: 번들 fbot-checkout.sh → lib/session-end.py 부재 · fbot-writeguard.sh →
# lib/shcmd.py 부재(`|| exit 0` 로 fail-open) · fpm-ask-question-guard.sh → lib/decision-question.py).
# 편입된 훅의 의존은 새 편입 결정이 아니다 — 훅을 실은 순간 이미 결정된 것이다.
#
# 무엇을 지키나
#   1. 동기 시 번들 훅(라이브 판)이 참조하는 lib 이 번들에 없으면 라이브에서 싣는다
#   2. lib 이 다시 참조하는 lib 도 싣는다(전이)
#   3. --check 는 누락 의존을 표류로 이름과 함께 고지하고 exit 1
#   4. 라이브에도 없는 참조는 만들지 않는다(가짜 파일 금지) · 번들에 없는 훅의 lib 은 싣지 않는다
#
# 격리: 임시 git repo + 임시 HOME. 검사 대상 스크립트는 실물 복사.
# 실행: bash scripts/test_bundle_sync_lib_deps_issue561.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/bundle-libdeps.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

R="$SB/repo"; H="$SB/home"; L="$H/.claude"; B="$R/plugins/fpm-core"
mkdir -p "$R/scripts" "$B/services/hub" "$B/hooks/lib" "$L/hooks/lib"
cp "$REPO/scripts/fpm-bundle-sync.sh" "$R/scripts/"
mkdir -p "$R/sh" && cp "$REPO/sh/gen-integrity-manifest.sh" "$R/sh/"   # 7단계 매니페스트 재생성까지 실물로
echo "# hub" > "$B/services/hub/server.py"
mkdir -p "$R/services" && ln -s ../plugins/fpm-core/services/hub "$R/services/hub"

# 번들: 훅 guard.sh(구판 — 아직 lib 안 부름) + 기존 lib old.sh + 스킬 fbot-icon(파일 1개)
echo 'echo old' > "$B/hooks/guard.sh"
echo '# old lib' > "$B/hooks/lib/old.sh"
mkdir -p "$B/skills/fbot-icon" "$L/skills/fbot-icon"
echo '# skill' > "$B/skills/fbot-icon/SKILL.md"
echo '# skill' > "$L/skills/fbot-icon/SKILL.md"
echo '# new script' > "$L/skills/fbot-icon/new.py"
git -C "$R" init -q && git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base

# 라이브: guard.sh 가 lib/judge.py 를 부르고, judge.py 는 lib/util.py 를 부른다(전이).
#   ghost.py 는 참조만 있고 라이브에도 없다. only-live.sh 는 번들에 없는 훅이 부르는 lib.
cat > "$L/hooks/guard.sh" <<'EOF'
v=$(python3 "$(dirname "$0")/lib/judge.py")
python3 "$(dirname "$0")/lib/ghost.py" || true
EOF
echo '# old lib' > "$L/hooks/lib/old.sh"
printf '# judge — uses lib/util.py\nimport util\n' > "$L/hooks/lib/judge.py"
echo '# util' > "$L/hooks/lib/util.py"
echo 'source "$(dirname "$0")/lib/only-live.sh"' > "$L/hooks/unbundled.sh"
echo '# only' > "$L/hooks/lib/only-live.sh"

echo "[test_bundle_sync_lib_deps_issue561]"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "--check 는 누락 의존이 있으면 exit 1" "$rc" "1"
if printf '%s\n' "$out" | grep -q 'DRIFT plugins/fpm-core/hooks/lib/judge.py'; then ok "--check 가 누락 lib 을 이름으로 고지"; else fail "--check 가 누락 lib 을 이름으로 고지"; fi
if printf '%s\n' "$out" | grep -q 'DRIFT plugins/fpm-core/hooks/lib/util.py'; then ok "--check 가 전이 의존도 고지"; else fail "--check 가 전이 의존도 고지"; fi
check "--check 는 아무것도 만들지 않는다" "$(ls "$B/hooks/lib" | tr '\n' ' ')" "old.sh "

sync_out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" 2>&1)"; rc=$?
check "동기 rc 0" "$rc" "0"
if cmp -s "$B/hooks/lib/judge.py" "$L/hooks/lib/judge.py"; then ok "훅 참조 lib 을 싣는다"; else fail "훅 참조 lib 을 싣는다"; fi
if cmp -s "$B/hooks/lib/util.py" "$L/hooks/lib/util.py"; then ok "lib 의 lib 도 싣는다(전이)"; else fail "lib 의 lib 도 싣는다(전이)"; fi
check "라이브에도 없는 참조는 만들지 않는다" "$([ -e "$B/hooks/lib/ghost.py" ] && echo made || echo absent)" "absent"
check "번들에 없는 훅의 lib 은 싣지 않는다" "$([ -e "$B/hooks/lib/only-live.sh" ] && echo made || echo absent)" "absent"
check "번들에 없는 훅 자체도 싣지 않는다(수동 편입 원칙 유지)" "$([ -e "$B/hooks/unbundled.sh" ] && echo made || echo absent)" "absent"
# 무결성 매니페스트는 추적 파일(`git ls-files`)만 싣는다 — 동기가 만든 신규 파일이 미추적이면
#   매니페스트에서 빠지고 pre-commit 무결성 게이트가 커밋을 거부한다(2026-09-28 실발생).
#   ⚠️ 해법이 공유 인덱스 조작(intent-to-add)이면 안 된다 — issue-tx 임시 인덱스 커밋 뒤 공유
#   인덱스에 i-t-a 가 남고, 다른 세션의 맨 `git commit` 이 그 파일을 **삭제로 커밋**한다(실측).
MF="$B/.fpm-integrity.json"
check "동기가 만든 신규 lib 이 매니페스트에 실린다" "$(grep -c '"hooks/lib/judge.py"\|"hooks/lib/util.py"' "$MF" 2>/dev/null)" "2"
check "스킬 rsync 가 만든 신규 파일도 매니페스트에 실린다" "$(grep -c '"skills/fbot-icon/new.py"' "$MF" 2>/dev/null)" "1"
check "공유 인덱스는 건드리지 않는다(스테이징·i-t-a 0)" "$(git -C "$R" diff --cached --name-only | wc -l | tr -d ' ')/$(git -C "$R" ls-files -- plugins/fpm-core/hooks/lib/judge.py | wc -l | tr -d ' ')" "0/0"
if printf '%s\n' "$sync_out" | grep -q '신규 3 파일' && printf '%s\n' "$sync_out" | grep -q '+ plugins/fpm-core/hooks/lib/judge.py'; then ok "새로 만든 파일을 커밋 대상으로 고지"; else fail "새로 만든 파일을 커밋 대상으로 고지"; fi

git -C "$R" add -A && git -C "$R" -c user.name=t -c user.email=t@t commit -q -m synced >/dev/null 2>&1
HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check >/dev/null 2>&1; rc=$?
check "동기 후 --check exit 0 (표류 없음)" "$rc" "0"
check "커밋 후 매니페스트 자기검사 통과" "$(bash "$R/sh/gen-integrity-manifest.sh" --check >/dev/null 2>&1; echo $?)" "0"

echo
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
