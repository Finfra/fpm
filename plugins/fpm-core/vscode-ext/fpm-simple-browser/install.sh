#!/bin/bash
# install.sh — fpm-simple-browser 확장 패키징 + 설치 (___pm Issue216).
#   vsce package → code --install-extension. 멱등(idempotent) — 재실행 시 재설치.
#   설치 후 VSCode 창 새로고침(Cmd+R / "Developer: Reload Window") 1회 필요.
set -euo pipefail
cd "$(dirname "$0")"

VSIX="fpm-simple-browser-0.0.1.vsix"

echo "[1/3] vsce package..."
vsce package --allow-missing-repository --skip-license -o "$VSIX" >/dev/null

echo "[2/3] code --install-extension..."
code --install-extension "$VSIX" --force

echo "[3/3] 완료. ⚠️ VSCode 창 새로고침 1회 필요 (Cmd+Shift+P → 'Developer: Reload Window')."
echo "  검증: open \"vscode://finfra.fpm-simple-browser/open?url=http%3A%2F%2F127.0.0.1%3A9876%2Ffpm-icon.png\""
