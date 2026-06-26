#!/usr/bin/env bash
# test_publish_gates.sh — 공개 게이트 4머신 회귀 테스트 (Issue211 Phase 1 / 영역 E)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 공개 push 시 개인정보/시크릿 누출을
#   막는 결정적 게이트(fpm-guard / fpm-dir-gate / fpm-sanitize / fpm-secret-scan)를
#   양성(주입된 누출=차단)·음성(clean=통과) 픽스처로 exit-code 단언 검증한다.
#   머신 계약과 동일하게 출력 파싱 없이 exit code 만 본다.
#
# 설계 SSOT: _doc_arch/fpm-release-test.md (E 영역) / plan: _doc_work/plan/fpm-release-test_plan.md
# 전례: resource/·keyboard-maestro/ exclude 갭 유출(Issue163) → dir-gate 도입(Issue164).
#
# 실행: bash scripts/test_publish_gates.sh
# exit: 0=전부 PASS, 1=하나 이상 FAIL. (gitleaks 부재 시 secret-scan 0/1 케이스는 SKIP)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
GUARD="$HERE/fpm-guard.sh"
DIRGATE="$HERE/fpm-dir-gate.sh"
SANITIZE="$HERE/fpm-sanitize.sh"
SECRETSCAN="$HERE/fpm-secret-scan.sh"

PASS=0; FAIL=0; SKIP=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
skip() { printf '  \033[33mSKIP\033[0m %s\n' "$1"; SKIP=$((SKIP+1)); }

# 임시 작업 루트 (전체 trap cleanup)
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ── fixture policy (자급 — 실 정책 내용 비의존, 결정적) ───────────
FIX_POLICY="$WORK/fixture-policy.yml"
cat > "$FIX_POLICY" <<'YML'
exclude:
  - .git/
  - SECRET_HOST.md
personal_guard:
  - 'SECRET_HOST\.md$'
  - 'finfra-server-access'
mirror_dir_allow:
  - data
  - scripts
sanitize:
  - {from: "$HOME", to: "$HOME"}
  - {from: "host.v1.2", to: "host.local"}
YML

# assert_rc <expected> <label> -- <cmd...>
assert_rc() {
    local exp="$1" label="$2"; shift 3   # drop expected,label,'--'
    local rc=0
    "$@" >/dev/null 2>&1 || rc=$?
    if [ "$rc" -eq "$exp" ]; then ok "$label (rc=$rc)"; else bad "$label (기대 $exp, 실제 $rc)"; fi
}

echo "═══ E-2 공개 게이트 양/음성 회귀 ═══"

# ── T1.4 guard (tree 모드) ───────────────────────────────────────
echo "[guard]"
CLEAN="$WORK/guard_clean"; mkdir -p "$CLEAN/data"; echo "ok" > "$CLEAN/data/a.md"
TAINT="$WORK/guard_taint"; mkdir -p "$TAINT/data"; echo "x" > "$TAINT/SECRET_HOST.md"
assert_rc 0 "음성: clean 트리 통과"          -- env FPM_POLICY="$FIX_POLICY" bash "$GUARD" tree "$CLEAN"
assert_rc 1 "양성: personal_guard 경로 차단" -- env FPM_POLICY="$FIX_POLICY" bash "$GUARD" tree "$TAINT"

# ── T1.3 dir-gate ────────────────────────────────────────────────
echo "[dir-gate]"
DG_OK="$WORK/dg_ok"; mkdir -p "$DG_OK/data" "$DG_OK/scripts"; echo y > "$DG_OK/data/x"
DG_BAD="$WORK/dg_bad"; mkdir -p "$DG_BAD/data" "$DG_BAD/resource"; echo y > "$DG_BAD/resource/cert"
assert_rc 0 "음성: allowlist 내 top dir 통과"            -- env FPM_POLICY="$FIX_POLICY" bash "$DIRGATE" "$DG_OK"
assert_rc 1 "양성: 미등록 top dir(resource/) 차단(Issue163 재현)" -- env FPM_POLICY="$FIX_POLICY" bash "$DIRGATE" "$DG_BAD"

# ── T1.5 sanitize (in-place + 원본 불변 + quotemeta) ─────────────
echo "[sanitize]"
SAN="$WORK/san"; mkdir -p "$SAN/data"
printf 'path=$HOME/secret host=host.v1.2 end\n' > "$SAN/data/conf.txt"
# 원본 불변 검증용 마커 — ROOT 밖 파일은 절대 건드리면 안 됨
OUTSIDE="$WORK/outside.txt"; printf '$HOME/keep\n' > "$OUTSIDE"
assert_rc 0 "치환 실행(rc=0)" -- env FPM_POLICY="$FIX_POLICY" bash "$SANITIZE" "$SAN"
if grep -qF '$HOME/secret' "$SAN/data/conf.txt" && ! grep -qF '$HOME' "$SAN/data/conf.txt"; then
    ok "in-place: $HOME → \$HOME 치환"
