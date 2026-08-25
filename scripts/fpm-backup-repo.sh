#!/usr/bin/env bash
# fpm-backup-repo.sh — repo 무관 오프사이트 백업(추적분) 미러 (Issue386)
#
# `___pm`(prj1)·`~/.claude`(prj3) 등 **remote 가 없는 로컬 단일 사본 repo** 를
# fg1 bare mirror 로 밀어 넣고, **밀렸는지까지 검증**한다.
#
# 왜 신선도 검증이 핵심인가 (Issue386 실측):
#   fg1:/home/nowage/_git/_backup/___pm.git 은 **존재했지만** 로컬에 remote 가 등록돼
#   있지 않아 아무도 push 하지 않았고, main tip 이 16일 뒤처진 채 방치돼 있었다.
#   "백업이 있다"는 사실은 "백업이 최신이다"를 보장하지 않는다 — 그래서 본 스크립트는
#   push 여부와 무관하게 **항상 로컬↔원격 tip 을 대조하고 불일치를 non-zero 로 보고**한다.
#
# 사용: fpm-backup-repo.sh <repo-path> [--host fg1] [--base <원격 베이스>]
#                          [--remote <이름>] [--push] [--no-scan]
#   (기본은 **읽기 전용 점검**) 스캔 + 신선도 대조만. 쓰기는 --push 명시 시에만.
#   --push     원격 bare 보장(없으면 init) → remote 등록(없으면) → 전 브랜치·태그 push
#   --no-scan  gitleaks 이력 스캔 생략 (gitleaks 미설치 환경)
# exit: 0=최신·clean, 1=stale/미백업 또는 시크릿 검출, 2=사용법·환경 오류(fail-loud)
#
# ⚠️ push 는 원격 쓰기다. 위임 세션·비대화 실행에서는 --push 를 자동으로 붙이지 않는다.
# ⚠️ 삭제 전파(--mirror/--prune)는 쓰지 않는다 — 로컬 실수 삭제가 백업까지 지우면
#    백업이 아니라 복제다. 원격 orphan ref 정리는 사람이 판단한다.
set -uo pipefail

HOST="fg1"
BASE="/home/nowage/_git/_backup"
REMOTE=""
PUSH=0
SCAN=1
REPO=""

while [ $# -gt 0 ]; do
    case "$1" in
        --host)   HOST="${2:?--host 인자 필요}"; shift 2 ;;
        --base)   BASE="${2:?--base 인자 필요}"; shift 2 ;;
        --remote) REMOTE="${2:?--remote 인자 필요}"; shift 2 ;;
        --push)   PUSH=1; shift ;;
        --no-scan) SCAN=0; shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        -*) echo "🚨 알 수 없는 인자: $1" >&2; exit 2 ;;
        *)  [ -n "$REPO" ] && { echo "🚨 repo 는 하나만" >&2; exit 2; }; REPO="$1"; shift ;;
    esac
done

[ -n "$REPO" ] || { echo "🚨 사용법: $0 <repo-path> [--push]" >&2; exit 2; }
REPO="$(cd "$REPO" 2>/dev/null && pwd)" || { echo "🚨 경로 없음: $REPO" >&2; exit 2; }
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || { echo "🚨 git repo 아님: $REPO" >&2; exit 2; }

NAME="$(basename "$REPO")"
[ -n "$REMOTE" ] || REMOTE="$HOST"
URL="$HOST:$BASE/$NAME.git"

info() { printf '\033[36m[backup]\033[0m %s\n' "$1"; }
warn() { printf '\033[33m[backup]\033[0m %s\n' "$1"; }
err()  { printf '\033[31m[backup]\033[0m %s\n' "$1" >&2; }

info "repo=$REPO  →  $URL  (push=$PUSH)"

