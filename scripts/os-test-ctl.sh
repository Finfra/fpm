#!/usr/bin/env bash
# os-test-ctl.sh — OS 테스트 clear · 복귀 · 긴급 복구 구동기 (Issue652 · 설계 _doc_arch/fpm-release-test.md "F-4")
#
# 묻는 것: *"clear 하고 나서 그 서버를 원래대로 돌려놓았는가, 접속이 막혀도 돌려놓을 수 있는가."*
#   페이로드 2종을 대상 머신에 stdin 으로 보낸다(후보 트리·미러에 없어도 돈다):
#     scripts/os-test-payload.sh          clear → 태그 clean clone 설치 → 테스트   (비우기만 한다)
#     scripts/os-test-restore-payload.sh  복귀 — clear 이전 상태로 되돌림         (plan·restore·dry-run)
#
# 사용:
#   os-test-ctl.sh plan    <host>                               복구 후보 표 — 읽기 전용 (스탬프별 missing/differs)
#   os-test-ctl.sh restore <host> --stamp S [--dry-run]         긴급 복구 — 지정 스탬프의 clear 이전 상태로
#   os-test-ctl.sh clear   <host> --tag vX.Y.Z [--stamp S] [--keep]
#                                                              clear → 설치·테스트 → **항상** 복귀 (--keep 이면 복귀 생략)
#
# <host>: ssh 별칭, 또는 tdd/machines.yml 의 머신 id(id 의 '-' 는 '_').
#   호스트명은 이 파일에 쓰지 않는다 — 공개 미러로 나간다. 로컬 설정 `tdd/remote.local.sh`(gitignore) 규약을 재사용:
#     FPM_TDD_SSH_<id>=<ssh 대상>   FPM_TDD_WAKE_<id>='<기동 명령>'   FPM_TDD_SHELL_<id>='<원격 셸>'(기본 bash -s · Windows 는 'bash -l -s')
#     FPM_TDD_TS_<id>=<tailscale 이름>  (없으면 ssh 대상 이름 그대로)
# 접속: ssh 대상 → (실패) tailscale IP 로 재시도 → (실패) 기동 명령 후 둘 다 재시도 → 전부 실패면 rc 3, 페이로드는 보내지 않는다
#   — mDNS(.local) 한 길에 의존하면 그 길이 죽을 때 ssh·동기화가 같이 죽는다 (2026-10-21)
# 로그: _doc_work/z_log/os-test-ctl/<host>-<cmd>-<시각>.log  (OSTEST_LOG_DIR 로 변경)
# exit: 0 성공 · 1 실패(페이로드 또는 복귀) · 2 입력 오류 · 3 접속 불가
set -uo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; REPO="$(cd "$SELF/.." && pwd)"
PAYLOAD_CLEAR="$SELF/os-test-payload.sh"; PAYLOAD_RESTORE="$SELF/os-test-restore-payload.sh"
die2() { echo "⛔ $*" >&2; exit 2; }
usage() { sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^사용:/,/^<host>:/p' | sed '$d'; }

CMD="${1:-}"; case "$CMD" in -h|--help|"") usage; [ -n "$CMD" ] && exit 0; exit 2 ;; esac
HOST="${2:-}"; [ -n "$HOST" ] || die2 "<host> 필요"
shift 2
TAG=""; STAMP=""; KEEP=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tag|--stamp) [ $# -ge 2 ] || die2 "$1 값 필요"
                   case "$1" in --tag) TAG="$2" ;; --stamp) STAMP="$2" ;; esac; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) die2 "알 수 없는 인자: $1" ;;
  esac
