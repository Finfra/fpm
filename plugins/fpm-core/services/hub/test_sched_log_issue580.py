#!/usr/bin/env python3
# test_sched_log_issue580.py — Issue580 회귀 테스트 (서버 절반)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `/sched-log?job=<잡>[&run=<pid>]` 잡 로그 뷰를 검증한다.
#   스케줄·잡 탭은 원장의 시각·rc·소요만 보여 줘서 **무엇이 나왔는지**는 터미널로
#   `data/schedule/log/<잡>.out·.err` 를 열어야 알았다. 이 테스트가 지키는 것은 다섯이다:
#     ① 이름 검증 — 잡 이름(`_SCHED_NAME_RE`) + 스텝 접미(`#N`)만 통과, `../`·대문자·빈 접미는 거부
#     ② 경로는 서버가 조립 — 선언의 `log` 필드(없으면 prj3 기본 폴더), 없는 잡은 None(→ 404)
#     ③ 잡음(`bash -lc` 로그인 셸) 줄은 **접는다** — 지우지 않고 <details> 안에 남긴다
#     ④ 회차 — 로그에 경계 표식이 없으므로 거짓 절단 금지, 마지막 회차/이후 N회/원장에 없음을 말한다
#     ⑤ 저작 내용이 md 를 깨지 않는다 — 로그 안의 ``` 가 코드펜스를 닫지 못한다
#
# 실행: python3 plugins/fpm-core/services/hub/test_sched_log_issue580.py
"""server.py `_sched_log_label` · `_sched_log_md` · `/sched-log` 라우트 단위 테스트."""
import os
import sys
import tempfile
from urllib.parse import urlparse

# ⚠️ SCHEDULE_SH 는 **import 시점**에 env 로 굳는다 — 기본 로그 폴더가 그 조부모 기준이다.
SANDBOX = tempfile.mkdtemp(prefix="sched580-")
os.environ["SCHEDULE_SH"] = os.path.join(SANDBOX, "hooks", "schedule.sh")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"\n       {detail}" if detail else ""))


LOGDIR = os.path.join(SANDBOX, "data", "schedule", "log")
CUSTOM = os.path.join(SANDBOX, "custom-log")
os.makedirs(LOGDIR)
os.makedirs(CUSTOM)


def put(d, name, text):
    with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
        fh.write(text)


# 실례 형태 — prj5#Issue106 mq-collect 잡은 요약을 stdout 에 낸다. .err 에는 로그인 셸 잡음이 섞인다
put(LOGDIR, "mq-collect-lecture.out", "신규 10건 · 먼저 볼 3건\n사람 할 일: 없음\ncommit abc1234\n")
put(LOGDIR, "mq-collect-lecture.err",
    "tput: No value for $TERM and no -T specified\n"
    "/Users/x/.bashrc: line 3: iterm2_shell_integration: not found\n"
    "경고: 실제 오류 한 줄\n"
    "fpm: alias cdf 충돌\n")
put(LOGDIR, "multi#1.out", "스텝1 출력\n")
put(LOGDIR, "multi#2.out", "스텝2 출력\n")
put(LOGDIR, "multi#2.err", "스텝2 오류\n")
put(CUSTOM, "own-log.out", "자기 폴더 로그\n")
put(LOGDIR, "fence.out", "앞\n```\n# 제목 아님\n```\n뒤\n")

DATA = {
    "ok": True,
    "jobs": [
        {"name": "mq-collect-lecture", "log": None, "steps": [{"kind": "sh", "run": "x"}],
         "last": {"ts": "2026-09-28T09:00:05", "job": "mq-collect-lecture", "rc": "0", "detail": "5s pid=300 raw=0"}},
        {"name": "multi", "log": None, "steps": [{"kind": "sh", "run": "a"}, {"kind": "sh", "run": "b"}]},
        {"name": "own-log", "log": CUSTOM, "steps": [{"kind": "sh", "run": "x"}]},
        {"name": "fence", "log": None, "steps": [{"kind": "sh", "run": "x"}]},
        {"name": "silent", "log": None, "steps": [{"kind": "sh", "run": "x"}]},
    ],
    # 원장은 최신이 앞이다
    "runs": [
        {"ts": "2026-09-28T09:00:05", "event": "t-0900", "job": "mq-collect-lecture", "rc": "0", "detail": "5s pid=300 raw=0"},
        {"ts": "2026-09-27T09:00:05", "event": "t-0900", "job": "mq-collect-lecture", "rc": "0", "detail": "5s pid=200 raw=0"},
        {"ts": "2026-09-26T09:00:05", "event": "t-0900", "job": "mq-collect-lecture", "rc": "1", "detail": "5s pid=100"},
    ],
}

# ── ① 이름 검증 ─────────────────────────────────────────────────────────
L = getattr(server, "_sched_log_label", None)
check("_sched_log_label 이 있다", callable(L))
if callable(L):
    check("잡 이름 통과", L("mq-collect-lecture") == ("mq-collect-lecture", None))
    check("스텝 접미 통과", L("multi#2") == ("multi", 2))
    for bad in ("../etc/passwd", "Mq", "a/b", "multi#", "multi#x", "", "a" * 41, "-a", "a#1#2"):
        check(f"거부 — {bad!r}", L(bad) is None)

