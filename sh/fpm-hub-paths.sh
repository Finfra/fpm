#!/usr/bin/env bash
# fpm-hub-paths.sh — hub 상태 경로 해석 (Issue446 · source 전용)
#
# 왜 있는가 (jpc1 실측 2026-08-31):
#   셸과 python 이 **각자** `/tmp/___pm/claude-htm-server` 를 해석하면 Windows 에서
#   서로 다른 폴더가 된다. MSYS 셸의 `/tmp` 는 `C:\Users\…\AppData\Local\Temp` 인데
#   Windows python 은 소스에 박힌 리터럴을 현재 드라이브 루트 상대(`C:\tmp\…`)로 읽는다.
#   MSYS 가 변환해 주는 것은 argv 로 넘어가는 인자뿐이라, 소스 리터럴은 아무도 안 고쳐준다.
#   hub 는 A 폴더에 쓰고 청소·진단하는 셸 도구는 B 폴더를 봤다 — `/hub reset` 이
#   "초기화했다" 고 보고하며 엉뚱한 폴더를 지웠다. 조용히.
#
#   그래서 **셸은 계산하지 않는다.** 판정 단일 지점은 hub 의 python 이고, 여기서는
#   `server.py --print-state-dir` 로 그 값을 물어본다.
#
# 사용:
#   . "${FPM_BASE:?}/sh/fpm-hub-paths.sh"   # HUB_STATE_DIR · HUB_TMP_ROOT 설정
#   env: FPM_HUB_REPO(서버 소스 위치 강제) · FPM_TMP_ROOT(루트 강제 — server.py 가 해석)
#
# 실패 계약: 값을 못 얻으면 HUB_STATE_DIR 을 **빈 문자열**로 두고 rc=1.
#   추측값으로 채우면 그 순간 다시 갈라진다 — 호출측이 skip 하거나 보고하게 한다.

_fpm_hub_repo() {
    if [ -n "${FPM_HUB_REPO:-}" ] && [ -f "$FPM_HUB_REPO/services/hub/server.py" ]; then
        printf '%s\n' "$FPM_HUB_REPO"; return 0
    fi
    # 자기 위치 self-detect — sh/fpm.sh 와 같은 방식(zsh 는 BASH_SOURCE 가 없다).
    local here _self=""
    if [ -n "${ZSH_VERSION:-}" ]; then
        eval '_self="${(%):-%x}"'   # zsh: source 중 스크립트 경로. eval 로 bash 파싱 오류 회피
    elif [ -n "${BASH_SOURCE:-}" ]; then
        _self="${BASH_SOURCE[0]}"
    else
        _self="$0"
    fi
    here="$(cd "$(dirname "$_self")/.." 2>/dev/null && pwd)"
    if [ -n "$here" ] && [ -f "$here/services/hub/server.py" ]; then
        printf '%s\n' "$here"; return 0
    fi
    if [ -n "${FPM_BASE:-}" ] && [ -f "$FPM_BASE/services/hub/server.py" ]; then
        printf '%s\n' "$FPM_BASE"; return 0
    fi
    return 1
}

fpm_hub_paths() {
    HUB_STATE_DIR=""; HUB_TMP_ROOT=""
    local repo py
    repo="$(_fpm_hub_repo)" || {
        printf '[fpm-hub-paths] hub 소스를 찾지 못했다 (FPM_HUB_REPO 로 지정 가능)\n' >&2
        return 1
    }
    # 인터프리터 해석은 sh/fbot-python.sh 가 SSOT (Issue436) — 있으면 그걸 쓴다.
    if [ -f "$repo/sh/fbot-python.sh" ]; then
        # shellcheck source=/dev/null
        . "$repo/sh/fbot-python.sh"
        if fbot_resolve_python 2>/dev/null; then
            HUB_STATE_DIR="$("${FBOT_PY_ARGV[@]}" "$repo/services/hub/server.py" --print-state-dir 2>/dev/null || true)"
        fi
    fi
    if [ -z "$HUB_STATE_DIR" ]; then
        for py in python3 python; do
            command -v "$py" >/dev/null 2>&1 || continue
            HUB_STATE_DIR="$("$py" "$repo/services/hub/server.py" --print-state-dir 2>/dev/null || true)"
            [ -n "$HUB_STATE_DIR" ] && break
        done
    fi
    if [ -z "$HUB_STATE_DIR" ]; then
        printf '[fpm-hub-paths] 상태 경로를 얻지 못했다 — 추측하지 않는다 (python 확인 필요)\n' >&2
        return 1
    fi
    HUB_TMP_ROOT="$(dirname "$HUB_STATE_DIR")"
    export HUB_STATE_DIR HUB_TMP_ROOT
    return 0
}

fpm_hub_paths
