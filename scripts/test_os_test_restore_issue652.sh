#!/bin/bash
# test_os_test_restore_issue652.sh — Issue652 회귀 테스트
#
# OS 테스트(zero-base clear)가 끝난 머신을 clear 이전 상태(prj3 `~/.claude` · prj1 `~/_git/fpm`)로 되돌리는지 본다.
# 안 되면 jma 가 테스트 상태로 사흘 남았다(2026-10-18 → 10-21).
#
#   A. clear 페이로드 step 1 — fpm 로컬 파일(untracked+ignored) tar 를 만들고, 실패하면 `~/.claude` 를 비우지 않는다
#   B. 복귀 페이로드
#      ① 인자 없음 = plan(읽기 전용, rc 2, 아무것도 안 바뀜) · --dry-run 도 아무것도 안 바뀜
#      ② --stamp: 사라진 설정 복원 · 바뀐 설정 복원(현재본은 safety 에 보관)
#      ③ `.credentials.json`(더 새 로그인)·volatile(history.jsonl)·존재하는 `.git` 은 덮지 않는다 / 사라졌으면 복원
#      ④ fpm: detached → main 복귀 · 로컬 gitignored 파일 복원(tar 우선, 없으면 .bak) · 잡파일(.DS_Store·__pycache__) 제외
#      ⑤ 멱등: 두 번째 실행은 복원 0건 · .bak/tar 는 지우지 않는다 · 없는 스탬프는 rc 3
#
# 격리: 가짜 HOME + 로컬 bare origin. 실물 스크립트를 그대로 돈다(재구현 금지).
# 실행: bash scripts/test_os_test_restore_issue652.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CLEAR="$REPO/scripts/os-test-payload.sh"
RESTORE="$REPO/scripts/os-test-restore-payload.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/os-restore.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
has()  { if printf '%s' "$2" | grep -qF -- "$3"; then ok "$1"; else fail "$1 (없음: '$3')"; fi; }

export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
STAMP="2026.10.18_1513"

echo "[test_os_test_restore_issue652]"
[ -f "$CLEAR" ]   && ok "clear 페이로드 존재(scripts/)" || fail "clear 페이로드가 scripts/ 에 없다"
[ -f "$RESTORE" ] && ok "복귀 페이로드 존재" || fail "복귀 페이로드 없음 — scripts/os-test-restore-payload.sh"

