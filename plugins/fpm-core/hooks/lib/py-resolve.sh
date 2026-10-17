# shellcheck shell=bash
# py-resolve.sh — SCAR python 인터프리터 해석 단일 지점 (prj3#Issue1117)   ※ source 전용
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 라이브러리는 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   절차: ~/.claude/rules/global-scar-change-rules.md · 배선 색인: ~/.claude/_doc_arch/hook-arch.md «python 해석»
#
# 쓰임: `. "$HOOKS_DIR/lib/py-resolve.sh"; PY="$(py_resolve)" || …` — bash·zsh 양쪽에서 source 된다.
#   (종전: fbot-tick.sh · fbot-worker-plist.sh · fbot-worker-unit.sh 가 서로 다른 순서의 resolve_python 3벌 — 버전은 아무도 안 봤다)
#
# 해석 순서 (먼저 «기준 3.14 이상» 을 만족한 후보가 이긴다. 없으면 발견된 것 중 최고 버전 — 경고만, 차단 아님)
#   1. $FBOT_PYTHON                 명시 설정 — 버전과 무관하게 이긴다(미달이면 경고)
#   2. ~/.local/bin/python3.14      uv 기준 설치원 — **절대경로**라 PATH 앞에 /usr/bin 이 끼어도 3.14 를 잡는다(OpenClaw, Issue1109)
#   3. ~/.local/bin/python3         이름이 버전을 보장하지 않아 --version 확인
#   4. PATH 의 python3.14           (fg1 Ubuntu 22.04: 맨 python3 = 3.10, 3.14 는 python3.14 로만 잡힌다)
#   5. py -3.14                     Windows Git Bash
#   6. PATH 의 python3              --version 확인
#   7. $PY_RESOLVE_EXTRA            공백 구분 추가 후보 — 관례 절대경로는 launchd·systemd 생성기만 넘긴다
#                                   (세션 경로에서 절대경로로 메우면 PATH 누락 원인이 가려진다 — Issue1109)
#   하한(3.14)만 보고 상한은 두지 않는다 — 3.15+ 통과. 상한을 두면 brew 업그레이드 한 번이 전 hook 정지가 된다.
#
# py_resolve [--strict] [--min M.m] [--quiet]
#   stdout  해석된 인터프리터 경로
#   rc 0    찾음. 3.14 미만이면 stderr 에 경고 1줄(프로세스 트리당 1회) — **차단하지 않는다**
#   rc 2    미발견 / --strict 에서 --min(기본 3.14) 미달 → stderr 에 `python3 = <경로> <버전> — 기준 3.14, …`
#   hook 경로는 비엄격(경고만) — fg1 은 아직 3.10, macOS /usr/bin/python3 3.9.6 으로 도는 경로가 남아 있다.
#   엄격은 «이 버전 미만이면 코드가 문법에서 죽는» 호출처(fpm-do: --min 3.10)만 쓴다.
#   변수: PY_RESOLVE_PATH · PY_RESOLVE_VER · PY_RESOLVE_SRC (서브셸 `$(…)` 안에서는 전달되지 않는다)
#   캐시: 해석 결과를 env PY_RESOLVE_CACHE 로 export — 자식 프로세스는 --version 을 다시 띄우지 않는다.
#         이름이 버전을 보장하는 후보(python3.14)는 애초에 서브프로세스가 없다.
#
# set -e 호출자에서도 안전하다 — 후보 탐색 실패는 전부 `|| true` 로 흡수하고, 의미 있는 rc 는 py_resolve 만 낸다.
# 문법 하한: 3.10 호환 유지(fg1 22.04) — 이 파일은 셸이라 해당 없음. 호출하는 py 코드는 3.11+ 전용 문법 금지.

_PYR_BASE_MAJ=3
_PYR_BASE_MIN=14

# _pyr_ver <인터프리터> → stdout "M.m.p"
_pyr_ver() {
  local out
  out="$("$1" --version 2>&1)" || return 1
  out="${out%%$'\n'*}"
  out="${out#Python }"
  case "$out" in [0-9]*.[0-9]*) ;; *) return 1 ;; esac
  printf '%s' "${out%%[[:space:]]*}"
}

