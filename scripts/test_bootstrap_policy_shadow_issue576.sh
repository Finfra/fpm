#!/bin/bash
# test_bootstrap_policy_shadow_issue576.sh — Issue576 회귀 테스트 (tdd playlist `bootstrap-policy-shadow`)
#
# sh/fbot-bootstrap.sh 가 개발 머신의 운영 aoa 폴더(AOA_MEMORY_DIR ≠ ~/.claude/data/aoa)에 policy.yml 을
# 템플릿으로 만들었다(2026-09-27 18:41 실측). fbot 로더는 «aoa 폴더 → prj3 정본 → policy_org» 순이라 이 사본이
# prj3 정본을 가린다 — 정책 개정이 운영에 안 닿는 잠복 갈림(prj3#Issue755 관측 · prj3#Issue757 에서 확정).
#
# 무엇을 지키나
#   1. 소비자(aoa 폴더 = ~/.claude/data/aoa) — 종전대로 policy.yml 을 만든다
#   2. 개발 머신(aoa 폴더 ≠ 정본 폴더 · 정본 존재) — policy.yml 을 만들지 않는다
#   3. 이미 있는 그림자 사본은 한 줄도 건드리지 않고(키 병합도 안 함) 경고로 알린다
#
# 격리: 임시 HOME·임시 AOA_MEMORY_DIR. 검사 대상은 실물 스크립트. 실행: bash scripts/test_bootstrap_policy_shadow_issue576.sh
set -u
unset AOA_DECISION_POLICY

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-shadow.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

echo "[test_bootstrap_policy_shadow_issue576]"
# 1. 소비자
C="$SB/consumer"; mkdir -p "$C/.claude"
HOME="$C" AOA_MEMORY_DIR="$C/.claude/data/aoa" bash "$REPO/sh/fbot-bootstrap.sh" >"$SB/c.log" 2>&1; rc=$?
check "소비자 bootstrap rc 0" "$rc" "0"
check "소비자 — aoa 폴더(=정본 자리)에 policy.yml 생성" "$([ -f "$C/.claude/data/aoa/policy.yml" ] && echo made || echo absent)" "made"

# 2. 개발 머신 — 정본이 있고 aoa 폴더가 다르다
D="$SB/dev"; mkdir -p "$D/.claude/data/aoa" "$D/common/aoa"
printf 'lease_ttl_secs: 720\nfbot_manager_multibody: true\n' > "$D/.claude/data/aoa/policy.yml"
HOME="$D" AOA_MEMORY_DIR="$D/common/aoa" bash "$REPO/sh/fbot-bootstrap.sh" >"$SB/d.log" 2>&1; rc=$?
check "개발 머신 bootstrap rc 0" "$rc" "0"
check "🔑 개발 머신 — 그림자 policy.yml 을 만들지 않는다" "$([ -f "$D/common/aoa/policy.yml" ] && echo made || echo absent)" "absent"
if grep -q "정본" "$SB/d.log"; then ok "정본 사용을 알린다"; else fail "정본 사용을 알린다"; fi
check "스토어는 그대로 만든다(registry.db)" "$([ -f "$D/common/aoa/registry.db" ] && echo made || echo absent)" "made"

# 3. 이미 있는 그림자 사본 — 건드리지 않고 경고
printf 'lease_ttl_secs: 111\n' > "$D/common/aoa/policy.yml"
before="$(cat "$D/common/aoa/policy.yml")"
HOME="$D" AOA_MEMORY_DIR="$D/common/aoa" bash "$REPO/sh/fbot-bootstrap.sh" >"$SB/d2.log" 2>&1; rc=$?
check "기존 사본 있는 bootstrap rc 0" "$rc" "0"
check "🔑 기존 그림자 사본은 한 줄도 바꾸지 않는다(키 병합 없음)" "$(cat "$D/common/aoa/policy.yml")" "$before"
if grep -q "그림자" "$SB/d2.log"; then ok "그림자 사본 경고"; else fail "그림자 사본 경고"; fi

# 4. Issue585 — HOME 만 바꾼 샌드박스가 HOME 밖 데이터 루트(운영 aoa 폴더 상속)에 쓴다
#    임시 HOME 에는 정본이 없어 2번 판정이 «소비자» 로 떨어진다(2026-09-28 22:41 실측 재생성 경로)
S="$SB/sandbox-home"; X="$SB/outside/aoa"; mkdir -p "$S" "$X"
HOME="$S" AOA_MEMORY_DIR="$X" bash "$REPO/sh/fbot-bootstrap.sh" >"$SB/s.log" 2>&1; rc=$?
check "샌드박스 bootstrap rc 0" "$rc" "0"
check "🔑 HOME 밖 데이터 루트에 policy.yml 을 만들지 않는다(Issue585)" "$([ -f "$X/policy.yml" ] && echo made || echo absent)" "absent"
if grep -q "Issue585" "$SB/s.log"; then ok "건너뛴 이유를 알린다"; else fail "건너뛴 이유를 알린다"; fi
# 명시 옵트인이면 종전대로 만든다 — HOME 밖 데이터 루트를 쓰는 실사용자의 탈출구
HOME="$S" AOA_MEMORY_DIR="$X" FBOT_BOOTSTRAP_EXTERNAL_POLICY=1 bash "$REPO/sh/fbot-bootstrap.sh" >/dev/null 2>&1
check "옵트인(FBOT_BOOTSTRAP_EXTERNAL_POLICY=1) — 생성" "$([ -f "$X/policy.yml" ] && echo made || echo absent)" "made"

echo
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
