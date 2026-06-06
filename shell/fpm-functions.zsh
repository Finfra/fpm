# fpm-functions.zsh — fpm 셸 함수군 (cdf 계열 + sshf 계열)
#
# 설치: install.sh 가 ~/.zshrc 또는 ~/.zsh_functions 에 본 파일 source 라인을 추가함.
#   source <repo>/shell/fpm-functions.zsh
#
# 의존:
#   - ~/.info/__pmBasePath.txt : 프로젝트 번호→경로 매핑 폴더(projects/)의 경로 (install.sh 가 생성)
#   - <repo>/Servers.md        : sshf 용 서버 목록 (install.sh 가 Servers_org.md 로부터 배치)
#   - iTerm2 (다중 분할), VS Code(`vscode` 명령), macOS `open`/`pbcopy`
#
# 비-macOS 환경에서는 cdf(단일 cd)·cdfc·sshf(단일) 는 동작, iTerm2 분할 기능은 무시됨.

# ─────────────────────────────────────────────────────────────
# cdf 계열 — 프로젝트 번호 인덱스로 디렉토리 이동
# ─────────────────────────────────────────────────────────────

# _pm_manager : 베이스 경로 관리 및 목록 출력 공용 함수
_pm_manager() {
    local config_path="$HOME/.info/__pmBasePath.txt"
    [[ -f "$config_path" ]] || { echo "Error: $config_path not found (run install.sh)"; return 1; }

    local base_dir=$(eval echo $(cat "$config_path"))

    if [[ "$1" == "list" ]]; then
        for f in "${base_dir}"/[0-9]*; do
            [[ -f "$f" ]] || continue
            printf "cdf %-4s # %s\n" "$(basename "$f")" "$(cat "$f")"
        done
        return 0
    fi
    echo "$base_dir"
}

