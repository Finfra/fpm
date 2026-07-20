#!/usr/bin/env python3
"""Projects.md → Projects_map.htm 생성기.

설계 SSOT: _doc_arch/projects-map-design.md
표(### 📋 프로젝트) = 속성(id·경로·이모지·색) SSOT.
트리(# Project Map) = 계층(소속) SSOT.

Issue294: 표현을 mermaid flowchart 로 전환. mmdc 프리렌더는 쓰지 않는다 —
정적 SVG 는 `click ... href` 를 앵커로 만들지 않아(실측: `class="clickable"` 만 부여)
링크가 죽는다. hub 가 주입하는 canonical UMD 런타임으로 브라우저에서 렌더해야 `<a>` 가 생긴다.
그 런타임은 `securityLevel: strict` 이라 `vscode://` 같은 커스텀 스킴은 sanitize 되므로,
노드 링크는 상대경로 http 브리지(`/open-prj?id=N`)를 쓴다(`/ob` 브리지와 같은 해법).
mermaid 런타임 <script> 는 여기서 저작하지 않는다 — hub `_normalize_mermaid_runtime` 이 주입한다.

외부 의존 없음(표준 라이브러리만).
"""

import argparse
import html
import os
import re
import sys
import urllib.parse
from pathlib import Path

MISC_LABEL = "미할당"

# Issue294: 계층 소스 섹션 헤딩. 현행은 `# Project Map` 이며, 완전 일치 하드코딩이
#   헤딩 rename 한 번에 생성 실패로 이어졌으므로(회귀) 구 표기도 함께 받아 준다.
TREE_HEADINGS = {"# Project Map", "# Project Tree", "# 프로젝트 트리"}

TABLE_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$"
)
TREE_NODE_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<rest>.+?)\s*$")
ID_NODE_RE = re.compile(r"^(?P<id>\d+)\.\s+(?P<emoji>\S+)\s+(?P<name>.+)$")


def find_root(explicit):
    if explicit:
        return Path(explicit).resolve()
    # .claude/skills/projects-map/build_projects_map.py -> root = parents[3]
    return Path(__file__).resolve().parents[3]


