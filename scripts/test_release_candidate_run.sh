#!/bin/bash
# test_release_candidate_run.sh — Issue543 M0 회귀 테스트 (tdd playlist #33 release-candidate-isolated)
#
# sh/release-candidate-run.sh 가 후보 커밋을 **격리 worktree** 에서 돌려
#   ① 공유 작업트리가 dirty(미커밋 Issue.md·미추적 파일)여도 게이트 기록이 `dirty: no` 로 남고
#   ② 기록이 worktree 가 아니라 **본 작업트리**에 남으며(worktree 와 함께 지워지지 않는다)
#   ③ 성공·실패 어느 경로든 worktree 를 남기지 않는지(`git worktree list` 전후 동일) 검증한다.
# 배경: data/releases/release-gates.yml 12/12 `dirty: yes` — 공유 작업트리에서 돌면 기록이
#   구조적으로 dirty 가 되어 G4 가 항상 막는다(_doc_arch/fpm-release-gate.md "1번의 원인").
#
# 격리: 임시 git repo. 검사 대상 스크립트는 **실물을 복사**해 쓴다 — 재구현을 검사하면 회귀를 못 잡는다.
# 실행: bash scripts/test_release_candidate_run.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# 바깥 R1 문맥을 상속하지 않는다 — 기본 경로 검증은 깨끗한 env 에서 (상속 방어는 ⑧ 이 따로 본다)
unset FPM_RELEASE_MAIN_REPO FPM_RELEASE_CANDIDATE FPM_RELEASE_GATE_STATE FPM_RELEASE_EVIDENCE_DIR
SB="$(mktemp -d "${TMPDIR:-/tmp}/rc-run-test.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
has()   { case "$2" in *"$3"*) ok "$1" ;; *) fail "$1 (missing '$3' in: $2)" ;; esac; }

R="$SB/repo"
mkdir -p "$R/sh" "$R/scripts" "$R/data/releases"
cp "$REPO/scripts/fpm-deploy-record.sh" "$R/scripts/"
[ -f "$REPO/sh/release-candidate-run.sh" ] && cp "$REPO/sh/release-candidate-run.sh" "$R/sh/"
echo "0.0.1" > "$R/VERSION"
echo "# issues" > "$R/Issue.md"
git -C "$R" init -q -b main
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base
C1="$(git -C "$R" rev-parse HEAD)"
echo "second" > "$R/second.txt"
git -C "$R" add second.txt
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m second
TOP="$(git -C "$R" rev-parse --show-toplevel)"

# 공유 작업트리를 타 세션처럼 더럽힌다 — 미커밋 수정 1 + 미추적 1
echo "WIP by other session" >> "$R/Issue.md"
echo "untracked" > "$R/other-session.tmp"

echo "[test_release_candidate_run]"

# ── 전제(결손 재현): 공유 작업트리에서 기록하면 dirty: yes 가 된다 ──
out="$(FPM_RELEASE_GATE_STATE="$SB/shared.yml" bash "$R/scripts/fpm-deploy-record.sh" --gate release --repo "$R" 2>&1)"
has "전제: 공유 작업트리 기록은 dirty: yes (결손 재현)" "$(cat "$SB/shared.yml" 2>/dev/null)" "dirty: yes"

RUN="$R/sh/release-candidate-run.sh"
if [ ! -f "$RUN" ]; then
    fail "실행기 sh/release-candidate-run.sh 존재"
    echo "── PASS $PASS / FAIL $FAIL"; exit 1
fi
ok "실행기 sh/release-candidate-run.sh 존재"

WT_BEFORE="$(git -C "$R" worktree list --porcelain)"

# ── ① 격리 실행 + 기록 경로 기본 주입(env 미설정) ──
out="$(env -u FPM_RELEASE_GATE_STATE -u FPM_RELEASE_EVIDENCE_DIR -u FPM_RELEASE_MAIN_REPO \
        bash "$RUN" HEAD -- bash scripts/fpm-deploy-record.sh --gate release 2>&1)"; rc=$?
check "격리 실행 rc 0" "$rc" "0"
st="$R/data/releases/release-gates.yml"
has "기록이 본 작업트리 data/releases/release-gates.yml 에 남는다" "$(cat "$st" 2>/dev/null)" "suite: release"
has "기록은 dirty: no (격리 worktree)" "$(cat "$st" 2>/dev/null)" "dirty: no"
has "기록 commit = 후보(HEAD)" "$(cat "$st" 2>/dev/null)" "commit: $(git -C "$R" rev-parse --short HEAD)"
check "공유 작업트리의 타 세션 수정 보존" "$(tail -1 "$R/Issue.md")" "WIP by other session"
check "공유 작업트리의 미추적 파일 보존" "$(cat "$R/other-session.tmp" 2>/dev/null)" "untracked"
check "실행 후 worktree 목록 불변" "$(git -C "$R" worktree list --porcelain)" "$WT_BEFORE"

