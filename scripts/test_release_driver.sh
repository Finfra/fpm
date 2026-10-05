#!/bin/bash
# test_release_driver.sh — Issue543 M1-0·M1-2 회귀 테스트 (tdd playlist #36 release-driver)
#
# R1 드라이버 `tdd/run-release.sh` 와 범용 재생목록 실행기 `tdd/playlist-run.py` 를 검증한다.
#   ① 표 파싱: 실행 열의 첫 명령을 돌리고, `—`(실행 수단 없음)·`수동`·`기동 필요`(외부 대기) 행은 skip 으로 분류
#   ② 행별 결과(pass/fail/skip/partial)를 모아 기록기 --rows 로 넘긴다 — 건너뛴 행이 있으면 result: partial
#   ③ 공유 작업트리(dirty)에서 불러도 스스로 격리 worktree 로 들어가 증거가 `dirty: no` 로 남는다
#   ④ 개발 재생목록(1행 dev-playlist-green)에 외부 대기 행이 있으면 그 행은 partial (rc 3)
#   ⑤ 같은 실행 안에서 같은 명령은 한 번만 돈다(1행 안의 release-check 를 2행이 재사용)
#   ⑥ 수동 행은 --manual <id>=pass:<근거> 로만 pass 가 되고, 실패 행은 fail + 마지막 출력 줄을 비고에 남긴다
#   ⑦ --version 미지정이면 deploy patch 와 같은 규칙(scripts/fpm-sync.sh next-version)으로 출고 버전을 정한다
#
# 격리: 임시 git repo + 임시 projects 인덱스. 검사 대상은 실물 복사.
# 실행: bash scripts/test_release_driver.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/rel-driver.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
fmv() { sed -n '/^---$/,/^---$/p' "$1" 2>/dev/null | sed -n "s/^$2: *//p" | head -1; }
rowres() { grep "| \`$2\` |" "$1" 2>/dev/null | awk -F'|' '{gsub(/ /,"",$4); print $4}' | head -1; }

need=(tdd/playlist-run.py tdd/run-playlist.sh tdd/run-release.sh sh/release-candidate-run.sh
      scripts/fpm-deploy-record.sh scripts/fpm-sync.sh scripts/fpm-policy-lib.sh)
missing=0
for f in "${need[@]}"; do [ -f "$REPO/$f" ] || { fail "대상 존재: $f"; missing=1; }; done
[ "$missing" -eq 0 ] || { echo "── PASS $PASS / FAIL $FAIL"; exit 1; }

R="$SB/repo"
mkdir -p "$R/tdd" "$R/sh" "$R/scripts" "$R/data/releases"
for f in "${need[@]}"; do cp "$REPO/$f" "$R/$f"; done
echo "0.0.1" > "$R/VERSION"
cat > "$R/tdd/ok.sh" <<'EOF'
#!/bin/bash
[ -n "${COUNT_FILE:-}" ] && echo x >> "$COUNT_FILE"
echo "ok-run"
EOF
printf '#!/bin/bash\necho "boom: last line"\nexit 4\n' > "$R/tdd/bad.sh"
printf '#!/bin/bash\n[ "${RELEASE_TEST_R1:-}" = 1 ] || { echo "RELEASE_TEST_R1 미설정"; exit 1; }\n' > "$R/tdd/r1env.sh"
cat > "$R/tdd/playlist.md" <<'EOF'
---
title: fixture playlist
---
| # | id | 목표 | 근거 | 실행 | 상태 |
| :- | :- | :- | :- | :- | :- |
| 1 | `p-ok` | ok | x | `bash tdd/ok.sh` | ✅ |
| 2 | `p-hub` | hub | x | `node tdd/x.js` (hub 기동 필요) | ✅ |
EOF
cat > "$R/tdd/release.md" <<'EOF'
---
title: fixture release
gate: pre-merge
env: authoring
peers: prj3
doc_paths: data/releases/
---
| # | id | 채널 | 목표 | 근거 | 실행 | 상태 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 1 | `dev-playlist-green` | — | 개발 재생목록 | x | `bash tdd/run-playlist.sh` (코어 전 행) | ⬜ |
| 2 | `release-check` | 소스 | g3 | x | `bash tdd/ok.sh` | ⬜ |
| 3 | `native-linux` | native | 원격 | x | — (`tdd/run-remote.sh` 🚧 plan M3) | ⬜ |
| 4 | `hub-ui-signoff` | 수동 | 체크 | x | 수동 — B-2 체크리스트 | ⬜ |
| 5 | `board-x` | board | 자리 | x | — | ⬜ |
EOF
git -C "$R" init -q -b main
git -C "$R" add -A
git -C "$R" -c user.name=t -c user.email=t@t commit -q -m base
C1="$(git -C "$R" rev-parse HEAD)"
# peers 해석용 가짜 prj3
P3="$SB/prj3"; mkdir -p "$P3"; git -C "$P3" init -q -b main
git -C "$P3" -c user.name=t -c user.email=t@t commit -q --allow-empty -m p3
mkdir -p "$SB/projects"; echo "$P3" > "$SB/projects/3"
export PM_PROJECTS_DIR="$SB/projects"
unset FPM_RELEASE_CANDIDATE FPM_RELEASE_MAIN_REPO FPM_RELEASE_GATE_STATE FPM_RELEASE_EVIDENCE_DIR FPM_PLAYLIST_MEMO

