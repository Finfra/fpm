#!/usr/bin/env bash
# run-release.sh — 배포 재생목록 tdd/release.md 를 후보 커밋에서 돌리고 R1 증거를 남긴다 (Issue543 M1-0)
#
# 왜: tdd/release.md 는 인덱스일 뿐 행을 돌려 결과를 모으는 주체가 없었다(codex plan-check high).
#   기록기는 `--gate release --repo` 만 받아 «어느 행을 돌렸고 무엇을 건너뛰었나» 를 알 수 없었다.
#   이 드라이버가 ① 후보를 격리 worktree 로 꺼내고(sh/release-candidate-run.sh — dirty: no 가 구성상 보장)
#   ② 표를 위에서 아래로 돌리고(tdd/playlist-run.py) ③ 행별 결과를 기록기 --rows 로 넘겨
#   md 증거 `_doc_work/_release/v{VER}/release-test_{VER}.md` 를 남긴다. R2(출고 재확인)가 그 파일을 읽는다.
#
# 사용: bash tdd/run-release.sh [--version <출고 버전>] [--commit <후보>] [--manual <id>=<결과>[:근거]]...
#                               [--only id,id] [--timeout 초] [--no-record]
#   --version  출고할 버전 — 증거 폴더 키. 생략하면 deploy patch 와 같은 규칙(scripts/fpm-sync.sh next-version)
#              ⚠️ deploy 를 minor·major·X.Y.Z 로 할 거면 같은 값을 준다 — R2 는 출고 버전 폴더에서 증거를 찾는다
#   --commit   후보 커밋 (기본 HEAD — release/{X.Y} 브랜치 HEAD 에서 부르는 것이 R1 이다)
#   --manual   수동 행 결과 ex) --manual "hub-ui-signoff=pass:_doc_work/z_done/report/b2_0.8.4.md"
#   --only     일부 행만 — 나머지는 skip 으로 기록되어 result 는 partial 이 된다(통과 근거가 아니다)
# exit: 0 result pass · 3 partial(건너뛴 행) · 1 fail·기록 실패 · 2 입력 오류
set -uo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
ARGS=("$@")

VER="" COMMIT="HEAD" NO_RECORD=0
PASSTHRU=()
while [ $# -gt 0 ]; do
    case "$1" in
        --version)   VER="${2:-}";    shift 2 ;;
        --commit)    COMMIT="${2:-}"; shift 2 ;;
        --manual)    PASSTHRU+=(--manual "${2:-}");  shift 2 ;;
        --only)      PASSTHRU+=(--only "${2:-}");    shift 2 ;;
        --timeout)   PASSTHRU+=(--timeout "${2:-}"); shift 2 ;;
        --no-record) NO_RECORD=1; shift ;;
        -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "❌ 알 수 없는 인자: $1" >&2; exit 2 ;;
    esac
done

# ── 1. 격리 진입 ── 공유 작업트리에서 불리면 후보를 worktree 로 꺼내 **후보 자신의 드라이버**로 다시 돈다
if [ -z "${FPM_RELEASE_CANDIDATE:-}" ]; then
    exec bash "$REPO_DIR/sh/release-candidate-run.sh" "$COMMIT" -- bash tdd/run-release.sh "${ARGS[@]}"
fi
MAIN="${FPM_RELEASE_MAIN_REPO:-$REPO_DIR}"

# ── 2. 출고 버전 ──
if [ -z "$VER" ]; then
    VER="$(FPM_SRC="$REPO_DIR" bash "$REPO_DIR/scripts/fpm-sync.sh" next-version patch 2>/dev/null)" || VER=""
    [ -n "$VER" ] || { echo "❌ 출고 버전을 정하지 못했다 — --version <X.Y.Z> 로 지정" >&2; exit 2; }
    echo "ℹ️ --version 생략 → deploy patch 규칙으로 v$VER (다른 버전으로 출고할 거면 --version 지정)"
