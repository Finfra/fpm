# shellcheck shell=bash
# sh/fpm_function.sh — finfra pm 네비게이션 함수 (cdf 계열 + sshf 계열)
#
# fpm.sh 부트스트랩이 FPM_BASE export 후 본 파일을 source.
# 모든 경로는 $FPM_BASE 기반 → 설치 위치 무관(~/_git/___pm, ~/_git/__all/fpm 등) 동작.
# zsh / bash 양쪽 호환 (regex 매치·배열 인덱스·word-split 을 셸 분기로 처리).
#   예외 chpwd : zsh 전용 디렉토리 훅 — bash 에선 자동 호출 안 됨(함수 정의만 존재).
# alias 는 sh/fpm_aliases.sh 로 분리됨.
#
# === TOC ===
# --- CDF (인덱스 기반 디렉토리 이동, $FPM_BASE/projects 기반) ---
#   _pm_manager / _cdf_base / _cdf_apply_subfolder : 공용 내부 헬퍼
#   cdf   : 인덱스 폴더로 cd (cdf 1 2 / cdf 11-16 / cdf 1 --- cmd / cdf 1 <<EOF)
#   cdff  : Finder 에서 열기 / cdfc : 경로 클립보드 복사 / cdfv : VS Code 로 열기
#   cdft  : tmux pm 세션 window/pane 관리
# --- SSH by Server ID ($FPM_BASE/Servers.md SSOT) ---
#   _sshf_file / _sshf_resolve : 공용 내부 헬퍼
#   sshf  : Servers.md id/name/alias 로 SSH 접속 (다중 키 → iTerm2 분할)
# ===========

# --- 셸 호환 헬퍼 (zsh / bash 양쪽 지원) ---
# _fpm_rematch <string> <regex> : [[ =~ ]] 매치 후 캡처 그룹을 $_M1 $_M2 로 노출.
#   zsh 는 $match[n], bash 는 $BASH_REMATCH[n] 로 매치 결과 위치가 달라 통합 래핑.
#   반환 0=매치 성공, 1=실패. 최대 2 그룹 (cdf 범위·인덱스 파싱에 충분).
_fpm_rematch() {
    _M1=""; _M2=""
    if [ -n "${ZSH_VERSION:-}" ]; then
        [[ "$1" =~ $2 ]] || return 1
        _M1="${match[1]}"; _M2="${match[2]}"
    else
        [[ "$1" =~ $2 ]] || return 1
        _M1="${BASH_REMATCH[1]}"; _M2="${BASH_REMATCH[2]}"
    fi
    return 0
}

# --- CDF (인덱스 기반 디렉토리 이동) ---
# _pm_manager : 베이스 경로 관리 및 목록 출력 공용 함수
#   base = $FPM_BASE/projects (env 우선). FPM_BASE 미설정 시 legacy ~/.info/__pmBasePath.txt fallback.
_pm_manager() {
    local base_dir
    if [[ -n "${FPM_BASE:-}" && -d "${FPM_BASE}/projects" ]]; then
        base_dir="${FPM_BASE}/projects"
    else
        local config_path="$HOME/.info/__pmBasePath.txt"
        [[ -f "$config_path" ]] || { echo "Error: FPM_BASE unset and $config_path not found"; return 1; }
        base_dir=$(eval echo $(cat "$config_path"))
    fi

    # 인자가 "list"인 경우 목록을 출력하고 종료
    if [[ "$1" == "list" ]]; then
        for f in "${base_dir}"/[0-9]*; do
            [[ -f "$f" ]] || continue
            printf "cdf %-4s # %s\n" "$(basename "$f")" "$(cat "$f")"
        done
        return 0
    fi
    echo "$base_dir"
}

