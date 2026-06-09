# shellcheck shell=bash
# sh/fpm.sh — fpm 부트스트랩 (FPM_BASE 결정 → 함수·alias 로드 + 외부 소비자용 캐시 갱신)
#
# 설치 위치 무관 동작(~/_git/___pm, ~/_git/__all/fpm 등)을 위한 단일 진입점.
# 권장 로드 — ~/.zshrc / ~/.bashrc 에서:
#   export FPM_BASE=~/_git/___pm        # 설치 위치 (또는 ~/_git/__all/fpm)
#   [[ -f "$FPM_BASE/sh/fpm.sh" ]] && source "$FPM_BASE/sh/fpm.sh"
# FPM_BASE 미설정 시 본 스크립트 위치(sh/ 의 상위)로 자동 추론 → env 없이도 동작.
#
# SSOT 계층 (.git 등 마커 미사용 — 자기 위치만 신뢰):
#   1) export FPM_BASE (명시 override)            — 있으면 그대로 (symlink·vendored 사본용)
#   2) self-detect (본 파일 위치)                  — 진짜 SSOT, 평소 경로
#   3) ~/.config/fpm/base (self-healing 캐시)      — fpm 미source 외부 소비자(KM 매크로·cron)용. 로드마다 갱신
#
# 구성:
#   fpm.sh              : 본 부트스트랩 (FPM_BASE 확정 + 캐시 + 하위 source)
#   fpm_function.sh     : cdf/cdff/cdfc/cdfv/cdft + sshf + 헬퍼
#   fpm_aliases.sh      : alias (iterm-bg 등)
# 이전: ~/.fpm.sh(단일) → sh/fpm.sh(이동) → sh/fpm.sh+function+aliases(분리, FPM_BASE 도입 2026-06-09)

# --- FPM_BASE 결정: env 우선, 없으면 본 파일 위치로 self-detect (.git 미확인) ---
if [ -z "${FPM_BASE:-}" ]; then
    if [ -n "${ZSH_VERSION:-}" ]; then
        eval '_fpm_self="${(%):-%x}"'   # zsh: source 중 스크립트 경로. eval 로 bash 파싱 단계 syntax error 회피
    elif [ -n "${BASH_VERSION:-}" ]; then
        _fpm_self="${BASH_SOURCE[0]}"   # bash: source 중 스크립트 경로
    else
        _fpm_self="$0"
    fi
    FPM_BASE="$(cd "$(dirname "$_fpm_self")/.." 2>/dev/null && pwd)"
    unset _fpm_self
fi
export FPM_BASE

# --- 외부 소비자용 self-healing 캐시 (~/.config/fpm/base) — 값 변할 때만 write ---
# fpm 을 source 하지 않는 소비자(Keyboard Maestro 매크로·cron·비-fpm 도구)가 base 를 읽는 단일 조회처.
# 권위 아님(투영) — 폴더 이전 시 rc source 경로만 고치면 다음 로드에 자동 정정됨.
_fpm_cache="${XDG_CONFIG_HOME:-$HOME/.config}/fpm/base"
if [ "$(cat "$_fpm_cache" 2>/dev/null)" != "$FPM_BASE" ]; then
    mkdir -p "$(dirname "$_fpm_cache")" 2>/dev/null && printf '%s\n' "$FPM_BASE" > "$_fpm_cache"
fi
unset _fpm_cache

# --- 함수 + alias 로드 ---
[ -f "$FPM_BASE/sh/fpm_function.sh" ] && . "$FPM_BASE/sh/fpm_function.sh"
[ -f "$FPM_BASE/sh/fpm_aliases.sh" ]  && . "$FPM_BASE/sh/fpm_aliases.sh"
