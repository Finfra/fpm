#!/usr/bin/env python3
# test_md_doc.py — Issue353_1 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). md-first 셸 렌더(/md-doc) +
#   register-doc `.md` 확장(stem·autoheal·autoregister·self-heal)을 검증한다.
#
# 실행: python3 services/hub/test_md_doc.py
"""server.py /md-doc 라우트 + md_shell 템플릿 (Issue353_1) 단위 테스트."""
import os
import sys
import tempfile
from urllib.parse import urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402
import md_shell  # noqa: E402

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


# --- 파일명 패턴 게이트 (_htm_output_stem / _HTM_DOC_PATH_RE) ---
check("stem: hub_htm_*.md 인식", server._htm_output_stem("hub_htm_1722800000_x.md") == "hub_htm_1722800000_x")
check("stem: 규약 밖 md 거부", server._htm_output_stem("notes.md") == "")
check("stem: 기존 htm 인식 유지", server._htm_output_stem("hub_htm_1_a.htm") == "hub_htm_1_a")
check("autoheal 정규식: htm 디렉토리 md 매치",
      server._HTM_DOC_PATH_RE.search("x /p/_doc_work/htm/hub_htm_1_a.md y") is not None)
check("autoheal 정규식: legacy html 매치 유지",
      server._HTM_DOC_PATH_RE.search("/p/_doc_work/z_htm/claude-htm-123.html") is not None)
check("autoheal 정규식: 규약 밖 md 비매치",
      server._HTM_DOC_PATH_RE.search("/p/_doc_work/htm/readme.md") is None)

# --- frontmatter 분리 (marked 가 YAML 을 모름 → 떼지 않으면 본문에 노출) ---
meta, body_md = md_shell.split_frontmatter(
    '---\ntitle: "제목: 콜론 포함"\nsid: abc-123\n---\n\n# 본문\n\n내용\n')
check("frontmatter meta 파싱 (인용부호 제거)", meta.get("title") == "제목: 콜론 포함")
check("frontmatter sid 파싱", meta.get("sid") == "abc-123")
check("frontmatter 가 본문에서 분리됨", body_md.lstrip().startswith("# 본문"))
meta2, body2 = md_shell.split_frontmatter("# frontmatter 없는 문서\n")
check("frontmatter 없으면 원문 그대로", meta2 == {} and body2.startswith("# frontmatter"))
meta3, body3 = md_shell.split_frontmatter("본문 시작\n\n---\n\n구분선은 frontmatter 아님\n")
check("본문 중간 --- 은 frontmatter 로 오인하지 않음", meta3 == {} and "구분선" in body3)

# --- md_shell 템플릿 (serve 시점 XSS 불가침) ---
XSS_MD = "# t\n\n</script><script>alert(1)</script>\n\n<img src=x onerror=alert(2)>\n"
nonce = md_shell.make_nonce()
page = md_shell.render_md_shell(XSS_MD, "t", "/p/_doc_work/htm/hub_htm_1.md", nonce)
check("md 원문 <script> 는 JSON \\u003c 이스케이프", b"\\u003cscript>alert(1)" in page)
check("serve 시점 실행 가능한 주입 script 없음", b"<script>alert(1)" not in page)
check("onerror 인라인 핸들러도 태그로 실리지 않음", b"<img src=x onerror" not in page)
check("nonce 가 셸 스크립트에 부여됨", f'nonce="{nonce}"'.encode() in page)
check("CSP: script-src nonce + jsdelivr 한정",
      f"'nonce-{nonce}'" in md_shell.csp_header(nonce)
      and "cdn.jsdelivr.net" in md_shell.csp_header(nonce)
      and "unsafe-inline" not in md_shell.csp_header(nonce).split("style-src")[0])


# --- ALLOWED_URI_REGEXP: vscode 스킴 허용 + 위험 스킴 차단 (M1-후속 회귀) ---
# DOMPurify 는 이 정규식에 **매치되지 않는** href/src 를 제거한다. JS 정규식과 파이썬
# `re` 문법이 호환되는 표현이라 여기서 직접 판정을 재현해 검증한다.
import re as _re  # noqa: E402
_URI_RE = _re.compile(md_shell.ALLOWED_URI_REGEXP, _re.IGNORECASE)
check("vscode://file 링크 허용 (Issue201 회귀 차단)",
      _URI_RE.match("vscode://file$HOME/_git/___pm/Issue.md") is not None)