def read_toggle(root):
    setting_path = root / "data" / "projects_map_setting.yml"
    if not setting_path.exists():
        return True
    for line in setting_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*enabled\s*:\s*(true|false)\s*(#.*)?$", line, re.IGNORECASE)
        if m:
            return m.group(1).lower() == "true"
    return True


def parse_table(md_text):
    """id -> {name, path, emoji, color}"""
    table = {}
    in_table = False
    for line in md_text.splitlines():
        if line.strip().startswith("### 📋 프로젝트"):
            in_table = True
            continue
        if in_table:
            if line.strip().startswith("# ") or (
                line.strip() and not line.strip().startswith("|") and not line.strip().startswith(">")
            ):
                # left the table section (next heading or prose)
                if not line.strip().startswith("|"):
                    in_table = False
                    continue
            m = TABLE_ROW_RE.match(line)
            if m:
                pid = m.group(1).strip()
                name = m.group(2).strip()
                path = m.group(5).strip().strip("`")
                emoji = m.group(7).strip()
                color = m.group(8).strip()
                table[pid] = {"name": name, "path": path, "emoji": emoji, "color": color}
    return table


# Issue298: 노드 표기 — 확정 규약(설계 "표기 규칙 4개")
#   프로젝트  `- {id}. {emoji} {name} : {목적}`
#   담당 주체  `- @{id}. {name} : {목적}`  또는 구 표기 `- {id}.{name}@{맵} : {목적}`
#   참조      `- "{맵이름}"`
#   그룹      `- {label} : {목적}`
ID_NODE_LOOSE_RE = re.compile(r"^(?P<at>@)?(?P<id>\d+)\.\s*(?P<rest>.+)$")
REF_NODE_RE = re.compile(r'^"(?P<ref>[^"]+)"$')
MAP_HEAD_RE = re.compile(r"^(?P<level>#{2,3})\s+(?P<name>.+?)\s*$")
SUBMAP_CONTAINER = {"Sub Map", "Main Map"}


def split_node(rest):
    """노드 원문 → (kind, id, label, purpose, actor).

    kind: "project" | "ref" | "group"
    `:` 뒤는 **목적**이며 라벨에서 분리한다(설계 "`:` 의 정의").
    """
    rest = rest.strip()
    m = REF_NODE_RE.match(rest)
    if m:
        return "ref", None, m.group("ref").strip(), None, False
    purpose = None
    if ":" in rest:
        head, tail = rest.split(":", 1)
        # `Goal: 수익실현` 처럼 id 없는 노드도 동일 규칙 적용
        rest, purpose = head.strip(), tail.strip() or None
    m = ID_NODE_LOOSE_RE.match(rest)
    if not m:
        return "group", None, rest, purpose, False
    body = m.group("rest").strip()
    actor = bool(m.group("at"))
    # 구 표기 `common@프로모션` — `@` 뒤 맵 이름은 섹션이 이미 알려주므로 버린다.
    if "@" in body:
        body, _ = body.split("@", 1)
        actor = True
    return "project", m.group("id"), body.strip(), purpose, actor


def parse_maps(md_text):
    """`# Project Map` 구간을 맵 단위로 파싱 → {맵이름: [루트노드…]}.

    Issue298: 코드펜스 의존 제거. 소스는 펜스 없는 진짜 markdown 리스트이며
    `## Main Map` · `### {맵이름}` 헤딩이 구간을 나눈다. 펜스가 남아 있어도
    무시하고 읽어 구 소스와 호환된다. 헤딩의 따옴표(`### "프로모션"`)도 벗겨
    참조(`- "프로모션"`)와 같은 이름으로 맞춘다.
    """
    lines = md_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() in TREE_HEADINGS:
            start = i
            break
    if start is None:
        return {}
    maps, cur, roots, stack = {}, None, None, []
    for raw in lines[start + 1:]:
        st = raw.strip()
        if st.startswith("# "):          # 다음 H1 = 구간 종료
            break
        if st.startswith("```"):          # 펜스는 무시(구 소스 호환)
            continue
        hm = MAP_HEAD_RE.match(raw)
        if hm:
            name = hm.group("name").strip().strip('"').strip()
            if name in SUBMAP_CONTAINER and hm.group("level") == "##" and name == "Sub Map":
                cur = None               # 컨테이너 헤딩 — 그 자체는 맵이 아님
                continue
            cur, stack = name, []
            roots = maps.setdefault(name, [])
            continue
        if cur is None:
            continue
        m = TREE_NODE_RE.match(raw)
        if not m:
            continue
        depth = len(m.group("indent")) // 2
        kind, pid, label, purpose, actor = split_node(m.group("rest"))
        node = {"id": pid, "label": label, "kind": kind, "purpose": purpose,
                "actor": actor, "children": []}
        while stack and stack[-1][0] >= depth:
            stack.pop()
        (stack[-1][1]["children"] if stack else roots).append(node)
        stack.append((depth, node))
    return maps


def resolve_refs(maps):
    """Issue298 P3: 참조로 파싱된 노드 중 **참조가 될 수 없는 것**을 그룹으로 되돌린다.

    참조(`- "이름"`)는 다른 맵으로 이어지는 잎이어야 한다. 다음 둘은 참조일 수 없다:

    * **자식이 있는 노드** — 참조는 대상 맵이 내용을 갖고 있으므로 자식을 달 이유가 없다
    * **대상 맵이 없는 이름** — 오타이거나, 그룹 레이블에 따옴표를 붙인 경우

    되돌리지 않으면 렌더가 그 노드를 만들지 않아 **자식들이 부모를 잃고 조용히 흩어진다**.
    사람이 따옴표를 그룹 표시로 쓴 실수를 조용한 소실이 아니라 경고로 드러낸다.
    """
    names = set(maps.keys())
    fixed = []

    def walk(nodes):
        for n in nodes:
            if n.get("kind") == "ref":
                why = None
                if n["children"]:
                    why = "자식이 있음"
                elif n["label"] not in names:
                    why = "그 이름의 맵이 없음"
                if why:
                    n["kind"] = "group"
                    fixed.append((n["label"], why))
            walk(n["children"])

    for roots in maps.values():
        walk(roots)
    return fixed


def parse_tree(md_text):
    """구 인터페이스 호환 — 전 맵의 루트를 한 리스트로 이어 반환."""
    out = []
    for roots in parse_maps(md_text).values():
        out.extend(roots)
    return out


def collect_tree_ids(nodes):
    ids = set()
    for n in nodes:
        if n["id"]:
            ids.add(n["id"])
        ids |= collect_tree_ids(n["children"])
    return ids


def enforce_completeness(maps, table):
    """Issue298: 미할당 판정을 **전 맵 id 합집합** 기준으로. 맵이 여러 개인데 한 맵만
    보면 다른 맵에 있는 프로젝트가 미할당로 잘못 잡힌다. 합성 노드는 별도 `미할당` 맵에
    담아, 사람이 쓴 맵을 오염시키지 않는다."""
    tree_ids = set()
    for roots in maps.values():
        tree_ids |= collect_tree_ids(roots)
    missing = sorted((set(table.keys()) - tree_ids), key=int)
    if missing:
        maps[MISC_LABEL] = [
            {"id": pid, "label": table[pid]["name"], "kind": "project",
             "purpose": None, "actor": False, "children": []}
            for pid in missing
        ]
    return missing


# ── 데드 루프 감지 ───────────────────────────────────────────────────────
def detect_dead_loops(nodes, ancestors=None, path=None, found=None, seen=None):
    """목적 맵의 구조 결함 2종을 검출한다. 설계: _doc_arch/projects-map-design.md "데드 루프·중복 정의 감지"

    * cycle — 조상 경로에 같은 id 가 다시 나타남. "A 를 하려면 B 가 필요하고 B 를 하려면
      A 가 필요하다" → 어느 것도 먼저 착수할 수 없는 **데드 루프**. 목적 맵에서는 논리 결함이다.
    * duplicate — 같은 id 가 서로 다른 위치에 2회 이상 정의됨. 순환은 아니지만 mermaid 가
      노드를 중복 정의해 그래프가 깨진다(설계 문서 "한 프로젝트가 여러 목적에 필요할 때" 참조).

    반환: {"cycles": [[id...]], "duplicates": {id: [경로문자열, ...]}}
    """
    if found is None:
        found = {"cycles": [], "duplicates": {}}
        seen, ancestors, path = {}, [], []
    for n in nodes:
        pid = n["id"]
        label = pid or n["label"]
        if pid:
            if pid in ancestors:
                # 조상에서 자신까지의 구간만 잘라 순환 고리를 보고한다.
                cut = ancestors.index(pid)
                found["cycles"].append(ancestors[cut:] + [pid])
                continue  # 더 내려가면 무한 재귀
            seen.setdefault(pid, []).append(" > ".join(path + [label]))
        child_anc = ancestors + [pid] if pid else ancestors
        detect_dead_loops(n["children"], child_anc, path + [label], found, seen)
    if not ancestors and not path:  # 최상위 호출에서만 집계
        found["duplicates"] = {k: v for k, v in seen.items() if len(v) > 1}
    return found


def build_reference_graph(maps):
    """Issue298 P2: 맵들 → 참조를 간선으로 환원한 **전체 그래프**.

    노드 키 — 프로젝트는 `#{id}`(맵을 가로질러 같은 노드), 그룹은 `{맵}/{경로}`(맵 안에서만 고유).
    참조(`- "맵"`)는 노드를 만들지 않고 **부모 → 대상 맵 루트** 간선이 된다(렌더와 같은 규약).

    반환: (edges: {키: [키…]}, labels: {키: 표시명}, self_refs: [(맵, 부모표시명)])
    """
    edges, labels, self_refs = {}, {}, []
    roots_of = {}
    for name, roots in maps.items():
        keys = []
        for n in roots:
            kind = n.get("kind") or ("project" if n.get("id") else "group")
            if kind == "ref":
                continue
            keys.append(f"#{n['id']}" if n.get("id") else f"{name}/{n['label']}")
        roots_of[name] = keys

    def walk(name, nodes, parent_key, path):
        for n in nodes:
            kind = n.get("kind") or ("project" if n.get("id") else "group")
            if kind == "ref":
                target = n["label"]
                if target == name:
                    self_refs.append((name, parent_key or "(맵 최상위)"))
                    continue
                if parent_key:
                    for dst in roots_of.get(target, []):
                        edges.setdefault(parent_key, []).append(dst)
                continue
            key = f"#{n['id']}" if n.get("id") else f"{name}/{'/'.join(path + [n['label']])}"
            labels[key] = f"{n['label']}" + (f" #{n['id']}" if n.get("id") else "")
            if parent_key:
                edges.setdefault(parent_key, []).append(key)
            walk(name, n["children"], key, path + [n["label"]])

    for name, roots in maps.items():
        walk(name, roots, None, [])
    return edges, labels, self_refs


def detect_reference_cycles(maps):
    """참조 환원 그래프에서 순환을 찾는다(DFS back-edge).

    트리 안의 순환만 보던 `detect_dead_loops` 와 달리, **맵을 건너뛰는 순환**을 잡는다 —
    `42 → "빠른_강의" → (그 맵 루트) 42` 같은 형태. 자기 참조(맵이 자기를 참조)는 별도 보고.
    """
    edges, labels, self_refs = build_reference_graph(maps)
    cycles, seen_sig = [], set()
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}

    def dfs(u, stack):
        color[u] = GRAY
        stack.append(u)
        for v in edges.get(u, []):
            c = color.get(v, WHITE)
            if c == GRAY:                      # back-edge → 순환
                cut = stack.index(v)
                ring = stack[cut:] + [v]
                sig = tuple(sorted(set(ring)))
                if sig not in seen_sig:
                    seen_sig.add(sig)
                    cycles.append([labels.get(k, k) for k in ring])
            elif c == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for k in list(edges.keys()) + list(labels.keys()):
        if color.get(k, WHITE) == WHITE:
            dfs(k, [])
    return {"cycles": cycles, "self_refs": self_refs}


