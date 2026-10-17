#!/usr/bin/env python3
# test_map_place_issue626.py — Issue626 회귀 테스트 (tdd playlist `map-place-single`)
#
# pm-new 가 `# Project Map` 트리에 노드를 넣는 단계가 절차에 없었다. 9t fTyping 은 생성 때 «프로모션»
# 그룹 아래 놓였다가 사용자가 «25 fSnippetCli 아래» 로 옮겼다 — 트리 위치(기반 prj)와 `goal_parent`
# (목적 축 그룹)가 같은 값으로 읽힌 탓이다. 집행자 `sh/fpm-map-place.py` 가 노드를 **한 곳에만** 넣는다.
#
#   ① --under <id>    → 그 프로젝트 항목의 하위 끝에 들여쓰기 +2 로 1줄
#   ② --under <그룹>  → `### <그룹>` 서브맵 끝(들여쓰기 0) · 맵 안 그룹 노드(`- App 개발`)면 그 하위 끝
#   ③ 이미 맵에 있는 id → 거부 rc 2 (사본 금지 — 단일 배치)
#   ④ 없는 부모 → rc 1 · 같은 id 가 두 곳(다중 부모)이라 부모가 모호 → rc 1
#   ⑤ --dry-run → 파일 무변경 · `# Project Map` 밖(표·Reference)은 바이트 동일
#
# 격리: 임시 Projects.md 만 쓴다(실 Projects.md 무접촉).
# 실행: python3 scripts/test_map_place_issue626.py
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "sh", "fpm-map-place.py")

HEAD = """# Info

| id | 프로젝트명 |
| -- | :--------- |
| 25 | fSnippetCli |

"""

MAP = """# Project Map

* 설명 줄

## Main Map

- Goal: 목표 목록
  - "프로모션"
  - "fApp"

## Sub Map

### fApp

- App 개발
  - 15. 🚀 fSnippet
    - 25. 🚀⌨️ fSnippetCli
      - 9. 🚀💾 <private-project-2>
  - 16. ⚓ fWarrange
- 보조 도구
  - 51. 📸 fCapture

### 프로모션

- 10. 😸🏠 finfraHome
- 40. 🎬▶️ videoStudio
  - 42. 🎬📑 m2slide

### 강의_과목
- 60. 🎓📚 lec
- 42. 🎬📑 m2slide

### 숨김

- 0. 😸 nowage

> 숨김 설명
"""

TAIL = """
# Reference

- 끝
"""

fails = []


def check(ok, msg):
    print(("  ok  " if ok else "  FAIL ") + msg)
    if not ok:
        fails.append(msg)


def run(args, src=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "Projects.md")
    with open(p, "w") as f:
        f.write(src if src is not None else HEAD + MAP + TAIL)
    r = subprocess.run([sys.executable, TOOL, "--file", p, *args], capture_output=True, text=True)
    with open(p) as f:
        return r, f.read()


def lines(text):
    return text.split("\n")


if not os.path.exists(TOOL):
    print("  FAIL 집행자 없음: sh/fpm-map-place.py")
    sys.exit(1)

# ① 프로젝트 항목 아래 — 하위 끝(9 다음), 들여쓰기 +2
r, out = run(["--id", "9t", "--text", "🎮⌨️ fTyping : fSnippet 홍보 게임", "--under", "25"])
check(r.returncode == 0, f"① --under 25 rc=0 (rc={r.returncode} {r.stderr.strip()})")
L = lines(out)
want = "      - 9t. 🎮⌨️ fTyping : fSnippet 홍보 게임"
check(want in L, "① 25 의 자식 들여쓰기(6칸)로 1줄")
if want in L:
    i = L.index(want)
    check(L[i - 1].strip().startswith("- 9."), "① 기존 하위(9) 뒤 — 하위 끝에 붙는다")
    check(L[i + 1].strip().startswith("- 16."), "① 다음 형제(16) 앞")
check(out.count("9t.") == 1, "① 한 곳에만 (프로모션 사본 없음)")

# ② 서브맵 그룹 — `### 프로모션` 끝, 들여쓰기 0, 하위(42) 뒤
r, out = run(["--id", "9t", "--text", "🎮⌨️ fTyping", "--under", "프로모션"])
check(r.returncode == 0, f"② --under 프로모션 rc=0 (rc={r.returncode} {r.stderr.strip()})")
L = lines(out)
want = "- 9t. 🎮⌨️ fTyping"
check(want in L, "② 서브맵 최상위(들여쓰기 0)로 1줄")
if want in L:
    i = L.index(want)
    check(L[i - 1].strip().startswith("- 42."), "② 그 서브맵 마지막 항목 뒤")
    check(L[i + 1] == "" and L[i + 2].startswith("### 강의_과목"), "② 다음 서브맵 헤더 앞 빈 줄 유지")

# ② 맵 안 그룹 노드 — `- 보조 도구` 하위 끝
r, out = run(["--id", "52", "--text", "🧰 fTool", "--under", "보조 도구"])
check(r.returncode == 0, f"② --under '보조 도구' rc=0 (rc={r.returncode} {r.stderr.strip()})")
L = lines(out)
want = "  - 52. 🧰 fTool"
check(want in L and L[L.index(want) - 1].strip().startswith("- 51."), "② 그룹 노드 하위 끝 · 들여쓰기 2")

# ③ 이미 맵에 있는 id → 거부, 무변경
src = HEAD + MAP + TAIL
r, out = run(["--id", "51", "--text", "📸 fCapture", "--under", "프로모션"])
check(r.returncode == 2, f"③ 이미 있는 id 51 → rc=2 (rc={r.returncode})")
check(out == src, "③ 거부 시 파일 무변경")
r, out = run(["--id", "0", "--text", "😸 nowage", "--under", "fApp"])
check(r.returncode == 2, f"③ 숨김에 있는 id 0 → rc=2 (rc={r.returncode})")

# ④ 없는 부모 · 모호한 부모
r, out = run(["--id", "9t", "--text", "x", "--under", "없는그룹"])
check(r.returncode == 1 and out == src, f"④ 없는 부모 → rc=1·무변경 (rc={r.returncode})")
r, out = run(["--id", "42b", "--text", "x", "--under", "42"])
check(r.returncode == 1 and out == src, f"④ 두 곳에 있는 42 → 모호 rc=1·무변경 (rc={r.returncode})")
check("모호" in r.stderr, "④ 모호 사유를 stderr 로 알린다")

# ⑤ dry-run 무변경 + 맵 밖 바이트 동일
r, out = run(["--id", "9t", "--text", "x", "--under", "25", "--dry-run"])
check(r.returncode == 0 and out == src, f"⑤ --dry-run rc=0·무변경 (rc={r.returncode})")
check("9t." in r.stdout, "⑤ --dry-run 이 넣을 줄을 보여준다")
r, out = run(["--id", "9t", "--text", "x", "--under", "25"])
check(out.startswith(HEAD) and out.endswith(TAIL), "⑤ `# Project Map` 밖은 바이트 동일")

print(f"\n{'FAIL' if fails else 'PASS'} — {len(fails)} 실패")
sys.exit(1 if fails else 0)
