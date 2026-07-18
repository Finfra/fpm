#!/usr/bin/env python3
# test_htm_res.py — Issue255 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). /htm-res 라우트 + 상대 img src
#   재작성(_rewrite_relative_imgs)을 TDD 검증한다.
#
# 실행: python3 services/hub/test_htm_res.py
"""server.py /htm-res 리소스 라우트 (Issue255) 단위 테스트."""
import os
import shutil
import sys
import tempfile
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


# --- _rewrite_relative_imgs ---
DOC = "/proj/_doc_work/z_htm/a.htm"
body = (b'<html><body>'
        b'<img class="shot" src="../capture/x.png" alt="a">'
        b"<img src='../capture/y two.png'>"
        b'<img src="data:image/png;base64,AAA=">'
        b'<img src="https://ex.com/z.png">'
        b'<img src="/fpm-icon.png">'
        b'</body></html>')
out = server._rewrite_relative_imgs(body, DOC)
check("상대 src → /htm-res 재작성 (double quote)",
      b'src="/htm-res?doc=' in out and b"rel=..%2Fcapture%2Fx.png" in out)
check("상대 src → /htm-res 재작성 (single quote + 공백 rel 인코딩)",
      b"rel=..%2Fcapture%2Fy%20two.png" in out)
check("data: URI 는 미변경", b'src="data:image/png;base64,AAA="' in out)
check("http(s) 절대 URL 은 미변경", b'src="https://ex.com/z.png"' in out)
check("/ 시작 절대경로는 미변경", b'src="/fpm-icon.png"' in out)
check("extra query 전달 (cwd/token)",
      b"cwd=" in server._rewrite_relative_imgs(body, DOC, extra_query="cwd=%2Fproj&token=t1"))

# --- /htm-res 라우트 (_FakeHandler) ---
class _FakeWriter:
    def __init__(self, outer):
        self.outer = outer

    def write(self, b):
        self.outer.raw += b


class _FakeHandler(server.Handler):
    def __init__(self):
        self.client_address = ("127.0.0.1", 0)
        self.json_responses = []   # [(status, body), ...]
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


TMP = tempfile.mkdtemp(prefix="htm-res-test-")
DOCWORK = os.path.join(TMP, "proj", "_doc_work")
os.makedirs(os.path.join(DOCWORK, "z_htm"))
os.makedirs(os.path.join(DOCWORK, "capture"))
DOC2 = os.path.join(DOCWORK, "z_htm", "d.htm")
open(DOC2, "w").write("<html><body>x</body></html>")
PNG = os.path.join(DOCWORK, "capture", "img.png")
open(PNG, "wb").write(b"\x89PNG-fake")
open(os.path.join(TMP, "proj", "secret.py"), "w").write("top=1")

# registry 픽스처 — HTM_REGISTRY 를 임시 파일로 교체
server.HTM_REGISTRY = os.path.join(TMP, "htm-registry.json")
server.save_registry(server.HTM_REGISTRY, [{"path": DOC2}])


def _get(url):
    h = _FakeHandler()
    h.path = url
    h._handle_htm_res(urlparse(url))
    return h


r = _get(f"/htm-res?doc={quote(DOC2, safe='')}&rel={quote('../capture/img.png', safe='')}")
check("등록 doc + 유효 rel → 200 이미지 bytes",
      r._status == 200 and r.raw == b"\x89PNG-fake")
check("Content-Type image/png", r.raw_headers.get("Content-Type") == "image/png")
check("Cache-Control no-store", r.raw_headers.get("Cache-Control") == "no-store")

r = _get(f"/htm-res?doc={quote('/etc/hosts', safe='')}&rel=x.png")
check("미등록 doc → 403",
      r.json_responses and r.json_responses[0][0] == 403)

r = _get(f"/htm-res?doc={quote(DOC2, safe='')}&rel={quote('../../secret.py', safe='')}")
check("jail(_doc_work) 탈출 rel → 403",
      r.json_responses and r.json_responses[0][0] == 403)

r = _get(f"/htm-res?doc={quote(DOC2, safe='')}&rel={quote('../capture/none.png', safe='')}")
check("파일 부재 → 404",
      r.json_responses and r.json_responses[0][0] == 404)

r = _get(f"/htm-res?doc={quote(DOC2, safe='')}&rel=missing-ext")
check("확장자 비허용 → 403",
      r.json_responses and r.json_responses[0][0] == 403)

r = _get(f"/htm-res?doc={quote(DOC2, safe='')}")
check("rel/abs 누락 → 400",
      r.json_responses and r.json_responses[0][0] == 400)

# --- Issue283: file:// 절대경로 (abs 모드) ---
out2 = server._rewrite_relative_imgs(
    b'<img src="file:///Users/x/Desktop/cat.png">'
    b'<img src="file:///Users/x/a%20b.png">'
    b'<img src="file://otherhost/Users/x/c.png">', DOC)
check("file:// src → /htm-res abs 재작성",
      b"abs=%2FUsers%2Fx%2FDesktop%2Fcat.png" in out2)
check("file:// percent-encoding 디코드 후 재인코딩",
      b"abs=%2FUsers%2Fx%2Fa%20b.png" in out2)
check("원격 file://host/… 는 미변경",
      b'src="file://otherhost/Users/x/c.png"' in out2)

HOME = os.path.realpath(os.path.expanduser("~"))
HOME_PNG = os.path.join(HOME, ".htm-res-test-abs.png")
open(HOME_PNG, "wb").write(b"\x89PNG-abs")
try:
    r = _get(f"/htm-res?doc={quote(DOC2, safe='')}&abs={quote(HOME_PNG, safe='')}")
    check("등록 doc + $HOME 하위 abs → 200 이미지 bytes",
          r._status == 200 and r.raw == b"\x89PNG-abs")

    r = _get(f"/htm-res?doc={quote('/etc/hosts', safe='')}&abs={quote(HOME_PNG, safe='')}")
    check("미등록 doc + abs → 403",
          r.json_responses and r.json_responses[0][0] == 403)

    r = _get(f"/htm-res?doc={quote(DOC2, safe='')}&abs={quote('/etc/hosts.png', safe='')}")
    check("$HOME 밖 abs → 403",
          r.json_responses and r.json_responses[0][0] == 403)

    h = _FakeHandler()
    h.client_address = ("192.168.0.9", 0)
    url = f"/htm-res?doc={quote(DOC2, safe='')}&abs={quote(HOME_PNG, safe='')}"
    h.path = url
    h._handle_htm_res(urlparse(url))
    check("비-loopback 클라이언트 abs → 403",
          h.json_responses and h.json_responses[0][0] == 403)
finally:
    os.remove(HOME_PNG)

shutil.rmtree(TMP)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
