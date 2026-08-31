#!/usr/bin/env python3
# test_ask_pending_issue452.py — Issue452 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `..ask` 를 b(폼) 주 페이지 + a 문서
#   55vh iframe 에서 → a(맥락) 문서 위 모달로 뒤집은 서버측 계약을 검증한다.
#   짝 이슈 prj3#Issue492(생성 지점 hook)는 여기 범위가 아니다.
#
# 실행: python3 services/hub/test_ask_pending_issue452.py
"""server.py `/ask-register` + `?ask=` 모달 주입 + `/answer` 소멸 단위 테스트."""
import io
import json
import os
import sys
import tempfile
import time
from urllib.parse import urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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


# ── 페이크 핸들러 (test_md_doc.py 와 동형) ────────────────────────────────
class _FakeWriter:
    def __init__(self, outer):
        self.outer = outer

    def write(self, b):
        self.outer.raw += b


class _FakeHandler(server.Handler):
    def __init__(self, body=None, ip="127.0.0.1"):
        self.client_address = (ip, 0)
        self.json_responses = []
        self.raw = b""
        self.raw_headers = {}
        self._status = None
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        self.rfile = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

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


TMP = tempfile.mkdtemp(prefix="ask-pending-test-")
PROJ = os.path.join(TMP, "proj")
HTM_DIR = os.path.join(PROJ, "_doc_work", "htm")
os.makedirs(HTM_DIR)

A_MD = os.path.join(HTM_DIR, "hub_htm_1756700001_a_ctx.md")
open(A_MD, "w").write("---\ntitle: 맥락 문서\n---\n\n# 맥락\n\n읽어야 할 본문.\n")
A_HTM = os.path.join(HTM_DIR, "hub_htm_1756700002_a_ctx.htm")
open(A_HTM, "w").write("<html><head><title>맥락 htm</title></head><body><p>본문</p></body></html>")
OUTSIDE = os.path.join(PROJ, "notes.md")          # 규약 밖 → autoregister 불가
open(OUTSIDE, "w").write("# outside\n")

server.HTM_REGISTRY = os.path.join(TMP, "htm-registry.json")
server.HTM_CLEARED = os.path.join(TMP, "htm-cleared.json")
server.ASK_PENDING = os.path.join(TMP, "ask-pending.json")
server.INBOX_ROOT = os.path.join(TMP, "inbox")
server.save_registry(server.HTM_REGISTRY,
                     [{"path": A_MD, "cwd": PROJ}, {"path": A_HTM, "cwd": PROJ}])
server.save_registry(server.HTM_CLEARED, [])
server.save_registry(server.ASK_PENDING, [])

FORM = ('<form id="qa-form"><div class="q-card" data-question="배포?">'
        '<label><input type="radio" name="q0" value="예">예</label></div>'
        '<button type="button" id="submit-btn">전송</button><div id="status"></div>'
        '</form><script>document.getElementById("submit-btn")'
        '.addEventListener("click",function(){});</script>')


def _register(**over):
    body = {"doc_path": A_MD, "cwd": PROJ, "sid": "sess-1",
            "title": "배포 방식", "form_html": FORM}
    body.update(over)
    h = _FakeHandler(body, ip=over.pop("_ip", "127.0.0.1"))
    h._handle_ask_register(urlparse("/ask-register"))
    return h


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


# ── /ask-register 계약 ────────────────────────────────────────────────────
r = _register()
check("등록 → 200 + id 반환", r.json_responses and r.json_responses[0][0] == 200
      and r.json_responses[0][1].get("id"))
AID = r.json_responses[0][1]["id"]
check("md 문서는 /md-doc URL 로 안내",
      r.json_responses[0][1]["url"].startswith("/md-doc?path=")
      and r.json_responses[0][1]["url"].endswith("&ask=" + AID))
check("저장소에 레코드 1건", len(server.load_registry(server.ASK_PENDING)) == 1)

r = _register(form_html="")
check("form_html 없으면 400", r.json_responses[0][0] == 400)
r = _register(doc_path="")
check("doc_path 없으면 400", r.json_responses[0][0] == 400)
r = _register(form_html="x" * (server.ASK_FORM_HTML_MAX + 1))
check("form_html 상한 초과 400", r.json_responses[0][0] == 400)
r = _register(sid="bad sid!")
check("sid 형식 위반 400", r.json_responses[0][0] == 400)
h = _FakeHandler({"doc_path": A_MD, "form_html": FORM}, ip="203.0.113.9")
h._handle_ask_register(urlparse("/ask-register"))
check("비-localhost 등록 403", h.json_responses[0][0] == 403)
check("실패 등록들이 저장소를 오염시키지 않음",
      len(server.load_registry(server.ASK_PENDING)) == 1)

# 같은 문서·같은 세션 재등록은 대체 (모달 중첩 방지)
r2 = _register(title="다시 묻기")
check("같은 doc+sid 재등록은 대체(1건 유지)",
      len(server.load_registry(server.ASK_PENDING)) == 1)
AID = r2.json_responses[0][1]["id"]

# ── ① 짝 a 가 md ─────────────────────────────────────────────────────────
r = _get_md(f"/md-doc?path={quote(A_MD, safe='')}&ask={AID}")
check("① md 문서 200 + 모달 주입", r._status == 200
      and b'id="fpm-ask-modal"' in r.raw and b'id="qa-form"' in r.raw)
