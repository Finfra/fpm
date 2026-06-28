#!/usr/bin/env bash
# gh-sync.sh — Issue.md ↔ GitHub Issues 옵트인 브리지 진입점 (Issue233 T6)
#
# 로컬 Issue.md 가 SSOT. GitHub Issues 는 옵트인 미러(data/gh-sync.yml enabled).
# 서브커맨드: status | push [--apply] | pull
#   status      설정·매핑 현황
#   push        로컬→GH (기본 dry-run, --apply 로 실제 gh 쓰기 + 개인정보 가드)
#   pull        GH→로컬 (dry-run + local-wins 충돌 표시, 자동 병합 없음)
#
# 설계 SSOT: _doc_work/plan/gh-issue-bridge_plan.md
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE="$HERE/gh-sync/engine.py"

if ! command -v gh >/dev/null 2>&1; then
    echo "[gh-sync] gh CLI 미발견 — 설치 후 재시도 (brew install gh)" >&2
    exit 1
fi

CMD="${1:-status}"; shift || true
case "$CMD" in
    status|push|pull)
        exec python3 "$ENGINE" "$CMD" "$@"
        ;;
    *)
        echo "usage: gh-sync.sh [status|push [--apply]|pull]" >&2
        exit 1
        ;;
esac