def format_reference_report(report):
    """참조 그래프 검출 결과 → 사람이 읽는 줄 목록."""
    lines = []
    for cyc in report["cycles"]:
        lines.append("데드 루프(참조 포함): " + " → ".join(cyc) + "  (서로를 요구해 착수 불가)")
    for name, parent in report["self_refs"]:
        lines.append(f'자기 참조: 맵 "{name}" 안에서 자신을 참조 — {parent}')
    return lines


def format_dead_loop_report(report):
    """검출 결과를 사람이 읽는 줄 목록으로. 결함 없으면 빈 리스트.

    Issue298 P1-6: **중복 정의 경고를 철회**했다. 같은 프로젝트가 여러 목적에 필요한 것은
    정상이며(`10 finfraHome` 은 프로모션·컨설팅·SNS 마케팅 모두에 필요), 렌더가 노드를
    1회만 정의하고 간선을 여러 개 걸어 다중 부모로 합치므로 그래프도 깨지지 않는다.
    `duplicates` 는 호출부가 넘기면 무시한다 — 아래 목적 충돌만 정보로 알린다.
    """
    lines = []
    for cyc in report["cycles"]:
        lines.append("데드 루프: " + " → ".join(cyc) + "  (서로를 요구해 착수 불가)")
    for pid, purposes in sorted(report.get("purpose_conflicts", {}).items(),
                                key=lambda kv: int(kv[0])):
        lines.append(f"목적 충돌(정보): #{pid} 에 서로 다른 목적이 적힘 — "
                     + " | ".join(purposes))
    return lines