# 공유 작업트리를 더럽힌다
echo "WIP" >> "$R/VERSION.note"

echo "[test_release_driver]"

# ── ① 분류 (--list) ──
lst="$(cd "$R" && python3 tdd/playlist-run.py tdd/release.md --list 2>&1)"
case "$lst" in *"dev-playlist-green"*command*) ok "분류: 명령 행 = command" ;; *) fail "분류: 명령 행 (got: $lst)" ;; esac
case "$lst" in *"native-linux"*none*) ok "분류: — 행 = none (백틱 경로를 실행하지 않는다)" ;; *) fail "분류: — 행 = none" ;; esac
case "$lst" in *"hub-ui-signoff"*manual*) ok "분류: 수동 행 = manual" ;; *) fail "분류: 수동 행 = manual" ;; esac
lst2="$(cd "$R" && python3 tdd/playlist-run.py tdd/playlist.md --list 2>&1)"
case "$lst2" in *"p-hub"*external*) ok "분류: 기동 필요 행 = external" ;; *) fail "분류: 기동 필요 행 = external (got: $lst2)" ;; esac

# ── ④ 개발 재생목록 러너: 외부 대기 행 → rc 3 ──
(cd "$R" && bash tdd/run-playlist.sh >/dev/null 2>&1); rc=$?
check "개발 재생목록에 외부 대기 행 → rc 3 (partial)" "$rc" "3"

