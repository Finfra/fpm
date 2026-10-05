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
#
# ── R1 md 증거 모드 (Issue543 M1-1) ────────────────────────────────
#   bash scripts/fpm-deploy-record.sh --gate release --rows <tsv> --version <출고 버전> \
#        [--repo <경로>] [--env <머신>] [--peers <prj3@sha>] [--dry-run]
#   <tsv> 는 행마다 `id<TAB>결과<TAB>비고` — 결과는 pass|fail|skip|partial 만 (tdd/run-release.sh 가 만든다)
#   정본: ${FPM_RELEASE_EVIDENCE_DIR:-_doc_work/_release}/v{VER}/release-test_{VER}.md (release-test-rules "증거 형식")
#     result = fail 1건 이상 → fail · skip·partial 1건 이상 → partial · 전건 pass → pass
#     ⚠️ 건너뛴 행이 있는 실행을 pass 로 쓰지 않는다 (--no-sandbox 교훈) — R2 는 pass 만 근거로 쓴다
#   색인: release-gates.yml 에 `suite: release-test` 1줄 (정본은 md — 색인은 사람이 이력을 훑는 용도)
#   rc: 0 기록 성공(결과와 무관 — 판정은 드라이버 몫) · 1 입력 오류(버전 누락·0건·허용 외 토큰)·쓰기 실패

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="${FPM_DEPLOY_STATE:-$HERE/../data/releases/deploy-state.yml}"

PRJ="" NAME="" VERSION="" CHANNEL="" TAG="-" COMMIT="-" DRY=0
GATE="" REPO="" ROWS="" EV_ENV="-" EV_PEERS="-"

while [ $# -gt 0 ]; do
    case "$1" in
        --gate)    GATE="${2:-}";    shift 2 ;;
        --repo)    REPO="${2:-}";    shift 2 ;;
        --rows)    ROWS="${2:-}";    shift 2 ;;
        --env)     EV_ENV="${2:--}"; shift 2 ;;
        --peers)   EV_PEERS="${2:--}"; shift 2 ;;
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
    # 격리 worktree(sh/release-candidate-run.sh)는 detached 다 — 브랜치 기준 이름을 붙인다.
    #   worktree 는 ref 를 공유하므로 REPO 자신으로 푼다(상속 env 로 다른 저장소를 보지 않는다)
    if [ "$g_branch" = "detached" ]; then
        g_branch="$(git -C "$REPO" name-rev --name-only --no-undefined --refs='refs/heads/*' HEAD 2>/dev/null || echo 'detached')"
    fi
    g_ver="$(tr -d '[:space:]' < "$REPO/VERSION" 2>/dev/null || echo '-')"
    if [ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]; then g_dirty=yes; else g_dirty=no; fi

    # ── R1 md 증거 모드 (Issue543 M1-1) ──
    if [ -n "$ROWS" ]; then
        [ -n "$VERSION" ] || { echo "❌ --rows 에는 --version <출고 버전> 이 필요하다 (증거 폴더 키)" >&2; exit 1; }
        [ -f "$ROWS" ]    || { echo "❌ 행 결과 파일 없음: $ROWS" >&2; exit 1; }
        EVDIR="${FPM_RELEASE_EVIDENCE_DIR:-$HERE/../_doc_work/_release}"
        EVFILE="$EVDIR/v$VERSION/release-test_$VERSION.md"
        g_full="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo '-')"
        MAINROOT="${FPM_RELEASE_MAIN_REPO:-$HERE/..}"
        # md 생성·검증은 python — 표 이스케이프·토큰 검증을 셸로 짜면 그 자체가 버그원이다
        if ! ev_out="$(python3 - "$ROWS" "$EVFILE" "$VERSION" "$g_full" "$g_dirty" "$EV_ENV" "$EV_PEERS" \
                        "$g_branch" "$MAINROOT" "$DRY" <<'PYEOF'
import datetime, os, sys, tempfile
rows_f, ev, ver, commit, dirty, env, peers, branch, mainroot, dry = sys.argv[1:11]
OK = ("pass", "fail", "skip", "partial")
rows = []
for n, line in enumerate(open(rows_f, encoding="utf-8").read().splitlines(), 1):
    if not line.strip() or line.startswith("#"):
        continue
    parts = (line.split("\t") + ["", ""])[:3]
    rid, res, note = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if not rid or res not in OK:
        sys.stderr.write(f"❌ {rows_f}:{n} 형식 오류 — id<TAB>{'|'.join(OK)}<TAB>비고 (got {line!r})\n")
        sys.exit(1)
    rows.append((rid, res, note))
if not rows:
    sys.stderr.write("❌ 행 결과 0건 — 돌지 않은 것은 통과가 아니다\n")
    sys.exit(1)
results = [r[1] for r in rows]
result = "fail" if "fail" in results else ("partial" if ("skip" in results or "partial" in results) else "pass")
now = datetime.datetime.now()
esc = lambda s: s.replace("|", "\\|").replace("\n", " ")
out = [
    "---",
    f'title: "fpm v{ver} 출고 검증 증거 (R1)"',
    f'description: "tdd/release.md 를 후보 커밋에서 돌린 결과 — 글로벌 release-test-rules 증거 형식 (R2 가 읽는다)"',
    f"version: {ver}",
    f"commit: {commit}",
    f"dirty: {dirty}",
    f"result: {result}",
    f"env: {env}",
    f"peers: {peers}",
    f"date: {now:%Y.%m.%d}",
    "---",
    "",
    "# 행별 결과",
    "",
    "| # | id | 결과 | 비고 |",
    "| :- | :- | :- | :- |",
]
for i, (rid, res, note) in enumerate(rows, 1):
    out.append(f"| {i} | `{esc(rid)}` | {res} | {esc(note) or '—'} |")