done
case "$CMD" in plan|restore|clear) ;; *) die2 "알 수 없는 명령: $CMD (plan|restore|clear)" ;; esac
# 원격 셸 명령줄에 들어가는 값이다 — 식별자 문자만 받는다 (주입 방지)
valid() { printf '%s' "$1" | grep -qE '^[A-Za-z0-9._-]+$'; }
[ -z "$TAG" ]   || valid "$TAG"   || die2 "--tag 에 허용되지 않는 문자: $TAG"
[ -z "$STAMP" ] || valid "$STAMP" || die2 "--stamp 에 허용되지 않는 문자: $STAMP"
[ "$CMD" != restore ] || [ -n "$STAMP" ] || die2 "restore 는 --stamp 필수 — 먼저 'os-test-ctl.sh plan $HOST' 로 후보를 본다"
[ "$CMD" != clear ] || [ -n "$TAG" ] || die2 "clear 는 --tag 필수 (ex: v0.8.3)"
[ "$CMD" != clear ] || [ -n "$STAMP" ] || STAMP="$(date +%Y.%m.%d_%H%M)"
[ -f "$PAYLOAD_RESTORE" ] || die2 "복귀 페이로드 없음: $PAYLOAD_RESTORE"
[ "$CMD" != clear ] || [ -f "$PAYLOAD_CLEAR" ] || die2 "clear 페이로드 없음: $PAYLOAD_CLEAR"

# ── 로컬 설정 → ssh 대상·기동 명령·원격 셸 (run-remote.sh 와 같은 규약) ──
MAIN="${FPM_RELEASE_MAIN_REPO:-$REPO}"
CONF="${FPM_TDD_REMOTE_CONF:-}"
if [ -z "$CONF" ]; then for c in "$MAIN/tdd/remote.local.sh" "$REPO/tdd/remote.local.sh"; do [ -f "$c" ] && { CONF="$c"; break; }; done; fi
# shellcheck disable=SC1090
[ -n "$CONF" ] && [ -f "$CONF" ] && . "$CONF"
KEY="$(printf '%s' "$HOST" | tr -c 'A-Za-z0-9_' '_')"   # eval 에 들어가므로 식별자 문자만
eval "TARGET=\${FPM_TDD_SSH_$KEY:-}"; TARGET="${TARGET:-$HOST}"
eval "WAKE=\${FPM_TDD_WAKE_$KEY:-}"
[ -z "$WAKE" ] && [ -n "${FPM_TDD_WAKE_CMD:-}" ] && WAKE="$FPM_TDD_WAKE_CMD $HOST"
eval "RSHELL=\${FPM_TDD_SHELL_$KEY:-}"; RSHELL="${RSHELL:-bash -s}"
eval "TSNAME=\${FPM_TDD_TS_$KEY:-}"; TSNAME="${TSNAME:-${TARGET##*@}}"

SSH="${FPM_TDD_SSH_BIN:-ssh}"; TS="${OSTEST_TS_BIN:-tailscale}"
SO=(-o BatchMode=yes -o ConnectTimeout="${FPM_TDD_CONNECT_TIMEOUT:-8}")
SO_RUN=(-o BatchMode=yes -o ServerAliveInterval=30)   # 긴 실행: 연결 타임아웃은 걸지 않고 끊김만 감지

LOGDIR="${OSTEST_LOG_DIR:-$MAIN/_doc_work/z_log/os-test-ctl}"; mkdir -p "$LOGDIR" 2>/dev/null
LOG="$LOGDIR/$HOST-$CMD-$(date +%Y%m%d_%H%M%S).log"