# ── 하니스: clear 이전 상태를 만들고 → 백업 → clear+설치를 흉내낸다 ──────────────────────────────
mk_origin() {   # bare origin: main 에 커밋 2개, 태그 v1 은 첫 커밋
    local O="$SB/origin.git" W="$SB/w"
    git init -q --bare -b main "$O"
    git init -q -b main "$W"
    printf 'Projects.md\ndata/local.yml\nsh/fpm_aliases_iterm-bg.sh\n.zed/\n' > "$W/.gitignore"
    echo 1 > "$W/VERSION"; git -C "$W" add -A; git -C "$W" commit -q -m c1; git -C "$W" tag v1
    echo 2 > "$W/VERSION"; git -C "$W" commit -q -am c2
    git -C "$W" push -q "$O" main --tags
}
mk_case() {     # $1=이름 → $SB/$1/home 에 clear 직후 상태
    local H="$SB/$1/home"; mkdir -p "$H/.claude/hooks/lib" "$H/.claude/commands" "$H/.claude/plugins" "$H/.claude/.git" "$H/.claude/openclaw-plugins" "$H/_git"
    # 이전(원본) 상태
    echo "OLD-CLAUDE-MD" > "$H/.claude/CLAUDE.md"
    echo '{"old":1}'     > "$H/.claude/settings.json"
    echo "cmd-a"         > "$H/.claude/commands/a.md"
    echo "SEL"           > "$H/.claude/hooks/lib/selection.py"
    echo "OLDTOKEN"      > "$H/.claude/.credentials.json"
    echo "oldhist"       > "$H/.claude/history.jsonl"
    echo "oldsweep"      > "$H/.claude/plugins/.last_inuse_sweep"
    echo "ref: refs/heads/main" > "$H/.claude/.git/HEAD"
    echo "plug"          > "$H/.claude/openclaw-plugins/p.txt"
    # fpm .bak (clear 이전 clone: main + 로컬 파일)
    git clone -q "$SB/origin.git" "$H/_git/fpm.bak-$STAMP"
    local B="$H/_git/fpm.bak-$STAMP"
    echo "LOCAL-PROJECTS" > "$B/Projects.md"; mkdir -p "$B/data" "$B/projects" "$B/sh" "$B/.zed" "$B/x/__pycache__" "$B/tdd/results"
    echo "LOCAL-YML" > "$B/data/local.yml"; echo "idx11" > "$B/projects/11"; echo "alias" > "$B/sh/fpm_aliases_iterm-bg.sh"
    echo "z" > "$B/.zed/s.json"; echo "ds" > "$B/.DS_Store"; echo "pyc" > "$B/x/__pycache__/a.pyc"; echo "r" > "$B/tdd/results/r.txt"
    # 백업 tar
    tar -czf "$H/claude-backup-$STAMP.tar.gz" -C "$H" .claude
    # ── clear: .credentials.json·openclaw-plugins 만 남기고 비움 → 설치 흉내 ──
    ( cd "$H/.claude" && ls -A | grep -vxE '\.credentials\.json|openclaw-plugins' | while IFS= read -r e; do rm -rf -- "$e"; done )
    echo "NEWTOKEN" > "$H/.claude/.credentials.json"; sleep 1; touch "$H/.claude/.credentials.json"
    echo '{"installed":1}' > "$H/.claude/settings.json"
    mkdir -p "$H/.claude/commands"; echo "fpm" > "$H/.claude/commands/fpm-only.md"
    echo "newhist" > "$H/.claude/history.jsonl"
    # 새 clone: 태그 v1 detached + 기본 로컬 파일
    git -c advice.detachedHead=false clone -q --branch v1 "$SB/origin.git" "$H/_git/fpm"
    echo "DEFAULT-PROJECTS" > "$H/_git/fpm/Projects.md"
}
snapshot() { ( cd "$1" && find . -type f -not -path './.claude/projects/*' | sort | xargs -I{} sh -c 'printf "%s " "{}"; cksum < "{}"' ) | cksum; }

mk_origin
mk_case a; H="$SB/a/home"

# ── A. clear 페이로드 step 1 — fpm-local tar ────────────────────────────────────────────
# step 1 = "# 1. " ~ "# 2. " 직전. 비우기 직전까지의 하니스: 변수·t() 만 흉내
S1="$SB/s1.sh"; awk '/^# 1\. /{p=1} /^# 2\. /{p=0} p' "$CLEAR" > "$S1" 2>/dev/null
mk_case c; HC="$SB/c/home"
# 비우기 직전으로 되돌린다: clear 흉내가 이미 비웠으므로 백업본으로 복원해 clear 전 상태를 만든다
rm -rf "$HC/.claude" && tar -xzf "$HC/claude-backup-$STAMP.tar.gz" -C "$HC"
rm -rf "$HC/_git/fpm" && cp -a "$HC/_git/fpm.bak-$STAMP" "$HC/_git/fpm"; rm -f "$HC/claude-backup-$STAMP.tar.gz"
run_s1() {   # $1=HOME $2=PATH 앞에 붙일 dir(선택)
    ( export HOME="$1"; [ -n "${2:-}" ] && export PATH="$2:$PATH"
      OUT="$1/out"; mkdir -p "$OUT"; FPM="$1/_git/fpm"; STAMP="$STAMP"
      t() { echo "FPMT $*"; }
      . "$S1" ) 2>&1
}
OUT1="$(run_s1 "$HC")"
LT="$HC/fpm-local-$STAMP.tar.gz"
[ -s "$LT" ] && ok "A. fpm-local tar 생성" || fail "A. fpm-local-$STAMP.tar.gz 없음"
LL="$(tar -tzf "$LT" 2>/dev/null)"
has "A. 로컬 ignored 파일 포함(Projects.md)" "$LL" "Projects.md"
has "A. 로컬 ignored 파일 포함(data/local.yml)" "$LL" "data/local.yml"
has "A. 로컬 ignored 파일 포함(projects/11)" "$LL" "projects/11"
printf '%s' "$LL" | grep -qE '\.DS_Store|__pycache__|tdd/results' && fail "A. 잡파일(.DS_Store·__pycache__·tdd/results) 제외 위반" || ok "A. 잡파일 제외"
has "A. FPMT fpm_local=ok" "$OUT1" "fpm_local=ok"
check "A. 정상이면 ~/.claude 는 비워짐(credentials·openclaw-plugins 만)" "$(ls -A "$HC/.claude" | tr '\n' ',')" ".credentials.json,openclaw-plugins,"