out += [
    "",
    f"* 후보: `{commit}` ({branch}) · 기록: {now:%Y-%m-%d %H:%M:%S}",
    "* result 규칙: fail 1건 이상 → `fail` · skip·partial 1건 이상 → `partial` · 전건 pass → `pass`. R2(`release-test-audit.py recheck`)는 `pass`·`dirty: no` 만 근거로 쓴다",
    "* ⚠️ 기록기가 쓴다 — 손으로 고치지 않는다(`scripts/fpm-deploy-record.sh --gate release --rows`). 재실행하면 같은 버전 증거를 덮어쓰고 이력은 `data/releases/release-gates.yml` 색인에 남는다",
    "",
]
rel = os.path.relpath(ev, mainroot)
if rel.startswith(".."):
    rel = ev
if dry == "1":
    print(f"DRY\t{result}\t{rel}")
    print("\n".join(out))
    sys.exit(0)
try:
    os.makedirs(os.path.dirname(ev), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ev), prefix=".release-test.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    um = os.umask(0); os.umask(um)
    os.chmod(tmp, 0o666 & ~um)   # mkstemp 는 0600 — 공유 문서라 일반 파일과 같은 umask 기준으로
    os.replace(tmp, ev)
except OSError as e:
    sys.stderr.write(f"🚨 R1 증거 쓰기 실패 — {ev}: {e}\n")
    sys.exit(1)
print(f"{result}\t{rel}")
PYEOF
)"; then
            exit 1
        fi
        if [ "$DRY" = "1" ]; then printf '%s\n' "$ev_out"; exit 0; fi
        ev_result="${ev_out%%	*}"; ev_rel="${ev_out#*	}"
        GLINE="  - { date: $(date +%Y-%m-%dT%H:%M:%S%z), suite: release-test, version: $VERSION, branch: $g_branch, commit: $g_commit, tree: $g_tree, dirty: $g_dirty, result: $ev_result, evidence: $ev_rel }"
        EV_MSG="📒 R1 증거: v$VERSION result=$ev_result dirty=$g_dirty → $ev_rel"
    else
        GLINE="  - { date: $(date +%Y-%m-%dT%H:%M:%S%z), suite: $GATE, version: $g_ver, branch: $g_branch, commit: $g_commit, tree: $g_tree, dirty: $g_dirty }"
        EV_MSG=""
    fi
    if [ "$DRY" = "1" ]; then
        echo "[dry-run] $GSTATE 에 기록될 줄:"; echo "$GLINE"; exit 0
    fi
    # ⚠️ 쓰기 실패는 rc 1 (Issue543 M1-0b) — 종전엔 mkdir·append 가 실패해도 아래 `exit 0` 에
    #   닿아 "기록했다" 고 답했다. 기록이 곧 게이트의 근거이므로 못 남겼으면 실패로 드러낸다.
    if [ ! -f "$GSTATE" ]; then
        mkdir -p "$(dirname "$GSTATE")" 2>/dev/null || {
            echo "🚨 G3 기록 실패 — 디렉토리를 만들 수 없다: $(dirname "$GSTATE")" >&2; exit 1; }
        cat > "$GSTATE" 2>/dev/null <<'EOF' || { echo "🚨 G3 기록 실패 — 파일을 만들 수 없다: $GSTATE" >&2; exit 1; }
# release-gates.yml — G3 병합 게이트 통과 기록 (Issue478_2)
#
# ⚠️ 손으로 쓰지 않는다. scripts/fpm-deploy-record.sh --gate 가 append 한다.
#   "이 커밋이 5스테이지 통합 검증을 통과했다" 의 이력이다. 줄을 지우거나 고치지 말 것.
#
# 생산: suite: release      — sh/release-check.sh 전체 실행(--no-sandbox 아님) 이 전건 PASS 일 때만
#       suite: release-test — tdd/run-release.sh (R1 전 행) — 정본은 evidence: 의 md 증거다
# 소비: 사람(이력 색인). 출고 게이트(G4 → R2)는 이 파일이 아니라 md 증거를 읽는다 (Issue543 M2)
# 설계: _doc_arch/fpm-release-gate.md "G3 — 병합 게이트" / "출고 재생목록 통합"
#
# ⚠️ dirty: yes 는 **그 커밋을 검증한 것이 아니다**(워킹트리에 미커밋 변경이 있었다).

gates:
EOF
    fi
    printf '%s\n' "$GLINE" 2>/dev/null >> "$GSTATE" || {
        echo "🚨 G3 기록 실패 — 쓸 수 없다: $GSTATE" >&2; exit 1; }
    if [ -n "$EV_MSG" ]; then echo "$EV_MSG"
    else echo "📒 G3 게이트 기록: suite=$GATE v$g_ver $g_branch@$g_commit (dirty=$g_dirty)"; fi
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
