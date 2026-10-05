#!/bin/bash
# test_bundle_sync_head_source_issue591.sh — Issue591 회귀 테스트 (tdd playlist `bundle-sync-head-source`)
#
# scripts/fpm-bundle-sync.sh 는 라이브(prj3)의 **작업트리**를 원본으로 읽었다. 그런데 출고 규칙은
# «번들에는 prj3 HEAD 판을 싣는다(미커밋 사본 반출 금지)» 다 — 판정이 둘로 갈려, prj3 에 다른 세션의
# 진행 중 편집이 하나라도 있으면 `--check` 가 DRIFT 를 내 deploy 재생목록 `bundle-in-sync` 가 떨어졌다
# (2026-10-03 실측: 번들 == prj3 HEAD 인데 catalog.yml·fbot-lead.py·fbot-state.py 미커밋분으로 16/17).
# 반대로 동기를 돌리면 남의 미완성 편집을 번들로 반출한다.
#
# 무엇을 지키나
#   1. 라이브가 git repo 면 원본은 HEAD 다 — 미커밋 편집은 --check 에서 표류로 세지 않는다
#   2. 동기는 미커밋 편집을 반출하지 않는다(번들 = HEAD 판)
#   3. 라이브 미추적 파일(lib 의존 포함)은 반입하지 않는다
#   4. 커밋된 변경은 여전히 표류로 잡고 동기한다
#   5. 미커밋분을 건너뛴 사실은 조용히 묻히지 않는다(고지)
#   6. 라이브가 git repo 가 아니면 종전대로 작업트리를 원본으로 쓴다
#
# 격리: 임시 git repo + 임시 HOME. 검사 대상 스크립트는 실물 복사.
# 실행: bash scripts/test_bundle_sync_head_source_issue591.sh
set -u

# R1 하네스(tdd/run-release.sh)가 RELEASE_TEST_R1=1 을 주입한다 — fpm-bundle-sync.sh 가 핀 기준 판정으로 바뀌어
# «HEAD 판 동기» 를 검사하는 이 테스트가 오판한다(Issue598 핀 도입 후 R1 재실패 실측). 핀 동작은 test_bundle_sync_pin_issue598.sh 가 검사.
unset RELEASE_TEST_R1

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/bundle-head.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
G() { git -C "$1" -c user.name=t -c user.email=t@t "${@:2}"; }
#   전역 git 설정 격리 — 사용자 `~/.gitignore_global` 의 `Icon?`(macOS 아이콘 파일)이 core.ignorecase 로
#   `icons/` 를 잡아 픽스처 catalog 가 커밋되지 않았다(샌드박스 HOME 의 스크립트에겐 미추적 = dirty 로 보여
#   catalog 단언이 엉뚱한 이유로 통과). 픽스처 커밋과 스크립트가 같은 설정을 보게 한다
export GIT_CONFIG_GLOBAL=/dev/null

R="$SB/repo"; H="$SB/home"; L="$H/.claude"; B="$R/plugins/fpm-core"
mkdir -p "$R/scripts" "$R/sh" "$B/services/hub" "$B/hooks/lib" "$B/data/fbot/icons" \
         "$L/hooks/lib" "$L/data/fbot/icons"
cp "$REPO/scripts/fpm-bundle-sync.sh" "$R/scripts/"
cp "$REPO/sh/gen-integrity-manifest.sh" "$R/sh/"
echo "# hub" > "$B/services/hub/server.py"
mkdir -p "$R/services" && ln -s ../plugins/fpm-core/services/hub "$R/services/hub"

