#!/bin/bash
# test_os_test_ctl_issue652.sh — Issue652 회귀 테스트 (구동기 scripts/os-test-ctl.sh)
#
# 구동기가 «clear 하면 반드시 복귀한다» 는 순서를 지키고, 접속 단일 경로(mDNS 사망)에 막히지 않는지 본다.
#   ① plan = 복구 페이로드를 인자 없이 보낸다(읽기 전용) · restore 는 --stamp 필수, --dry-run 전달
#   ② clear = 페이로드 → 복귀 순서. 페이로드가 실패(11)해도 복귀한다 · 비우기 전 중단(10)이면 복귀 생략
#   ③ --keep 이면 복귀하지 않고 복귀 명령을 안내한다 · 복귀가 실패하면 result=fail
#   ④ 접속: ssh 별칭 → tailscale IP 폴백 → 기동 명령 → 전부 실패면 페이로드를 보내지 않고 rc 3
#   ⑤ 로컬 설정(tdd/remote.local.sh) 매핑·셸 지정 · 인자 검증(주입 방지) · 호스트명 하드코딩 금지
#
# 격리: 가짜 ssh·tailscale. 실물 구동기를 돈다.
# 실행: bash scripts/test_os_test_ctl_issue652.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CTL="$REPO/scripts/os-test-ctl.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/os-ctl.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
has()  { if printf '%s' "$2" | grep -qF -- "$3"; then ok "$1"; else fail "$1 (없음: '$3')"; fi; }
hasnt(){ if printf '%s' "$2" | grep -qF -- "$3"; then fail "$1 (있으면 안 됨: '$3')"; else ok "$1"; fi; }

echo "[test_os_test_ctl_issue652]"
[ -f "$CTL" ] && ok "구동기 존재" || fail "구동기 없음 — scripts/os-test-ctl.sh"

# ── 가짜 ssh / tailscale ─────────────────────────────────────────────────────────────
BIN="$SB/bin"; mkdir -p "$BIN"
cat > "$BIN/ssh" <<'EOF'
#!/bin/bash
# 옵션(-o X)을 건너뛰고 첫 인자=대상, 나머지=원격 명령
while [ "${1:-}" = "-o" ]; do shift 2; done
target="$1"; shift; cmd="$*"
echo "ssh $target :: $cmd" >> "$FAKE_LOG"
for u in ${FAKE_UNREACHABLE:-}; do [ "$target" = "$u" ] && exit 255; done
if [ -n "${FAKE_NEED_WAKE:-}" ] && [ "$target" = "$FAKE_NEED_WAKE" ] && [ ! -f "$FAKE_DIR/awake" ]; then exit 255; fi
[ "$cmd" = true ] && exit 0
body="$(cat)"
name="$(printf '%s\n' "$body" | sed -n '2p' | grep -oE 'os-test-[a-z-]+\.sh' | head -1)"
echo "payload=$name args=${cmd#*-- }" >> "$FAKE_LOG"
case "$name" in
  os-test-payload.sh)         echo "FPMT fake_payload"; exit "${FAKE_RC_PAYLOAD:-0}" ;;
  os-test-restore-payload.sh) echo "FPMT fake_restore"; exit "${FAKE_RC_RESTORE:-0}" ;;
  *) echo "FPMT unknown_payload"; exit 99 ;;
esac
EOF
cat > "$BIN/tailscale" <<'EOF'
#!/bin/bash
[ "$1" = ip ] || exit 1
name="${@: -1}"
for k in ${FAKE_TS_KNOWN:-}; do [ "$k" = "$name" ] && { echo 100.1.1.1; exit 0; }; done
exit 1
EOF
chmod +x "$BIN/ssh" "$BIN/tailscale"

