#!/usr/bin/env python3
# test_sched_result_issue593.py — Issue593 회귀 테스트 (서버 절반)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `/sched-result?job=<잡>` — 잡 «최신 결과 문서» 뷰.
#   경로는 서버가 prj3#Issue893 `result_latest.path` 에서 꺼내고(클라이언트는 라벨만), 선언을 신뢰하지 않고 재검증한다:
#     ① 라벨 형식 400 · 잡 없음 404 · result 없음/일치 0건 404
#     ② 재검증 403 — $HOME 밖 · 실존 아님 · dotfile(민감) · .md 아님
#     ③ 통과 200 + md 셸 · registry 무기록
#
# 실행: python3 plugins/fpm-core/services/hub/test_sched_result_issue593.py
import os
import sys
import tempfile
from urllib.parse import urlparse

SANDBOX = tempfile.mkdtemp(prefix="sched593-", dir=os.path.expanduser("~"))
os.environ["SCHEDULE_SH"] = os.path.join(SANDBOX, "hooks", "schedule.sh")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"\n       {detail}" if detail else ""))


def put(name, text):
    p = os.path.join(SANDBOX, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


good = put("2026.10.03_digest.md", "# 일일 다이제스트\n본문 XYZ\n")
dot = put(".secret.md", "비밀")
txt = put("out.txt", "텍스트")
htm = put("out.htm", "<p>x</p>")
OUT = "/tmp/outside593.md"
with open(OUT, "w") as fh:
    fh.write("밖")


def job(name, rl, result=("x/*.md",)):
    j = {"name": name, "steps": [{"kind": "sh", "run": "x"}], "result": list(result) if result is not None else None}
    j["result_latest"] = {"path": rl, "mtime": 1790000000} if rl else None
    return j


DATA = {"ok": True, "jobs": [
    job("good", good), job("nores", None, result=[]), job("zero", None),
    job("dotf", dot), job("txtf", txt), job("htmf", htm), job("outside", OUT),
    job("gone", os.path.join(SANDBOX, "nope.md")),
]}


class _W:
    def __init__(self, o): self.o = o
    def write(self, b): self.o.raw += b


class H(server.Handler):
    def __init__(self):
        self.client_address = ("127.0.0.1", 0)
        self.json_responses, self.raw, self.raw_headers, self._status = [], b"", {}, None
    def _send_json(self, s, b): self.json_responses.append((s, b))
    def send_response(self, s): self._status = s
    def send_header(self, k, v): self.raw_headers[k] = v
    def end_headers(self): pass
    @property
    def wfile(self): return _W(self)


server._schedule_collect = lambda runs=30: DATA


def get(url):
    h = H()
    h.path = url
    h._handle_sched_result(urlparse(url))
    return h


def code(h):
    return h.json_responses[0][0] if h.json_responses else h._status


if not hasattr(server.Handler, "_handle_sched_result"):
    check("Handler._handle_sched_result 가 있다", False)
else:
    reg_before = open(server.HTM_REGISTRY).read() if os.path.isfile(server.HTM_REGISTRY) else None
    check("라벨 형식 위반 → 400", code(get("/sched-result?job=..%2Fetc")) == 400)
    check("job 없음 → 400", code(get("/sched-result")) == 400)
    check("잡 없음 → 404", code(get("/sched-result?job=nope")) == 404)
    check("result 선언 없음 → 404", code(get("/sched-result?job=nores")) == 404)
    check("일치 0건 → 404", code(get("/sched-result?job=zero")) == 404)
    check("$HOME 밖 → 403", code(get("/sched-result?job=outside")) == 403)
    check("실존 아님 → 403", code(get("/sched-result?job=gone")) == 403)
    check("dotfile → 403", code(get("/sched-result?job=dotf")) == 403)
    check(".md 아님 → 403", code(get("/sched-result?job=txtf")) == 403)
    check(".htm 은 1차 범위 밖 → 403", code(get("/sched-result?job=htmf")) == 403)
    h = get("/sched-result?job=good")
    check("통과 → 200 + CSP 셸", h._status == 200 and "Content-Security-Policy" in h.raw_headers, (h._status, h.json_responses))
    check("본문이 실린다", "XYZ" in h.raw.decode("utf-8", "replace"))
    reg_after = open(server.HTM_REGISTRY).read() if os.path.isfile(server.HTM_REGISTRY) else None
    check("registry 무기록", reg_before == reg_after)
    server._schedule_collect = lambda runs=30: {"ok": False, "error": "x", "jobs": []}
    check("수집 실패 → 502", code(get("/sched-result?job=good")) == 502)

import shutil
shutil.rmtree(SANDBOX, ignore_errors=True)
os.remove(OUT)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