# _pyr_mm <버전> → _PYR_X(major) _PYR_Y(minor). 파싱 실패 rc 1
_pyr_mm() {
  local v="$1" rest
  _PYR_X="${v%%.*}"; rest="${v#*.}"; _PYR_Y="${rest%%[!0-9]*}"
  case "${_PYR_X}${_PYR_Y}" in ''|*[!0-9]*) return 1 ;; esac
  case "$_PYR_X" in ''|*[!0-9]*) return 1 ;; esac
  case "$_PYR_Y" in ''|*[!0-9]*) return 1 ;; esac
  return 0
}

# _pyr_take <경로> <출처> [버전 — 이름이 보장하면 넘겨 서브프로세스 생략] [explicit]
#   기준 이상이면 _PYR_DONE=1. 아니면 최고 버전을 _PYR_P 에 보관.
_pyr_take() {
  local p="$1" src="$2" v="${3:-}" explicit="${4:-}"
  [ -n "$p" ] && [ -x "$p" ] || return 1
  [ -n "$v" ] || v="$(_pyr_ver "$p")" || return 1
  _pyr_mm "$v" || return 1
  if [ -z "$_PYR_P" ] || [ "$_PYR_X" -gt "$_PYR_BX" ] || { [ "$_PYR_X" -eq "$_PYR_BX" ] && [ "$_PYR_Y" -gt "$_PYR_BY" ]; }; then
    _PYR_P="$p"; _PYR_V="$v"; _PYR_S="$src"; _PYR_BX="$_PYR_X"; _PYR_BY="$_PYR_Y"
  fi
  if [ -n "$explicit" ]; then _PYR_P="$p"; _PYR_V="$v"; _PYR_S="$src"; _PYR_BX="$_PYR_X"; _PYR_BY="$_PYR_Y"; _PYR_DONE=1; return 0; fi
  if [ "$_PYR_X" -gt "$_PYR_BASE_MAJ" ] || { [ "$_PYR_X" -eq "$_PYR_BASE_MAJ" ] && [ "$_PYR_Y" -ge "$_PYR_BASE_MIN" ]; }; then
    _PYR_P="$p"; _PYR_V="$v"; _PYR_S="$src"; _PYR_BX="$_PYR_X"; _PYR_BY="$_PYR_Y"; _PYR_DONE=1
  fi
  return 0
}