check("http(s)·mailto 등 기본 스킴 유지",
      all(_URI_RE.match(u) for u in
          ("https://ex.com/a", "http://127.0.0.1:9876/hub", "mailto:a@b.c", "tel:+8210")))
check("상대경로·앵커·프로토콜 상대 URL 유지",
      all(_URI_RE.match(u) for u in ("../capture/x.png", "#sec", "/fpm-icon.png", "//ex.com/a")))
check("javascript: 차단", _URI_RE.match("javascript:alert(1)") is None)
check("data: 차단", _URI_RE.match("data:text/html;base64,PHNjcmlwdD4=") is None)
check("대문자·혼합 표기 우회 차단 (JAVASCRIPT:)",
      _URI_RE.match("JAVASCRIPT:alert(1)") is None
      and _URI_RE.match("JaVaScRiPt:alert(1)") is None)
check("file: 스킴은 비허용 유지 (이미지 경로는 /htm-res 재작성 담당)",
      _URI_RE.match("file:///etc/passwd") is None)
check("RENDER_JS 에 플레이스홀더가 남지 않고 정규식이 주입됨",
      "__ALLOWED_URI_REGEXP__" not in md_shell.RENDER_JS
      and "xmpp|vscode" in md_shell.RENDER_JS
      and "ALLOWED_URI_REGEXP: ALLOWED_URI_REGEXP" in md_shell.RENDER_JS)

# --- /md-doc 라우트 (_FakeHandler) ---
class _FakeWriter:
    def __init__(self, outer):
        self.outer = outer

    def write(self, b):
        self.outer.raw += b


class _FakeHandler(server.Handler):
    def __init__(self):
        self.client_address = ("127.0.0.1", 0)
        self.json_responses = []
        self.raw = b""
        self.raw_headers = {}
        self._status = None

    def _send_json(self, status, body):
        self.json_responses.append((status, body))

    def send_response(self, status):
        self._status = status

    def send_header(self, k, v):
        self.raw_headers[k] = v

    def end_headers(self):
        pass

    @property
    def wfile(self):
        return _FakeWriter(self)


TMP = tempfile.mkdtemp(prefix="md-doc-test-")
HTM_DIR = os.path.join(TMP, "proj", "_doc_work", "htm")
ARCH_DIR = os.path.join(TMP, "proj", "_doc_work", "z_done", "htm")
os.makedirs(HTM_DIR)
os.makedirs(ARCH_DIR)

MD1 = os.path.join(HTM_DIR, "hub_htm_1722800001_alpha.md")
open(MD1, "w").write("---\ntitle: 알파 문서\n---\n\n# 헤딩\n\n본문 요약 대상 문장.\n")
MD_AUTO = os.path.join(HTM_DIR, "hub_htm_1722800002_beta.md")
open(MD_AUTO, "w").write("# beta\n\nauto-register me\n")
MD_OUT = os.path.join(TMP, "proj", "notes.md")  # 규약 밖 (autoregister 불가)
open(MD_OUT, "w").write("# outside\n")
HTM1 = os.path.join(HTM_DIR, "hub_htm_1722800003_gamma.htm")
open(HTM1, "w").write("<html><body>g</body></html>")

server.HTM_REGISTRY = os.path.join(TMP, "htm-registry.json")
server.HTM_CLEARED = os.path.join(TMP, "htm-cleared.json")
server.save_registry(server.HTM_REGISTRY, [{"path": MD1}, {"path": HTM1}])
server.save_registry(server.HTM_CLEARED, [])


def _get_md(url):
    h = _FakeHandler()
    h.path = url
    h._handle_md_doc(urlparse(url))
    return h


def _get_htm(url):
    h = _FakeHandler()
    h.path = url
    h._handle_htm_doc(urlparse(url))
    return h


r = _get_md(f"/md-doc?path={quote(MD1, safe='')}")
check("등록 md → 200 html 셸", r._status == 200
      and r.raw_headers.get("Content-Type", "").startswith("text/html"))
