#!/bin/bash
# test_deploy_lockstep_issue607.sh — Issue607 회귀 테스트
#
# 출고·라인 마감이 prj1 단독이던 결함(v0.8.4 1차 출고: prj1 만 release/0.8.5 로 넘어가고 prj3 는 release/0.8.4 에 남음)과
# 소비자 전파가 상주 hub 를 재기동하지 않던 결함을 막는다.
#   ① prj3 선검사: VERSION·브랜치가 prj1 라인과 같으면 통과
#   ② prj3 VERSION 이 다르면 거부(rc≠0)
#   ③ prj3 브랜치가 라인(release/<VERSION>)도 prj1 현재 브랜치도 아니면 거부
#   ④ prj3 저장소 없음 → fail-closed 거부 · FPM_SKIP_PRJ3_LOCKSTEP=1 만 우회
#   ⑤ prj3 소스 태그: HEAD 에 v<VER> · 다른 커밋에 이미 있으면 옮기지 않음
#   ⑥ do_deploy 배선(정적): 선검사는 번호 승인 게이트·bump 앞 · prj3 태그는 src 태그 뒤
#   ⑦ 소비자 전파 표준 명령 fpm-consumer-propagate.sh --dry-run: 머신마다 갱신→hub 재기동→healthz 단계가 나온다
#      (fg1=systemctl · jma=pid 종료 후 절대경로 기동 · jpc1=Git Bash 표준입력)
#   ⑧ 전파 페이로드는 재기동 뒤 healthz 가 200 이 아니면 rc≠0 (거짓 성공 금지)
#
# 격리: 임시 git repo. 대상 함수는 실물 scripts/fpm-sync.sh 에서 **추출**해 eval 한다(재구현 금지).
# 실행: bash scripts/test_deploy_lockstep_issue607.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SYNC="$REPO/scripts/fpm-sync.sh"
PROP="$REPO/scripts/fpm-consumer-propagate.sh"
PAY="$REPO/scripts/fpm-consumer-propagate-payload.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/lockstep607.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
has()  { if printf '%s' "$2" | grep -qE -- "$3"; then ok "$1"; else fail "$1 (패턴 '$3' 없음)"; fi; }

echo "[test_deploy_lockstep_issue607]"
export GIT_CONFIG_GLOBAL=/dev/null

FUNCS="$SB/funcs.sh"
for fn in prj3_lockstep_gate prj3_tag_release; do
    awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {p=1} p {print} p && /^}/ {p=0}' "$SYNC" >> "$FUNCS"
done
[ -s "$FUNCS" ] || echo "  (함수 추출 0 — 미구현)"

G() { git -C "$1" -c user.name=t -c user.email=t@t "${@:2}"; }
S="$SB/src"; P="$SB/prj3"
mkdir -p "$S" "$P"
echo 0.8.3 > "$S/VERSION"; git -C "$S" init -q -b main; G "$S" add -A; G "$S" commit -q -m s0
echo 0.8.3 > "$P/VERSION"; git -C "$P" init -q -b release/0.8.3; G "$P" add -A; G "$P" commit -q -m p0

run() {
    ( SRC="$S"; PRJ3_DIR="${PRJ3_DIR:-$P}"; VERSION_REL=VERSION
      log() { printf '%s\n' "$1"; }
      . "$FUNCS" 2>/dev/null
      "$@" )
}

# ① 일치
out="$(run prj3_lockstep_gate 0.8.3 2>&1)"; rc=$?
check "① VERSION·라인 일치 → 통과" "$rc" "0"

# ② VERSION 불일치
echo 0.8.4 > "$P/VERSION"; G "$P" commit -qam v
out="$(run prj3_lockstep_gate 0.8.3 2>&1)"; rc=$?
check "② prj3 VERSION 다름 → 거부" "$rc" "1"
has "②' 사유에 두 VERSION 이 나온다" "$out" "0\.8\.4.*0\.8\.3|0\.8\.3.*0\.8\.4"
echo 0.8.3 > "$P/VERSION"; G "$P" commit -qam v

# ③ 브랜치 불일치(라인도 아니고 prj1 브랜치(main)도 아님)
git -C "$P" switch -q -c release/0.8.4
out="$(run prj3_lockstep_gate 0.8.3 2>&1)"; rc=$?
check "③ prj3 브랜치가 라인 밖 → 거부" "$rc" "1"
has "③' 사유에 prj3 브랜치명" "$out" "release/0\.8\.4"
git -C "$P" switch -q release/0.8.3