# _pyr_scan — 후보를 순서대로 훑어 _PYR_P/_PYR_V/_PYR_S 를 채운다
_pyr_scan() {
  local c x
  _PYR_DONE=0; _PYR_P=""; _PYR_V=""; _PYR_S=""; _PYR_BX=0; _PYR_BY=0
  if [ -n "${FBOT_PYTHON:-}" ]; then
    _pyr_take "$FBOT_PYTHON" "FBOT_PYTHON" "" explicit \
      || printf '[py-resolve] ⚠️ FBOT_PYTHON=%s 실행·버전 확인 불가 — 무시하고 다음 후보로\n' "$FBOT_PYTHON" >&2
  fi
  if [ "$_PYR_DONE" != 1 ] && [ -n "${HOME:-}" ]; then
    _pyr_take "$HOME/.local/bin/python3.14" "~/.local/bin/python3.14" "3.14" || true
    [ "$_PYR_DONE" = 1 ] || _pyr_take "$HOME/.local/bin/python3" "~/.local/bin/python3" || true
  fi
  if [ "$_PYR_DONE" != 1 ]; then
    c="$(command -v python3.14 2>/dev/null || true)"
    case "$c" in /*) _pyr_take "$c" "PATH python3.14" "3.14" || true ;; esac
  fi
  if [ "$_PYR_DONE" != 1 ] && command -v py >/dev/null 2>&1; then
    c="$(py -3.14 -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
    if [ -n "$c" ]; then
      command -v cygpath >/dev/null 2>&1 && c="$(cygpath -u "$c" 2>/dev/null || printf '%s' "$c")"
      _pyr_take "$c" "py -3.14" "3.14" || true
    fi
  fi
  if [ "$_PYR_DONE" != 1 ]; then
    c="$(command -v python3 2>/dev/null || true)"
    case "$c" in /*) _pyr_take "$c" "PATH python3" || true ;; esac
  fi
  if [ "$_PYR_DONE" != 1 ] && [ -n "${PY_RESOLVE_EXTRA:-}" ]; then
    # shellcheck disable=SC2086
    for x in $PY_RESOLVE_EXTRA; do
      [ "$_PYR_DONE" = 1 ] || _pyr_take "$x" "$x" || true
    done
  fi
  [ -n "$_PYR_P" ]
}

py_resolve() {
  local strict=0 quiet="${PY_RESOLVE_QUIET:-0}" min="" mx my cache cp cr cv
  while [ $# -gt 0 ]; do
    case "$1" in
      --strict) strict=1 ;;
      --quiet)  quiet=1 ;;
      --min)    min="${2:-}"; shift ;;
    esac
    shift
  done
  [ -n "$min" ] || min="${_PYR_BASE_MAJ}.${_PYR_BASE_MIN}"
  _pyr_mm "$min" || min="${_PYR_BASE_MAJ}.${_PYR_BASE_MIN}"
  _pyr_mm "$min"; mx="$_PYR_X"; my="$_PYR_Y"

  # 캐시 — 같은 프로세스 트리에서 --version 을 다시 띄우지 않는다. FBOT_PYTHON 이 바뀌면 무효.
  cache="${PY_RESOLVE_CACHE:-}"
  _PYR_P=""
  if [ -n "$cache" ]; then
    cp="${cache%%|*}"; cr="${cache#*|}"; cv="${cr%%|*}"; cr="${cr#*|}"
    if [ -x "$cp" ] && [ "${PY_RESOLVE_CACHE_KEY:-}" = "${FBOT_PYTHON:-}|${PY_RESOLVE_EXTRA:-}|${HOME:-}|${PATH:-}" ] && _pyr_mm "$cv"; then
      _PYR_P="$cp"; _PYR_V="$cv"; _PYR_S="$cr"; _PYR_BX="$_PYR_X"; _PYR_BY="$_PYR_Y"
    fi
  fi
  if [ -z "$_PYR_P" ]; then
    if ! _pyr_scan; then
      printf '[py-resolve] python3 = (미발견) — 기준 %s.%s, PATH 확인 또는 FBOT_PYTHON 지정\n' "$_PYR_BASE_MAJ" "$_PYR_BASE_MIN" >&2
      return 2
    fi
    PY_RESOLVE_CACHE="${_PYR_P}|${_PYR_V}|${_PYR_S}"
    PY_RESOLVE_CACHE_KEY="${FBOT_PYTHON:-}|${PY_RESOLVE_EXTRA:-}|${HOME:-}|${PATH:-}"
    export PY_RESOLVE_CACHE PY_RESOLVE_CACHE_KEY
  fi
  PY_RESOLVE_PATH="$_PYR_P"; PY_RESOLVE_VER="$_PYR_V"; PY_RESOLVE_SRC="$_PYR_S"

  # 하한 판정
  if [ "$_PYR_BX" -lt "$_PYR_BASE_MAJ" ] || { [ "$_PYR_BX" -eq "$_PYR_BASE_MAJ" ] && [ "$_PYR_BY" -lt "$_PYR_BASE_MIN" ]; }; then
    if [ "$strict" = 1 ] && { [ "$_PYR_BX" -lt "$mx" ] || { [ "$_PYR_BX" -eq "$mx" ] && [ "$_PYR_BY" -lt "$my" ]; }; }; then
      printf '[py-resolve] ⛔ python3 = %s %s — 기준 %s.%s (최소 %s.%s), PATH 확인 또는 FBOT_PYTHON 지정\n' \
        "$_PYR_P" "$_PYR_V" "$_PYR_BASE_MAJ" "$_PYR_BASE_MIN" "$mx" "$my" >&2
      return 2
    fi
    if [ "$quiet" != 1 ] && [ "${PY_RESOLVE_WARNED:-}" != 1 ]; then
      printf '[py-resolve] ⚠️ python3 = %s %s — 기준 %s.%s 미만(비차단), PATH 확인 또는 FBOT_PYTHON 지정\n' \
        "$_PYR_P" "$_PYR_V" "$_PYR_BASE_MAJ" "$_PYR_BASE_MIN" >&2
      PY_RESOLVE_WARNED=1; export PY_RESOLVE_WARNED
    fi
  fi
  printf '%s\n' "$_PYR_P"
}