run() {   # 환경은 호출 앞에 VAR=… 로. 출력 + rc= 마지막 줄
    local out rc
    out="$(cd "$SB" && PATH="$BIN:$PATH" FAKE_LOG="$SB/calls.log" FAKE_DIR="$SB" \
        FPM_TDD_SSH_BIN="$BIN/ssh" OSTEST_TS_BIN="$BIN/tailscale" OSTEST_LOG_DIR="$SB/logs" \
        FPM_TDD_REMOTE_CONF="${CONF:-/dev/null}" FPM_TDD_CONNECT_TIMEOUT=1 FPM_TDD_WAKE_POLL=0 FPM_TDD_WAKE_TIMEOUT=2 \
        "$@" 2>&1)"; rc=$?
    printf '%s\nrc=%s\n' "$out" "$rc"
}
calls() { cat "$SB/calls.log" 2>/dev/null; }
reset() { rm -f "$SB/calls.log" "$SB/awake"; unset FAKE_UNREACHABLE FAKE_NEED_WAKE FAKE_TS_KNOWN FAKE_RC_PAYLOAD FAKE_RC_RESTORE CONF; }
export -n FAKE_LOG 2>/dev/null

# ① plan·restore
reset
OUT="$(run bash "$CTL" plan hostA)"
has "① plan rc 0(복구 페이로드의 rc 2 는 정상)" "$OUT" "rc=0"
has "① plan 은 복구 페이로드를 보낸다" "$(calls)" "payload=os-test-restore-payload.sh"
hasnt "① plan 은 clear 페이로드를 보내지 않는다" "$(calls)" "payload=os-test-payload.sh"
hasnt "① plan 은 --stamp 를 주지 않는다" "$(calls)" "--stamp"

reset; OUT="$(run bash "$CTL" restore hostA)"
has "① restore 는 --stamp 없으면 rc 2" "$OUT" "rc=2"
check "① --stamp 없으면 ssh 를 부르지 않는다" "$(calls)" ""

reset; OUT="$(run bash "$CTL" restore hostA --stamp 2026.10.18_1513 --dry-run)"
has "① restore rc 0" "$OUT" "rc=0"
has "① --stamp 전달" "$(calls)" "--stamp 2026.10.18_1513"
has "① --dry-run 전달" "$(calls)" "--dry-run"

# ② clear
reset; OUT="$(run bash "$CTL" clear hostA --tag v0.8.3 --stamp 2026.10.21_1700)"
has "② clear 정상 rc 0" "$OUT" "rc=0"
has "② result=pass" "$OUT" "result=pass"
P1="$(grep -n 'payload=os-test-payload.sh' "$SB/calls.log" | head -1 | cut -d: -f1)"; P2="$(grep -n 'payload=os-test-restore-payload.sh' "$SB/calls.log" | head -1 | cut -d: -f1)"
[ -n "$P1" ] && [ -n "$P2" ] && [ "$P1" -lt "$P2" ] && ok "② clear 페이로드 → 복귀 순서" || fail "② 순서 위반 (clear=$P1 restore=$P2)"
has "② clear 에 태그·스탬프 전달" "$(calls)" "args=v0.8.3 2026.10.21_1700"
has "② 복귀에 같은 스탬프 전달" "$(calls)" "--stamp 2026.10.21_1700"

reset; FAKE_RC_PAYLOAD=11 OUT="$(run env FAKE_RC_PAYLOAD=11 bash "$CTL" clear hostA --tag v0.8.3 --stamp S1)"
has "② 페이로드 실패(11)여도 복귀한다" "$(calls)" "payload=os-test-restore-payload.sh"
has "② 페이로드 실패면 result=fail" "$OUT" "result=fail"
has "② rc 1" "$OUT" "rc=1"

reset; OUT="$(run env FAKE_RC_PAYLOAD=10 bash "$CTL" clear hostA --tag v0.8.3 --stamp S1)"
hasnt "② 비우기 전 중단(10)이면 복귀를 생략" "$(calls)" "payload=os-test-restore-payload.sh"
has "② 생략 사유 표시" "$OUT" "비우기 전"

