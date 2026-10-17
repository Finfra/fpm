#!/usr/bin/env python3
# test_mq_class_issue624.py — /mq 부제 «할 일 · 예약 · 대기» 분리 + «➕ 병합 N» 배지 (Issue624)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 분류 규칙 정본은 prj3#Issue1046
#   (`~/.claude/_doc_arch/aoa-mq.md` «할 일 / 예약 / 대기»).
# 왜: 부제가 `미종결 N` 한 숫자라 기한 전 예약 리마인더까지 «쌓인 일» 로 보였다
#   (2026-10-09 실측 13건 중 지금 할 일 1건). prj3 가 넛지·MCP list 를 셋으로 나눴으니 화면도 같은 규칙을 따른다.
#
# 계약 — hub 는 분류를 **다시 쓰지 않는다**: `_mq_collect` 가 prj3 `mcp/aoa-mq/server.py` 의
#   `_mq_class` 를 로드해 항목마다 `_class` 를 싣고, 화면은 받아 쓰기만 한다(Issue504 경과 계산과 같은 원칙).
#
# 실행: python3 plugins/fpm-core/services/hub/test_mq_class_issue624.py
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


PAST, FUTURE = "2020-01-01T09:00:00", "2099-01-01T09:00:00"
OPEN = [
    {"id": "20261009-000001-001", "status": "due", "due_ts": PAST, "message": "기한 도래"},
    {"id": "20261009-000002-001", "status": "pending", "due_ts": PAST, "message": "기한 지난 pending"},
    {"id": "20261009-000003-001", "status": "pending", "due_ts": FUTURE, "message": "기한 전 pending"},
    {"id": "20261009-000004-001", "status": "watching", "due_ts": PAST, "message": "완료 감시"},
    {"id": "20261009-000005-001", "status": "waiting", "due_ts": PAST, "message": "대기"},
    {"id": "20261009-000006-001", "status": "in_progress", "due_ts": PAST, "message": "작업 중",
     "group": "appstore-review", "merged": [
         {"ts": "2026-10-09T20:18:48", "source": "claude@fQRGen", "message": "fQRGen 심사 확인", "due": PAST},
         {"ts": "2026-10-09T20:18:49", "source": "claude@fBoard", "message": "fBoard 심사 확인", "due": PAST}]},
]
DONE = [{"id": "20261008-000001-001", "status": "confirmed", "due_ts": PAST, "message": "종결분"}]
WANT = {"20261009-000001-001": "action", "20261009-000002-001": "action", "20261009-000003-001": "reserved",
        "20261009-000004-001": "reserved", "20261009-000005-001": "wait", "20261009-000006-001": "action"}


def _queue_js(html):
    js = re.search(r"<script>([\s\S]*?)</script>", html).group(1)
    cut = js.find("// ── prj3#Issue570")
    if cut > 0:
        js = js[:cut]
    return re.sub(r"^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$", "", js, flags=re.M)


# load() 를 그대로 돌려 부제를 얻고, render() 로 내용 열을 얻는다. fetch 는 수집 결과를 돌려주는 스텁.
SANDBOX = r"""
const vm=require('vm'); const fs=require('fs');
const js=fs.readFileSync(process.argv[2],'utf8'); const D=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const els={}; const el=()=>({textContent:'',innerHTML:'',value:'',checked:false,hidden:false,style:{},dataset:{},
  classList:{add(){},remove(){},toggle(){}},addEventListener(){},querySelectorAll:()=>[],closest:()=>null,appendChild(){},options:[{outerHTML:''}]});
const document={getElementById:id=>els[id]||(els[id]=el()),querySelectorAll:()=>[],querySelector:()=>el(),createElement:()=>el(),addEventListener(){},body:el()};
const ctx={document,window:{},console,URL,URLSearchParams,Date,Math,JSON,location:{href:'http://x/mq',search:''},
  history:{pushState(){},replaceState(){}},addEventListener(){},setInterval:()=>0,setTimeout:()=>0,clearTimeout(){},
  fetch:()=>Promise.resolve({json:()=>Promise.resolve(D)}),EventSource:function(){},localStorage:{getItem:()=>null,setItem(){}}};
ctx.globalThis=ctx;
vm.runInNewContext(js+`
  pass=()=>true; ACKED={}; SORT={k:"due_ts",asc:true};
  load().then(()=>{ globalThis.__SUB=document.getElementById("sub").textContent;
                    globalThis.__ROWS=document.getElementById("rows").innerHTML; });`,ctx,{filename:'mq.js'});
setTimeout(()=>console.log(JSON.stringify({sub:ctx.__SUB,rows:ctx.__ROWS})),50);
"""