check("CSP 헤더 동봉", "Content-Security-Policy" in r.raw_headers)
check("md 본문이 JSON 으로 실림", b"\\ubcf8\\ubb38" in r.raw or "본문".encode("unicode_escape") in r.raw or b"md-src" in r.raw)
check("shim(닫기 버튼) 주입 + nonce 부여", b"<script>" not in r.raw)  # 전 인라인 script 에 nonce
check("canonical header 마크업 존재", b"<header>" in r.raw
      and b'class="header-actions"' in r.raw and b'class="hub-link"' in r.raw)
check("header CSS 정규화 주입", b'id="hub-header-normalized"' in r.raw)
check("frontmatter 는 본문에 렌더되지 않음", b"title: " not in r.raw)
check("frontmatter title 이 헤더 h1 에 반영", "알파 문서".encode() in r.raw)

r = _get_md(f"/md-doc?path={quote(MD_OUT, safe='')}")
check("규약 밖 미등록 md → 403", r.json_responses and r.json_responses[0][0] == 403)

r = _get_md(f"/md-doc?path={quote(MD_AUTO, safe='')}")
check("canonical 규약 md self-heal autoregister → 200", r._status == 200)
reg_now = {os.path.realpath(e.get("path")) for e in server.load_registry(server.HTM_REGISTRY)}
check("autoregister 가 registry 에 기록", os.path.realpath(MD_AUTO) in reg_now)

r = _get_md(f"/md-doc?path={quote(HTM1, safe='')}")
check("등록돼도 md 외 확장자는 403", r.json_responses and r.json_responses[0][0] == 403)

r = _get_htm(f"/htm-doc?path={quote(MD1, safe='')}")
check("/htm-doc 로 온 md 는 302 → /md-doc",
      r._status == 302 and r.raw_headers.get("Location", "").startswith("/md-doc?path="))

# ENOENT 이동 self-heal (htm/ → z_done/htm/)
moved_to = os.path.join(ARCH_DIR, os.path.basename(MD1))
os.rename(MD1, moved_to)
r = _get_md(f"/md-doc?path={quote(MD1, safe='')}")
check("아카이브 이동 md self-heal → 200", r._status == 200)
reg_now = {os.path.realpath(e.get("path")) for e in server.load_registry(server.HTM_REGISTRY)}
check("self-heal 이 registry 경로 갱신",
      os.path.realpath(moved_to) in reg_now and os.path.realpath(MD1) not in reg_now)

# --- 카드 메타 추출 md 대응 ---
check("title: frontmatter 추출", server.Handler._extract_html_title(moved_to) == "알파 문서")
summary = server.Handler._extract_html_summary(moved_to)
check("summary: frontmatter·헤딩 제외 본문 발췌",
      "본문 요약" in summary and "title" not in summary and "헤딩" not in summary)

# --- Issue634: 헤더 🗺️ 버튼 + 풍선(이슈맵 그림 + 이동 버튼) ---
# md_shell 단위 — 마크업·이스케이프·빈 값·CSP
CWD_X = '/p/a"<b>&c'
ENC_X = "%2Fp%2Fa%22%3Cb%3E%26c"
pop = md_shell.render_issue_map_pop(CWD_X, "프로젝트")
check("pop: 버튼은 이모지만(제목 텍스트 없음)",
      '<button type="button" class="im-pop-btn"' in pop and ">\U0001F5FA\uFE0F</button>" in pop
      and "프로젝트 이슈맵</button>" not in pop)
check("pop: 풍선 iframe 은 열 때 로드(data-src) + embed=1",
      f'data-src="/issue-map?cwd={ENC_X}&amp;embed=1"' in pop and ' src="/issue-map' not in pop)
check("pop: 그림 아래 이슈맵 이동 링크(embed 없음)",
      f'class="im-pop-go" href="/issue-map?cwd={ENC_X}"' in pop
      and pop.index("<iframe") < pop.index('class="im-pop-go"'))
check("pop: cwd HTML 특수문자가 마크업으로 새지 않음", "<b>" not in pop and 'a"<' not in pop)
check("pop: 접기 패널(details) 폐기", "<details" not in pop)
check("pop: 빈 cwd → 빈 문자열", md_shell.render_issue_map_pop("", "x") == "")
check("CSP: frame-src 'self' (와일드카드 없음)",
      "frame-src 'self';" in md_shell.csp_header("n") and "frame-src *" not in md_shell.csp_header("n"))
