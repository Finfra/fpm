#!/usr/bin/env bash
# fpm-pr-absorb.sh — 미러 외부 PR 2단 흡수 (F5-2 / prj3 감사 ◆P4 v1.0.3)
#
# ⚠️ 글로벌 SCAR 변경 가드: cwd ≠ ~/_git/___pm 이면 즉흥 수정 금지.
#   설계 SSOT: _doc_arch/fpm-sync-deploy.md · 정책: data/publishable-policy.yml
#
# 왜 reverse 가 아닌가 (P1):
#   reverse 는 스냅샷 rsync 라 ① 저작자 소실 ② sanitize 오염 전파 ③ fpm:private 소실을
#   일으킨다. 외부 PR 은 반드시 이 경로로 흡수한다.
#
# 2단 판정 (◆P4 — 실측 Tier1 적용률 94.1%)
#   PR 이 건드린 파일의 **blob 이 원본에 전부 존재하면** Tier1: `git am` 으로 패치 적용.
#     저작자·커밋 메시지가 그대로 보존된다.
#   하나라도 부재하면 Tier2: `pr/<n>` 전용 브랜치에 수동 재작성.
#     blob 부재 = 그 파일이 sanitize 로 변형됐다는 뜻이라, 패치가 원본에 안 맞는다.
#
# ⚠️ **판정은 PR 마다 재계산한다.** 정적 목록(이 파일은 항상 Tier2 등)을 만들지 말 것 —
#   policy 의 sanitize 규칙이 바뀌면 같은 파일도 판정이 뒤집힌다.
#
# Usage:
#   bash scripts/fpm-pr-absorb.sh <미러경로> <PR브랜치> [원본경로]
#   FPM_PR_APPLY=1 을 주지 않으면 **판정만** 하고 끝난다(기본 dry-run).

set -uo pipefail

MIRROR="${1:-}"
BRANCH="${2:-}"
SRC="${3:-$HOME/_git/___pm}"
APPLY="${FPM_PR_APPLY:-0}"

[ -n "$MIRROR" ] && [ -n "$BRANCH" ] || {
  sed -n '/^# Usage:/,$p' "$0" | sed 's/^# \{0,2\}//' | head -5; exit 2; }

BASE=$(git -C "$MIRROR" merge-base main "$BRANCH" 2>/dev/null) || {
  echo "❌ merge-base 없음: main..$BRANCH" >&2; exit 1; }

files=$(git -C "$MIRROR" diff --name-only "$BASE".."$BRANCH")
[ -n "$files" ] || { echo "변경 파일 0 — 흡수할 것이 없다"; exit 0; }

# ── blob 판정 ────────────────────────────────────────────────────────
# PR 이 건드린 파일의 **변경 전 blob**(base 시점)이 원본에도 있는가.
# 있으면 그 파일은 sanitize 를 타지 않았다는 뜻이라 패치가 그대로 맞는다.
tier=1
miss=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  b=$(git -C "$MIRROR" rev-parse "$BASE:$f" 2>/dev/null) || { tier=2; miss="$miss $f(미러에 없음)"; continue; }
  if git -C "$SRC" cat-file -e "$b" 2>/dev/null; then
    :                       # 원본에 같은 blob 존재 → 변형되지 않았다
  else
    tier=2; miss="$miss $f"
  fi
done <<< "$files"

echo "PR: $BRANCH  (base ${BASE:0:7})"
echo "변경 파일:"; printf '%s\n' "$files" | sed 's/^/    /'
if [ "$tier" = 1 ]; then
  echo "판정: **Tier1** — 전 파일 blob 이 원본에 존재. \`git am\` 으로 저작자 보존 흡수 가능"
else
  echo "판정: **Tier2** — blob 부재:$miss"
  echo "      해당 파일은 sanitize 로 변형됐다. 패치가 원본에 맞지 않으므로"
  echo "      pr/<n> 전용 브랜치에서 **수동 재작성**한다(working tree 직접 rsync 금지 — P6)."
fi

[ "$APPLY" = 1 ] || { echo; echo "(dry-run — 실제 적용은 FPM_PR_APPLY=1)"; exit 0; }

# ── 적용 ─────────────────────────────────────────────────────────────
if [ "$tier" != 1 ]; then
  echo "❌ Tier2 는 자동 적용하지 않는다. pr/<n> 브랜치를 만들어 수동으로 옮길 것" >&2
  exit 1
fi
PDIR=$(mktemp -d); PATCH="$PDIR/pr.patch"
git -C "$MIRROR" format-patch --stdout "$BASE".."$BRANCH" > "$PATCH"
# ⚠️ P5: 자동 경로라고 시크릿 스캔을 건너뛰지 않는다.
#   gitleaks `--source` 는 **디렉토리**를 기대한다 — 파일을 주면 스캔이 성립하지 않아
#   무조건 차단으로 보이는 오탐이 난다(1차 구현에서 실측). 임시 디렉토리째 스캔한다.
if command -v gitleaks >/dev/null 2>&1; then
  # ⚠️ `-q` 를 주지 말 것 — gitleaks 에 없는 옵션이라 **옵션 오류로 비정상 종료**하고
  #   그것이 '시크릿 검출' 로 오독돼 정상 패치가 전부 차단된다(2차 시도에서 실측).
  #   출력 억제는 리다이렉트로 충분하다.
  if ! gitleaks detect --no-git --source "$PDIR" --redact >/dev/null 2>&1; then
    echo "🚨 패치에서 시크릿 검출 — 흡수 중단" >&2; rm -rf "$PDIR"; exit 1
  fi
fi
if git -C "$SRC" am --3way < "$PATCH"; then
  echo "✅ Tier1 흡수 완료 (저작자 보존)"
else
  git -C "$SRC" am --abort 2>/dev/null
  echo "❌ am 실패 — Tier2 로 강등해 수동 처리할 것" >&2; rm -rf "$PDIR"; exit 1
fi
rm -rf "$PDIR"