def detect_purpose_conflicts(maps):
    """같은 프로젝트에 서로 다른 `:` 목적이 적힌 경우를 모은다.

    다중 부모 자체는 정상이지만, 목적이 갈리면 렌더가 어느 것을 표시할지 모호해진다.
    결함이 아니라 **정보**로 알린다.
    """
    seen = {}

    def walk(nodes):
        for n in nodes:
            if n.get("id") and n.get("purpose"):
                seen.setdefault(n["id"], set()).add(n["purpose"])
            walk(n["children"])

    for name, roots in maps.items():
        if name == MISC_LABEL:
            continue
        walk(roots)
    return {k: sorted(v) for k, v in seen.items() if len(v) > 1}


# ── mermaid 렌더 (Issue294) ─────────────────────────────────────────────
_MMD_UNSAFE = str.maketrans({'"': "'", "`": "'", "[": "(", "]": ")",
                             "{": "(", "}": ")", "|": "/", "\n": " "})


def mmd_label(text):
    """mermaid 라벨 안전화 — 따옴표·대괄호·백틱은 파서를 깨뜨린다.
    백틱은 특히 markdown-string("`...`") 으로 오인되어 노드가 통째로 사라진다."""
    return text.translate(_MMD_UNSAFE).strip()


def mmd_id(prefix, key):
    """mermaid 노드 id — 영숫자·언더스코어만 허용."""
    return prefix + re.sub(r"[^A-Za-z0-9_]", "_", str(key))


def node_label(node):
    """노드 라벨 — 목적(`:` 뒤)이 있으면 이름 **아래 줄**에 함께 그린다.

    목적은 이 지도의 존재 이유다(설계 "`:` 는 목적이지 설명이 아니다"). 툴팁으로만
    두면 마우스를 올려야 보이므로 지도를 훑어서는 "무엇을 위해"가 읽히지 않는다.
    흐름은 좌→우지만 목적은 이름 밑에 붙어야 이름과 한 덩어리로 읽힌다.
    목적이 없는 노드는 한 줄 그대로 — 빈 줄로 높이만 키우지 않는다.
    """
    label = node["label"]
    purpose = node.get("purpose")
    if not purpose:
        return label
    return f"{label}<br/><small>{mmd_label(purpose)}</small>"