# 번들 = 라이브 HEAD 판
echo 'v1' > "$B/hooks/fbot-a.py" && chmod +x "$B/hooks/fbot-a.py"   # 실번들처럼 실행권한 — 6단계 chmod 가 mode diff 로 dirty 를 만들지 않게
echo 'icon: v1' > "$B/data/fbot/icons/catalog.yml"
#   디렉토리 rsync 대상(skills) — 내용은 같고 mtime 만 다르다. HEAD 스냅샷의 mtime 은 추출 시각이라
#   크기+mtime 비교면 전부 표류로 센다(2026-10-03 실측 30건 오탐) → --checksum 으로 내용 비교해야 한다
mkdir -p "$B/skills/fbot-icon" && echo '# skill' > "$B/skills/fbot-icon/SKILL.md" && touch -t 202001010000 "$B/skills/fbot-icon/SKILL.md"
G "$R" init -q && G "$R" add -A && G "$R" commit -q -m base
#   무결성 매니페스트 기준선 — 없으면 --check 가 매니페스트 미갱신으로 표류를 센다(본 테스트의 관심 밖)
(cd "$R" && bash sh/gen-integrity-manifest.sh >/dev/null 2>&1) && G "$R" add -A && G "$R" commit -q -m manifest

# 라이브(git repo): HEAD = v1, 그 위에 타 세션의 미커밋 편집 + 미추적 lib 의존
echo 'v1' > "$L/hooks/fbot-a.py"
echo 'icon: v1' > "$L/data/fbot/icons/catalog.yml"
mkdir -p "$L/skills/fbot-icon" && echo '# skill' > "$L/skills/fbot-icon/SKILL.md"
G "$L" init -q && G "$L" add -A && G "$L" commit -q -m base
echo 'v2-wip # lib/wip-dep.py' > "$L/hooks/fbot-a.py"
echo 'icon: v2-wip' > "$L/data/fbot/icons/catalog.yml"
echo '# untracked' > "$L/hooks/lib/wip-dep.py"

echo "[test_bundle_sync_head_source_issue591]"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "미커밋 편집만 있으면 --check exit 0" "$rc" "0"
if printf '%s\n' "$out" | grep -q "표류 없음"; then ok "--check 가 «표류 없음» 을 낸다"; else fail "--check 가 «표류 없음» 을 낸다"; fi
if printf '%s\n' "$out" | grep -q "라이브 미커밋"; then ok "미커밋분을 건너뛴 사실을 고지한다"; else fail "미커밋분을 건너뛴 사실을 고지한다"; fi

HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" >/dev/null 2>&1; rc=$?
check "동기 rc 0" "$rc" "0"
check "미커밋 훅 편집을 반출하지 않는다" "$(cat "$B/hooks/fbot-a.py")" "v1"
check "미커밋 데이터 편집을 반출하지 않는다" "$(cat "$B/data/fbot/icons/catalog.yml")" "icon: v1"
check "라이브 미추적 lib 의존을 반입하지 않는다" "$([ -e "$B/hooks/lib/wip-dep.py" ] && echo made || echo absent)" "absent"

# 커밋되면 표류로 잡고 동기한다
G "$L" add hooks/fbot-a.py && G "$L" commit -q -m "a v2"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "커밋된 변경은 --check exit 1" "$rc" "1"
if printf '%s\n' "$out" | grep -q "DRIFT plugins/fpm-core/hooks/fbot-a.py"; then ok "커밋된 변경을 이름으로 고지"; else fail "커밋된 변경을 이름으로 고지"; fi
HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" >/dev/null 2>&1
check "커밋된 훅 판을 동기한다" "$(cat "$B/hooks/fbot-a.py")" "v2-wip # lib/wip-dep.py"
check "커밋된 판이어도 데이터 미커밋분은 여전히 제외" "$(cat "$B/data/fbot/icons/catalog.yml")" "icon: v1"

# 라이브가 git repo 가 아니면 작업트리가 원본(종전 동작)
rm -rf "$L/.git"
out="$(HOME="$H" bash "$R/scripts/fpm-bundle-sync.sh" --check 2>&1)"; rc=$?
check "비 git 라이브는 작업트리 기준 — 표류 exit 1" "$rc" "1"
if printf '%s\n' "$out" | grep -q "DRIFT plugins/fpm-core/data/fbot/icons/catalog.yml"; then ok "비 git 라이브의 작업트리 표류를 고지"; else fail "비 git 라이브의 작업트리 표류를 고지"; fi

echo
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
