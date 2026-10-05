#!/usr/bin/env python3
# test_fbot_cascade_issue545.py — 핀봇 지시 흐름 캐스케이드 (Issue545 M3-1~3 · M4-1, prj3#Issue739 계보 소비)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: 보드·흐름 그래프는 배분의 부모를 «배분자를 대상으로 가진 직전 배분» 으로 **시간순 추정**했다. 같은 봇이
#   두 지시를 병행하면 뒤 지시의 하위가 앞 지시에 붙는다(plan 결정 2). prj3#Issue739 가 원장에
#   `parent_dispatch_id`·`root_dispatch_id` 를 남기므로 부모는 원장이 정한다 — 추정은 계보 필드가 **없는 옛 기록**에만.
# 지키는 것: ① 원장 추출이 계보 필드를 싣는다 ② 원장 계보 > 추정(병행 체인 함정) ③ 루트별 캐스케이드 — 파생 수·깊이,
#   취소·회수된 가지에 달린 하위도 끊기지 않는다(M3-3) ④ «지시 선택» 필터가 계보로 하위를 모은다
#   ⑤ 봇 카드 «지시 중» = 그 봇이 낸 열린 배분(M4-1)
#
# 실행: python3 plugins/fpm-core/services/hub/test_fbot_cascade_issue545.py
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}" + (f"\n       {str(detail)[:300]}" if detail else ""))


def row(jid, owner, worker, issue, ts, status="open", **lin):
    pl = {"worker_bot_id": worker, "issue": issue, "role": "lead"}
    pl.update(lin)
    return (jid, owner, json.dumps(pl), status, ts)


# d1(루트) ─ d2 · d3(회수) ─ d4 · d6  /  d5(다른 루트, 같은 lead 가 병행)  /  d7 ─ d8 (계보 필드 없는 옛 기록)
ROWS = [
    row("d7", "chief", "lead2", "Old1", 50),
    row("d8", "lead2", "w8", "Old1-a", 60),
    row("d1", "chief", "lead", "Issue545", 100, parent_dispatch_id=None, root_dispatch_id="d1"),
    row("d2", "lead", "wa", "Issue545 A", 200, parent_dispatch_id="d1", root_dispatch_id="d1"),
    row("d5", "chief", "lead", "Issue999", 205, parent_dispatch_id=None, root_dispatch_id="d5"),
    row("d3", "lead", "wb", "Issue545 B", 210, "reaped", parent_dispatch_id="d1", root_dispatch_id="d1"),
    row("d4", "wb", "sub", "Issue545 B-1", 220, parent_dispatch_id="d3", root_dispatch_id="d1"),
    # 함정: d6 은 d1 의 하위다(원장). 시간순 추정은 lead 의 가장 최근 수신 배분 d5 에 붙인다
    row("d6", "lead", "wc", "prj1#Issue545 C", 230, parent_dispatch_id="d1", root_dispatch_id="d1",
        task_ref="_doc_work/plan/x_task.md#M3", cwd="/Users/x/_git/___pm"),
]


