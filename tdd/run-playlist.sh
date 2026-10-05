#!/usr/bin/env bash
# run-playlist.sh — 개발 재생목록 tdd/playlist.md 전 행 실행 (Issue543 M1-2 · release.md 1행 dev-playlist-green)
#
# 표의 실행 열을 위에서 아래로 돈다(tdd/playlist-run.py). 외부 대기 행(«hub 기동 필요» 등)은
#   돌리지 않고 skip — 후보 코드가 아닌 운영 hub 를 검사하게 되기 때문이다. 그런 행이 남아 있으면
#   이 러너는 rc 3(partial)이고, 배포 재생목록 1행도 partial 이 된다(release.md 목표 문구 그대로).
#
# 사용: bash tdd/run-playlist.sh [--list] [--only id,id] [--timeout 초]
# exit: 0 전 행 pass · 3 skip 존재 · 1 fail 존재 · 2 입력 오류
set -uo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
exec python3 "$REPO_DIR/tdd/playlist-run.py" "$REPO_DIR/tdd/playlist.md" "$@"
