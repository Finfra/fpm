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

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
