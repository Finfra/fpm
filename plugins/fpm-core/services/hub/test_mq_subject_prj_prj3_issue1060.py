#!/usr/bin/env python3
# test_mq_subject_prj_prj3_issue1060.py — /mq «프로젝트» 열이 항목의 주제 prj 를 보인다 (prj3#Issue1060_1)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 짝: prj3 `mcp/aoa-mq/test-aoa-mq-subject.sh`(enqueue 가 subject_prj 기록)
#   실발생 2026-10-10: 총괄 [컨펌] 2건(prj60 Issue51·prj7 Issue63_1)이 source=`fbot-chief-narae@.claude` 라
#   «프로젝트» 열에 `.claude` 로만 보였다 — 사람은 본문을 펼쳐야 무슨 prj 일인지 알았다.
#   계약: 서버가 `subject_prj` → `_subject_label`(`prjN · <폴더명>`)을 붙이고, srcCell 은 그것을 굵게,
#   source 의 프로젝트는 «보낸 곳» 줄로 내린다. subject 없는 항목은 종전 표시 그대로.
#
# 실행: python3 services/hub/test_mq_subject_prj_prj3_issue1060.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def js_func(src, name):
    i = src.find("function %s(" % name)
    if i < 0:
        return None
    j = src.find("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    return None


def run_node(code):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", code], capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else "ERR:" + r.stderr[-300:]


print("# 서버 — _subject_label")
tmp = tempfile.mkdtemp()
try:
    os.makedirs(os.path.join(tmp, "queue"))
    os.makedirs(os.path.join(tmp, "queue_done"))
    items = [
        {"id": "20261010-000001-001", "type": "scheduled", "status": "pending", "message": "[컨펌] [H:비용] prj60 Issue51 x",
         "source": "fbot-chief-narae@.claude", "target": "prj3", "subject_prj": "prj60"},
        {"id": "20261010-000002-001", "type": "scheduled", "status": "pending", "message": "x", "source": "claude@fSnippet"},
        {"id": "20261010-000003-001", "type": "scheduled", "status": "pending", "message": "x", "source": "c@a",
         "subject_prj": "prj99999"},
    ]
    for it in items:
        with open(os.path.join(tmp, "queue", it["id"] + ".json"), "w") as f:
            json.dump(it, f, ensure_ascii=False)
    old_dir = server.MQ_DIR
    old_entries = server._registered_project_entries
    server.MQ_DIR = tmp
    server._registered_project_entries = lambda: [("3", "/x/.claude"), ("60", "/x/_git/lecture-kit")]
    try:
        got = {it["id"]: it for it in server._mq_collect()["items"]}
    finally:
        server.MQ_DIR = old_dir
        server._registered_project_entries = old_entries
    a = got.get("20261010-000001-001", {})
    check("🔑 subject_prj=prj60 → _subject_label «prj60 · lecture-kit»", a.get("_subject_label") == "prj60 · lecture-kit")
    check("원 필드(subject_prj·source·target) 불변", a.get("subject_prj") == "prj60" and a.get("source") == "fbot-chief-narae@.claude"
          and a.get("target") == "prj3")
    check("subject 없는 항목은 _subject_label 없음", "_subject_label" not in got.get("20261010-000002-001", {"_subject_label": 1}))
    check("매핑 없는 prj 는 번호만", got.get("20261010-000003-001", {}).get("_subject_label") == "prj99999")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("# 화면 — srcCell(source, subject)")
mq = server._MQ_PAGE_HTML
check("호출 지점이 subject 를 넘긴다", "srcCell(x.source,x._subject_label)" in mq.replace(" ", ""))
fn = js_func(mq, "srcCell")
check("srcCell 존재", fn is not None)
if fn:
    esc = 'const esc=t=>String(t==null?"":t).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));'
    code = esc + fn + ";console.log(JSON.stringify([srcCell('fbot-chief-narae@.claude','prj60 · lecture-kit'),"\
        "srcCell('claude@fSnippet'),srcCell('claude@fSnippet',''),srcCell('',null)]))"
    o = run_node(code)
    if o is None or o.startswith("ERR"):
        check("srcCell node 실행 " + str(o), False)
    else:
        a, b, c, d = json.loads(o)
        bold = a.split("<b>", 1)[-1].split("</b>", 1)[0]   # title 속성(원문 source)은 제외 — 굵은 글자만
        check("🔑 subject 가 있으면 굵은 줄 = «prj60 · lecture-kit»", bold == "prj60 · lecture-kit")
        check("🔑 source 의 프로젝트(.claude)는 «보낸 곳» 줄로", ".claude" not in bold and "보낸 곳" in a and ".claude" in a
              and "fbot-chief-narae" in a)
        check("subject 없으면 종전 표시(굵게 fSnippet)", "<b>fSnippet</b>" in b and b == c)
        check("빈 값은 -", d == "-")

print(f"\n결과: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