# ── ②~⑤ md 조립 ─────────────────────────────────────────────────────────
M = getattr(server, "_sched_log_md", None)
check("_sched_log_md 가 있다", callable(M))
if callable(M):
    check("없는 잡 → None", M("nope", DATA) is None)
    check("스텝 번호가 잡 스텝 수 밖 → None", M("multi#9", DATA) is None)

    md, path = M("mq-collect-lecture", DATA)
    check("기본 폴더(prj3 data/schedule/log) 에서 연다",
          path == os.path.join(LOGDIR, "mq-collect-lecture.out"), path)
    check("stdout 요약이 본문에 있다", "신규 10건 · 먼저 볼 3건" in md and "commit abc1234" in md)
    check("stderr 실제 오류 줄은 본문에 있다", "경고: 실제 오류 한 줄" in md)
    main, _, fold = md.partition("<details>")
    check("잡음은 <details> 로 접힌다", bool(fold) and "tput: No value" in fold and "fpm: alias cdf" in fold, md)
    check("잡음은 접힘 밖 본문에 없다", "tput: No value" not in main)
    check("잡음 줄 수를 요약에 적는다", "잡음 3줄" in md, md)
    check("run 없으면 회차 구분 불가를 알린다", "회차 구분 불가" in md)

    md, _ = M("mq-collect-lecture", DATA, run="300")
    check("마지막 회차 — «마지막 실행» 안내", "마지막 실행" in md and "회차 구분 불가" in md, md)
    check("그 회차 원장 행을 싣는다", "2026-09-28 09:00:05" in md and "pid=300" in md)
    md, _ = M("mq-collect-lecture", DATA, run="100")
    check("과거 회차 — 이후 2회 더 실행됐다고 말한다", "2회 더" in md, md)
    check("과거 회차 rc=1 을 싣는다", "rc=1" in md or "| 1 |" in md, md)
    md, _ = M("mq-collect-lecture", DATA, run="999")
    check("원장에 없는 pid — 찾지 못했다고 말한다", "찾지 못" in md, md)
    # 실측(2026-09-28): 시스템 잡이 5분마다 원장을 채워 daily-digest(07:04) 가 runs 창 밖으로 밀렸다.
    #   「최근」 칸 링크는 잡의 `last` 에서 pid 를 싣는다 — 창 밖이어도 마지막 실행으로 알아봐야 한다
    FAR = dict(DATA, runs=[r for r in DATA["runs"] if r["job"] != "mq-collect-lecture"])
    md, _ = M("mq-collect-lecture", FAR, run="300")
    check("runs 창 밖 — 잡 last 로 마지막 실행을 알아본다", "마지막 실행" in md and "찾지 못" not in md, md)

    md, path = M("multi", DATA)
    check("다단계 잡 — 스텝별 절", "multi#1" in md and "multi#2" in md and "스텝1 출력" in md and "스텝2 오류" in md, md)
    md, _ = M("multi#2", DATA)
    check("스텝 지목 — 그 스텝만", "스텝2 출력" in md and "스텝1 출력" not in md)

    md, path = M("own-log", DATA)
    check("선언 log 폴더를 따른다", "자기 폴더 로그" in md and path.startswith(CUSTOM), path)

    md, _ = M("silent", DATA)
    check("로그 파일이 없으면 없다고 말한다", "로그 파일 없음" in md, md)

    md, _ = M("fence", DATA)
    body = md.split("## ", 1)[1] if "## " in md else md
    check("로그 안 ``` 가 펜스를 닫지 못한다 — 더 긴 펜스", "````" in md, md)
    check("로그 안 # 는 제목이 되지 않는다(펜스 안)", "\n# 제목 아님" in body)


# ── 라우트 ────────────────────────────────────────────────────────────────
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


server._schedule_collect = lambda runs=30: DATA


def get(url):
    h = _FakeHandler()
    h.path = url
    h._handle_sched_log(urlparse(url))
    return h


if not hasattr(server.Handler, "_handle_sched_log"):
    check("Handler._handle_sched_log 가 있다", False)
else:
    h = get("/sched-log?job=..%2Fetc")
    check("경로 탈출 → 400", h.json_responses and h.json_responses[0][0] == 400, h.json_responses)
    h = get("/sched-log?job=MQ")
    check("대문자 → 400", h.json_responses and h.json_responses[0][0] == 400)
    h = get("/sched-log?job=nope")
    check("없는 잡 → 404", h.json_responses and h.json_responses[0][0] == 404)
    h = get("/sched-log?job=mq-collect-lecture&run=1;rm")
    check("run 은 숫자만 → 400", h.json_responses and h.json_responses[0][0] == 400)
    h = get("/sched-log?job=multi%232")
    check("스텝 라벨(%23) → 200", h._status == 200, h.json_responses)
    h = get("/sched-log?job=mq-collect-lecture&run=300")
    page = h.raw.decode("utf-8", "replace")
    check("200 + md 셸(CSP)", h._status == 200 and "Content-Security-Policy" in h.raw_headers)
    check("본문이 실린다", "mq-collect-lecture" in page)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
