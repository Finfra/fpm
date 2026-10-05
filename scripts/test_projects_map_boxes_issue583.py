#!/usr/bin/env python3
# test_projects_map_boxes_issue583.py — Issue583 회귀 테스트 (tdd playlist `projects-map-box-order`)
#
# 사용자 지시 «프로모션을 가장 위에, 다음이 App 개발, 그 아래 강의_과목»(2026-09-28). 한 장 flowchart 에서는
# 박스 세로 순서를 지정할 수 없다 — dagre 가 교차 최소화로 정하고 데이터 편집마다 다시 섞인다(prj6#Issue19 후속
# 실측: 서브맵 순서 120 가지 × 참조 순서 2 가지 전부 0건). 그래서 **박스마다 다이어그램 1장**을 그려 쌓는다.
# 계약: ① 박스 순서 = Main Map 참조(`"맵"`) 등장 순서 → 참조 안 된 서브맵은 파일 순서로 뒤에
#       ② Main Map 은 맨 위 머리 다이어그램 1장(서브맵 노드는 싣지 않는다) ③ 다이어그램마다 간격 init + flowchart LR,
#          subgraph 없음 ④ 두 박스에 나오는 노드는 두 곳 모두 그린다(세션 배지·hover 가 둘 다 붙게)
#       ⑤ 참조는 «→ 맵» 표식 노드 ⑥ htm·md 모두 같은 순서 ⑦ 숨김·미할당·텍스트 트리 불변 ⑧ 두 사본 동일
#
# 격리: 임시 소스·임시 루트만 쓴다(실 Projects.md 무접촉). 빌더는 **실물** 두 사본을 모두 검사한다.
# 실행: python3 scripts/test_projects_map_boxes_issue583.py
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

SRC = """### 📋 프로젝트

| id  | 프로젝트명 | 한국어명칭 | Dmn | 경로        | 설명 | tdd | license | 이모지 | color   |
| --- | :--------- | ---------- | :-- | :---------- | :--- | :-: | :------ | :----- | :------ |
| 0   | home       | 홈         | g   | `~`         | 홈   | ➖  | —       | 🏠     | #eeeeee |
| 5   | common     | 공통       | g   | `~/_git/c`  | 공통 | ✅  | —       | 🧩     | #bbbbbb |
| 6   | architect  | 설계       | g   | `~/_git/a`  | 판정 | ➖  | —       | 📐     | #cccccc |
| 7   | alpha      | 가         | g   | `~/_git/g`  | 가   | ➖  | —       | 🅰     | #aaaaaa |
| 8   | beta       | 나         | g   | `~/_git/n`  | 나   | ➖  | —       | 🅱     | #999999 |
| 9   | gamma      | 다         | g   | `~/_git/d`  | 다   | ➖  | —       | 🆎     | #888888 |
| 42  | slide      | 슬라이드   | g   | `~/_git/s`  | 공유 | ➖  | —       | 🎞     | #777777 |
| 99  | orphan     | 미할당     | g   | `~/_git/o`  | 없음 | ➖  | —       | ❔     | #666666 |

# Project Map

## Main Map

- Goal: 목표 목록
  - "가맵"
  - "나맵"
  - "다맵"
  - @6. 📐 architect : 판정

## Sub Map

### 다맵

- 9. gamma : 다

### Infra

- 6. architect
  - 5. common

### 가맵

- 7. alpha : 가
  - 42. slide : 공유
  - "Infra"

### 나맵

- 42. slide : 공유
  - 8. beta : 나

### 숨김

- 0. home

# 다음 절
"""

ORDER = ["Main Map", "가맵", "나맵", "다맵", "Infra"]
INIT = '%%{init: {"flowchart": {"nodeSpacing": 22, "rankSpacing": 38, "padding": 6}}}%%'

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}" + (f"\n       {str(detail)[:300]}" if detail else ""))


def load(path, tag):
    spec = importlib.util.spec_from_file_location("bpm583_" + tag, path)
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


