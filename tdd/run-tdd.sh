#!/usr/bin/env bash
# run-tdd.sh — 머신별 기능 테스트 러너 (Issue430)
#
# 현재 플랫폼을 판정해 cases/core.yml + cases/<platform>.yml 을 돈다.
# 목적은 "코드를 읽어선 안 보이는 실패" 를 그 OS 에서 실제로 드러내는 것이다.
#
# 사용: bash tdd/run-tdd.sh [--list] [--only core|macos|linux|windows]
# exit: 0=전부 통과 / 1=하나라도 FAIL
set -uo pipefail

# ⚠️ 경로 기준은 **자기 위치**다 (Issue429 교훈 — $FPM_BASE 는 rc 가 export 하므로
#    비대화 셸·타 머신에서 미정의고, 그때 빈 경로로 검색해 거짓 PASS 를 낸다).
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
export REPO_DIR
TDD_DIR="$REPO_DIR/tdd"

LIST_ONLY=0; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --list) LIST_ONLY=1; shift ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

# 플랫폼 판정 — sh/fpm_function.sh 의 _fpm_platform 이 SSOT. 재구현하지 않는다.
if [ -f "$REPO_DIR/sh/fpm_function.sh" ]; then
  . "$REPO_DIR/sh/fpm_function.sh" >/dev/null 2>&1 || true
fi
if command -v _fpm_platform >/dev/null 2>&1; then
  PLATFORM="$(_fpm_platform)"
else
  PLATFORM="unknown"
fi
# wsl 은 linux 케이스를 쓴다 (차이가 드러나면 그때 분리한다)
CASE_PLATFORM="$PLATFORM"; [ "$PLATFORM" = "wsl" ] && CASE_PLATFORM="linux"

PASS=0; FAIL=0
printf '\n\033[1m▶ fpm TDD — platform=%s (uname=%s)\033[0m\n' "$PLATFORM" "$(uname -s 2>/dev/null)"

run_file() {
  local yf="$1" label="$2"
  [ -f "$yf" ] || return 0
  printf '\n\033[1m[%s]\033[0m %s\n' "$label" "$yf"
  # YAML 파싱은 python 에 맡긴다 — 셸 파서를 손으로 짜면 그 자체가 버그원이다
  local n; n=$(python3 -c "
import yaml,io,sys
d=yaml.safe_load(io.open('$yf',encoding='utf-8')) or {}
print(len(d.get('cases') or []))" 2>/dev/null || echo 0)
  local i=0
  while [ "$i" -lt "$n" ]; do
    local id desc run expect out rc
    id=$(python3 -c "
import yaml,io; d=yaml.safe_load(io.open('$yf',encoding='utf-8'))
print(d['cases'][$i].get('id',''))")
    desc=$(python3 -c "
import yaml,io; d=yaml.safe_load(io.open('$yf',encoding='utf-8'))
print(d['cases'][$i].get('desc',''))")
    run=$(python3 -c "
import yaml,io; d=yaml.safe_load(io.open('$yf',encoding='utf-8'))
print(d['cases'][$i].get('run',''))")
    expect=$(python3 -c "
import yaml,io; d=yaml.safe_load(io.open('$yf',encoding='utf-8'))
print(d['cases'][$i].get('expect','exit0'))")
    i=$((i+1))
    if [ "$LIST_ONLY" = 1 ]; then printf '  · %-24s %s\n' "$id" "$desc"; continue; fi

    out=$(bash -c "$run" 2>/dev/null); rc=$?
    local okflag=1
    case "$expect" in
      exit0)          [ "$rc" -eq 0 ] || okflag=0 ;;
      nonempty)       [ -n "$out" ] || okflag=0 ;;
      nonzero-epoch)  case "$out" in ''|*[!0-9]*) okflag=0 ;; *) [ "$out" -gt 0 ] || okflag=0 ;; esac ;;
      contains:*)     case "$out" in *"${expect#contains:}"*) ;; *) okflag=0 ;; esac ;;
      *)              [ "$rc" -eq 0 ] || okflag=0 ;;
    esac
    if [ "$okflag" = 1 ]; then
      printf '  \033[32m✅\033[0m %-24s %s\n' "$id" "$desc"; PASS=$((PASS+1))
    else
      printf '  \033[31m❌\033[0m %-24s %s\n' "$id" "$desc"
      printf '     expect=%s rc=%s out=%s\n' "$expect" "$rc" "${out:-<빈값>}"
      FAIL=$((FAIL+1))
    fi
  done
}

case "$ONLY" in
  # 기본: core(공통) → 플랫폼 → deploy(배포 체인).
  #   deploy 는 저작 머신에서만 의미 있는 항목을 포함하지만, 소비자에서도
  #   무결성·버전 정합은 유효하다. 역할이 아닌 항목은 케이스가 skip 을 낸다.
  "")     run_file "$TDD_DIR/cases/core.yml" "core"
          run_file "$TDD_DIR/cases/$CASE_PLATFORM.yml" "$CASE_PLATFORM"
          run_file "$TDD_DIR/cases/deploy.yml" "deploy" ;;
  *)      run_file "$TDD_DIR/cases/$ONLY.yml" "$ONLY" ;;
esac

[ "$LIST_ONLY" = 1 ] && exit 0

mkdir -p "$TDD_DIR/results"
printf '%s platform=%s pass=%s fail=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$PLATFORM" "$PASS" "$FAIL" \
  >> "$TDD_DIR/results/history.log"

printf '\n────────────────────────────────\n'
printf '결과: \033[32mPASS %d\033[0m / \033[31mFAIL %d\033[0m  (platform=%s)\n' "$PASS" "$FAIL" "$PLATFORM"
[ "$FAIL" -eq 0 ] || { printf '\033[31m❌ 이 머신에서 동작하지 않는 기능이 있다 — 위 항목의 why 를 볼 것\033[0m\n'; exit 1; }
printf '\033[32m✅ 이 머신에서 전부 통과\033[0m\n'