mk_case d; HD="$SB/d/home"
rm -rf "$HD/.claude" && tar -xzf "$HD/claude-backup-$STAMP.tar.gz" -C "$HD"
rm -rf "$HD/_git/fpm" && cp -a "$HD/_git/fpm.bak-$STAMP" "$HD/_git/fpm"; rm -f "$HD/claude-backup-$STAMP.tar.gz"
mkdir -p "$SB/failbin"
cat > "$SB/failbin/tar" <<'EOF'
#!/bin/sh
case "$*" in *fpm-local*) echo "tar: forced failure" >&2; exit 1 ;; esac
exec /usr/bin/tar "$@"
EOF
chmod +x "$SB/failbin/tar"
OUT2="$(run_s1 "$HD" "$SB/failbin"; echo "rc=$?")"
has "A. fpm tar 실패 → FAIL 기록" "$OUT2" "fpm_local=FAIL"
[ -f "$HD/.claude/CLAUDE.md" ] && ok "A. fpm tar 실패 시 ~/.claude 를 비우지 않는다" || fail "A. fpm tar 가 실패했는데 ~/.claude 가 비워졌다"

# ── B. 복귀 페이로드 ───────────────────────────────────────────────────────────────────
run_restore() { ( cd "$SB" && HOME="$H" OSTEST_SKIP_AUTH=1 bash "$RESTORE" "$@" 2>&1 ); }

BEFORE="$(snapshot "$H")"
OUT="$(run_restore; echo "rc=$?")"
has "B① 인자 없음 → plan 표" "$OUT" "plan"
has "B① plan 에 스탬프 표시" "$OUT" "$STAMP"
has "B① plan 은 rc 2" "$OUT" "rc=2"
check "B① plan 은 아무것도 바꾸지 않는다" "$(snapshot "$H")" "$BEFORE"

OUT="$(run_restore --stamp "$STAMP" --dry-run; echo "rc=$?")"
has "B① dry-run verdict" "$OUT" "restore_verdict=DRY"
check "B① dry-run 은 아무것도 바꾸지 않는다" "$(snapshot "$H")" "$BEFORE"
[ -z "$(ls -d "$H"/fpm-restore-safety-* 2>/dev/null)" ] && ok "B① dry-run 은 safety 폴더도 만들지 않는다" || fail "B① dry-run 이 safety 폴더를 만들었다"

OUT="$(run_restore --stamp "$STAMP"; echo "rc=$?")"
has "B② 복원 실행 verdict ok" "$OUT" "restore_verdict=ok"
has "B② rc 0" "$OUT" "rc=0"
check "B② 사라진 CLAUDE.md 복원" "$(cat "$H/.claude/CLAUDE.md" 2>/dev/null)" "OLD-CLAUDE-MD"
check "B② 사라진 commands/a.md 복원" "$(cat "$H/.claude/commands/a.md" 2>/dev/null)" "cmd-a"
check "B② 사라진 판정기 복원" "$(cat "$H/.claude/hooks/lib/selection.py" 2>/dev/null)" "SEL"
check "B② 바뀐 settings.json 은 원본으로" "$(cat "$H/.claude/settings.json")" '{"old":1}'
SAFE="$(ls -d "$H"/fpm-restore-safety-* 2>/dev/null | head -1)"
[ -n "$SAFE" ] && check "B② 덮어쓴 settings.json 현재본은 safety 에 보관" "$(cat "$SAFE/claude/settings.json" 2>/dev/null)" '{"installed":1}' || fail "B② safety 폴더 없음"
check "B③ 더 새 로그인(.credentials.json)은 덮지 않는다" "$(cat "$H/.claude/.credentials.json")" "NEWTOKEN"
check "B③ volatile(history.jsonl)이 있으면 덮지 않는다" "$(cat "$H/.claude/history.jsonl")" "newhist"
check "B③ 사라진 volatile(.last_inuse_sweep)은 복원" "$(cat "$H/.claude/plugins/.last_inuse_sweep" 2>/dev/null)" "oldsweep"
check "B③ 사라진 .git 은 복원" "$(cat "$H/.claude/.git/HEAD" 2>/dev/null)" "ref: refs/heads/main"
check "B② 설치로 생긴 파일은 지우지 않는다" "$(cat "$H/.claude/commands/fpm-only.md" 2>/dev/null)" "fpm"