def defines(src, nid):
    return re.search(rf"^\s*{nid}\[", src, re.M) is not None


for path in BUILDERS:
    tag = ".agents" if "/.agents/" in path else ".claude"
    print(f"[{tag}]")
    b = load(path, tag.strip("."))
    rb = getattr(b, "render_boxes", None)
    if not rb:
        check("render_boxes 존재", False)
    else:
        maps = b.parse_maps(SRC); hidden = b.split_hidden(maps); b.resolve_refs(maps)
        table = b.parse_table(SRC); missing = b.enforce_completeness(maps, table, hidden)
        boxes = rb(maps, table)
        names = [n for n, _ in boxes]
        check("박스 순서 = Main Map 머리 → 참조 순서(가·나·다) → 참조 안 된 Infra", names == ORDER, names)
        src = dict(boxes)
        check("다이어그램마다 첫 줄 간격 init · 둘째 줄 flowchart LR",
              all(s.splitlines()[:2] == [INIT, "flowchart LR"] for s in src.values()))
        check("subgraph 를 쓰지 않는다(박스 = 다이어그램 1장)", not any("subgraph" in s for s in src.values()))
        head = src.get("Main Map", "")
        check("머리에 Goal·판정 주체(P6) — 서브맵 노드(P7·P9)는 싣지 않는다",
              re.search(r"^\s*G\S+\[\"Goal", head, re.M) is not None and defines(head, "P6")
              and not defines(head, "P7") and not defines(head, "P9"), head)
        check("두 박스에 나오는 노드(P42)는 가맵·나맵 모두에 정의", defines(src.get("가맵", ""), "P42")
              and defines(src.get("나맵", ""), "P42"))
        check("박스 안 간선 유지(가맵 P7 → P42 · Infra P6 → P5)",
              re.search(r"^\s*P7 --> P42$", src.get("가맵", ""), re.M) is not None
              and re.search(r"^\s*P6 --> P5$", src.get("Infra", ""), re.M) is not None)
        ga = src.get("가맵", "")
        stub = re.search(r"^\s*(R\S+)\[\"→ Infra\"\]", ga, re.M)
        check("서브맵 안 참조 → «→ Infra» 표식 노드 + 점선 간선", stub is not None
              and re.search(rf"^\s*P7 -\.-> {stub.group(1) if stub else 'X'}$", ga, re.M) is not None, ga)
        check("숨김(P0)·미할당(P99)은 어느 박스에도 없다 · 미할당 = 99",
              not any(defines(s, "P0") or defines(s, "P99") for s in src.values()) and missing == ["99"])

    r, htm, md = run_main(path, SRC)
    check("생성 rc 0", r.returncode == 0, r.stderr)
    pres = htm.count('<pre class="mermaid">')
    check(f"htm: 다이어그램 {len(ORDER)}장 ({pres})", pres == len(ORDER))
    pos = [htm.find(f'data-map="{n}"') for n in ORDER]
    check("htm: 박스 등장 순서 = 참조 순서", all(p >= 0 for p in pos) and pos == sorted(pos), pos)
    check("htm: 박스 제목 = 서브맵 이름(map-box-title)",
          all(re.search(rf'<h3 class="map-box-title"[^>]*>{n}</h3>', htm) for n in ORDER[1:]))
    check("htm: 미할당·숨김·텍스트 트리 유지", 'id="misc"' in htm and 'id="hidden"' in htm
          and "PROJECTS-MAP:TREE" in htm)
    mds = [m.start() for m in re.finditer(r"^```mermaid$", md, re.M)]
    hpos = [md.find(f"\n## {n}\n") for n in ORDER[1:]]
    check(f"md: mermaid 블록 {len(ORDER)}개 · 서브맵 절 순서 동일", len(mds) == len(ORDER)
          and all(p >= 0 for p in hpos) and hpos == sorted(hpos), (len(mds), hpos))

same = open(BUILDERS[0], "rb").read() == open(BUILDERS[1], "rb").read()
check("두 사본(.claude·.agents) 동일", same)
print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
