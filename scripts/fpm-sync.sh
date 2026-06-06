#!/usr/bin/env bash
# fpm-sync.sh — ___pm(prj1) publishable → fpm(prj7) 단방향 동기화 엔진
#
# fpm-sync 에이전트(.claude/agents/fpm-sync.md)와 post-commit hook 의 공통 sync 로직 SSOT.
# 호출: scripts/fpm-sync.sh           (자동/수동 동일)
# 환경변수 override: FPM_SRC, FPM_DST
#
# 불변식:
#   - 단방향(___pm → fpm). ___pm 은 읽기 전용.
#   - 개인정보(untracked/gitignored)는 tracked export 라 자동 제외 + rsync exclude 2차 가드.
#   - push 안 함(커밋까지만). fpm repo 없으면 조용히 종료(다른 머신 대비).
set -euo pipefail

SRC="${FPM_SRC:-$HOME/_git/___pm}"
DST="${FPM_DST:-$HOME/_git/__all/fpm}"
LOG_DIR="$SRC/_doc_work/z_log"
LOG="$LOG_DIR/fpm-sync.log"

log() { mkdir -p "$LOG_DIR" 2>/dev/null || true; printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG" 2>/dev/null || true; printf '[fpm-sync] %s\n' "$1"; }

# fpm repo 미존재 → 조용히 종료 (다른 머신·미설치)
[ -d "$DST/.git" ] || { log "fpm repo 없음 ($DST) — skip"; exit 0; }
[ -d "$SRC/.git" ] || { log "src repo 없음 ($SRC) — skip"; exit 0; }

# 동시 실행 방지 (macOS flock 부재 → mkdir 원자적 락)
LOCKDIR="$SRC/.git/fpm-sync.lock.d"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    # 10분 이상 묵은 락이면 강제 해제 (죽은 프로세스 잔존 대비)
    if [ -d "$LOCKDIR" ] && [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
        rmdir "$LOCKDIR" 2>/dev/null || true
        mkdir "$LOCKDIR" 2>/dev/null || { log "락 획득 실패 — skip"; exit 0; }
    else
        log "다른 sync 실행 중 — skip"; exit 0
    fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

# 개인정보 tracked 가드 (1차)
if git -C "$SRC" ls-files | grep -iqE 'Servers\.md$|^Projects\.md$|finfra-server-access|fapp-projects'; then
    log "🚨 개인정보가 ___pm tracked 에 존재 — 중단 (gitignore+rm --cached 필요)"; exit 1
fi

# tracked 스냅샷 export → fpm working tree 정렬
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"; rmdir "$LOCKDIR" 2>/dev/null || true' EXIT
git -C "$SRC" archive HEAD | tar -x -C "$TMP"
rsync -a --delete \
    --exclude='.git/' --exclude='projects/' \
    --exclude='Servers.md' --exclude='Projects.md' \
    --exclude='data/finfra-server-access.md' --exclude='data/fapp-projects.md' \
    "$TMP"/ "$DST"/

git -C "$DST" add -A

# 개인정보 staged 가드 (2차)
if git -C "$DST" diff --cached --name-only | grep -iqE 'Servers\.md$|^Projects\.md$|finfra-server-access|fapp-projects'; then
    git -C "$DST" reset -q
    log "🚨 개인정보 staged 감지 — 커밋 중단·reset"; exit 1
fi

# 변경 없으면 종료
if git -C "$DST" diff --cached --quiet; then
    log "변경 없음 — skip"; exit 0
fi

SRC_HASH=$(git -C "$SRC" rev-parse --short HEAD)
git -C "$DST" commit -q -m "Sync: ___pm publishable 반영 ($SRC_HASH)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
log "동기화 완료 → fpm $(git -C "$DST" rev-parse --short HEAD) (src $SRC_HASH)"
