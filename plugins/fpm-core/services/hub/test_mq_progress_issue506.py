#!/usr/bin/env python3
# test_mq_progress_issue506.py — Issue506 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `/mq` 표의 **진행 3종 표시**를 검증한다.
#   스키마 쪽 절반은 prj3#Issue643(`claimed_by`·`progress`·`result` + 짝 시각)이고,
#   이 테스트가 지키는 것은 셋이다:
#     ① hub 는 세 필드를 **해석하지 않고 통과**시킨다 — 화이트리스트를 세우면 prj3 가
#        필드를 더할 때마다 화면이 조용히 떨어뜨린다(정본은 큐 파일)
#     ② 필드가 **없으면 아무것도 렌더하지 않는다** — 빈 칸·`-` 는 "기록 없음" 과
#        "기록했는데 비었음" 을 한 모양으로 뭉갠다
#     ③ 결과의 경로는 **열 수 있을 때만** 링크다 — 상대경로·`~/`·비 md 는 hub 가 열어
#        줄 라우트가 없으므로 `<code>` 로 드러내기만 한다(죽은 링크 금지)
#
# 실행: python3 plugins/fpm-core/services/hub/test_mq_progress_issue506.py
"""server.py `_mq_collect` 통과 계약 + /mq 진행 3종 렌더러(JS) 단위 테스트."""
import glob
import io
import json
import os
import subprocess
import sys
import tempfile

# ⚠️ MQ_DIR 은 **import 시점**에 env 로 굳는다 — server import 보다 먼저 세워야 한다.
SANDBOX = tempfile.mkdtemp(prefix="mq506-")
os.environ["AOA_MQ_DIR"] = SANDBOX
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0
SKIP = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


QUEUE = os.path.join(SANDBOX, "queue")
DONE = os.path.join(SANDBOX, "queue_done")
os.makedirs(QUEUE)
os.makedirs(DONE)


def put(d, name, item):
    with io.open(os.path.join(d, name + ".json"), "w", encoding="utf-8") as fh:
        json.dump(item, fh, ensure_ascii=False)


# ── ① 통과 계약 — hub 는 진행 3종을 해석하지 않는다 ────────────────────────
WITH = {
    "id": "with", "status": "in_progress", "message": "본문",
    "claimed_by": "session:8dd7aa16-6658-4490-8018-f2768910b55c",
    "claimed_ts": "2026-09-19T19:50:37",
    "progress": "draft 압축 반영 완료 · 사람 전결 대기",
    "progress_ts": "2026-09-19T21:24:32",
    "result": "압축 1126→771자. 상세 /Users/x/_doc_work/htm/hub_htm_a.md",
    "result_ts": "2026-09-19T21:26:17",
}
put(QUEUE, "20260919-000001-001", WITH)
put(QUEUE, "20260919-000002-001", {"id": "bare", "status": "due", "message": "옛 항목"})
put(QUEUE, "20260919-000003-001", {"id": "future", "status": "due", "message": "x",
                                   "blocked_by": "prj3#Issue999"})
put(DONE, "20260919-000004-001", {"id": "closed", "status": "confirmed", "message": "끝",
                                  "result": "끝났다", "result_ts": "2026-09-19T22:00:00",
                                  "claimed_by": "bot:fbot-lead-pm"})

out = server._mq_collect()
by_id = {it["id"]: it for it in out["items"]}
check("수집 자체는 성공", out["ok"] and out["error"] is None)
check("진행 3종이 원문 그대로 실린다",
      all(by_id["with"].get(k) == WITH[k] for k in
          ("claimed_by", "claimed_ts", "progress", "progress_ts", "result", "result_ts")))
check("필드 없는 기존 항목에 키를 만들어 넣지 않는다 (마이그레이션 없음)",
      not any(k in by_id["bare"] for k in ("claimed_by", "progress", "result")))
check("prj3 가 나중에 더할 필드도 통과한다 (화이트리스트 없음)",
      by_id["future"].get("blocked_by") == "prj3#Issue999")
check("종결분의 result 도 실린다 (되짚기가 Issue643 의 절반)",
      by_id["closed"].get("result") == "끝났다"
      and by_id["closed"]["_bucket"] == "done")

# ── ② 화면 배선 — 서버가 실어도 JS 가 안 쓰면 아무 데도 안 보인다 ──────────
page = server._MQ_PAGE_HTML
check("내용 열 렌더러 존재", "function msgCell(x)" in page)
check("내용 열에 배선됨", "${msgCell(x)}" in page)
check("종전 평문 배선이 남아 있지 않다", "esc(x.message||'')}</td>" not in page)
check("주체 축약기 존재", "function actorShort(v)" in page)
check("결과 링크화 존재", "function resultHtml(s)" in page)
check("진행 3종 CSS 존재", "td.msg .prog{" in page)
check("검색이 보이는 글자를 덮는다", "x.claimed_by,x.progress,x.result" in page)