def main():
    tmp = tempfile.mkdtemp()
    try:
        for sub, items in (("queue", OPEN), ("queue_done", DONE)):
            os.makedirs(os.path.join(tmp, sub))
            for it in items:
                with open(os.path.join(tmp, sub, it["id"] + ".json"), "w", encoding="utf-8") as fh:
                    json.dump(it, fh, ensure_ascii=False)
        server.MQ_DIR = tmp
        d = server._mq_collect()

        print("[A] 수집 — 항목별 _class · 집계 (prj3 _mq_class 규칙)")
        got = {it["id"]: it.get("_class") for it in d["items"] if it["_bucket"] == "queue"}
        for mid, want in WANT.items():
            check(f"{OPEN[[o['id'] for o in OPEN].index(mid)]['message']} → {want}", got.get(mid) == want)
        check("집계 action 3 · reserved 2 · wait 1",
              (d.get("action_count"), d.get("reserved_count"), d.get("wait_count")) == (3, 2, 1))
        check("종결분엔 _class 를 싣지 않는다",
              all("_class" not in it for it in d["items"] if it["_bucket"] == "done"))
        check("open_count·done_count 는 종전대로", (d["open_count"], d["done_count"]) == (6, 1))

        print("\n[B] 판정 단일 지점 — hub 는 prj3 분류 함수를 로드해 쓴다(세 번째 해석 금지)")
        fn = getattr(server, "_mq_classifier", lambda: None)()
        check("_mq_classifier() 가 함수를 돌려준다", callable(fn))
        check("그 함수는 prj3 aoa-mq server.py 소속",
              callable(fn) and fn.__code__.co_filename.endswith(os.path.join("mcp", "aoa-mq", "server.py")))
        src = open(server.__file__, encoding="utf-8").read()
        check("hub 소스에 분류 규칙 사본(\"reserved\" 반환) 없음", 'return "reserved"' not in src)

        print("\n[C] 분류 함수를 못 찾으면 조용한 0 대신 오류로 올린다")
        orig = server._MQ_CLASS_PATHS
        server._MQ_CLASS_PATHS = (os.path.join(tmp, "nope.py"),)
        server._MQ_CLASS_MOD.clear()
        d2 = server._mq_collect()
        server._MQ_CLASS_PATHS = orig
        server._MQ_CLASS_MOD.clear()
        check("집계 None (0 아님)", d2.get("action_count") is None)
        check("error 에 분류 함수 부재 사유", "분류" in (d2.get("error") or "") and d2.get("ok") is False)

        print("\n[D] 화면 — 부제 셋 분리 · ➕ 병합 N 배지 (서빙 스크립트를 node 로 실행)")
        node = shutil.which("node")
        if not node:
            check("node 필요", False)
        else:
            pj, pf, ps = (os.path.join(tmp, n) for n in ("q.js", "d.json", "run.js"))
            open(pj, "w", encoding="utf-8").write(_queue_js(server._MQ_PAGE_HTML))
            open(pf, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
            open(ps, "w", encoding="utf-8").write(SANDBOX)
            r = subprocess.run([node, ps, pj, pf], capture_output=True, text=True)
            try:
                out = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                out = {}
                check("스크립트 실행: " + (r.stderr or "")[:300], False)
            sub = out.get("sub") or ""
            check(f"부제 «할 일 3 · 예약 2 · 대기 1 · 종결(최근) 1» — 실제: {sub!r}",
                  sub.startswith("할 일 3 · 예약 2 · 대기 1 · 종결(최근) 1"))
            rows = (out.get("rows") or "").split("<tr")[1:]
            row = lambda i: next((x for x in rows if i in x), "")
            m, p = row("20261009-000006-001"), row("20261009-000001-001")
            check("병합 항목에 «➕ 병합 2» 배지", "➕ 병합 2" in m)
            check("배지 title 에 묶음·병합 출처", "appstore-review" in m and "claude@fQRGen" in m)
            check("병합 없는 항목엔 배지 없음", bool(p) and "➕ 병합" not in p)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
