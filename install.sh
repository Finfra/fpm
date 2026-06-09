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
# 사용: bash install.sh   (또는 ./install.sh)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFO_DIR="$HOME/.info"
BASEPATH_FILE="$INFO_DIR/__pmBasePath.txt"
ZSHRC="$HOME/.zshrc"
FUNC_FILE="$REPO_DIR/sh/fpm.sh"
MARKER="# >>> fpm functions >>>"
MARKER_END="# <<< fpm functions <<<"

info()  { printf '\033[36m[fpm]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[fpm]\033[0m %s\n' "$1"; }

# ── 1. fpm.sh 부트스트랩 source 라인 추가 (멱등) ──────────────
# FPM_BASE 명시 export 후 sh/fpm.sh source (fpm.sh 헤더 권장 로드 규약).
# fpm.sh 가 FPM_BASE 미설정 시 자기 위치로 self-detect 하나, 외부 소비자(KM·cron)
# 캐시 정합성을 위해 install 단계에서 명시 export.
if [[ ! -f "$FUNC_FILE" ]]; then
    warn "부트스트랩 파일 없음: $FUNC_FILE"; exit 1
fi
if grep -qF "$MARKER" "$ZSHRC" 2>/dev/null; then
    info "~/.zshrc 에 이미 fpm 블록 존재 — skip"
else
    {
        echo ""
        echo "$MARKER"
        echo "export FPM_BASE=\"$REPO_DIR\""
        echo "source \"$FUNC_FILE\""
        echo "$MARKER_END"
    } >> "$ZSHRC"
    info "~/.zshrc 에 fpm 부트스트랩 source 추가 (FPM_BASE=$REPO_DIR)"
fi

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
  1) 셸 재시작 또는:  source ~/.zshrc
  2) Projects.md / Servers.md 를 자신의 환경으로 편집
  3) ~/.ssh/config 의 # favorite 섹션에 sshf 대상 Host alias 정의
  4) cdf          → 프로젝트 목록 확인
     sshf         → 서버 목록 확인

[선택] hub 서버 (HTML 렌더 + 대시보드, Python 3):
  cd "$REPO_DIR/services/hub" && python3 server.py
  → http://127.0.0.1:9876/hub

[선택] Keyboard Maestro 매크로:  keyboard-maestro/README.md
────────────────────────────────────────────
EOF
