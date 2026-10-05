#!/bin/bash
# test_release_evidence_record.sh — Issue543 M1-1 회귀 테스트 (tdd playlist #35 release-evidence-md)
#
# 기록기 `scripts/fpm-deploy-record.sh --gate release --rows <tsv> --version <VER>` 가
#   ① md 증거 `_doc_work/_release/v{VER}/release-test_{VER}.md` 를 정본으로 쓰고(release-test-rules "증거 형식")
#   ② 행을 건너뛰면 result: partial · 실패가 있으면 fail · 전건 통과만 pass 로 판정하며
#   ③ data/releases/release-gates.yml 에 색인 1줄을 남기고
#   ④ 그 증거를 글로벌 R2(`release-test-audit.py recheck`)가 실제로 읽는지 검증한다.
# 0건·버전 누락·잘못된 결과 토큰·쓰기 실패는 rc 1 — 조용히 pass 로 새지 않는다.
#
# 격리: 임시 git repo. 기록기는 실물 복사. R2 는 실물 ~/.claude/sh/release-test-audit.py (없으면 해당 항목 skip).
# 실행: bash scripts/test_release_evidence_record.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
unset FPM_RELEASE_MAIN_REPO FPM_RELEASE_CANDIDATE FPM_RELEASE_GATE_STATE FPM_RELEASE_EVIDENCE_DIR   # 바깥 R1 문맥 비상속
SB="$(mktemp -d "${TMPDIR:-/tmp}/ev-record.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
skip() { SKIP=$((SKIP + 1)); echo "  skip $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
fmv() { sed -n '/^---$/,/^---$/p' "$1" 2>/dev/null | sed -n "s/^$2: *//p" | head -1; }
AUDIT="${FPM_RELEASE_AUDIT:-$HOME/.claude/sh/release-test-audit.py}"
# R1(tdd/run-release.sh) 안에서 돌면 RELEASE_TEST_R1=1 이 상속돼 recheck 가 «생략» rc 0 이 된다 — 차단 검증이 공허해지지 않게 해제
unset RELEASE_TEST_R1

R="$SB/repo"
mkdir -p "$R/scripts" "$R/tdd" "$R/data/releases"
cp "$REPO/scripts/fpm-deploy-record.sh" "$R/scripts/"
echo "0.0.1" > "$R/VERSION"
printf -- '---\ntitle: t\ngate: pre-merge\nenv: authoring\ndoc_paths: data/releases/\n---\n' > "$R/tdd/release.md"
git -C "$R" init -q -b main
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base
SHA="$(git -C "$R" rev-parse HEAD)"
export FPM_RELEASE_GATE_STATE="$SB/gates.yml"
export FPM_RELEASE_EVIDENCE_DIR="$R/_doc_work/_release"
REC() { bash "$R/scripts/fpm-deploy-record.sh" --gate release --repo "$R" "$@"; }
EV() { printf '%s' "$FPM_RELEASE_EVIDENCE_DIR/v$1/release-test_$1.md"; }

echo "[test_release_evidence_record]"

# ── ① 전건 pass ──
printf 'dev-playlist-green\tpass\t26/26\nrelease-check\tpass\t5스테이지\n' > "$SB/rows1.tsv"
REC --rows "$SB/rows1.tsv" --version 0.0.2 --env authoring --peers "prj3@abc1234" >/dev/null 2>&1; rc=$?
check "전건 pass 기록 rc 0" "$rc" "0"
F="$(EV 0.0.2)"
if [ -f "$F" ]; then ok "md 증거 생성: v0.0.2/release-test_0.0.2.md"; else fail "md 증거 생성 (없음: $F)"; fi
check "frontmatter version" "$(fmv "$F" version)" "0.0.2"
check "frontmatter commit = 후보 전체 SHA" "$(fmv "$F" commit)" "$SHA"
check "frontmatter dirty" "$(fmv "$F" dirty)" "no"
check "frontmatter result" "$(fmv "$F" result)" "pass"
check "frontmatter env" "$(fmv "$F" env)" "authoring"
check "frontmatter peers" "$(fmv "$F" peers)" "prj3@abc1234"
check "행별 결과 표 2행" "$(grep -c '^| [0-9]' "$F" 2>/dev/null)" "2"
um="$(umask)"; want_mode="$(printf '%o' $(( 0666 & ~0$um )))"
got_mode="$(python3 -c 'import os,sys; print("%o" % (os.stat(sys.argv[1]).st_mode & 0o777))' "$F" 2>/dev/null)"   # BSD·GNU stat 문법 차이 회피
check "증거 파일 권한 = umask 기준 (mkstemp 0600 아님)" "$got_mode" "$want_mode"
idx="$(grep 'suite: release-test' "$FPM_RELEASE_GATE_STATE" 2>/dev/null | tail -1)"
case "$idx" in *"version: 0.0.2"*"result: pass"*"evidence: "*) ok "yml 색인 1줄 (suite: release-test·result·evidence)" ;; *) fail "yml 색인 1줄 (got: $idx)" ;; esac

