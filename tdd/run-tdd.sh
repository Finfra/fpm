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

# ── 케이스 파서 인터프리터 해석 (Issue435 ⓒ) ──────────────────
# 판정 기준은 **존재가 아니라 "케이스를 실제로 읽을 수 있는가"** 다.
#   · jpc1 실측: Windows 의 `python3` 는 MS Store 스텁이라 이름만 있고 실행되지 않는다
#   · jma 실측: `python3` 가 정상 동작해도 그 인터프리터에 pyyaml 이 없으면 파싱이 통째로 실패한다
# 존재만 보면 둘 다 통과시켜 놓고 파싱에서 죽는다 — 그래서 `import yaml` 까지를 조건으로 삼는다.
PY=""; PY_REJECT=""
# shellcheck disable=SC2086  # "py -3" 는 단어 분리가 의도된 후보다
for _c in "${FBOT_PYTHON:-}" python3 python "py -3"; do
  [ -n "$_c" ] || continue
  if $_c -c 'import yaml' >/dev/null 2>&1; then PY="$_c"; break; fi
  if $_c -c 'import sys' >/dev/null 2>&1; then
    PY_REJECT="$PY_REJECT $_c(pyyaml 없음)"
  else
    PY_REJECT="$PY_REJECT $_c(실행 불가)"
  fi
done
if [ -z "$PY" ]; then
  # ⓐ fail-loud — "돌 게 없다" 가 아니라 "돌 수 없다" 다. 0 으로 뭉개지 않는다.
  printf '\n\033[31m🚨 케이스를 읽을 인터프리터가 없다 — 검사를 수행할 수 없다\033[0m\n' >&2
  printf '   후보 탈락:%s\n' "${PY_REJECT:- (후보 없음)}" >&2
  printf '   조치: pyyaml 이 있는 python 을 PATH 에 두거나 FBOT_PYTHON 으로 지정한다\n' >&2
  printf '         ex) pip3 install pyyaml   /   FBOT_PYTHON=/usr/bin/python3 bash tdd/run-tdd.sh\n' >&2
  exit 2
fi

PASS=0; FAIL=0
printf '\n\033[1m▶ fpm TDD — platform=%s (uname=%s)\033[0m\n' "$PLATFORM" "$(uname -s 2>/dev/null)"

run_file() {
  local yf="$1" label="$2"
  [ -f "$yf" ] || return 0
  printf '\n\033[1m[%s]\033[0m %s\n' "$label" "$yf"
  # YAML 파싱은 python 에 맡긴다 — 셸 파서를 손으로 짜면 그 자체가 버그원이다
  # ⚠️ 실패를 0 으로 뭉개지 않는다 (Issue435 ⓐ) — 그 삼킴이 "0건 돌고 전부 통과" 의 발원지였다.
  # ⚠️ 경로는 **argv 로 넘긴다** (Issue435 ⓔ · jpc1 실측 2026-08-31 · 설계 W3).
  #    `-c` 스크립트 **문자열 안에 경로를 박으면** MSYS 의 POSIX→Windows 경로 변환이
  #    적용되지 않아 Windows python 이 `/c/Users/…` 를 열지 못하고 FileNotFoundError 로 죽는다.
  #    argv 로 넘어가는 인자는 MSYS 가 변환해 준다 — 그래서 같은 파일이 A 는 실패, B 는 성공한다.
  #    macOS·Linux 에서는 둘 다 통하므로 이 결함은 Windows 에서만 드러난다.
  # 파싱은 파일당 1회. 종전엔 케이스마다 4번씩 인터프리터를 띄워 Windows 에서 특히 느렸다.
  local parsed
  if ! parsed=$($PY -c '
import sys, io, yaml, base64
# ⚠️ Windows python 의 stdout 은 텍스트 모드라 \n 을 \r\n 으로 바꾼다 (Issue435 ⓕ · jpc1 실측).
#    그러면 셸의 `read` 가 \n 에서 자른 뒤 **마지막 필드 끝에 \r 이 남아** base64 디코드가 깨진다.
#    같은 계열로 stdout 인코딩도 로케일 기본값(한국어 Windows = cp949)이라, 한글·em-dash 를
#    쓰는 출력이 UnicodeEncodeError 로 죽는다. 둘 다 여기서 못박는다.
try:
    sys.stdout.reconfigure(newline="\n", encoding="utf-8")
except Exception:
    pass
d = yaml.safe_load(io.open(sys.argv[1], encoding="utf-8")) or {}
for c in (d.get("cases") or []):
    row = [base64.b64encode(str(c.get(k, dv)).encode("utf-8")).decode("ascii")
           for k, dv in (("id", ""), ("desc", ""), ("expect", "exit0"), ("run", ""))]
    print("\t".join(row))
' "$yf"); then
    printf '\n\033[31m🚨 케이스 파일을 읽지 못했다: %s (파서=%s)\033[0m\n' "$yf" "$PY" >&2
    exit 2
  fi

  local id desc run expect out rc
  while IFS=$'\t' read -r id desc expect run; do
    [ -n "$id$desc$expect$run" ] || continue
    id=$(printf '%s' "$id"     | base64 -d)
    desc=$(printf '%s' "$desc" | base64 -d)
    expect=$(printf '%s' "$expect" | base64 -d)
    run=$(printf '%s' "$run"   | base64 -d)
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
  done <<< "$parsed"
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
# (Issue440) 결과에는 개인 경로·호스트명이 섞인다. prj1 은 .gitignore 로 막지만 **그 .gitignore 는 미러로
# sync 되지 않는다**(publishable-policy 의 exclude 항목 — 미러가 자체 관리). 그래서 소비자 repo
# (fg1·jma 실측)에서는 `?? tdd/results/` 로 추적 후보에 뜬다. 폴더가 스스로를 무시하게 두면
# 미러 .gitignore 에 손대지 않고 어느 설치본에서든 성립한다.
[ -f "$TDD_DIR/results/.gitignore" ] || printf '*\n' > "$TDD_DIR/results/.gitignore"
printf '%s platform=%s pass=%s fail=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$PLATFORM" "$PASS" "$FAIL" \
  >> "$TDD_DIR/results/history.log"

printf '\n────────────────────────────────\n'
printf '결과: \033[32mPASS %d\033[0m / \033[31mFAIL %d\033[0m  (platform=%s)\n' "$PASS" "$FAIL" "$PLATFORM"
# ⓑ 0건은 통과가 아니다 — 파싱을 고쳐도 이 가드는 남긴다. 다른 이유로 0건이 되는 경우가 또 생긴다
#   (케이스 파일 부재·--only 오타·플랫폼 판정 실패). "돌지 않았다" 를 "통과" 로 읽히게 두지 않는다.
if [ "$((PASS+FAIL))" -eq 0 ]; then
  printf '\033[31m🚨 실행된 케이스가 0건 — 통과가 아니라 "돌지 않았다"\033[0m\n' >&2
  printf '   확인: 케이스 파일 존재 여부 · --only 인자 · platform=%s 판정\n' "$PLATFORM" >&2
  exit 1
fi
[ "$FAIL" -eq 0 ] || { printf '\033[31m❌ 이 머신에서 동작하지 않는 기능이 있다 — 위 항목의 why 를 볼 것\033[0m\n'; exit 1; }
printf '\033[32m✅ 이 머신에서 전부 통과\033[0m\n'
