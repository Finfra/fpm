#!/usr/bin/env bash
# fpm-backup-untracked.sh — prj1 미추적 자산 백업 (Issue344)
#
# `git push fg1` 로 만드는 bare mirror(prj3#Issue322 X2)는 **git 추적 파일만** 커버한다.
# 이 스크립트는 그 사각지대 — .gitignore 로 로컬 전용 처리 중이면서 **재생성 불가**한 파일 —
# 을 fg1 로 rsync 한다. git 이 아니라 파일 복사이며, 목적지는 추적분 백업과 같은 머신이다.
#
# 선별 원칙: `git ls-files --others --exclude-standard` (미추적 전체, ignored 포함) 에서
#   재생성 가능(graphify-out·Issue_map.htm·Projects_map.* 등)·런타임 상태(data/hub/*.json)·
#   캐시·OS 노이즈를 뺀 나머지. 목록은 EXCLUDES 배열이 SSOT.
#
# 사용: fpm-backup-untracked.sh [--dry-run] [--verify]
#   --dry-run  전송 없이 대상 목록·용량만 출력
#   --verify   전송 후 fg1 파일 수를 원본과 대조 (복구 리허설 대용 상시 검증)
# exit: 0=성공, 1=검증 불일치, 2=사용법/환경 오류(fail-loud)
set -euo pipefail

FPM_SRC="${FPM_SRC:-$HOME/_git/___pm}"
FPM_BACKUP_HOST="${FPM_BACKUP_HOST:-fg1}"
FPM_BACKUP_DIR="${FPM_BACKUP_DIR:-/home/nowage/_git/_backup/___pm-untracked}"

DRY=0; VERIFY=0
for a in "$@"; do
    case "$a" in
        --dry-run) DRY=1 ;;
        --verify)  VERIFY=1 ;;
        *) echo "🚨 알 수 없는 인자: $a (사용법: $0 [--dry-run] [--verify])" >&2; exit 2 ;;
    esac
done

cd "$FPM_SRC" || { echo "🚨 소스 없음: $FPM_SRC" >&2; exit 2; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "🚨 git repo 아님: $FPM_SRC" >&2; exit 2; }

# 재생성 가능·런타임·캐시·노이즈 — 백업 대상 아님
EXCLUDES=(
    '^graphify-out/'          # AST 재빌드 가능 (graphify 산출물)
    '^\.playwright-mcp/'      # MCP 진단 부산물
    '^_doc_work/htm/'         # hub 렌더 산출물
    '^_doc_work/z_htm/'
    '^_doc_work/z_done/htm/'
    '^data/hub/.*\.json$'     # server.py 런타임 상태
    '^Issue_map\.htm$'        # Issue.md 로부터 재생성
    '^Projects_map\.(htm|md)$'  # Projects.md 로부터 재생성
    '^projects/'              # Projects.md + fpm-projects-sync 로 재생성
    '^sh/fpm_aliases_iterm-bg\.sh$'  # update-iterm-bg 산출물
    '(^|/)__pycache__/'
    '(^|/)\.pytest_cache/'
    '(^|/)\.DS_Store$'
    '\.pyc$'
    '\.backup[^/]*$'
    '(^|/)\.claude/\.dev-server-state/'
)
EXCLUDE_RE="$(IFS='|'; echo "${EXCLUDES[*]}")"

LIST="$(mktemp)"; trap 'rm -f "$LIST"' EXIT
# --others 는 ignored 를 빼므로, ignored 목록을 따로 뽑아 합집합을 만든다
{
    git ls-files --others --exclude-standard -z | tr '\0' '\n'
    git ls-files --others --ignored --exclude-standard -z | tr '\0' '\n'
} | grep -Ev "$EXCLUDE_RE" | grep -v '^$' | sort -u > "$LIST"

COUNT="$(wc -l < "$LIST" | tr -d ' ')"
[ "$COUNT" -gt 0 ] || { echo "🚨 백업 대상 0건 — 선별 로직 오류 의심 (fail-loud)" >&2; exit 2; }
SIZE="$(tr '\n' '\0' < "$LIST" | xargs -0 du -ck 2>/dev/null | tail -1 | cut -f1)"

echo "== prj1 미추적 백업 대상: ${COUNT}건 / ${SIZE}KB =="
if [ "$DRY" = 1 ]; then
    cat "$LIST"
    echo "(dry-run — 전송하지 않음)"
    exit 0
fi

# ⚠️ --files-from 모드에서는 --delete 가 무효다(원격에 사라진 파일이 남는다).
#    로컬 스테이징 트리를 만든 뒤 그것을 통째로 미러해야 삭제가 전파된다.
STAGE="$(mktemp -d)"; trap 'rm -f "$LIST"; rm -rf "$STAGE"' EXIT
rsync -a --files-from="$LIST" "$FPM_SRC/" "$STAGE/" \
  || { echo "🚨 스테이징 실패 — 백업 미완료" >&2; exit 2; }
rsync -az --delete "$STAGE/" "${FPM_BACKUP_HOST}:${FPM_BACKUP_DIR}/" \
  || { echo "🚨 rsync 실패 — 백업 미완료" >&2; exit 2; }
echo "✅ 전송 완료 → ${FPM_BACKUP_HOST}:${FPM_BACKUP_DIR}"

if [ "$VERIFY" = 1 ]; then
    REMOTE="$(ssh "$FPM_BACKUP_HOST" "find '$FPM_BACKUP_DIR' -type f | wc -l" | tr -d ' ')"
    if [ "$REMOTE" != "$COUNT" ]; then
        echo "🚨 검증 실패 — 원본 ${COUNT}건 vs 원격 ${REMOTE}건" >&2
        exit 1
    fi
    echo "✅ 검증 통과 — 파일 수 ${COUNT}건 일치"
fi
