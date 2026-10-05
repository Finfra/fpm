#!/bin/bash
# test_release_record_failloud.sh — Issue543 M1-0b 회귀 테스트 (tdd playlist #34 release-record-fail-loud)
#
# G3 통과 기록이 **실패하면 실패로 드러나는지** 검증한다. 종전에는 두 겹으로 삼켰다:
#   ① sh/release-check.sh 가 기록기를 `|| true` 로 불렀다
#   ② 기록기(scripts/fpm-deploy-record.sh --gate)가 mkdir·append 실패 뒤에도 `exit 0` 으로 끝났다
# 그 결과 "5스테이지 PASS + 기록 없음" 이 rc 0 으로 끝나 출고 게이트가 근거 없이 막히거나,
# 사람이 "돌렸다" 고 믿는데 파일은 답하지 못한다(codex plan-check medium, 2026-09-27).
#
# 격리: 임시 git repo + 임시 HOME. release-check.sh·기록기는 **실물 복사**, 무거운 스테이지 스크립트만 stub.
# 실행: bash scripts/test_release_record_failloud.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
unset FPM_RELEASE_MAIN_REPO FPM_RELEASE_CANDIDATE FPM_RELEASE_GATE_STATE FPM_RELEASE_EVIDENCE_DIR   # 바깥 R1 문맥 비상속
SB="$(mktemp -d "${TMPDIR:-/tmp}/rec-failloud.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

R="$SB/repo"; H="$SB/home"
mkdir -p "$R/sh" "$R/scripts" "$R/data" "$R/services/hub" "$R/plugins/fpm-core/.claude-plugin" "$H"
cp "$REPO/sh/release-check.sh" "$R/sh/"
cp "$REPO/scripts/fpm-deploy-record.sh" "$R/scripts/"
echo "0.0.1" > "$R/VERSION"
echo '{"name":"fpm-core","version":"0.0.1"}' > "$R/plugins/fpm-core/.claude-plugin/plugin.json"
echo 'FPM_PLUGIN_NAME=fpm-core' > "$R/data/install_manifest.sh"
printf '#!/bin/bash\nexit 0\n' > "$R/scripts/test_publish_gates.sh"
printf '#!/bin/bash\nexit 0\n' > "$R/scripts/test_mirror_install.sh"
M='# >>> fpm functions >>>'
cat > "$R/sh/install.sh" <<EOF
#!/bin/bash
d="\$(cd "\$(dirname "\$0")/.." && pwd)"
[ -f "\$d/data/install_manifest.sh" ] || exit 1
grep -qF "$M" "\$HOME/.zshrc" 2>/dev/null || echo "$M" >> "\$HOME/.zshrc"
EOF
printf '#!/bin/bash\ngrep -qF "%s" "$HOME/.zshrc"\n' "$M" > "$R/sh/check.sh"
printf '#!/bin/bash\ngrep -vF "%s" "$HOME/.zshrc" > "$HOME/.zshrc.n"; mv "$HOME/.zshrc.n" "$HOME/.zshrc"\n' "$M" > "$R/sh/uninstall.sh"
git -C "$R" init -q -b main
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base

echo "[test_release_record_failloud]"

# ── 기준선: 기록 가능 → rc 0 + 기록 1줄 ──
ST="$SB/gates.yml"
out="$(HOME="$H" FPM_RELEASE_GATE_STATE="$ST" bash "$R/sh/release-check.sh" --quiet 2>&1)"; rc=$?
check "기준선: 스테이지 전부 PASS + 기록 가능 → rc 0" "$rc" "0"
check "기준선: G3 기록 1줄" "$(grep -c '^  - { .*suite: release,' "$ST" 2>/dev/null)" "1"

# ── 기록기 단독: 쓸 수 없는 경로 → rc ≠ 0 ──
BAD="/dev/null/nope/release-gates.yml"
FPM_RELEASE_GATE_STATE="$BAD" bash "$R/scripts/fpm-deploy-record.sh" --gate release --repo "$R" >/dev/null 2>&1; rc=$?
if [ "$rc" -ne 0 ]; then ok "기록기: 쓰기 실패 → rc≠0 (got $rc)"; else fail "기록기: 쓰기 실패인데 rc 0 (조용한 통과)"; fi

# ── release-check: 스테이지 PASS 인데 기록 실패 → rc ≠ 0 ──
out="$(HOME="$H" FPM_RELEASE_GATE_STATE="$BAD" bash "$R/sh/release-check.sh" --quiet 2>&1)"; rc=$?
if [ "$rc" -ne 0 ]; then ok "release-check: 기록 실패 → rc≠0 (got $rc)"; else fail "release-check: 기록 실패인데 rc 0 (|| true 삼킴)"; fi
case "$out" in *기록*실패*) ok "release-check: 기록 실패를 출력에 남긴다" ;; *) fail "release-check: 기록 실패 문구 없음" ;; esac

# ── --no-sandbox 는 여전히 기록하지 않고 rc 0 (부분 실행 비기록 규약 유지) ──
out="$(HOME="$H" FPM_RELEASE_GATE_STATE="$BAD" bash "$R/sh/release-check.sh" --quiet --no-sandbox 2>&1)"; rc=$?
check "--no-sandbox: 기록 시도 없음 → rc 0" "$rc" "0"

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
