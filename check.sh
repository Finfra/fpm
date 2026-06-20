#!/usr/bin/env bash
# check.sh — fpm 설치 점검 (읽기 전용, 멱등)
#
# install.sh 가 배치한 흔적을 검사하여 설치 상태를 진단함. 아무것도 변경하지 않음.
# install.sh / uninstall.sh 와 동일하게 data/install_manifest.sh(SSOT) 를 source 하므로,
# 마커·경로·운영파일 목록·SCAR 타깃이 설치 측과 항상 일치(drift 없음).
#
# 검사 항목:
#   [셸]  1. sh/fpm.sh 부트스트랩 파일 존재
#         2. rc(zshrc/bashrc) 에 fpm 마커 블록 + FPM_BASE export
#         3. ~/.info/__pmBasePath.txt → <repo>/projects 일치
#         4. projects/ 스캐폴드 (필수 인덱스)
#         5. 운영 필수 파일 (FPM_ORG_FILES)
#         6. cdf 함수 로드 여부 (sh/fpm.sh source)
#   [SCAR] 7. claude CLI 존재
#          8. marketplace 등록 (FPM_MKT_NAME)
#          9. 플러그인 설치 (FPM_PLUGIN_NAME)
#
# 사용: bash check.sh            전체 점검 (셸 + SCAR)
#       bash check.sh --no-scar  SCAR 점검 생략 (셸만)
#       bash check.sh --quiet    PASS 항목 숨김, FAIL/WARN 만 출력
#
# 종료코드: 0=전부 PASS(WARN 허용) / 1=하나 이상 FAIL
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 아티팩트 SSOT 로드 (install/check 공통) ───────────────────
MANIFEST="$REPO_DIR/data/install_manifest.sh"
if [[ ! -f "$MANIFEST" ]]; then
    printf '\033[31m[fpm]\033[0m 🚨 매니페스트 없음: %s — 점검 불가 (저장소 손상?)\n' "$MANIFEST" >&2
    exit 1
fi
# shellcheck source=data/install_manifest.sh
source "$MANIFEST"

# 매니페스트 값 → 로컬 파생 (install.sh 와 동일 기준점)
BASEPATH_FILE="$HOME/$FPM_BASEPATH_REL_HOME"
FUNC_FILE="$REPO_DIR/$FPM_BOOTSTRAP_REL_REPO"
MARKER="$FPM_MARKER"
# FPM_MKT_NAME / FPM_PLUGIN_NAME / FPM_ORG_FILES / FPM_SCAFFOLD_INDEXES 는 매니페스트가 제공

# ── 인자 ──────────────────────────────────────────────────────
CHECK_SCAR=1
QUIET=0
for arg in "$@"; do
    case "$arg" in
        --no-scar) CHECK_SCAR=0 ;;
        --quiet|-q) QUIET=1 ;;
        -h|--help)
            echo "usage: check.sh [--no-scar] [--quiet]"
            echo "  --no-scar : SCAR(fpm-core 플러그인) 점검 생략 — 셸만"
            echo "  --quiet   : PASS 항목 숨김, FAIL/WARN 만 출력"
            exit 0 ;;
        *) printf '\033[33m[fpm]\033[0m 알 수 없는 인자: %s (무시)\n' "$arg" ;;
    esac
done

# ── 결과 카운터 + 출력 헬퍼 ───────────────────────────────────
PASS_N=0; WARN_N=0; FAIL_N=0
ok()   { PASS_N=$((PASS_N+1)); [[ "$QUIET" -eq 1 ]] || printf '  \033[32m✅ PASS\033[0m  %s\n' "$1"; }
warn() { WARN_N=$((WARN_N+1)); printf '  \033[33m⚠️  WARN\033[0m  %s\n' "$1"; }
fail() { FAIL_N=$((FAIL_N+1)); printf '  \033[31m❌ FAIL\033[0m  %s\n' "$1"; }
sec()  { printf '\n\033[36m%s\033[0m\n' "$1"; }

# ── [셸] 1. 부트스트랩 파일 ───────────────────────────────────
sec "── 셸 설치 ──"
if [[ -f "$FUNC_FILE" ]]; then
    ok "부트스트랩 존재: $FPM_BOOTSTRAP_REL_REPO"
else
    fail "부트스트랩 없음: $FUNC_FILE (install.sh 재실행 필요)"
fi

