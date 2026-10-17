#!/usr/bin/env python3
# test_issue_badge_map_issue623.py — Issue623 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). hub 카드 미완료 배지(`open_issue_count`)가
#   **이슈맵(`Issue_map.htm`)이 보여 주는 집계**를 그대로 쓰는지 검증한다.
#
# 왜 이 테스트가 필요한가 — 서버가 `Issue.md` 를 직접 세며 완료 섹션을 `{"✅ 완료"}` 하나로만
#   알아봐, 완료 섹션명이 `🏁 완료-해결순` 인 fSnippet 이 미완료 0건인데 배지 20 을 냈다
#   (2026-10-09 실측). 생성기는 같은 Issue.md 를 `이슈 189건 · 완료 189건` 으로 맞게 셌다 —
#   판정이 두 벌로 갈라진 것. 그래서 fixture 맵은 **실제 생성기**로 만든다(문구 계약 박제).
#
# 실행: python3 services/hub/test_issue_badge_map_issue623.py
"""카드 배지 = 이슈맵 집계(Issue623) 단위 테스트."""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


ISSUE_MD = """# Issue Management
* Issue HWM: 5

# 🚧 진행중

## Issue5: 진행 중 하나 (등록: 2026-10-09)
* 목적: x

# 📙 일반

## Issue4: 일반 하나 (등록: 2026-10-09)
* 목적: x

# 🏁 완료-해결순

## Issue3: 접미사 없는 옛 완료 (등록: 2026-05-01)
* 목적: x

## Issue2: 접미사 있는 완료 (등록: 2026-05-01) ✅
* 목적: x

# ⏸️ 보류

## Issue1: 보류 하나 (등록: 2026-05-01)
* 목적: x
"""


def make_root(issue_md: str) -> str:
    d = tempfile.mkdtemp(prefix="issue623-")
    with open(os.path.join(d, "Issue.md"), "w", encoding="utf-8") as f:
        f.write(issue_md)
    return d


def build_map(root: str, *extra) -> bool:
    builder = server._issue_map_builder()
    if not builder:
        return False
    r = subprocess.run([sys.executable, builder, "--no-cross", *extra], cwd=root,
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0 and os.path.isfile(os.path.join(root, "Issue_map.htm"))


def fresh(cwd: str):
    """TTL 캐시를 피해 판정을 다시 계산한다."""
    server._issue_map_cache.pop(cwd, None)
    return server._issue_open_count(cwd)


print("Issue623 — 카드 배지 = 이슈맵 집계")

# 1. 생성기로 만든 맵: 미완료 = 진행중 1 + 일반 1 = 2 (🏁 완료-해결순·보류 제외)
root = make_root(ISSUE_MD)
check("생성기 실행 성공", build_map(root))
check("미완료 2 — 🏁 완료-해결순 은 완료, 보류는 제외", fresh(root) == 2)

# 2. 하위 폴더 cwd 도 같은 루트의 맵을 본다(Issue282 드리프트)
sub = os.path.join(root, "sub")
os.makedirs(sub)
check("하위 폴더 cwd 도 2", fresh(sub) == 2)

# 3. 전부 완료(fSnippet 형상) → 0. 생성기는 잔여 0건이어도 맵을 쓴다(prj3#Issue1039)
root0 = make_root(ISSUE_MD.replace("# 🚧 진행중\n", "# 🚧 진행중\n\n# 🏁 완료-해결순\n", 1)
                  .replace("# 📙 일반\n", "", 1))
check("완료만 있는 맵 생성", build_map(root0))
check("전부 완료면 0 (종전 서버 판정은 4)", fresh(root0) == 0)

# 4. 맵이 없으면 None — 서버가 Issue.md 를 따로 세지 않는다
root_nomap = make_root(ISSUE_MD)
check("맵 부재 → None", fresh(root_nomap) is None)

# 5. 구버전 맵(변형 span 없음) — 첫 집계 문구로 폴백
root_old = make_root(ISSUE_MD)
with open(os.path.join(root_old, "Issue_map.htm"), "w", encoding="utf-8") as f:
    f.write('<div class="meta">이슈 7건 · 완료 4건 · 기준 자료 <code>Issue.md</code></div>')
check("구버전 맵 폴백 → 3", fresh(root_old) == 3)

# 6. 집계 문구가 없는 맵 → None (거짓 0 금지)
root_bad = make_root(ISSUE_MD)
with open(os.path.join(root_bad, "Issue_map.htm"), "w", encoding="utf-8") as f:
    f.write("<html>무관한 문서</html>")
check("집계 문구 없는 맵 → None", fresh(root_bad) is None)

# 7. 맵 재생성(mtime 변화) 후 TTL 이 지나면 새 값 — 캐시가 낡은 값을 붙들지 않는다
with open(os.path.join(root_old, "Issue_map.htm"), "w", encoding="utf-8") as f:
    f.write('<div class="meta">이슈 7건 · 완료 7건</div>')
future = time.time() + 5
os.utime(os.path.join(root_old, "Issue_map.htm"), (future, future))
check("맵 갱신 반영 → 0", fresh(root_old) == 0)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
