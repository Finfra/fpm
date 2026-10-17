#!/bin/bash
# test_ship_verify_issue613.sh — Issue613 회귀 테스트 (출고 3대 검증 게이트 보강)
#
# fpm-ship-verify.sh 의 판정이 «명세의 FAIL 조건» 을 전부 rc=1 로 잡는지 검증한다. 원격은 부르지 않는다(--judge-only).
#   ① 정상 합성 증거 → rc=0
#   ② plugin 버전 불일치 → rc=1 · ③ integrity FAIL → rc=1 · ④ /boards 404(구 hub) → rc=1
#   ⑤ clone_version ≠ 출고 버전 → rc=1 (종전엔 수집만 하고 판정 미반영)
#   ⑥ P1 비예외 FAIL → rc=1 · ⑦ P1 로그 없음 → rc=1 · ⑧ jpc1 symlink-support 단독 FAIL 은 예외로 PASS
#   ⑨ 캡처 shots/hub-<host>.png 없음 → rc=1 · ⑩ --skip-p1 / --skip-shots 는 명시 생략(PASS, 표에 skip)
#   ⑪ --fixtures: 위 FAIL 경로를 스스로 돌려 전부 rc=1 확인 + 대조군 rc=0, 결과를 evidence/fixture-<ver>.log 로 보존
#   ⑫ 실 0.8.3 증거(사본) 재판정 → rc=0
#   ⑬ --propagate 는 소비자 전파 표준 명령(fpm-consumer-propagate.sh)을 부른다 (정적)
#
# 실행: bash scripts/test_ship_verify_issue613.sh
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SV="$REPO/scripts/fpm-ship-verify.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/shipverify613.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
echo "[test_ship_verify_issue613]"

VER=9.9.9
# mk <case-dir> <host> — 정상 합성 증거 한 벌
mk() {
    local d="$1" h="$2"
    mkdir -p "$d/evidence/shots"
    printf 'FPMR host=%s os=Linux\nFPMR plugin=%s\nFPMR clone=abc1234 clone_version=%s\nFPMR integrity=PASS\nFPMR healthz=200 boards=200\nFPMR ssh_rc=0\n' "$h" "$VER" "$VER" > "$d/evidence/state-$h.log"
    printf 'FPMR host=%s\nFPMR tdd_rc=0\nFPMR sandbox_fail=0\nFPMR rc=0\n' "$h" > "$d/post-$h.log"
    echo png > "$d/evidence/shots/hub-$h.png"
}
judge() { bash "$SV" --tag "v$VER" --judge-only --host "$1" --out "$2" "${@:3}" >"$2/out.txt" 2>&1; echo $?; }
case_() {  # case_ <name> <host> <mutator…>
    local n="$1" h="$2"; shift 2
    local d="$SB/$n"; mk "$d" "$h"; "$@" "$d" "$h"; echo "$d"
}

d="$SB/good"; mk "$d" fx
check "① 정상 합성 증거 → rc=0" "$(judge fx "$d")" "0"

d="$SB/plug"; mk "$d" fx; sed -i.bak 's/^FPMR plugin=.*/FPMR plugin=0.0.1/' "$d/evidence/state-fx.log"
check "② plugin 버전 불일치 → rc=1" "$(judge fx "$d")" "1"
d="$SB/integ"; mk "$d" fx; sed -i.bak 's/integrity=PASS/integrity=FAIL/' "$d/evidence/state-fx.log"
check "③ integrity FAIL → rc=1" "$(judge fx "$d")" "1"
d="$SB/boards"; mk "$d" fx; sed -i.bak 's/boards=200/boards=404/' "$d/evidence/state-fx.log"
check "④ /boards 404 → rc=1" "$(judge fx "$d")" "1"
d="$SB/clone"; mk "$d" fx; sed -i.bak 's/clone_version=[0-9.]*/clone_version=0.0.1/' "$d/evidence/state-fx.log"
check "⑤ clone_version 불일치 → rc=1" "$(judge fx "$d")" "1"

d="$SB/p1fail"; mk "$d" fx; printf 'FPMR tdd_rc=1\n  ❌ some-case   무언가\n결과: PASS 3 / FAIL 1\nFPMR sandbox_fail=0\nFPMR rc=1\n' > "$d/post-fx.log"
check "⑥ P1 비예외 FAIL → rc=1" "$(judge fx "$d")" "1"
d="$SB/p1none"; mk "$d" fx; rm "$d/post-fx.log"
check "⑦ P1 로그 없음 → rc=1" "$(judge fx "$d")" "1"
d="$SB/p1sym"; mk "$d" jpc1; printf 'FPMR tdd_rc=1\n  ❌ symlink-support          심볼릭 링크를 만들 수 있다\n결과: PASS 35 / FAIL 1 / SKIP 8  (platform=windows)\nFPMR sandbox_fail=0\nFPMR rc=1\n' > "$d/post-jpc1.log"
check "⑧ jpc1 symlink-support 단독 FAIL → 예외 PASS" "$(judge jpc1 "$d")" "0"
d="$SB/p1symfg"; mk "$d" fx; cp "$SB/p1sym/post-jpc1.log" "$d/post-fx.log"
check "⑧' 같은 FAIL 이 jpc1 이 아닌 머신이면 예외 아님 → rc=1" "$(judge fx "$d")" "1"

d="$SB/noshot"; mk "$d" fx; rm "$d/evidence/shots/hub-fx.png"
check "⑨ 캡처 없음 → rc=1" "$(judge fx "$d")" "1"
d="$SB/skip"; mk "$d" fx; rm "$d/post-fx.log" "$d/evidence/shots/hub-fx.png"
check "⑩ --skip-p1 --skip-shots 명시 생략 → rc=0" "$(judge fx "$d" --skip-p1 --skip-shots)" "0"
grep -q "skip" "$d/out.txt" && ok "⑩' 표에 skip 이 드러난다" || fail "⑩' 표에 skip 미표기"

# ⑪ --fixtures
d="$SB/fx"; mkdir -p "$d"
bash "$SV" --tag "v$VER" --fixtures --out "$d" >"$d/out.txt" 2>&1; rc=$?
check "⑪ --fixtures rc=0(모든 FAIL 경로가 rc=1 로 잡힘)" "$rc" "0"
[ -s "$d/evidence/fixture-$VER.log" ] && ok "⑪' evidence/fixture-$VER.log 보존" || fail "⑪' fixture 로그 없음"
n=$(grep -c "rc=1" "$d/evidence/fixture-$VER.log" 2>/dev/null || echo 0)
[ "$n" -ge 3 ] && ok "⑪'' FAIL fixture 3종 이상 rc=1 기록($n)" || fail "⑪'' rc=1 기록 부족($n)"

# ⑫ 실 0.8.3 증거 사본
REAL="$REPO/_doc_work/_release/v0.8.3"
if [ -d "$REAL/evidence" ]; then
    cp -R "$REAL" "$SB/real"
    bash "$SV" --tag v0.8.3 --judge-only --out "$SB/real" >"$SB/real-out.txt" 2>&1; rc=$?
    check "⑫ 실 0.8.3 증거 → rc=0" "$rc" "0"
else
    ok "⑫ (0.8.3 증거 없음 — skip)"
fi

# ⑬ 배선(정적)
grep -q "fpm-consumer-propagate.sh" "$SV" && grep -q -- "--propagate" "$SV" && ok "⑬ --propagate → 소비자 전파 표준 명령" || fail "⑬ --propagate 배선 없음"

echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
