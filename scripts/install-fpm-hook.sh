#!/usr/bin/env bash
# install-fpm-hook.sh — ___pm git post-commit 에 fpm-sync 자동 트리거 블록 설치 (멱등)
#
# graphify hook(# graphify-hook-start/end)과 공존. fpm 블록을 post-commit 맨 앞에
# backgrounded subshell 로 prepend → graphify 의 조기 exit 영향 차단 + 비차단 실행.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$ROOT/.git/hooks/post-commit"
MARKER="# fpm-sync-hook-start"

if [ -f "$HOOK" ] && grep -qF "$MARKER" "$HOOK"; then
    echo "[install-fpm-hook] 이미 설치됨 — skip"
    exit 0
fi

BLOCK_FILE="$(mktemp)"
cat > "$BLOCK_FILE" <<'EOF'
# fpm-sync-hook-start
# ___pm publishable → fpm 자동 동기화 (비차단). 설치: scripts/install-fpm-hook.sh
(
    GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
    [ -d "$GIT_DIR/rebase-merge" ] && exit 0
    [ -d "$GIT_DIR/rebase-apply" ] && exit 0
    [ -f "$GIT_DIR/MERGE_HEAD" ] && exit 0
    [ -f "$GIT_DIR/CHERRY_PICK_HEAD" ] && exit 0
    ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
    [ -x "$ROOT/scripts/fpm-sync.sh" ] && "$ROOT/scripts/fpm-sync.sh"
) >/dev/null 2>&1 &
# fpm-sync-hook-end

EOF

if [ ! -f "$HOOK" ]; then
    printf '#!/bin/sh\n' > "$HOOK"
fi

# shebang(1행) 뒤에 fpm 블록 삽입 (graphify 블록 앞)
TMP="$(mktemp)"
{ head -1 "$HOOK"; cat "$BLOCK_FILE"; tail -n +2 "$HOOK"; } > "$TMP"
mv "$TMP" "$HOOK"
chmod +x "$HOOK"
rm -f "$BLOCK_FILE"
echo "[install-fpm-hook] post-commit 에 fpm-sync 블록 설치 완료"
