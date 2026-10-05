#!/bin/bash
# test_release_gate_r2.sh — Issue543 M2 회귀 테스트 (tdd playlist #38 release-gate-r2)
#
# 출고 게이트 G4(`scripts/fpm-sync.sh` release_gate_recheck)가 글로벌 R2
# (`~/.claude/sh/release-test-audit.py recheck`)의 래퍼로서 다음을 지키는지 검증한다.
#   ① 출고 버전 증거 없음 → 차단 (구 G4 는 yml 에 조상 기록만 있으면 통과시켰다)
#   ② 증거 이후 코드 커밋(번들 SCAR md 포함 — code_paths) → 차단 (구 G4 는 «경고» 만 했다)
#   ③ 증거 이후 Issue.md 만 → 통과 (정상 절차: 병합 뒤 완료 기록)
#   ④ FPM_SKIP_RELEASE_GATE=1 에 FPM_SKIP_REASON 이 없으면 거부 (구 G4 는 사유 없이 통과)
#   ⑤ 사유가 있으면 통과 + 증거 폴더 release-skip_{VER}.md 와 로그에 사유를 남긴다
#   ⑥ R2 도구가 없으면 차단 (조용히 통과하지 않는다)
#   ⑦ do_deploy 배선: 출고 버전(deploy_target_version)으로 R2 를 부르고, 그 버전을 bump 대상과 대조한다
#
# 격리: 임시 git repo. 대상 함수는 실물 scripts/fpm-sync.sh 에서 **추출**해 eval 한다(재구현 금지).
#       R2 는 실물 ~/.claude/sh/release-test-audit.py (없으면 rc 3 — 검증 불가).
# 실행: bash scripts/test_release_gate_r2.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SYNC="$REPO/scripts/fpm-sync.sh"
AUDIT="${FPM_RELEASE_AUDIT:-$HOME/.claude/sh/release-test-audit.py}"
SB="$(mktemp -d "${TMPDIR:-/tmp}/gate-r2.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

echo "[test_release_gate_r2]"
[ -f "$AUDIT" ] || { echo "  skip R2 도구 없음: $AUDIT"; exit 3; }

# 대상 함수 추출 — 정의 블록(^name() { … ^}) 그대로
FUNCS="$SB/funcs.sh"
for fn in next_patch_version deploy_target_version release_gate_recheck; do
    awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {p=1} p {print} p && /^}/ {p=0}' "$SYNC" >> "$FUNCS"
done

R="$SB/repo"
mkdir -p "$R/tdd" "$R/sh" "$R/scripts" "$R/plugins/fpm-core/skills/x" "$R/data/releases"
echo "0.1.0" > "$R/VERSION"
printf -- '---\ntitle: t\ngate: pre-merge\ncode_paths: plugins/**,.claude/**\ndoc_paths: data/releases/\n---\n' > "$R/tdd/release.md"
echo "# skill" > "$R/plugins/fpm-core/skills/x/SKILL.md"
echo "echo hi" > "$R/sh/x.sh"
echo "# issues" > "$R/Issue.md"
G() { git -C "$R" -c user.name=t -c user.email=t@t "$@"; }
git -C "$R" init -q -b main && G add -A && G commit -q -m c0
C0="$(git -C "$R" rev-parse HEAD)"
# 구 G4 가 통과 근거로 쓰던 yml 기록(dirty: no) — 이것만으로는 더 이상 통과하면 안 된다
printf 'gates:\n  - { suite: release, version: 0.1.0, commit: %s, dirty: no }\n' "${C0:0:7}" > "$R/data/releases/release-gates.yml"
EVD="$R/_doc_work/_release/v0.1.1"; mkdir -p "$EVD"
printf -- '---\nversion: 0.1.1\ncommit: %s\ndirty: no\nresult: pass\n---\n' "$C0" > "$EVD/release-test_0.1.1.md"
G add -A && G commit -q -m evidence

# 추출 함수를 fixture 에 대고 부른다 — exit 은 서브셸에 가둔다
gate() {  # $1 = 버전, 나머지 env 는 호출자가
    ( SRC="$R"; HERE="$R/scripts"; VERSION_REL=VERSION
      log() { printf '%s\n' "$1"; }
      . "$FUNCS"
      release_gate_recheck "$1" )
}
export FPM_RELEASE_AUDIT="$AUDIT"
unset FPM_SKIP_RELEASE_GATE FPM_SKIP_REASON
# R1(tdd/run-release.sh) 안에서 돌면 RELEASE_TEST_R1=1 이 상속돼 recheck 가 «생략» rc 0 이 된다 — 차단 검증이 공허해지지 않게 해제
unset RELEASE_TEST_R1