# ── ② skip 행 → partial ──
printf 'dev-playlist-green\tpass\t\nnative-linux\tskip\t실행 수단 없음 (plan M3)\n' > "$SB/rows2.tsv"
REC --rows "$SB/rows2.tsv" --version 0.0.3 >/dev/null 2>&1
check "skip 행이 있으면 result: partial" "$(fmv "$(EV 0.0.3)" result)" "partial"

# ── ③ fail 이 있으면 skip 보다 우선해 fail ──
printf 'a\tfail\tRELEASE-CHECK-FAIL: x | y\nb\tskip\t\nc\tpass\t\n' > "$SB/rows3.tsv"
REC --rows "$SB/rows3.tsv" --version 0.0.4 >/dev/null 2>&1
check "fail 1건 이상 → result: fail" "$(fmv "$(EV 0.0.4)" result)" "fail"
if grep -q 'x \\| y' "$(EV 0.0.4)" 2>/dev/null; then ok "비고의 | 는 표를 깨지 않게 이스케이프"; else fail "비고의 | 이스케이프"; fi

# ── ④ 입력 오류는 rc 1 + 파일 없음 ──
REC --rows "$SB/rows1.tsv" >/dev/null 2>&1; rc=$?
check "--version 누락 → rc 1" "$rc" "1"
: > "$SB/empty.tsv"
REC --rows "$SB/empty.tsv" --version 0.0.5 >/dev/null 2>&1; rc=$?
check "행 0건 → rc 1 (돌지 않은 것은 통과가 아니다)" "$rc" "1"
if [ ! -f "$(EV 0.0.5)" ]; then ok "행 0건 → 증거 파일 안 만든다"; else fail "행 0건인데 증거 생성"; fi
printf 'a\tok\t\n' > "$SB/bad.tsv"
REC --rows "$SB/bad.tsv" --version 0.0.6 >/dev/null 2>&1; rc=$?
check "허용 외 결과 토큰 → rc 1" "$rc" "1"
FPM_RELEASE_EVIDENCE_DIR="/dev/null/nope" REC --rows "$SB/rows1.tsv" --version 0.0.7 >/dev/null 2>&1; rc=$?
check "증거 쓰기 실패 → rc 1" "$rc" "1"

# ── ⑤ dirty 트리는 dirty: yes 로 남는다(판정을 느슨하게 하지 않는다) ──
echo wip >> "$R/VERSION"
REC --rows "$SB/rows1.tsv" --version 0.0.8 >/dev/null 2>&1
check "dirty 트리 기록 → dirty: yes" "$(fmv "$(EV 0.0.8)" dirty)" "yes"
git -C "$R" checkout -q -- VERSION

# ── ⑥ 글로벌 R2 가 이 증거를 읽는다 ──
if [ -f "$AUDIT" ]; then
    git -C "$R" add -A && git -C "$R" -c user.name=t -c user.email=t@t commit -q -m evidence
    python3 "$AUDIT" recheck --repo "$R" --version 0.0.2 >/dev/null 2>&1; rc=$?
    check "R2 recheck: pass 증거 → rc 0" "$rc" "0"
    python3 "$AUDIT" recheck --repo "$R" --version 0.0.3 >/dev/null 2>&1; rc=$?
    check "R2 recheck: partial 증거 → rc 1" "$rc" "1"
else
    skip "R2 recheck 교차 검증 (도구 없음: $AUDIT)"
fi

echo "── PASS $PASS / FAIL $FAIL / SKIP $SKIP"
[ "$FAIL" -eq 0 ]
