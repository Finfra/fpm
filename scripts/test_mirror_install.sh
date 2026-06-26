#!/usr/bin/env bash
# test_mirror_install.sh — 공개 미러 dry-run + 설치 회귀 (Issue211 Phase 2 A-4 / E-4)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). fpm-sync forward 의 미러 스냅샷 생성
#   레시피(git archive → sanitize → exclude rsync → gates)를 fpm 에 적용(rsync --delete)
#   하지 않고 임시 디렉토리에 재현한다. 그 "공개본 사본"만으로:
#     (1) 게이트 통과(secret-scan·dir-gate·guard) — E-4 end-to-end dry-run
#     (2) 샌드박스 install 성공 — A-4 공개본 설치
#     (3) exclude 로 빠진 hub_setting.yml 이 hub_setting_org.yml 에서 복원 — A-4 핵심
#   ⚠️ fpm(DST) 트리·___pm 버전을 일절 건드리지 않음(읽기 전용 dry-run).
#
# 설계 SSOT: _doc_arch/fpm-release-test.md (A-4·E-4) / forward 레시피: scripts/fpm-sync.sh:139-156
# 실행: bash scripts/test_mirror_install.sh
# exit: 0=PASS, 1=FAIL. (git archive HEAD 기준 — 커밋된 트리만 미러됨)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
# shellcheck source=fpm-policy-lib.sh
FPM_SRC="$REPO"; export FPM_SRC
. "$HERE/fpm-policy-lib.sh"

PASS=0; FAIL=0
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }

read_policy || { echo "🚨 정책 로드 실패"; exit 1; }

TMP="$(mktemp -d)"; TMP2="$(mktemp -d)"; SBX="$(mktemp -d)"
trap 'rm -rf "$TMP" "$TMP2" "$SBX"' EXIT

echo "═══ A-4 / E-4 공개 미러 dry-run + 설치 ═══"

# [1] forward 레시피 재현 (fpm 미적용) ────────────────────────────
git -C "$REPO" archive HEAD | tar -x -C "$TMP" || { echo "🚨 git archive 실패"; exit 1; }
"$HERE/fpm-sanitize.sh" "$TMP" >/dev/null 2>&1 || { bad "sanitize 실행"; }
rsync -a "${EXCLUDES[@]}" "$TMP"/ "$TMP2"/ >/dev/null 2>&1 && ok "미러 스냅샷 생성(exclude rsync)" || bad "미러 rsync"

# [2] 게이트 통과 (E-4) ───────────────────────────────────────────
if FPM_SRC="$REPO" FPM_POLICY="$POLICY" "$HERE/fpm-dir-gate.sh" "$TMP2" >/dev/null 2>&1; then
    ok "dir-gate: 미러 top-level 전부 allowlist 내"
else bad "dir-gate: 미등록 top dir 검출(공개 차단됨)"; fi
if FPM_SRC="$REPO" "$HERE/fpm-guard.sh" tree "$TMP2" >/dev/null 2>&1; then
    ok "guard: 미러에 personal_guard 경로 0"
else bad "guard: 개인정보 경로 잔존"; fi
if command -v gitleaks >/dev/null 2>&1; then
    if FPM_SRC="$REPO" FPM_POLICY="$POLICY" "$HERE/fpm-secret-scan.sh" "$TMP2" >/dev/null 2>&1; then
        ok "secret-scan: 미러 내용 시크릿 0"
    else bad "secret-scan: 미러에 시크릿 검출(공개 차단됨)"; fi
else
    printf '  \033[33mSKIP\033[0m secret-scan (gitleaks 미설치)\n'
fi

# [3] 개인값 제외 확인 (A-4) ──────────────────────────────────────
[ ! -f "$TMP2/data/hub_setting.yml" ] && ok "exclude: hub_setting.yml 미러에 없음(개인값)" || bad "hub_setting.yml 미러 유출!"
[ -f "$TMP2/data/hub_setting_org.yml" ] && ok "템플릿: hub_setting_org.yml 미러에 존재" || bad "hub_setting_org.yml 미러 누락"
[ ! -f "$TMP2/Servers.md" ] && ok "exclude: Servers.md 미러에 없음" || bad "Servers.md 미러 유출!"

# [4] 미러 사본으로 샌드박스 install (A-4) ────────────────────────
if [ -f "$TMP2/sh/install.sh" ]; then
    : > "$SBX/.zshrc"
    if env HOME="$SBX" bash "$TMP2/sh/install.sh" --no-scar >/dev/null 2>&1; then
        ok "공개본 install 성공(--no-scar)"
    else bad "공개본 install 실패"; fi
    # 핵심: install 이 org→real 복원 → 미러 data/hub_setting.yml 생성
    [ -f "$TMP2/data/hub_setting.yml" ] && ok "org 복원: install 이 hub_setting.yml 생성" || bad "org 복원 실패"
    # 복원된 기본값 안전성 — language 기본 en (국제 사용자)
    if [ -f "$TMP2/data/hub_setting.yml" ] && grep -qE '^language:[[:space:]]*en' "$TMP2/data/hub_setting.yml"; then
        ok "기본값 안전: language: en"
    else bad "기본값: language 기본 en 아님"; fi
else
    bad "미러에 sh/install.sh 없음"
fi

echo "──────────────────────────────────────"
printf 'PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
