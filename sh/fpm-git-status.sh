#!/usr/bin/env bash
# fpm-git-status.sh — 등록 프로젝트 전체의 git checkout 상태 일람 (읽기 전용)
#
# "지금 각 프로젝트가 어느 브랜치에 체크아웃돼 있고, 작업트리가 깨끗한가"를 한 화면에 모은다.
# 브랜치 전환 사고(딴 브랜치에 커밋)·미커밋 잔여물·중단된 rebase/merge 를 찾는 것이 목적.
#
# 읽기 전용 보장:
#   - 실행하는 git 하위명령은 rev-parse / status --porcelain / rev-list / stash list 뿐 (조회 전용)
#   - git fetch 하지 않음 → ahead/behind 는 **로컬 ref 기준**. 원격 실태와
#     다를 수 있으므로 정확한 비교가 필요하면 사용자가 직접 fetch 후 재실행한다
#   - @host 조회 시에만 ssh 로 나간다. 그때도 원격에서 실행하는 것은 본 스크립트의
#     조회 전용 경로뿐이며, 원격 repo 를 변경하지 않는다 (git fetch 도 하지 않음)
#   - -c core.fsmonitor=false : FUSE·네트워크 마운트 repo 의 인덱스 손상 회피
#     (git-index-integrity-rules — fsmonitor 데몬이 붙지 못하는 마운트에서 인덱스가 깨진 실사례)
#
# 사용:
#   bash sh/fpm-git-status.sh              전체 등록 프로젝트
#   bash sh/fpm-git-status.sh 1 3 11-16    번호·범위 지정
#   bash sh/fpm-git-status.sh 1@fg1 @ma    원격 머신 조회 (번호@host / @host=그 머신 전체)
#   bash sh/fpm-git-status.sh --dirty      변경/이상 있는 프로젝트만
#   bash sh/fpm-git-status.sh --md         markdown 표로 출력 (문서·hub 렌더용)
#   bash sh/fpm-git-status.sh --no-color   ANSI 색 제거
#
# 원격 조회(@host):
#   - 번호→경로 해석은 **그 머신의 인덱스**가 한다. 머신마다 같은 번호가 다른 프로젝트를
#     가리키므로(jm4 prj1=___pm / fg1 prj1=fpm) 로컬 인덱스로 해석하면 엉뚱한 곳을 본다
#   - 원격 스크립트를 찾아 --md 로 실행하고 그 표를 파싱해 한 표로 합친다.
#     원격 스크립트가 구버전이어도 --md 는 원래 지원하므로 하위호환된다
#   - 원격 인자가 하나라도 있으면 출력에 '머신' 열이 붙는다 (없으면 기존과 동일)
#
# 종료코드: 0=조회 성공(이상 유무와 무관) / 1=인덱스 베이스 경로 확정 실패
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# ── 옵션 파싱 ────────────────────────────────────────────────
ONLY_DIRTY=0; AS_MD=0; USE_COLOR=1; ARGS=(); RARGS=()
for a in "$@"; do
    case "$a" in
        --dirty)    ONLY_DIRTY=1 ;;
        --md)       AS_MD=1; USE_COLOR=0 ;;
        --no-color) USE_COLOR=0 ;;
        -h|--help)
            sed -n '2,36p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        all)        ;;                       # 기본값과 동일 — 무시
        *@*)        RARGS+=("$a") ;;         # 번호@host / @host — 원격 조회
        *)          ARGS+=("$a") ;;
    esac
