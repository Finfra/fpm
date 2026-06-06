#!/usr/bin/env bash
# fpm-sync.sh — ___pm(prj1) ↔ fpm(prj7) 동기화 엔진
#
# fpm-sync 에이전트(.claude/agents/fpm-sync.md)와 post-commit hook 의 공통 sync 로직 SSOT.
# 환경변수 override: FPM_SRC, FPM_DST
#
# 모드:
#   (인자 없음) | forward   : ___pm → fpm 단방향 복사·자동 커밋 (hook 기본)
#   reverse-dryrun          : fpm → ___pm 변경 미리보기 (적용 안 함)
#   reverse-apply           : fpm → ___pm 적용 (working tree 만, 커밋 안 함) — 에이전트가 사용자 동의 후에만 호출
#
# 불변식:
#   - forward: ___pm 읽기 전용. 개인정보(untracked)는 archive 라 자동 제외 + rsync exclude 2차 가드. fpm 자동 커밋.
#   - reverse: fpm → ___pm 는 --delete 금지(없는 ___pm 파일 보존), ___pm 자동 커밋·push 금지(사용자 검토).
#   - push 안 함(forward 도 커밋까지만). repo 없으면 조용히 종료(다른 머신 대비).
set -euo pipefail

MODE="${1:-forward}"
SRC="${FPM_SRC:-$HOME/_git/___pm}"
DST="${FPM_DST:-$HOME/_git/__all/fpm}"
LOG_DIR="$SRC/_doc_work/z_log"
LOG="$LOG_DIR/fpm-sync.log"

# 개인정보 경로 패턴 (양방향 공통 가드)
PERSONAL_RE='Servers\.md$|^Projects\.md$|finfra-server-access|fapp-projects'
EXCLUDES=(--exclude='.git/' --exclude='projects/'
          --exclude='Servers.md' --exclude='Projects.md'
          --exclude='data/finfra-server-access.md' --exclude='data/fapp-projects.md')

log() { mkdir -p "$LOG_DIR" 2>/dev/null || true; printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG" 2>/dev/null || true; printf '[fpm-sync] %s\n' "$1"; }

[ -d "$DST/.git" ] || { log "fpm repo 없음 ($DST) — skip"; exit 0; }
[ -d "$SRC/.git" ] || { log "src repo 없음 ($SRC) — skip"; exit 0; }

acquire_lock() {
    LOCKDIR="$SRC/.git/fpm-sync.lock.d"
    if ! mkdir "$LOCKDIR" 2>/dev/null; then
        if [ -d "$LOCKDIR" ] && [ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
            rmdir "$LOCKDIR" 2>/dev/null || true
            mkdir "$LOCKDIR" 2>/dev/null || { log "락 획득 실패 — skip"; exit 0; }
        else
            log "다른 sync 실행 중 — skip"; exit 0
        fi
    fi
    trap 'rm -rf "${TMP:-}" 2>/dev/null; rmdir "$LOCKDIR" 2>/dev/null || true' EXIT
}

# ── forward: ___pm → fpm (자동 커밋) ────────────────────────────
do_forward() {
    acquire_lock
    if git -C "$SRC" ls-files | grep -iqE "$PERSONAL_RE"; then
        log "🚨 개인정보가 ___pm tracked 에 존재 — 중단 (gitignore+rm --cached 필요)"; exit 1
    fi
    TMP=$(mktemp -d)
    git -C "$SRC" archive HEAD | tar -x -C "$TMP"
    rsync -a --delete "${EXCLUDES[@]}" "$TMP"/ "$DST"/
    git -C "$DST" add -A
    if git -C "$DST" diff --cached --name-only | grep -iqE "$PERSONAL_RE"; then
        git -C "$DST" reset -q; log "🚨 개인정보 staged 감지 — 커밋 중단·reset"; exit 1
    fi
    if git -C "$DST" diff --cached --quiet; then
        log "변경 없음 — skip"; exit 0
    fi
    local h; h=$(git -C "$SRC" rev-parse --short HEAD)
    git -C "$DST" commit -q -m "Sync: ___pm publishable 반영 ($h)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
    log "동기화 완료 → fpm $(git -C "$DST" rev-parse --short HEAD) (src $h)"
}

# ── reverse: fpm → ___pm (working tree 만, 커밋 안 함) ───────────
# fpm 의 tracked 스냅샷을 ___pm working tree 에 오버레이(--delete 금지).
# dryrun: 변경 미리보기만. apply: 실제 적용(사용자 동의 후 에이전트가 호출).
do_reverse() {
    local apply="$1"  # 0=dryrun, 1=apply
    acquire_lock
    TMP=$(mktemp -d)
    git -C "$DST" archive HEAD | tar -x -C "$TMP"
    # 개인정보가 fpm 쪽에 혼입돼 있으면 즉시 중단 (양방향 가드)
    if (cd "$TMP" && git -C "$SRC" ls-files >/dev/null 2>&1; ls) | grep -iqE "$PERSONAL_RE"; then
        : # (no-op; 아래 find 로 정확 검사)
    fi
    if find "$TMP" -type f | sed "s#^$TMP/##" | grep -iqE "$PERSONAL_RE"; then
        log "🚨 fpm 스냅샷에 개인정보 경로 존재 — reverse 중단"; exit 1
    fi
    if [ "$apply" = "0" ]; then
        log "── reverse dry-run (fpm → ___pm, 적용 안 함) ──"
        # -c(checksum): content 기준 비교 (mtime-only 차이 무시). 실제 전송 라인(^>f)만 표시
        local changes
        changes=$(rsync -nic -a "${EXCLUDES[@]}" "$TMP"/ "$SRC"/ | grep -E '^>f' || true)
        if [ -z "$changes" ]; then
            log "되돌릴 변경 없음 (content 동일)"
        else
            printf '%s\n' "$changes"
            log "── 위 파일이 fpm→___pm 로 적용될 변경. 동의 후 reverse-apply ──"
        fi
    else
        # -c: content 동일 파일은 skip. --delete 없음 (___pm 고유 파일 보존)
        rsync -c -a "${EXCLUDES[@]}" "$TMP"/ "$SRC"/
        log "reverse 적용 완료 (___pm working tree). 검토 후 직접 커밋: git -C $SRC status"
    fi
}

case "$MODE" in
    forward)         do_forward ;;
    reverse-dryrun)  do_reverse 0 ;;
    reverse-apply)   do_reverse 1 ;;
    *)               log "unknown mode: $MODE (forward|reverse-dryrun|reverse-apply)"; exit 2 ;;
esac
