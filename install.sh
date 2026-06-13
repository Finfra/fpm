#!/usr/bin/env bash
# install.sh — fpm 설치 스크립트 (멱등)
#
# 동작:
#   1. <repo>/sh/fpm.sh 부트스트랩을 ~/.zshrc 에서 source (FPM_BASE export + 마커 가드 — 중복 방지)
#   2. ~/.info/__pmBasePath.txt 생성 → <repo>/projects
#   3. projects/ 스캐폴드 (없으면 생성)
#   4. 운영 필수 파일 배치: Servers.md / Projects.md 부재 시 *_org 예제 복사
#   5. hub 서버 안내 출력
#
# 사용: bash install.sh            (또는 ./install.sh)
#       bash install.sh --clean   클린 재설치 — uninstall.sh 로 기존 흔적 백업·제거 후 설치
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFO_DIR="$HOME/.info"
BASEPATH_FILE="$INFO_DIR/__pmBasePath.txt"
FUNC_FILE="$REPO_DIR/sh/fpm.sh"
MARKER="# >>> fpm functions >>>"
MARKER_END="# <<< fpm functions <<<"

info()  { printf '\033[36m[fpm]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[fpm]\033[0m %s\n' "$1"; }

# ── 0. 인자 파싱 ──────────────────────────────────────────────
CLEAN=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        -h|--help)
            echo "usage: install.sh [--clean]"
            echo "  --clean : uninstall.sh 로 기존 fpm 흔적 백업·제거 후 설치 (클린 재설치)"
            exit 0 ;;
        *) warn "알 수 없는 인자: $arg (무시)" ;;
    esac
done

# --clean: 설치 전 백업+제거 (uninstall.sh 위임)
if [[ "$CLEAN" -eq 1 ]]; then
    if [[ -f "$REPO_DIR/uninstall.sh" ]]; then
        info "--clean: uninstall.sh 로 기존 흔적 백업 후 제거"
        bash "$REPO_DIR/uninstall.sh"
        echo ""
        info "클린 제거 완료 — 신규 설치 진행"
    else
        warn "--clean 지정됐으나 uninstall.sh 없음 — 백업 없이 설치 진행 (멱등 재설치)"
    fi
fi

# ── 1. fpm.sh 부트스트랩 source 라인 추가 (멱등, zsh + bash 양쪽) ──
# FPM_BASE 명시 export 후 sh/fpm.sh source (fpm.sh 헤더 권장 로드 규약).
# fpm.sh 가 FPM_BASE 미설정 시 자기 위치로 self-detect 하나, 외부 소비자(KM·cron)
# 캐시 정합성을 위해 install 단계에서 명시 export.
# 대상 rc : 로그인 셸($SHELL) rc 는 없어도 생성, 반대편 rc 는 존재 시에만 추가
#   → 평소 zsh / 스크립트 bash 이중 사용까지 커버. fpm.sh 가 셸을 분기하므로
#     동일 source 라인이 zsh·bash 양쪽에서 동작.
if [[ ! -f "$FUNC_FILE" ]]; then
    warn "부트스트랩 파일 없음: $FUNC_FILE"; exit 1
fi

# 대상 rc 수집 (빈 배열 미발생 — bash 3.2 set -u 안전)
declare -a RC_FILES=()
LOGIN_SHELL="$(basename "${SHELL:-}")"
if [[ "$LOGIN_SHELL" == "bash" ]]; then
    RC_FILES+=("$HOME/.bashrc")
    [[ -f "$HOME/.zshrc" ]] && RC_FILES+=("$HOME/.zshrc")
else
    # zsh 또는 미상 → zsh 우선
    RC_FILES+=("$HOME/.zshrc")
    [[ -f "$HOME/.bashrc" ]] && RC_FILES+=("$HOME/.bashrc")
fi

for RC in "${RC_FILES[@]}"; do
    rc_name="$(basename "$RC")"
    if grep -qF "$MARKER" "$RC" 2>/dev/null; then
        info "$rc_name 에 이미 fpm 블록 존재 — skip"
    else
        {
            echo ""
            echo "$MARKER"
            echo "export FPM_BASE=\"$REPO_DIR\""
            echo "source \"$FUNC_FILE\""
            echo "$MARKER_END"
        } >> "$RC"
        info "$rc_name 에 fpm 부트스트랩 source 추가 (FPM_BASE=$REPO_DIR)"
    fi
done

# ── 2. __pmBasePath.txt 생성 ──────────────────────────────────
mkdir -p "$INFO_DIR"
echo "$REPO_DIR/projects" > "$BASEPATH_FILE"
info "베이스 경로 기록: $BASEPATH_FILE → $REPO_DIR/projects"

# ── 3. projects/ 스캐폴드 ─────────────────────────────────────
if [[ ! -d "$REPO_DIR/projects" ]]; then
    mkdir -p "$REPO_DIR/projects"
    echo "\$HOME"           > "$REPO_DIR/projects/0"
    echo "$REPO_DIR"        > "$REPO_DIR/projects/1"
    info "projects/ 스캐폴드 생성 (0=home, 1=repo). Projects.md 참고하여 추가하세요."
fi

# ── 4. 운영 필수 파일 배치 (_org → 실파일) ────────────────────
place_org() {
    local real="$1" org="$2"
    if [[ -f "$REPO_DIR/$real" ]]; then
        info "$real 이미 존재 — 보존"
    elif [[ -f "$REPO_DIR/$org" ]]; then
        cp "$REPO_DIR/$org" "$REPO_DIR/$real"
        info "$org → $real 배치 (자신의 정보로 교체하세요)"
    fi
}
place_org "Servers.md"  "Servers_org.md"
place_org "Projects.md" "Projects_org.md"

# ── 5. 안내 ──────────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────
✅ fpm 설치 완료

다음 단계:
  1) 셸 재시작 (또는 zsh: source ~/.zshrc  /  bash: source ~/.bashrc)
  2) Projects.md / Servers.md 를 자신의 환경으로 편집
  3) ~/.ssh/config 의 # favorite 섹션에 sshf 대상 Host alias 정의
  4) cdf          → 프로젝트 목록 확인
     sshf         → 서버 목록 확인

[선택] hub 서버 (HTML 렌더 + 대시보드, Python 3):
  cd "$REPO_DIR/services/hub" && python3 server.py
  → http://127.0.0.1:9876/hub

[선택] Keyboard Maestro 매크로:  keyboard-maestro/README.md

제거:  bash uninstall.sh        (셸 흔적 백업 후 제거)
클린 재설치:  bash install.sh --clean
────────────────────────────────────────────
EOF
