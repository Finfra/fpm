#!/bin/bash
# test_deploy_line_close_issue601.sh — Issue601 회귀 테스트 (tdd playlist #75 deploy-line-close)
#
# 출고 절차가 «릴리스 라인 마감»(글로벌 release-test-rules)을 스스로 수행하는지 검증한다.
#   ① deploy 기본 레벨 auto: VERSION 이 아직 출고되지 않았으면(v$CUR 태그가 소스·미러 어디에도 없음) VERSION 그대로 출고
#   ② auto: 이미 출고된 VERSION(미러 태그) 이면 종전 patch 규칙
#   ③ auto: 소스 태그만 있어도 출고된 것으로 본다
#   ④ patch·minor 를 미출고 라인 버전에 명시하면 거부 — 0.8.3 라인에서 deploy minor 가 0.9.0 을 계산한 사고(2026-10-05)
#   ⑤ 출고된 VERSION 에 minor 명시 → 다음 minor (라인 전환)
#   ⑥ X.Y.Z 명시는 그대로
#   ⑦ next-version CLI 인자 생략 = auto (R1 드라이버 --version 기본값과 같은 계산)
#   ⑧ 소스 태그: v$NEW 를 HEAD 에 만든다 · 다른 커밋에 이미 있으면 옮기지 않고 경고
#   ⑨ GitHub Release: 미러 origin 에서 저장소를 읽어 `gh release create v$NEW -R <owner/repo> --verify-tag` 를 조립 · 이미 있으면 skip · gh 실패는 경고(출고 성공은 유지)
#   ⑩ do_deploy 배선(정적): 기본 레벨 auto · 미러 태그 뒤 소스 태그 · push 성공 경로에서만 Release · 완료 로그에 다음 라인 안내
#
# 격리: 임시 git repo 2개(소스·미러). 대상 함수는 실물 scripts/fpm-sync.sh 에서 **추출**해 eval 한다(재구현 금지).
# 실행: bash scripts/test_deploy_line_close_issue601.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SYNC="$REPO/scripts/fpm-sync.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/line-close.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

echo "[test_deploy_line_close_issue601]"
export GIT_CONFIG_GLOBAL=/dev/null   # 사용자 전역 gitignore·hook 격리 (전역 Icon? 무시 규칙이 fixture 를 삼킨 선례)

FUNCS="$SB/funcs.sh"
for fn in next_patch_version version_released deploy_target_version src_tag_release gh_release_create; do
    awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {p=1} p {print} p && /^}/ {p=0}' "$SYNC" >> "$FUNCS"
done

S="$SB/src"; D="$SB/dst"
G() { git -C "$1" -c user.name=t -c user.email=t@t "${@:2}"; }
mkdir -p "$S" "$D"
echo "0.1.0" > "$S/VERSION"
git -C "$S" init -q -b main && G "$S" add -A && G "$S" commit -q -m c0
echo m > "$D/README"
git -C "$D" init -q -b main && G "$D" add -A && G "$D" commit -q -m m0
git -C "$D" remote add origin git@github.com:Finfra/fpm.git

# 추출 함수를 fixture 에 대고 부른다 — exit 은 서브셸에 가둔다
run() {
    ( SRC="$S"; DST="$D"; VERSION_REL=VERSION
      log() { printf '%s\n' "$1"; }
      . "$FUNCS"
      "$@" )
}

# ── ① auto · 미출고 → VERSION 그대로 ──
out="$(run deploy_target_version auto 2>&1)"; rc=$?
check "① auto · v0.1.0 태그 없음 → 0.1.0" "$rc:$out" "0:0.1.0"

# ── ④ 미출고 라인 버전에 patch·minor → 거부 ──
out="$(run deploy_target_version patch 2>&1)"; rc=$?
check "④ patch · 미출고 VERSION → 거부" "$rc" "1"
case "$out" in *"0.1.0"*) ok "④ 거부 사유에 VERSION 그대로 출고하라는 안내" ;; *) fail "④ 거부 사유 안내 (out: $out)" ;; esac
out="$(run deploy_target_version minor 2>&1)"; rc=$?
check "④ minor · 미출고 VERSION → 거부" "$rc" "1"

# ── ⑥ X.Y.Z 명시 ──
out="$(run deploy_target_version 0.3.7 2>&1)"; rc=$?
check "⑥ X.Y.Z 명시 → 그대로" "$rc:$out" "0:0.3.7"

# ── ③ 소스 태그만 → 출고된 것으로 ──
G "$S" tag v0.1.0
out="$(run deploy_target_version auto 2>&1)"; rc=$?
check "③ auto · 소스 태그 v0.1.0 → 다음 patch 0.1.1" "$rc:$out" "0:0.1.1"
G "$S" tag -d v0.1.0 >/dev/null

# ── ② 미러 태그 → 출고된 것으로 ──
G "$D" tag v0.1.0
out="$(run deploy_target_version auto 2>&1)"; rc=$?
check "② auto · 미러 태그 v0.1.0 → 다음 patch 0.1.1" "$rc:$out" "0:0.1.1"

