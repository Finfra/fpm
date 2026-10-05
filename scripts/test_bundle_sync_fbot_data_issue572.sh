#!/bin/bash
# test_bundle_sync_fbot_data_issue572.sh — Issue572 회귀 테스트 (tdd playlist `bundle-sync-fbot-data`)
#
# scripts/fpm-bundle-sync.sh 는 fbot 데이터 중 `manuals/`·`icons/` 만 이름 일치로 스윕하고
# `data/fbot/org/` 는 아예 보지 않았다. 그래서 번들의 본사 조직(`_hq.yml`)·조직 템플릿(`_template/*`)이
# 옛 역할명(`taskmgr`)에 머물렀고, 매뉴얼 참조(`manuals/ref/`)도 따라오지 않았다(2026-09-28 실측, prj3#Issue757).
#
# 무엇을 지키나
#   1. 번들에 **이미 있는** `org/_hq.yml`·`org/_template/*`·`manuals/ref/*` 는 라이브를 따라간다
#   2. 번들의 사용자 prj 인스턴스(`org/<N>.yml`)는 건드리지 않는다 — 스윕 대상이 아니다
#   3. 번들에 없는 파일은 만들지 않는다(«신규 편입은 수동» 원칙 유지)
#   4. --check 는 표류를 이름으로 고지하고 exit 1
#
# 격리: 임시 git repo + 임시 HOME. 검사 대상 스크립트는 실물 복사.
# 실행: bash scripts/test_bundle_sync_fbot_data_issue572.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/bundle-fbotdata.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

R="$SB/repo"; H="$SB/home"; L="$H/.claude"; B="$R/plugins/fpm-core"
mkdir -p "$R/scripts" "$B/services/hub" "$B/data/fbot/org/_template" "$B/data/fbot/manuals/ref" \
         "$L/data/fbot/org/_template" "$L/data/fbot/manuals/ref"
cp "$REPO/scripts/fpm-bundle-sync.sh" "$R/scripts/"
mkdir -p "$R/sh" && cp "$REPO/sh/gen-integrity-manifest.sh" "$R/sh/"
echo "# hub" > "$B/services/hub/server.py"
mkdir -p "$R/services" && ln -s ../plugins/fpm-core/services/hub "$R/services/hub"

# 번들: 옛 판 — 본사·템플릿·ref 1종 · 사용자 prj 인스턴스 1종
echo 'role: taskmgr' > "$B/data/fbot/org/_hq.yml"
echo 'role: taskmgr' > "$B/data/fbot/org/_template/general.yml"
echo '# old ref' > "$B/data/fbot/manuals/ref/lead-ops.md"
echo 'prj: 1 # bundle' > "$B/data/fbot/org/1.yml"
git -C "$R" init -q && git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base

# 라이브: 새 판 + 번들에 없는 템플릿·ref·인스턴스
echo 'role: lead' > "$L/data/fbot/org/_hq.yml"
echo 'role: lead' > "$L/data/fbot/org/_template/general.yml"
echo 'role: lead' > "$L/data/fbot/org/_template/extra.yml"
echo '# new ref' > "$L/data/fbot/manuals/ref/lead-ops.md"
echo '# only live' > "$L/data/fbot/manuals/ref/chief-ops.md"
echo 'prj: 1 # live' > "$L/data/fbot/org/1.yml"
echo 'prj: 2 # live' > "$L/data/fbot/org/2.yml"

echo "[test_bundle_sync_fbot_data_issue572]"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "--check 는 표류가 있으면 exit 1" "$rc" "1"
for f in org/_hq.yml org/_template/general.yml manuals/ref/lead-ops.md; do
  if printf '%s\n' "$out" | grep -q "DRIFT plugins/fpm-core/data/fbot/$f"; then ok "--check 가 $f 표류를 고지"; else fail "--check 가 $f 표류를 고지"; fi
done
if printf '%s\n' "$out" | grep -q "data/fbot/org/1.yml"; then fail "--check 가 사용자 prj 인스턴스를 표류로 세지 않는다"; else ok "--check 가 사용자 prj 인스턴스를 표류로 세지 않는다"; fi

HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" >/dev/null 2>&1; rc=$?
check "동기 rc 0" "$rc" "0"
for f in org/_hq.yml org/_template/general.yml manuals/ref/lead-ops.md; do
  if cmp -s "$B/data/fbot/$f" "$L/data/fbot/$f"; then ok "$f 가 라이브를 따라간다"; else fail "$f 가 라이브를 따라간다"; fi
done
check "사용자 prj 인스턴스는 건드리지 않는다" "$(cat "$B/data/fbot/org/1.yml")" "prj: 1 # bundle"
check "번들에 없는 인스턴스는 만들지 않는다" "$([ -e "$B/data/fbot/org/2.yml" ] && echo made || echo absent)" "absent"
check "번들에 없는 템플릿은 만들지 않는다(수동 편입)" "$([ -e "$B/data/fbot/org/_template/extra.yml" ] && echo made || echo absent)" "absent"
check "번들에 없는 ref 는 만들지 않는다(수동 편입)" "$([ -e "$B/data/fbot/manuals/ref/chief-ops.md" ] && echo made || echo absent)" "absent"

git -C "$R" add -A && git -C "$R" -c user.name=t -c user.email=t@t commit -q -m synced >/dev/null 2>&1
HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check >/dev/null 2>&1; rc=$?
check "동기 후 --check exit 0 (표류 없음)" "$rc" "0"

# prj3#Issue757 — 개인 prj 조직 선언(N.yml)은 사용자 데이터다(사용자 결정 2026-09-28 «번들에서 제거 + 로컬 선언 폴백»).
#   번들은 골격(_hq.yml·_template/*)만 싣는다 — 플러그인 훅의 fbot-org 는 ~/.claude/data/fbot/org 를 먼저 읽는다.
_inst="$(ls "$REPO/plugins/fpm-core/data/fbot/org/" 2>/dev/null | /usr/bin/grep -E '^[0-9]+\.yml$' | tr '\n' ' ')"
check "실제 번들에 prj 조직 인스턴스(N.yml)가 없다" "$_inst" ""
if /usr/bin/grep -q '^plugins/fpm-core/data/fbot/org/\[0-9\]\*\.yml' "$REPO/.gitignore"; then ok "gitignore 가 번들 N.yml 재유입을 막는다"; else fail "gitignore 가 번들 N.yml 재유입을 막는다"; fi
if /usr/bin/grep -q '^_USER_ORG = ' "$REPO/plugins/fpm-core/hooks/fbot-org.py"; then ok "번들 fbot-org 가 사용자 폴더 폴백을 안다"; else fail "번들 fbot-org 가 사용자 폴더 폴백을 안다"; fi

echo
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