def text_on(color):
    """배경색 luminance 로 대비되는 글자색 선택 (어두운 peacock 색 위 검정 글씨 방지)."""
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", (color or "").strip())
    if not m:
        return "#1a1a1a"
    r, g, b = (int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return "#ffffff" if (0.299 * r + 0.587 * g + 0.114 * b) < 140 else "#1a1a1a"


def collect_map(nodes, table, maps_ctx, parent_nid=None, map_name=""):
    """한 맵의 노드 트리를 순회하며 (노드 정의, 간선) 을 맵 컨텍스트에 모은다.

    Issue298:
    * 참조 노드는 **mermaid 노드를 만들지 않는다** — 부모에서 대상 맵의 루트로 간선만 건다.
      노드를 만들면 껍데기가 생기고, 서브트리를 복제하면 순환에서 무한 전개된다.
    * 그룹 노드(id 없음)는 목적·중간 목표라 링크 대상이 아니지만 그래프에는 그린다 —
      맵 안에서 무엇이 무엇에 기여하는지가 그룹을 통해 드러나야 하기 때문.
    """
    for n in nodes:
        kind = n.get("kind") or ("project" if n.get("id") else "group")
        if kind == "ref":
            maps_ctx["refs"].append((parent_nid, n["label"]))
            continue
        if kind == "group":
            # Issue298: 그룹 id 는 **맵 이름으로 네임스페이스**한다. 맵마다 카운터를
            #   리셋하면 서로 다른 맵의 그룹이 같은 `G0` 를 갖게 되어, 렌더의 중복 노드
            #   방지가 뒤 노드를 통째로 삼키고 간선이 엉뚱한 노드로 붙는다(실측: Main Map
            #   의 `Goal` 과 fApp 의 `App 개발` 이 충돌해 후자가 사라지고 fBanner 가
            #   Goal 에 매달렸다).
            nid = mmd_id("G", f"{map_name}_{len(maps_ctx['nodes']) + len(maps_ctx['ref_seq'])}")
            maps_ctx["ref_seq"].append(nid)
            maps_ctx["nodes"].append({
                "nid": nid, "id": None, "label": mmd_label(n["label"]),
                "purpose": n.get("purpose"), "actor": False,
                "dead": False, "color": "", "path": "",
            })
        else:
            pid = n["id"]
            nid = mmd_id("P", pid)
            meta = table.get(pid)
            if meta is None:
                maps_ctx["nodes"].append({
                    "nid": nid, "id": pid, "label": f'{mmd_label(n["label"])} #{pid} (표에 없음)',
                    "purpose": n.get("purpose"), "actor": n.get("actor", False),
                    "dead": True, "color": "", "path": "",
                })
            else:
                path = os.path.expanduser(meta["path"])
                maps_ctx["nodes"].append({
                    "nid": nid, "id": pid,
                    "label": f'{mmd_label(meta["emoji"])} {mmd_label(meta["name"])} #{pid}',
                    "purpose": n.get("purpose"), "actor": n.get("actor", False),
                    "dead": not os.path.exists(path),
                    "color": meta["color"] or "", "path": path,
                })
        if parent_nid:
            maps_ctx["edges"].append((parent_nid, nid))
        else:
            # Issue298 P4: 최상위 노드의 nid 를 그대로 기록한다. 참조 간선의 도착점이며,
            #   그룹 루트(`App 개발`·`보조 도구`)는 id 가 없어 밖에서 nid 를 되계산할 수 없다.
            maps_ctx["roots"].append(nid)
        collect_map(n["children"], table, maps_ctx, parent_nid=nid, map_name=map_name)


def render_mermaid(maps, table):
    """맵들 → 한 장의 mermaid flowchart.

    맵 분리는 *편집 단위*이지 표시 단위가 아니다(설계 "맵 구성"). 맵마다 `subgraph`
    로 묶되 참조는 간선으로 환원해 그래프가 하나로 이어지게 한다. mermaid 는 트리가
    아니라 그래프이므로 다중 부모·순환이 있어도 노드가 중복되지 않는다.
    """
    # Issue298 P1-6: `미할당` 는 그래프에 그리지 않는다 — 목적이 없는 프로젝트가 22건이면
    #   목적 지향 지도가 미할당 덩어리에 압도된다. 다이어그램 아래 리스트로 따로 낸다.
    ctx = {}
    for name, roots in maps.items():
        if name == MISC_LABEL:
            continue
        c = {"nodes": [], "edges": [], "refs": [], "ref_seq": [], "roots": []}
        collect_map(roots, table, c, map_name=name)
        ctx[name] = c

    # 맵 이름 → 그 맵 루트 노드들의 nid (참조 간선의 도착점).
    #   collect_map 이 순회하며 기록한 값을 그대로 쓴다 — 밖에서 되계산하면 그룹 루트를
    #   놓친다(그룹은 id 가 없어 nid 를 유추할 수 없고, 실제로 `보조 도구` 가 빠졌었다).
    roots_of = {name: c["roots"] for name, c in ctx.items()}

    # Issue298 P4: 맵 헤딩을 **노드로 승격**한다(설계 "맵 구성" — subgraph 제목 또는 루트).
    #   subgraph 로 감싸면 참조 화살표가 클러스터 경계에서 끝나 어디로 이어지는지 눈으로
    #   못 따라가고, 클러스터가 멀리 배치돼 화살표가 화면을 가로지른다(실측: 697px →
    #   subgraph 제거 시 210px). 맵을 노드로 세우면 노드끼리 이어지고, 참조도 맵 노드
    #   하나로 수렴해 화살표가 퍼지지 않는다.
    # Issue298 P4-0: 두 요구를 함께 만족시킨다.
    #   * **그룹 표시** — subgraph 로 맵 경계를 그리고 라벨에 맵 이름을 단다
    #   * **노드 → 노드** — 참조는 subgraph 가 아니라 그 맵의 **루트 노드**를 가리킨다.
    #     subgraph 를 가리키면 화살표가 경계에서 끝나 어디로 이어지는지 눈으로 못 따라간다.
    #   맵 노드를 따로 세우는 안도 시도했으나 subgraph 라벨과 역할이 겹쳐 되돌렸다.
    lines = ["flowchart LR"]
    seen_nid = set()
    for name, c in ctx.items():
        lines.append(f'  subgraph {mmd_id("SG", name)}["{mmd_label(name)}"]')
        for n in c["nodes"]:
            if n["nid"] in seen_nid:
                continue
            seen_nid.add(n["nid"])
            lines.append(f'    {n["nid"]}["{node_label(n)}"]')
        lines.append("  end")

    for name, c in ctx.items():
        for src, dst in c["edges"]:
            lines.append(f"  {src} --> {dst}")
        # Issue298 P4: 참조 → **대상 맵의 루트 노드**로 간선. subgraph 자체를 가리키면
        #   화살표가 클러스터 경계에서 끝나 어디로 이어지는지 눈으로 못 따라간다(실사용 확인).
        #   노드끼리 이어야 읽힌다 — 화살표가 여럿이 되더라도 각각이 무엇을 가리키는지 분명하다.
        for parent_nid, ref_name in c["refs"]:
            if not parent_nid:
                continue
            dsts = roots_of.get(ref_name)
            if not dsts:
                print(f"  ⚠️ 참조 대상 맵 없음: \"{ref_name}\" (오타?)", file=sys.stderr)
                continue
            for dst in dsts:
                lines.append(f"  {parent_nid} -.-> {dst}")

    styled = set()
    for name, c in ctx.items():
        for n in c["nodes"]:
            if n["nid"] in styled:
                continue
            styled.add(n["nid"])
            if n["dead"]:
                lines.append(f'  style {n["nid"]} fill:#e8e8e8,stroke:#bbb,color:#999,'
                             f"stroke-dasharray:4 3")
            elif n["actor"]:
                lines.append(f'  style {n["nid"]} fill:{n["color"] or "#ffffff"},'
                             f'stroke:#333,stroke-width:3px,color:{text_on(n["color"])}')
            elif n["color"]:
                lines.append(f'  style {n["nid"]} fill:{n["color"]},stroke:#00000033,'
                             f'color:{text_on(n["color"])}')
            if n["id"]:
                tip = n["purpose"] or n["path"] or "경로 미상"
                # Issue294: 커스텀 스킴은 mermaid strict 가 sanitize → 상대경로 http 브리지만 유효
                lines.append(f'  click {n["nid"]} href "/open-prj?id={n["id"]}" '
                             f'"{mmd_label(tip)}"')
    return "\n".join(lines)


def render_node(node, table, depth=0):
    if node["id"] is None:
        inner = "".join(render_node(c, table, depth + 1) for c in node["children"])
        return (
            f'<details open><summary>{html.escape(node["label"])}</summary>'
            f"<ul>{inner}</ul></details>"
        )

    pid = node["id"]
    meta = table.get(pid)
    if meta is None:
        return f'<li class="dead">{html.escape(pid)}. {html.escape(node["label"])} (표에 없음)</li>'

    path = os.path.expanduser(meta["path"])
    exists = os.path.exists(path)
    quoted = urllib.parse.quote(path, safe="/")
    file_href = "file://" + quoted
    vscode_href = "vscode://file" + quoted
    emoji = html.escape(meta["emoji"])
    name = html.escape(meta["name"])
    color = meta["color"] or "#dddddd"
    swatch = f'<span class="swatch" style="background:{html.escape(color)}"></span>'

    if exists:
        main_link = f'<a class="node-link" href="{file_href}">{emoji} {name}</a>'
    else:
        main_link = (
            f'<span class="node-link dead" title="경로 없음: {html.escape(path)}">'
            f"{emoji} {name}</span>"
        )

    children_html = "".join(render_node(c, table, depth + 1) for c in node["children"])
    children_block = f"<ul>{children_html}</ul>" if children_html else ""

    return (
        f'<li data-name="{html.escape(meta["name"].lower())}">'
        f"{swatch}{main_link} "
        f'<span class="id-tag">#{html.escape(pid)}</span> '
        f'<a class="mini-link" href="{vscode_href}" title="VSCode 로 열기">🆚</a> '
        f'<button type="button" class="copy-btn" data-copy="cdf {html.escape(pid)}" '
        f'title="cdf {html.escape(pid)} 복사">📋</button>'
        f"{children_block}</li>"
    )


HTML_HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projects_map</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }
  h1 { font-size: 1.4rem; }
  .meta { color: #777; font-size: 0.85rem; margin-bottom: 1rem; }
  input#filter { width: 100%; box-sizing: border-box; padding: 0.5rem; font-size: 1rem;
    margin-bottom: 1rem; }
  ul { list-style: none; padding-left: 1.2rem; }
  details { margin: 0.2rem 0; }
  summary { cursor: pointer; font-weight: 600; }
  li { margin: 0.15rem 0; }
  .swatch { display: inline-block; width: 0.7em; height: 0.7em; border-radius: 2px;
    margin-right: 0.3em; vertical-align: middle; }
  .node-link { text-decoration: none; }
  .node-link:hover { text-decoration: underline; }
  .node-link.dead { color: #999; text-decoration: line-through; cursor: not-allowed; }
  .id-tag { color: #999; font-size: 0.8em; }
  .mini-link, .copy-btn { font-size: 0.8em; text-decoration: none; border: none;
    background: none; cursor: pointer; opacity: 0.6; }
  .mini-link:hover, .copy-btn:hover { opacity: 1; }
  li.hidden { display: none; }
  #notes { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #ccc; }
  .deadloop { background: #fdf1f0; border: 1px solid #e0a49c; border-left: 4px solid #c0392b;
    border-radius: 8px; padding: 0.8rem 1.1rem; margin: 1rem 0; }
  .deadloop ul { list-style: disc; padding-left: 1.4rem; margin: 0.5rem 0; }
  .deadloop li { margin: 0.2rem 0; }
  .deadloop small { color: #7a4a44; }
  #misc { margin: 1.2rem 0; padding: 0.8rem 1.1rem; border: 1px solid #d8d8d0;
    border-radius: 8px; background: #fafaf5; font-size: 0.94rem; }
  .misc-list { list-style: none; padding-left: 0; display: flex; flex-wrap: wrap;
    gap: 0.3rem 0.9rem; margin: 0.6rem 0 0; }
  .misc-list li { margin: 0; }
  @media (prefers-color-scheme: dark) {
    body { background: #1e1e1e; color: #ddd; }
    #notes { border-top-color: #444; }
    .deadloop { background: #2a1614; border-color: #7a3a32; }
    .deadloop small { color: #d9a49c; }
    #misc { background: #202024; border-color: #3a3b40; }
  }
</style>
</head>
<body>
<h1>Projects_map</h1>
"""

HTML_TAIL_SCRIPT = """
<script>
document.getElementById('filter').addEventListener('input', function (e) {
  var q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('li[data-name]').forEach(function (li) {
    var name = li.getAttribute('data-name');
    li.classList.toggle('hidden', q.length > 0 && name.indexOf(q) === -1);
  });
});
document.querySelectorAll('.copy-btn').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var text = btn.getAttribute('data-copy');
    function ok() {
      var o = btn.textContent;
      btn.textContent = '✓';
      setTimeout(function () { btn.textContent = o; }, 1000);
    }
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      ok();
    } catch (e) {
      window.prompt('복사할 명령', text);
    }
  });
});
</script>
</body>
</html>
"""

DEFAULT_NOTES = "\n(여기에 수기 메모를 남기세요 — 재생성 시 이 구간만 보존됩니다)\n"


def extract_existing_notes(out_path):
    if not out_path.exists():
        return None
    text = out_path.read_text(encoding="utf-8")
    m = re.search(
        r"<!-- PROJECTS-MAP:NOTES -->(.*?)<!-- /PROJECTS-MAP:NOTES -->", text, re.DOTALL
    )
    if m:
        return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="___pm 루트 경로 (기본: 스크립트 위치 기준 자동)")
    ap.add_argument("--projects", default=None, help="Projects.md 경로 (기본: {root}/Projects.md)")
    ap.add_argument("--out", default=None, help="출력 경로 (기본: {root}/Projects_map.htm)")
    ap.add_argument("--strict", action="store_true",
                    help="데드 루프·중복 정의 검출 시 종료코드 1 (기본: 경고만 하고 생성은 진행)")
    args = ap.parse_args()

    root = find_root(args.root)
    projects_path = Path(args.projects) if args.projects else root / "Projects.md"
    out_path = Path(args.out) if args.out else root / "Projects_map.htm"

    if not read_toggle(root):
        print("projects_map_setting.yml enabled=false — 생성 스킵(no-op)")
        return 0

    if not projects_path.exists():
        print(f"Projects.md 없음: {projects_path}", file=sys.stderr)
        return 1

    md_text = projects_path.read_text(encoding="utf-8")
    table = parse_table(md_text)
    maps = parse_maps(md_text)
    _refixed = resolve_refs(maps)
    if not maps:
        print("# Project Map 섹션을 찾지 못함", file=sys.stderr)
        return 1

    # 데드 루프 감지 — 미할당 합성 노드가 섞이기 전(enforce_completeness 앞)에 검사한다.
    #   합성 노드는 생성기가 만든 것이라 사람이 고칠 결함이 아니다.
    #   Issue298: 순환은 맵별로, 중복 정의는 **맵을 가로질러** 검사한다 — 같은 프로젝트가
    #   서로 다른 맵에 실물로 정의되는 것이 실제 발생 패턴이고, 맵별로만 보면 놓친다.
    loop_lines = [f'참조로 볼 수 없어 그룹으로 처리: "{_lbl}" ({_why})' for _lbl, _why in _refixed]
    for _name, _roots in maps.items():
        rep = detect_dead_loops(_roots)
        rep["duplicates"] = {}          # 중복은 아래에서 전 맵 기준으로 다시 계산
        loop_lines += format_dead_loop_report(rep)
    #   Issue298 P1-6: 중복 정의는 결함이 아니다(다중 부모 = 정상). 목적 충돌만 정보로 알린다.
    loop_lines += format_dead_loop_report({"cycles": [], "purpose_conflicts": detect_purpose_conflicts(maps)})
    #   Issue298 P2: 참조를 간선으로 환원한 전체 그래프에서 맵을 건너뛰는 순환·자기 참조 검출.
    loop_lines += format_reference_report(detect_reference_cycles(maps))

    missing = enforce_completeness(maps, table)

    # Issue294: 표현은 mermaid flowchart. 텍스트 트리는 다이어그램이 못 뜨는 환경
    #   (런타임 미주입·CSP 차단)의 fallback 으로 <details> 안에 함께 싣는다.
    mermaid_src = render_mermaid(maps, table)
    tree_html = "".join(
        f'<details open><summary>{html.escape(name)}</summary><ul>'
        + "".join(render_node(n, table) for n in roots) + "</ul></details>"
        for name, roots in maps.items()
    )

    existing_notes = extract_existing_notes(out_path)
    notes_body = existing_notes if existing_notes is not None else DEFAULT_NOTES

    # Issue298 P1-6: 미할당는 그래프 밖 리스트로. 링크는 유지해 바로 열 수 있게 한다.
    misc_html = ""
    if missing:
        items = []
        for pid in missing:
            meta = table.get(pid) or {}
            nm = html.escape(f'{meta.get("emoji","")} {meta.get("name", pid)}'.strip())
            items.append(f'<li><a href="/open-prj?id={html.escape(pid)}">{nm}</a> '
                         f'<span class="id-tag">#{html.escape(pid)}</span></li>')
        misc_html = ('<div id="misc"><b>미할당 ' + str(len(missing)) + '건</b> — '
                     "아직 어느 목적에도 붙지 않은 프로젝트입니다. 결함이 아니라 "
                     "<b>목적 미할당 신호</b>이므로, 목적이 생기면 맵에 넣고 없으면 그대로 둡니다."
                     f'<ul class="misc-list">{"".join(items)}</ul></div>')

    warn_html = ""
    if loop_lines:
        items = "".join(f"<li>{html.escape(x)}</li>" for x in loop_lines)
        warn_html = ('<div class="deadloop"><b>⚠️ 확인 필요 '
                     f'{len(loop_lines)}건</b><ul>{items}</ul>'
                     "<small>데드 루프는 서로를 요구해 어느 쪽도 먼저 착수할 수 없는 상태로 "
                     "<b>결함</b>입니다. 목적 충돌은 같은 프로젝트에 서로 다른 목적이 적힌 "
                     "경우로 <b>정보</b>이며, 같은 프로젝트가 여러 목적에 필요한 것 자체는 "
                     "정상입니다. 상세: _doc_arch/projects-map-design.md</small></div>")

    body = [
        HTML_HEAD,
        warn_html,
        f'<div class="meta">프로젝트 {len(table)}건'
        + (f" · 미할당 편입 {len(missing)}건" if missing else "")
        + " · 노드 클릭 → VSCode 로 열기</div>",
        "<!-- PROJECTS-MAP:MERMAID -->",
        '<pre class="mermaid">',
        html.escape(mermaid_src),
        "</pre>",
        "<!-- /PROJECTS-MAP:MERMAID -->",
        misc_html,
        '<details id="text-tree"><summary>텍스트 트리 (필터·복사)</summary>',
        '<input id="filter" type="text" placeholder="프로젝트명 필터…">',
        "<!-- PROJECTS-MAP:TREE -->",
        tree_html,
        "<!-- /PROJECTS-MAP:TREE -->",
        "</details>",
        '<div id="notes">',
        "<!-- PROJECTS-MAP:NOTES -->",
        notes_body,
        "<!-- /PROJECTS-MAP:NOTES -->",
        "</div>",
        HTML_TAIL_SCRIPT,
    ]
    out_path.write_text("\n".join(body), encoding="utf-8")

    print(f"Projects_map.htm 생성 완료 — 프로젝트 {len(table)}건, 미할당 편입 {len(missing)}건")
    if loop_lines:
        print(f"  ⚠️ 확인 필요 {len(loop_lines)}건:", file=sys.stderr)
        for x in loop_lines:
            print(f"    - {x}", file=sys.stderr)
    if missing:
        print(f"  미할당 id: {', '.join(missing)}")
    print(f"  출력: {out_path}")
    # 결함이 있어도 산출물은 남긴다 — 맵이 사라지는 편이 더 나쁘다. --strict 만 종료코드로 알린다.
    if loop_lines and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