fi
[[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "❌ --version 은 X.Y.Z (got '$VER')" >&2; exit 2; }

# ── 3. 증거 메타 — env·peers 는 release.md frontmatter 가 정한다 ──
PL="$REPO_DIR/tdd/release.md"
[ -f "$PL" ] || { echo "❌ 배포 재생목록 없음: tdd/release.md" >&2; exit 2; }
fm() { sed -n '/^---$/,/^---$/p' "$PL" | sed -n "s/^$1: *//p" | head -1; }
EV_ENV="$(fm env)"; EV_ENV="${EV_ENV:--}"
# peers: prjN → projects 인덱스(본 작업트리 — projects/ 는 추적되지 않아 worktree 에 없다) → HEAD
PROJ_DIR="${PM_PROJECTS_DIR:-$MAIN/projects}"
EV_PEERS=""
for p in $(fm peers | tr ',' ' '); do
    n="${p#prj}"; sha="?"
    if [ -f "$PROJ_DIR/$n" ]; then
        pp="$(head -1 "$PROJ_DIR/$n")"; pp="${pp/#\~/$HOME}"
        sha="$(git -C "$pp" rev-parse --short HEAD 2>/dev/null || echo '?')"
    fi
    EV_PEERS="${EV_PEERS:+$EV_PEERS,}$p@$sha"
done
EV_PEERS="${EV_PEERS:--}"

# ── 4. 행 실행 ──
TS="$(date +%Y%m%d_%H%M%S)"
LOGDIR="$MAIN/tdd/results/release-v${VER}_$TS"
mkdir -p "$MAIN/tdd/results"
[ -f "$MAIN/tdd/results/.gitignore" ] || printf '*\n' > "$MAIN/tdd/results/.gitignore"   # 로그엔 개인 경로가 섞인다 — run-tdd.sh 결과 폴더와 같은 이유
WORK="$(mktemp -d "${TMPDIR:-/tmp}/run-release.XXXXXX")"
trap 'case "$WORK" in */run-release.*) rm -rf "$WORK" ;; esac' EXIT
export FPM_PLAYLIST_MEMO="$WORK/memo"   # 1행(개발 재생목록) 안의 release-check 를 2행이 재사용한다
# R1 실행 규약 (release-test-rules, prj3#Issue741) — 행이 출고 명령을 스스로 부르면 거기 배선된 R2 가
#   «증거 없음» 으로 막아 R1 이 영원히 못 끝난다. recheck 는 이 변수가 1 이면 생략을 알리고 rc 0 이다
export RELEASE_TEST_R1=1

echo "▶ R1 — tdd/release.md · 후보 ${FPM_RELEASE_CANDIDATE:0:10} · 출고 v$VER · 로그 $LOGDIR"
python3 "$REPO_DIR/tdd/playlist-run.py" "$PL" --rows-out "$WORK/rows.tsv" --log-dir "$LOGDIR" ${PASSTHRU[@]+"${PASSTHRU[@]}"}
rc=$?
[ "$rc" -eq 2 ] && { echo "❌ 재생목록 입력 오류 — 증거를 남기지 않는다" >&2; exit 2; }

# ── 5. 증거 기록 (실패는 실패다 — 기록 없는 R1 은 R2 가 볼 수 없다) ──
if [ "$NO_RECORD" -eq 1 ]; then
    echo "ℹ️ --no-record — 증거를 남기지 않았다 (출고 근거가 되지 않는다)"
else
    bash "$REPO_DIR/scripts/fpm-deploy-record.sh" --gate release --repo "$REPO_DIR" \
        --rows "$WORK/rows.tsv" --version "$VER" --env "$EV_ENV" --peers "$EV_PEERS" || {
        echo "🚨 R1 증거 기록 실패 — 결과가 남지 않았다" >&2; exit 1; }
fi
case "$rc" in
    0) echo "✅ R1 pass — v$VER 출고 근거 확보 (R2: python3 ~/.claude/sh/release-test-audit.py recheck --repo . --version $VER)" ;;
    3) echo "◐ R1 partial — 건너뛴 행이 있다. 출고 근거가 아니다(R2 는 pass 만 인정)" ;;
    *) echo "❌ R1 fail — 실패 행을 고치고 다시 돈다" ;;
esac
exit "$rc"
