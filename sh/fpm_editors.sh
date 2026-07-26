# shellcheck shell=bash
# sh/fpm_editors.sh — 에디터 어댑터 + 경로 런처 (Issue327)
#
# 설계 SSOT: _doc_arch/editor-abstraction-design.md
#
# 제공:
#   _fpm_editor_cfg <key>            : data/editor.yml 값 조회 (flat key:value)
#   _fpm_editor_bin <editor>         : CLI 실행 파일 경로 해석 (5단계, 하드코딩 없음)
#   _fpm_editor_open <editor> <paths>: 경로들을 그 에디터로 열기 (capability 반영)
#   v/vn/vw   : VSCode 경로 런처 (신규창/대기)
#   z/zn/za/zw: Zed 경로 런처 (신규창/현재창추가/대기)
#
# cdfv/cdfz(번호 런처, fpm_function.sh)와 같은 어댑터를 공유한다 —
# 에디터를 추가할 때 고칠 곳이 한 군데여야 하기 때문.

# --- 설정 조회 (flat key:value, 주석·빈값 무시) ---
_fpm_editor_cfg() {
    local key="$1" f="${FPM_BASE}/data/editor.yml" val
    [ -f "$f" ] || return 1
    val=$(grep -E "^[[:space:]]*${key}[[:space:]]*:" "$f" 2>/dev/null | head -1 \
        | sed -E "s/^[[:space:]]*${key}[[:space:]]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//")
    [ -n "$val" ] || return 1
    printf '%s\n' "$val"
}

_fpm_editor_default() { _fpm_editor_cfg default_editor 2>/dev/null || echo vscode; }

# --- CLI 경로 해석: env → editor.yml → PATH → .app 후보 → 실패(에러 1줄) ---
_fpm_editor_bin() {
    local ed="$1" up cand
    case "$ed" in
        vscode|code) ed=vscode ;;
        zed)         ed=zed ;;
        *) echo "❌ 알 수 없는 에디터: $ed (vscode|zed)" >&2; return 1 ;;
    esac

    # 1) env override — FPM_EDITOR_BIN_VSCODE / FPM_EDITOR_BIN_ZED
    up=$(printf '%s' "$ed" | tr '[:lower:]' '[:upper:]')
    eval "cand=\${FPM_EDITOR_BIN_${up}:-}"
    [ -n "$cand" ] && [ -x "$cand" ] && { printf '%s\n' "$cand"; return 0; }

    # 2) editor.yml 의 bin_<editor>
    cand=$(_fpm_editor_cfg "bin_${ed}" 2>/dev/null)
    [ -n "$cand" ] && [ -x "$cand" ] && { printf '%s\n' "$cand"; return 0; }

    # 3) PATH
    case "$ed" in
        vscode) cand=$(command -v code 2>/dev/null) ;;
        zed)    cand=$(command -v zed 2>/dev/null) ;;
    esac
    [ -n "$cand" ] && [ -x "$cand" ] && { printf '%s\n' "$cand"; return 0; }

    # 4) .app 내부 CLI 후보
    local candidates
    if [ "$ed" = "vscode" ]; then
        candidates="/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code
/Applications/_editor/Visual Studio Code.app/Contents/Resources/app/bin/code
$HOME/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
    else
        candidates="/Applications/Zed.app/Contents/MacOS/cli
/Applications/_editor/Zed.app/Contents/MacOS/cli
$HOME/Applications/Zed.app/Contents/MacOS/cli"
    fi
    while IFS= read -r cand; do
        [ -n "$cand" ] && [ -x "$cand" ] && { printf '%s\n' "$cand"; return 0; }
    done <<EOF
$candidates
EOF

    # 5) fail-loud — 조용한 no-op 금지
    echo "❌ ${ed} CLI 를 찾지 못함. PATH 에 추가하거나 data/editor.yml 의 bin_${ed} 에 절대경로를 지정하세요." >&2
    return 1
}

# --- 열기 어댑터 ---
#   $1 = editor, $2 = mode(open|new|add|wait), 나머지 = paths
#   window_merge: zed=지원(다중 경로 1회 호출 = 한 창 멀티루트) / vscode=AppleScript 병합은 cdfv 가 담당
_fpm_editor_open() {
    local ed="$1" mode="${2:-open}"; shift 2
    local bin; bin=$(_fpm_editor_bin "$ed") || return 1
    [ $# -eq 0 ] && set -- .

    case "$ed" in
        zed)
            case "$mode" in
                new)  "$bin" -n "$@" ;;
                add)  "$bin" -a "$@" ;;
                wait) "$bin" -w "$@" ;;
                *)    "$bin" "$@" ;;
            esac
            ;;
        vscode)
            case "$mode" in
                new)  "$bin" -n "$@" ;;
                add)  "$bin" -a "$@" ;;
                wait) "$bin" -w "$@" ;;
                *)    "$bin" "$@" ;;
            esac
            ;;
    esac
}

# --- 경로 런처 (short_launchers 로 opt-out, 기존 정의 있으면 덮지 않음) ---
_fpm_define_launcher() {
    local name="$1" body="$2"
    # 기존 함수·alias 가 있으면 덮지 않고 경고 (사용자 정의 우선)
    if alias "$name" >/dev/null 2>&1; then
        echo "⚠️  fpm: alias '$name' 이 이미 있어 런처를 정의하지 않음 (alias 제거 후 재로드 권장)" >&2
        return 0
    fi
    eval "$body"
}

if [ "$(_fpm_editor_cfg short_launchers 2>/dev/null || echo true)" != "false" ]; then
    _fpm_define_launcher v  'v()  { _fpm_editor_open vscode open "$@"; }'
    _fpm_define_launcher vn 'vn() { _fpm_editor_open vscode new  "$@"; }'
    _fpm_define_launcher vw 'vw() { _fpm_editor_open vscode wait "$@"; }'
    _fpm_define_launcher z  'z()  { _fpm_editor_open zed open "$@"; }'
    _fpm_define_launcher zn 'zn() { _fpm_editor_open zed new  "$@"; }'
    _fpm_define_launcher za 'za() { _fpm_editor_open zed add   "$@"; }'
    _fpm_define_launcher zw 'zw() { _fpm_editor_open zed wait  "$@"; }'
fi

# --- EDITOR/VISUAL (opt-in) ---
if [ "$(_fpm_editor_cfg set_editor_env 2>/dev/null || echo false)" = "true" ]; then
    _fpm_ed_default=$(_fpm_editor_default)
    _fpm_ed_bin=$(_fpm_editor_bin "$_fpm_ed_default" 2>/dev/null)
    if [ -n "$_fpm_ed_bin" ]; then
        EDITOR="$_fpm_ed_bin -w"; VISUAL="$EDITOR"; export EDITOR VISUAL
    fi
    unset _fpm_ed_default _fpm_ed_bin
fi
