#!/usr/bin/env python3
# test_projects_map_columns_issue550.py — Issue550 회귀 테스트 (tdd playlist #26 projects-map-columns-by-header)
#
# projects-map 빌더 parse_table() 이 Projects.md 본표를 **헤더 명칭**으로 읽는지 검증한다.
# 종전 TABLE_ROW_RE 는 8컬럼 고정 정규식이라 tdd 컬럼이 끼자 **0행**을 반환했고,
# license 컬럼(Issue550)이 더 끼어도 마찬가지다 — 관계도 노드 이모지·색이 전부 빠진다.
#
# 격리: 임시 문자열 표만 쓴다(실 Projects.md 무접촉). 빌더는 **실물 모듈**을 import 한다.
# 실행: python3 scripts/test_projects_map_columns_issue550.py
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDERS = [
    os.path.join(REPO, ".claude", "skills", "projects-map", "build_projects_map.py"),
    os.path.join(REPO, ".agents", "skills", "projects-map", "build_projects_map.py"),  # Codex 포트 사본
]

CURRENT = """### 📋 프로젝트

| id  | 프로젝트명 | 한국어명칭 | Dmn | 경로            | 설명 | tdd | license | 이모지 | color   |
| --- | :--------- | ---------- | :-- | :-------------- | :--- | :-: | :------ | :----- | :------ |
| 2   | obsidian   | 옵시디언   | g   | `~/_doc`        | 문서 | 🆕  | —       | 💜     | #cfedd9 |
| 8   | fpm        | 에프피엠   | g   | `~/_git/fpm`    | 미러 | ➖  | A①      | 🔌     | #eeeedd |
| 9a  | paper      | 논문       | g   | `~/_git/paper`  | 하위 | ➖  | —       | 🔬     | #92dab6 |

> 범례
"""

LEGACY = """### 📋 프로젝트

| id | 프로젝트명 | 한국어명칭 | Dmn | 경로       | 설명 | 이모지 | color   |
| -- | :--------- | ---------- | :-- | :--------- | :--- | :----- | :------ |
| 1  | legacy     | 레거시     | g   | `~/legacy` | 옛표 | 🎮     | #aabbcc |
"""

PASS = FAIL = 0


def check(label, cond, got=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label} (got={got!r})")


def load(path):
    spec = importlib.util.spec_from_file_location("bpm_" + str(abs(hash(path))), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


for b in BUILDERS:
    tag = "claude" if "/.claude/" in b else "agents"
    if not os.path.isfile(b):
        check(f"[{tag}] 빌더 존재", False, b)
        continue
    m = load(b)
    t = m.parse_table(CURRENT)
    check(f"[{tag}] A1 현행 표(tdd·license)도 3행을 읽는다", len(t) == 3, len(t))
    r8 = t.get("8", {})
    check(f"[{tag}] A2 이모지는 이모지 컬럼(🔌)", r8.get("emoji") == "🔌", r8.get("emoji"))
    check(f"[{tag}] A3 색은 color 컬럼", r8.get("color") == "#eeeedd", r8.get("color"))
    check(f"[{tag}] A4 경로는 경로 컬럼(백틱 제거)", r8.get("path") == "~/_git/fpm", r8.get("path"))
    check(f"[{tag}] A5 이름은 프로젝트명 컬럼", r8.get("name") == "fpm", r8.get("name"))
    check(f"[{tag}] A6 접미 id(9a) 행도 읽는다", t.get("9a", {}).get("emoji") == "🔬", t.get("9a"))
    check(f"[{tag}] A7 license 값(A①)이 이모지에 섞이지 않는다",
          all(v.get("emoji") not in ("A①", "—", "🆕", "➖") for v in t.values()),
          {k: v.get("emoji") for k, v in t.items()})
    lg = m.parse_table(LEGACY)
    check(f"[{tag}] B1 구 8컬럼 표도 읽는다", lg.get("1", {}).get("emoji") == "🎮", lg.get("1"))

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
