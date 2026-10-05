#!/usr/bin/env bash
# fpm-claude-bin.sh — claude CLI 해석 SSOT (Issue564)
#
# 왜 필요한가 (2026-09-28 jma 네이티브 실측 — prj3#Issue467 의 재발):
#   공식 네이티브 설치 경로는 `~/.local/bin/claude` 다. 대화 셸은 rc 가 PATH 에 넣어 주므로
#   보이지만, **SSH 비대화·cron·원격 실행** 의 PATH 에는 없다. `command -v` 하나로 판정하면
#   그때 «셸-only 사용자» 로 오판해 SCAR·MCP 배선을 건너뛰고 성공을 보고한다.
#   update.sh 만 관례 경로를 훑도록 고쳐졌고(prj3#Issue467), install·uninstall·check·
#   fpm update·publish-scar·TDD 케이스는 판정이 갈라진 채였다 — 그래서 한 곳으로 모은다.
#
# 계약
#   후보 순서  PATH → ~/.local/bin → ~/.claude/local → /opt/homebrew/bin → /usr/local/bin
#              → /usr/bin → ~/.nvm/versions/node/v*/bin (버전 최신)
#   채택 기준  실행 가능(-x)한 첫 후보
#   부작용     PATH 밖에서 찾으면 그 디렉토리를 PATH **앞에** 붙인다(export). 호출부의 기존
#              `claude …` 가 그대로 통하게 하려는 것이다. 대화 셸 PATH 를 건드리면 안 되는
#              곳(sh/fpm_function.sh)은 CLI 모드를 쓴다
#   FPM_CLAUDE_PATH_ONLY=1  PATH 만 본다 — «claude 부재» 시나리오 검증용(release-check A-1)
#
# 사용 (bash 전용 — zsh 에서 source 하지 말 것)
#   source "$REPO_DIR/sh/fpm-claude-bin.sh"
#   if fpm_resolve_claude; then claude plugin list; fi      # 또는 "$FPM_CLAUDE_BIN"
#   bash sh/fpm-claude-bin.sh   → 경로 1줄 · rc 0 / 전멸 시 무출력 · rc 1 (호출한 셸 PATH 무변경)
#
# 출력 (전역)  FPM_CLAUDE_BIN — 채택 경로(전멸 시 빈 값) · rc 0 채택 / 1 전멸
#
# shellcheck disable=SC2034  # FPM_CLAUDE_BIN 은 source 한 쪽이 읽는 출력 변수다

# $1 > $2 (점 구분 숫자 버전)
_fpm_claude_ver_gt() {
    local IFS=. i
    local -a a b
    read -r -a a <<<"$1"; read -r -a b <<<"$2"
    for i in 0 1 2; do
        [ "${a[i]:-0}" -gt "${b[i]:-0}" ] 2>/dev/null && return 0
        [ "${a[i]:-0}" -lt "${b[i]:-0}" ] 2>/dev/null && return 1
    done
    return 1
}

# nvm 설치본 중 버전이 가장 높은 claude — 글롭 정렬은 v18 < v9 처럼 틀린다
_fpm_claude_nvm_latest() {
    local d v best="" bestv=""
    for d in "$HOME"/.nvm/versions/node/v*/bin/claude; do
        [ -f "$d" ] && [ -x "$d" ] || continue
        v="${d#"$HOME"/.nvm/versions/node/v}"; v="${v%%/*}"
        if [ -z "$best" ] || _fpm_claude_ver_gt "$v" "$bestv"; then best="$d"; bestv="$v"; fi
    done
    printf '%s' "$best"
}

fpm_resolve_claude() {
    FPM_CLAUDE_BIN=""
    local c
    c="$(command -v claude 2>/dev/null || true)"
    # alias·함수 이름이 돌아오면 -x 에서 걸러진다 — 실행 파일만 채택
    if [ -n "$c" ] && [ -f "$c" ] && [ -x "$c" ]; then FPM_CLAUDE_BIN="$c"; return 0; fi
    [ "${FPM_CLAUDE_PATH_ONLY:-0}" = 1 ] && return 1
    local -a cands=("$HOME/.local/bin/claude" "$HOME/.claude/local/claude"
                    /opt/homebrew/bin/claude /usr/local/bin/claude /usr/bin/claude)
    c="$(_fpm_claude_nvm_latest)"; [ -n "$c" ] && cands+=("$c")
    for c in "${cands[@]}"; do
        [ -f "$c" ] && [ -x "$c" ] || continue
        FPM_CLAUDE_BIN="$c"
        case ":$PATH:" in
            *":$(dirname "$c"):"*) ;;
            *) PATH="$(dirname "$c"):$PATH"; export PATH ;;
        esac
        return 0
    done
    return 1
}

# CLI 모드 — 실행됐을 때만. zsh 에서 source 되면 BASH_SOURCE 가 없어 $0 과 같아 보이므로 배제한다
if [ -z "${ZSH_VERSION:-}" ] && [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
    fpm_resolve_claude || exit 1
    printf '%s\n' "$FPM_CLAUDE_BIN"
fi