# ── ② 주입 env · cwd 가 격리 worktree 인가 ──
out="$(bash "$RUN" HEAD -- bash -c 'printf "%s|%s|%s|%s|%s" "$FPM_RELEASE_MAIN_REPO" "$FPM_RELEASE_GATE_STATE" "$FPM_RELEASE_EVIDENCE_DIR" "$FPM_RELEASE_CANDIDATE" "$(git rev-parse --show-toplevel)"' 2>/dev/null)"
IFS='|' read -r e_main e_state e_ev e_cand e_top <<< "$out"
check "FPM_RELEASE_MAIN_REPO = 본 작업트리" "$e_main" "$TOP"
check "FPM_RELEASE_GATE_STATE = 본 작업트리 절대경로" "$e_state" "$TOP/data/releases/release-gates.yml"
check "FPM_RELEASE_EVIDENCE_DIR = 본 작업트리 _doc_work/_release" "$e_ev" "$TOP/_doc_work/_release"
check "FPM_RELEASE_CANDIDATE = 후보 전체 SHA" "$e_cand" "$(git -C "$R" rev-parse HEAD)"
if [ -n "$e_top" ] && [ "$e_top" != "$TOP" ]; then ok "명령 cwd 는 본 작업트리가 아닌 격리 worktree"; else fail "명령 cwd 는 격리 worktree (got '$e_top')"; fi

# ── ③ 이미 설정된 기록 경로는 존중한다(테스트·운영 override) ──
out="$(FPM_RELEASE_GATE_STATE="$SB/override.yml" bash "$RUN" HEAD -- bash -c 'printf "%s" "$FPM_RELEASE_GATE_STATE"' 2>/dev/null)"
check "기존 FPM_RELEASE_GATE_STATE 는 덮어쓰지 않는다" "$out" "$SB/override.yml"

# ── ④ 후보 선택: 과거 커밋을 지정하면 그 트리에서 돈다 ──
out="$(bash "$RUN" "$C1" -- git rev-parse HEAD 2>/dev/null)"
check "지정 후보 커밋에서 실행" "$out" "$C1"
out="$(bash "$RUN" "$C1" -- bash -c '[ -e second.txt ] && echo yes || echo no' 2>/dev/null)"
check "후보 트리 내용 = 지정 커밋(이후 파일 없음)" "$out" "no"

# ── ⑤ 실패 경로: rc 전달 + worktree 정리 ──
bash "$RUN" HEAD -- bash -c 'exit 7' >/dev/null 2>&1; rc=$?
check "명령 실패 rc 그대로 전달" "$rc" "7"
check "실패 후에도 worktree 목록 불변" "$(git -C "$R" worktree list --porcelain)" "$WT_BEFORE"

# ── ⑥ 입력 오류: 없는 커밋 · -- 누락 → rc 2, worktree 없음 ──
bash "$RUN" deadbeefdeadbeef -- true >/dev/null 2>&1; rc=$?
check "없는 커밋 → rc 2" "$rc" "2"
bash "$RUN" HEAD true >/dev/null 2>&1; rc=$?
check "-- 누락 → rc 2 (usage)" "$rc" "2"
check "입력 오류 후 worktree 목록 불변" "$(git -C "$R" worktree list --porcelain)" "$WT_BEFORE"

# ── ⑧ 다른 저장소의 R1 문맥(env)을 상속해도 자기 저장소만 대상으로 한다 ──
#   R1(tdd/run-release.sh) 안에서 이 테스트가 돌면 바깥 실행기가 export 한 FPM_RELEASE_* 를 상속한다.
#   그 값을 존중하면 fixture 가 아니라 바깥 저장소에 worktree 를 만들고 기록한다(2026-09-27 R1 실측 6 FAIL)
O="$SB/other"; mkdir -p "$O"; git -C "$O" init -q -b main
git -C "$O" -c user.name=t -c user.email=t@t commit -q --allow-empty -m o
O_WT="$(git -C "$O" worktree list --porcelain)"
out="$(FPM_RELEASE_MAIN_REPO="$O" FPM_RELEASE_CANDIDATE=deadbeef \
       FPM_RELEASE_GATE_STATE="$O/data/releases/release-gates.yml" FPM_RELEASE_EVIDENCE_DIR="$O/_doc_work/_release" \
       bash "$RUN" HEAD -- bash -c 'printf "%s|%s|%s|%s" "$FPM_RELEASE_MAIN_REPO" "$FPM_RELEASE_GATE_STATE" "$FPM_RELEASE_EVIDENCE_DIR" "$FPM_RELEASE_CANDIDATE"' 2>/dev/null)"
IFS='|' read -r i_main i_state i_ev i_cand <<< "$out"
check "상속 문맥 무시: MAIN = 자기 저장소" "$i_main" "$TOP"
check "상속 문맥 무시: 기록 경로 = 자기 저장소" "$i_state" "$TOP/data/releases/release-gates.yml"
check "상속 문맥 무시: 증거 경로 = 자기 저장소" "$i_ev" "$TOP/_doc_work/_release"
check "상속 문맥 무시: 후보 = 자기 HEAD" "$i_cand" "$(git -C "$R" rev-parse HEAD)"
check "다른 저장소 worktree 무접촉" "$(git -C "$O" worktree list --porcelain)" "$O_WT"

# ── ⑦ 격리 worktree 안에서 부산물을 남겨도 정리된다(--force remove) ──
bash "$RUN" HEAD -- bash -c 'echo junk > junk.tmp' >/dev/null 2>&1; rc=$?
check "부산물 남기는 명령 rc 0" "$rc" "0"
check "부산물이 있어도 worktree 정리" "$(git -C "$R" worktree list --porcelain)" "$WT_BEFORE"

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
