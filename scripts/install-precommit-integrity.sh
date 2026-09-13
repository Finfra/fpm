#!/usr/bin/env bash
# install-precommit-integrity.sh — ___pm git pre-commit 에 무결성 매니페스트 drift 게이트 설치 (멱등, Issue479)
#
# plugins/fpm-core/ 번들 ↔ plugins/fpm-core/.fpm-integrity.json 이 어긋난 채로 커밋되는 것을
# 차단한다. `gen-integrity-manifest.sh --check` 가 불일치면 커밋 거부.
#
# 왜 필요한가 (2026-09-05 실측): 매니페스트 재생성이 **배포 경로에만** 배선돼 있어
#   *번들만 고치고 커밋하는 경로* 가 매니페스트를 stale 로 남겼다. 그 결과 `sh/check.sh` 가
#   2026-09-01 이래 상시 FAIL 이었는데 release-check.sh 호출처가 0건이라 아무도 몰랐다
#   (Issue478 결손2). scripts/fpm-bundle-sync.sh 말미 재생성(Issue479 ①)이 정상 경로를 덮고,
#   본 게이트가 **손으로 번들을 고치는 경로**까지 막아 재발 자체를 없앤다.
#
# 검사 범위: **스테이징에 plugins/fpm-core/ 가 포함된 커밋만**. 번들을 건드리지 않는 커밋까지
#   막으면 무관한 작업을 볼모로 잡게 되고, 그런 게이트는 곧 SKIP=1 상시화로 무력화된다.
#   판정 대상은 작업트리 실물이다(생성기가 파일을 해시하므로) — 부분 스테이징 시 어긋날 수
#   있으며 이는 scar-manifest 게이트와 동일한 성격이다.
#
# 우회는 SKIP_INTEGRITY=1 (tagcheck 의 SKIP_TAGCHECK 와 대칭).
# python3/생성기 부재 시 graceful skip(커밋 정상 진행) — 최소 환경 무해.
#
# 다른 pre-commit 블록과 마커(# integrity-precommit-start/end)로 공존. 멱등.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$ROOT/.git/hooks/pre-commit"
MARKER="# integrity-precommit-start"

if [ -f "$HOOK" ] && grep -qF "$MARKER" "$HOOK"; then
    echo "[install-precommit-integrity] 이미 설치됨 — skip"
    exit 0
fi

BLOCK_FILE="$(mktemp)"
cat > "$BLOCK_FILE" <<'EOF'
# integrity-precommit-start
# 무결성 매니페스트 drift 게이트 (Issue479). 설치: scripts/install-precommit-integrity.sh
(
    ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
    GEN="$ROOT/sh/gen-integrity-manifest.sh"
    [ -f "$GEN" ] || exit 0
    command -v python3 >/dev/null 2>&1 || exit 0
    if [ "${SKIP_INTEGRITY:-0}" = 1 ]; then
        echo "⚠️ [integrity] SKIP_INTEGRITY=1 — 매니페스트 정합 검사 우회 (Issue479)" >&2
        exit 0
    fi
    # 번들을 건드리지 않는 커밋은 검사하지 않는다 (범위 근거는 설치 스크립트 주석)
    git diff --cached --name-only --diff-filter=ACMR -- 'plugins/fpm-core' \
        | grep -q . || exit 0
    if ! bash "$GEN" --check >/dev/null 2>&1; then
        echo "❌ [integrity] 번들 ↔ .fpm-integrity.json 불일치 — 커밋 거부 (Issue479)" >&2
        echo "   원인: 번들 파일이 바뀌었는데 매니페스트가 재생성되지 않았다" >&2
        echo "   해결: bash scripts/fpm-bundle-sync.sh   (라이브→번들 동기 + 매니페스트 재생성)" >&2
        echo "         또는 bash sh/gen-integrity-manifest.sh 후 'git add plugins/fpm-core/.fpm-integrity.json'" >&2
        echo "   상세: bash sh/gen-integrity-manifest.sh --check" >&2
        echo "   우회: SKIP_INTEGRITY=1 git commit ...  (무결성 결손을 안고 커밋한다는 뜻)" >&2
        exit 1
    fi
)
RC=$?
# if 문 사용 — `[ ] && exit` 를 마지막 줄에 쓰면 RC=0 시 test 가 false(1) 반환되어
# 스크립트가 1 로 종료되는 버그가 있음. if 는 조건 false 시 0 반환(후속 hook 블록도 보존).
if [ "$RC" -ne 0 ]; then exit "$RC"; fi
# integrity-precommit-end

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
echo "[install-precommit-integrity] pre-commit 에 무결성 매니페스트 drift 게이트 설치 완료"