# prj3 가 prj1 과 같은 이름 브랜치(main)여도 통과
git -C "$P" switch -q -c main
out="$(run prj3_lockstep_gate 0.8.3 2>&1)"; rc=$?
check "③'' prj3 가 prj1 현재 브랜치(main)와 같으면 통과" "$rc" "0"
git -C "$P" switch -q release/0.8.3

# ④ 저장소 없음 fail-closed · 우회는 env
out="$(PRJ3_DIR="$SB/none" run prj3_lockstep_gate 0.8.3 2>&1)"; rc=$?
check "④ prj3 저장소 없음 → fail-closed" "$rc" "1"
out="$(FPM_SKIP_PRJ3_LOCKSTEP=1 PRJ3_DIR="$SB/none" run prj3_lockstep_gate 0.8.3 2>&1)"; rc=$?
check "④' FPM_SKIP_PRJ3_LOCKSTEP=1 우회" "$rc" "0"

# ⑤ prj3 소스 태그
out="$(run prj3_tag_release 0.8.3 2>&1)"; rc=$?
check "⑤ prj3 태그 생성 rc" "$rc" "0"
check "⑤' v0.8.3 → prj3 HEAD" "$(git -C "$P" rev-parse v0.8.3^{commit})" "$(git -C "$P" rev-parse HEAD)"
echo x > "$P/x"; G "$P" add -A; G "$P" commit -qm n
out="$(run prj3_tag_release 0.8.3 2>&1)"
check "⑤'' 다른 커밋에 있는 태그는 옮기지 않는다" "$(git -C "$P" rev-parse v0.8.3^{commit})" "$(git -C "$P" rev-parse HEAD~1)"
has "⑤''' 이동 거부 경고" "$out" "다른 커밋"

# ⑥ 배선(정적)
dep="$(awk '/^do_deploy\(\) \{/ {p=1} p {print} p && /^}/ {exit}' "$SYNC")"
l_gate="$(printf '%s\n' "$dep" | grep -n 'prj3_lockstep_gate' | head -1 | cut -d: -f1)"
l_appr="$(printf '%s\n' "$dep" | grep -n 'version_bump_gate' | head -1 | cut -d: -f1)"
l_src="$(printf '%s\n' "$dep" | grep -n 'src_tag_release' | head -1 | cut -d: -f1)"
l_p3="$(printf '%s\n' "$dep" | grep -n 'prj3_tag_release' | head -1 | cut -d: -f1)"
[ -n "$l_gate" ] && [ -n "$l_appr" ] && [ "$l_gate" -lt "$l_appr" ] && ok "⑥ prj3 선검사가 번호 승인 게이트 앞" || fail "⑥ prj3 선검사 배선 (gate=$l_gate appr=$l_appr)"
[ -n "$l_p3" ] && [ -n "$l_src" ] && [ "$l_p3" -gt "$l_src" ] && ok "⑥' prj3 태그는 소스 태그 뒤" || fail "⑥' prj3 태그 배선 (p3=$l_p3 src=$l_src)"

# ⑦ 소비자 전파 표준 명령 dry-run
if [ -x "$PROP" ] || [ -f "$PROP" ]; then
    out="$(bash "$PROP" --tag v0.8.3 --dry-run 2>&1)"; rc=$?
    check "⑦ dry-run rc" "$rc" "0"
    has "⑦' fg1 = systemctl --user restart fpm-hub" "$out" "fg1.*systemctl --user restart fpm-hub|systemctl --user restart fpm-hub"
    has "⑦'' jma 재기동" "$out" "jma"
    has "⑦''' jpc1 Git Bash" "$out" "jpc1"
    has "⑦'''' healthz 확인 단계" "$out" "healthz"
    has "⑦''''' 재설치(같은 버전 재출고 대비)" "$out" "uninstall|install"
else
    fail "⑦ fpm-consumer-propagate.sh 없음"
fi

# ⑧ 페이로드: 재기동 후 healthz 가 200 이 아니면 rc≠0
if [ -f "$PAY" ]; then
    out="$(FPM_PROP_NO_INSTALL=1 FPM_PROP_RESTART_CMD=true FPM_PROP_PORT=1 FPM_PROP_WAIT=1 bash "$PAY" 2>&1)"; rc=$?
    check "⑧ healthz 무응답 → rc≠0" "$([ $rc -ne 0 ] && echo nz || echo 0)" "nz"
    has "⑧' FPMR healthz 키" "$out" "FPMR healthz="
else
    fail "⑧ fpm-consumer-propagate-payload.sh 없음"
fi

echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
