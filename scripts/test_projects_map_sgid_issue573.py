#!/usr/bin/env python3
# test_projects_map_sgid_issue573.py — Issue573 회귀 테스트 (tdd playlist `projects-map-korean-id`)
#
# projects-map 빌더 `mmd_id()` 는 `[^A-Za-z0-9_]` 를 전부 `_` 로 바꿔 mermaid id 를 만든다.
# 한글 맵 이름은 글자 수만 남아 **같은 길이면 같은 id** 가 된다 — `생애 판정`·`강의_과목` 이 모두
# `SG_____` 가 되어 mermaid 가 두 subgraph 를 한 박스로 합쳤다(2026-09-28 prj6#Issue18 발견).
# 생성 로그 경고 0건인 **조용한 병합**이라 생성기 검사로는 안 잡혔다.
#
# 격리: 임시 문자열 소스만 쓴다(실 Projects.md 무접촉). 빌더는 **실물 모듈** 두 사본을 모두 import 한다.
# 실행: python3 scripts/test_projects_map_sgid_issue573.py
import importlib.util
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDERS = [
    os.path.join(REPO, ".claude", "skills", "projects-map", "build_projects_map.py"),
    os.path.join(REPO, ".agents", "skills", "projects-map", "build_projects_map.py"),  # Codex 포트 사본
]

# 같은 길이 한글 맵 2개(각각 그룹 노드 포함) + ASCII 맵
SRC = """### 📋 프로젝트

| id  | 프로젝트명 | 한국어명칭 | Dmn | 경로         | 설명 | tdd | license | 이모지 | color   |
| --- | :--------- | ---------- | :-- | :----------- | :--- | :-: | :------ | :----- | :------ |
| 1   | pm         | 피엠       | g   | `~/_git/pm`  | 관리 | ✅  | —       | 🗂     | #eeeeee |
| 6   | architect  | 설계       | g   | `~/_git/a`   | 설계 | ✅  | —       | 🏛     | #dddddd |
| 60  | lec        | 강의       | g   | `~/_git/lec` | 강의 | ✅  | —       | 📚     | #cccccc |

# Project Map

## Main Map

- 1. pm : 관리
    - "생애 판정"
    - "강의_과목"

### 생애 판정

- 판정 묶음
    - 6. architect : 판정 주체

### 강의_과목

- 강의 묶음
    - 60. lec : 강의

# 다음 절
"""

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


def load(path, tag):
    spec = importlib.util.spec_from_file_location("bpm_" + tag, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


for path in BUILDERS:
    tag = ".agents" if "/.agents/" in path else ".claude"
    print(f"[{tag}]")
    b = load(path, tag.strip("."))
    check("같은 길이 한글 맵 이름 → 서로 다른 subgraph id", b.mmd_id("SG", "생애 판정") != b.mmd_id("SG", "강의_과목"))
    check("같은 키는 같은 id(결정적)", b.mmd_id("SG", "생애 판정") == b.mmd_id("SG", "생애 판정"))
    check("ASCII 키는 그대로 — P9a·SGfApp·SGInfra (JS `flowchart-P{id}-` 규약 불변)",
          (b.mmd_id("P", "9a"), b.mmd_id("SG", "fApp"), b.mmd_id("SG", "Infra")) == ("P9a", "SGfApp", "SGInfra"))
    check("id 는 mermaid 안전 문자만", all(re.fullmatch(r"[A-Za-z0-9_]+", b.mmd_id("SG", k)) for k in ("생애 판정", "a-b", "Main Map")))
    maps = b.parse_maps(SRC)
    b.resolve_refs(maps)
    table = b.parse_table(SRC)
    b.enforce_completeness(maps, table)
    # Issue583 이후 박스 = 다이어그램 1장(subgraph 없음) — 같은 길이 한글 맵 2개가 **각자 박스**로 나오고
    #   그룹 노드가 둘 다 살아 있어야 한다(합쳐지거나 둘째가 삼켜지는 것이 이 테스트가 막는 결함)
    boxes = dict(b.render_boxes(maps, table))
    check(f"같은 길이 한글 맵 → 박스 2장 따로 ({list(boxes)})", "생애 판정" in boxes and "강의_과목" in boxes)
    groups = [g for n in ("생애 판정", "강의_과목") for g in re.findall(r"^\s*(G\S+)\[", boxes.get(n, ""), re.M)]
    check(f"같은 길이 맵의 그룹 노드 id 도 서로 다름 ({groups})", len(groups) == 2 and len(set(groups)) == 2)

same = open(BUILDERS[0], "rb").read() == open(BUILDERS[1], "rb").read()
check("두 사본(.claude·.agents) 동일", same)
print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
