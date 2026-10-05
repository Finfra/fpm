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
#
# ── G3 게이트 통과 기록 모드 (Issue478_2) ──────────────────────────
#   bash scripts/fpm-deploy-record.sh --gate release [--repo <경로>] [--dry-run]
#   기록처는 **형제 파일** data/releases/release-gates.yml 이다. deploy-state.yml 에
#   섞지 않는 이유가 둘 있다:
#     ① 저 파일의 append 계약은 "EOF 에 releases: 항목을 붙인다" 다. 두 번째 섹션이
#        생기는 순간 그 계약이 순서 의존이 되어 기록기가 조용히 엉뚱한 곳에 쓴다
#     ② 게이트 통과는 **배포 이벤트가 아니다.** `channel: release-gate` 같은 줄을
#        인벤토리에 끼우면 "무엇이 나갔는가" 를 세는 소비처가 전부 틀린 답을 준다
#   기록기는 하나로 유지한다 — deploy-state.yml 헤더의 "손으로 쓰지 않는다" 원칙이
#   새 파일에도 그대로 적용돼야 하기 때문이다.
#   commit 은 기록 시점 HEAD, tree 는 그 커밋의 트리, dirty 는 워킹트리 오염 여부다.
#   ⚠️ dirty=yes 기록은 **그 커밋을 검증한 것이 아니다** — G4 는 그런 줄을 무시한다.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="${FPM_DEPLOY_STATE:-$HERE/../data/releases/deploy-state.yml}"

PRJ="" NAME="" VERSION="" CHANNEL="" TAG="-" COMMIT="-" DRY=0
GATE="" REPO=""

while [ $# -gt 0 ]; do
    case "$1" in
        --gate)    GATE="${2:-}";    shift 2 ;;
        --repo)    REPO="${2:-}";    shift 2 ;;
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

# ── 게이트 모드 (Issue478_2) — 배포 인벤토리와 분리된 경로 ─────────
if [ -n "$GATE" ]; then
    REPO="${REPO:-$HERE/..}"
    GSTATE="${FPM_RELEASE_GATE_STATE:-$HERE/../data/releases/release-gates.yml}"
    g_commit="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo '-')"
    g_tree="$(git -C "$REPO" rev-parse --short 'HEAD^{tree}' 2>/dev/null || echo '-')"
    g_branch="$(git -C "$REPO" symbolic-ref --short HEAD 2>/dev/null || echo 'detached')"
    g_ver="$(tr -d '[:space:]' < "$REPO/VERSION" 2>/dev/null || echo '-')"
    if [ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]; then g_dirty=yes; else g_dirty=no; fi
    GLINE="  - { date: $(date +%Y-%m-%dT%H:%M:%S%z), suite: $GATE, version: $g_ver, branch: $g_branch, commit: $g_commit, tree: $g_tree, dirty: $g_dirty }"
    if [ "$DRY" = "1" ]; then
        echo "[dry-run] $GSTATE 에 기록될 줄:"; echo "$GLINE"; exit 0
    fi
    if [ ! -f "$GSTATE" ]; then
        mkdir -p "$(dirname "$GSTATE")"
        cat > "$GSTATE" <<'EOF'
# release-gates.yml — G3 병합 게이트 통과 기록 (Issue478_2)
#
# ⚠️ 손으로 쓰지 않는다. scripts/fpm-deploy-record.sh --gate 가 append 한다.
#   "이 커밋이 5스테이지 통합 검증을 통과했다" 의 이력이다. 줄을 지우거나 고치지 말 것.
#
# 생산: sh/release-check.sh 전체 실행(--no-sandbox 아님) 이 전건 PASS 일 때만
# 소비: scripts/fpm-sync.sh do_deploy 진입부(G4) — 통과 기록이 현재 HEAD 의 조상인지 확인
# 설계: _doc_arch/fpm-release-gate.md "G3 — 병합 게이트" / "G4 — 출고 게이트"
#
# ⚠️ dirty: yes 는 **그 커밋을 검증한 것이 아니다**(워킹트리에 미커밋 변경이 있었다).
#   G4 는 그런 줄을 통과 근거로 쓰지 않는다.

gates:
EOF
    fi
    printf '%s\n' "$GLINE" >> "$GSTATE"
    echo "📒 G3 게이트 기록: suite=$GATE v$g_ver $g_branch@$g_commit (dirty=$g_dirty)"
    exit 0
fi

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
