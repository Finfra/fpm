#!/usr/bin/env python3
# test_human_pages_issue616_4to9.py — Issue616_4~9 회귀 테스트 (hub 회고 M 등급)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
#   616_4: 공통 헤더·내비 — /mq·md-doc 셸(sched-log 포함)에 hub 복귀·페이지 이동
#   616_5: /fbot-map 고유어 도움말 + 카드 본문 summary 우선(부재 시 topic 폴백·규약 꼬리 제거)
#   616_6: 개인 경로 `~` 축약(mq 헤더·sched-log·issue-map/projects-map 본문 텍스트)·메모 박스
#   616_7: /mq 가독성 — 출처 라벨·본문 3줄 접기·범례 상단·ID 툴팁·sched-log 구분선 설명
#   616_8: 활동피드 — 연속 동종 이벤트 묶기·세션 종료 기본 숨김
#   616_9: 초기 로드 무게 — 응답 gzip(Accept-Encoding) 지원
#
# 실행: python3 services/hub/test_human_pages_issue616_4to9.py
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))  # services/hub 심링크 경유 실행에서도 REPO 가 맞도록 (Issue659 — release-check 가 링크 경로로 돌린다)
sys.path.insert(0, HERE)
import md_shell  # noqa: E402
import server  # noqa: E402

PASS = 0
FAIL = 0
HOME = os.path.expanduser("~")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def js_func(src, name):
    """`function name(...){...}` 본문을 중괄호 짝으로 추출 (문자열·정규식 리터럴 속 중괄호는 무시하지 않는다 — 대상 함수에 없음)."""
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


def node_bin():
    n = shutil.which("node")
    if n:
        return n
    base = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, v, "bin", "node")
            if os.path.exists(p):
                return p
    return None


def run_node(code):
    n = node_bin()
    if not n:
        return None
    r = subprocess.run([n, "-e", code], capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else "ERR:" + r.stderr[-300:]


# ───────────────────────── 616_4 공통 내비 ─────────────────────────
print("# 616_4")
nav = md_shell.hub_nav("mq")
check("hub_nav: nav.hub-nav 마크업", 'class="hub-nav"' in nav)
for href in ("/hub", "/mq", "/fbot-map"):
    check(f"hub_nav: {href} 링크", f'href="{href}"' in nav)
check("hub_nav: 현재 페이지 표시(aria-current)", 'aria-current="page"' in nav)
check("hub_nav: 현재 없으면 aria-current 없음", 'aria-current' not in md_shell.hub_nav(""))
hdr = md_shell.render_header("t", "/x", "x")
check("md 셸 헤더에 공통 내비", 'class="hub-nav"' in hdr and 'href="/mq"' in hdr)
check("/mq 페이지에 공통 내비·hub 복귀", 'class="hub-nav"' in server._MQ_PAGE_HTML
      and 'href="/hub"' in server._MQ_PAGE_HTML)
check("header CSS 에 .hub-nav 규칙", b".hub-nav" in server.HUB_HEADER_CSS)

# ───────────────────────── 616_6 경로 축약 ─────────────────────────
print("# 616_6")
check("_tilde_home: 접두 치환", server._tilde_home(HOME + "/a/b") == "~/a/b")
check("_tilde_home: 문장 속 여러 곳", server._tilde_home(f"x {HOME}/a and {HOME}/b") == "x ~/a and ~/b")
check("_tilde_home: 홈 자체", server._tilde_home(HOME) == "~")
check("_tilde_home: 형제 접두 오탐 없음", server._tilde_home(HOME + "x/a") == HOME + "x/a")
check("_tilde_home: 비문자열 통과", server._tilde_home(None) is None)
src = (f'<p>{HOME}/a</p><a href="{HOME}/a" title="{HOME}/t">{HOME}/b</a>'
       f'<script>var p="{HOME}/c";</script><style>.x{{background:url({HOME}/d)}}</style>').encode()
out = server._tilde_home_html(src).decode()
check("html: 텍스트 노드 축약", "<p>~/a</p>" in out and ">~/b</a>" in out)
check("html: 속성 값 보존(링크·툴팁 기능)", f'href="{HOME}/a"' in out and f'title="{HOME}/t"' in out)
check("html: script·style 보존", f'var p="{HOME}/c"' in out and f"url({HOME}/d)" in out)
data = {"jobs": [{"name": "j1", "log": HOME + "/logs/j1", "steps": [{}], "desc": "d"}], "runs": []}
res = server._sched_log_md("j1", data)
check("sched-log: 로그 폴더 `~` 표기", res is not None and "`~/logs/j1`" in res[0] and HOME not in res[0])
check("/mq 헤더: mq_dir 축약 호출", "tildeHome(d.mq_dir)" in server._MQ_PAGE_HTML
      or server._tilde_home(HOME + "/q") == "~/q" and "mq_dir" in server._MQ_PAGE_HTML and "~" in server._MQ_PAGE_HTML)
spec = importlib.util.spec_from_file_location(
    "bpm", os.path.join(REPO, ".claude", "skills", "projects-map", "build_projects_map.py"))
bpm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bpm)
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "_note.md"), "w", encoding="utf-8").write("* 개인 메모\n")
    note_html, _ = bpm.read_note(td)