# ── 기준선: 증거 직후 → 통과 ──
out="$(gate 0.1.1 2>&1)"; rc=$?
check "기준선: v0.1.1 증거 직후 → 통과" "$rc" "0"

# ── ① 출고 버전 증거 없음 → 차단 ──
out="$(gate 0.2.0 2>&1)"; rc=$?
check "① 출고 버전(v0.2.0) 증거 없음 → 차단" "$rc" "1"

# ── ③ 증거 이후 Issue.md 만 → 통과 ──
echo "- done" >> "$R/Issue.md"; G commit -qam issue-only
out="$(gate 0.1.1 2>&1)"; rc=$?
check "③ 증거 이후 Issue.md 만 → 통과" "$rc" "0"

# ── ② 증거 이후 번들 SCAR md 커밋 → 차단 ──
echo "changed" >> "$R/plugins/fpm-core/skills/x/SKILL.md"; G commit -qam scar-md
out="$(gate 0.1.1 2>&1)"; rc=$?
check "② 증거 이후 번들 SCAR md 변경 → 차단" "$rc" "1"
case "$out" in *SKILL.md*) ok "② 차단 사유에 변경 파일 표시" ;; *) fail "② 차단 사유에 변경 파일 표시 (out: $out)" ;; esac

# ── ④ 사유 없는 우회 → 거부 ──
out="$(FPM_SKIP_RELEASE_GATE=1 gate 0.1.1 2>&1)"; rc=$?
check "④ FPM_SKIP_RELEASE_GATE=1 · 사유 없음 → 거부" "$rc" "1"
out="$(FPM_SKIP_RELEASE_GATE=1 FPM_SKIP_REASON="   " gate 0.1.1 2>&1)"; rc=$?
check "④ 공백뿐인 사유 → 거부" "$rc" "1"

# ── ⑤ 사유 있는 우회 → 통과 + 기록 ──
out="$(FPM_SKIP_RELEASE_GATE=1 FPM_SKIP_REASON="hotfix 긴급 — 테스트 사유" gate 0.1.1 2>&1)"; rc=$?
check "⑤ 사유 있는 우회 → 통과" "$rc" "0"
SK="$EVD/release-skip_0.1.1.md"
if grep -q 'hotfix 긴급 — 테스트 사유' "$SK" 2>/dev/null; then ok "⑤ 증거 폴더 release-skip_0.1.1.md 에 사유"; else fail "⑤ 증거 폴더 사유 기록 (없음: $SK)"; fi
case "$out" in *"hotfix 긴급"*) ok "⑤ deploy 로그에 사유" ;; *) fail "⑤ deploy 로그에 사유" ;; esac

# ── ⑥ R2 도구 부재 → 차단 ──
out="$(FPM_RELEASE_AUDIT="$SB/none.py" gate 0.1.1 2>&1)"; rc=$?
check "⑥ R2 도구 없음 → 차단 (조용한 통과 금지)" "$rc" "1"

# ── ⑦ do_deploy 배선 (정적) ──
body="$(awk '/^do_deploy\(\) \{/{p=1} p{print} p&&/^}/{exit}' "$SYNC")"
res="$(BODY="$body" python3 - <<'PYEOF'
import os, re
b = os.environ["BODY"]
def at(p):
    m = re.search(p, b); return m.start() if m else -1
plan  = at(r'PLANNED="\$\(deploy_target_version "\$level"\)"')
gate  = at(r'release_gate_recheck "\$PLANNED"')
new   = at(r'NEW="\$\(deploy_target_version "\$level"\)"')
cmp_  = at(r'"\$NEW" !?= "\$PLANNED"')
bump  = at(r'write_version_files "\$NEW"')
names = ["plan", "gate", "new", "cmp", "bump"]
idx = [plan, gate, new, cmp_, bump]
lost = [n for n, i in zip(names, idx) if i < 0]
print("ANCHOR-LOST:" + ",".join(lost) if lost else ("ok" if idx == sorted(idx) else "ORDER-BROKEN"))
PYEOF
)"
check "⑦ do_deploy: 출고 버전 계산 → R2 → 재계산·대조 → bump 순서" "$res" "ok"

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
