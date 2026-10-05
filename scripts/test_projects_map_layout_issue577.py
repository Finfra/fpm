#!/usr/bin/env python3
# test_projects_map_layout_issue577.py — Issue577 회귀 테스트 (tdd playlist `projects-map-compact`)
#
# 원본이 화면보다 훨씬 커서 폭 맞춤으로 축소되고 글자가 작아졌다(사용자 지적 «잘 보이게, 공간 낭비 없게»).
# 가장 큰 낭비는 Main Map 이 subgraph 라 Goal 의 자식이 각 서브맵 옆에 붙으며 박스가 전체 높이로 늘어난 것.
# 계약: ① 머리에 flowchart 간격 init 지시문 ② Main Map 노드는 subgraph 없이 정의(나머지 맵은 박스 유지)
#       — Issue583 이후: ①은 다이어그램마다, ②는 Main Map = 맨 위 머리 다이어그램 · 서브맵 = 자기 박스 1장
#       ③ 노드 id `P{id}`(세션 배지·hover JS) 불변 ④ 숨김(Issue574)·미할당 불변 ⑤ 두 사본 동일
#
# 격리: 임시 문자열 소스만(실 Projects.md 무접촉). 빌더는 **실물** 두 사본을 모두 검사한다.
# 실행: python3 scripts/test_projects_map_layout_issue577.py
import importlib.util
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDERS = [
    os.path.join(REPO, ".claude", "skills", "projects-map", "build_projects_map.py"),
    os.path.join(REPO, ".agents", "skills", "projects-map", "build_projects_map.py"),
]

SRC = """### 📋 프로젝트

| id  | 프로젝트명 | 한국어명칭 | Dmn | 경로        | 설명 | tdd | license | 이모지 | color   |
| --- | :--------- | ---------- | :-- | :---------- | :--- | :-: | :------ | :----- | :------ |
| 0   | home       | 홈         | g   | `~`         | 홈   | ➖  | —       | 🏠     | #eeeeee |
| 1   | pm         | 피엠       | g   | `~/_git/pm` | 관리 | ✅  | —       | 🗂     | #dddddd |
| 5   | common     | 공통       | g   | `~/_git/c`  | 공통 | ✅  | —       | 🧩     | #bbbbbb |
| 9   | paper      | 논문       | g   | `~/_git/p`  | 논문 | ➖  | —       | 🔬     | #aaaaaa |

# Project Map

## Main Map

- 목표 : 잘 굴러간다
    - 1. pm : 관리
    - "Infra"

## Sub Map

### Infra

- 5. common : 공통

### 숨김

- 0. home

# 다음 절
"""

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


for path in BUILDERS:
    tag = ".agents" if "/.agents/" in path else ".claude"
    print(f"[{tag}]")
    spec = importlib.util.spec_from_file_location("bpm577_" + tag.strip("."), path)
    b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
    maps = b.parse_maps(SRC); hidden = b.split_hidden(maps); b.resolve_refs(maps)
    table = b.parse_table(SRC); missing = b.enforce_completeness(maps, table, hidden)
    # Issue583 이후 박스 = 다이어그램 1장 — 간격 init·LR 은 **다이어그램마다**, Main Map 은 맨 위 머리(박스 아님)
    boxes = b.render_boxes(maps, table)
    srcs = dict(boxes)
    mmd = "\n".join(srcs.values())
    lines = boxes[0][1].splitlines() if boxes else []
    init = re.match(r'^%%\{init: (\{.*\})\}%%$', lines[0]) if lines else None
    cfg = __import__("json").loads(init.group(1)).get("flowchart", {}) if init else {}
    check("첫 줄 = flowchart 간격 init 지시문(nodeSpacing 22 · rankSpacing 38 · padding 6)",
          cfg == {"nodeSpacing": 22, "rankSpacing": 38, "padding": 6})
    check("둘째 줄 = flowchart LR", len(lines) > 1 and lines[1] == "flowchart LR")
    check("Main Map 은 박스가 아니라 맨 위 머리다(subgraph 없음)",
          boxes and boxes[0][0] == "Main Map" and "subgraph" not in mmd)
    check("서브맵(Infra)은 자기 박스", "Infra" in srcs)
    check("Main Map 노드는 여전히 정의된다(P1)", re.search(r"^\s*P1\[", srcs.get("Main Map", ""), re.M) is not None)
    check("노드 id P{id} 불변(P5)", re.search(r"^\s*P5\[", srcs.get("Infra", ""), re.M) is not None)
    check("숨김·미할당 불변 — P0 없음 · 미할당 = 9", not re.search(r"\bP0\[", mmd) and missing == ["9"])

check("두 사본(.claude·.agents) 동일", open(BUILDERS[0], "rb").read() == open(BUILDERS[1], "rb").read())
print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