# ── 1. 이력 시크릿 스캔 ────────────────────────────────────────────────────
# private remote 라도 자격증명은 원격 디스크에 평문 복제된다. 유출 시 답은 회수가
# 아니라 **회전**이므로, 스캔은 "유출 차단"이 아니라 **회전 트리거**로 값어치가 있다.
if [ "$SCAN" = 1 ]; then
    if command -v gitleaks >/dev/null 2>&1; then
        CFG=""
        [ -f "$REPO/.gitleaks.toml" ] && CFG="$REPO/.gitleaks.toml"
        RPT="$(mktemp)"; trap 'rm -f "$RPT"' EXIT
        rc=0
        if [ -n "$CFG" ]; then
            gitleaks git "$REPO" --config "$CFG" --no-banner --redact \
                --report-format json --report-path "$RPT" >/dev/null 2>&1 || rc=$?
        else
            gitleaks git "$REPO" --no-banner --redact \
                --report-format json --report-path "$RPT" >/dev/null 2>&1 || rc=$?
        fi
        if [ "$rc" -ne 0 ]; then
            n=0
            command -v jq >/dev/null 2>&1 && [ -s "$RPT" ] && n="$(jq 'length' "$RPT" 2>/dev/null || echo 0)"
            if [ "${n:-0}" -gt 0 ]; then
                err "🚨 이력 시크릿 $n 건 — 백업 전 **자격증명 회전**부터 (원격 복제 시 회수 불가):"
                jq -r '.[] | "  \(.File):\(.StartLine) [\(.RuleID)]"' "$RPT" >&2 2>/dev/null || true
                exit 1
            fi
            warn "gitleaks 실행 오류(rc=$rc, findings 0) — 스캔 미수행으로 간주"
        else
            info "gitleaks 이력 스캔 clean"
        fi
    else
        warn "gitleaks 미설치 — 이력 스캔 생략 (brew install gitleaks 권장)"
    fi
fi

# ── 2. 원격 bare 보장 + remote 등록 (--push 에서만 쓰기) ───────────────────
if [ "$PUSH" = 1 ]; then
    ssh -o BatchMode=yes "$HOST" "test -d '$BASE/$NAME.git' || { mkdir -p '$BASE' && git init --bare -q '$BASE/$NAME.git'; }" \
        || { err "🚨 원격 bare 보장 실패: $URL"; exit 2; }
    if git -C "$REPO" remote get-url "$REMOTE" >/dev/null 2>&1; then
        cur="$(git -C "$REPO" remote get-url "$REMOTE")"
        [ "$cur" = "$URL" ] || warn "remote '$REMOTE' URL 상이: $cur (요청: $URL) — 기존 유지"
    else
        git -C "$REPO" remote add "$REMOTE" "$URL" || { err "🚨 remote 등록 실패"; exit 2; }
        info "remote '$REMOTE' 등록: $URL"
    fi
    # 삭제 전파 없음 (--mirror 금지). 전 브랜치 + 태그만 전진.
    # ⚠️ `--all --tags` 는 **함께 못 쓴다** — git 이 `fatal: options '--tags' and
    #    '--all/--branches' cannot be used together` 로 거부한다(Issue396, git 2.50 실측).
    #    반드시 2회로 분리한다. 합치면 push 가 통째로 실패해 백업이 안 된다.
    git -C "$REPO" push "$REMOTE" --all  || { err "🚨 브랜치 push 실패"; exit 1; }
    git -C "$REPO" push "$REMOTE" --tags || { err "🚨 태그 push 실패"; exit 1; }
    info "push 완료 (전 브랜치 + 태그, 삭제 전파 없음)"
fi

# ── 3. 신선도 검증 — 로컬 브랜치 tip 이 원격에 실제로 있는가 ───────────────
LS="$(git -C "$REPO" ls-remote --heads "$URL" 2>/dev/null)" || {
    err "🚨 원격 조회 실패 — 백업 미존재·접속 불가: $URL"; exit 1; }

stale=0
while read -r sha ref; do
    [ -n "$ref" ] || continue
    rsha="$(printf '%s\n' "$LS" | awk -v r="refs/heads/$ref" '$2==r{print $1}')"
    if [ -z "$rsha" ]; then
        err "❌ $ref — 원격에 **없음** (미백업)"; stale=1
    elif [ "$rsha" != "$sha" ]; then
        d="$(git -C "$REPO" rev-list --count "$rsha..$sha" 2>/dev/null || echo '?')"
        err "❌ $ref — 원격 tip 뒤처짐 (로컬이 $d 커밋 앞섬)"; stale=1
    else
        info "✅ $ref — 최신"
    fi
done < <(git -C "$REPO" for-each-ref --format='%(objectname) %(refname:short)' refs/heads)

if [ "$stale" = 1 ]; then
    err "백업이 최신이 아니다 — '$0 $REPO --push' 로 갱신 (원격 쓰기, 승인 후)"
    exit 1
fi
info "전 브랜치 백업 최신"
exit 0