# cdf : 터미널 내 디렉토리 이동
# 사용법:
#   cdf 1 2 3              : 각 인덱스 폴더로 이동
#   cdf 1 2 3 --- ls       : 각 인덱스 폴더로 이동 후 명령 실행
#   cdf 1 2 <<EOF          : heredoc으로 멀티라인 명령 실행
#     ls -as
#   EOF
# _cdf_base: cdf 계열 공통 로직
# 기능: 빈 인자 처리, --- 구분자 파싱, 범위 확장(11-16), 비숫자→서브폴더, index→경로 해석
# 결과: _CDF_TARGETS=() _CDF_CMD=""
#   - 비숫자 토큰 → 서브폴더로 경로에 반영 (디렉토리 존재 시)
#   - --- 뒤 → _CDF_CMD (호출측이 명령/서브폴더 결정)
# 반환: 0=성공, 1=list 출력(호출측 return 필요)
_cdf_base() {
    _CDF_TARGETS=()
    _CDF_CMD=""
    [[ -z "$1" ]] && { _pm_manager "list"; return 1; }
    local base_dir=$(_pm_manager)

    # --- 구분자 파싱: 앞은 인덱스+서브폴더, 뒤는 _CDF_CMD
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

    # 범위 확장 + 비숫자 토큰은 서브폴더로 분리
    local -a indices
    local subfolder=""
    for token in "${raw_indices[@]}"; do
        if _fpm_rematch "$token" '^([0-9]+)-([0-9]+)$'; then
            local from=$_M1 to=$_M2
            for ((i=from; i<=to; i++)); do indices+=("$i"); done
            elif [[ "$token" =~ ^[0-9]+$ ]]; then
            indices+=("$token")
        else
            subfolder="${subfolder:+$subfolder/}$token"
        fi
    done

    # 인덱스 없으면 usage 출력
    if [[ ${#indices[@]} -eq 0 ]]; then
        echo "Usage: cdf[c|f|v|t] <index|range> [subfolder] [--- cmd]"
        echo "  ex) cdf 11          cdf 11-16        cdf 11 data"
        echo "      cdf 11 --- ls   cdfc 11-16 --- data"
        return 1
    fi

    # index → target 해석 + 서브폴더 적용
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

cdf() {
    # heredoc(stdin) 우선
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
            osascript -e "tell application \"iTerm2\" to tell current session of current window to tell (split horizontally with default profile) to write text \"${iterm_cmd}\""
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

# cdfv : 해당 경로를 VS Code로 열기
cdfv() {
    _cdf_base "$@" || return 0
    _cdf_apply_subfolder
    for target in "${_CDF_TARGETS[@]}"; do
        if [[ -e "$target" ]]; then
            echo "🚀 Opening: $target"
            vscode "$target" && sleep 0.1
        else
            echo "Warning: Path '$target' not found."
        fi
    done
}

# cdft : tmux pm 세션의 window/pane 생성·관리
# 사용법:
#   cdft list                     : pm 세션 윈도우 목록
#   cdft 11 12 13                 : pane 생성 (프로젝트 인덱스)
#   cdft 11 12 :fapp              : pane 생성 + 윈도우 이름 지정
#   cdft 11 12 @3                 : pane 생성 + 윈도우 인덱스 지정
#   cdft :fapp --- ls             : 기존 pane에 CMD 전달
#   cdft --- ls                   : 활성 윈도우에 CMD 전달
#   cdft kill :fapp               : 윈도우 삭제
#   cdft kill @2                  : 윈도우 인덱스로 삭제
#   cdft capture :fapp            : pane 출력 수집 (기본 50줄)
#   cdft capture :fapp 30         : pane 출력 수집 (30줄)
cdft() {
    local TMUX_CMD=/opt/homebrew/bin/tmux
    local base_dir=$(_pm_manager)
    [[ $? -ne 0 ]] && return 1

    # --- 인자 파싱 ---
    local TARGET_WIN="" WIN_NUM="" WIN_CREATE_IDX=""
    local CAPTURE_MODE=0 CAPTURE_N=50
    local -a PANES KILL_ARGS
    local CMD="" MODE=""
    local args_w="$*"

    # 특수 키워드: list
    [[ -z "$1" || "$1" == "list" ]] && {
        $TMUX_CMD list-windows -t pm -F '#I:#W (#F)' 2>/dev/null || { echo "pm 세션 없음"; return 1; }
        echo "---"
        for win in $($TMUX_CMD list-windows -t pm -F '#W' 2>/dev/null); do
            echo "=== $win ==="
            $TMUX_CMD list-panes -t "pm:$win" -F '  pane #P: #{pane_current_path}' 2>/dev/null
        done
        return 0
    }

    # 특수 키워드: kill
    if [[ "$1" == "kill" ]]; then
        shift
        for target in "$@"; do
            # :NAME → NAME, @N → N
            target="${target#:}"
            target="${target#@}"
            local win_count=$($TMUX_CMD list-windows -t pm 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
            if [[ "$win_count" -le 1 ]]; then
                $TMUX_CMD kill-session -t pm 2>/dev/null && echo "pm 세션 전체 삭제됨"
                return 0
            fi
            $TMUX_CMD kill-window -t "pm:$target" 2>/dev/null && echo "pm:$target 삭제됨"
        done
        return 0
    fi

    # 특수 키워드: capture
    if [[ "$1" == "capture" ]]; then
        shift
        # :NAME 추출
        for arg in "$@"; do
            if [[ "$arg" =~ ^:[A-Za-z] ]]; then
                TARGET_WIN="${arg#:}"
                elif [[ "$arg" =~ ^@[0-9] ]]; then
                TARGET_WIN=$($TMUX_CMD display-message -t "pm:${arg#@}" -p '#W' 2>/dev/null)
                elif [[ "$arg" =~ ^[0-9]+$ ]]; then
                CAPTURE_N="$arg"
            fi
        done
        [[ -z "$TARGET_WIN" ]] && TARGET_WIN=$($TMUX_CMD display-message -t pm -p '#W' 2>/dev/null)
        local pane_count=$($TMUX_CMD list-panes -t "pm:$TARGET_WIN" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
        [[ "$pane_count" -eq 0 ]] && { echo "오류: pm:$TARGET_WIN 에 pane이 없음"; return 1; }
        echo "=== pm:$TARGET_WIN capture (last ${CAPTURE_N} lines) ==="
        for ((i=0; i<pane_count; i++)); do
            local target="pm:$TARGET_WIN.$i"
            local pane_dir=$($TMUX_CMD display-message -t "$target" -p '#{pane_current_path}' 2>/dev/null)
            echo ""
            echo "--- pane $i [${pane_dir##*/}] ---"
            $TMUX_CMD capture-pane -t "$target" -p -l "$CAPTURE_N" 2>/dev/null
        done
        echo ""
        echo "=== 완료: ${pane_count}개 pane ==="
        return 0
    fi

    # --- 일반 파싱: @N, :NAME, ---, 숫자 ---

    # @N 윈도우 인덱스 추출
    local -a filtered_args
    for arg in "$@"; do
        if _fpm_rematch "$arg" '^@([0-9]+)$'; then
            WIN_NUM="$_M1"
            TARGET_WIN=$($TMUX_CMD display-message -t "pm:$WIN_NUM" -p '#W' 2>/dev/null)
            [[ -z "$TARGET_WIN" ]] && TARGET_WIN="win-$WIN_NUM" && WIN_CREATE_IDX="$WIN_NUM"
        else
            filtered_args+=("$arg")
        fi
    done

    # :NAME 윈도우 이름 추출
    local -a filtered_args2
    for arg in "${filtered_args[@]}"; do
        if _fpm_rematch "$arg" '^:([A-Za-z][A-Za-z0-9_-]*)$'; then
            TARGET_WIN="$_M1"
        else
            filtered_args2+=("$arg")
        fi
    done

    # --- 구분자 분리
    local sep_found=0
    local -a before_args cmd_parts
    for arg in "${filtered_args2[@]}"; do
        if [[ "$arg" == "---" ]]; then
            sep_found=1
            elif [[ $sep_found -eq 0 ]]; then
            before_args+=("$arg")
        else
            cmd_parts+=("$arg")
        fi
    done
    [[ $sep_found -eq 1 ]] && CMD="${cmd_parts[*]}"

    # 숫자 토큰 → PANES (범위 확장: 11-16 → 11 12 13 14 15 16)
    for token in "${before_args[@]}"; do
        if _fpm_rematch "$token" '^([0-9]+)-([0-9]+)$'; then
            local from=$_M1 to=$_M2
            for ((i=from; i<=to; i++)); do PANES+=("$i"); done
            elif [[ "$token" =~ ^[0-9]+$ ]]; then
            PANES+=("$token")
        fi
    done

    # 모드 결정
    if [[ ${#PANES[@]} -gt 0 ]]; then
        MODE="setup"
        elif [[ -n "$CMD" ]]; then
        MODE="send"
        [[ -z "$TARGET_WIN" ]] && TARGET_WIN=$($TMUX_CMD display-message -t pm -p '#W' 2>/dev/null)
    else
        echo "오류: 프로젝트 번호 또는 명령을 지정해주세요"
        return 1
    fi

    # --- send 모드 ---
    if [[ "$MODE" == "send" ]]; then
        local pane_count=$($TMUX_CMD list-panes -t "pm:$TARGET_WIN" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
        [[ "$pane_count" -eq 0 ]] && { echo "오류: pm:$TARGET_WIN 에 pane이 없음"; return 1; }
        # CMD가 디렉토리명이면 cd 명령으로 변환
        local send_cmd="$CMD"
        local pane0_dir=$($TMUX_CMD display-message -t "pm:$TARGET_WIN.0" -p '#{pane_current_path}' 2>/dev/null)
        [[ -n "$pane0_dir" && -d "$pane0_dir/$CMD" ]] && send_cmd="cd $CMD"
        local sync=$($TMUX_CMD show-window-options -t "pm:$TARGET_WIN" synchronize-panes 2>/dev/null | /usr/bin/grep -c "on")
        if [[ "$sync" -gt 0 ]]; then
            $TMUX_CMD send-keys -t "pm:$TARGET_WIN.0" "$send_cmd" Enter
            echo "pm:$TARGET_WIN [sync] pane 0에만 전달: $send_cmd"
        else
            for ((i=0; i<pane_count; i++)); do
                local pdir=$($TMUX_CMD display-message -t "pm:$TARGET_WIN.$i" -p '#{pane_current_path}' 2>/dev/null)
                local pcmd="$CMD"
                [[ -n "$pdir" && -d "$pdir/$CMD" ]] && pcmd="cd $CMD"
                $TMUX_CMD send-keys -t "pm:$TARGET_WIN.$i" "$pcmd" Enter
                /bin/sleep 0.1
            done
            echo "pm:$TARGET_WIN 의 ${pane_count}개 pane에 전달: $CMD"
        fi
        return 0
    fi

    # --- setup 모드 ---
    local PREFIX="${TARGET_WIN:-pm}"
    local pane_count=${#PANES[@]}

    # 경로 해석 (--- 뒤가 디렉토리면 서브폴더로 이동)
    local -a PROJ_PATHS PROJ_APPS
    local idx=1
    for num in "${PANES[@]}"; do
        local content=$(/bin/cat "${base_dir}/${num}" 2>/dev/null)
        local proj_path=$(echo "$content" | /usr/bin/sed "s|~|$HOME|g")
        if [[ -n "$CMD" && -d "$proj_path/$CMD" ]]; then
            proj_path="$proj_path/$CMD"
        fi
        PROJ_PATHS[$idx]="$proj_path"
        PROJ_APPS[$idx]="${proj_path##*/}"
        idx=$((idx+1))
    done

    # column-major PANE_MAP 계산
    local cols=2
    local rows=$(( (pane_count + cols - 1) / cols ))
    local -a PANE_MAP
    for ((i=1; i<=pane_count; i++)); do
        local col=$(( (i-1) / rows ))
        local row=$(( (i-1) % rows ))
        PANE_MAP[$i]=$(( row * cols + col ))
    done

    # pm 세션 확인/생성
    $TMUX_CMD has-session -t pm 2>/dev/null || $TMUX_CMD new-session -d -s pm -n "${PREFIX}1"

    # pane 매칭 — 기존 pane에서 프로젝트 경로 탐색
    local -a FOUND_TARGETS
    local FOUND_COUNT=0
    for ((i=1; i<=pane_count; i++)); do
        FOUND_TARGETS[$i]=""
    done

    local ACTIVE_WIN=$($TMUX_CMD display-message -t pm -p '#W' 2>/dev/null)
    local WIN_ORDER="$ACTIVE_WIN"
    for win in $($TMUX_CMD list-windows -t pm -F '#W' 2>/dev/null); do
        [[ "$win" != "$ACTIVE_WIN" ]] && WIN_ORDER="$WIN_ORDER $win"
    done

    # WIN_ORDER 공백구분 → 배열. zsh 는 unquoted 변수 word-split 미수행($= flag 필요),
    # bash 는 unquoted 시 IFS split. eval 로 zsh 전용 ${=..} 구문을 bash 파싱서 격리.
    local -a _win_list
    if [ -n "${ZSH_VERSION:-}" ]; then
        eval '_win_list=(${=WIN_ORDER})'
    else
        _win_list=($WIN_ORDER)
    fi
    for win in "${_win_list[@]}"; do
        for pane_info in $($TMUX_CMD list-panes -t "pm:$win" -F '#P:#{pane_current_path}' 2>/dev/null); do
            local pane_idx=${pane_info%%:*}
            local pane_dir=${pane_info#*:}
            for ((i=1; i<=pane_count; i++)); do
                if [[ -z "${FOUND_TARGETS[$i]}" && "$pane_dir" == "${PROJ_PATHS[$i]}" ]]; then
                    FOUND_TARGETS[$i]="pm:$win.$pane_idx"
                    FOUND_COUNT=$((FOUND_COUNT + 1))
                    break
                fi
            done
        done
    done

    echo "매칭: $FOUND_COUNT / $pane_count"

    if [[ "$FOUND_COUNT" -eq "$pane_count" ]]; then
        # 재사용
        echo "기존 pane 재사용:"
        for ((i=1; i<=pane_count; i++)); do
            echo "  ${FOUND_TARGETS[$i]} → ${PROJ_PATHS[$i]}"
        done
        local REUSE_WIN=$(echo "${FOUND_TARGETS[1]}" | /usr/bin/sed 's/pm://;s/\..*//')
        /usr/bin/say "session ready"
        echo "WIN_NAME=$REUSE_WIN"
    else
        # 신규 윈도우 생성
        local MAX_NUM=0
        for existing in $($TMUX_CMD list-windows -t pm -F '#W' 2>/dev/null | /usr/bin/grep "^${PREFIX}[0-9]*$"); do
            local num=${existing#$PREFIX}
            [[ -n "$num" && "$num" -gt "$MAX_NUM" ]] && MAX_NUM=$num
        done
        local WIN_NAME="${PREFIX}$((MAX_NUM + 1))"
        echo "새 window: $WIN_NAME"

        if [[ -n "$WIN_CREATE_IDX" ]]; then
            $TMUX_CMD new-window -a -t "pm:$WIN_CREATE_IDX" -n "$WIN_NAME" 2>/dev/null || \
            $TMUX_CMD new-window -a -t pm -n "$WIN_NAME" 2>/dev/null
        else
            $TMUX_CMD new-window -a -t pm -n "$WIN_NAME" 2>/dev/null
        fi

        # pane 생성
        for ((i=1; i<pane_count; i++)); do
            $TMUX_CMD split-window -t "pm:$WIN_NAME"
            $TMUX_CMD select-layout -t "pm:$WIN_NAME" tiled
        done

        # column-major cd 배정
        for ((i=1; i<=pane_count; i++)); do
            $TMUX_CMD send-keys -t "pm:$WIN_NAME.${PANE_MAP[$i]}" "cd '${PROJ_PATHS[$i]}'" Enter
            /bin/sleep 0.1
        done

        /bin/sleep 1
        $TMUX_CMD list-panes -t "pm:$WIN_NAME" -F '  pane #P: #{pane_current_path}'
        /usr/bin/say "session ready"
        echo "WIN_NAME=$WIN_NAME"
    fi
}

# --- CDF end ---

# _sshf_file : Servers.md SSOT 경로 출력 ($FPM_BASE 우선, 없으면 현재 폴더)
_sshf_file() {
    if [[ -n "${FPM_BASE:-}" && -f "$FPM_BASE/Servers.md" ]]; then
        echo "$FPM_BASE/Servers.md"
    elif [[ -f "$(pwd)/Servers.md" ]]; then
        echo "$(pwd)/Servers.md"
    else
        return 1
    fi
}

# _sshf_resolve <key> : id/name/alias → ssh config Host alias(Name, f3) 출력. 미발견 시 빈 문자열
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

# --- SSH by Server ID ---
# sshf : Servers.md의 id/name/alias 로 SSH 접속. cdf는 폴더 기준, sshf는 서버 기준.
#   SSOT: $FPM_BASE/Servers.md (없으면 $(pwd)/Servers.md fallback)
#   테이블 컬럼: | id | Name | ssh alias | Host | Port | User | Description |
#   Name = ~/.ssh/config 의 Host alias → ssh <Name> 으로 접속 (IdentityFile 등 config 옵션 적용)
#   Usage:
#     sshf                    : 서버 목록
#     sshf <key>              : 단일 서버 접속
#     sshf <key> <cmd...>     : 단일 서버에서 명령 실행
#     sshf <key1> <key2> ...  : 다중 서버 → iTerm2 수평 분할 (cdf 1 2 패턴)
sshf() {
    local servers_file
    servers_file=$(_sshf_file) || {
        echo "Error: Servers.md not found (expected \$FPM_BASE/Servers.md)"
        return 1
    }

    # 인자 없으면 서버 목록 출력
    if [[ -z "$1" ]]; then
        echo "Usage: sshf <id|name|alias> [cmd...]   |   sshf <key1> <key2> ... (다중 분할)"
        echo ""
        echo "Servers (from $servers_file):"
        grep "^|" "$servers_file" | grep -v ":---" | tail -n +2 | sed 's/^/  /'
        return 1
    fi

    # 다중 서버 판정: 인자 2개 이상이고 모든 인자가 유효 키 → iTerm2 분할
    if [[ $# -ge 2 ]]; then
        local -a names
        local all_keys=1 arg resolved
        for arg in "$@"; do
            resolved=$(_sshf_resolve "$arg")
            if [[ -z "$resolved" ]]; then all_keys=0; break; fi
            names+=("$resolved")
        done

        if [[ $all_keys -eq 1 ]]; then
            # ssh는 블로킹 → 분할(2~n번) 먼저 실행, 현재창 ssh(1번)는 마지막.
            # (cdf는 cd가 즉시 끝나 순서 무관하나 ssh는 세션 점유)
            # 분할은 항상 원래 pane(현재 셸) 바로 아래에 삽입됨 → 역순(n→2)으로
            # 분할해야 위→아래 정순(2,3,...,n) 배치됨.
            # zsh 배열 1-base / bash 0-base → lo(첫)·hi(끝) 인덱스로 통합.
            local i n lo=0
            [ -n "${ZSH_VERSION:-}" ] && lo=1
            local hi=$(( lo + ${#names[@]} - 1 ))
            for (( i=hi; i>lo; i-- )); do
                n="${names[$i]}"
                osascript -e "tell application \"iTerm2\" to tell current session of current window to tell (split horizontally with default profile) to write text \"ssh ${n}\""
                sleep 0.1
            done
            # 첫 서버: 현재 창 (마지막, 블로킹 OK)
            ssh "${names[$lo]}"
            return 0
        fi
    fi

    # 단일 서버 (+ 선택적 cmd)
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

# --- fpm-projects-sync : Projects.md(SSOT) → projects/ + .vscode + iterm-bg 일괄 반영 ---
# 수동 단일 명령. Projects.md 편집 후 실행.
fpm-projects-sync() {
    python3 "${FPM_BASE}/sh/fpm-projects-sync" "$@"
}

# --- iTerm2 배경색 (Projects.md color / peacock 연동) ---
# (이전 위치 ~/.zsh_functions → 2026-06-09 fpm 으로 이관. fpm 색상 기능 일체화)
# iterm-bg : iTerm2 배경색 변경. 인자 없으면 기본값 복원. iterm-bg-N alias(생성물)·chpwd 의 베이스.
iterm-bg() {
    if [[ -z "$1" ]]; then
        printf '\033]111;\007' > /dev/tty
    else
        printf '\033]1337;SetColors=bg=%s\007' "$1" > /dev/tty
    fi
}

# chpwd : 디렉토리 이동 시 .vscode/settings.json 의 peacock.color 를 iTerm2 배경색으로 적용
#   - peacock.color 없으면 기본값 복원. (zsh 훅 — bash 에선 미사용 함수로만 존재)
chpwd() {
    local settings="$PWD/.vscode/settings.json"
    if [[ -f "$settings" ]]; then
        local hex
        hex=$(grep -o '"peacock\.color"\s*:\s*"#[0-9a-fA-F]\{6\}"' "$settings" \
            | grep -o '#[0-9a-fA-F]\{6\}' \
        | head -1)
        [[ -n "$hex" ]] && { iterm-bg "${hex#\#}"; return; }
    fi
    iterm-bg  # 인자 없으면 기본값 복원
}

# --- Server Management ($FPM_BASE/Servers.md SSOT) ---
# server-check : SSH favorite 서버 상태 확인. sshf 와 동일 Servers.md SSOT(_sshf_file).
#   (이전 위치 ~/.zsh_functions, $HOME/Servers.md(미존재) → 2026-06-09 fpm 이관 + 경로 수정)
#   Usage: server-check [servers...]   ex) server-check / server-check jma jm4
server-check() {
    local servers=("${@:-jma jm1 jm2 jm4 fg1}")
    local servers_file
    servers_file=$(_sshf_file) || {
        echo "Error: Servers.md not found (expected \$FPM_BASE/Servers.md)"
        return 1
    }

    echo "=== Server Status Check ==="
    echo

    # 인자 없으면 기본 목록
    if (( $# == 0 )); then
        servers=(jma jm1 jm2 jm4 fg1)
    fi

    for srv in "${servers[@]}"; do
        result=$(timeout 3 ssh -o ConnectTimeout=2 -o LogLevel=ERROR "$srv" hostname 2>/dev/null)
        if [[ -n "$result" ]]; then
            printf "%-8s ✅ %s\n" "$srv:" "$result"
        else
            printf "%-8s ❌ DOWN\n" "$srv:"
        fi
    done

    echo
    echo "Source: $servers_file"
}

# --- hub 브라우저 열기 ($FPM_BASE/plugins/fpm-core/hooks/fpm-browser-open.sh) ---
# fhub : 터미널(iTerm 등)에서 hub 대시보드를 브라우저 탭 1개 재사용하며 열기 (Issue162).
#   Keyboard Maestro 매크로 "fPm hub page Open" 의 CLI 버전.
#   default_browser(hub_setting.yml)를 따르되 firefox(탭 재사용 불가)면 chrome 으로 강제.
#   match=origin(:9876) → /hub·?path=… 모든 hub URL 을 단일 탭으로 재사용.
#   Usage: fhub [url]   ex) fhub  /  fhub http://127.0.0.1:9876/hub
fhub() {
    local url="${1:-http://127.0.0.1:9876/hub}"
    local helper="$FPM_BASE/plugins/fpm-core/hooks/fpm-browser-open.sh"
    [[ -f "$helper" ]] || { echo "fhub: helper 없음 ($helper)" >&2; return 1; }
    local db
    db=$(grep -E '^[[:space:]]*default_browser:' "$FPM_BASE/data/hub_setting.yml" 2>/dev/null \
         | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
    case "$db" in
        chrome|Chrome|safari|Safari|edge|Edge) ;;   # 탭 재사용 가능 → 그대로
        *) db=chrome ;;                              # firefox/미설정 → chrome 강제
    esac
    bash "$helper" -a "$db" -f true -r true -m "http://127.0.0.1:9876" "$url"
}
