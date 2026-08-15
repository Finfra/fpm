#!/usr/bin/env bash
# install-precommit-tagcheck.sh — ___pm git pre-commit 에 `Issue{N}` 태그 정합 게이트 설치 (멱등, Issue325)
#
# 왜 필요한가 (Issue324 사고):
#   digest 참조 필터가 "미러 코드에 `(Issue{N})` 이 나오면 그 이슈를 공개한다" 로 동작하는 순간,
#   코드 주석의 자유 텍스트 태그가 **공개 스위치**로 승격됐다. 그래서 무관한 번호를 한 번
#   잘못 적은 것만으로 사설 이슈(프로젝트 재번호·외주명·외장 볼륨 경로)가 공개 digest 에
#   실려 push 됐다. 태그를 검증하는 곳이 어디에도 없었다.
#
# 무엇을 막는가:
#   staged 변경의 **새 `Issue{N}` 태그**에 대해 두 조건을 강제한다.
#     ① 실존   : `Issue.md` 에 `## Issue{N}:` 헤딩이 있을 것 (오타·존재하지 않는 번호 차단)
#     ② 동시성 : 같은 커밋의 staged `Issue.md` 변경분에도 그 번호가 등장할 것
#                (= 이번 작업이 실제로 다룬 이슈. 무관한 기존 번호 복붙 차단)
#
# 우회: SKIP_TAGCHECK=1 git commit …  (stderr 경고 동반 — 의도적 예외만)
# 검사 제외: Issue.md 자신 · _doc_work/** · _doc_arch/** (이력 서술 문맥)
#            · plugins/** (Issue364 — 동기 산출물이라 태그 저작처가 원본 쪽이고, 번들에서
#              차단해도 고칠 곳이 여기가 아님. 제외 목록·잔여 구멍 정본은 precommit-tagcheck.py)
# python3 부재 시 graceful skip (커밋 정상 진행) — install-precommit-scar.sh 와 동일 관례.
#
# 다른 pre-commit 블록과 마커(# tagcheck-precommit-start/end)로 공존. 멱등.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$ROOT/.git/hooks/pre-commit"
MARKER="# tagcheck-precommit-start"

if [ -f "$HOOK" ] && grep -qF "$MARKER" "$HOOK"; then
    echo "[install-precommit-tagcheck] 이미 설치됨 — skip"
    exit 0
fi

BLOCK_FILE="$(mktemp)"
cat > "$BLOCK_FILE" <<'EOF'
# tagcheck-precommit-start
# Issue{N} 태그 정합 게이트 (Issue325). 설치: scripts/install-precommit-tagcheck.sh
(
    ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
    CHK="$ROOT/scripts/precommit-tagcheck.py"
    [ -f "$CHK" ] || exit 0
    command -v python3 >/dev/null 2>&1 || exit 0
    if [ "${SKIP_TAGCHECK:-0}" = 1 ]; then
        echo "⚠️ [tagcheck] SKIP_TAGCHECK=1 — Issue 태그 정합 검사 우회 (Issue325)" >&2
        exit 0
    fi
    python3 "$CHK" || exit 1
)
RC=$?
# if 문 사용 — `[ ] && exit` 를 마지막 줄에 쓰면 RC=0 시 test 가 false(1) 반환되어
# 스크립트가 1 로 종료되는 버그가 있음 (install-precommit-scar.sh 와 동일 주의).
if [ "$RC" -ne 0 ]; then exit "$RC"; fi
# tagcheck-precommit-end

EOF

if [ ! -f "$HOOK" ]; then
    printf '#!/bin/sh\n' > "$HOOK"
fi

TMP="$(mktemp)"
{ head -1 "$HOOK"; cat "$BLOCK_FILE"; tail -n +2 "$HOOK"; } > "$TMP"
mv "$TMP" "$HOOK"
chmod +x "$HOOK"
rm -f "$BLOCK_FILE"
echo "[install-precommit-tagcheck] pre-commit 에 Issue 태그 정합 게이트 설치 완료"
