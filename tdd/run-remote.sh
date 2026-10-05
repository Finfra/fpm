#!/usr/bin/env bash
# run-remote.sh — 네이티브 원격 러너 (Issue543 M3 · 설계 _doc_arch/fpm-release-test.md "F-1")
#
# 묻는 것: *"이 후보가 저작 머신이 아닌 그 OS 에서 실제로 도는가."* macOS 에서 `--only linux`
#   를 돌린 대리 실행은 케이스 스크립트가 macOS 에서 돈다는 뜻일 뿐이다 — 출고 증거는 네이티브뿐.
#
# 5단계:
#   ① 기동 — ssh 무응답이면 로컬 설정의 기동 명령을 돌리고 응답을 기다린다(상한 있음)
#   ② 반송 — 후보 트리를 **이력 없는 단일 커밋** git bundle 로 떠서 scp. push 하지 않는다.
#      이력을 싣지 않는 이유: 과거 커밋에 자격증명이 남아 있다(백업 선행 게이트가 이력 시크릿으로 경고한 그 이력). 검사 대상은
#      후보 트리뿐이므로 소비자 머신 디스크에 이력을 복제할 까닭이 없다
#   ③ 실행 — 원격에서 run-tdd.sh(core + 자기 플랫폼) + 임시 HOME install→check→uninstall
#   ④ 회수 — 원격 로그 → tdd/results/remote-<ts>-<id>/ (gitignore · 미러 제외)
#   ⑤ 정리 — 원격 임시 디렉토리 삭제. 실패·중단에도 수행한다
#
# 호스트명은 이 파일·machines.yml 에 쓰지 않는다 — 둘 다 공개 미러로 나간다.
#   머신 id → ssh 대상은 로컬 설정 `tdd/remote.local.sh`(gitignore · 미러 제외)에서 읽고,
#   없으면 **ssh 별칭 = id** 로 본다(plan 열린 질문 2 의 (b) 가 기본, 설정은 덮어쓰기용).
#     FPM_TDD_SSH_<id>=<ssh 대상>        id 의 '-' 는 '_' — ex) FPM_TDD_SSH_gpu_server=myhost
#     FPM_TDD_WAKE_<id>='<기동 명령>'    없으면 FPM_TDD_WAKE_CMD='<명령>' 에 id 를 인자로 붙인다
#   R1 격리 worktree 에는 미추적 설정이 없으므로 FPM_RELEASE_MAIN_REPO(M0-4 주입)의 것을 먼저 본다.
#
# 사용: bash tdd/run-remote.sh --machine <id> [--candidate <rev>] [--repo <후보 repo>]
# exit: 0 PASS · 1 FAIL · 3 partial(머신 불가 — planned·ssh 무응답·중도 끊김) · 2 입력 오류
set -uo pipefail

SELF_REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
REPO="$SELF_REPO"; MACHINE=""; CAND="${FPM_RELEASE_CANDIDATE:-}"
die2() { echo "⛔ $*"; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --machine|--candidate|--repo)
      [ $# -ge 2 ] || die2 "$1 값 필요"
      case "$1" in --machine) MACHINE="$2" ;; --candidate) CAND="$2" ;; --repo) REPO="$2" ;; esac
      shift 2 ;;
    -h|--help) sed -n 's/^# 사용: //p' "$0"; exit 0 ;;
    *) die2 "알 수 없는 인자: $1" ;;
  esac
done
[ -n "$MACHINE" ] || die2 "--machine <id> 필요 (tdd/machines.yml 의 id)"

# ── 명부 조회 — platform·status 는 machines.yml 이 SSOT ──
MYML="$REPO/tdd/machines.yml"
[ -f "$MYML" ] || die2 "머신 명부 없음: $MYML"
read -r PLATFORM STATUS < <(awk -v id="$MACHINE" '
  /^[[:space:]]*- id:/        { cur = $3; next }
  cur == id && /^[[:space:]]*platform:/ { p = $2 }
  cur == id && /^[[:space:]]*status:/   { s = $2 }
  END { if (p != "") print p, (s == "" ? "active" : s) }' "$MYML")
[ -n "${PLATFORM:-}" ] || die2 "machines.yml 에 없는 id: $MACHINE"

# ── 후보 — 입력 오류는 머신에 닿기 전에 가른다 ──
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || die2 "git repo 아님: $REPO"
SHA="$(git -C "$REPO" rev-parse --verify -q "${CAND:-HEAD}^{commit}")" || die2 "후보 커밋 해석 실패: ${CAND:-HEAD}"
SHA7="${SHA:0:7}"; TREE="$(git -C "$REPO" rev-parse "$SHA^{tree}")"

MAIN="${FPM_RELEASE_MAIN_REPO:-$REPO}"
RES_ROOT="${FPM_TDD_RESULTS_DIR:-$MAIN/tdd/results}"
START="$(date +%s)"
SSH="${FPM_TDD_SSH_BIN:-ssh}"; SCP="${FPM_TDD_SCP_BIN:-scp}"
SO=(-o BatchMode=yes -o ConnectTimeout="${FPM_TDD_CONNECT_TIMEOUT:-8}")
LT=""; RD=""; TARGET=""

cleanup() {
  if [ -n "$RD" ]; then
    # 삭제 대상이 우리가 만든 형식일 때만 지운다 — 빈 값·엉뚱한 경로로 rm -rf 가 나가지 않게
    case "$RD" in
      */fpm-remote.*) "$SSH" "${SO[@]}" "$TARGET" "rm -rf '$RD'" >/dev/null 2>&1 \
                        || echo "⚠️ 원격 정리 실패: $MACHINE:$RD — 수동 삭제 필요" ;;
      *) echo "⚠️ 원격 경로가 예상 형식이 아니라 지우지 않음: $RD" ;;
    esac
    RD=""
  fi
  [ -n "$LT" ] && rm -rf "$LT"; LT=""
}
trap cleanup EXIT
# 판정 줄은 **마지막 줄**이어야 한다 — playlist-run.py 가 출력 끝 줄을 증거 비고로 쓴다.
#   그래서 정리를 먼저 끝내고(경고도 그 앞에 찍히게) 판정을 찍는다.
finish() {  # $1 pass|fail|partial  $2 상세  $3 exit
  cleanup; trap - EXIT
  echo "native-$PLATFORM $MACHINE candidate=$SHA7 result=$1${2:+ — $2} ($(( $(date +%s) - START ))s)"
  exit "$3"
}

