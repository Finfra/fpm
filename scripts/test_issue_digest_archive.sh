#!/usr/bin/env bash
# test_issue_digest_archive.sh — 아카이브(_doc_work/Issue_OLD.md)로 옮긴 이슈가 digest 에서 사라지지 않는지 검증 (Issue648)
#   digest 의 존재 이유는 코드 주석의 이슈 번호 근거 제공이다. 완료 이슈를 아카이브로 옮기면
#   Issue.md 만 읽던 digest 가 급감해 그 근거가 공개 미러에서 사라졌다(1752 → 약 100줄, 실측 2026-10-18).
#   정책: issue_digest_archive_min(이상 이월) + issue_digest_archive_extra(개별). 이 테스트는 min=10, extra=[6].
#   (번호 토큰을 `Issue` 접두와 붙여 쓰지 않는다 — 접두+번호는 그 자체로 digest 반출 스위치라 변수로 조립한다)
#   기대:
#     ① 현행 20 과 아카이브의 11(min 이상)·6(extra)이 digest 에 실린다 (모두 코드가 참조)
#     ② 아카이브의 5(min 미만·extra 아님)는 코드가 참조해도 실리지 않는다 — 새 공개 방지
#     ③ 코드가 참조하지 않는 아카이브 이슈 12 는 실리지 않는다 — 참조 필터가 노출 상한이다
#     ④ HEAD 기준 --check: 신선 → rc 0 · 아카이브만 커밋 변경 → stale rc 3
#     ⑤ 명시 SRC 인자를 준 호출은 종전대로 그 파일만 읽는다 (아카이브를 섞지 않는다)
set -uo pipefail
I=Issue
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/scripts" "$T/_doc_work" "$T/data"; cp "$HERE/fpm-issue-digest.sh" "$T/scripts/"
cd "$T"
git init -q . && git config user.email t@t && git config user.name t
printf 'issue_digest_archive_min: 10\nissue_digest_archive_extra:\n  - 6\n\nexclude:\n  - x\n' > data/publishable-policy.yml
printf '# Issue Management\n\n# ✅ 완료\n\n## %s20: 현행 이슈\n* 목적: 현행\n* 구현 명세:\n    - 항목\n' "$I" > Issue.md
{ printf '# 보관\n\n# ✅ 완료\n'
  for n in 11 12 6 5; do printf '\n## %s%s: 보관 이슈\n* 목적: 보관 %s\n* 구현 명세:\n    - 항목\n' "$I" "$n" "$n"; done; } > _doc_work/Issue_OLD.md
printf 'a // %s11\nb // %s20\nc // %s6\nd // %s5\n' "$I" "$I" "$I" "$I" > code.txt
git add -A && git commit -qm init
fail=0
bash scripts/fpm-issue-digest.sh >/dev/null 2>&1 || { echo "FAIL: digest 생성 실패"; exit 1; }
for n in 20 11 6; do grep -q "^## $I$n:" Issue_public.md || { echo "FAIL: ① $n 누락 (아카이브 근거 유실)"; fail=1; }; done
grep -q "^## ${I}5:" Issue_public.md && { echo "FAIL: ② min 미만 5 가 새로 공개됨"; fail=1; }
grep -q "^## ${I}12:" Issue_public.md && { echo "FAIL: ③ 비참조 12 가 노출됨"; fail=1; }
git add -A && git commit -qm digest
bash scripts/fpm-issue-digest.sh --check >/dev/null 2>&1 || { echo "FAIL: ④ 신선 상태 rc!=0"; fail=1; }
printf '\n## %s13: 추가 보관\n* 목적: x\n' "$I" >> _doc_work/Issue_OLD.md
git add -A && git commit -qm old-change
bash scripts/fpm-issue-digest.sh --check >/dev/null 2>&1; rc=$?
[ "$rc" = 3 ] || { echo "FAIL: ④ 아카이브 변경 커밋 뒤 rc=$rc (기대 3)"; fail=1; }
printf '# x\n\n## %s20: 현행 이슈\n* 목적: 현행\n' "$I" > "$T/only.md"
bash scripts/fpm-issue-digest.sh "$T/only.md" "$T/only_out.md" >/dev/null 2>&1
grep -q "^## ${I}11:" "$T/only_out.md" && { echo "FAIL: ⑤ 명시 SRC 호출에 아카이브가 섞임"; fail=1; }
[ "$fail" = 0 ] && echo "PASS: digest 아카이브 이월"
exit "$fail"
