#!/usr/bin/env bash
# uninstall.sh — fpm 제거 (백업 후 제거, 멱등)
#
# 동작:
#   1. 셸 rc(zshrc/bashrc) 의 fpm 블록(마커 사이) 추출 백업 → 제거
#   2. ~/.info/__pmBasePath.txt 백업 → 제거
#   3. 백업 위치: ${FPM_BACKUP_DIR:-<repo>/_doc_work/z_done}/fpm-uninstall-<ts>/
#
# 보존(삭제 안 함): projects/ · Projects.md · Servers.md (사용자 데이터)
#   → 사용자 데이터까지 지우려면 백업 확인 후 직접 rm
#
# 사용: bash uninstall.sh   (또는 ./uninstall.sh)
#   클린 재설치는 install.sh --clean (= uninstall 후 install)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

# ── 결과 안내 ──
if [[ "$REMOVED" -eq 1 ]]; then
    cat <<EOF

────────────────────────────────────────────
✅ fpm 제거 완료 (셸 아티팩트)

백업:  $BACKUP_DIR
보존:  projects/ · Projects.md · Servers.md (사용자 데이터 — 필요 시 직접 rm)

다음 단계:
  1) 셸 재시작 (또는 새 셸) 으로 fpm 함수 해제 반영
  2) 재설치       : bash install.sh
     클린 재설치  : bash install.sh --clean
────────────────────────────────────────────
EOF
else
    info "제거할 fpm 설치 흔적 없음 (이미 제거됨)"
fi