# ── ③ JS 실동작 — 정적 grep 은 "있다" 만 말하고 "맞다" 는 말하지 않는다 ────
NODE = None
for cand in ["node"] + sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")),
                              reverse=True):
    try:
        subprocess.run([cand, "--version"], capture_output=True, check=True)
        NODE = cand
        break
    except Exception:
        continue

# 헬퍼 구간만 떼어 낸다 — 같은 <script> 의 나머지는 DOM 을 건드려 node 에서 죽는다.
BEG = "const esc=t=>String"
END = "// 액션 → 사람이 읽는 이름."
src = page[page.index(BEG):page.index(END)]
check("발췌 구간이 DOM 을 건드리지 않는다 (node 실행 전제)",
      "document." not in src and "$(" not in src)

# Issue565: `<div class="mbody" …>본문</div>` 를 벗긴다. 래퍼가 없으면 매치 실패로 원문 그대로 남아 eq 가 깨진다
UNWRAP = '(%s).replace(/^<div class="mbody"[^>]*>([\\s\\S]*?)<\\/div>/,"$1")'
CASES = [
    # (이름, 식, 기대, 비교모드)  비교모드: eq | has | hasnot
    ("세션은 앞 8자로 줄인다",
     'actorShort("session:8dd7aa16-6658-4490-8018-f2768910b55c")', "8dd7aa16", "eq"),
    ("봇은 bot_id 그대로", 'actorShort("bot:fbot-lead-pm")', "fbot-lead-pm", "eq"),
    ("빈 값은 빈 값", 'actorShort("")', "", "eq"),
    ("모르는 꼴은 건드리지 않는다", 'actorShort("누군가")', "누군가", "eq"),
    ("uuid 아닌 짧은 세션 id 는 자르지 않는다 (실큐 session:sreMsa-prj61)",
     'actorShort("session:sreMsa-prj61")', "sreMsa-prj61", "eq"),
    ("병리적 장문만 마지막 안전판에서 줄인다",
     'actorShort("bot:"+"가".repeat(40))', "가" * 24 + "…", "eq"),

    # Issue565: 본문은 문서 뷰 진입점 `.mbody` 로 감싼다 — 래퍼를 벗긴(UNWRAP) 나머지가 본문뿐이어야 한다
    ("필드가 없으면 본문뿐이다", UNWRAP % 'msgCell({message:"본문"})', "본문", "eq"),
    ("빈 문자열도 줄을 만들지 않는다",
     UNWRAP % 'msgCell({message:"본문",progress:"",result:"   ",claimed_by:null})', "본문", "eq"),
    ("집은 주체 줄이 선다",
     'msgCell({message:"m",claimed_by:"session:8dd7aa16-6658-4490-8018-f2768910b55c",claimed_ts:"2026-09-19T23:45:40"})',
     "집은 주체", "has"),
    ("집은 주체는 축약형이 보인다",
     'msgCell({message:"m",claimed_by:"session:8dd7aa16-6658-4490-8018-f2768910b55c"})', ">8dd7aa16<", "has"),
    ("기록 시각은 tooltip 으로만 (줄을 늘리지 않는다)",
     'msgCell({message:"m",progress:"p",progress_ts:"2026-09-19T21:24:32"})',
     'title="진행 · 기록 2026-09-19 21:24:32"', "has"),
    ("세 줄이 함께 선다",
     'msgCell({message:"m",claimed_by:"bot:b",progress:"p",result:"r"}).match(/class="prog"/g).length',
     3, "eq"),
    ("긴 진행 메모를 화면이 자르지 않는다 (자르는 곳은 prj3 helper 하나)",
     'msgCell({message:"m",progress:"가".repeat(400)}).includes("가".repeat(400))', True, "eq"),

    ("본문 HTML 은 이스케이프된다", UNWRAP % 'msgCell({message:"<b>x</b>"})', "&lt;b&gt;x&lt;/b&gt;", "eq"),
    ("진행 메모의 태그도 이스케이프된다",
     'msgCell({message:"m",progress:"<img src=x onerror=alert(1)>"})', "<img", "hasnot"),
    ("주체 문자열의 따옴표가 title 을 깨지 않는다",
     'msgCell({message:"m",claimed_by:"bot:a\\" onmouseover=\\"x"})', ' onmouseover="x"', "hasnot"),

    ("htm 산출 규약 md 는 hub 라우트로 링크한다",
     'resultHtml("상세 /Users/x/_doc_work/htm/hub_htm_a.md 참조")',
     'href="/md-doc?path=%2FUsers%2Fx%2F_doc_work%2Fhtm%2Fhub_htm_a.md"', "has"),
    ("링크 글자는 파일명, 전체 경로는 tooltip",
     'resultHtml("/Users/x/_doc_work/htm/hub_htm_a.md")',
     '>hub_htm_a.md</a>', "has"),
    ("아카이브(z_done/htm)도 같은 규약이다",
     'resultHtml("/Users/x/_doc_work/z_done/htm/hub_htm_a.md")', "<a ", "has"),
    ("규약 밖 md 는 링크하지 않는다 (/md-doc 가 403 을 준다)",
     'resultHtml("/Users/x/_doc_work/report/2026.09.19.md")', "<a ", "hasnot"),
    ("규약 밖 md 도 경로로는 드러낸다",
     'resultHtml("/Users/x/_doc_work/report/2026.09.19.md")', "<code", "has"),
    ("파일명 규약(hub_htm_*)을 어기면 링크하지 않는다",
     'resultHtml("/Users/x/_doc_work/htm/note.md")', "<a ", "hasnot"),
    ("`~/` 는 링크하지 않는다 (hub 가 ~ 를 풀지 않는다)",
     'resultHtml("~/x/_doc_work/htm/hub_htm_a.md")', "<a ", "hasnot"),
    ("`~/` 는 경로로 드러낸다", 'resultHtml("~/x/y.md")', "<code", "has"),
    ("md 아닌 절대경로는 링크하지 않는다",
     'resultHtml("/Users/x/run.sh")', "<a ", "hasnot"),
    ("상대경로는 손대지 않는다 (가운데 `/` 를 경로 시작으로 집지 않는다)",
     'resultHtml("mcp/aoa-mq/tick.sh 를 고쳤다")', "<code", "hasnot"),
    ("상대경로는 글자도 보존한다",
     'resultHtml("mcp/aoa-mq/tick.sh 를 고쳤다")', "mcp/aoa-mq/tick.sh 를 고쳤다", "eq"),
    ("괄호 안 경로도 잡는다",
     'resultHtml("산출물(/Users/x/_doc_work/htm/hub_htm_a.md)")', '>hub_htm_a.md</a>', "has"),
    ("괄호는 경로에 섞이지 않는다",
     'resultHtml("산출물(/Users/x/_doc_work/htm/hub_htm_a.md)")', "%29", "hasnot"),
    ("경로가 없으면 평문 그대로", 'resultHtml("압축 1126→771자")', "압축 1126→771자", "eq"),
    ("문장부호는 경로에서 떼어 낸다",
     'resultHtml("/Users/x/_doc_work/htm/hub_htm_a.md.")', '.md"', "has"),
    ("떼어 낸 문장부호는 본문에 남는다",
     'resultHtml("/Users/x/_doc_work/htm/hub_htm_a.md.").endsWith("</a>.")', True, "eq"),
    ("결과의 태그도 이스케이프된다",
     'resultHtml("<img src=x onerror=alert(1)>")', "<img", "hasnot"),
    ("`/` 로 시작해도 폴더 구분이 없으면 경로로 안 본다",
     'resultHtml("/완료")', "<code", "hasnot"),
]

