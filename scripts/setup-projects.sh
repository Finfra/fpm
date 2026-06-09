#!/bin/zsh
# setup-projects.sh — DEPRECATED shim (2026-06-09).
#
# 과거: projects/ 인덱스 경로를 하드코딩하여 재생성.
# 현재: Projects.md(SSOT) 파싱 기반 통합 드라이버 sh/fpm-projects-sync 로 위임.
#       (projects/ 인덱스 + 각 .vscode 배경색·이모지 + iterm-bg alias 일괄 반영)
#
# 직접 호출 대신 `fpm-projects-sync` (sh/fpm.sh 함수) 사용 권장.
exec python3 "$(cd "$(dirname "$0")/.." && pwd)/sh/fpm-projects-sync"