done
HAS_REMOTE=0; [ ${#RARGS[@]} -gt 0 ] && HAS_REMOTE=1
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
#   host ⟂ prj ⟂ 이름 ⟂ 경로 ⟂ 브랜치 ⟂ 원격차이 ⟂ 변경 ⟂ 비고 ⟂ 등급(ok|dirty|warn|skip)
#   host 는 로컬이면 빈 문자열. 등급은 항상 **마지막 필드**라 ${rec##*US} 로 뽑는다
#   구분자는 US(0x1f) — TAB 은 IFS 공백류라 빈 필드(비고 없음)가 뭉개져 컬럼이 한 칸씩 밀린다
inspect() {
    local n="$1" idx="$BASE/$n" path name branch track chg note grade
    name=$(prj_name "$n")

    [ -f "$idx" ] || { printf '\x1f%s\x1f%s\x1f-\x1f-\x1f-\x1f-\x1f%s\x1fskip\n' "$n" "$name" "인덱스 파일 없음"; return; }
    path=$(sed 's#^~#'"$HOME"'#' "$idx" | head -1)
    [ -d "$path" ] || { printf '\x1f%s\x1f%s\x1f%s\x1f-\x1f-\x1f-\x1f%s\x1fskip\n' "$n" "$name" "${path/#$HOME/~}" "경로 부재"; return; }

    local G=(git -c core.fsmonitor=false -C "$path")
    local top
    top=$("${G[@]}" rev-parse --show-toplevel 2>/dev/null) || {
        printf '\x1f%s\x1f%s\x1f%s\x1f-\x1f-\x1f-\x1f%s\x1fskip\n' "$n" "$name" "${path/#$HOME/~}" "git repo 아님"; return; }

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

    printf '\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\n' \
        "$n" "$name" "${path/#$HOME/~}" "$branch" "$track" "$chg" "$note" "$grade"
}

# ── 원격 조회 (@host) ────────────────────────────────────────
#   번호→경로 해석은 **원격 인덱스**가 한다. 로컬 인덱스로 풀면 머신마다 같은 번호가
#   다른 프로젝트를 가리켜 엉뚱한 repo 를 본다(jm4 prj1=___pm / fg1 prj1=fpm).
#   원격에서 본 스크립트를 찾아 --md 로 돌리고, 그 표를 파싱해 레코드로 되돌린다.
#   --md 는 구버전에도 있으므로 원격 스크립트가 낡아도 동작한다(하위호환).
SSH_TIMEOUT="${FPM_GS_SSH_TIMEOUT:-25}"

remote_launcher() {
    # 원격에서 실행할 부트스트랩. 스크립트 위치를 4단계로 탐색한다.
    cat <<'RL'
for c in "${FPM_BASE:-/nonexistent}/sh/fpm-git-status.sh" \
         "$HOME/_git/___pm/sh/fpm-git-status.sh" \
         "$HOME/_git/fpm/sh/fpm-git-status.sh"; do
    [ -f "$c" ] && exec bash "$c" "$@"
done
if [ -f "$HOME/.info/__pmBasePath.txt" ]; then
    __b=$(eval echo "$(cat "$HOME/.info/__pmBasePath.txt")")
    __r="$(dirname "$__b")/sh/fpm-git-status.sh"
    [ -f "$__r" ] && exec bash "$__r" "$@"
fi
echo "__FPM_GS_NO_SCRIPT__" >&2
exit 9
RL
}

# md 표 1행 → 등급 재판정 (원격 출력에는 등급 칸이 없다)
regrade() {
    local branch="$1" chg="$2" note="$3"
    case "$note" in *"git repo 아님"*|*"경로 부재"*|*"인덱스 파일 없음"*) echo skip; return ;; esac
    case "$chg"    in *'!'*) echo warn; return ;; esac
    case "$branch" in detached@*) echo warn; return ;; esac
    case "$note"   in *중단*|*"상위 repo"*) echo warn; return ;; esac
    [ "$chg" = "clean" ] && { echo ok; return; }
    echo dirty
}