# ── ③⑤⑦ 드라이버 E2E: 공유 작업트리에서 호출 → 격리 → 증거 ──
export COUNT_FILE="$SB/count"; : > "$COUNT_FILE"
WT_BEFORE="$(git -C "$R" worktree list --porcelain)"
out="$(cd "$R" && bash tdd/run-release.sh 2>&1)"; rc=$?
check "건너뛴 행 있음 → 드라이버 rc 3" "$rc" "3"
EV="$R/_doc_work/_release/v0.0.2/release-test_0.0.2.md"
if [ -f "$EV" ]; then ok "--version 생략 → 다음 patch v0.0.2 증거"; else fail "v0.0.2 증거 없음 (out: $(printf '%s' "$out" | tail -5))"; fi
check "증거 dirty: no (스스로 격리)" "$(fmv "$EV" dirty)" "no"
check "증거 commit = 후보" "$(fmv "$EV" commit)" "$C1"
check "증거 result: partial" "$(fmv "$EV" result)" "partial"
check "증거 env = release.md env" "$(fmv "$EV" env)" "authoring"
check "증거 peers = prj3@HEAD" "$(fmv "$EV" peers)" "prj3@$(git -C "$P3" rev-parse --short HEAD)"
check "1행 dev-playlist-green = partial" "$(rowres "$EV" dev-playlist-green)" "partial"
if grep "| \`dev-playlist-green\` |" "$EV" | grep -q 'p-hub'; then ok "1행 비고에 건너뛴 하위 행 id(p-hub)"; else fail "1행 비고에 건너뛴 하위 행 id(p-hub)"; fi
check "맨 — 행 비고 = «실행 수단 없음» (문구 중복 없음)" "$(grep "| \`board-x\` |" "$EV" | awk -F'|' '{gsub(/^ +| +$/,"",$5); print $5}')" "실행 수단 없음"
check "2행 release-check = pass" "$(rowres "$EV" release-check)" "pass"
check "3행 native-linux = skip" "$(rowres "$EV" native-linux)" "skip"
check "4행 hub-ui-signoff = skip (수동 미기록)" "$(rowres "$EV" hub-ui-signoff)" "skip"
check "같은 명령은 한 번만 (1행 안 p-ok 와 2행 공유)" "$(wc -l < "$COUNT_FILE" | tr -d ' ')" "1"
check "드라이버 후 worktree 목록 불변" "$(git -C "$R" worktree list --porcelain)" "$WT_BEFORE"

# ── ⑥ 수동 결과·실패 행 ──
cat > "$R/tdd/release.md" <<'EOF'
---
title: fixture release 2
gate: pre-merge
env: authoring
---
| # | id | 채널 | 목표 | 근거 | 실행 | 상태 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 1 | `release-check` | 소스 | g3 | x | `bash tdd/ok.sh` | ⬜ |
| 2 | `hub-ui-signoff` | 수동 | 체크 | x | 수동 — B-2 체크리스트 | ⬜ |
| 3 | `r1-env` | x | R1 규약 | x | `bash tdd/r1env.sh` | ⬜ |
EOF
git -C "$R" add -A tdd/release.md && git -C "$R" -c user.name=t -c user.email=t@t commit -q -m r2
out="$(cd "$R" && bash tdd/run-release.sh --version 0.1.0 --manual "hub-ui-signoff=pass:_doc_work/report/b2.md" 2>&1)"; rc=$?
EV2="$R/_doc_work/_release/v0.1.0/release-test_0.1.0.md"
check "전 행 통과 + 수동 pass 기록 → rc 0" "$rc" "0"
check "result: pass" "$(fmv "$EV2" result)" "pass"
if grep -q 'b2.md' "$EV2" 2>/dev/null; then ok "수동 근거가 비고에 남는다"; else fail "수동 근거 비고"; fi
check "행은 RELEASE_TEST_R1=1 로 돈다 (release-test-rules R1 실행 규약)" "$(rowres "$EV2" r1-env)" "pass"

printf '| 4 | `bad-row` | x | x | x | `bash tdd/bad.sh` | ⬜ |\n' >> "$R/tdd/release.md"
git -C "$R" add -A tdd/release.md && git -C "$R" -c user.name=t -c user.email=t@t commit -q -m r3
out="$(cd "$R" && bash tdd/run-release.sh --version 0.1.1 --manual "hub-ui-signoff=pass:ok" 2>&1)"; rc=$?
EV3="$R/_doc_work/_release/v0.1.1/release-test_0.1.1.md"
check "실패 행 → 드라이버 rc 1" "$rc" "1"
check "실패 행 → result: fail" "$(fmv "$EV3" result)" "fail"
if grep -q 'boom: last line' "$EV3" 2>/dev/null; then ok "실패 비고 = 마지막 출력 줄"; else fail "실패 비고 = 마지막 출력 줄"; fi

# ── 입력 오류: 허용 외 --manual 토큰 → rc 2, 증거 없음 ──
out="$(cd "$R" && bash tdd/run-release.sh --version 0.1.2 --manual "hub-ui-signoff=ok" 2>&1)"; rc=$?
check "잘못된 --manual → rc 2" "$rc" "2"
if [ ! -f "$R/_doc_work/_release/v0.1.2/release-test_0.1.2.md" ]; then ok "입력 오류 → 증거 없음"; else fail "입력 오류인데 증거 생성"; fi

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
