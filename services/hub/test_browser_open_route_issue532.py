#!/usr/bin/env python3
# test_browser_open_route_issue532.py — Issue532 opener 게이트 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `hooks/fpm-browser-open.sh` 가 md-doc URL 을
#   열기 전에 hub `/live-route` 판정을 따르는지 **실제 스크립트**로 검증한다.
#   가짜 hub(로컬 HTTP) + PATH 앞의 가짜 `open`(인자 기록)으로 브라우저를 대신한다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_browser_open_route_issue532.py
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# realpath — release-check 는 심볼릭 링크 services/hub 경유로 돌린다(Issue465). abspath 면
#   ../../hooks 가 repo 루트 hooks/ 로 풀려 스크립트를 못 찾는다.
HERE = os.path.dirname(os.path.realpath(__file__))
SCRIPT = os.path.normpath(os.path.join(HERE, "..", "..", "hooks", "fpm-browser-open.sh"))

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


REPLY = {"body": None}


class _Hub(BaseHTTPRequestHandler):
    def do_GET(self):
        if REPLY["body"] is None:           # 무응답 흉내 — 연결은 받되 500
            self.send_response(500)
            self.end_headers()
            return
        b = json.dumps(REPLY["body"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), _Hub)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

TMP = tempfile.mkdtemp(prefix="issue532-open-")
LOG = os.path.join(TMP, "open.log")
for name, body in (("open", f'echo "$@" >> "{LOG}"\n'),
                   ("osascript", "exit 0\n"),
                   ("pgrep", "exit 1\n")):
    p = os.path.join(TMP, name)
    with open(p, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(p, 0o755)
ENV = dict(os.environ, PATH=TMP + os.pathsep + os.environ["PATH"])
ENV.pop("FPM_OPEN_NO_ROUTE", None)

DOC_URL = f"http://jm4.example:{PORT}/md-doc?path=/p/_doc_work/htm/hub_htm_20260926_1_a_x.md"
LIVE_URL = f"http://127.0.0.1:{PORT}/s/h/s/live?token=t"


def run(url, env=None):
    open(LOG, "w").close()
    subprocess.run(["bash", SCRIPT, "-a", "firefox", "-f", "true", url],
                   env=env or ENV, capture_output=True, timeout=20)
    return open(LOG).read()


REPLY["body"] = {"action": "skip", "url": DOC_URL}
check("1 skip → 아무것도 열지 않음", run(DOC_URL).strip() == "")

REPLY["body"] = {"action": "open", "url": LIVE_URL}
out = run(DOC_URL)
check("2 open+라이브 URL → 문서 대신 라이브 창", LIVE_URL in out and "md-doc" not in out)

REPLY["body"] = None
check("3 서버 오류 → 원래 URL (fail-open)", DOC_URL in run(DOC_URL))

REPLY["body"] = {"action": "skip", "url": ""}
check("4 md-doc 아닌 URL 은 판정 안 함", "/hub" in run(f"http://127.0.0.1:{PORT}/hub"))
check("5 FPM_OPEN_NO_ROUTE=1 → 판정 우회", DOC_URL in run(DOC_URL, dict(ENV, FPM_OPEN_NO_ROUTE="1")))

srv.shutdown()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
