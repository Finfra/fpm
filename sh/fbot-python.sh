#!/usr/bin/env bash
# fbot-python.sh — python 인터프리터 해석 SSOT (Issue436)
#
# 왜 필요한가 (2026-08-31 jpc1 실측):
#   Windows 는 `python3` 라는 이름이 **"있지만 실행되지 않는"** 상태가 기본값이다.
#   PATH 의 `…/WindowsApps/python3` 는 Microsoft Store 리디렉터 스텁이라 `command -v` 는
#   통과시키고 실행하면 rc=49 로 죽는다. python.org 정식 인스톨러로 3.12 를 설치해도
#   만들어지는 것은 `python.exe`·`py.exe` 뿐 — `python3` 는 끝까지 스텁으로 남는다.
#
#   그래서 판정 기준이 **존재가 아니라 실행**이어야 하고, 후보가 하나여서는 안 된다.
#   설계 근거: _doc_arch/windows-port.md W4(python 이름)
#
# 계약 (tdd/run-tdd.sh · tdd/cases/core.yml:python3-available · python-baseline-* 와 동일)
#   후보 순서  $FBOT_PYTHON → ~/.local/bin/python3.14 → ~/.local/bin/python3 → python3.14 → py -3.14
#              → python3 → python → py -3                                           (Issue642 · Issue646)
#              앞의 두 절대경로는 prj3 hooks/lib/py-resolve.sh 와 같은 순서다(있을 때만). 다른 점은 둘뿐 —
#              여기는 요구 모듈 import 를 보고(prj3 는 안 본다), `python`·`py -3` 후보가 더 있다
#   채택 기준  실행되고, 인자로 준 모듈을 **전부** import 하는 첫 후보
#              (Issue435 원인 정정 — "실행 가능" 만으로는 부족하다. jma 의 python3 는
#               정상 실행되는데 pyyaml 이 없어 소비처가 죽었다. 요구 능력까지 봐야 한다)
#   기준(하한)  3.14 (FBOT_PY_BASELINE 로 재정의). **하한만** 본다 — 상한은 두지 않는다(3.15+ 통과).
#              상한을 두면 brew 업그레이드 한 번이 전 소비처 정지가 된다. 단일 minor 고정은 설치 정책의 몫.
#              · 이름이 minor 를 보장하는 후보(python3.14 · py -3.14)는 버전을 묻지 않는다
#              · 그렇지 않은 후보($FBOT_PYTHON · python3 · python · py -3)만 `sys.version_info` 로 확인한다
#              · 기준 이상 후보가 하나라도 있으면 그것이 채택된다 — 맨 `python3` 가 3.10 인 호스트(fg1 22.04)에서도
#                `python3.14` 가 잡힌다
#              · 전부 미달이면 **기본은 경고만**: 첫 미달 후보를 채택하되 FBOT_PY_BELOW=1 · FBOT_PY_WARN 에
#                «python3 = <경로> <버전> — 기준 3.14, PATH 확인 또는 FBOT_PYTHON 지정» 을 남긴다(rc 0).
#                정지는 opt-in — FBOT_PY_ENFORCE=1 이면 rc 2 로 정지한다(FBOT_PY_ARGV 는 비운다).
#                기본을 경고로 둔 이유: fg1(Ubuntu 22.04)은 26.04 전환 전까지 맨 `python3` 가 3.10 이라
#                정지가 기본이면 해석 경로 전체가 멈춘다.
#              · $FBOT_PYTHON 은 사용자가 못박은 값이다 — 미달이어도 다음 후보로 넘기지 않고 그대로 채택하되
#                경고(또는 ENFORCE 시 정지)한다
#   부작용 없음  후보를 고르기만 한다. 설치·수정은 하지 않는다.
#
# 사용:
#   source "$REPO_DIR/sh/fbot-python.sh"
#   if fbot_resolve_python sqlite3; then
#       "${FBOT_PY_ARGV[@]}" script.py        # ← 반드시 배열 전개. "py -3" 는 2 토큰이다
#   fi
#
# 출력 (전역)
#   FBOT_PY_ARGV[]    채택 커맨드. 배열인 이유는 `py -3` 가 한 단어가 아니기 때문이다
#   FBOT_PY_DISPLAY   사람이 읽는 1줄 표기 (로그·안내용)
#   FBOT_PY_REJECT    탈락 후보와 사유 (Issue436 ⓑ — 스텁을 잡은 사실이 출력에 보여야 한다)
#   FBOT_PY_VERSION   채택 인터프리터의 major.minor (확인하지 못했으면 빈 값)
#   FBOT_PY_PATH      채택 인터프리터의 실제 경로(`command -v` 값)
#   FBOT_PY_BELOW     1 이면 기준 미달 후보를 채택(또는 ENFORCE 로 거부)한 것
#   FBOT_PY_WARN      기준 미달 사유 1줄 (미달이 아니면 빈 값). 호출부는 이것을 warn 으로 내보낸다
#   rc                0 채택 / 1 전멸 / 2 기준 미달(FBOT_PY_ENFORCE=1 일 때만)
#
# shellcheck disable=SC2034  # FBOT_PY_* 는 source 한 쪽이 읽는 출력 변수다

