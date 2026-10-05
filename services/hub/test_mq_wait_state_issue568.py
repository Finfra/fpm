#!/usr/bin/env python3
# test_mq_wait_state_issue568.py — /mq 「🔨 작업 중 · 🙋 내 차례 · ⏳ 대기」 + [진행] 즉시 기동 (Issue568)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 큐 계약 정본은 prj3#Issue770(aoa-mq.md «공은 누구에게 있나»).
# 왜: 기다려야 하는 항목(113830)과 진행 중이어야 하는 항목(120452)이 같은 `in_progress` 주황 배지라
#   구분되지 않았고, [진행] 을 눌러도 대상 prj 에서 아무것도 시작되지 않았다(2026-09-28 사용자 지적).
#   prj3 가 상태(`waiting`·`needs_human`·`approved_ts`)와 helper(`wait`·`resume`·`need-done`·`target`·
#   `launch`)를 세웠고, 여기는 그것을 사람이 보고 누르는 자리다.
#
# 화면 판정은 서빙되는 /mq 인라인 스크립트(`_MQ_PAGE_HTML`)를 node vm 으로 그대로 실행한다
#   (test_mq_render_issue521.js 와 같은 방식이지만 hub 기동 없이 모듈 상수를 읽는다).
#
# 실행: python3 plugins/fpm-core/services/hub/test_mq_wait_state_issue568.py
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


FIX = [
    {"id": "20260928-000001-001", "status": "due", "_bucket": "open", "message": "평범한 예약", "due_ts": "2026-09-28T09:00:00"},
    {"id": "20260926-113830-001", "status": "waiting", "_bucket": "open", "message": "prj16 촬영 끝나면",
     "wait_for": "prj16 App Store 촬영 종료", "recheck_ts": "2026-09-29T09:00:00", "wait_from": "in_progress",
     "_wip_age_sec": 90000, "due_ts": "2026-09-26T09:00:00"},
    {"id": "20260928-120452-001", "status": "in_progress", "_bucket": "open", "message": "[컨펌] [H:스토어] prj16 제출",
     "approved_ts": "2026-09-28T12:05:00", "approved_by": "human:/mq", "_wip_age_sec": 3600,
     "needs_human": ["decide:스크린샷 6장 확정", "act:Connect 제출"], "due_ts": "2026-09-28T12:04:52"},
    {"id": "20260928-130000-001", "status": "in_progress", "_bucket": "open", "message": "작업 중인 일",
     "approved_ts": "2026-09-28T13:00:00", "_wip_age_sec": 600, "due_ts": "2026-09-28T13:00:00"},
    {"id": "20260928-120438-001", "status": "in_progress", "_bucket": "open", "message": "[컨펌] [H:배포] prj26 배포",
     "_wip_age_sec": 600, "due_ts": "2026-09-28T12:04:38"},
]


def _queue_js(html):
    m = re.search(r"<script>([\s\S]*?)</script>", html)
    js = m.group(1)
    cut = js.find("// ── prj3#Issue570")
    if cut > 0:
        js = js[:cut]
    return re.sub(r"^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$", "", js, flags=re.M)


SANDBOX = r"""
const vm=require('vm'); const fs=require('fs');
const js=fs.readFileSync(process.argv[2],'utf8'); const FIX=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const els={}; const el=()=>({textContent:'',innerHTML:'',value:'',checked:false,hidden:false,style:{},dataset:{},
  classList:{add(){},remove(){},toggle(){}},addEventListener(){},querySelectorAll:()=>[],closest:()=>null,appendChild(){},options:[{outerHTML:''}]});
const document={getElementById:id=>els[id]||(els[id]=el()),querySelectorAll:()=>[],querySelector:()=>el(),createElement:()=>el(),addEventListener(){},body:el()};
const ctx={document,window:{},console,URL,URLSearchParams,Date,Math,JSON,location:{href:'http://x/mq',search:''},
  history:{pushState(){},replaceState(){}},addEventListener(){},setInterval:()=>0,setTimeout:()=>0,clearTimeout(){},
  fetch:()=>Promise.reject(new Error('x')),EventSource:function(){},localStorage:{getItem:()=>null,setItem(){}}};
ctx.globalThis=ctx;
vm.runInNewContext(js+`
  pass=()=>true; DATA=${JSON.stringify(FIX)}; ACKED={}; SORT={k:"due_ts",asc:true}; render();
  globalThis.__OUT=document.getElementById("rows").innerHTML;`,ctx,{filename:'mq.js'});
console.log(JSON.stringify({rows:ctx.__OUT}));
"""


