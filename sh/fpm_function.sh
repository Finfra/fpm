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
#   cdfn/cdfvn : 번호 대신 "문자(이름)" 부분일치 (cdf/cdfv 의 이름검색 변형, _cdfn_resolve 공용)
#                1개 즉시·다수 choose from list 선택창 — Projects.md 의 프로젝트명·한글명·경로 매칭
#   cdf-num : cdf 역방향 — 경로($PWD 기본) → 등록 프로젝트 번호 (최장 prefix 일치)
#   cdf-rel/cdfr  : 경로(파일 가능) → 프로젝트 루트 기준 상대 경로
#   cdf-base/cdfb : 경로(파일 가능) → 프로젝트 루트 절대 경로 (-n 으로 prj 번호 병기)
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

# --- 플랫폼 헬퍼 (macOS 전용 기능의 Linux fail-loud 처리) ---
# 배경: cdf 다중 인덱스·cdff·cdfc·cdfn 선택창은 osascript/open/pbcopy 에 의존.
#   Linux(fg1 등)에서는 `osascript: command not found` 만 뜨고 무엇이 왜 안 되는지
#   알 수 없었음 → 아래 헬퍼로 "macOS 전용" 을 명시하고 가능한 대체 경로를 안내.
_fpm_os() { uname -s 2>/dev/null || echo unknown; }
_fpm_is_macos() { [ "$(_fpm_os)" = "Darwin" ]; }

# _fpm_need_macos <기능명> [대안안내] : macOS 면 0, 아니면 메시지 출력 후 1
_fpm_need_macos() {
    _fpm_is_macos && return 0
    echo "⛔ ${1:-이 기능} : macOS 전용 (현재 OS=$(_fpm_os))" >&2
    [ -n "$2" ] && echo "   → $2" >&2
    return 1
}

# _fpm_tmux_bin : tmux 실행 경로 (PATH 우선, Homebrew fallback). 없으면 빈 문자열
_fpm_tmux_bin() {
    local t
    t=$(command -v tmux 2>/dev/null) && { printf '%s' "$t"; return 0; }
    [ -x /opt/homebrew/bin/tmux ] && { printf '%s' /opt/homebrew/bin/tmux; return 0; }
    return 1
}

# _fpm_say <메시지> : 음성 알림. hook-say.sh 우선 → say(macOS) → 없으면 생략 고지
#   `say` 는 macOS 내장 TTS. Linux 에는 없어 `/usr/bin/say: no such file or directory`
#   로 깨졌음 → 존재 확인 후 실행하고, 없으면 왜 생략됐는지 1줄 표시(무음 실패 금지).
_fpm_say() {
    local msg="${1:-session ready}"
    if [ -x "$HOME/.claude/hooks/hook-say.sh" ]; then
        "$HOME/.claude/hooks/hook-say.sh" session_ready "$msg"
        return 0
    fi
    if command -v say >/dev/null 2>&1; then
        say "$msg"
        return 0
    fi
    echo "🔇 음성 알림 생략: \`say\` 는 macOS 전용 (현재 OS=$(_fpm_os)) — \"${msg}\"" >&2
    return 0
}

# _fpm_tmux_focus <tmux경로> <window명> : 만든/찾은 window 로 실제 이동
#   tmux 안  → select-window (현재 client 를 그 window 로 전환)
#   tmux 밖  → attach-session (블로킹 — 사용자가 그 화면으로 들어감)
#   ⚠️ stdout 이 tty 가 아니면(=명령치환·파이프·pm-do 의 WIN_NAME 파싱) attach 하지 않는다.
#      attach 는 터미널을 점유하므로 스크립트 문맥에서 실행되면 그대로 멈춘다.
#   억제: FPM_NO_ATTACH=1
_fpm_tmux_focus() {
    local tb="$1" win="$2"
    [ -n "${FPM_NO_ATTACH:-}" ] && return 0
    if [ -n "${TMUX:-}" ]; then
        "$tb" select-window -t "pm:$win" 2>/dev/null
        return 0
    fi
    if [ ! -t 1 ]; then
        echo "   (attach 생략: 비대화 문맥. 직접 들어가려면 \`tmux attach -t pm\`)" >&2
        return 0
    fi
    "$tb" select-window -t "pm:$win" 2>/dev/null
    "$tb" attach-session -t pm
}

# _fpm_split_pane <dir> [cmd] : 새 pane 에서 dir 로 이동(+cmd 실행)
#   macOS+iTerm2 → osascript 수평분할 / tmux 세션 안 → tmux split-window
#   둘 다 아니면 안내 후 1 반환 (호출측이 경로만 출력하도록)
_fpm_split_pane() {
    local dir="$1" cmd="$2" full="cd '$1'"
    [ -n "$cmd" ] && full="${full} && ${cmd}"
    if _fpm_is_macos; then
        osascript -e "tell application \"iTerm2\" to tell current session of current window to tell (split horizontally with default profile) to write text \"${full}\""
        sleep 0.1
        return 0
    fi
    local tb
    if [ -n "${TMUX:-}" ] && tb=$(_fpm_tmux_bin); then
        "$tb" split-window -h -c "$dir" ${cmd:+"$cmd"}
        "$tb" select-layout -E >/dev/null 2>&1
        return 0
    fi
    return 1
}

