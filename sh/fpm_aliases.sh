# shellcheck shell=bash
# sh/fpm_aliases.sh — fpm alias 모음
#
# fpm.sh 부트스트랩이 FPM_BASE export 후 본 파일을 source.
# 함수는 sh/fpm_function.sh 로 분리됨.

# --- iterm-bg alias (Projects.md color 기반, 자동 생성) ---
# 생성: sh/update-iterm-bg → sh/fpm_aliases_iterm-bg.sh ($FPM_BASE 기반)
# 버그 이력: 이전엔 ~/.zsh_aliases_iterm-bg.sh 로 생성만 되고 어디서도 source 안 됨
#            → 재생성본 미로드. 본 줄에서 로드하여 해결 (출력 파일도 설치 폴더 내부로 이동).
[ -f "${FPM_BASE}/sh/fpm_aliases_iterm-bg.sh" ] && . "${FPM_BASE}/sh/fpm_aliases_iterm-bg.sh"
