#!/usr/bin/env python3
# test_schedule_missed_issue578.py — hub /mq 스케줄 탭 발화 누락 표시 (Issue578, prj3#Issue775 후속)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: 스케줄 탭은 «다음 실행» 만 보여 줘, 예정 시각에 **안 돈 것**이 화면에 드러나지 않았다. prj3#Issue775 가
#   `schedule.sh status --json` 에 누락 판정(`events[].missed` = [{slot, cause: up|off}] · 최상위 `missed`)을
#   더했고, 여기는 그것을 렌더한다. `up`(켜져 있었는데 안 돔 = 결함)과 `off`(꺼져서 못 돔)를 가른다.
#
# 판정은 서빙되는 /mq 페이지 스크립트 전체를 node vm 으로 실행하고 `renderSchedule()` 결과를 본다.
# 실행: python3 plugins/fpm-core/services/hub/test_schedule_missed_issue578.py
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


def ev(name, missed, jobs):
    return {"name": name, "type": "calendar", "spec": "", "unit": "", "weekday": None, "day": None, "month": None,
            "loaded": True, "runs": 3, "next": "2026-09-29 07:03", "source": "user", "jobs": jobs, "missed": missed}


SDATA = {
    "ok": True, "error": None, "yml": "/x/schedule.yml", "user_yml": "/x/user.yml", "ledger": "/x/l",
    "missed": {"hours": 48, "expected": 6, "fired": 3},
    "events": [ev("morning", [{"slot": "2026-09-27T07:03:00", "cause": "up"}, {"slot": "2026-09-28T07:03:00", "cause": "off"}], ["jobA"]),
               ev("night", [{"slot": "2026-09-27T23:00:00", "cause": "off"}], ["jobB"]),
               ev("noon", [], ["jobC"])],
    "jobs": [{"name": n, "source": "user", "desc": "", "paused": False, "last": None} for n in ("jobA", "jobB", "jobC")],
    "bindings": [{"job": "jobA", "event": "morning", "source": "user"}, {"job": "jobB", "event": "night", "source": "user"},
                 {"job": "jobC", "event": "noon", "source": "user"}],
    "runs": [],
}

RUN = r"""
const vm=require('vm'); const fs=require('fs');
const js=fs.readFileSync(process.argv[2],'utf8'); const SD=fs.readFileSync(process.argv[3],'utf8');
const els={}; const el=()=>({textContent:'',innerHTML:'',value:'',checked:false,hidden:false,style:{},dataset:{},className:'',
  classList:{add(){},remove(){},toggle(){},contains:()=>false},addEventListener(){},querySelectorAll:()=>[],querySelector:()=>null,
  closest:()=>null,appendChild(){},setAttribute(){},getAttribute:()=>null,options:[{outerHTML:''}]});
const document={getElementById:id=>els[id]||(els[id]=el()),querySelectorAll:()=>[],querySelector:()=>el(),createElement:()=>el(),
  addEventListener(){},body:el(),documentElement:el()};
const ctx={document,window:{addEventListener(){}},console:{log(){},warn(){},error(){}},URL,URLSearchParams,Date,Math,JSON,
  location:{href:'http://x/mq',search:'',hash:''},history:{pushState(){},replaceState(){}},addEventListener(){},
  setInterval:()=>0,setTimeout:()=>0,clearTimeout(){},clearInterval(){},navigator:{clipboard:{writeText:async()=>{}}},
  fetch:()=>new Promise(()=>{}),EventSource:function(){return {addEventListener(){},close(){}}},
  localStorage:{getItem:()=>null,setItem(){}},sessionStorage:{getItem:()=>null,setItem(){}},matchMedia:()=>({matches:false,addEventListener(){}})};
ctx.globalThis=ctx; ctx.self=ctx;
try{ vm.runInNewContext(js+`
;SDATA=${SD}; SSYS=false; renderSchedule();
globalThis.__OUT={body:document.getElementById("s-body").innerHTML, sub:document.getElementById("s-sub").innerHTML};`,ctx,{filename:'mq.js'}); }
catch(e){ console.error("RUNERR "+e.message); process.exit(3); }
process.stdout.write(JSON.stringify(ctx.__OUT));
"""


def main():
    node = shutil.which("node")
    if not node:
        check("node 필요", False); print(f"\n{PASS} passed, {FAIL} failed"); return 1
    js = "\n;\n".join(re.findall(r"<script>([\s\S]*?)</script>", server._MQ_PAGE_HTML))
    with tempfile.TemporaryDirectory() as tmp:
        pj, ps, pr = (os.path.join(tmp, n) for n in ("mq.js", "sd.json", "run.js"))
        open(pj, "w", encoding="utf-8").write(js)
        open(ps, "w", encoding="utf-8").write(json.dumps(SDATA, ensure_ascii=False))
        open(pr, "w", encoding="utf-8").write(RUN)
        r = subprocess.run([node, pr, pj, ps], capture_output=True, text=True)
    try:
        o = json.loads(r.stdout)
    except Exception:
        check("renderSchedule 실행: " + (r.stderr or "")[:300], False)
        print(f"\n{PASS} passed, {FAIL} failed"); return 1
    body, sub = o["body"], o["sub"]
    rows = body.split("<tr")
    row = lambda job: next((x for x in rows if f">{job}</a>" in x), "")
    A, B, C = row("jobA"), row("jobB"), row("jobC")
    print("[행 배지]")
    check("가동 중 누락이 있는 행 = ⚠ 빨강 «누락 2»", "⚠ 누락 2" in A and "bad" in A)
    check("배지 title 에 슬롯·원인(가동 중·꺼짐)", "2026-09-27 07:03" in A and "가동 중" in A and "꺼짐" in A)
    check("꺼짐 누락만 있는 행 = 회색 «꺼짐 누락 1»(⚠ 아님)", "꺼짐 누락 1" in B and "⚠" not in B)
    check("누락 없는 행엔 배지 없음", "누락" not in C)
    print("[요약]")
    check("부제에 최근 48h 기대 6 · 발화 3", "48h" in sub and "기대 6" in sub and "발화 3" in sub)
    check("부제에 누락 합계와 원인 내역(가동 중 1 · 꺼짐 2)", "누락 3" in sub and "가동 중 1" in sub and "꺼짐 2" in sub)
    print("[이벤트 상세표]")
    check("이벤트 표에도 같은 배지", body.count("⚠ 누락 2") >= 2)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