# ── ⑤ 출고된 VERSION 에 minor → 라인 전환 ──
out="$(run deploy_target_version minor 2>&1)"; rc=$?
check "⑤ minor · 출고된 VERSION → 0.2.0" "$rc:$out" "0:0.2.0"
G "$D" tag -d v0.1.0 >/dev/null

# ── ⑦ next-version CLI 인자 생략 = auto ──
out="$(FPM_SRC="$S" FPM_DST="$D" bash "$SYNC" next-version 2>/dev/null)"; rc=$?
check "⑦ next-version (인자 없음) · 미출고 → 0.1.0" "$rc:$out" "0:0.1.0"

# ── ⑧ 소스 태그 ──
run src_tag_release 0.1.0 >/dev/null 2>&1
tag_at="$(git -C "$S" rev-parse -q --verify 'refs/tags/v0.1.0^{commit}' 2>/dev/null)"
check "⑧ 소스 태그 v0.1.0 → HEAD" "$tag_at" "$(git -C "$S" rev-parse HEAD)"
echo x >> "$S/VERSION"; G "$S" commit -qam c1
out="$(run src_tag_release 0.1.0 2>&1)"; rc=$?
tag_at2="$(git -C "$S" rev-parse -q --verify 'refs/tags/v0.1.0^{commit}' 2>/dev/null)"
check "⑧ 다른 커밋에 이미 있는 태그는 옮기지 않는다" "$tag_at2" "$tag_at"
case "$out" in *"⚠️"*) ok "⑧ 기존 태그 충돌 경고" ;; *) fail "⑧ 기존 태그 충돌 경고 (out: $out)" ;; esac

# ── ⑨ GitHub Release (gh stub) ──
GHLOG="$SB/gh.log"
cat > "$SB/gh" <<'EOF'
#!/bin/bash
echo "$*" >> "$GHLOG"
case "$1 $2" in
    "release view") exit "${GH_VIEW_RC:-1}" ;;
    "release create") exit "${GH_CREATE_RC:-0}" ;;
esac
exit 0
EOF
chmod +x "$SB/gh"
export GHLOG
: > "$GHLOG"
out="$(FPM_GH_BIN="$SB/gh" run gh_release_create 0.1.0 2>&1)"; rc=$?
check "⑨ Release 생성 rc 0" "$rc" "0"
if grep -q -- 'release create v0.1.0 -R Finfra/fpm --verify-tag' "$GHLOG"; then ok "⑨ gh release create v0.1.0 -R Finfra/fpm --verify-tag 조립"; else fail "⑨ 명령 조립 (gh.log: $(cat "$GHLOG"))"; fi
: > "$GHLOG"
out="$(GH_VIEW_RC=0 FPM_GH_BIN="$SB/gh" run gh_release_create 0.1.0 2>&1)"; rc=$?
if grep -q 'release create' "$GHLOG"; then fail "⑨ 이미 있는 Release 는 다시 만들지 않는다"; else ok "⑨ 이미 있는 Release → skip"; fi
: > "$GHLOG"
out="$(GH_CREATE_RC=1 FPM_GH_BIN="$SB/gh" run gh_release_create 0.1.0 2>&1)"; rc=$?
check "⑨ gh 실패 → 경고만 (rc 0 — 출고는 이미 끝났다)" "$rc" "0"
case "$out" in *"⚠️"*"gh release create"*) ok "⑨ 실패 시 수동 명령 안내" ;; *) fail "⑨ 실패 시 수동 명령 안내 (out: $out)" ;; esac

# ── ⑩ do_deploy 배선 (정적) ──
body="$(awk '/^do_deploy\(\) \{/{p=1} p{print} p&&/^}/{exit}' "$SYNC")"
res="$(BODY="$body" python3 - <<'PYEOF'
import os, re
b = os.environ["BODY"]
def at(p):
    m = re.search(p, b); return m.start() if m else -1
checks = {
    "default-auto": at(r'local level="auto"') >= 0,
    "auto-arg": at(r'auto\|patch\|minor\|major\)') >= 0,
    "src-tag-after-mirror-tag": 0 <= at(r'git -C "\$DST" tag -f "v\$NEW"') < at(r'src_tag_release "\$NEW"'),
    "release-after-push": 0 <= at(r'git -C "\$DST" push -f origin "v\$NEW"') < at(r'gh_release_create "\$NEW"'),
    "release-only-on-push": at(r'gh_release_create "\$NEW"') < at(r'--no-push → push 생략'),
    "next-line-hint": at(r'release/\$') >= 0 or at(r'다음 라인') >= 0,
}
bad = [k for k, v in checks.items() if not v]
print("ok" if not bad else "BROKEN:" + ",".join(bad))
PYEOF
)"
check "⑩ do_deploy: auto 기본 · 소스 태그 · push 뒤 Release · 다음 라인 안내" "$res" "ok"

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