# --- CDF (인덱스 기반 디렉토리 이동) ---
# _pm_manager : 베이스 경로 관리 및 목록 출력 공용 함수
#   base = $FPM_BASE/projects (env 우선). FPM_BASE 미설정 시 legacy ~/.info/__pmBasePath.txt fallback.
_pm_manager() {
    local base_dir
    if [[ -n "${FPM_BASE:-}" && -d "${FPM_BASE}/projects" ]]; then
        base_dir="${FPM_BASE}/projects"
        # lazy sync — Projects.md(SSOT) 가 인덱스보다 최신이면 projects/ 자동 재생성.
        # "동기화 해줘" 수동 명령을 잊어도 cdf 사용 시점에 항상 최신 보장.
        # stamp 부재(첫 실행) → -nt 가 참 → 1회 동기화 후 stamp 생성.
        local _ssot="${FPM_BASE}/Projects.md" _stamp="${base_dir}/.sync-stamp"
        if [[ -f "$_ssot" && "$_ssot" -nt "$_stamp" && -x "${FPM_BASE}/sh/fpm-projects-sync" ]]; then
            "${FPM_BASE}/sh/fpm-projects-sync" --index-only >/dev/null 2>&1 && touch "$_stamp"
        fi
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

# === FRECENCY + FUZZY FALLBACK (Issue227 / T4) =========================
# 번호 점프(SSOT·결정론)는 그대로. 비번호 인자일 때만 아래 fallback 레이어 발동.
#   store: $FPM_BASE/projects/.frecency  (행 = "id|freq|epoch", gitignore)
#   bump : cdf 로 실제 cd 한 id 의 빈도 +1·최근시각 갱신 (zoxide-lite, recency 우선)
#   resolve: fzf 가용·tty → frecency 정렬 리스트 + fuzzy picker
#            fzf 미가용/ESC 아닌 no-match → _cdfn_resolve(이름·한글 substring) 로 위임

# _fpm_frecency_file : store 경로 출력
_fpm_frecency_file() {
    local base; base=$(_pm_manager) || return 1
    printf '%s/.frecency' "$base"
}

# _fpm_frecency_bump <id> : 해당 id 의 freq +1, epoch 갱신 (없으면 신규 행)
_fpm_frecency_bump() {
    local id="$1"; [ -n "$id" ] || return 0
    local f; f=$(_fpm_frecency_file) || return 0
    local now; now=$(command date +%s)
    local tmp="${f}.tmp.$$" found=0 i fr la
    if [ -f "$f" ]; then
        while IFS='|' read -r i fr la; do
            [ -z "$i" ] && continue
            if [ "$i" = "$id" ]; then fr=$((fr + 1)); la=$now; found=1; fi
            printf '%s|%s|%s\n' "$i" "$fr" "$la"
        done < "$f" > "$tmp"
    fi
    [ "$found" -eq 0 ] && printf '%s|%s|%s\n' "$id" 1 "$now" >> "$tmp"
    command mv -f "$tmp" "$f" 2>/dev/null
}

# _fpm_frecency_candidates : "<id>\t<id>  <path>" 행을 frecency-desc 로 emit.
#   1) store 가 있으면 epoch desc · freq desc 정렬해 먼저 (최근 방문 상단)
#   2) store 에 없는 나머지 프로젝트를 id 순으로 뒤에 append (전체 탐색 가능)
#   외부명령은 전부 `command` prefix — 유저 zsh 의 alias(grep/sort/cat 등) 우회
#   (코드베이스 관례; 미prefix 시 함수 내 alias 오파싱으로 "command not found" 발생).
#   ⚠️ 변수명 path 금지 — zsh 에서 $path 는 $PATH 에 tie 된 특수배열.
#      local path 선언 시 함수 내 PATH 가 깨져 외부명령 전멸. _p 사용.
_fpm_frecency_candidates() {
    local base; base=$(_pm_manager) || return 1
    local f="${base}/.frecency" id fr la _p pf
    if [ -f "$f" ]; then
        command sort -t'|' -k3,3nr -k2,2nr "$f" | while IFS='|' read -r id fr la; do
            [ -n "$id" ] || continue
            pf="${base}/${id}"; [ -f "$pf" ] || continue
            _p=$(eval echo $(command cat "$pf"))
            printf '%s\t%s  %s\n' "$id" "$id" "$_p"
        done
    fi
    for pf in "${base}"/[0-9]*; do
        [ -f "$pf" ] || continue
        id=$(command basename "$pf")
        [ -f "$f" ] && command grep -q "^${id}|" "$f" && continue   # 이미 위에서 emit
        _p=$(eval echo $(command cat "$pf"))
        printf '%s\t%s  %s\n' "$id" "$id" "$_p"
    done
}

# _cdf_resolve_smart <query> : 비번호 인자 → 단일 id 를 stdout 으로 반환
#   fzf 가용 + stdout tty → frecency 리스트 fuzzy picker (query 초기 필터)
#     fzf rc: 0=선택 / 1=no-match → 이름·한글 resolver 위임 / 130=ESC → 취소
#   fzf 미가용 → 바로 _cdfn_resolve
_cdf_resolve_smart() {
    local q="$1"
    if command -v fzf >/dev/null 2>&1 && [ -t 1 ]; then
        local picked rc
        picked=$(_fpm_frecency_candidates | command cut -f2- | \
            command fzf --query="$q" --select-1 --exit-0 --height=40% --reverse \
                --prompt='cdf> ' --header='frecency+fuzzy (번호 점프가 우선; 이건 fallback)')
        rc=$?
        if [ "$rc" -eq 0 ] && [ -n "$picked" ]; then
            printf '%s' "${picked%% *}"; return 0
        fi
        [ "$rc" -eq 130 ] && { echo "취소됨" >&2; return 1; }
        # rc==1 (no match) → 이름·한글 substring resolver 로 위임
    fi
    _cdfn_resolve "$q"
}
# ======================================================================

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
    _CDF_IDS=()
    _CDF_CMD=""
    [[ -z "$1" ]] && { _pm_manager "list"; return 1; }

    # --- fallback 레이어 (Issue227 / T4): 첫 토큰이 비번호 텍스트면 frecency+fuzzy 로 id 해석.
    #     번호/범위(11-16)/특수(list·---)는 건너뜀 → 번호 결정론성 100% 보존.
    case "$1" in
        list|---|[0-9]*) : ;;                       # 번호·범위·특수 → 기존 경로
        *)
            local _fid
            _fid=$(_cdf_resolve_smart "$1") || return 1
            shift; set -- "$_fid" "$@"
            ;;
    esac

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
            # 프로젝트 id (Issue303): 정수 | 정수+소문자 | 정수+소문자+정수 (9 / 9a / 9a1).
            # 반드시 위 범위 검사 **뒤**에 둘 것 — 순서가 바뀌면 11-16 이 범위로 안 잡힘.
            # 하이픈은 범위 문법에 영구 예약, 점은 regex 메타문자라 접미 구분자에서 배제.
            # 설계 SSOT: _doc_arch/project-id-scheme.md
            elif [[ "$token" =~ ^[0-9]+([a-z][0-9]*)?$ ]]; then
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
        _CDF_IDS+=("$idx")          # frecency bump 용 (cdf 가 cd 후 갱신)
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

    local first=1 _CDF_HINTED=0   # _CDF_HINTED: 분할 불가 안내를 인덱스마다 반복 출력하지 않기 위함
    for target in "${_CDF_TARGETS[@]}"; do
        if [[ $first -eq 1 ]]; then
            first=0
            cd "$target"
            [[ -n "$_CDF_CMD" ]] && eval "$_CDF_CMD"
        else
            # 2번째 이후 인덱스 = 창 분할. macOS(iTerm2) → osascript, tmux 안 → split-window.
            if ! _fpm_split_pane "$target" "$_CDF_CMD"; then
                # tmux 밖 Linux → 분할 불가. 같은 목적의 이식 가능 대안(cdft)을 즉시 제시.
                if [[ $_CDF_HINTED -eq 0 ]]; then
                    _CDF_HINTED=1
                    _fpm_need_macos "cdf 다중 인덱스(창 분할)" \
                        "대신 \`cdft ${_CDF_IDS[*]}\` 를 쓰면 tmux pm 세션에 pane 을 만들어 동일하게 동작함 (OS 무관)."
                    echo "   아래는 해석된 경로 (cd 는 첫 인덱스만 적용됨):" >&2
                fi
                echo "   $target"
            fi
        fi
    done

    # frecency bump (Issue227 / T4): 방문한 모든 인덱스의 빈도·최근시각 갱신.
    local _bid
    for _bid in "${_CDF_IDS[@]}"; do _fpm_frecency_bump "$_bid"; done
}