# ③ --keep · 복귀 실패
reset; OUT="$(run bash "$CTL" clear hostA --tag v0.8.3 --stamp S2 --keep)"
hasnt "③ --keep 은 복귀하지 않는다" "$(calls)" "payload=os-test-restore-payload.sh"
has "③ --keep 은 복귀 명령을 안내" "$OUT" "os-test-ctl.sh restore hostA --stamp S2"

reset; OUT="$(run env FAKE_RC_RESTORE=1 bash "$CTL" clear hostA --tag v0.8.3 --stamp S3)"
has "③ 복귀 실패면 result=fail" "$OUT" "result=fail"
has "③ 복귀 실패면 rc 1" "$OUT" "rc=1"

# ④ 접속
reset; OUT="$(run env FAKE_UNREACHABLE=hostA FAKE_TS_KNOWN=hostA bash "$CTL" plan hostA)"
has "④ 별칭 실패 → tailscale IP 폴백" "$(calls)" "100.1.1.1 :: "
has "④ 폴백으로 페이로드 전달" "$(calls)" "payload=os-test-restore-payload.sh"
has "④ 폴백 rc 0" "$OUT" "rc=0"

reset; OUT="$(run env FAKE_UNREACHABLE="hostA" bash "$CTL" clear hostA --tag v0.8.3 --stamp S4)"
has "④ 전부 불통이면 rc 3" "$OUT" "rc=3"
hasnt "④ 불통이면 페이로드를 보내지 않는다" "$(calls)" "payload="
has "④ 불통 안내" "$OUT" "접속"

reset; CONF="$SB/wake.conf"; printf 'FPM_TDD_WAKE_hostB="echo woke >> %s/wake.log; touch %s/awake"\n' "$SB" "$SB" > "$CONF"; rm -f "$SB/wake.log"
OUT="$(run env CONF="$CONF" FPM_TDD_REMOTE_CONF="$CONF" FAKE_NEED_WAKE=hostB bash "$CTL" plan hostB)"
[ -s "$SB/wake.log" ] && ok "④ 불통이면 기동 명령 실행" || fail "④ 기동 명령이 실행되지 않았다"
has "④ 기동 후 접속·rc 0" "$OUT" "rc=0"

# ⑤ 로컬 설정 매핑·셸·검증
reset; CONF="$SB/map.conf"; printf "FPM_TDD_SSH_win_x=realhost\nFPM_TDD_SHELL_win_x='bash -l -s'\n" > "$CONF"
OUT="$(run env FPM_TDD_REMOTE_CONF="$CONF" bash "$CTL" plan win-x)"
has "⑤ 머신 id → ssh 대상 매핑" "$(calls)" "ssh realhost ::"
has "⑤ 머신별 원격 셸 지정(bash -l -s)" "$(calls)" "bash -l -s --"

reset; OUT="$(run bash "$CTL" clear hostA --tag 'v1;rm -rf ~' --stamp S5)"
has "⑤ 태그에 셸 메타문자 → rc 2" "$OUT" "rc=2"
check "⑤ 검증 실패면 ssh 를 부르지 않는다" "$(calls)" ""
reset; OUT="$(run bash "$CTL" restore hostA --stamp '$(id)')"
has "⑤ 스탬프에 셸 메타문자 → rc 2" "$OUT" "rc=2"

reset; OUT="$(run bash "$CTL" bogus hostA)"; has "⑤ 알 수 없는 명령 rc 2" "$OUT" "rc=2"

# 호스트명 하드코딩 금지 — 공개 미러로 나가는 파일 (run-remote.sh 와 같은 규약)
HN="$(grep -nE '\b(jma|jpc1|fg1|jm4)\b' "$REPO/scripts/os-test-ctl.sh" "$REPO/scripts/os-test-restore-payload.sh" 2>/dev/null | head -3)"
[ -z "$HN" ] && ok "⑤ 새 스크립트에 호스트명 하드코딩 없음" || fail "⑤ 호스트명 하드코딩: $HN"

echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
