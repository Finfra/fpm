#!/usr/bin/env bash
# update.sh — fpm 머신 갱신 단일 진입점 (셸 + SCAR), Issue236
#
# 머신 갱신이 ① 셸 `git pull` ② `claude plugin marketplace update` ③ `claude plugin update`
# 로 흩어진 수동 다단계였다. 한 진입점으로 묶어 셸·SCAR 이원 경로를 일괄 갱신한다.
#
# 동작:
#   1. [셸] git -C $FPM_BASE pull  → 부트스트랩·함수·alias 최신화 (재source 안내)
#   2. [SCAR] claude plugin marketplace update + claude plugin update fpm-core
#
# 사용: bash sh/update.sh           셸 + SCAR 모두 갱신
#       bash sh/update.sh --shell-only   git pull 만
#       bash sh/update.sh --scar-only    SCAR(plugin) 만
# exit: 0=성공(부분 WARN 허용), 1=치명 실패
set -uo pipefail

# FPM_BASE: env 우선, 없으면 스크립트 위치로 자기 탐지 (install-location agnostic)
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
FPM_BASE="${FPM_BASE:-$REPO_DIR}"

info()  { printf '\033[36m[update]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[update]\033[0m %s\n' "$1"; }
err()   { printf '\033[31m[update]\033[0m %s\n' "$1" >&2; }

MANIFEST="$FPM_BASE/data/install_manifest.sh"
if [[ -f "$MANIFEST" ]]; then source "$MANIFEST"; fi
FPM_MKT_NAME="${FPM_MKT_NAME:-f-claude-plugins}"
FPM_PLUGIN_NAME="${FPM_PLUGIN_NAME:-fpm-core}"
FPM_PLUGIN="${FPM_PLUGIN_NAME}@${FPM_MKT_NAME}"

DO_SHELL=1; DO_SCAR=1
for a in "$@"; do
    case "$a" in
        --shell-only) DO_SCAR=0 ;;
        --scar-only)  DO_SHELL=0 ;;
        -h|--help) echo "usage: sh/update.sh [--shell-only] [--scar-only]"; exit 0 ;;
        *) warn "알 수 없는 인자: $a (무시)" ;;
    esac
done

FAIL=0

# ── 1. 셸 갱신 (git pull) ────────────────────────────────────
if [[ "$DO_SHELL" -eq 1 ]]; then
    if [[ -d "$FPM_BASE/.git" ]]; then
        info "[셸] git -C $FPM_BASE pull…"
        if git -C "$FPM_BASE" pull --ff-only 2>&1 | sed 's/^/  /'; then
            info "[셸] 갱신 완료 — 새 셸을 열거나 'source ~/.zshrc' 로 재로드하세요."
        else
            warn "[셸] git pull 실패(로컬 변경·충돌?) — 수동 확인 필요"
            FAIL=1
        fi
    else
        warn "[셸] $FPM_BASE 는 git 저장소가 아님 — git pull 생략"
    fi
fi

# ── 2. SCAR 갱신 (plugin) ────────────────────────────────────
if [[ "$DO_SCAR" -eq 1 ]]; then
    if ! command -v claude >/dev/null 2>&1; then
        warn "[SCAR] 'claude' CLI 미발견 → 플러그인 갱신 생략 (셸-only 환경 정상)"
    else
        info "[SCAR] marketplace update: $FPM_MKT_NAME"
        claude plugin marketplace update "$FPM_MKT_NAME" 2>&1 | sed 's/^/  /' \
            || warn "[SCAR] marketplace update 실패 (계속 진행)"
        info "[SCAR] plugin update: $FPM_PLUGIN"
        if claude plugin update "$FPM_PLUGIN" 2>&1 | sed 's/^/  /'; then
            info "[SCAR] 갱신 완료 — Claude Code 재시작 후 적용"
        elif claude plugin update "$FPM_PLUGIN_NAME" 2>&1 | sed 's/^/  /'; then
            info "[SCAR] 갱신 완료(plugin 이름 fallback) — 재시작 후 적용"
        else
            warn "[SCAR] plugin update 실패 — 'claude plugin install $FPM_PLUGIN' 수동 시도 권장"
            FAIL=1
        fi
    fi
fi

[[ "$FAIL" -eq 0 ]] && { info "✅ 갱신 완료"; exit 0; } || { err "일부 단계 실패 — 위 경고 확인"; exit 1; }