# _cdf_base: cdf 계열 공통 로직 (인자 파싱·범위 확장·index→경로 해석)
# 결과: _CDF_TARGETS=() _CDF_CMD=""
_cdf_base() {
    _CDF_TARGETS=()
    _CDF_CMD=""
    [[ -z "$1" ]] && { _pm_manager "list"; return 1; }
    local base_dir=$(_pm_manager)

    local -a raw_indices cmd_parts
    local sep_found=0
    for arg in "$@"; do
        if [[ "$arg" == "---" ]]; then
            sep_found=1
        elif [[ $sep_found -eq 0 ]]; then
            raw_indices+=("$arg")
        else
            cmd_parts+=("$arg")
        fi
    done
    [[ $sep_found -eq 1 ]] && _CDF_CMD="${cmd_parts[*]}"

    local -a indices
    local subfolder=""
    for token in "${raw_indices[@]}"; do
        if [[ "$token" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            local from=${match[1]} to=${match[2]}
            for ((i=from; i<=to; i++)); do indices+=("$i"); done
        elif [[ "$token" =~ ^[0-9]+$ ]]; then
            indices+=("$token")
        else
            subfolder="${subfolder:+$subfolder/}$token"
        fi
    done

    if [[ ${#indices[@]} -eq 0 ]]; then
        echo "Usage: cdf[c|f|v] <index|range> [subfolder] [--- cmd]"
        echo "  ex) cdf 11          cdf 11-16        cdf 11 data"
        echo "      cdf 11 --- ls   cdfc 11-16 --- data"
        return 1
    fi

    for idx in "${indices[@]}"; do
        local file="${base_dir}/${idx}"
        if [[ ! -f "$file" ]]; then
            echo "Error: Index '$idx' not found"; continue
        fi
        local target=$(eval echo $(command cat "$file"))
        [[ -n "$subfolder" && -d "$target/$subfolder" ]] && target="$target/$subfolder"
        _CDF_TARGETS+=("$target")
    done
    return 0
}

# _cdf_apply_subfolder: 비명령 함수용 — _CDF_CMD를 서브폴더로 적용
_cdf_apply_subfolder() {
    [[ -z "$_CDF_CMD" ]] && return
    local -a new_targets
    for target in "${_CDF_TARGETS[@]}"; do
        [[ -d "$target/$_CDF_CMD" ]] && target="$target/$_CDF_CMD"
        new_targets+=("$target")
    done
    _CDF_TARGETS=("${new_targets[@]}")
    _CDF_CMD=""
}

# cdf : 터미널 디렉토리 이동 (복수 인덱스 시 iTerm2 수평 분할)
cdf() {
    if [[ ! -t 0 ]]; then
        local cmd=$(cat)
        _cdf_base "$@" || return 0
        _CDF_CMD="$cmd"
    else
        _cdf_base "$@" || return 0
    fi

    local first=1
    for target in "${_CDF_TARGETS[@]}"; do
        if [[ $first -eq 1 ]]; then
            first=0
            cd "$target"
            [[ -n "$_CDF_CMD" ]] && eval "$_CDF_CMD"
        else
            local iterm_cmd="cd '$target'"
            [[ -n "$_CDF_CMD" ]] && iterm_cmd="${iterm_cmd} && ${_CDF_CMD}"
            osascript -e "tell application \"iTerm2\" to tell current session of current window to tell (split horizontally with default profile) to write text \"${iterm_cmd}\"" 2>/dev/null
            sleep 0.1
        fi
    done
}

# cdff : Finder에서 해당 경로 열기
cdff() {
    _cdf_base "$@" || return 0
    _cdf_apply_subfolder
    for target in "${_CDF_TARGETS[@]}"; do
        open "$target"
        sleep 0.1
    done
}

# cdfc : 해당 경로를 클립보드에 복사
cdfc() {
    _cdf_base "$@" || return 0
    _cdf_apply_subfolder
    local result=""
    for target in "${_CDF_TARGETS[@]}"; do
        result+="$target"$'\n'
    done
    [[ -n "$result" ]] && { echo -n "${result%$'\n'}" | pbcopy; echo "📋 Copied to clipboard."; }
}

# cdfv : 해당 경로를 VS Code로 열기 (복수 가능)
cdfv() {
    _cdf_base "$@" || return 0
    _cdf_apply_subfolder
    for target in "${_CDF_TARGETS[@]}"; do
        if [[ -e "$target" ]]; then
            echo "🚀 Opening: $target"
            { code "$target" || vscode "$target"; } 2>/dev/null && sleep 0.1
        else
            echo "Warning: Path '$target' not found."
        fi
    done
}

# 참고: cdft (tmux pm 세션 window/pane 오케스트레이션)는 고급 기능으로 본 배포본에서 제외.
#       원본 프로젝트의 cdf 스킬(.claude/skills/cdf/) 참조.

# ─────────────────────────────────────────────────────────────
# sshf 계열 — Servers.md 의 id/name/alias 로 SSH 접속
# ─────────────────────────────────────────────────────────────

# _sshf_file : Servers.md SSOT 경로 출력
#   1순위: __pmBasePath(projects/) 의 부모 = <repo>/Servers.md
#   2순위: 현재 폴더 Servers.md
_sshf_file() {
    local base parent
    base=$(_pm_manager 2>/dev/null) && parent=$(dirname "$base")
    if [[ -n "$parent" && -f "$parent/Servers.md" ]]; then
        echo "$parent/Servers.md"
    elif [[ -f "$(pwd)/Servers.md" ]]; then
        echo "$(pwd)/Servers.md"
    else
        return 1
    fi
}

# _sshf_resolve <key> : id/name/alias → ssh config Host alias(Name) 출력
_sshf_resolve() {
    local key=$1 servers_file
    servers_file=$(_sshf_file) || return 1
    grep "^|" "$servers_file" | grep -v ":---" | tail -n +2 | awk -F'|' -v k="$key" '
        function trim(s){ gsub(/^[ \t]+|[ \t]+$/,"",s); return s }
        {
            id=trim($2); name=trim($3); alias=trim($4);
            if (id==k || name==k) { print name; exit }
            n=split(alias, a, /[ \t]*,[ \t]*/);
            for (i=1;i<=n;i++) if (a[i]==k) { print name; exit }
        }'
}

# sshf : Servers.md 의 id/name/alias 로 SSH 접속 (cdf 는 폴더, sshf 는 서버 기준)
#   sshf                    : 서버 목록
#   sshf <key>              : 단일 접속
#   sshf <key> <cmd...>     : 단일 서버 명령 실행
#   sshf <key1> <key2> ...  : 다중 서버 → iTerm2 수평 분할
sshf() {
    local servers_file
    servers_file=$(_sshf_file) || {
        echo "Error: Servers.md not found (expected <repo>/Servers.md — run install.sh)"
        return 1
    }

    if [[ -z "$1" ]]; then
        echo "Usage: sshf <id|name|alias> [cmd...]   |   sshf <key1> <key2> ... (다중 분할)"
        echo ""
        echo "Servers (from $servers_file):"
        grep "^|" "$servers_file" | grep -v ":---" | tail -n +2 | sed 's/^/  /'
        return 1
    fi

    if [[ $# -ge 2 ]]; then
        local -a names
        local all_keys=1 arg resolved
        for arg in "$@"; do
            resolved=$(_sshf_resolve "$arg")
            if [[ -z "$resolved" ]]; then all_keys=0; break; fi
            names+=("$resolved")
        done

        if [[ $all_keys -eq 1 ]]; then
            local i n
            for (( i=${#names[@]}; i>=2; i-- )); do
                n="${names[$i]}"
                osascript -e "tell application \"iTerm2\" to tell current session of current window to tell (split horizontally with default profile) to write text \"ssh ${n}\"" 2>/dev/null
                sleep 0.1
            done
            ssh "${names[1]}"
            return 0
        fi
    fi

    local key=$1; shift
    local cmd="$@"
    local name
    name=$(_sshf_resolve "$key")
    if [[ -z "$name" ]]; then
        echo "Error: Server '$key' not found in $servers_file"
        return 1
    fi

    if [[ -n "$cmd" ]]; then
        ssh "$name" $cmd
    else
        ssh "$name"
    fi
}