# 후보 하나를 실제로 실행해 요구 모듈을 import 시켜 본다.
#   $1..  후보 토큰(들) 다음에 `--` 다음에 요구 모듈. 호출부는 fbot_resolve_python 만 쓰면 된다.
_fbot_py_probe() {
    [ -n "${ZSH_VERSION:-}" ] && emulate -L ksh   # zsh source: 배열 0부터·단어 분리를 bash 와 맞춘다 (Issue642)
    local -a cmd=() mods=()
    local seen_sep=0 a
    for a in "$@"; do
        if [[ "$a" == "--" ]]; then seen_sep=1; continue; fi
        if [[ "$seen_sep" -eq 1 ]]; then mods+=("$a"); else cmd+=("$a"); fi
    done

    # 요구 모듈이 없으면 인터프리터가 살아 있는지만 본다.
    local py_code="import sys"
    if [[ "${#mods[@]}" -gt 0 ]]; then
        local m
        for m in "${mods[@]}"; do py_code+=$'\n'"import $m"; done
    fi

    # stderr 는 버린다 — 후보 탐색 중의 실패는 정상 흐름이고, 사유는 호출부가 요약한다.
    "${cmd[@]}" -c "$py_code" >/dev/null 2>&1
}

# 후보의 major.minor 를 묻는다. 읽지 못하면 빈 값. (Windows python 은 CRLF 를 낸다 — 개행을 걷는다)
_fbot_py_version() {
    [ -n "${ZSH_VERSION:-}" ] && emulate -L ksh   # zsh source: 배열 0부터·단어 분리를 bash 와 맞춘다 (Issue642)
    local v
    v="$("$@" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || v=""
    v="${v%%$'\n'*}"; v="${v%$'\r'}"
    [[ "$v" =~ ^[0-9]+\.[0-9]+$ ]] || v=""
    printf '%s' "$v"
}

# $1 >= $2 (둘 다 major.minor). 형식이 이상하면 «판정 불가» = 통과로 본다(근거 없이 막지 않는다).
_fbot_py_ge() {
    [ -n "${ZSH_VERSION:-}" ] && emulate -L ksh   # zsh source: 배열 0부터·단어 분리를 bash 와 맞춘다 (Issue642)
    local a="$1" b="$2"
    [[ "$a" =~ ^[0-9]+\.[0-9]+$ && "$b" =~ ^[0-9]+\.[0-9]+$ ]] || return 0
    local a1="${a%%.*}" a2="${a#*.}" b1="${b%%.*}" b2="${b#*.}"
    (( a1 > b1 )) && return 0
    (( a1 < b1 )) && return 1
    (( a2 >= b2 ))
}