# ── 2. rc 블록 + FPM_BASE export ──────────────────────────────
RC_FOUND=0
for RC in "$HOME/.zshrc" "$HOME/.bashrc"; do
    name="$(basename "$RC")"
    [[ -f "$RC" ]] || continue
    if grep -qF "$MARKER" "$RC" 2>/dev/null; then
        RC_FOUND=1
        rc_base="$(grep -F 'export FPM_BASE=' "$RC" 2>/dev/null | tail -1 | sed -E 's/.*export FPM_BASE="?([^"]*)"?.*/\1/')"
        if [[ "$rc_base" == "$REPO_DIR" ]]; then
            ok "$name: fpm 블록 + FPM_BASE=$REPO_DIR"
        else
            warn "$name: fpm 블록 있으나 FPM_BASE='$rc_base' ≠ repo($REPO_DIR)"
        fi
    fi
done
[[ "$RC_FOUND" -eq 0 ]] && fail "rc(zshrc/bashrc) 에 fpm 마커 블록 없음 — install.sh 재실행"

# ── 3. __pmBasePath.txt ───────────────────────────────────────
if [[ -f "$BASEPATH_FILE" ]]; then
    bp="$(cat "$BASEPATH_FILE" 2>/dev/null)"
    if [[ "$bp" == "$REPO_DIR/projects" ]]; then
        ok "베이스 경로 기록 일치: $BASEPATH_FILE"
    else
        warn "베이스 경로 불일치: '$bp' ≠ '$REPO_DIR/projects'"
    fi
else
    fail "베이스 경로 파일 없음: $BASEPATH_FILE"
fi

# ── 4. projects/ 스캐폴드 ─────────────────────────────────────
if [[ -d "$REPO_DIR/projects" ]]; then
    n="$(find "$REPO_DIR/projects" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')"
    missing=""
    for idx in "${FPM_SCAFFOLD_INDEXES[@]}"; do
        [[ -f "$REPO_DIR/projects/$idx" ]] || missing="$missing $idx"
    done
    if [[ -z "$missing" ]]; then
        ok "projects/ 스캐폴드 OK (필수 인덱스 ${FPM_SCAFFOLD_INDEXES[*]} 존재, 총 ${n}개)"
    else
        warn "projects/ 존재하나 필수 인덱스 누락:$missing (총 ${n}개)"
    fi
else
    fail "projects/ 디렉토리 없음"
fi

# ── 5. 운영 필수 파일 (매니페스트 FPM_ORG_FILES — install.sh 와 동일 SSOT) ──
for pair in "${FPM_ORG_FILES[@]}"; do
    real="${pair%%:*}"
    if [[ -f "$REPO_DIR/$real" ]]; then
        ok "운영 파일 존재: $real"
    else
        warn "운영 파일 없음: $real (install.sh 가 ${pair##*:} 예제로 배치)"
    fi
done

# ── 6. cdf 함수 로드 여부 (현재 셸) ───────────────────────────
# check.sh 는 bash 서브셸 → 부모 셸 함수 미상속. fpm.sh 직접 source 후 확인.
# shellcheck disable=SC1090  # 런타임 동적 경로(매니페스트 유래) — 정적 추적 불가, 의도적
if (source "$FUNC_FILE" >/dev/null 2>&1 && command -v cdf >/dev/null 2>&1); then
    ok "cdf 함수 로드 가능 ($FPM_BOOTSTRAP_REL_REPO source)"
else
    warn "cdf 함수 로드 실패 — $FPM_BOOTSTRAP_REL_REPO source 후에도 미정의 (셸 재시작 확인)"
fi

# ── [SCAR] 7~9 ────────────────────────────────────────────────
if [[ "$CHECK_SCAR" -eq 1 ]]; then
    sec "── SCAR (fpm-core 플러그인) ──"
    if ! command -v claude >/dev/null 2>&1; then
        warn "claude CLI 미발견 → SCAR 미설치(셸-only 정상 시나리오). 점검 생략"
    else
        ok "claude CLI 존재: $(command -v claude)"
        # 8) marketplace
        if claude plugin marketplace list 2>/dev/null | grep -qF "$FPM_MKT_NAME"; then
            ok "marketplace 등록: $FPM_MKT_NAME"
        else
            fail "marketplace 미등록: $FPM_MKT_NAME (install.sh 재실행)"
        fi
        # 9) plugin
        if claude plugin list 2>/dev/null | grep -qF "$FPM_PLUGIN_NAME"; then
            ok "플러그인 설치: $FPM_PLUGIN_NAME"
        else
            fail "플러그인 미설치: $FPM_PLUGIN_NAME (claude plugin install)"
        fi
    fi
else
    sec "── SCAR 점검 생략 (--no-scar) ──"
fi

# ── 요약 ──────────────────────────────────────────────────────
printf '\n────────────────────────────────────────────\n'
printf '결과: \033[32mPASS %d\033[0m / \033[33mWARN %d\033[0m / \033[31mFAIL %d\033[0m\n' "$PASS_N" "$WARN_N" "$FAIL_N"
if [[ "$FAIL_N" -gt 0 ]]; then
    printf '\033[31m❌ 설치 불완전 — 위 FAIL 항목 확인 후 install.sh 재실행\033[0m\n'
    printf '────────────────────────────────────────────\n'
    exit 1
else
    if [[ "$WARN_N" -gt 0 ]]; then
        printf '\033[33m✅ 핵심 설치 정상 (WARN 항목은 선택/환경 의존)\033[0m\n'
    else
        printf '\033[32m✅ 설치 정상 — 전 항목 PASS\033[0m\n'
    fi
    printf '────────────────────────────────────────────\n'
    exit 0
fi
