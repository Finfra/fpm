#!/usr/bin/env bash
# uninstall.sh — fpm 제거 (백업 후 제거, 멱등)
#
# 동작:
#   1. 셸 rc(zshrc/bashrc) 의 fpm 블록(마커 사이) 추출 백업 → 제거
#   2. ~/.info/__pmBasePath.txt 백업 → 제거
#   3. [SCAR] fpm-core 플러그인 uninstall (claude CLI 존재 + --no-scar 아닐 때)
#   4. 백업 위치: ${FPM_BACKUP_DIR:-<repo>/_doc_work/z_done}/fpm-uninstall-<ts>/
#
# 보존(삭제 안 함): projects/ · Projects.md · Servers.md (사용자 데이터)
#   → 사용자 데이터까지 지우려면 백업 확인 후 직접 rm
# 보존(제거 안 함): marketplace FPM_MKT_NAME — fQRGen·fBanner 등 타 플러그인 공유 마켓.
#   marketplace remove 는 그 마켓의 모든 플러그인을 cascade uninstall → 제거 금지.
#
# 사용: bash sh/uninstall.sh              셸 + SCAR 제거 (기본)
#       bash sh/uninstall.sh --no-scar    SCAR 플러그인 제거 생략 (셸만)
#   클린 재설치는 sh/install.sh --clean (= uninstall 후 install)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 스크립트는 sh/ 하위 → repo 루트는 한 단계 위

# ── 아티팩트 SSOT 로드 (install/check 공통) ───────────────────
MANIFEST="$REPO_DIR/data/install_manifest.sh"
if [[ -f "$MANIFEST" ]]; then
    # shellcheck source=data/install_manifest.sh
    source "$MANIFEST"
    BASEPATH_FILE="$HOME/$FPM_BASEPATH_REL_HOME"
    MARKER="$FPM_MARKER"
    MARKER_END="$FPM_MARKER_END"
else
    # 매니페스트 부재(구버전 잔존 제거 등) — 안전 fallback 상수
    BASEPATH_FILE="$HOME/.info/__pmBasePath.txt"
    MARKER="# >>> fpm functions >>>"
    MARKER_END="# <<< fpm functions <<<"
fi
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${FPM_BACKUP_DIR:-$REPO_DIR/_doc_work/z_done}/fpm-uninstall-$TS"

info()  { printf '\033[36m[fpm]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[fpm]\033[0m %s\n' "$1"; }

# ── 인자 ──────────────────────────────────────────────────────
NO_SCAR=0
for arg in "$@"; do
    case "$arg" in
        --no-scar) NO_SCAR=1 ;;
        -h|--help)
            echo "usage: sh/uninstall.sh [--no-scar]"
            echo "  --no-scar : fpm-core 플러그인 제거 생략 — 셸 아티팩트만"
            exit 0 ;;
        *) warn "알 수 없는 인자: $arg (무시)" ;;
    esac
done

REMOVED=0

# ── rc 파일의 fpm 블록 백업 후 제거 (zsh + bash 양쪽) ──
strip_rc_block() {
    local RC="$1" name
    name="$(basename "$RC")"
    [[ -f "$RC" ]] || return 0
    if ! grep -qF "$MARKER" "$RC"; then
        info "$name: fpm 블록 없음 — skip"
        return 0
    fi
    mkdir -p "$BACKUP_DIR"
    # 마커 사이(마커 라인 포함) 블록 추출 백업
    sed -n "/$MARKER/,/$MARKER_END/p" "$RC" > "$BACKUP_DIR/${name}_fpm_block.txt"
    # 블록 제거 (BSD/GNU sed 양립: -i 에 백업접미사 명시 후 삭제)
    sed -i.fpmbak "/$MARKER/,/$MARKER_END/d" "$RC"
    rm -f "$RC.fpmbak"
    info "$name: fpm 블록 백업 후 제거"
    REMOVED=1
}
strip_rc_block "$HOME/.zshrc"
strip_rc_block "$HOME/.bashrc"

# ── ~/.info/__pmBasePath.txt 백업 후 제거 ──
if [[ -f "$BASEPATH_FILE" ]]; then
    mkdir -p "$BACKUP_DIR"
    cp "$BASEPATH_FILE" "$BACKUP_DIR/__pmBasePath.txt"
    rm -f "$BASEPATH_FILE"
    info "__pmBasePath.txt 백업 후 제거"
    REMOVED=1
fi

# ── [SCAR] fpm-core 플러그인 제거 (멱등) ──────────────────────
#   marketplace(FPM_MKT_NAME)는 공유 자산 — 제거 안 함(타 플러그인 cascade 보호).
#   plugin uninstall 만 수행. 백업 불필요(sh/install.sh 재실행으로 복원).
if [[ "$NO_SCAR" -eq 0 ]]; then
    if ! command -v claude >/dev/null 2>&1; then
        info "claude CLI 미발견 → SCAR 플러그인 제거 건너뜀 (셸-only)"
    elif claude plugin list 2>/dev/null | grep -qF "$FPM_PLUGIN_NAME"; then
        if claude plugin uninstall "$FPM_PLUGIN_NAME" >/dev/null 2>&1 \
           || claude plugin uninstall "${FPM_PLUGIN_NAME}@${FPM_MKT_NAME}" >/dev/null 2>&1; then
            info "fpm-core 플러그인 제거 완료 (marketplace '$FPM_MKT_NAME' 은 공유 — 보존)"
            REMOVED=1
        else
            warn "fpm-core 플러그인 제거 실패 — 수동: claude plugin uninstall $FPM_PLUGIN_NAME"
        fi
    else
        info "fpm-core 플러그인 미설치 — skip"
    fi
else
    info "SCAR 플러그인 제거 생략 (--no-scar)"
fi

# ── 결과 안내 ──
if [[ "$REMOVED" -eq 1 ]]; then
    cat <<EOF

────────────────────────────────────────────
✅ fpm 제거 완료 (셸 아티팩트)

백업:  $BACKUP_DIR
보존:  projects/ · Projects.md · Servers.md (사용자 데이터 — 필요 시 직접 rm)
보존:  marketplace $FPM_MKT_NAME (공유 마켓 — 타 플러그인 보호)

다음 단계:
  1) 셸 재시작 (또는 새 셸) 으로 fpm 함수 해제 반영
  2) 재설치       : bash sh/install.sh
     클린 재설치  : bash sh/install.sh --clean
────────────────────────────────────────────
EOF
else
    info "제거할 fpm 설치 흔적 없음 (이미 제거됨)"
fi
