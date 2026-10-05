#!/usr/bin/env python3
# test_mq_shell_tab_issue602.py — Issue602 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
#   render_tab_mode: hub-internal 이면 hub 가 여는 화면은 /hub-shell 내부 탭에 실려야 한다.
#   📮 Aoa-mq 만 `target=_blank` 고정이라 OS 새 탭으로 빠졌다(형제 👥 fBot·🗺️ Map 은 내부 탭).
#   이 테스트가 지키는 것은 셋이다:
#     ① hub 헤더 `#btn-mq` 가 `fpmOpenInShell` 로 셸 내부 탭 라우팅을 받는다
#     ② /mq 페이지에 `window.open(…,"_blank")` 직접 호출이 남지 않는다 — 전부 `openView` 경유
#     ③ `openView` 는 임베드면 부모 셸로 `fpm-open-tab`, 비임베드면 새 탭 (node 로 실행 검증)
#        + 임베드 시 same-origin `a[target=_blank]` 클릭도 셸 탭으로 보낸다
#
# 실행: python3 plugins/fpm-core/services/hub/test_mq_shell_tab_issue602.py
"""server.py HUB_HTML `#btn-mq` · _MQ_PAGE_HTML `openView` 단위 테스트."""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"\n       {detail}" if detail else ""))


# ① hub 헤더 버튼
m = re.search(r'<a[^>]*id="btn-mq"[^>]*>', server.HUB_HTML)
check("① #btn-mq 존재", bool(m))
tag = m.group(0) if m else ""
check("① #btn-mq → fpmOpenInShell 라우팅", "fpmOpenInShell(event,this)" in tag, tag)
check("① #btn-mq data-title 부여(셸 탭 제목)", 'data-title="' in tag, tag)
check("① 비임베드 폴백 — target=_blank 유지", 'target="_blank"' in tag, tag)

# ② /mq 페이지 — _blank 직접 호출 잔존 0
page = server._MQ_PAGE_HTML
# 줄 단위 — `window.open(mqDocUrl(id),"_blank")` 처럼 인자에 괄호가 중첩돼도 놓치지 않는다
body_wo_helper = re.sub(r"function openView\(.*?\n}\n", "", page, flags=re.S)
leftover = [ln.strip() for ln in body_wo_helper.splitlines()
            if "window.open(" in ln and '"_blank"' in ln
            and not ln.lstrip().startswith("//")]   # 금지를 적은 주석 줄은 제외
check("② openView 정의", "function openView(" in page)
check("② window.open(_blank) 직접 호출 0건", not leftover, str(leftover))

# ③ openView 실행 검증 (node)
fm = re.search(r"function openView\(.*?\n}\n", page, flags=re.S)
cm = re.search(r"// Issue602-click\n(.*?)\n// /Issue602-click\n", page, flags=re.S)
check("③ 클릭 위임 블록 존재", bool(cm))
node = shutil.which("node") or os.path.expanduser("~/.nvm/versions/node/v24.18.0/bin/node")
if fm and cm and os.path.exists(node):
    js = r"""
const out={posted:[],opened:[]};
function mk(embedded){
  const listeners={};
  const self={};
  const w={
    location:{href:"http://h:9876/mq",origin:"http://h:9876"},
    parent:{postMessage:(m,o)=>out.posted.push(m)},
    open:(u,t)=>out.opened.push([u,t]),
  };
  w.self=self; w.top=embedded?{}:self;
  const doc={addEventListener:(ev,fn,cap)=>{listeners[ev]=fn;}};
  return {w,doc,listeners};
}
function run(embedded){
  const {w,doc,listeners}=mk(embedded);
  const f=new Function("window","document","URL",SRC+"\nreturn {openView, listeners:null};");
  const api=f(w,doc,URL);
  return {api,listeners,w};
}
const SRC=FN+"\n"+CLICK;
const r={};
// 임베드
let e=run(true);
e.api.openView("/mq-doc?id=1","문서");
r.emb_post=out.posted.slice(); r.emb_open=out.opened.slice();
out.posted.length=0; out.opened.length=0;
// 임베드 + same-origin a[target=_blank] 클릭
let prevented=false;
const a={getAttribute:k=>({href:"/sched-result?job=x",target:"_blank",title:"결과"})[k]||null,
         textContent:"📄 결과", href:"http://h:9876/sched-result?job=x"};
const ev={button:0,metaKey:false,ctrlKey:false,shiftKey:false,altKey:false,
          target:{closest:s=>a},preventDefault:()=>{prevented=true;}};
e.listeners.click(ev);
r.click_post=out.posted.slice(); r.click_prevented=prevented;
out.posted.length=0;
// 임베드 + 외부 origin 링크 → 가로채지 않음
prevented=false;
const ax={getAttribute:k=>({href:"https://github.com/x",target:"_blank"})[k]||null,
          textContent:"gh", href:"https://github.com/x"};
e.listeners.click({button:0,target:{closest:s=>ax},preventDefault:()=>{prevented=true;}});
r.ext_post=out.posted.slice(); r.ext_prevented=prevented;
out.posted.length=0;
// 비임베드
let n=run(false);
n.api.openView("/mq-doc?id=2","문서2");
r.std_post=out.posted.slice(); r.std_open=out.opened.slice();
console.log(JSON.stringify(r));
"""
    js = "const FN=" + json.dumps(fm.group(0)) + ";\nconst CLICK=" + json.dumps(cm.group(1)) + ";\n" + js
    p = subprocess.run([node, "-e", js], capture_output=True, text=True)
    if p.returncode != 0:
        check("③ node 실행", False, p.stderr[-800:])
    else:
        r = json.loads(p.stdout.strip().splitlines()[-1])
        ep = r["emb_post"]
        check("③ 임베드 openView → fpm-open-tab postMessage",
              len(ep) == 1 and ep[0].get("type") == "fpm-open-tab"
              and ep[0].get("view_url") == "/mq-doc?id=1" and ep[0].get("title") == "문서", str(r))
        check("③ 임베드 openView → 새 탭 미생성", r["emb_open"] == [], str(r))
        cp = r["click_post"]
        check("③ 임베드 same-origin _blank 클릭 → 셸 탭",
              r["click_prevented"] and len(cp) == 1
              and cp[0].get("view_url") == "/sched-result?job=x", str(r))
        check("③ 외부 origin 링크는 가로채지 않음",
              (not r["ext_prevented"]) and r["ext_post"] == [], str(r))
        check("③ 비임베드 openView → 새 탭",
              r["std_post"] == [] and r["std_open"] == [["/mq-doc?id=2", "_blank"]], str(r))
else:
    check("③ openView·클릭 블록 추출 + node", False,
          f"fn={bool(fm)} click={bool(cm)} node={os.path.exists(node)}")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