hdr = md_shell.render_header("t", "/p", "p", issue_map_cwd="/p")
check("header: 🗺️ 버튼이 헤더 header-actions 안", 'class="im-pop"' in hdr
      and hdr.index('class="header-actions"') < hdr.index('class="im-pop"') < hdr.index("</header>"))
check("header: 기본값 → 버튼 없음", "im-pop" not in md_shell.render_header("t", "/p", "p"))
p_on = md_shell.render_md_shell("# t\n", "t", "/p/_doc_work/htm/x.md", "N", "/p", "p",
                                issue_map_cwd="/p")
p_off = md_shell.render_md_shell("# t\n", "t", "/p/_doc_work/htm/x.md", "N", "/p", "p")
check("shell: 버튼은 헤더 안 · 본문 위 패널 없음", b'class="im-pop"' in p_on
      and p_on.index(b'class="im-pop"') < p_on.index(b"</header>") and b"im-panel" not in p_on)
check("shell: 풍선 스크립트에 nonce", b'nonce="N"' in p_on and b"im-pop" in p_on.split(b"</header>")[1])
check("shell: issue_map_cwd 기본값 → 버튼·iframe 없음",
      b'class="im-pop"' not in p_off and b"<iframe" not in p_off)
p_live = md_shell.render_live_shell("t", "/p", "p", "sid", "h", "tok", "N", issue_map_cwd="/p")
check("live shell: 같은 🗺️ 버튼", b'class="im-pop"' in p_live)

# 라우트 — `_issue_map_openable` 이 루트를 내면 패널, 아니면 없음
IM_PROJ = os.path.realpath(os.path.join(TMP, "improj"))
IM_HTM = os.path.join(IM_PROJ, "_doc_work", "htm")
os.makedirs(IM_HTM)
open(os.path.join(IM_PROJ, "Issue.md"), "w").write("# Issue\n")
IM_MD = os.path.join(IM_HTM, "hub_htm_1722800010_im.md")
open(IM_MD, "w").write("# im\n")
NOIM_PROJ = os.path.realpath(os.path.join(TMP, "noim"))  # Issue.md 없음
os.makedirs(os.path.join(NOIM_PROJ, "_doc_work", "htm"))
NOIM_MD = os.path.join(NOIM_PROJ, "_doc_work", "htm", "hub_htm_1722800011_noim.md")
open(NOIM_MD, "w").write("# noim\n")
_orig_roots = server._issue_map_roots
server._issue_map_roots = lambda: [IM_PROJ, NOIM_PROJ]
try:
    r = _get_md(f"/md-doc?path={quote(IM_MD, safe='')}")
    check("route: 맵을 열 수 있는 prj → 200 + 🗺️ 버튼", r._status == 200
          and f'data-src="/issue-map?cwd={quote(IM_PROJ, safe="")}&amp;embed=1"'.encode() in r.raw)
    check("route: CSP 헤더에 frame-src 'self'",
          "frame-src 'self'" in r.raw_headers.get("Content-Security-Policy", ""))
    r = _get_md(f"/md-doc?path={quote(NOIM_MD, safe='')}")
    check("route: Issue.md 없는 prj → 버튼 없음", r._status == 200 and b'class="im-pop"' not in r.raw)
    server._issue_map_roots = lambda: [NOIM_PROJ]
    r = _get_md(f"/md-doc?path={quote(IM_MD, safe='')}")
    check("route: 등록 트리 밖 prj → 버튼 없음", r._status == 200 and b'class="im-pop"' not in r.raw)
    # 모든 md 셸 문서 — /mq-doc·/sched-log 도 _send_md_html 한 벌이라 같은 판정을 탄다
    server._issue_map_roots = lambda: [IM_PROJ]
    h = _FakeHandler()
    h._send_md_html("# mq\n", "t", IM_MD, IM_PROJ, "improj")
    check("route: _send_md_html(mq-doc·sched 경로)도 버튼", h._status == 200 and b'class="im-pop"' in h.raw)
    h = _FakeHandler()
    h._send_md_html("# r\n", "t", IM_MD, "", "schedule")
    check("route: 프로젝트 없는 문서(sched-result) → 버튼 없음", h._status == 200 and b'class="im-pop"' not in h.raw)
finally:
    server._issue_map_roots = _orig_roots

print()
print(f"PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