else bad "in-place 치환 누락"; fi
# host.v1.2 의 '.' 가 정규식 메타로 오작동하지 않고 리터럴 매칭됐는지(quotemeta)
if grep -qF 'host.local' "$SAN/data/conf.txt"; then ok "quotemeta: 메타문자 from 리터럴 치환"; else bad "quotemeta 치환 실패"; fi
if grep -qF '$HOME/keep' "$OUTSIDE"; then ok "원본 불변: ROOT 밖 파일 미변경"; else bad "ROOT 밖 파일 오염!"; fi

# ── T1.2 secret-scan (gitleaks 의존) ─────────────────────────────
echo "[secret-scan]"
if command -v gitleaks >/dev/null 2>&1; then
    SS_OK="$WORK/ss_ok"; mkdir -p "$SS_OK/data"; echo "hello world" > "$SS_OK/data/a.txt"
    SS_BAD="$WORK/ss_bad"; mkdir -p "$SS_BAD/data"
    # 더미 AWS 키 주입. ⚠️ 2가지 주의:
    #   (1) 'EXAMPLE' 키(AKIAIOSFODNN7EXAMPLE 등)는 gitleaks 기본 allowlist → non-example 사용.
    #   (2) 본 스크립트 소스 자체도 공개 미러 forward 시 gitleaks 스캔 대상 → 정적 키 리터럴이
    #       있으면 forward 가 자기 자신을 시크릿으로 차단(self-flag). 따라서 키를 런타임 결합으로
    #       분할(소스엔 연속 AKIA[16] 리터럴 없음). 작성된 creds.txt 엔 완전 키 → 테스트 정상.
    _ak="AKIA""Z5OAQ7TR4N3JKLMW"
    _sk="wJalr9XutnFK7sMDpQbPx2""RfiCYz1a8BvN0eLmTq"
    printf 'aws_access_key_id = %s\naws_secret_access_key = %s\n' "$_ak" "$_sk" > "$SS_BAD/data/creds.txt"
    # 기본 룰만 사용 (fixture 는 repo .gitleaks.toml 비의존) → FPM_GITLEAKS_CONFIG 를 빈 경로로 강제
    assert_rc 0 "음성: clean 트리 통과"       -- env FPM_GITLEAKS_CONFIG=/nonexistent FPM_SRC="$REPO" bash "$SECRETSCAN" "$SS_OK"
    assert_rc 1 "양성: 더미 AWS 키 검출 차단"  -- env FPM_GITLEAKS_CONFIG=/nonexistent FPM_SRC="$REPO" bash "$SECRETSCAN" "$SS_BAD"
else
    # 도구 부재 = fail-loud exit 2 경로 검증 (graceful skip 시나리오)
    SS_OK="$WORK/ss_ne"; mkdir -p "$SS_OK/data"; echo x > "$SS_OK/data/a"
    assert_rc 2 "gitleaks 부재 → exit2 fail-loud" -- env FPM_SRC="$REPO" bash "$SECRETSCAN" "$SS_OK"
    skip "secret-scan 0/1 케이스 (gitleaks 미설치 — brew install gitleaks)"
fi

# ── T1.6 정책 일관성 (실 정책 publishable-policy.yml) ────────────
echo "═══ E-3 정책 일관성 ═══"
REAL_POLICY="$REPO/data/publishable-policy.yml"
# self-exclude: 정책·룰·가드머신 자체가 exclude 에 포함 (미러 비공개)
for must in "data/publishable-policy.yml" ".gitleaks.toml" "scripts/fpm-sync.sh"; do
    if grep -qF "$must" "$REAL_POLICY"; then ok "self-exclude: $must"; else bad "self-exclude 누락: $must"; fi
done
# 개인 운영파일 제외
for must in "Servers.md" "Projects.md" "data/hub_setting.yml" "data/fapp.txt"; do
    if grep -qF "$must" "$REAL_POLICY"; then ok "개인파일 제외: $must"; else bad "개인파일 제외 누락: $must"; fi
done
# yq/python3 파싱 동일성 (둘 다 가용 시) — exclude 카운트 일치
if command -v yq >/dev/null 2>&1 && python3 -c 'import yaml' 2>/dev/null; then
    c_yq="$(yq '.exclude[]' "$REAL_POLICY" | grep -c .)"
    c_py="$(python3 -c 'import yaml,sys; print(len(yaml.safe_load(open(sys.argv[1]))["exclude"]))' "$REAL_POLICY")"
    if [ "$c_yq" -eq "$c_py" ]; then ok "yq↔python3 exclude 카운트 동일($c_yq)"; else bad "yq($c_yq)↔python3($c_py) 불일치"; fi
else
    skip "yq↔python3 파싱 동일성 (한쪽 도구 부재)"
fi

# ── 요약 ─────────────────────────────────────────────────────────
echo "──────────────────────────────────────"
printf 'PASS=%d FAIL=%d SKIP=%d\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ]
