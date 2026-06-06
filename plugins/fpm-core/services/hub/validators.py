"""dashboard content schema 검증.

Issue30 (server.py 모듈 분리)으로 server.py 에서 추출됨.
향후 form/answer payload 등 추가 검증도 본 모듈에 누적.
"""

import json


# Issue24 Phase 2: dashboard schema 검증
# Issue66: graph 위젯 추가 (DAG 큐 시각화)
DASH_WIDGET_TYPES = {
    "progress", "table", "checklist", "text",
    "chart", "log", "diff", "timer", "badge", "graph",
}


def validate_dashboard(content: str):
    """dashboard content(JSON 문자열) schema 검증. 통과 시 None, 위반 시 에러 메시지."""
    if not content:
        return "empty dashboard content"
    try:
        data = json.loads(content)
    except Exception as e:
        return f"dashboard content not valid JSON: {e}"
    if not isinstance(data, dict):
        return "dashboard content must be JSON object"
    widgets = data.get("widgets")
    if widgets is None:
        return "dashboard.widgets missing"
    if not isinstance(widgets, list):
        return "dashboard.widgets must be array"
    for i, w in enumerate(widgets):
        if not isinstance(w, dict):
            return f"widget[{i}] must be object"
        wtype = w.get("type")
        if wtype not in DASH_WIDGET_TYPES:
            return f"widget[{i}].type unknown: {wtype!r} (allowed: {sorted(DASH_WIDGET_TYPES)})"
        # 필수 필드 검증
        if wtype == "progress":
            v = w.get("value")
            if not isinstance(v, (int, float)):
                return f"widget[{i}](progress).value missing or not number"
        elif wtype == "table":
            if not isinstance(w.get("rows"), list):
                return f"widget[{i}](table).rows missing or not array"
        elif wtype == "checklist":
            if not isinstance(w.get("items"), list):
                return f"widget[{i}](checklist).items missing or not array"
        elif wtype == "text":
            if w.get("content") is None and w.get("text") is None:
                return f"widget[{i}](text) requires 'content' or 'text'"
        elif wtype == "chart":
            s = w.get("series")
            if not isinstance(s, list):
                return f"widget[{i}](chart).series missing or not array"
            kind = w.get("kind", "bar")
            if kind not in ("bar", "line"):
                return f"widget[{i}](chart).kind must be 'bar' or 'line', got {kind!r}"
        elif wtype == "log":
            if not isinstance(w.get("lines"), list):
                return f"widget[{i}](log).lines missing or not array"
        elif wtype == "diff":
            if w.get("before") is None or w.get("after") is None:
                return f"widget[{i}](diff) requires 'before' and 'after'"
        elif wtype == "timer":
            mode = w.get("mode", "up")
            if mode not in ("up", "down"):
                return f"widget[{i}](timer).mode must be 'up' or 'down', got {mode!r}"
            if mode == "up" and not isinstance(w.get("start_ts"), (int, float)):
                return f"widget[{i}](timer up).start_ts missing or not number"
            if mode == "down" and not isinstance(w.get("target"), (int, float)):
                return f"widget[{i}](timer down).target missing or not number"
        elif wtype == "badge":
            if w.get("label") is None:
                return f"widget[{i}](badge).label missing"
        elif wtype == "graph":
            # Issue66: DAG 큐 시각화 위젯 — nodes/edges 필수.
            # node 는 id·label 둘 다 필수, edge 는 from·to 둘 다 필수.
            # 키 부재(None)뿐 아니라 빈/공백 문자열·비문자열도 거부 —
            # 빈 label 은 빈 노드로 렌더되고, 비문자열 id 는 renderer idMap 매칭을 깬다.
            nodes = w.get("nodes")
            if not isinstance(nodes, list):
                return f"widget[{i}](graph).nodes missing or not array"
            edges = w.get("edges")
            if not isinstance(edges, list):
                return f"widget[{i}](graph).edges missing or not array"

            def _bad_field(v):
                """필수 식별 필드 검증 — None·비문자열·빈/공백 문자열이면 True(불량)."""
                return not isinstance(v, str) or not v.strip()

            for ni, node in enumerate(nodes):
                if not isinstance(node, dict):
                    return f"widget[{i}](graph).nodes[{ni}] must be object"
                if "id" not in node:
                    return f"widget[{i}](graph).nodes[{ni}].id missing"
                if _bad_field(node.get("id")):
                    return f"widget[{i}](graph).nodes[{ni}].id must be non-empty string"
                if "label" not in node:
                    return f"widget[{i}](graph).nodes[{ni}].label missing"
                if _bad_field(node.get("label")):
                    return f"widget[{i}](graph).nodes[{ni}].label must be non-empty string"
                node_action = node.get("action")
                if node_action is not None and not isinstance(node_action, dict):
                    return f"widget[{i}](graph).nodes[{ni}].action must be object"
            for ei, edge in enumerate(edges):
                if not isinstance(edge, dict):
                    return f"widget[{i}](graph).edges[{ei}] must be object"
                if "from" not in edge:
                    return f"widget[{i}](graph).edges[{ei}].from missing"
                if _bad_field(edge.get("from")):
                    return f"widget[{i}](graph).edges[{ei}].from must be non-empty string"
                if "to" not in edge:
                    return f"widget[{i}](graph).edges[{ei}].to missing"
                if _bad_field(edge.get("to")):
                    return f"widget[{i}](graph).edges[{ei}].to must be non-empty string"
        # width 필드 검증 (Issue77 — 글로벌 .claude#Issue91 짝, 선택).
        # 위젯 spec 의 optional 너비 힌트. 부재·기타 값이면 기본 1셀 멀티컬럼,
        # 'full' 이면 그리드 전폭 1컬럼 행. 값이 있으면 문자열만 허용 —
        # 미지의 문자열 값은 reject 하지 않고 renderDashboard 가 기본(1셀)으로 처리.
        width = w.get("width")
        if width is not None and not isinstance(width, str):
            return f"widget[{i}].width must be string ('full' or omit), got {width!r}"

        # action 필드 검증 (Phase 3 도입, 선택)
        action = w.get("action")
        if action is not None:
            if not isinstance(action, dict):
                return f"widget[{i}].action must be object"
            atype = action.get("type")
            if atype not in ("link", "notify", "control"):
                return f"widget[{i}].action.type must be 'link'|'notify'|'control', got {atype!r}"
            if atype == "link" and not isinstance(action.get("url"), str):
                return f"widget[{i}].action(link).url missing or not string"
    return None