def main():
    print("[A] 화면 — 3배지·버튼·🙋 상단 고정 (서빙 스크립트를 node 로 실행)")
    node = shutil.which("node")
    if not node:
        check("node 필요", False)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            pj, pf, ps = (os.path.join(tmp, n) for n in ("q.js", "fix.json", "run.js"))
            open(pj, "w", encoding="utf-8").write(_queue_js(server._MQ_PAGE_HTML))
            open(pf, "w", encoding="utf-8").write(json.dumps(FIX, ensure_ascii=False))
            open(ps, "w", encoding="utf-8").write(SANDBOX)
            r = subprocess.run([node, ps, pj, pf], capture_output=True, text=True)
        try:
            rows_html = json.loads(r.stdout.strip().splitlines()[-1])["rows"]
        except Exception:
            rows_html = ""
            check("스크립트 실행: " + (r.stderr or "")[:300], False)
        rows = rows_html.split("<tr")[1:]
        row = lambda i: next((x for x in rows if i in x), "")
        W, H, P, C, D = (row(i) for i in ("113830", "120452", "130000-001", "120438", "000001"))
        check("🙋 내 차례 행이 정렬과 무관하게 맨 위", bool(rows) and "120452" in rows[0])
        check("⏳ 대기 배지 + 대기 조건 + 재확인 시각", "⏳ 대기" in W and "prj16 App Store 촬영 종료" in W and "09-29" in W)
        check("⏳ 대기에는 경과 배지를 세우지 않는다", 'class="wip' not in W)
        check("⏳ 대기 → [▶ 재개] (진행 버튼 없음)", "mqOp('20260926-113830-001','resume'" in W and "'start'" not in W)
        check("🙋 내 차례 배지", "🙋 내 차례" in H)
        check("🙋 사람 몫 항목마다 [승인] (index 0·1)",
              "mqOp('20260928-120452-001','need-done',this,0)" in H and "mqOp('20260928-120452-001','need-done',this,1)" in H
              and "스크린샷 6장 확정" in H and "Connect 제출" in H)
        check("🔨 작업 중 배지 + 경과 배지 유지", "🔨 작업 중" in P and 'class="wip' in P)
        check("🔨 작업 중 → [⏸ 대기로], [진행] 없음", "mqOp('20260928-130000-001','wait'" in P and "'start'" not in P)
        check("승인 기록 없는 [컨펌] in_progress 엔 [진행] 재노출", "act('20260928-120438-001','start'" in C)
        check("due 항목 [진행] 은 종전대로", "act('20260928-000001-001','start'" in D and "🔨" not in D and "⏳ 대기" not in D)

    print("\n[B] /mq-doc 정보 표 — 대기 조건·재확인·승인·대상 prj·사람 몫")
    md_w = server._mq_item_md(FIX[1], target={"target": "prj16", "cwd": "/x/fWarrange", "via": "message", "resolved": True})
    check("대기 조건 행", "대기 조건" in md_w and "prj16 App Store 촬영 종료" in md_w)
    check("재확인 행", "재확인" in md_w and "2026-09-29" in md_w)
    check("상태 표기 ⏳ 대기", "⏳ 대기" in md_w)
    check("대상 prj 행(cwd·판정 근거)", "대상 prj" in md_w and "prj16" in md_w and "/x/fWarrange" in md_w and "message" in md_w)
    md_h = server._mq_item_md(dict(FIX[2], needs_human_done=[{"item": "act:촬영", "ts": "2026-09-28T13:00:00", "by": "human:/mq"}]))
    check("승인 행(주체·시각)", "승인" in md_h and "human:/mq" in md_h and "12:05" in md_h)
    check("상태 표기 🙋 내 차례 + 사람 몫 목록·해소 이력",
          "🙋 내 차례" in md_h and "스크린샷 6장 확정" in md_h and "act:촬영" in md_h)
    md_d = server._mq_item_md(FIX[0])
    check("새 필드 없는 항목엔 새 행을 만들지 않는다", "대기 조건" not in md_d and "승인" not in md_d and "사람 몫" not in md_d)

    print("\n[C] /mq-progress 명령 조립 — 판정·전이는 prj3 helper 가 한다(얇은 래퍼)")
    f = getattr(server, "_mq_progress_cmd", None)
    if not f:
        check("_mq_progress_cmd 존재", False)
    else:
        H_ = "/x/aoa-mq-progress.sh"
        i = "20260926-113830-001"
        c, e = f(H_, {"op": "resume", "id": i})
        check("resume → resume <id> --via human:/mq", e is None and c[1:] == [H_, "resume", i, "--via", "human:/mq"])
        c, e = f(H_, {"op": "wait", "id": i, "for": "촬영 종료", "recheck": "+1d"})
        check("wait → wait <id> --for … --recheck +1d", e is None and c[1:] == [H_, "wait", i, "--for", "촬영 종료", "--recheck", "+1d"])
        # 번호가 아니라 항목 문자열로 승인한다 — helper --index 는 1 기반이고(0 기반 가정이 종단에서 실패),
        #   목록이 그 사이 바뀌면 번호는 다른 항목을 가리킨다. 화면에 보인 그 항목을 정확히 해소한다
        c, e = f(H_, {"op": "need-done", "id": i, "text": "act:Connect 제출"})
        check("need-done → need-done <id> --text <항목> --by human:/mq",
              e is None and c[1:] == [H_, "need-done", i, "--text", "act:Connect 제출", "--by", "human:/mq"])
        bad = [f(H_, b)[0] for b in ({"op": "launch", "id": i}, {"op": "resume", "id": "--x"},
                                      {"op": "wait", "id": i, "for": ""}, {"op": "wait", "id": i, "for": "x", "recheck": "tomorrow"},
                                      {"op": "need-done", "id": i, "index": 1}, ["x"], None)]
        check("허용 밖 op·id 형식·빈 조건·재확인 형식·항목 문자열 없음·비객체 → 거부", bad == [None] * 7)

    print("\n[D] [진행] 직후 즉시 기동 — 소비된 뒤에만, 거부 사유는 그대로 보여 준다")
    g = getattr(server, "_mq_launch_after_start", None)
    if not g:
        check("_mq_launch_after_start 존재", False)
    else:
        class R:  # subprocess.CompletedProcess 흉내
            def __init__(s, rc, out="", err=""): s.returncode, s.stdout, s.stderr = rc, out, err
        calls = []
        def run_ok(cmd, **kw): calls.append(cmd); return R(0, "launch: 20260928-120452-001 → /x/fWarrange (pid 4242)\n")
        def run_rej(cmd, **kw): calls.append(cmd); return R(3, "", "거부: 쿨다운 10분 안(재클릭)\n상세\n")
        o = g("20260928-120452-001", False, helper="/x/p.sh", run=run_ok)
        check("tick 이 아직 소비 못 했으면 기동하지 않는다(승인 전이 전)", o.get("launched") is False and not calls
              and "tick" in (o.get("reason") or ""))
        o = g("20260928-120452-001", True, helper="/x/p.sh", run=run_ok)
        check("소비됐으면 launch <id> 호출 + 결과 1줄", o.get("launched") is True and calls and calls[-1][-2:] == ["launch", "20260928-120452-001"]
              and "/x/fWarrange" in (o.get("detail") or ""))
        o = g("20260928-120452-001", True, helper="/x/p.sh", run=run_rej)
        check("rc 3 → 기동 안 됨 + stderr 첫 줄이 사유", o.get("launched") is False and o.get("rc") == 3
              and o.get("reason") == "거부: 쿨다운 10분 안(재클릭)")
        o = g("20260928-120452-001", True, helper="", run=run_ok)
        check("helper 부재 → 조용히 넘기지 않고 사유", o.get("launched") is False and "helper" in (o.get("reason") or ""))

    print("\n[E] 배선")
    src = open(server.__file__, encoding="utf-8").read()
    check("POST /mq-progress 라우트", 'parsed.path == "/mq-progress"' in src)
    check("start 소비 뒤 launch 결과를 응답에 싣는다", '"launch": ' in src and "_mq_launch_after_start(" in src)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