check("projects-map 메모: 기본 접힘 <details>(open 없음)", "<details" in note_html and "<details open" not in note_html)
check("projects-map 메모: 사용자 데이터 표시", "_note.md" in note_html and "이 PC" in note_html)
check("projects-map 메모: #note 편집면 유지", 'id="note"' in note_html and 'contenteditable="true"' in note_html)

# ───────────────────────── 616_7 /mq 가독성 ─────────────────────────
print("# 616_7")
mq = server._MQ_PAGE_HTML
check("mq: 열 제목 «프로젝트 / 보낸 곳»", "프로젝트 / 보낸 곳" in mq)
fn = js_func(mq, "srcCell")
check("mq: srcCell 존재", fn is not None)
if fn:
    esc = 'const esc=t=>String(t==null?"":t).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));'
    code = esc + fn + ";console.log(JSON.stringify([srcCell('claude@.claude'),srcCell('fbot-chief-narae@'),"\
        "srcCell('claude@sreMsa (fbot-lead-sremsa)'),srcCell(''),srcCell(null)]))"
    o = run_node(code)
    if o is None or o.startswith("ERR"):
        check("mq: srcCell node 실행 " + str(o), False)
    else:
        a, b, c, d, e = json.loads(o)
        check("srcCell: 프로젝트(.claude) + 보낸 곳(claude)", ".claude" in a and "보낸 곳" in a and "claude" in a)
        check("srcCell: 프로젝트 빈 값은 대시, 보낸 곳 유지", "fbot-chief-narae" in b and "보낸 곳" in b and "–" in b)
        check("srcCell: 역할 괄호는 보낸 곳에 합침", "sreMsa" in c and "fbot-lead-sremsa" in c)
        check("srcCell: 빈 값은 -", d == "-" and e == "-")
check("mq: 본문 3줄 접기 CSS", re.search(r"line-clamp:\s*3", mq) is not None)
check("mq: 범례(.note)가 표보다 위", mq.find('id="note"') != -1 and mq.find('id="note"') < mq.find("<table>"))
check("mq: ID 셀 툴팁", 'class="id2" title=' in mq)
btns = re.findall(r"<button class=\"a[^>]*>", mq)
check("mq: 처리 버튼 전부 title", btns != [] and all("title=" in b for b in btns))
sl = server._sched_log_md("j1", data)[0]
check("sched-log: 구분선(— rc=… —) 의미 설명", "— rc=" in sl and "구분" in sl)

# ───────────────────────── 616_8 활동피드 ─────────────────────────
print("# 616_8")
hub = server.HUB_HTML
g = js_func(hub, "groupFeedRuns")
nz = js_func(hub, "isNoiseFeed")
check("HUB_HTML: groupFeedRuns·isNoiseFeed 존재", g is not None and nz is not None)
if g and nz:
    code = nz + g + """
const L=[
 {id:'1',event:'session_end',summary:'세션 종료 (other)',cwd:'/a',name:'a',ts:5},
 {id:'2',event:'session_end',summary:'세션 종료 (other)',cwd:'/b',name:'b',ts:4},
 {id:'3',event:'stop',summary:'응답 완료',cwd:'/a',name:'a',ts:3},
 {id:'4',event:'stop',summary:'응답 완료',cwd:'/a',name:'a',ts:2},
 {id:'5',event:'session_end',summary:'세션 종료 (other)',cwd:'/a',name:'a',ts:1}];
const all=groupFeedRuns(L,true), vis=groupFeedRuns(L,false);
console.log(JSON.stringify({all:all.map(x=>[x.id,x.count]),vis:vis.map(x=>[x.id,x.count]),noise:L.filter(isNoiseFeed).length}));
"""
    o = run_node(code)
    if o is None or o.startswith("ERR"):
        check("피드 묶기 node 실행 " + str(o), False)
    else:
        r = json.loads(o)
        check("연속 동종 이벤트 묶음(1+2 → ×2, 3+4 → ×2, 5)", r["all"] == [["1", 2], ["3", 2], ["5", 1]])
        check("세션 종료 숨김 모드: 응답 완료만 남음", r["vis"] == [["3", 2]])
        check("noise 판정 = session_end 3건", r["noise"] == 3)