# fbot_resolve_python [<요구 모듈> ...]
fbot_resolve_python() {
    [ -n "${ZSH_VERSION:-}" ] && emulate -L ksh   # zsh source: 배열 0부터·단어 분리를 bash 와 맞춘다 (Issue642)
    local -a want=("$@")
    FBOT_PY_ARGV=()
    FBOT_PY_DISPLAY=""
    FBOT_PY_REJECT=""
    FBOT_PY_VERSION=""
    FBOT_PY_PATH=""
    FBOT_PY_BELOW=0
    FBOT_PY_WARN=""

    local base="${FBOT_PY_BASELINE:-3.14}"

    # 후보 = "<종류>|<커맨드>"  종류: explicit(사용자 지정) · pinned(이름이 3.14 를 보장) · check(버전 확인 필요)
    local -a cands=()
    # $FBOT_PYTHON 은 사용자가 못박은 절대경로다 — 최우선. 미설정이면 후보에서 뺀다.
    [[ -n "${FBOT_PYTHON:-}" ]] && cands+=("explicit|$FBOT_PYTHON")
    # prj3 py-resolve.sh(prj3#Issue1117)와 같은 순서 — uv 기준 설치원의 절대경로는 PATH 앞에 /usr/bin 이 끼어도 3.14 를 잡는다 (Issue646).
    # 후보 문자열은 공백으로 토큰을 편다 — HOME 에 공백이 있으면 깨지므로 그때는 뺀다(PATH 후보가 대신한다).
    if [[ -n "${HOME:-}" && "$HOME" != *[[:space:]]* ]]; then
        [[ -x "$HOME/.local/bin/python3.14" ]] && cands+=("pinned|$HOME/.local/bin/python3.14")
        [[ -x "$HOME/.local/bin/python3" ]] && cands+=("check|$HOME/.local/bin/python3")
    fi
    cands+=("pinned|python3.14" "pinned|py -3.14" "check|python3" "check|python" "check|py -3")

    local entry kind c reason ver
    local -a fb_argv=()          # 첫 기준 미달 후보 (전부 미달일 때의 채택 대상)
    local fb_display="" fb_ver=""
    for entry in "${cands[@]}"; do
        kind="${entry%%|*}"; c="${entry#*|}"
        # "py -3" 처럼 공간 분리된 후보를 토큰 배열로 편다 (의도된 단어 분리).
        # shellcheck disable=SC2206
        local -a argv=($c)
        [[ "${#argv[@]}" -eq 0 ]] && continue

        # 이름이 버전을 박은 후보는 그 실행체가 PATH 에 없으면 «없는 것» 이다 — 탈락 사유로 소음을 내지 않는다
        # (python3.14 가 없는 호스트가 대다수다. 있는데 죽는 경우만 아래 probe 가 사유를 남긴다).
        if [[ "$kind" == "pinned" ]] && ! command -v "${argv[0]}" >/dev/null 2>&1; then
            continue
        fi

        # 1) 실행 자체가 되는가 — MS Store 스텁은 여기서 떨어진다(rc=49).
        if ! _fbot_py_probe "${argv[@]}" --; then
            reason="실행 불가"
            FBOT_PY_REJECT+="${FBOT_PY_REJECT:+, }$c($reason)"
            continue
        fi
        # 2) 요구 능력을 갖췄는가 — 실행되는데 모듈이 없어 소비처가 죽는 경우를 여기서 거른다.
        if [[ "${#want[@]}" -gt 0 ]] && ! _fbot_py_probe "${argv[@]}" -- "${want[@]}"; then
            reason="$(IFS=,; printf '%s' "${want[*]}") 없음"
            FBOT_PY_REJECT+="${FBOT_PY_REJECT:+, }$c($reason)"
            continue
        fi

        # 3) 기준(하한) — 이름이 보장하지 않는 후보만 묻는다.
        if [[ "$kind" == "pinned" ]]; then
            ver="3.14"
        else
            ver="$(_fbot_py_version "${argv[@]}")"
        fi
        if [[ -n "$ver" ]] && ! _fbot_py_ge "$ver" "$base"; then
            if [[ "$kind" == "explicit" ]]; then
                # 사용자가 못박은 값은 다음 후보로 넘기지 않는다 — 그대로 채택하되 미달을 알린다.
                fb_argv=("${argv[@]}"); fb_display="$c"; fb_ver="$ver"
                break
            fi
            if [[ "${#fb_argv[@]}" -eq 0 ]]; then
                fb_argv=("${argv[@]}"); fb_display="$c"; fb_ver="$ver"
            fi
            continue
        fi

        FBOT_PY_ARGV=("${argv[@]}")
        FBOT_PY_DISPLAY="$c"
        FBOT_PY_VERSION="$ver"
        FBOT_PY_PATH="$(command -v "${argv[0]}" 2>/dev/null || printf '%s' "${argv[0]}")"
        return 0
    done

    # 기준 이상 후보가 없다 — 미달 후보가 있으면 경고(기본) 또는 정지(ENFORCE).
    if [[ "${#fb_argv[@]}" -gt 0 ]]; then
        FBOT_PY_BELOW=1
        FBOT_PY_VERSION="$fb_ver"
        FBOT_PY_PATH="$(command -v "${fb_argv[0]}" 2>/dev/null || printf '%s' "${fb_argv[0]}")"
        FBOT_PY_WARN="${fb_display} = ${FBOT_PY_PATH} ${fb_ver} — 기준 ${base}, PATH 확인 또는 FBOT_PYTHON 지정"
        if [[ "${FBOT_PY_ENFORCE:-0}" == "1" ]]; then
            return 2
        fi
        FBOT_PY_ARGV=("${fb_argv[@]}")
        FBOT_PY_DISPLAY="$fb_display"
        return 0
    fi
    return 1
}

# 이미 등록된 커맨드가 지금도 유효한지 본다 (Issue436 ⓒ).
#   설치기가 "이미 있으면 보존" 만 하면, 한 번 깨진 등록은 재설치로도 낫지 않는다.
#   실측 2종이 같은 결함의 두 발현이다:
#     · jpc1(Windows) — 인터프리터가 MS Store 스텁이라 실행되지 않는다
#     · jm4(macOS)    — 스크립트 경로가 사라졌다(repo 이전 후 등록만 남음)
#   $1 인터프리터  $2 스크립트 경로
#   rc  0 유효 / 1 무효(사유는 FBOT_PY_INVALID_REASON)
fbot_registration_valid() {
    [ -n "${ZSH_VERSION:-}" ] && emulate -L ksh   # zsh source: 배열 0부터·단어 분리를 bash 와 맞춘다 (Issue642)
    local py="$1" script="$2"
    FBOT_PY_INVALID_REASON=""

    # shellcheck disable=SC2206
    local -a argv=($py)
    if [[ "${#argv[@]}" -eq 0 ]] || ! _fbot_py_probe "${argv[@]}" --; then
        FBOT_PY_INVALID_REASON="인터프리터가 실행되지 않음($py)"
        return 1
    fi
    if [[ ! -f "$script" ]]; then
        FBOT_PY_INVALID_REASON="스크립트 부재($script)"
        return 1
    fi
    return 0
}
