#!/usr/bin/env python3
# test_human_pages_issue616.py — Issue616_1~3 회귀 테스트 (hub 회고: «처음 보는 사람도 쓰게»)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
#   616_1: 브라우저(Accept: text/html) 진입 시 JSON 엔드포인트 안내 페이지·문서 오류 화면
#   616_2: /hub 탭 제목 고정(마지막 이벤트로 덮지 않음) + 통계줄 ko/en 키·툴팁
#   616_3: 375px 가로 넘침 방지 CSS(@media max-width:600px)
#
# 실행: python3 services/hub/test_human_pages_issue616.py
import json
import os
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LOCALES = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "locales")

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


class _W:
    def __init__(self, outer):
        self.outer = outer

    def write(self, b):
        self.outer.raw += b


class _H(server.Handler):
    """네트워크 없이 Handler 응답 바이트·헤더를 캡처 (_send_json 은 실제 구현 사용)."""

    def __init__(self, accept="*/*"):
        self.client_address = ("127.0.0.1", 0)
        self.headers = {"Accept": accept}
        self.raw = b""
        self.raw_headers = {}
        self._status = None

    def send_response(self, status):
        self._status = status

    def send_header(self, k, v):
        self.raw_headers[k] = v

    def end_headers(self):
        pass

    @property
    def wfile(self):
        return _W(self)


BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

# --- 616_1: JSON 엔드포인트 안내 페이지 ---
for path in ("/boards", "/projects-list", "/job-catalog"):
    h = _H(BROWSER)
    served = h._serve_api_guide(path)
    body = h.raw.decode("utf-8", "replace")
    check(f"{path}: 브라우저 Accept → 안내 페이지 200 text/html",
          served is True and h._status == 200
          and h.raw_headers.get("Content-Type", "").startswith("text/html"))
    check(f"{path}: 안내 페이지에 hub 복귀 링크", 'href="/hub"' in body)
    check(f"{path}: raw JSON 아님", not body.lstrip().startswith("{"))
    check(f"{path}: token 문자열 미노출", "token" not in body.lower().replace("tokens", ""))
    h2 = _H("*/*")
    check(f"{path}: fetch(Accept */*) 는 안내 페이지로 가로채지 않음", h2._serve_api_guide(path) is False)
    h3 = _H("application/json")
    check(f"{path}: Accept JSON 은 통과", h3._serve_api_guide(path) is False)

# --- 616_1: md-doc / htm-doc 오류 → 사람용 오류 화면 ---
h = _H(BROWSER)
h.path = "/md-doc?path=%2Fnope%2Fx.md"
h._send_json(403, {"error": "not a registered md doc"})
body = h.raw.decode("utf-8", "replace")
check("md-doc 오류(브라우저) → text/html 오류 화면",
      h._status == 403 and h.raw_headers.get("Content-Type", "").startswith("text/html"))
check("오류 화면에 hub 복귀 링크·원인 문구", 'href="/hub"' in body and "not a registered md doc" in body)
h = _H("*/*")
h.path = "/md-doc?path=%2Fnope%2Fx.md"
h._send_json(403, {"error": "not a registered md doc"})
check("md-doc 오류(Accept */*) 는 JSON 유지", h.raw_headers.get("Content-Type", "").startswith("application/json"))
h = _H(BROWSER)
h.path = "/hub-events"
h._send_json(403, {"error": "x"})
check("대상 외 경로 오류는 JSON 유지", h.raw_headers.get("Content-Type", "").startswith("application/json"))
h = _H(BROWSER)
h.path = "/htm-doc?path=%2Fnope"
h._send_json(404, {"error": "<script>alert(1)</script>"})
check("오류 화면 XSS 이스케이프", b"<script>alert(1)" not in h.raw)

# --- 616_1: locale 키 en/ko 대칭 ---
en = json.load(open(os.path.join(LOCALES, "en.json"), encoding="utf-8"))
ko = json.load(open(os.path.join(LOCALES, "ko.json"), encoding="utf-8"))
for k in ("apiGuide.title", "apiGuide.back", "docError.title", "docError.back"):
    check(f"locale {k} en/ko 존재", k in en and k in ko)

# --- 616_2: /hub 첫 화면 — 목적 1줄·통계줄 i18n/툴팁·탭 제목 고정 ---
hub = server.HUB_HTML
check("HUB_HTML: 페이지 목적 1줄 placeholder", "{T:hub.purpose}" in hub)
check("HUB_HTML: 통계줄 툴팁 placeholder", 'id="hub-stats"' in hub and "{T:hub.statsTitle}" in hub)
check("HUB_HTML: 통계줄 영어 하드코딩 제거", "project · ${dashCount} dashboard" not in hub)
check("HUB_HTML: 통계줄이 t('hub.stats') 사용", "t('hub.stats'" in hub)
check("HUB_HTML: 탭 제목 고정 잠금(MutationObserver)", "__hubTitleLock" in hub and "MutationObserver" in hub)
check("HUB_HTML: <title> 고정 문구", "<title>fPm Hub</title>" in hub)
for k in ("hub.purpose", "hub.statsTitle", "hub.stats", "hub.statsOff", "hub.statsOffSystem"):
    check(f"locale {k} en/ko 존재", k in en and k in ko)
check("ko hub.stats 한글 설명어", re.search(r"[가-힣]", ko.get("hub.stats", "")) is not None)
check("en hub.stats 한글 혼입 없음", re.search(r"[가-힣]", en.get("hub.stats", "")) is None)

# --- 616_3: 375px 가로 넘침 방지 CSS ---
def _mq(css_src, name):
    m = re.search(r"@media\s*\(max-width:\s*600px\)\s*\{(.*?)\n\}", css_src, re.S) or \
        re.search(r"@media\s*\(max-width:\s*600px\)\s*\{(.*)\}", css_src, re.S)
    return m.group(1) if m else ""

mqcss = _mq(server._MQ_PAGE_HTML, "mq")
check("/mq: 600px 이하 미디어쿼리 존재", mqcss != "")
check("/mq: 표가 자체 가로 스크롤(overflow-x:auto)", "overflow-x:auto" in mqcss.replace(" ", ""))
check("/mq: 검색 입력 min-width 해제", "min-width:0" in mqcss.replace(" ", ""))
hubcss = _mq(server.HUB_HTML, "hub")
check("/hub: 600px 이하 미디어쿼리 존재", hubcss != "")
hc = hubcss.replace(" ", "")
check("/hub: 헤더 줄바꿈 허용", "header{" in hc and "flex-wrap:wrap" in hc)
check("/hub: 헤더 버튼군 줄바꿈 허용", ".header-actions{" in hc and hc.count("flex-wrap:wrap") >= 2)
check("/hub: 피드 min-width 해제", "min-width:0" in hc)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