collect_remote() {
    local host="$1"; shift
    local out rc line
    out=$(printf '%s' "$(remote_launcher)" \
          | timeout "$SSH_TIMEOUT" ssh -o ConnectTimeout=8 -o BatchMode=yes "$host" \
              "bash -s -- --md --no-color $*" 2>&1)
    rc=$?
    # 성공 판정은 **출력 기준**이다. 원격 스크립트 버전이 제각각이라 rc 에 기대면
    # 표가 멀쩡히 돌아와도 실패로 오독한다(실제로 겪음 — 종료코드 회귀가 fg1 까지
    # 전파된 동안 정상 표를 받고도 'ssh 실패' 행을 냈다). 표 헤더가 오면 성공이다.
    local got_table=0
    printf '%s' "$out" | grep -q '^| prj |' && got_table=1
    if [ $got_table -eq 0 ]; then
        local why="ssh 실패(rc=$rc)"
        printf '%s' "$out" | grep -q '__FPM_GS_NO_SCRIPT__' && why="원격에 fpm-git-status.sh 없음"
        # '@host' 전체 조회는 번호 인자가 없다 — 실패 행의 prj 칸을 비워두지 않는다
        if [ $# -eq 0 ] || [ -z "${1:-}" ]; then
            printf '%s\x1f%s\x1f-\x1f-\x1f-\x1f-\x1f-\x1f%s\x1fskip\n' "$host" "(전체)" "$why"
        else
            for n in "$@"; do
                [ -n "$n" ] || continue
                printf '%s\x1f%s\x1f-\x1f-\x1f-\x1f-\x1f-\x1f%s\x1fskip\n' "$host" "$n" "$why"
            done
        fi
        return
    fi
    # | prj | 이름 | `브랜치` | 원격 | 변경 | 비고 |  → 레코드
    while IFS= read -r line; do
        case "$line" in
            '| prj |'*|'| :--'*|'') continue ;;
            '|'*) ;;
            *) continue ;;
        esac
        local n name branch track chg note grade
        n=$(     printf '%s' "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2}')
        name=$(  printf '%s' "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$3); print $3}')
        branch=$(printf '%s' "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$4); gsub(/`/,"",$4); print $4}')
        track=$( printf '%s' "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$5); print $5}')
        chg=$(   printf '%s' "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$6); print $6}')
        note=$(  printf '%s' "$line" | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$7); print $7}')
        [ -n "$n" ] || continue
        grade=$(regrade "$branch" "$chg" "$note")
        printf '%s\x1f%s\x1f%s\x1f-\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\n' \
            "$host" "$n" "$name" "$branch" "$track" "$chg" "$note" "$grade"
    done <<<"$out"
}

# ── 수집 ─────────────────────────────────────────────────────
ROWS=()
# 로컬 인자가 없고 원격 인자만 있으면 로컬 전체 조회를 하지 않는다
# (그냥 두면 '@fg1' 한 개 물었는데 로컬 43건이 딸려 나온다)
if [ ${#ARGS[@]} -eq 0 ] && [ "$HAS_REMOTE" = 1 ]; then NUMS=(); fi
for n in "${NUMS[@]}"; do
    rec=$(inspect "$n")
    grade="${rec##*$'\x1f'}"
    [ "$ONLY_DIRTY" = 1 ] && [ "$grade" = "ok" ] && continue
    [ "$ONLY_DIRTY" = 1 ] && [ "$grade" = "skip" ] && continue
    ROWS+=("$rec")
done

# 원격: host 별로 번호를 모아 ssh 1회씩만 실행한다 (repo 마다 접속하지 않는다)
if [ "$HAS_REMOTE" = 1 ]; then
    RHOSTS=()
    for spec in "${RARGS[@]}"; do
        h="${spec##*@}"; [ -n "$h" ] || continue
        printf '%s\n' "${RHOSTS[@]:-}" | grep -qx "$h" || RHOSTS+=("$h")
    done
    for h in "${RHOSTS[@]}"; do
        rnums=()
        for spec in "${RARGS[@]}"; do
            [ "${spec##*@}" = "$h" ] || continue
            p="${spec%@*}"
            [ -n "$p" ] || continue                       # '@host' = 그 머신 전체
            if [[ "$p" =~ ^([0-9]+)-([0-9]+)$ ]]; then
                for ((i=${BASH_REMATCH[1]}; i<=${BASH_REMATCH[2]}; i++)); do rnums+=("$i"); done
            else
                rnums+=("$p")
            fi
        done
        while IFS= read -r rec; do
            [ -n "$rec" ] || continue
            grade="${rec##*$'\x1f'}"
            [ "$ONLY_DIRTY" = 1 ] && [ "$grade" = "ok" ] && continue
            [ "$ONLY_DIRTY" = 1 ] && [ "$grade" = "skip" ] && continue
            ROWS+=("$rec")
        done < <(collect_remote "$h" "${rnums[@]:-}")
    done
fi

# ── 출력 ─────────────────────────────────────────────────────
MCOL=""; [ "$HAS_REMOTE" = 1 ] && MCOL="yes"   # 원격 인자 있을 때만 머신 열
if [ "$AS_MD" = 1 ]; then
    if [ -n "$MCOL" ]; then
        echo "| 머신 | prj | 이름 | 브랜치 | 원격 | 변경 | 비고 |"
        echo "| :--- | :-- | :--- | :----- | :--- | :--- | :--- |"
    else
        echo "| prj | 이름 | 브랜치 | 원격 | 변경 | 비고 |"
        echo "| :-- | :--- | :----- | :--- | :--- | :--- |"
    fi
    for r in "${ROWS[@]}"; do
        IFS=$'\x1f' read -r host n name path branch track chg note grade <<<"$r"
        if [ -n "$MCOL" ]; then
            echo "| ${host:-local} | $n | $name | \`$branch\` | $track | $chg | ${note:-} |"
        else
            echo "| $n | $name | \`$branch\` | $track | $chg | ${note:-} |"
        fi
    done
else
    # bash printf 의 %-Ns 는 **바이트** 기준 패딩이다. 한글 1자 = 3바이트/표시폭 2 이므로
    # 표시폭 W 를 맞추려면 폭 인자를 W + (한글 글자수) 로 준다 (이름 18+2 · 브랜치 26+3 · …)
    if [ -n "$MCOL" ]; then
        printf '%s%-8s %-4s %-20s %-29s %-14s %-11s %s%s\n' "$C_DIM" "머신" "prj" "이름" "브랜치" "원격" "변경" "비고" "$C_RST"
    else
        printf '%s%-4s %-20s %-29s %-14s %-11s %s%s\n' "$C_DIM" "prj" "이름" "브랜치" "원격" "변경" "비고" "$C_RST"
    fi
    for r in "${ROWS[@]}"; do
        IFS=$'\x1f' read -r host n name path branch track chg note grade <<<"$r"
        case "$grade" in
            ok)    col="$C_GRN" ;;
            dirty) col="$C_YEL" ;;
            warn)  col="$C_RED" ;;
            *)     col="$C_DIM" ;;
        esac
        if [ -n "$MCOL" ]; then
            printf '%s%-8s %-4s %-18s %s%-26s%s %-12s %-9s %s%s\n' \
                "$col" "${host:-local}" "$n" "$name" "$C_CYA" "$branch" "$col" "$track" "$chg" "${note:-}" "$C_RST"
        else
            printf '%s%-4s %-18s %s%-26s%s %-12s %-9s %s%s\n' \
                "$col" "$n" "$name" "$C_CYA" "$branch" "$col" "$track" "$chg" "${note:-}" "$C_RST"
        fi
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
if [ "$HAS_REMOTE" = 1 ]; then
    printf '%s\n' "@host 행의 번호는 **그 머신의 인덱스** 기준이다 (같은 번호라도 머신마다 다른 프로젝트일 수 있음)"
fi

# 조회는 이상 유무와 무관하게 0 으로 끝난다(헤더 "종료코드" 계약).
# ⚠️ 마지막 명령을 `[ ... ] && printf` 로 두면 조건이 false 일 때 그 실패가 스크립트
#    종료코드가 되어 rc=1 로 나간다 — 원격 조회(@host)가 이를 ssh 실패로 오독했다.
exit 0