check("① 재호출 버튼·Esc 바인딩 동봉",
      b'id="fpm-ask-reopen"' in r.raw and b"Escape" in r.raw)
check("① 모달이 </body> 앞에 들어감",
      r.raw.rfind(b'id="fpm-ask-modal"') < r.raw.lower().rfind(b"</body>"))
_SNIP = server._ask_modal_snippet({"title": "t", "form_html": "<i></i>"}).decode()
_SNIP_NS = _SNIP.replace(" ", "")
check("① 배경 문서 스크롤 차단 없음 (backdrop·showModal·body overflow 잠금 부재)",
      "showModal" not in _SNIP and "backdrop" not in _SNIP
      and "body{overflow" not in _SNIP_NS
      and "document.body.style.overflow" not in _SNIP_NS
      and "documentElement.style.overflow" not in _SNIP_NS)
check("① CSP: 조각 인라인 script 도 nonce 를 받음", b"<script>" not in r.raw)
check("① a 문서 파일은 재작성되지 않음",
      open(A_MD, encoding="utf-8").read().startswith("---\ntitle: 맥락 문서"))

r = _get_md(f"/md-doc?path={quote(A_MD, safe='')}")
check("① ask 파라미터 없으면 평범한 문서 (모달 없음)",
      r._status == 200 and b'id="fpm-ask-modal"' not in r.raw)

# ── ② 짝 a 가 htm ────────────────────────────────────────────────────────
rh = _register(doc_path=A_HTM, sid="sess-2")
HID = rh.json_responses[0][1]["id"]
check("② htm 문서는 /htm-doc URL 로 안내",
      rh.json_responses[0][1]["url"].startswith("/htm-doc?path="))
r = _get_htm(f"/htm-doc?path={quote(A_HTM, safe='')}&ask={HID}")
check("② htm 문서 200 + 모달 주입", r._status == 200
      and b'id="fpm-ask-modal"' in r.raw and b'id="qa-form"' in r.raw)
r = _get_htm(f"/htm-doc?path={quote(A_HTM, safe='')}")
check("② ask 없으면 평범한 htm", r._status == 200 and b'id="fpm-ask-modal"' not in r.raw)

# id 를 남의 문서에 붙여도 맥락이 어긋난 모달은 뜨지 않는다
r = _get_htm(f"/htm-doc?path={quote(A_HTM, safe='')}&ask={AID}")
check("다른 문서의 id 는 무시 (doc_path 대조)", r._status == 200
      and b'id="fpm-ask-modal"' not in r.raw)

# ── ④ 미등록 경로 + ?ask= → 403 유지 (화이트리스트 우회 금지) ────────────
ro = _register(doc_path=OUTSIDE, sid="sess-3")
OID = ro.json_responses[0][1]["id"]
r = _get_md(f"/md-doc?path={quote(OUTSIDE, safe='')}&ask={OID}")
check("④ 미등록 경로 + ask → 403 유지",
      r.json_responses and r.json_responses[0][0] == 403 and r._status is None)

# ── ③ 응답 회수 → 소멸 → 재방문 시 모달 없음 ────────────────────────────
server.projects[server.cwd_hash(PROJ)] = {"cwd": PROJ, "token": "tok1", "name": "proj"}
ans = _FakeHandler([{"question": "배포?", "answers": ["예"]}])
ans._handle_answer(urlparse(f"/answer?cwd={quote(PROJ, safe='')}&token=tok1&sid=sess-1"))
check("③ /answer 200", ans.json_responses and ans.json_responses[0][0] == 200)
left = {e["id"] for e in server.load_registry(server.ASK_PENDING)}
check("③ 응답한 세션(sess-1)의 pending 소멸", AID not in left)
check("③ 다른 세션(sess-2·sess-3) pending 은 보존", {HID, OID} <= left)
r = _get_md(f"/md-doc?path={quote(A_MD, safe='')}&ask={AID}")
check("③ 소멸 후 재방문 → 문서는 200, 모달 없음",
      r._status == 200 and b'id="fpm-ask-modal"' not in r.raw)

# ── 저장소 위생 (GC) ─────────────────────────────────────────────────────
now = time.time()
aged = [{"id": "old", "doc_path": A_MD, "cwd": PROJ, "sid": "", "form_html": "x",
         "created": now - server.ASK_PENDING_TTL - 10},
        {"id": "new", "doc_path": A_MD, "cwd": PROJ, "sid": "", "form_html": "x",
         "created": now}]
kept = {e["id"] for e in server._ask_pending_gc(aged)}
check("GC: TTL 초과 제거·유효분 보존", kept == {"new"})
many = [{"id": f"i{i}", "doc_path": A_MD, "cwd": PROJ, "sid": "", "form_html": "x",
         "created": now + i} for i in range(server.ASK_PENDING_MAX + 5)]
check("GC: 상한 초과 시 오래된 것부터 절삭",
      len(server._ask_pending_gc(many)) == server.ASK_PENDING_MAX
      and server._ask_pending_gc(many)[0]["id"] == "i5")
check("GC: 파손 레코드(dict 아님·id 없음) 제거",
      server._ask_pending_gc(["x", {"created": now}]) == [])

print()
print(f"PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
