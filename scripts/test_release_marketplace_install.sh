#!/bin/bash
# test_release_marketplace_install.sh — Issue543 M1-3 회귀 테스트 (tdd playlist #37 release-marketplace-install)
#
# 배포 재생목록 3행 `marketplace-install` 의 실행 수단 tdd/release-marketplace-install.sh 가
#   정상 번들은 통과시키고, 사용자가 설치해도 **기동하지 않을 번들**은 떨어뜨리는지 검증한다.
#   ① 정상: validate → 임시 HOME marketplace add → install → 설치 버전 = VERSION · hook 스크립트 전부 실행 가능 → rc 0
#   ② hooks.json 이 가리키는 스크립트 누락 → rc 1 (validate·install 은 이것을 잡지 않는다)
#   ③ hook 스크립트 실행 권한 상실 → rc 1 (직접 실행 형식이라 설치본에서 Permission denied)
#   ④ VERSION ≠ plugin.json → rc 1 (설치 버전이 출고 버전과 다르다)
#   ⑤ 실 ~/.claude 플러그인 등록부 무접촉
#
# 격리: HEAD 번들을 git archive 로 꺼낸 임시 마켓 소스. claude CLI 가 없으면 전체 skip(rc 0 아님 — rc 3).
# 실행: bash scripts/test_release_marketplace_install.sh   (claude plugin install 4회 — 수십 초)
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/mkt-install-test.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

echo "[test_release_marketplace_install]"
command -v claude >/dev/null 2>&1 || { echo "  skip claude CLI 없음 — 검증 불가"; exit 3; }
S="$REPO/tdd/release-marketplace-install.sh"
[ -f "$S" ] || { fail "대상 존재: tdd/release-marketplace-install.sh"; echo "── PASS $PASS / FAIL $FAIL"; exit 1; }
ok "대상 존재: tdd/release-marketplace-install.sh"

mkfx() {  # $1 = 이름 → HEAD 번들 사본
    mkdir -p "$SB/$1"
    git -C "$REPO" archive HEAD .claude-plugin plugins/fpm-core VERSION | tar -x -C "$SB/$1"
}
reg="$HOME/.claude/plugins/installed_plugins.json"
reg_before="$( [ -f "$reg" ] && shasum "$reg" | cut -d' ' -f1)"

mkfx good
out="$(bash "$S" --repo "$SB/good" 2>&1)"; rc=$?
check "① 정상 번들 → rc 0" "$rc" "0"
[ "$rc" -eq 0 ] || printf '%s\n' "$out" | tail -8 | sed 's/^/       /'

mkfx nohook; rm "$SB/nohook/plugins/fpm-core/hooks/fbot-idle.sh"
out="$(bash "$S" --repo "$SB/nohook" 2>&1)"; rc=$?
check "② hook 스크립트 누락 → rc 1" "$rc" "1"
case "$out" in *fbot-idle.sh*) ok "② 누락 스크립트 이름을 출력" ;; *) fail "② 누락 스크립트 이름 출력" ;; esac

mkfx noexec; chmod -x "$SB/noexec/plugins/fpm-core/hooks/fpm-hub-trigger.sh"
out="$(bash "$S" --repo "$SB/noexec" 2>&1)"; rc=$?
check "③ 실행 권한 상실 → rc 1" "$rc" "1"
case "$out" in *fpm-hub-trigger.sh*) ok "③ 권한 상실 스크립트 이름을 출력" ;; *) fail "③ 권한 상실 스크립트 이름 출력" ;; esac

mkfx badver; echo "9.9.9" > "$SB/badver/VERSION"
out="$(bash "$S" --repo "$SB/badver" 2>&1)"; rc=$?
check "④ VERSION ≠ 설치 버전 → rc 1" "$rc" "1"

reg_after="$( [ -f "$reg" ] && shasum "$reg" | cut -d' ' -f1)"
check "⑤ 실 ~/.claude 플러그인 등록부 불변" "$reg_after" "$reg_before"

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
