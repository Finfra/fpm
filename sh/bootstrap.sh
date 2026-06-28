#!/usr/bin/env sh
# bootstrap.sh — fpm 원격 원라인 설치 진입점 (Issue224 T1)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 스크립트는 공개 미러(prj7) 동기 페이로드.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   설계 SSOT: ~/_git/___pm/_doc_arch/fpm-competitive-benchmark.md (강화 로드맵 Phase0 T1).
#   절차: ~/.claude/rules/global-scar-change-rules.md
#
# 용도: repo 를 먼저 클론하지 않고도 한 줄로 fpm 을 설치한다.
#   [공개 repo]  curl -fsSL https://raw.githubusercontent.com/Finfra/fpm/main/sh/bootstrap.sh | sh
#   [비공개 repo] gh api -H "Accept: application/vnd.github.raw" \
#                   repos/Finfra/fpm/contents/sh/bootstrap.sh | sh
#                 (gh CLI 인증 필요. 본 스크립트가 gh auth setup-git 으로 clone/pull 자동 인증)
#
# 동작:
#   1. 의존성 확인 (git)
#   2. 설치 위치 결정: $FPM_DIR (override) > $HOME/.fpm (기본)
#   3. 위치에 이미 fpm git repo 존재 → git pull, 없으면 git clone
#   4. 클론된 repo 의 sh/install.sh 로 위임 (셸 부트스트랩 + SCAR 설치, 멱등)
#
# 환경변수:
#   FPM_DIR     설치 디렉토리 (기본 $HOME/.fpm)
#   FPM_REPO    원격 git URL (기본 https://github.com/Finfra/fpm.git)
#   FPM_REF     체크아웃할 브랜치/태그 (기본 main)
# 인자: install.sh 로 그대로 전달 (--no-scar / --clean / --local 등)
#
# POSIX sh 호환 (curl|sh 파이프는 사용자 셸 불문 /bin/sh 로 실행될 수 있음).
set -eu

FPM_REPO="${FPM_REPO:-https://github.com/Finfra/fpm.git}"
FPM_REF="${FPM_REF:-main}"
FPM_DIR="${FPM_DIR:-$HOME/.fpm}"

info() { printf '\033[36m[fpm]\033[0m %s\n' "$1"; }
warn() { printf '\033[33m[fpm]\033[0m %s\n' "$1"; }
err()  { printf '\033[31m[fpm]\033[0m %s\n' "$1" >&2; }

# ── 1. 의존성 ───────────────────────────────────────────────
if ! command -v git >/dev/null 2>&1; then
    err "git 미발견 — git 설치 후 재실행 (macOS: xcode-select --install)"
    exit 1
fi

# ── 1b. private repo 대비: gh 인증 git 자격증명 셋업 (Issue224) ──
#   FPM_REPO 가 비공개면 익명 https clone 이 실패한다. gh CLI 가 인증돼 있으면
#   git credential helper 를 구성해(https 자동 인증) clone/pull 양쪽이 동작한다.
#   gh 없거나 미인증이면 무시(공개 repo·SSH·기존 자격증명 경로 그대로).
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh auth setup-git >/dev/null 2>&1; then
        info "gh 인증 git 자격증명 구성 — 비공개 repo clone/pull 가능"
    else
        warn "gh auth setup-git 실패 — 공개 repo 또는 별도 자격증명 필요"
    fi
fi

# ── 2~3. 설치 위치 확보 (clone 또는 pull, 멱등) ──────────────
if [ -d "$FPM_DIR/.git" ]; then
    info "기존 설치 발견: $FPM_DIR → 갱신(git pull)"
    git -C "$FPM_DIR" fetch --quiet origin "$FPM_REF"
    # 로컬 미커밋 변경 보호 — dirty 면 pull 생략하고 현 상태로 install 위임
    if [ -n "$(git -C "$FPM_DIR" status --porcelain)" ]; then
        warn "로컬 변경 감지 — git pull 생략(기존 상태 유지). 갱신하려면 직접 stash/commit 후 'fpm update'"
    else
        git -C "$FPM_DIR" checkout --quiet "$FPM_REF"
        git -C "$FPM_DIR" merge --ff-only --quiet "origin/$FPM_REF" 2>/dev/null || \
            warn "fast-forward 불가 — 수동 확인 필요"
    fi
elif [ -e "$FPM_DIR" ]; then
    err "$FPM_DIR 가 이미 존재하나 git repo 아님 — FPM_DIR 로 다른 경로 지정 또는 해당 폴더 정리 후 재실행"
    exit 1
else
    info "fpm 클론: $FPM_REPO → $FPM_DIR (ref=$FPM_REF)"
    git clone --quiet --branch "$FPM_REF" --depth 1 "$FPM_REPO" "$FPM_DIR"
fi

# ── 4. install.sh 위임 ──────────────────────────────────────
INSTALL="$FPM_DIR/sh/install.sh"
if [ ! -f "$INSTALL" ]; then
    err "install.sh 없음: $INSTALL — repo 손상? 재클론 위해 '$FPM_DIR' 제거 후 재실행"
    exit 1
fi
info "설치 위임 → $INSTALL"
exec bash "$INSTALL" "$@"