def main():
    print("[1] 원장 추출이 계보 필드를 싣는다")
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE job (id TEXT, kind TEXT, owner TEXT, payload TEXT, status TEXT, created_at INT)")
    for jid, owner, pl, st, ts in ROWS:
        con.execute("INSERT INTO job VALUES (?,?,?,?,?,?)", (jid, "fbot_dispatch", owner, pl, st, ts))
    edges = server._fbot_dispatch_edges(con)
    by = {e["job_id"]: e for e in edges}
    check("d6 parent_dispatch_id = d1 · root = d1", by["d6"].get("parent_dispatch_id") == "d1" and by["d6"].get("root_dispatch_id") == "d1")
    check("d6 task_ref 를 싣는다", by["d6"].get("task_ref") == "_doc_work/plan/x_task.md#M3")
    check("계보 필드 유무를 구분한다(d1 = 원장 루트, d7 = 옛 기록)", by["d1"].get("lineage") is True and by["d7"].get("lineage") is False)

    print("[2] 부모 — 원장 계보가 추정을 이긴다")
    nodes = [{"bot_id": b, "title": b, "role": "lead", "state": "working", "root": b}
             for b in ("chief", "lead", "lead2", "wa", "wb", "wc", "sub", "w8")]
    d = server._fbot_board_payload({"nodes": nodes, "dispatch": edges}, {"available": True, "seats": []}, now=1000)
    pe = {e["job_id"]: e for e in d["dispatch"]}
    check("병행 함정: d6 의 부모 = d1(원장) — d5 아님", pe["d6"]["parent"] == "d1" and pe["d6"].get("parent_via") == "ledger", pe["d6"])
    check("원장 루트 d1·d5 는 부모 없음", pe["d1"]["parent"] is None and pe["d5"]["parent"] is None)
    check("옛 기록 d8 만 추정(부모 d7 · via inferred)", pe["d8"]["parent"] == "d7" and pe["d8"].get("parent_via") == "inferred", pe["d8"])

    print("[3] 캐스케이드 — 루트별 트리")
    cs = d.get("cascade") or {}
    roots = {r["job"]: r for r in cs.get("roots") or []}
    check("루트 = d1·d5·d7", set(roots) == {"d1", "d5", "d7"}, roots.keys())
    check("d1 파생 수 4(d2·d3·d4·d6) · 깊이 2", roots.get("d1", {}).get("descendants") == 4 and roots.get("d1", {}).get("depth") == 2, roots.get("d1"))
    nd = cs.get("nodes") or {}
    check("회수된 가지(d3)는 cut 표시 · 그 하위 d4 는 끊기지 않고 d3 아래·루트 d1", nd.get("d3", {}).get("cut") is True
          and nd.get("d4", {}).get("parent") == "d3" and nd.get("d4", {}).get("root") == "d1", (nd.get("d3"), nd.get("d4")))
    check("d5 는 파생 0(병행 지시의 하위가 붙지 않는다)", roots.get("d5", {}).get("descendants") == 0)

    print("[4] «지시 선택» 필터 — 계보로 하위를 모은다")
    f1 = {e["job_id"] for e in server._fbot_flow_filter(edges, job="d1")}
    check("job=d1 → d1·d2·d3·d4·d6", f1 == {"d1", "d2", "d3", "d4", "d6"}, f1)
    f5 = {e["job_id"] for e in server._fbot_flow_filter(edges, job="d5")}
    check("job=d5 → d5 만(시간순 추정이면 d6 이 끼어든다)", f5 == {"d5"}, f5)

    print("[5] 봇 카드 «지시 중»")
    lead = d["bots"]["lead"].get("directing")
    check("lead 가 낸 열린 배분 = d2·d6(회수 d3 제외) · 대상·이슈·시각", lead is not None
          and [x["job"] for x in lead] == ["d2", "d6"] and lead[0]["to"] == "wa" and lead[0]["issue"] == "Issue545 A", lead)

    check("지시 중 항목이 cwd 를 싣는다(이슈맵 링크 재료)", lead is not None and lead[-1].get("cwd") == "/Users/x/_git/___pm", lead)
    # prj3#Issue818 — 링크 여부는 서빙과 같은 판정(`_issue_map_openable`)이 정한다. cwd 만 보고 그리면
    #   Issue.md 가 없는 cwd 에서 404 막다른 길이 남는다(재판정 금지 — 클라이언트는 신호만 읽는다)
    check("Issue818: 지시 중 항목이 issue_map 신호를 싣는다 — 실재하지 않는 cwd 는 False",
          lead is not None and lead[-1].get("issue_map") is False, lead)
    _orig_open = getattr(server, "_issue_map_openable", None)
    server._issue_map_openable = lambda c, roots=None: c if c == "/Users/x/_git/___pm" else None
    try:
        d = server._fbot_board_payload({"nodes": nodes, "dispatch": edges}, {"available": True, "seats": []}, now=1000)
    finally:
        if _orig_open is not None:
            server._issue_map_openable = _orig_open
        else:
            del server._issue_map_openable
    lead = d["bots"]["lead"].get("directing")
    check("Issue818: 열 수 있는 cwd → issue_map True · cwd 없는 항목은 False",
          lead is not None and lead[-1].get("issue_map") is True and lead[0].get("issue_map") is False, lead)

    print("[6] 흐름 그래프 — 엣지 굵기 = 하위 파생 수 (M3-4)")
    fe = server._fbot_graph_elements({"nodes": nodes, "hires": [], "dispatch": edges}, None, "flow")
    w = {x["data"]["job"]: x["data"] for x in fe["edges"]}
    check("d1 w=5(자신+하위 4) · d5 w=1", w.get("d1", {}).get("w") == 5 and w.get("d5", {}).get("w") == 1, w.get("d1"))
    check("툴팁에 «하위 4»", "하위 4" in (w.get("d1", {}).get("full") or ""), w.get("d1"))
    body = open(server.__file__, encoding="utf-8").read()
    check("흐름 스타일이 w 로 굵기를 정한다(mapData)", "mapData(w," in body)

    print("[7] 흐름 탭 SSE 갱신 — 배분 생애 이벤트만 (M3-5)")
    check("지도 탭이 fbot SSE 를 구독한다", "__fbMapES" in body)
    check("배분 생애 이벤트(dispatch·assigned·done·cancel·reap)에만 반응", "FB_MAP_EV=/^(dispatch|assigned|done|cancel|reap)/" in body)

    print("[8] 봇 카드 «지시 중» 렌더 + 교차 링크 (M4-1·M4-2, node 실행)")
    import re as _re, shutil, subprocess, tempfile
    node = shutil.which("node")
    js_src = server._FBOT_BOARD_JS
    def grab(name):
        i = js_src.index("function " + name + "("); j = js_src.index("{", js_src.index(")", i)); dep = 0
        for k in range(j, len(js_src)):
            dep += (js_src[k] == "{") - (js_src[k] == "}")
            if dep == 0: return js_src[i:k + 1]
    if not node or "function directingHtml(" not in js_src:
        check("directingHtml 서빙 원문 존재", False)
    else:
        esc_line = next(l.strip() for l in js_src.splitlines() if l.strip().startswith("const esc"))
        ago_fn = grab("ago") if "function ago(" in js_src else "function ago(t){return String(t);}"
        js = esc_line + "\n" + ago_fn + "\n" + grab("directingHtml") + "\nconsole.log(JSON.stringify(directingHtml(" + json.dumps(d["bots"]["lead"], ensure_ascii=False) + ")));"
        with tempfile.TemporaryDirectory() as t:
            fp = os.path.join(t, "d.js"); open(fp, "w", encoding="utf-8").write(js)
            r = subprocess.run([node, fp], capture_output=True, text=True)
        try:
            h = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            h = ""; check("directingHtml 실행: " + r.stderr[:200], False)
        check("«지시 중» 칸 + 대상·이슈", "지시 중" in h and "wa" in h and "Issue545 A" in h, h[:300])
        check("캐스케이드 가지 링크(/fbot-map?tab=map&job=)", "/fbot-map?tab=map&amp;job=d6" in h or "/fbot-map?tab=map&job=d6" in h, h[:400])
        check("이슈맵 노드 링크(/issue-map?cwd=…#issue=Issue545) — cwd 있는 항목만", "#issue=Issue545" in h and "issue-map?cwd=" in h and h.count("#issue=") == 1, h[:500])
        # Issue818 — cwd 가 있어도 서버가 «열 수 없음»(issue_map False) 이라 하면 링크를 그리지 않는다
        _b2 = json.loads(json.dumps(d["bots"]["lead"]))
        for _x in _b2["directing"]:
            _x["issue_map"] = False
        js2 = esc_line + "\n" + ago_fn + "\n" + grab("directingHtml") + "\nconsole.log(JSON.stringify(directingHtml(" + json.dumps(_b2, ensure_ascii=False) + ")));"
        with tempfile.TemporaryDirectory() as t:
            fp = os.path.join(t, "d.js"); open(fp, "w", encoding="utf-8").write(js2)
            r2 = subprocess.run([node, fp], capture_output=True, text=True)
        try:
            h2 = json.loads(r2.stdout.strip().splitlines()[-1])
        except Exception:
            h2 = "#issue=ERR"
        check("Issue818: issue_map False 면 cwd 가 있어도 🗺 이슈맵 링크 없음", "#issue=" not in h2 and "지시 중" in h2, h2[:400])
    check("카드 본문이 «지시 중» 칸을 그린다", "directingHtml(b)" in js_src)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
