#!/usr/bin/env bash
# fpm-git-status.sh — 등록 프로젝트 전체의 git checkout 상태 일람 (읽기 전용)
#
# "지금 각 프로젝트가 어느 브랜치에 체크아웃돼 있고, 작업트리가 깨끗한가"를 한 화면에 모은다.
# 브랜치 전환 사고(딴 브랜치에 커밋)·미커밋 잔여물·중단된 rebase/merge 를 찾는 것이 목적.
#
# 읽기 전용 보장:
#   - 실행하는 git 하위명령은 rev-parse / status --porcelain / rev-list / stash list 뿐 (조회 전용)
#   - 네트워크 접근 없음 (fetch 하지 않음) → ahead/behind 는 **로컬 ref 기준**. 원격 실태와
#     다를 수 있으므로 정확한 비교가 필요하면 사용자가 직접 fetch 후 재실행한다
#   - -c core.fsmonitor=false : FUSE·네트워크 마운트 repo 의 인덱스 손상 회피
#     (git-index-integrity-rules — fsmonitor 데몬이 붙지 못하는 마운트에서 인덱스가 깨진 실사례)
#
# 사용:
#   bash sh/fpm-git-status.sh              전체 등록 프로젝트
#   bash sh/fpm-git-status.sh 1 3 11-16    번호·범위 지정
#   bash sh/fpm-git-status.sh --dirty      변경/이상 있는 프로젝트만
#   bash sh/fpm-git-status.sh --md         markdown 표로 출력 (문서·hub 렌더용)
#   bash sh/fpm-git-status.sh --no-color   ANSI 색 제거
#
# 종료코드: 0=조회 성공(이상 유무와 무관) / 1=인덱스 베이스 경로 확정 실패
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# ── 옵션 파싱 ────────────────────────────────────────────────
ONLY_DIRTY=0; AS_MD=0; USE_COLOR=1; ARGS=()
for a in "$@"; do
    case "$a" in
        --dirty)    ONLY_DIRTY=1 ;;
        --md)       AS_MD=1; USE_COLOR=0 ;;
        --no-color) USE_COLOR=0 ;;
        -h|--help)
            sed -n '2,26p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        all)        ;;                       # 기본값과 동일 — 무시
        *)          ARGS+=("$a") ;;
    esac
done
[ -t 1 ] || USE_COLOR=0                      # 파이프·리다이렉트면 색 끔

if [ "$USE_COLOR" = 1 ]; then
    C_RST=$'\033[0m'; C_DIM=$'\033[2m'; C_GRN=$'\033[32m'
    C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_CYA=$'\033[36m'
else
    C_RST=""; C_DIM=""; C_GRN=""; C_YEL=""; C_RED=""; C_CYA=""
fi

# ── 인덱스 베이스 확정 ($FPM_BASE 우선 → 자기 repo → legacy) ──
if [ -n "${FPM_BASE:-}" ] && [ -d "$FPM_BASE/projects" ]; then
    BASE="$FPM_BASE/projects"; SSOT="$FPM_BASE/Projects.md"
elif [ -d "$REPO_DIR/projects" ]; then
    BASE="$REPO_DIR/projects"; SSOT="$REPO_DIR/Projects.md"
elif [ -f "$HOME/.info/__pmBasePath.txt" ]; then
    BASE=$(eval echo "$(cat "$HOME/.info/__pmBasePath.txt")"); SSOT="$(dirname "$BASE")/Projects.md"
else
    printf '%s\n' "⛔ 인덱스 경로 확정 실패 — FPM_BASE 미설정 + projects/ 부재" >&2; exit 1
fi

