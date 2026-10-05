#!/usr/bin/env python3
# test_projects_map_hidden_issue574.py — Issue574 회귀 테스트 (tdd playlist `projects-map-hidden`)
#
# 사용자가 맵을 프로젝트 단위로 간추리려고 일부 프로젝트를 **일부러** 그리지 않기로 했다(prj6#Issue19).
# 트리에서 빼면 그래프에서는 사라지지만, 완전성 보장(`enforce_completeness`)이 트리에 없는 id 를 전부
# `미할당` 으로 되살려 «목적 없음» 상자에 11건이 섞였다. «안 그리기로 함»과 «아직 목적 없음»을 가를
# 표기가 없었다 — `# Project Map` 안 `### 숨김` 절이 그 표기다.
#
# 격리: 임시 소스·임시 루트만 쓴다(실 Projects.md 무접촉). 빌더는 **실물** 두 사본을 모두 검사한다.
# 실행: python3 scripts/test_projects_map_hidden_issue574.py
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDERS = [
    os.path.join(REPO, ".claude", "skills", "projects-map", "build_projects_map.py"),
    os.path.join(REPO, ".agents", "skills", "projects-map", "build_projects_map.py"),  # Codex 포트 사본
]

TABLE = """### 📋 프로젝트

| id  | 프로젝트명 | 한국어명칭 | Dmn | 경로         | 설명 | tdd | license | 이모지 | color   |
| --- | :--------- | ---------- | :-- | :----------- | :--- | :-: | :------ | :----- | :------ |
| 0   | home       | 홈         | g   | `~`          | 홈   | ➖  | —       | 🏠     | #eeeeee |
| 1   | pm         | 피엠       | g   | `~/_git/pm`  | 관리 | ✅  | —       | 🗂     | #dddddd |
| 2   | obsidian   | 옵시디언   | g   | `~/_doc`     | 문서 | ➖  | —       | 💜     | #cccccc |
| 5   | common     | 공통       | g   | `~/_git/c`   | 공통 | ✅  | —       | 🧩     | #bbbbbb |
| 9   | paper      | 논문       | g   | `~/_git/p`   | 논문 | ➖  | —       | 🔬     | #aaaaaa |
"""

MAP = """
# Project Map

## Main Map

- 1. pm : 관리
    - 5. common : 공통

### 숨김

- 0. home
- 2. obsidian

# 다음 절
"""

# 숨김과 맵에 동시에 적힌 id(5) — 그리기가 이긴다(맵은 사람이 쓴 목적). 모순은 경고로 드러낸다
MAP_BOTH = MAP.replace("- 2. obsidian", "- 2. obsidian\n- 5. common")

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


def load(path, tag):
    spec = importlib.util.spec_from_file_location("bpm574_" + tag, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_main(path, src):
    with tempfile.TemporaryDirectory() as d:
        pj = os.path.join(d, "Projects.md"); out = os.path.join(d, "out.htm")
        open(pj, "w", encoding="utf-8").write(src)
        r = subprocess.run([sys.executable, path, "--root", d, "--projects", pj, "--out", out],
                           capture_output=True, text=True)
        htm = open(out, encoding="utf-8").read() if os.path.exists(out) else ""
        md_p = os.path.splitext(out)[0] + ".md"
        md = open(md_p, encoding="utf-8").read() if os.path.exists(md_p) else ""
    return r, htm, md


for path in BUILDERS:
    tag = ".agents" if "/.agents/" in path else ".claude"
    print(f"[{tag}]")
    b = load(path, tag.strip("."))
    split = getattr(b, "split_hidden", None)
    if not split:
        check("split_hidden 존재", False)
    else:
        maps = b.parse_maps(TABLE + MAP)
        hidden = split(maps)
        check("숨김 절의 id 를 순서대로 낸다", hidden == ["0", "2"])
        check("숨김은 맵이 아니다(맵 목록에서 빠진다)", "숨김" not in maps)
        table = b.parse_table(TABLE + MAP)
        missing = b.enforce_completeness(maps, table, hidden)
        check("숨긴 id 는 미할당이 아니다 — 미할당 = 9 하나", missing == ["9"])
        mmd = "\n".join(src for _, src in b.render_boxes(maps, table))   # Issue583: 박스별 다이어그램 전부
        check("그래프에 숨긴 노드가 없다(P0·P2)", not re.search(r"\bP0\[", mmd) and not re.search(r"\bP2\[", mmd))
    r, htm, md = run_main(path, TABLE + MAP)
    check("생성 rc 0", r.returncode == 0)
    check("요약 줄: 미할당 1건 · 숨김 2건", "미할당 편입 1건" in r.stdout and "숨김 2건" in r.stdout)
    check("htm: 다이어그램 아래 접힘 목록 «숨김 2건»(링크 유지)",
          'id="hidden"' in htm and "숨김 2건" in htm and "/open-prj?id=0" in htm)
    check("htm: 미할당 상자에 숨긴 id 가 없다", "#0<" not in htm.split('id="misc"', 1)[-1].split("</div>", 1)[0])
    check("md: «# 숨김 2건» 절", "# 숨김 2건" in md)
    r2, htm2, _ = run_main(path, TABLE + MAP_BOTH)
    check("숨김과 맵에 동시에 적힌 id 는 그리고 경고한다", "P5[" in htm2 and "숨김" in (r2.stderr + r2.stdout) and "5" in r2.stderr)

same = open(BUILDERS[0], "rb").read() == open(BUILDERS[1], "rb").read()
check("두 사본(.claude·.agents) 동일", same)
print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