check "B④ detached → main 복귀" "$(git -C "$H/_git/fpm" branch --show-current)" "main"
check "B④ main 은 origin/main 추적" "$(git -C "$H/_git/fpm" rev-parse --abbrev-ref main@{upstream} 2>/dev/null)" "origin/main"
check "B④ 기본값이던 Projects.md 를 로컬본으로" "$(cat "$H/_git/fpm/Projects.md")" "LOCAL-PROJECTS"
check "B④ 로컬 ignored data/local.yml 복원" "$(cat "$H/_git/fpm/data/local.yml" 2>/dev/null)" "LOCAL-YML"
check "B④ 로컬 projects/11 복원" "$(cat "$H/_git/fpm/projects/11" 2>/dev/null)" "idx11"
check "B④ untracked sh/fpm_aliases_iterm-bg.sh 복원" "$(cat "$H/_git/fpm/sh/fpm_aliases_iterm-bg.sh" 2>/dev/null)" "alias"
[ -e "$H/_git/fpm/.DS_Store" ] && fail "B④ .DS_Store 가 복사됐다" || ok "B④ .DS_Store 제외"
[ -e "$H/_git/fpm/x/__pycache__" ] && fail "B④ __pycache__ 가 복사됐다" || ok "B④ __pycache__ 제외"
check "B④ 추적 파일(VERSION)은 origin/main 그대로" "$(cat "$H/_git/fpm/VERSION")" "2"
check "B④ 현재 Projects.md 는 safety 에 보관" "$(cat "$SAFE/fpm/Projects.md" 2>/dev/null)" "DEFAULT-PROJECTS"

# tar 가 있으면 .bak 보다 tar 를 쓴다
mk_case e; HE="$SB/e/home"
rm -rf "$HE/_git/fpm" && git -c advice.detachedHead=false clone -q --branch v1 "$SB/origin.git" "$HE/_git/fpm"
mkdir -p "$SB/ltmp/data"; echo "FROM-TAR" > "$SB/ltmp/Projects.md"; echo "TARYML" > "$SB/ltmp/data/local.yml"
tar -czf "$HE/fpm-local-$STAMP.tar.gz" -C "$SB/ltmp" Projects.md data/local.yml
( cd "$SB" && HOME="$HE" OSTEST_SKIP_AUTH=1 bash "$RESTORE" --stamp "$STAMP" >/dev/null 2>&1 )
check "B④ fpm-local tar 가 있으면 tar 우선(.bak 아님)" "$(cat "$HE/_git/fpm/Projects.md" 2>/dev/null)" "FROM-TAR"

# ⑤ 멱등·보존
OUT="$(run_restore --stamp "$STAMP"; echo "rc=$?")"
has "B⑤ 두 번째 실행 verdict ok" "$OUT" "restore_verdict=ok"
has "B⑤ 두 번째 실행은 복원 0건" "$OUT" "restored=0"
[ -f "$H/claude-backup-$STAMP.tar.gz" ] && [ -d "$H/_git/fpm.bak-$STAMP" ] && ok "B⑤ 백업 tar·.bak 폴더는 지우지 않는다" || fail "B⑤ 백업 tar 또는 .bak 이 사라졌다"
OUT="$(run_restore --stamp 1999.01.01_0000; echo "rc=$?")"
has "B⑤ 없는 스탬프는 rc 3" "$OUT" "rc=3"

echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