# ── 대상 번호 결정 (인자 없으면 전체, 'a-b' 범위 전개) ────────
NUMS=()
if [ ${#ARGS[@]} -eq 0 ]; then
    while IFS= read -r n; do NUMS+=("$n"); done < <(
        find "$BASE" -maxdepth 1 -type f -name '[0-9]*' -exec basename {} \; \
            | grep -E '^[0-9]+$' | sort -n)
else
    for a in "${ARGS[@]}"; do
        if [[ "$a" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            for ((i=${BASH_REMATCH[1]}; i<=${BASH_REMATCH[2]}; i++)); do NUMS+=("$i"); done
        else
            NUMS+=("$a")
        fi
    done
fi

# ── Projects.md 에서 프로젝트명 조회 (없으면 경로 basename) ───
prj_name() {
    local n="$1" nm=""
    [ -f "$SSOT" ] && nm=$(awk -F'|' -v n="$n" '
        { gsub(/^[ \t]+|[ \t]+$/, "", $2); gsub(/^[ \t]+|[ \t]+$/, "", $3)
          if ($2 == n) { print $3; exit } }' "$SSOT")
    printf '%s' "$nm"
}

# ── 프로젝트 1건 조사 → TAB 구분 레코드 출력 ─────────────────
#   prj ⟂ 이름 ⟂ 경로 ⟂ 브랜치 ⟂ 원격차이 ⟂ 변경 ⟂ 비고 ⟂ 등급(ok|dirty|warn|skip)
#   구분자는 US(0x1f) — TAB 은 IFS 공백류라 빈 필드(비고 없음)가 뭉개져 컬럼이 한 칸씩 밀린다
inspect() {
    local n="$1" idx="$BASE/$n" path name branch track chg note grade
    name=$(prj_name "$n")

    [ -f "$idx" ] || { printf '%s\x1f%s\x1f-\x1f-\x1f-\x1f-\x1f%s\x1fskip\n' "$n" "$name" "인덱스 파일 없음"; return; }
    path=$(sed 's#^~#'"$HOME"'#' "$idx" | head -1)
    [ -d "$path" ] || { printf '%s\x1f%s\x1f%s\x1f-\x1f-\x1f-\x1f%s\x1fskip\n' "$n" "$name" "${path/#$HOME/~}" "경로 부재"; return; }

    local G=(git -c core.fsmonitor=false -C "$path")
    local top
    top=$("${G[@]}" rev-parse --show-toplevel 2>/dev/null) || {
        printf '%s\x1f%s\x1f%s\x1f-\x1f-\x1f-\x1f%s\x1fskip\n' "$n" "$name" "${path/#$HOME/~}" "git repo 아님"; return; }

    note=""; grade="ok"

    # 프로젝트 경로가 repo 루트가 아니면(상위 repo 안의 하위 폴더) 그 사실을 표기 —
    # 이 경우 status/브랜치는 **상위 repo 전체**의 것이라 오해를 부르기 쉽다.
    if [ "$(cd "$path" && pwd -P)" != "$(cd "$top" && pwd -P)" ]; then
        note="상위 repo=${top/#$HOME/~}"; grade="warn"
    fi

    # 브랜치 (detached 면 짧은 해시 병기)
    branch=$("${G[@]}" symbolic-ref --quiet --short HEAD 2>/dev/null) || {
        branch="detached@$("${G[@]}" rev-parse --short HEAD 2>/dev/null)"; grade="warn"; }

    # 진행 중인 작업(중단된 rebase/merge/cherry-pick/bisect)이 있으면 최우선 경고
    local gdir st=""
    gdir=$("${G[@]}" rev-parse --git-dir 2>/dev/null)
    case "$gdir" in /*) ;; *) gdir="$path/$gdir" ;; esac
    [ -d "$gdir/rebase-merge" ] || [ -d "$gdir/rebase-apply" ] && st="rebase 중단"
    [ -f "$gdir/MERGE_HEAD" ]      && st="${st:+$st, }merge 중단"
    [ -f "$gdir/CHERRY_PICK_HEAD" ] && st="${st:+$st, }cherry-pick 중단"
    [ -f "$gdir/BISECT_LOG" ]      && st="${st:+$st, }bisect 중"
    if [ -n "$st" ]; then note="${note:+$note · }$st"; grade="warn"; fi

    # upstream 대비 ahead/behind (로컬 ref 기준, fetch 안 함)
    local lr
    if lr=$("${G[@]}" rev-list --left-right --count '@{u}...HEAD' 2>/dev/null); then
        # 출력은 "<behind>\t<ahead>" (left=upstream 전용, right=HEAD 전용)
        local behind ahead
        behind=$(printf '%s' "$lr" | awk '{print $1+0}')
        ahead=$(printf '%s' "$lr" | awk '{print $2+0}')
        track=""
        # ^=ahead v=behind (ASCII 고정 — 정렬 컬럼에 다국어 기호를 넣지 않는다)
        [ "$ahead"  -gt 0 ] && track="^$ahead"
        [ "$behind" -gt 0 ] && track="${track:+$track }v$behind"
        [ -n "$track" ] || track="="
    else
        track="no-upstream"
    fi

    # 작업트리 변경 집계 (staged / unstaged / untracked / conflict)
    local s=0 u=0 q=0 c=0 line x y
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        x="${line:0:1}"; y="${line:1:1}"
        if [ "$x$y" = "??" ]; then q=$((q+1)); continue; fi
        case "$x$y" in *U*|DD|AA) c=$((c+1)); continue ;; esac
        case "$x" in ' '|'?') ;; *) s=$((s+1)) ;; esac
        case "$y" in ' '|'?') ;; *) u=$((u+1)) ;; esac
    done < <("${G[@]}" status --porcelain 2>/dev/null)

    chg=""
    [ "$c" -gt 0 ] && chg="!$c"      # ! = 충돌(conflict)
    [ "$s" -gt 0 ] && chg="${chg:+$chg }+$s"
    [ "$u" -gt 0 ] && chg="${chg:+$chg }~$u"
    [ "$q" -gt 0 ] && chg="${chg:+$chg }?$q"
    if [ -z "$chg" ]; then chg="clean"; else
        [ "$grade" = ok ] && grade=dirty
        [ "$c" -gt 0 ] && grade=warn
    fi

    local stash
    stash=$("${G[@]}" stash list 2>/dev/null | wc -l | tr -d ' ')
    [ "${stash:-0}" -gt 0 ] && note="${note:+$note · }stash $stash"

    printf '%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\n' \
        "$n" "$name" "${path/#$HOME/~}" "$branch" "$track" "$chg" "$note" "$grade"
}

# ── 수집 ─────────────────────────────────────────────────────
ROWS=()
for n in "${NUMS[@]}"; do
    rec=$(inspect "$n")
    grade="${rec##*$'\x1f'}"
    [ "$ONLY_DIRTY" = 1 ] && [ "$grade" = "ok" ] && continue
    [ "$ONLY_DIRTY" = 1 ] && [ "$grade" = "skip" ] && continue
    ROWS+=("$rec")
done

# ── 출력 ─────────────────────────────────────────────────────
if [ "$AS_MD" = 1 ]; then
    echo "| prj | 이름 | 브랜치 | 원격 | 변경 | 비고 |"
    echo "| :-- | :--- | :----- | :--- | :--- | :--- |"
    for r in "${ROWS[@]}"; do
        IFS=$'\x1f' read -r n name path branch track chg note grade <<<"$r"
        echo "| $n | $name | \`$branch\` | $track | $chg | ${note:-} |"
    done
else
    # bash printf 의 %-Ns 는 **바이트** 기준 패딩이다. 한글 1자 = 3바이트/표시폭 2 이므로
    # 표시폭 W 를 맞추려면 폭 인자를 W + (한글 글자수) 로 준다 (이름 18+2 · 브랜치 26+3 · …)
    printf '%s%-4s %-20s %-29s %-14s %-11s %s%s\n' "$C_DIM" "prj" "이름" "브랜치" "원격" "변경" "비고" "$C_RST"
    for r in "${ROWS[@]}"; do
        IFS=$'\x1f' read -r n name path branch track chg note grade <<<"$r"
        case "$grade" in
            ok)    col="$C_GRN" ;;
            dirty) col="$C_YEL" ;;
            warn)  col="$C_RED" ;;
            *)     col="$C_DIM" ;;
        esac
        printf '%s%-4s %-18s %s%-26s%s %-12s %-9s %s%s\n' \
            "$col" "$n" "$name" "$C_CYA" "$branch" "$col" "$track" "$chg" "${note:-}" "$C_RST"
    done
fi

# ── 요약 ─────────────────────────────────────────────────────
tot=${#ROWS[@]}; n_ok=0; n_dirty=0; n_warn=0; n_skip=0
for r in "${ROWS[@]}"; do
    case "${r##*$'\x1f'}" in
        ok) n_ok=$((n_ok+1)) ;; dirty) n_dirty=$((n_dirty+1)) ;;
        warn) n_warn=$((n_warn+1)) ;; *) n_skip=$((n_skip+1)) ;;
    esac
done
echo
printf '%s\n' "총 ${tot}건 · ✅ clean ${n_ok} · ✏️ 변경 ${n_dirty} · ⚠️ 주의 ${n_warn} · — 제외 ${n_skip}"
printf '%s\n' "변경 표기: +staged ~unstaged ?untracked !충돌 · 원격: ^ahead v behind (fetch 안 함 — 로컬 ref 기준)"
