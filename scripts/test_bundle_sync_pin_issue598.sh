#!/bin/bash
# test_bundle_sync_pin_issue598.sh — Issue598 회귀 테스트 (tdd playlist `bundle-sync-r1-pin`)
#
# R1 이 bundle-in-sync 를 «지금의 prj3 HEAD» 와 비교하면, 후보를 고정한 뒤 prj3 가 커밋될 때마다
# 후보와 무관하게 DRIFT 가 난다(2026-10-05 R1 재실패). 동기가 박은 핀(data/releases/bundle-live-ref)으로
# R1(RELEASE_TEST_R1=1)만 «핀 시점의 prj3» 와 비교한다.
#   1. 전체 동기는 핀(= prj3 HEAD)을 기록한다
#   2. 동기 후 prj3 가 더 커밋돼도 R1 --check 는 exit 0 (후보 고정 = 판정 고정) + 앞섬을 고지
#   3. R1 이 아니면 종전대로 HEAD 와 비교해 표류(exit 1)로 잡는다
#   4. 부분 동기(--only)는 핀을 쓰지 않는다
# 격리: 임시 git repo + 임시 HOME. 실행: bash scripts/test_bundle_sync_pin_issue598.sh
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/bundle-pin.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
G() { git -C "$1" -c user.name=t -c user.email=t@t "${@:2}"; }
export GIT_CONFIG_GLOBAL=/dev/null
unset RELEASE_TEST_R1 FPM_BUNDLE_LIVE_REF

R="$SB/repo"; H="$SB/home"; L="$H/.claude"; B="$R/plugins/fpm-core"
mkdir -p "$R/scripts" "$R/sh" "$R/data/releases" "$B/services/hub" "$B/hooks" "$L/hooks"
cp "$REPO/scripts/fpm-bundle-sync.sh" "$R/scripts/"
cp "$REPO/sh/gen-integrity-manifest.sh" "$R/sh/"
echo "# hub" > "$B/services/hub/server.py"
mkdir -p "$R/services" && ln -s ../plugins/fpm-core/services/hub "$R/services/hub"
echo 'v1' > "$B/hooks/fbot-a.py" && chmod +x "$B/hooks/fbot-a.py"
echo 'v1' > "$L/hooks/fbot-a.py"
G "$L" init -q && G "$L" add -A && G "$L" commit -q -m base
G "$R" init -q && G "$R" add -A && G "$R" commit -q -m base
(cd "$R" && bash sh/gen-integrity-manifest.sh >/dev/null 2>&1) && G "$R" add -A && G "$R" commit -q -m manifest

echo "[test_bundle_sync_pin_issue598]"
HEAD0="$(G "$L" rev-parse HEAD)"
HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" >/dev/null 2>&1
check "전체 동기가 핀을 기록한다" "$(cat "$R/data/releases/bundle-live-ref" 2>/dev/null)" "$HEAD0"
G "$R" add -A && G "$R" commit -q -m "sync+pin"

# 동기 이후 prj3 가 앞서간다
echo 'v2' > "$L/hooks/fbot-a.py"; G "$L" add -A; G "$L" commit -q -m "a v2"

out="$(RELEASE_TEST_R1=1 HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "R1 --check 는 핀 기준이라 exit 0" "$rc" "0"
case "$out" in *"앞섰다"*) ok "라이브가 앞선 사실을 고지한다" ;; *) fail "라이브가 앞선 사실을 고지한다" ;; esac

out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "R1 이 아니면 HEAD 기준 — 표류 exit 1" "$rc" "1"

HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --only plugins/fpm-core/hooks >/dev/null 2>&1
check "부분 동기는 핀을 바꾸지 않는다" "$(cat "$R/data/releases/bundle-live-ref")" "$HEAD0"

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