reach() { "$SSH" "${SO[@]}" "$1" true >/dev/null 2>&1; }
ts_target() {   # tailscale IP 로 만든 ssh 대상 — user@ip (사용자는 ssh 대상의 user@ 또는 현재 사용자)
  local ip user; ip="$("$TS" ip -4 "$TSNAME" 2>/dev/null | head -1)"; [ -n "$ip" ] || return 1
  case "$TARGET" in *@*) user="${TARGET%@*}" ;; *) user="${OSTEST_USER:-$(id -un)}" ;; esac
  echo "$user@$ip"
}
USE=""
connect() {
  local alt
  if reach "$TARGET"; then USE="$TARGET"; return 0; fi
  if alt="$(ts_target)" && reach "$alt"; then USE="$alt"; echo "… $HOST: ssh 대상 불통 — tailscale 경로($alt)로 접속" >&2; return 0; fi
  if [ -n "$WAKE" ]; then
    echo "… $HOST: 접속 불통 — 기동 명령 실행" >&2
    bash -c "$WAKE" || echo "⚠️ 기동 명령 실패(rc $?)" >&2
    local deadline=$(( $(date +%s) + ${FPM_TDD_WAKE_TIMEOUT:-240} ))
    until reach "$TARGET" || { alt="$(ts_target)" && reach "$alt"; }; do
      [ "$(date +%s)" -lt "$deadline" ] || return 1
      sleep "${FPM_TDD_WAKE_POLL:-10}"
    done
    if reach "$TARGET"; then USE="$TARGET"; else USE="$alt"; fi
    return 0
  fi
  return 1
}

# 페이로드 전송 — $1=스크립트 나머지=페이로드 인자. 출력은 화면+로그. rc 는 원격 rc
run_remote() {
  local script="$1"; shift
  "$SSH" "${SO_RUN[@]}" "$USE" "$RSHELL -- $*" < "$script" 2>&1 | tee -a "$LOG"
  return "${PIPESTATUS[0]}"
}

if ! connect; then
  echo "⛔ $HOST: 접속 불가 (ssh '$TARGET' · tailscale '$TSNAME'${WAKE:+ · 기동 명령 실행 후에도}) — 페이로드를 보내지 않았다" >&2
  echo "   확인: tailscale status · ssh -o ConnectTimeout=5 $TARGET true" >&2
  [ "$CMD" = clear ] || echo "   접속이 돌아오면 이 명령을 다시 실행한다" >&2
  exit 3
fi
echo "▶ os-test-ctl $CMD host=$HOST via=$USE log=$LOG" | tee -a "$LOG"

case "$CMD" in
  plan)
    run_remote "$PAYLOAD_RESTORE"; rc=$?
    [ "$rc" -eq 2 ] && exit 0      # 복구 페이로드의 plan 은 rc 2(복원 안 함)가 정상이다
    exit "$rc" ;;
  restore)
    DRYARG=""; [ "$DRY" = 1 ] && DRYARG="--dry-run"
    run_remote "$PAYLOAD_RESTORE" --stamp "$STAMP" $DRYARG; rc=$?
    echo "os-test-ctl restore $HOST stamp=$STAMP rc=$rc" | tee -a "$LOG"
    exit "$rc" ;;
  clear)
    run_remote "$PAYLOAD_CLEAR" "$TAG" "$STAMP"; prc=$?
    rrc="skip"; why=""
    if [ "$prc" -eq 10 ]; then
      why="페이로드가 비우기 전에 중단(rc 10) — 바뀐 것이 없어 복귀 생략"
    elif [ "$KEEP" = 1 ]; then
      why="--keep — 복귀 생략. 서버가 테스트 상태다. 복귀: os-test-ctl.sh restore $HOST --stamp $STAMP"
    else
      # 접속이 끊겼을 수 있다 — 다시 잇는다. 못 이으면 복귀 명령을 남기고 실패로 끝낸다
      if connect; then
        run_remote "$PAYLOAD_RESTORE" --stamp "$STAMP"; rrc=$?
      else
        rrc=3; why="복귀 실패 — 접속 불가. 접속이 돌아오면: os-test-ctl.sh restore $HOST --stamp $STAMP"
      fi
    fi
    res=pass; [ "$prc" -eq 0 ] || res=fail; case "$rrc" in skip|0) ;; *) res=fail ;; esac
    [ -z "$why" ] || echo "ℹ️  $why" | tee -a "$LOG"
    echo "os-test-ctl clear $HOST stamp=$STAMP payload_rc=$prc restore_rc=$rrc result=$res" | tee -a "$LOG"
    [ "$res" = pass ] && exit 0 || exit 1 ;;
esac
