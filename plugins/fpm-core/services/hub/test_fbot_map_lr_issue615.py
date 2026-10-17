#!/usr/bin/env python3
# test_fbot_map_lr_issue615.py — Issue615 회귀 테스트 (핀봇 조직도 그래프 가독성)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 사용자 지적 3건(2026-10-08)을 박제한다.
#   ① 그래프는 좌→우로 흐른다 — 깊이가 x, 형제는 y 로 쌓인다(`lrPos` 순수 함수)
#   ② 노드 라벨은 제목만 — 긴 작업문은 말줄임, 전문은 `title`(패널·툴팁)
#   ③ 칩에 구성 중 팀의 팀장핀봇 — `?root=<팀장>` 은 그 팀장의 하위 트리만 그린다
#
# 실행: python3 services/hub/test_fbot_map_lr_issue615.py
"""핀봇 조직도 LR·제목 라벨·팀장 칩(Issue615) 단위 테스트."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402
from test_fbot_map_issue402 import SCHEMA  # noqa: E402 — 같은 레지스트리 스키마를 쓴다

PASS = 0
FAIL = 0
LONG = ("Issue609 완료 검증(출고 단계 — QA 필수). 커밋 ec05d866·76aa538e·06667fb5. "
        "구현 명세 ①재설치 ②hub 재기동")


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def build_fixture(tmp):
    """총괄 CH → 본사 팀장 HL → prj 팀장 L7(재직)·L9(해고) → 워커.

    L7 은 W7 을 채용했고, 명부에 없는 GHOST7 에게 배분했다(하위 트리는 배분도 따라간다).
    HL 은 prj 가 없는 본사 팀장 — 프로젝트 칩 대상이 아니다.
    """
    aoa = os.path.join(tmp, "aoa")
    os.makedirs(aoa)
    now = int(time.time())
    con = sqlite3.connect(os.path.join(aoa, "registry.db"))
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("CH", "나래(총괄핀봇)", "chief", "working", "probation", None, "", None, "", None, None, now),
            ("HL", "팀장핀봇", "lead", "checkout", "active", None, "", None, "", "CH", None, now),
            ("L7", "cg 팀장핀봇", "lead", "checkin", "active", None, "", 7, "", "HL", None, now),
            ("L9", "old 팀장핀봇", "lead", "checkout", "terminated", None, "", 9, "", "HL", None, now),
            ("W7", LONG, "qa", "working", "probation", None, "", 7, "", "L7", None, now),
            ("W8", "본사 워커", "qa", "working", "probation", None, "", None, "", "HL", None, now),
            # L8 — 팀은 있으나 전원 퇴근·배분 없음 → 기본 보기에서 그릴 것이 없다(Issue615 후속)
            ("L8", "idle 팀장핀봇", "lead", "checkout", "active", None, "", 8, "", "HL", None, now),
            ("W8b", "idle 워커", "qa", "checkout", "probation", None, "", 8, "", "L8", None, now),
        ])
    con.executemany(
        "INSERT INTO job VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("d1", "fbot", "fbot_dispatch", "pending",
             json.dumps({"issue": "Issue7", "role": "qa", "worker_bot_id": "GHOST7"}),
             "", 0, "L7", None, None, now - 10),
            ("d2", "fbot", "fbot_dispatch", "done",
             json.dumps({"issue": "Issue8", "role": "qa", "worker_bot_id": "W8"}),
             "", 0, "HL", None, None, now - 20),
        ])
    con.commit()
    con.close()
    server.FBOT_AOA_DIR = aoa
    server.FBOT_ROOT = os.path.join(tmp, "root")
    # 조직(자리·구성 판정)은 실제 ~/.claude 설정을 읽는다 — 픽스처 밖 사실이 새지 않게 고정한다.
    #   구성 중 = prj7·prj8 (L8 은 구성 중이지만 전원 퇴근 → «그릴 것 없음» 판정 대상)
    _info = {"formed": True, "reason": "", "idle_days": 0, "disbanded_at": None}
    server._fbot_org_seats = lambda prj=None: {
        "seats": [], "available": True, "scopes": 2, "title": None,
        "scope_info": {None: _info, 7: _info, 8: _info}, "all_scopes": [], "stale_drops": []}


def _check_data():
    print("== ③ 팀장 칩 데이터 — leads · 하위 트리 필터 ==")
    with tempfile.TemporaryDirectory() as tmp:
        build_fixture(tmp)
        d = server._fbot_org_data()
        check("leads = prj 소속·비퇴역 팀장만(본사·해고 제외)", d.get("leads") == ["L7", "L8"])
        f = server._fbot_org_data("L7")
        ids = {n["bot_id"] for n in f["nodes"]}
        check("팀장 id 는 unknown_root 가 아니다", f["unknown_root"] is False)
        check("팀장 하위 트리 = 팀장 + 채용 + 배분 대상", ids == {"L7", "W7", "GHOST7"})
        check("하위 트리 채용 엣지", {(e["src"], e["dst"]) for e in f["hires"]} == {("L7", "W7")})
        check("하위 트리 배분 엣지", [(e["src"], e["dst"]) for e in f["dispatch"]] == [("L7", "GHOST7")])
        check("필터해도 leads 는 전수(칩 이동 길 유지)", f.get("leads") == ["L7", "L8"])
        check("팀장 보기의 그룹 머리는 팀장(총괄 id 로 떨어지지 않음)",
              {n["root"] for n in f["nodes"]} == {"L7"})
        w = server._fbot_org_data("W7")
        check("팀장 아닌 개체 id 는 종전대로 폴백", w["unknown_root"] is True)
        x = server._fbot_org_data("L9")
        check("해고된 팀장은 칩 대상이 아니다(폴백)", x["unknown_root"] is True)

        page = server.Handler._render_fbot_map(d, False, False, "map").decode("utf-8")
        check("그래프 탭에 팀장 칩(root=L7)", 'href="/fbot-map?tab=map&amp;root=L7"' in page)
        check("팀장 칩 라벨에 prj 번호", "prj7 · cg 팀장핀봇" in page)
        check("루트 칩(나래)은 유지", 'root=CH"' in page)
        print("\n== ③-2 그릴 것이 없는 팀장 칩은 비활성 (사용자 지적 2026-10-08) ==")
        check("그릴 봇 없는 팀장(L8)은 링크가 아니다", 'root=L8"' not in page)
        check("L8 칩은 아예 그리지 않는다(«전체» 뒤로는 활성만 — 사용자 지시)", "idle 팀장핀봇" not in page)
        pa = server.Handler._render_fbot_map(d, True, False, "map").decode("utf-8")
        check("«전체» 보기에선 퇴근 봇도 그리므로 L8 칩이 링크", 'href="/fbot-map?tab=map&amp;root=L8&amp;all=1"' in pa)
        p7 = server.Handler._render_fbot_map(server._fbot_org_data("L7"), False, False, "map").decode("utf-8")
        check("다른 팀장을 보는 중에도 판정은 전체 원장 기준(L8 비활성 유지)", 'root=L8"' not in p7)
        check("다른 팀장 보기에서 L7 자신은 on", 'class="fm-chip lead on"' in p7)
        pf = server.Handler._render_fbot_map(f, False, False, "map").decode("utf-8")
        check("팀장 보기에서도 루트 칩은 호칭(잘려나간 노드여도)", '>나래(총괄핀봇)</a>' in pf)
        check("팀장 보기에서도 다른 칩이 prjNone 으로 떨어지지 않는다", "prjNone" not in pf)
        check("선택된 팀장 칩이 on", re.search(r'class="fm-chip lead on" href="[^"]*root=L7"', pf) is not None)

        print("\n== ② 노드 라벨은 제목만 ==")
        els = server._fbot_graph_elements(d, kind="org")
        nd = {e["data"].get("bot"): e["data"] for e in els["nodes"] if e["data"].get("bot")}
        w7 = nd["W7"]
        check("긴 제목은 말줄임", len(w7["label"]) <= server._FBOT_NODE_LABEL_MAX
              and w7["label"].endswith("…"))
        check("전문은 title 로", w7["title"] == LONG)
        check("짧은 제목은 그대로", nd["L7"]["label"] == "cg 팀장핀봇")
        check("상세(sub)는 데이터에 남는다(패널용)", bool(w7["sub"]))
        print("\n== ② -2 아이콘·색이 빈 노드가 그래프를 죽이지 않는다 ==")
        check("아이콘 셀렉터는 값이 있을 때만([?icon]) — 빈 문자열이면 Cytoscape 파싱 예외로 그래프 생성 중단(실측)",
              "node[?icon]" in page and "'node[icon]'" not in page)
        check("색 셀렉터도 값이 있을 때만([?color])", "node[?color]" in page and "'node[color]'" not in page)
        check("노드 스타일 라벨은 data(label) 만 — sub·세션을 그리지 않는다",
              "e.data('sub')" not in page and "'label':'data(label)'" in page)


def _grab_fn(src, name):
    """페이지 스크립트에서 `function name(` 블록을 중괄호 균형으로 잘라낸다."""
    i = src.index("function " + name + "(")
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise ValueError(name)


JS_CHECKS = r"""
var P=0,F=0;function ck(n,c){if(c){P++;console.log('  PASS '+n);}else{F++;console.log('  FAIL '+n);}}
var N=[{id:'R',w:100,h:30},{id:'A',w:200,h:30},{id:'B',w:80,h:30},
       {id:'A1',w:120,h:30},{id:'A2',w:120,h:30},{id:'X',w:90,h:30},{id:'Y',w:90,h:30}];
