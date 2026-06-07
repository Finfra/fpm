#!/usr/bin/env bash
# install.sh — fpm 설치 스크립트 (멱등)
#
# 동작:
#   1. <repo>/shell/fpm-functions.zsh 를 ~/.zshrc 에서 source (마커 가드 — 중복 방지)
#   2. ~/.info/__pmBasePath.txt 생성 → <repo>/projects
#   3. projects/ 스캐폴드 (없으면 생성)
#   4. 운영 필수 파일 배치: Servers.md / Projects.md 부재 시 *_org 예제 복사
#   5. Claude Code 플러그인(fpm-core) 설치 — hub hook·대시보드 활성화
#   6. dashboard 런타임 템플릿 심링크 (~/.claude/agents/dashboard-*)
#   7. hub 서버 안내 출력
#
# 사용: bash install.sh   (또는 ./install.sh)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFO_DIR="$HOME/.info"
BASEPATH_FILE="$INFO_DIR/__pmBasePath.txt"
ZSHRC="$HOME/.zshrc"
FUNC_FILE="$REPO_DIR/shell/fpm-functions.zsh"
MARKER="# >>> fpm functions >>>"
MARKER_END="# <<< fpm functions <<<"

info()  { printf '\033[36m[fpm]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[fpm]\033[0m %s\n' "$1"; }

# ── 1. fpm-functions.zsh source 라인 추가 (멱등) ──────────────
if [[ ! -f "$FUNC_FILE" ]]; then
    warn "함수 파일 없음: $FUNC_FILE"; exit 1
fi
if grep -qF "$MARKER" "$ZSHRC" 2>/dev/null; then
    info "~/.zshrc 에 이미 fpm 블록 존재 — skip"
else
    {
        echo ""
        echo "$MARKER"
        echo "source \"$FUNC_FILE\""
        echo "$MARKER_END"
    } >> "$ZSHRC"
    info "~/.zshrc 에 fpm 함수 source 추가"
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

# ── 5. Claude Code 플러그인 설치 (hub hook·대시보드 활성화) ────
# fpm-core 플러그인이 SessionStart/UserPromptSubmit hook 으로 hub 활성 세션·
# 활동 피드를 채운다. 셸 함수(cdf)만 설치하고 플러그인을 빼면 hub 가 비어 보임.
if command -v claude >/dev/null 2>&1; then
    if claude plugin list 2>/dev/null | grep -q "fpm-core@fpm"; then
        info "플러그인 fpm-core@fpm 이미 설치됨 — skip"
    else
        # 마켓플레이스 등록 (멱등 — 이미 있으면 무해)
        claude plugin marketplace add "$REPO_DIR" >/dev/null 2>&1 || true
        if claude plugin install fpm-core@fpm >/dev/null 2>&1; then
            info "플러그인 fpm-core@fpm 설치 완료 (hub hook·대시보드 활성화 — claude 재시작 후 적용)"
        else
            warn "플러그인 fpm-core@fpm 설치 실패 — 수동 설치: claude plugin install fpm-core@fpm"
        fi
    fi
else
    warn "claude CLI 미발견 — 플러그인 미설치"
    warn "  Claude Code 설치 후: claude plugin marketplace add \"$REPO_DIR\" && claude plugin install fpm-core@fpm"
fi

# ── 6. dashboard 런타임 템플릿 배치 (~/.claude/agents/ 심링크) ──
# dashboard agent 본문은 런너/슈퍼바이저 템플릿을 고정 절대경로
# `~/.claude/agents/dashboard-*.sh` 로 참조(shim 이 tmux pane 에서 실행 — 이 경로엔
# CLAUDE_PLUGIN_ROOT 가 없음). 플러그인 설치는 이 경로를 채우지 않으므로 직접 심링크.
# 누락 시 증상: dashboard 호출돼도 런너 미기동(파일 부재) → 대시보드 동작 안 함.
AGENTS_DIR="$HOME/.claude/agents"
DASH_SRC="$REPO_DIR/plugins/fpm-core/agents"
if [[ -d "$DASH_SRC" ]]; then
    mkdir -p "$AGENTS_DIR"
    for f in dashboard-runner.sh dashboard-supervisor.sh dashboard-queue-runner.sh dashboard-queue.sample.yaml; do
        if [[ -f "$DASH_SRC/$f" ]]; then
            ln -sfn "$DASH_SRC/$f" "$AGENTS_DIR/$f"
        fi
    done
    info "dashboard 런타임 템플릿 심링크 배치 → $AGENTS_DIR/dashboard-*"
fi

# ── 7. 안내 ──────────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────
✅ fpm 설치 완료

다음 단계:
  1) 셸 재시작 또는:  source ~/.zshrc
  1-1) Claude Code 재시작 (fpm-core 플러그인 hook 적용 — hub 활성 세션·활동 피드)
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
