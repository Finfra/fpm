#!/usr/bin/env bash
# install-precommit-scar.sh — ___pm git pre-commit 에 SCAR 매니페스트 drift 게이트 설치 (멱등, Issue240_4)
#
# data/scar-manifest.yml(SSOT) ↔ data/install_manifest.sh(파생) ↔ claude_forNewServer/(디스크)
# 가 어긋난 채로 커밋되는 것을 차단한다. `gen-install-manifest.sh --check` 가 drift(exit 2)면
# 커밋 거부. python3/pyyaml/생성기 부재 시 graceful skip(커밋 정상 진행) — 최소 환경 무해.
#
# 다른 pre-commit 블록과 마커(# scar-manifest-precommit-start/end)로 공존. 멱등.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$ROOT/.git/hooks/pre-commit"
MARKER="# scar-manifest-precommit-start"

if [ -f "$HOOK" ] && grep -qF "$MARKER" "$HOOK"; then
    echo "[install-precommit-scar] 이미 설치됨 — skip"
    exit 0
fi

BLOCK_FILE="$(mktemp)"
cat > "$BLOCK_FILE" <<'EOF'
# scar-manifest-precommit-start
# SCAR 매니페스트 drift 게이트 (Issue240_4). 설치: scripts/install-precommit-scar.sh
(
    ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
    GEN="$ROOT/sh/gen-install-manifest.sh"
    [ -f "$GEN" ] || exit 0
    command -v python3 >/dev/null 2>&1 || exit 0
    python3 -c 'import yaml' >/dev/null 2>&1 || exit 0
    if ! bash "$GEN" --check >/dev/null 2>&1; then
        echo "❌ [scar-manifest] drift 감지 — 커밋 거부 (Issue240_4)" >&2
        echo "   원인: data/scar-manifest.yml ↔ install_manifest.sh 또는 ↔ claude_forNewServer/ 불일치" >&2
        echo "   해결: data/scar-manifest.yml 수정 → bash sh/gen-install-manifest.sh → 재커밋" >&2
        echo "   상세: bash sh/gen-install-manifest.sh --check" >&2
        exit 1
    fi
)
RC=$?
[ "$RC" -ne 0 ] && exit "$RC"
# scar-manifest-precommit-end

EOF

if [ ! -f "$HOOK" ]; then
    printf '#!/bin/sh\n' > "$HOOK"
fi

# shebang(1행) 뒤에 블록 삽입 (다른 hook 블록 앞)
TMP="$(mktemp)"
{ head -1 "$HOOK"; cat "$BLOCK_FILE"; tail -n +2 "$HOOK"; } > "$TMP"
mv "$TMP" "$HOOK"
chmod +x "$HOOK"
rm -f "$BLOCK_FILE"
echo "[install-precommit-scar] pre-commit 에 SCAR 매니페스트 drift 게이트 설치 완료"
