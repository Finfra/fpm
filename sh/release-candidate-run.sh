#!/usr/bin/env bash
# release-candidate-run.sh — 출고 후보 커밋을 격리 worktree 에서 실행 (Issue543 M0)
#
# 왜: 공유 작업트리에는 타 세션의 미커밋 Issue.md·미추적 파일이 상시 있다. 거기서 R1(G3)을
#   돌리면 기록이 **구조적으로** `dirty: yes` 가 되고(release-gates.yml 12/12 실측), dirty 기록은
#   게이트가 근거로 쓰지 않으므로 출고가 항상 막힌다 → 우회 변수 상시화 직전이었다.
#   dirty 판정을 느슨하게 하지 않고 **실행 위치**를 바꾼다 — 후보를 detached worktree 로 꺼내
#   그 안에서 돌리면 dirty 는 구성상 no 이고 타 세션 작업도 건드리지 않는다.
#   설계: _doc_arch/fpm-release-gate.md "1번의 원인 — 작업트리에서 돌리기 때문"
#
# ⚠️ 기록은 본 작업트리로 — 기록기는 스크립트 위치 기준($HERE/../data/releases/)으로 쓰므로
#   worktree 안에서 돌면 기록이 worktree 와 함께 지워진다. 그래서 기록 경로를 **본 작업트리
#   절대경로**로 주입한다(이미 설정돼 있으면 존중 — 테스트·운영 override):
#     FPM_RELEASE_MAIN_REPO     본 작업트리 루트
#     FPM_RELEASE_CANDIDATE     후보 전체 SHA
#     FPM_RELEASE_GATE_STATE    <본>/data/releases/release-gates.yml (기존 env — 기록기가 읽음)
#     FPM_RELEASE_EVIDENCE_DIR  <본>/_doc_work/_release (md 증거 — 기록기 --rows 모드가 읽음)
#
# 사용: bash sh/release-candidate-run.sh <commit-ish> -- <명령> [인자...]
#   명령은 격리 worktree 루트를 cwd 로 돈다 — 후보 자신의 스크립트를 상대경로로 부른다.
#   ex) bash sh/release-candidate-run.sh HEAD -- bash tdd/run-tdd.sh --only release
# exit: 명령의 rc 그대로 · 2=입력 오류(usage·없는 커밋·worktree 생성 실패)
#       명령이 성공했는데 worktree 정리에 실패하면 1 (남은 worktree 를 조용히 두지 않는다)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

usage() { echo "usage: sh/release-candidate-run.sh <commit-ish> -- <명령> [인자...]" >&2; exit 2; }
[ $# -ge 3 ] || usage
REF="$1"; shift
[ "$1" = "--" ] || usage
shift

# 본 작업트리 = **이 스크립트가 속한 저장소**의 공용 .git 부모. show-toplevel 은 linked worktree 안에서
#   부르면 그 worktree 를 주므로 common-dir 로 푼다(worktree 안에서 불려도 본 작업트리가 나온다).
# ⚠️ 상속된 FPM_RELEASE_MAIN_REPO 로 대상을 정하지 않는다 — R1 안에서 도는 테스트가 바깥 실행기의 문맥을
#   상속하면 fixture 가 아니라 바깥 저장소에 worktree 를 만들고 기록했다(2026-09-27 R1 실측 #33 6 FAIL).
common="$(git -C "$HERE/.." rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || {
    echo "🚨 git 저장소가 아니다: $HERE/.." >&2; exit 2; }
MAIN="$(cd "$(dirname "$common")" && pwd -P)"
# 기록 경로 override 는 **같은 저장소 문맥**일 때만 존중한다 — 다른 저장소의 R1 문맥이면 버린다
inherited="${FPM_RELEASE_MAIN_REPO:-}"
if [ -n "$inherited" ] && [ "$(cd "$inherited" 2>/dev/null && pwd -P)" != "$MAIN" ]; then
    unset FPM_RELEASE_GATE_STATE FPM_RELEASE_EVIDENCE_DIR
fi
SHA="$(git -C "$MAIN" rev-parse --verify --quiet "${REF}^{commit}")" || {
    echo "🚨 후보 커밋을 찾을 수 없다: $REF" >&2; exit 2; }

BASE="$(mktemp -d "${TMPDIR:-/tmp}/fpm-rc.XXXXXX")" || { echo "🚨 임시 디렉토리 생성 실패" >&2; exit 2; }
WT="$BASE/wt"

cleanup_failed=0
cleanup() {
    if [ -d "$WT" ]; then
        # --force: 명령이 남긴 미추적 부산물(tdd/results·__pycache__ 등)이 있어도 지운다 — 격리본이다
        if ! git -C "$MAIN" worktree remove --force "$WT" >/dev/null 2>&1; then
            echo "⚠️ worktree 정리 실패: $WT — 수동: git -C \"$MAIN\" worktree remove --force \"$WT\"" >&2
            cleanup_failed=1
        fi
    fi
    git -C "$MAIN" worktree prune >/dev/null 2>&1
    # 우리가 mktemp 로 만든 경로만 지운다
    case "$BASE" in */fpm-rc.*) [ -d "$BASE" ] && rm -rf "$BASE" ;; esac
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# hooksPath=/dev/null — worktree add 는 post-checkout 을 발화한다(graphify 재빌드 등). 격리 실행에 부작용을 싣지 않는다
if ! git -C "$MAIN" -c core.hooksPath=/dev/null worktree add --detach -q "$WT" "$SHA" >/dev/null 2>&1; then
    echo "🚨 worktree 생성 실패: $SHA → $WT" >&2
    exit 2
fi

export FPM_RELEASE_MAIN_REPO="$MAIN"
export FPM_RELEASE_CANDIDATE="$SHA"
export FPM_RELEASE_GATE_STATE="${FPM_RELEASE_GATE_STATE:-$MAIN/data/releases/release-gates.yml}"
export FPM_RELEASE_EVIDENCE_DIR="${FPM_RELEASE_EVIDENCE_DIR:-$MAIN/_doc_work/_release}"

echo "▶ 후보 ${SHA:0:10} 격리 실행 (worktree: $WT)" >&2
( cd "$WT" && "$@" )
rc=$?

cleanup
trap - EXIT
if [ "$rc" -eq 0 ] && [ "$cleanup_failed" -eq 1 ]; then rc=1; fi
exit "$rc"