if NODE:
    js = src + "\nconst OUT=[];\n" + "".join(
        "OUT.push((()=>{try{return %s}catch(e){return 'ERR:'+e.message}})());\n" % expr
        for _, expr, _, _ in CASES
    ) + "console.log(JSON.stringify(OUT));\n"
    jf = os.path.join(SANDBOX, "mq506.mjs")
    io.open(jf, "w", encoding="utf-8").write(js)
    pr = subprocess.run([NODE, jf], capture_output=True, text=True)
    if pr.returncode != 0:
        check("node 실행 (헬퍼 발췌가 그대로 돈다)", False)
        print(pr.stderr.strip()[:800])
    else:
        got = json.loads(pr.stdout)
        check("node 실행 (헬퍼 발췌가 그대로 돈다)", True)
        for (name, _expr, want, mode), g in zip(CASES, got):
            if mode == "eq":
                check(name, g == want)
            elif mode == "has":
                check(name, isinstance(g, str) and want in g)
            else:
                check(name, isinstance(g, str) and want not in g)
            if (mode == "eq" and g != want) or (mode != "eq" and not isinstance(g, str)):
                print(f"       got={g!r} want={want!r}")
else:
    SKIP = len(CASES) + 1
    print(f"  SKIP {SKIP}건 — node 를 찾지 못해 JS 실동작을 검증하지 못했다.")
    print("       ⚠️ 위 ② 는 «함수가 있다» 만 말한다. «맞게 돈다» 는 검증되지 않았다.")

print()
print(f"PASS={PASS} FAIL={FAIL} SKIP={SKIP}")
sys.exit(1 if FAIL else 0)