[ "$STATUS" = active ] || finish partial "machines.yml status=$STATUS — 아직 편입 전 머신" 3

# ── 로컬 설정 → ssh 대상·기동 명령 ──
CONF="${FPM_TDD_REMOTE_CONF:-}"
if [ -z "$CONF" ]; then
  for c in "$MAIN/tdd/remote.local.sh" "$REPO/tdd/remote.local.sh"; do
    [ -f "$c" ] && { CONF="$c"; break; }
  done
fi
if [ -n "$CONF" ]; then
  [ -f "$CONF" ] || die2 "로컬 설정 없음: $CONF"
  # shellcheck disable=SC1090
  . "$CONF"
fi
KEY="$(printf '%s' "$MACHINE" | tr -c 'A-Za-z0-9_' '_')"   # eval 에 들어가므로 식별자 문자만
eval "TARGET=\${FPM_TDD_SSH_$KEY:-}"; TARGET="${TARGET:-$MACHINE}"
eval "WAKE=\${FPM_TDD_WAKE_$KEY:-}"
[ -z "$WAKE" ] && [ -n "${FPM_TDD_WAKE_CMD:-}" ] && WAKE="$FPM_TDD_WAKE_CMD $MACHINE"

# ── ① 기동 ──
reach() { "$SSH" "${SO[@]}" "$TARGET" true >/dev/null 2>&1; }
if ! reach; then
  [ -n "$WAKE" ] || finish partial "ssh 무응답 — 기동 명령 미설정(FPM_TDD_WAKE_$KEY)" 3
  echo "… $MACHINE ssh 무응답 — 기동 명령 실행"
  bash -c "$WAKE" || finish partial "ssh 무응답 — 기동 명령 실패(rc $?)" 3
  WAIT="${FPM_TDD_WAKE_TIMEOUT:-240}"; deadline=$(( $(date +%s) + WAIT ))
  until reach; do
    [ "$(date +%s)" -lt "$deadline" ] || finish partial "기동 후 ${WAIT}s 안에 ssh 무응답" 3
    sleep "${FPM_TDD_WAKE_POLL:-10}"
  done
fi

# ── ② 반송 — 이력 없는 단일 커밋 ──
LT="$(mktemp -d "${TMPDIR:-/tmp}/fpm-rlocal.XXXXXX")"
mkdir -p "$LT/src"
git -C "$REPO" archive "$SHA" | tar -x -C "$LT/src" || finish fail "후보 트리 추출 실패" 1
# add -f: 원본에서 추적 중인 파일이 트리 안 .gitignore 에 걸려도 빠지지 않게(트리 동일성 조건)
# hooksPath=/dev/null: 전역 hook(graphify·tagcheck 등)이 임시 repo 에서 돌지 않게
( cd "$LT/src" && git init -q && git add -A -f . \
  && GIT_AUTHOR_NAME=fpm-remote GIT_AUTHOR_EMAIL=fpm-remote@localhost \
     GIT_COMMITTER_NAME=fpm-remote GIT_COMMITTER_EMAIL=fpm-remote@localhost \
     git -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -q -m "fpm remote candidate $SHA" ) \
  || finish fail "후보 단일 커밋 구성 실패" 1
[ "$(git -C "$LT/src" rev-parse 'HEAD^{tree}')" = "$TREE" ] || finish fail "재구성 트리 ≠ 후보 트리" 1
git -C "$LT/src" bundle create "$LT/c.bundle" HEAD >/dev/null 2>&1 || finish fail "bundle 생성 실패" 1