# cdff : Finder에서 해당 경로 열기
cdff() {
    _cdf_base "$@" || return 0
    _cdf_apply_subfolder
    # 파일관리자 열기: macOS=open / Linux=xdg-open. 둘 다 없으면 경로만 출력.
    local opener=""
    if _fpm_is_macos; then opener=open
    else opener=$(command -v xdg-open 2>/dev/null || true); fi
    if [[ -z "$opener" ]]; then
        _fpm_need_macos "cdff (파일관리자 열기)" "xdg-open 설치 시 Linux 도 지원. 지금은 경로만 출력:"
        printf '   %s\n' "${_CDF_TARGETS[@]}"
        return 1
    fi
    for target in "${_CDF_TARGETS[@]}"; do
        "$opener" "$target"
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
    [[ -z "$result" ]] && return 0
    result="${result%$'\n'}"
    # 클립보드: macOS=pbcopy / Wayland=wl-copy / X11=xclip|xsel
    local clip=""
    if _fpm_is_macos; then clip="pbcopy"
    elif command -v wl-copy >/dev/null 2>&1; then clip="wl-copy"
    elif command -v xclip   >/dev/null 2>&1; then clip="xclip -selection clipboard"
    elif command -v xsel    >/dev/null 2>&1; then clip="xsel --clipboard --input"
    fi
    if [[ -z "$clip" ]]; then
        _fpm_need_macos "cdfc (클립보드 복사)" "Linux 는 wl-copy / xclip / xsel 중 하나 설치 필요. 지금은 경로만 출력:"
        echo "$result"
        return 1
    fi
    echo -n "$result" | eval "$clip"
    echo "📋 Copied to clipboard."
}

