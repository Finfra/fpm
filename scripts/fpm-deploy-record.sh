#!/usr/bin/env bash
# fpm-deploy-record.sh — 배포 인벤토리 기록기 (F5-5 / Issue346)
#
# ⚠️ 글로벌 SCAR 변경 가드: cwd ≠ ~/_git/___pm 이면 즉흥 수정 금지.
#   기록 대상: data/releases/deploy-state.yml · 짝 게이트: scripts/fpm-lockstep-check.sh
#
# 왜: "무엇이 언제 어느 채널로 나갔는가" 를 남기는 곳이 없었다. 태그만으로는
#   채널(App Store · Homebrew · 로컬 debug)을 구분할 수 없고, 배포 스크립트가
#   4곳으로 흩어져 있어 각자 기록하면 형식이 갈린다. 기록 지점을 하나로 둔다.
#
# ⚠️ append 전용이다. 기존 줄을 고치거나 지우지 않는다 — 인벤토리는 이력이다.
#
# Usage:
#   bash scripts/fpm-deploy-record.sh --prj 15 --name fSnippet --version 1.2.3 \
#        --channel local-debug --tag v1.2.3 --commit abc1234
#   옵션 --dry-run 이면 기록하지 않고 만들어질 줄만 출력한다.
#   rc=0 기록 성공 / rc=1 인자 오류

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="${FPM_DEPLOY_STATE:-$HERE/../data/releases/deploy-state.yml}"

PRJ="" NAME="" VERSION="" CHANNEL="" TAG="-" COMMIT="-" DRY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --prj)     PRJ="${2:-}";     shift 2 ;;
        --name)    NAME="${2:-}";    shift 2 ;;
        --version) VERSION="${2:-}"; shift 2 ;;
        --channel) CHANNEL="${2:-}"; shift 2 ;;
        --tag)     TAG="${2:--}";    shift 2 ;;
        --commit)  COMMIT="${2:--}"; shift 2 ;;
        --dry-run) DRY=1;            shift   ;;
        *) echo "❌ 알 수 없는 인자: $1" >&2; exit 1 ;;
    esac
done

for pair in "prj:$PRJ" "name:$NAME" "version:$VERSION" "channel:$CHANNEL"; do
    if [ -z "${pair#*:}" ]; then
        echo "❌ 필수 인자 누락: --${pair%%:*}" >&2
        exit 1
    fi
done

TS="$(date +%Y-%m-%dT%H:%M:%S%z)"
LINE="  - { date: $TS, prj: $PRJ, name: $NAME, version: $VERSION, channel: $CHANNEL, tag: $TAG, commit: $COMMIT }"

if [ "$DRY" = "1" ]; then
    echo "[dry-run] $STATE 에 기록될 줄:"
    echo "$LINE"
    exit 0
fi

if [ ! -f "$STATE" ]; then
    mkdir -p "$(dirname "$STATE")"
    cat > "$STATE" <<'EOF'
# deploy-state.yml — 배포 인벤토리 (F5-5 / Issue346)
#
# ⚠️ 손으로 쓰지 않는다. scripts/fpm-deploy-record.sh 가 append 한다.
#   무엇이 · 언제 · 어느 채널로 나갔는지의 이력이다. 줄을 지우거나 고치지 말 것.
#
# channel: local-debug(로컬 /Applications 배포) · homebrew(brew tap) · appstore
# tag/commit 이 `-` 면 그 배포 경로가 아직 태그·커밋을 남기지 않는다는 뜻이다.

releases:
EOF
fi

printf '%s\n' "$LINE" >> "$STATE"
echo "📒 배포 기록: prj$PRJ $NAME v$VERSION [$CHANNEL] tag=$TAG"