RD="$("$SSH" "${SO[@]}" "$TARGET" 'mktemp -d "${TMPDIR:-/tmp}/fpm-remote.XXXXXX"' 2>/dev/null | tail -1 | tr -d '\r')"
case "$RD" in */fpm-remote.*) ;; *) RD=""; finish partial "원격 임시 디렉토리 생성 실패" 3 ;; esac
"$SCP" -q "${SO[@]}" "$LT/c.bundle" "$TARGET:$RD/c.bundle" >/dev/null 2>&1 \
  || finish partial "번들 전송 실패" 3

# ── ③ 실행 — 원격 스크립트는 stdin 으로 보낸다(후보 트리에 없어도 돈다) ──
# 결과는 `FPMR k=v` 줄로 돌려받는다. 원격 로그 본문은 ④ 에서 파일로 회수한다.
read -r -d '' PAYLOAD <<'REMOTE'
set -uo pipefail
RD="$1"; export FPM_RELEASE_CANDIDATE="$2"
# 원격 네이티브 실행 표식 — 이 머신의 ~/.claude 는 저작 라이브 소스가 아니다(케이스 bundle-in-sync 가 본다)
export FPM_TDD_NATIVE_REMOTE=1
cd "$RD" || exit 20
git clone -q c.bundle src >"$RD/clone.log" 2>&1 || { echo "FPMR clone=fail"; exit 21; }
cd src
echo "FPMR tree=$(git rev-parse 'HEAD^{tree}') history=$(git rev-list --count HEAD)"
bash tdd/run-tdd.sh >"$RD/tdd.log" 2>&1; t=$?
echo "FPMR tdd_rc=$t"
SBX="$(mktemp -d "$RD/home.XXXXXX")"; f=0
# Issue585: HOME 만 바꾸면 AOA_MEMORY_DIR 이 운영값으로 상속돼 bootstrap 이 운영 aoa 폴더에 쓴다 — 데이터 루트도 샌드박스로
sb() { env HOME="$SBX" FPM_BACKUP_DIR="$SBX/backup" AOA_MEMORY_DIR="$SBX/.claude/data/aoa" AOA_MQ_DIR="$SBX/.claude/data/aoa/mq" bash "$@"; }
{
  if sb sh/install.sh --no-scar; then echo "install PASS"; else echo "install FAIL"; f=$((f+1)); fi
  if sb sh/check.sh --no-scar;   then echo "check PASS";   else echo "check FAIL";   f=$((f+1)); fi
  if sb sh/uninstall.sh;         then echo "uninstall PASS"; else echo "uninstall FAIL"; f=$((f+1)); fi
} >"$RD/sandbox.log" 2>&1
echo "FPMR sandbox_fail=$f"
[ "$t" -eq 0 ] && [ "$f" -eq 0 ]
REMOTE
"$SSH" "${SO[@]}" "$TARGET" "bash -s -- '$RD' '$SHA'" <<<"$PAYLOAD" >"$LT/remote.out" 2>&1; prc=$?

# ── ④ 회수 ──
RES="$RES_ROOT/remote-$(date +%Y%m%d_%H%M%S)-$MACHINE"
mkdir -p "$RES" && cp "$LT/remote.out" "$RES/remote.out"
"$SCP" -q "${SO[@]}" "$TARGET:$RD/*.log" "$RES/" >/dev/null 2>&1 \
  || echo "⚠️ 원격 로그 회수 실패 — 판정은 remote.out 기준"

# awk 로 토큰 단위 조회 — BSD sed 는 \b 를 모른다(macOS 에서 조용히 빈 값이 됐다)
kv() { awk -v k="$1" '/^FPMR /{ for (i = 2; i <= NF; i++) if (index($i, k "=") == 1) v = substr($i, length(k) + 2) }
                      END { print v }' "$LT/remote.out"; }
R_TREE="$(kv tree)"; R_HIST="$(kv history)"; R_TDD="$(kv tdd_rc)"; R_SBX="$(kv sandbox_fail)"
# ssh 자체가 끊기면 rc 255 — 머신 문제이지 후보의 실패가 아니다(PASS 로도 FAIL 로도 세지 않는다)
[ "$prc" -eq 255 ] && [ -z "$R_TDD" ] && finish partial "원격 실행 중 ssh 끊김(rc 255)" 3
[ -n "$R_TREE" ] || finish fail "원격 clone 실패 — $RES/clone.log" 1
TREE_OK=ok; [ "$R_TREE" = "$TREE" ] || TREE_OK="불일치"
SUM="tree=$TREE_OK history=${R_HIST:-?} tdd_rc=${R_TDD:-?} sandbox_fail=${R_SBX:-?}"
[ "$TREE_OK" = ok ] || finish fail "$SUM — 원격 트리가 후보와 다르다" 1
[ "${R_HIST:-}" = 1 ] || finish fail "$SUM — 이력이 함께 반출됐다" 1
if [ "$prc" -ne 0 ]; then
  [ -f "$RES/tdd.log" ] && grep -E 'FAIL' "$RES/tdd.log" | head -5 | sed 's/^/  /'
  finish fail "$SUM · 로그 $RES" 1
fi
finish pass "$SUM" 0