check("HUB_HTML: 피드 숨김 토글 버튼", 'id="feed-noise"' in hub)
check("HUB_HTML: renderFeed 가 묶기 사용", "groupFeedRuns(list" in hub)
loc = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "locales")
en = json.load(open(os.path.join(loc, "en.json"), encoding="utf-8"))
ko = json.load(open(os.path.join(loc, "ko.json"), encoding="utf-8"))
for k in ("feed.noiseShow", "feed.noiseHide", "feed.noiseTitle"):
    check(f"locale {k} en/ko", k in en and k in ko)

# ───────────────────────── 616_5 fbot-map ─────────────────────────
print("# 616_5")
check("_fbot_task_line: summary 우선", server._fbot_task_line("긴 topic 원문", "한 줄 요약") == "한 줄 요약")
raw = ("Issue616 5단계 — 서브 이슈 해결. [Issue399 완료 통지 규약] 완료 시 Issue.md 완료 마커를 남기는 것이 정본이다. "
       "— topic 잘림: ~/.claude/hooks/fbot-lead.py topic fbotdisp-1-aaaaaaaa")
t = server._fbot_task_line(raw, "")
check("_fbot_task_line: topic 폴백 — 규약 꼬리·잘림 안내 제거", "Issue399" not in t and "topic 잘림" not in t
      and t.startswith("Issue616 5단계"))
check("_fbot_task_line: 빈 값", server._fbot_task_line("", "") == "")
check("_fbot_task_line: 규약 없는 평문 그대로", server._fbot_task_line("평범한 작업", None) == "평범한 작업")
board_src = server._FBOT_BOARD_JS if hasattr(server, "_FBOT_BOARD_JS") else None
page = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
check("fbot-map: 용어 도움말 접이식", 'id="fb-glossary"' in page and "<details" in page[page.find('id="fb-glossary"') - 200:page.find('id="fb-glossary"') + 40])
for term in ("교착", "공석", "인박스", "하위 진행 중", "결속"):
    i = page.find('id="fb-glossary"')
    check(f"용어 도움말에 «{term}»", i != -1 and term in page[i:i + 2500])
check("fbot-map: 목록 기본 접힘(긴 목록 상한)", "FB_LIST_CAP" in page)

# ───────────────────────── 616_9 초기 로드 ─────────────────────────
print("# 616_9")
check("gzip 헬퍼: 작은 본문은 그대로", server._maybe_gzip(b"x" * 100, "gzip") == (b"x" * 100, None))
big = (b"<html>" + b"abc " * 5000 + b"</html>")
gz, enc = server._maybe_gzip(big, "gzip, deflate")
check("gzip 헬퍼: 큰 본문 + Accept-Encoding gzip → 압축", enc == "gzip" and len(gz) < len(big) // 3)
import gzip  # noqa: E402
check("gzip 헬퍼: 왕복 동일", gzip.decompress(gz) == big)
check("gzip 헬퍼: 미지원 클라이언트는 원문", server._maybe_gzip(big, "") == (big, None))

class _GH(server.Handler):
    def __init__(self, ae):
        self.client_address = ("127.0.0.1", 0)
        self.headers = {"Accept": "*/*", "Accept-Encoding": ae}
        self.raw = b""
        self.rh = {}
        self.path = "/boards"

    def send_response(self, st):
        pass

    def send_header(self, k, v):
        self.rh[k] = v

    def end_headers(self):
        pass

    @property
    def wfile(self):
        class W:
            def __init__(s, o):
                s.o = o

            def write(s, b):
                s.o.raw += b
        return W(self)


gh = _GH("gzip")
gh._send_json(200, {"k": "v" * 5000})
check("_send_json: gzip 응답 헤더·본문", gh.rh.get("Content-Encoding") == "gzip"
      and json.loads(gzip.decompress(gh.raw))["k"] == "v" * 5000
      and int(gh.rh["Content-Length"]) == len(gh.raw))
gh = _GH("")
gh._send_json(200, {"k": "v" * 5000})
check("_send_json: Accept-Encoding 없으면 원문", "Content-Encoding" not in gh.rh and json.loads(gh.raw)["k"] == "v" * 5000)
check("_send_json: Vary 헤더", gh.rh.get("Vary") == "Accept-Encoding")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
