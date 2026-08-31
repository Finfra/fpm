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
#   설계 근거: _doc_arch/windows-port-design.md W4(python 이름)
#
# 계약 (tdd/run-tdd.sh · tdd/cases/core.yml:python3-available 과 동일)
#   후보 순서  $FBOT_PYTHON → python3 → python → py -3
#   채택 기준  실행되고, 인자로 준 모듈을 **전부** import 하는 첫 후보
#              (Issue435 원인 정정 — "실행 가능" 만으로는 부족하다. jma 의 python3 는
#               정상 실행되는데 pyyaml 이 없어 소비처가 죽었다. 요구 능력까지 봐야 한다)
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
#   rc                0 채택 / 1 전멸
#
# shellcheck disable=SC2034  # FBOT_PY_* 는 source 한 쪽이 읽는 출력 변수다

# 후보 하나를 실제로 실행해 요구 모듈을 import 시켜 본다.
#   $1..  후보 토큰(들) 다음에 `--` 다음에 요구 모듈. 호출부는 fbot_resolve_python 만 쓰면 된다.
_fbot_py_probe() {
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

# fbot_resolve_python [<요구 모듈> ...]
fbot_resolve_python() {
    local -a want=("$@")
    FBOT_PY_ARGV=()
    FBOT_PY_DISPLAY=""
    FBOT_PY_REJECT=""

    local -a cands=()
    # $FBOT_PYTHON 은 사용자가 못박은 절대경로다 — 최우선. 미설정이면 후보에서 뺀다.
    [[ -n "${FBOT_PYTHON:-}" ]] && cands+=("$FBOT_PYTHON")
    cands+=("python3" "python" "py -3")

    local c reason
    for c in "${cands[@]}"; do
        # "py -3" 처럼 공간 분리된 후보를 토큰 배열로 편다 (의도된 단어 분리).
        # shellcheck disable=SC2206
        local -a argv=($c)
        [[ "${#argv[@]}" -eq 0 ]] && continue

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

        FBOT_PY_ARGV=("${argv[@]}")
        FBOT_PY_DISPLAY="$c"
        return 0
    done
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