# cdfv : 해당 경로를 VS Code로 열기
#   -n / --new-window : 지정 프로젝트들을 기존 창과 분리된 "새 창(탭 그룹)"으로 함께 열기.
#     ex) cdfv -n 15 25  → 15·25 가 한 창에 탭으로 같이, 기존 무관한 창과는 분리.
#     macOS window tabbing=always 환경 대응: 첫 프로젝트를 열고 applescript
#     "Move Tab to New Window" 로 새 창(W1)으로 분리(1회만). 이후 프로젝트는
#     frontmost=W1 로 자동 병합 → 지정 프로젝트끼리 한 창에 모임.
#   -e <editor> / --editor <editor> : 대상 에디터 지정 (vscode|zed). 미지정 시 data/editor.yml 의
#     default_editor. `cdfz` 는 `cdfv -e zed` 의 별칭. (Issue327 — 어댑터 sh/fpm_editors.sh)
cdfv() {
    local new_window=0 editor=""
    while :; do
        case "$1" in
            -n|--new-window) new_window=1; shift ;;
            -e|--editor)     editor="$2"; shift 2 ;;
            *) break ;;
        esac
    done
    [[ -z "$editor" ]] && editor=$(_fpm_editor_default 2>/dev/null || echo vscode)

    _cdf_base "$@" || return 0
    _cdf_apply_subfolder

    # Zed: 다중 경로 1회 호출 = 한 창 멀티루트(실측). AppleScript 병합 불필요.
    if [[ "$editor" == "zed" ]]; then
        local -a existing=()
        for target in "${_CDF_TARGETS[@]}"; do
            if [[ -e "$target" ]]; then echo "🚀 Opening (zed): $target"; existing+=("$target")
            else echo "Warning: Path '$target' not found."; fi
        done
        (( ${#existing[@]} )) || return 0
        if [[ $new_window -eq 1 ]]; then _fpm_editor_open zed new "${existing[@]}"
        else _fpm_editor_open zed open "${existing[@]}"; fi
        return
    fi

    # VSCode: macOS window tabbing 대응 — 첫 프로젝트만 새 창 분리 후 나머지 병합
    local nw_detached=0
    for target in "${_CDF_TARGETS[@]}"; do
        if [[ -e "$target" ]]; then
            echo "🚀 Opening: $target"
            if [[ $new_window -eq 1 ]]; then
                _fpm_editor_open vscode new "$target"
                sleep 0.8   # 새 창(탭) 생성 대기
                if [[ $nw_detached -eq 0 ]] && ! _fpm_is_macos; then
                    # Linux: window tabbing 자체가 없어 분리 불필요 — code -n 결과 그대로 사용
                    nw_detached=1
                elif [[ $nw_detached -eq 0 ]]; then
                    # 첫 프로젝트만 별도 창으로 분리 (이후 프로젝트는 이 창에 병합)
                    osascript -e 'tell application "System Events" to tell process "Code"' \
                              -e 'set mi to menu item "Move Tab to New Window" of menu 1 of menu bar item "Window" of menu bar 1' \
                              -e 'if enabled of mi then click mi' \
                              -e 'end tell' 2>/dev/null
                    nw_detached=1
                    sleep 0.2
                fi
            else
                _fpm_editor_open vscode open "$target" && sleep 0.1
            fi
        else
            echo "Warning: Path '$target' not found."
        fi
    done
}

# cdfz : cdfv 의 Zed 변형 (= cdfv -e zed)
cdfz() { cdfv -e zed "$@"; }

# --- CDF*N (이름 기반: 번호 대신 문자 부분일치) ---
# _cdfn_resolve : 텍스트 부분일치 → 단일 프로젝트 id 를 stdout 으로 반환 (cdf 계열의 _cdf_base 대응)
#   매칭 소스 = $FPM_BASE/Projects.md 테이블의 프로젝트명·한국어명칭·경로 (대소문자 무시)
#   매치 0개 → 메시지(stderr)+return 1 / 1개 → id 출력 / 다수 → choose from list 선택 후 id 출력
#   호출측(cdfn/cdfvn/…)은 반환 id 를 기존 cdf/cdfv 등에 넘겨 동작 — index→경로 해석은 그쪽이 담당
# zsh 전용 구현(setopt·<->·${(@s)}·${(L)}·중첩 ${${}})은 별도 파일로 분리해 source.
# bash 가 본 파일을 source 할 때 `<->` 등 zsh 글롭이 parse error 를 내지 않도록 격리
# (fpm.sh:24 의 eval 격리와 동일 취지). bash 는 동등 fallback 을 아래에서 정의.
if [ -n "${ZSH_VERSION:-}" ]; then
    [ -f "${FPM_BASE}/sh/fpm_function_zsh.sh" ] && . "${FPM_BASE}/sh/fpm_function_zsh.sh"
else
    # bash fallback: Projects.md 표를 '|' 로 split, 숫자 id 행만 매칭 (zsh 구현과 동작 동일).
    _cdfn_resolve() {
        local q="$1"
        [ -z "$q" ] && { echo "Usage: cdf*n <text>  (프로젝트명/한글명/경로 부분일치)" >&2; return 1; }
        local proj_md="${FPM_BASE}/Projects.md"
        [ -f "$proj_md" ] || { echo "Error: $proj_md not found" >&2; return 1; }
        local ql; ql=$(printf '%s' "$q" | tr '[:upper:]' '[:lower:]')
        local -a hits=()
        local line id eng kor pth hay
        local -a cols
        while IFS= read -r line; do
            [[ "$line" == \|* ]] || continue            # 표 행만
            IFS='|' read -r -a cols <<< "$line"          # '|' 로 split (bash 0-index)
            # cols: [0]="" [1]=id [2]=프로젝트명 [3]=한국어명 [4]=Dmn [5]=경로 ...
            id=$(printf '%s' "${cols[1]}" | tr -d '[:space:]')
            [[ "$id" =~ ^[0-9]+$ ]] || continue          # 숫자 id 행만
            eng=$(printf '%s' "${cols[2]}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
            kor=$(printf '%s' "${cols[3]}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
            pth=$(printf '%s' "${cols[5]//\`/}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
            hay=$(printf '%s %s %s' "$eng" "$kor" "$pth" | tr '[:upper:]' '[:lower:]')
            [[ "$hay" == *"$ql"* ]] && hits+=("${id}"$'\t'"${id}  ${eng}  (${kor})  ${pth}")
        done < "$proj_md"

        local n=${#hits[@]}
        if [ "$n" -eq 0 ]; then
            echo "❌ no match: $q" >&2; return 1
        elif [ "$n" -eq 1 ]; then
            printf '%s' "${hits[0]%%$'\t'*}"; return 0   # bash 0-index
        else
            local menu_file="/tmp/.cdfn_menu_$$" picked
            printf '%s\n' "${hits[@]#*$'\t'}" > "$menu_file"
            # macOS 아니면 choose from list(osascript) 불가 → 터미널 번호 입력 fallback
            if ! _fpm_is_macos; then
                command rm -f "$menu_file"
                echo "여러 개 매치 — 번호 선택 (macOS 선택창은 macOS 전용, 터미널 입력으로 대체)" >&2
                local _i=1 _h
                for _h in "${hits[@]}"; do echo "  [$_i] ${_h#*$'\t'}" >&2; _i=$((_i+1)); done
                printf '번호> ' >&2; read -r picked
                [[ "$picked" =~ ^[0-9]+$ ]] && [ "$picked" -ge 1 ] && [ "$picked" -le "$n" ] \
                    || { echo "취소됨" >&2; return 1; }
                printf '%s' "${hits[$((picked-1))]%%$'\t'*}"; return 0
            fi
            picked=$(osascript \
                -e 'set t to do shell script "cat '"$menu_file"'"' \
                -e 'set L to paragraphs of t' \
                -e 'set c to choose from list L with prompt "여러 개 매치 — 프로젝트 선택" without multiple selections allowed' \
                -e 'if c is false then return ""' \
                -e 'return item 1 of c' 2>/dev/null)
            command rm -f "$menu_file"
            [ -z "$picked" ] && { echo "취소됨" >&2; return 1; }
            printf '%s' "${picked%% *}"; return 0
        fi
    }
fi

# cdfn  : 숫자 시작이면 cdf  인덱스 모드(범위·다중), 아니면 이름 부분일치 → cd
# cdfvn : 숫자 시작이면 cdfv 인덱스 모드(범위·다중), 아니면 이름 부분일치 → VS Code
#   ex) cdfn 5 / cdfn 11-16 / cdfn common / cdfn 커먼 / cdfvn snippet
#       (이름검색: 0개→알림 · 1개→즉시 · 다수→선택창)
#   필요 시 cdffn(Finder)·cdfcn(클립보드)도 동일 한 줄 패턴으로 추가 가능
cdfn()  { [[ "$1" == [0-9]* ]] && { cdf  "$@"; return; }; local _id; _id=$(_cdfn_resolve "$1") || return; cdf  "$_id"; }
cdfvn() { local _a="$1"; [[ "$_a" == "-n" || "$_a" == "--new-window" ]] && _a="$2"; [[ "$_a" == [0-9]* ]] && { cdfv "$@"; return; }; local _id; _id=$(_cdfn_resolve "$1") || return; cdfv "$_id"; }
# cdfzn : cdfvn 의 Zed 변형 (이름검색 → zed)
cdfzn() { local _id; [[ "$1" == [0-9]* ]] && { cdfz "$@"; return; }; _id=$(_cdfn_resolve "$1") || return; cdfz "$_id"; }

# cdf-num : cdf 의 역방향 — 경로(기본 $PWD) → 등록 프로젝트 번호 조회
#   ex) cdf-num             : 현재 디렉토리 기준 번호 출력
#       cdf-num /some/path  : 지정 경로 기준
#       cdf-num -v          : 번호 + 매칭된 등록 경로도 stderr 로 표시
#   서브폴더에서 실행해도 등록 경로 중 최장 prefix 일치 항목으로 귀속 (hub _resolve_project_root 와 동일 정책)
cdf-num() {
    local verbose=0
    [[ "$1" == "-v" ]] && { verbose=1; shift; }
    local target="${1:-$PWD}"
    target="${target/#\~/$HOME}"
    target="$(cd "$target" 2>/dev/null && pwd)" || { echo "Error: 유효하지 않은 경로: ${1:-$PWD}" >&2; return 1; }

    local base_dir; base_dir=$(_pm_manager) || return 1
    local best_id="" best_path="" best_len=-1
    local f p
    for f in "${base_dir}"/[0-9]*; do
        [[ -f "$f" ]] || continue
        p=$(cat "$f")
        p="${p/#\~/$HOME}"
        p="${p%/}"
        [[ -z "$p" ]] && continue
        if [[ "$target" == "$p" || "$target" == "$p"/* ]] && (( ${#p} > best_len )); then
            best_len=${#p}
            best_id=$(basename "$f")
            best_path="$p"
        fi
    done

    if [[ -z "$best_id" ]]; then
        echo "미등록 경로: $target" >&2
        return 1
    fi
    echo "$best_id"
    (( verbose )) && echo "  path: $best_path" >&2
    return 0
}

# _fpm_clean_path : 터미널 제어 문자(Bracketed paste \e[?2004l, ANSI escape 등) 제거 헬퍼
_fpm_clean_path() {
    printf '%s' "$1" | LC_ALL=C sed -e "s/'$'\x1b''\[[0-9;?]*[a-zA-Z]//g" -e "s/\[?[0-9]*[a-zA-Z]//g"
}

# cdf-rel (cdfr) : 등록 프로젝트 루트 기준 상대 경로(Project-relative path) 추출
#   ex) cdf-rel $HOME/Documents/finfra/<private-project>/_doc_arch/file.md
#       → _doc_arch/file.md
#       cdfr (alias)
cdf-rel() {
    local raw_target="${1:-$PWD}"
    local target; target=$(_fpm_clean_path "$raw_target")
    target="${target/#\~/$HOME}"

    if [[ -d "$target" ]]; then
        target="$(chpwd_functions=(); builtin cd -P -- "$target" 2>/dev/null && pwd)"
    elif [[ -f "$target" ]]; then
        local dir_part="$(dirname "$target")"
        local base_part="$(basename "$target")"
        dir_part="$(chpwd_functions=(); builtin cd -P -- "$dir_part" 2>/dev/null && pwd)"
        target="${dir_part}/${base_part}"
    fi

    local base_dir; base_dir=$(_pm_manager) || return 1
    local best_path="" best_len=-1
    local f p
    for f in "${base_dir}"/[0-9]*; do
        [[ -f "$f" ]] || continue
        p=$(cat "$f")
        p="${p/#\~/$HOME}"
        p="${p%/}"
        [[ -z "$p" ]] && continue
        if [[ "$target" == "$p" || "$target" == "$p"/* ]] && (( ${#p} > best_len )); then
            best_len=${#p}
            best_path="$p"
        fi
    done

    if [[ -z "$best_path" ]]; then
        _fpm_clean_path "$target"
        echo
        return 1
    fi

    local rel="${target#$best_path}"
    rel="${rel#/}"
    local res
    if [[ -z "$rel" ]]; then
        res="."
    else
        res="$rel"
    fi
    _fpm_clean_path "$res"
    echo
}

cdfr() {
    cdf-rel "$@"
}

# cdf-base (cdfb) : 경로(파일 가능) → 등록 프로젝트 루트 절대 경로 (cdf-rel 의 짝)
#   ex) cdf-base $HOME/Documents/finfra/<private-project>/_doc_arch/x.md
#       → $HOME/Documents/finfra/<private-project>
#       cdf-base -n  : 루트 경로 + 프로젝트 번호를 stderr 로 표시
#   최장 prefix 일치. 미등록이면 stderr 안내 후 exit 1
cdf-base() {
    local verbose=0
    [[ "$1" == "-n" || "$1" == "-v" ]] && { verbose=1; shift; }

    local raw_target="${1:-$PWD}"
    local target; target=$(_fpm_clean_path "$raw_target")
    target="${target/#\~/$HOME}"

    if [[ -d "$target" ]]; then
        target="$(chpwd_functions=(); builtin cd -P -- "$target" 2>/dev/null && pwd)"
    elif [[ -f "$target" ]]; then
        local dir_part="$(dirname "$target")"
        local base_part="$(basename "$target")"
        dir_part="$(chpwd_functions=(); builtin cd -P -- "$dir_part" 2>/dev/null && pwd)"
        target="${dir_part}/${base_part}"
    fi

    local base_dir; base_dir=$(_pm_manager) || return 1
    local best_id="" best_path="" best_len=-1
    local f p
    for f in "${base_dir}"/[0-9]*; do
        [[ -f "$f" ]] || continue
        p=$(cat "$f")
        p="${p/#\~/$HOME}"
        p="${p%/}"
        [[ -z "$p" ]] && continue
        if [[ "$target" == "$p" || "$target" == "$p"/* ]] && (( ${#p} > best_len )); then
            best_len=${#p}
            best_path="$p"
            best_id=$(basename "$f")
        fi
    done

    if [[ -z "$best_path" ]]; then
        echo "미등록 경로: $target" >&2
        return 1
    fi

    _fpm_clean_path "$best_path"
    echo
    (( verbose )) && echo "  prj: $best_id" >&2
    return 0
}

cdfb() {
    cdf-base "$@"
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
    # tmux 경로: PATH 우선 → Homebrew fallback (Linux 는 /usr/bin/tmux 등)
    local TMUX_CMD
    TMUX_CMD=$(_fpm_tmux_bin) || { echo "⛔ cdft : tmux 미설치 (PATH·/opt/homebrew 모두 없음)" >&2; return 1; }
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
        _fpm_say "session ready"
        echo "WIN_NAME=$REUSE_WIN"
        _fpm_tmux_focus "$TMUX_CMD" "$REUSE_WIN"
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
        _fpm_say "session ready"
        echo "WIN_NAME=$WIN_NAME"
        _fpm_tmux_focus "$TMUX_CMD" "$WIN_NAME"
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
                if ! _fpm_split_pane "$PWD" "ssh ${n}"; then
                    _fpm_need_macos "sshf 다중 접속(창 분할)" \
                        "tmux 세션 안에서 실행하면 split-window 로 동작함. 건너뜀: ssh ${n}"
                fi
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
    # 제어 터미널 없는 셸(Claude Code Bash 등)에선 /dev/tty open 실패 → 에러 노이즈.
    # 그룹+2>/dev/null 로 리다이렉트 실패를 침묵 처리(정상 터미널에선 그대로 동작).
    if [[ -z "$1" ]]; then
        # 배경(111) + 전경(110) 모두 프로파일 기본값 복원 (Issue333)
        { printf '\033]111;\007\033]110;\007' > /dev/tty; } 2>/dev/null
    else
        local hex="${1#\#}"
        # 배경 명도에 맞춘 가독 전경색 동반 전송 (Issue333)
        # fpm-projects-sync 의 readable_fg() 와 동일 공식: 0.2126R + 0.7152G + 0.0722B
        if [[ "$hex" =~ ^[0-9a-fA-F]{6}$ ]]; then
            local r g b lum fg
            r=$((16#${hex:0:2})); g=$((16#${hex:2:2})); b=$((16#${hex:4:2}))
            lum=$(( (2126 * r + 7152 * g + 722 * b) / 10000 ))   # 0..255
            if (( lum > 127 )); then fg=15202b; else fg=e8e8e8; fi
            { printf '\033]1337;SetColors=bg=%s\007\033]1337;SetColors=fg=%s\007' "$hex" "$fg" > /dev/tty; } 2>/dev/null
        else
            # hex 파싱 실패 시 기존 동작(배경만) 유지 — fail-soft
            { printf '\033]1337;SetColors=bg=%s\007' "$hex" > /dev/tty; } 2>/dev/null
        fi
    fi
}

# chpwd : 디렉토리 이동 시 .vscode/settings.json 의 peacock.color 를 iTerm2 배경색으로 적용
#   - peacock.color 없으면 기본값 복원. (zsh 훅 — bash 에선 미사용 함수로만 존재)
chpwd() {
    local hex settings
    # 1) VSCode peacock
    settings="$PWD/.vscode/settings.json"
    if [[ -f "$settings" ]]; then
        hex=$(grep -o '"peacock\.color"\s*:\s*"#[0-9a-fA-F]\{6\}"' "$settings" \
            | grep -o '#[0-9a-fA-F]\{6\}' \
        | head -1)
        [[ -n "$hex" ]] && { iterm-bg "${hex#\#}"; return; }
    fi
    # 2) Zed theme_overrides (Issue327) — .vscode 없는 Zed 전용 프로젝트 대응
    settings="$PWD/.zed/settings.json"
    if [[ -f "$settings" ]]; then
        hex=$(grep -o '"editor\.background"\s*:\s*"#[0-9a-fA-F]\{6\}"' "$settings" \
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
# fhub : 터미널(iTerm 등)에서 hub 대시보드를 브라우저로 열기 (Issue162).
#   Keyboard Maestro 매크로 "fPm hub page Open" 의 CLI 버전.
#   default_browser(hub_setting.yml)를 그대로 따른다 — 강제 치환 없음 (Issue297).
#   match=origin(:9876) → /hub·?path=… 모든 hub URL 을 단일 탭으로 재사용(재사용 가능 브라우저 한정).
#   Usage: fhub [url]   ex) fhub  /  fhub http://127.0.0.1:9876/hub
#
# Issue297: 구 구현은 default_browser 를 읽고도 firefox 면 `db=chrome` 으로 강제 치환했다.
#   사유는 "firefox 는 AppleScript 탭 제어 사전이 없어 탭 재사용 불가" 였으나, 그 결과
#   `default_browser: firefox` 설정이 이 경로에서만 무시되어 "설정대로 안 열린다" 혼란을 낳았다.
#   설정 SSOT 준수를 우선하여 치환을 제거한다. 트레이드오프 — firefox 는 helper 의 open 폴백을
#   타므로 탭 재사용이 안 되고 호출마다 새 탭이 누적된다(누적 감수). 탭 재사용이 꼭 필요하면
#   hub_setting.yml 의 default_browser 를 chrome/safari/edge 로 지정할 것.
fhub() {
    local url="${1:-http://127.0.0.1:9876/hub}"
    local helper="$FPM_BASE/plugins/fpm-core/hooks/fpm-browser-open.sh"
    [[ -f "$helper" ]] || { echo "fhub: helper 없음 ($helper)" >&2; return 1; }
    local db
    db=$(grep -E '^[[:space:]]*default_browser:' "$FPM_BASE/data/hub_setting.yml" 2>/dev/null \
         | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
    # 키 부재·빈값이면 helper 기본값(firefox)에 위임 — 여기서 브라우저를 임의 선택하지 않는다.
    bash "$helper" ${db:+-a "$db"} -f true -r true -m "http://127.0.0.1:9876" "$url"
}

# --- fpm : 설치본 셀프 관리 커맨드 (Issue224 T1) ---------------------------
# 패키지 매니저식 update/upgrade/version/uninstall. $FPM_BASE(설치 위치) 기준 동작.
#   fpm update     git pull(+clean-check) → install.sh 재실행 → claude plugin update
#   fpm upgrade    원격 최신 태그가 현재 VERSION 보다 새로우면 그 태그로 체크아웃 후 update
#   fpm version    설치본 VERSION 출력
#   fpm uninstall  uninstall.sh 위임 (인자 그대로 전달: --no-scar 등)
#   fpm help       사용법
# 안전장치: update/upgrade 는 로컬 미커밋 변경이 있으면 중단(사용자 변경 보호).
fpm() {
    local base="${FPM_BASE:-}"
    [[ -n "$base" && -d "$base" ]] || { echo "fpm: FPM_BASE 미설정/부재 — fpm.sh 부트스트랩 확인" >&2; return 1; }
    local sub="${1:-help}"; shift 2>/dev/null || true

    # 미커밋 변경 가드 (update/upgrade 공용)
    _fpm_clean_check() {
        if [[ ! -d "$base/.git" ]]; then
            echo "fpm: $base 가 git repo 아님 — 셀프업데이트 불가(수동 설치본?)" >&2; return 1
        fi
        if [[ -n "$(git -C "$base" status --porcelain 2>/dev/null)" ]]; then
            echo "fpm: 로컬 미커밋 변경 있음 → 중단(덮어쓰기 방지)." >&2
            echo "     git -C \"$base\" stash  또는 commit 후 다시 시도." >&2
            return 1
        fi
        return 0
    }

    case "$sub" in
        version|-v|--version)
            cat "$base/VERSION" 2>/dev/null || { echo "fpm: VERSION 없음" >&2; return 1; }
            ;;
        update)
            _fpm_clean_check || return 1
            echo "[fpm] git pull ($base)…"
            git -C "$base" pull --ff-only || { echo "fpm: pull 실패(fast-forward 불가) — 수동 확인" >&2; return 1; }
            echo "[fpm] install.sh 재실행(멱등)…"
            bash "$base/sh/install.sh" "$@" || return 1
            if command -v claude >/dev/null 2>&1; then
                echo "[fpm] SCAR 플러그인 갱신…"
                claude plugin update fpm-core@f-claude-plugins 2>/dev/null \
                    || echo "[fpm] (plugin update 건너뜀 — 설치 안 됨/네트워크)"
            fi
            echo "[fpm] update 완료 → $(cat "$base/VERSION" 2>/dev/null)"
            ;;
        upgrade)
            _fpm_clean_check || return 1
            git -C "$base" fetch --tags --quiet || { echo "fpm: fetch 실패" >&2; return 1; }
            local cur latest
            cur="$(cat "$base/VERSION" 2>/dev/null || echo 0)"
            latest="$(git -C "$base" tag -l 'v*' --sort=-v:refname | head -1)"
            if [[ -z "$latest" ]]; then
                echo "[fpm] 원격 태그 없음 → 'fpm update'(브랜치 최신)로 갱신하세요."; return 0
            fi
            echo "[fpm] 현재 VERSION=$cur / 최신 태그=$latest"
            if [[ "v$cur" == "$latest" ]]; then
                echo "[fpm] 이미 최신 태그."; return 0
            fi
            echo "[fpm] $latest 로 체크아웃…"
            git -C "$base" checkout --quiet "$latest" || { echo "fpm: 체크아웃 실패" >&2; return 1; }
            bash "$base/sh/install.sh" "$@" || return 1
            command -v claude >/dev/null 2>&1 && claude plugin update fpm-core@f-claude-plugins 2>/dev/null
            echo "[fpm] upgrade 완료 → $latest"
            ;;
        uninstall|remove)
            bash "$base/sh/uninstall.sh" "$@"
            ;;
        help|-h|--help|*)
            cat <<'EOF'
fpm — 설치본 셀프 관리 (Issue224)
  fpm version     설치 버전 출력
  fpm update      브랜치 최신으로 갱신 (git pull + install.sh + SCAR plugin update)
  fpm upgrade     원격 최신 릴리즈 태그로 갱신
  fpm uninstall   제거 (sh/uninstall.sh — --no-scar 등 인자 전달)
  fpm help        이 도움말
원격 원라인 설치:
  curl -fsSL https://raw.githubusercontent.com/Finfra/fpm/main/sh/bootstrap.sh | sh
EOF
            ;;
    esac
}