var E=[{s:'R',t:'A',hire:1},{s:'R',t:'B',hire:1},{s:'A',t:'A1',hire:1},{s:'A',t:'A2',hire:0},
       {s:'B',t:'A1',hire:0},{s:'X',t:'Y',hire:0},{s:'Y',t:'X',hire:0}];
var p=lrPos(N,E);
ck('모든 노드에 좌표',N.every(function(n){return p[n.id]&&isFinite(p[n.id].x)&&isFinite(p[n.id].y);}));
ck('깊이는 x 로 증가(좌→우)',p.R.x<p.A.x&&p.A.x<p.A1.x&&p.A.x===p.B.x);
ck('형제는 같은 x 에 y 로 쌓인다',p.A1.x===p.A2.x&&p.A1.y!==p.A2.y);
ck('채용선이 배분선보다 부모로 우선(A1 은 A 밑)',p.A1.y<=p.A.y+1e3&&Math.abs(p.A1.x-p.A.x)>0&&p.A1.x>p.B.x);
ck('부모는 자식 구간 가운데',Math.abs(p.A.y-(p.A1.y+p.A2.y)/2)<1e-6);
ck('순환(X↔Y)에서도 종료하고 좌표가 선다',isFinite(p.X.y)&&isFinite(p.Y.y));
var ys=N.map(function(n){return p[n.id].y+':'+p[n.id].x;});
ck('겹치는 좌표 없음',new Set(ys).size===ys.length);
var gap=p.A.x-p.R.x;ck('열 간격은 노드 폭을 넘는다(겹침 방지)',gap>(100+200)/2);
console.log('__RESULT__ '+P+' '+F);
"""


def _check_js():
    print("\n== ① 좌→우 레이아웃 — lrPos 순수 함수 ==")
    with tempfile.TemporaryDirectory() as tmp:
        build_fixture(tmp)
        d = server._fbot_org_data()
        page = server.Handler._render_fbot_map(d, False, False, "map").decode("utf-8")
    check("breadthfirst(상→하) 를 쓰지 않는다", "breadthfirst" not in page)
    try:
        fn = _grab_fn(page, "lrPos")
    except ValueError:
        check("lrPos 함수 존재", False)
        return
    check("lrPos 함수 존재", True)
    node = shutil.which("node")
    if not node:
        print("  SKIP node 없음")
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "lr.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(fn + "\n" + JS_CHECKS)
        r = subprocess.run([node, path], capture_output=True, text=True)
    out = r.stdout.strip()
    print("\n".join(l for l in out.splitlines() if not l.startswith("__RESULT__")))
    if r.returncode != 0 or "__RESULT__" not in out:
        check("node 실행", False)
        print((r.stderr or "")[:800])
        return
    global PASS, FAIL
    p, f = out.rsplit("__RESULT__", 1)[1].split()
    PASS += int(p)
    FAIL += int(f)


def main():
    _check_data()
    _check_js()
    print(f"\n결과: PASS {PASS} · FAIL {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
