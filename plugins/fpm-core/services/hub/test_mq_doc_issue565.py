#!/usr/bin/env python3
# test_mq_doc_issue565.py — Issue565 회귀 테스트 (서버 절반)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `/mq-doc?id=` 문서 뷰를 검증한다.
#   큐 표의 내용 열은 개행까지 뭉개 한 덩어리 산문으로 보인다 — `1) … 2) …` 번호 목록과
#   `①②③` 하위 항목이 있는 결정 묶음은 특히 읽을 수 없다. 문서 뷰는 `..show` 와 같은
#   md-doc 셸로 mq 1건을 **구조화해서** 보여 준다. 이 테스트가 지키는 것은 넷이다:
#     ① md 조립 — 제목(` — ` 앞)·태그 칩·번호 목록·원문자 하위 불릿·문장 불릿·정보 표·진행 절
#     ② 저작 내용은 **마크업이 되지 않는다** — `*`·`_`·`<` 가 그대로 글자로 남고, 경로는 code
#     ③ 참조는 **열 수 있는 것만** 링크 — `prjN#IssueM` → /issue, mq id → /mq-doc (자기 자신 제외)
#     ④ 조회 — id 형식 밖(경로 탈출)은 거부, 종결 40건 한도 밖도 열린다, 라우트는 md 셸을 낸다
#
# 실행: python3 plugins/fpm-core/services/hub/test_mq_doc_issue565.py
"""server.py `_mq_item_md` · `_mq_find_item` · `/mq-doc` 라우트 단위 테스트."""
import io
import json
import os
import re
import sys
import tempfile
from urllib.parse import urlparse

# ⚠️ MQ_DIR 은 **import 시점**에 env 로 굳는다 — server import 보다 먼저 세워야 한다.
SANDBOX = tempfile.mkdtemp(prefix="mq565-")
os.environ["AOA_MQ_DIR"] = SANDBOX
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402
import md_shell  # noqa: E402

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


QUEUE = os.path.join(SANDBOX, "queue")
DONE = os.path.join(SANDBOX, "queue_done")
os.makedirs(QUEUE)
os.makedirs(DONE)


def put(d, item):
    with io.open(os.path.join(d, item["id"] + ".json"), "w", encoding="utf-8") as fh:
        json.dump(item, fh, ensure_ascii=False)


# 실례 그대로 — 사용자가 «산문이라 보기 좋지 않다» 고 짚은 항목(2026-09-28 스크린샷)
DECISION = {
    "id": "20260928-102923-001", "type": "scheduled", "kind": "pre",
    "created_ts": "2026-09-28T10:29:23", "due_ts": "2026-09-28T09:00:00",
    "status": "due", "ask_count": 0, "source": "claude@.claude",
    "message": (
        "[컨펌] [H:배포] 사용자 결정 묶음 (2026-09-28) — 되돌릴 수 없거나 밖에서 보이는 것 6건만. "
        "나머지(다른 prj 이슈 등록·매뉴얼·내부 정책) 14건은 C 등급으로 결정·진행함 (prj3#Issue756)\n"
        "1) [H:배포] prj1#Issue556 release/0.8.3 출고 — 재검증(deploy-chain-integrity fail) → main 병합 → "
        "deploy --with-marketplace. 끝나면 prj6#Issue17 마무리 push(리마인드 20260928-001145-001)가 이어서 돈다\n"
        "2) [H:배포] prj26 fWarrangeCli Homebrew tap·npm 배포 — 할지·언제 (push 는 완료 c7323f7)\n"
        "3) [H:스토어·공개·법무] prj16 Issue265 App Store 1.1.1 — ① Connect 제출(archive·메타데이터·심사, "
        "Distribution 서명) ② 스크린샷 화면 선정(기능·장수·순서, 창 단독 재촬영) ③ finfra.kr privacy.html "
        "앱 조항 게시 (원문 20260927-144540-001)\n"
        "4) [H:브랜드] prj25 fSnippetCli Issue238 — 공식 앱 아이콘을 resources/official/ 로 분리해 소스 빌드는 "
        "기본 아이콘으로 할지\n"
        "5) [H:공개] m2slide 발행 덱 4개 subtitle 평문 정리 후 재발행 여부 — 원고 정리는 prj42#Issue422 로 진행(C)\n"
        "6) [H:계정] prj5 Issue95 typesafe.ai 가입·키 발급 재개 여부 (리마인드 20260926-113830-001, 09-29)"),
}
SINGLE = {
    "id": "20260928-001145-001", "type": "scheduled", "status": "in_progress",
    "due_ts": "2026-09-28T09:00:00", "source": "claude@___oracle",
    "message": ("prj6#Issue17 라이선스 재동기 잔여 5건 점검 — prj26#Issue105 · prj1#Issue556 이 전부 ✅ 인지 확인. "
                "전부 끝났으면 prj6 세션(~/_git/___oracle)에서 «마무리 push»(검수 → force 없음). 미완이면 snooze"),
    "claimed_by": "bot:fbot-lead-pm", "claimed_ts": "2026-09-28T00:20:00",
    "progress": "00:3x 재점검: 전부 ✅ + push 완료", "progress_ts": "2026-09-28T00:35:00",
    "result": "보고 /Users/x/_doc_work/htm/hub_htm_20260928_a_x.md 참조", "result_ts": "2026-09-28T01:00:00",
}
INLINE_ENUM = {"id": "20260928-000001-001", "status": "due", "source": "claude@x",
               "message": "점검 목록 1) A 확인 2) B 확인 3) C 확인"}
HOSTILE = {"id": "20260928-000002-001", "status": "due", "source": "claude@x",
           "message": "위험 문자 점검\n*강조 아님* <b>태그</b> a_b_c [링크 아님](http://evil) 1. 목록 아님"}
MARKDOWN = {"id": "20260928-000003-001", "status": "due", "source": "claude@x",
            "message": "표 정리\n| a | b |\n| --- | --- |\n| 1 | 2 |"}
for it in (DECISION, SINGLE, INLINE_ENUM, HOSTILE, MARKDOWN):
    put(QUEUE, it)
# 종결분 45건 — `_mq_collect` 는 최근 40건만 싣는다. 가장 오래된 것도 문서로는 열려야 한다
for i in range(45):
    put(DONE, {"id": "20260901-%06d-001" % i, "status": "confirmed", "message": "끝 %d" % i})

if not hasattr(server, "_mq_item_md") or not hasattr(server, "_mq_find_item"):
    check("server 에 _mq_item_md · _mq_find_item 이 있다", False)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1)


def body_of(md):
    return md_shell.split_frontmatter(md)


# ── ① md 조립 ─────────────────────────────────────────────────────────────
meta, md = body_of(server._mq_item_md(DECISION))
check("frontmatter 제목 = 📮 + ` — ` 앞 (선두 태그 제외)",
      meta.get("title") == "📮 사용자 결정 묶음 (2026-09-28)", repr(meta.get("title")))
check("선두 태그는 칩(code)으로 — `컨펌` `H:배포`", "`컨펌` `H:배포`" in md)
check("본문에 제목을 되풀이하지 않는다 (헤더 h1 이 이미 제목)", not re.search(r"^# ", md, re.M))
check("리드 문장 불릿 — 첫 문장", re.search(r"^- 되돌릴 수 없거나 밖에서 보이는 것 6건만\.$", md, re.M), md[:400])
check("리드 문장 불릿 — 둘째 문장 + issue 링크",
      re.search(r"^- 나머지\(.*\[prj3#Issue756\]\(/issue\?prj=3&id=756\)", md, re.M))
for n in range(1, 7):
    check(f"번호 목록 {n}. 로 선다", re.search(rf"^{n}\. ", md, re.M))
check("번호 항목의 선두 태그도 칩 — 1. `H:배포`", re.search(r"^1\. `H:배포` \[prj1#Issue556\]", md, re.M))
check("원문자 → 하위 불릿 ①", re.search(r"^ {4}- ① Connect 제출", md, re.M))
check("원문자 → 하위 불릿 ③", re.search(r"^ {4}- ③ finfra\.kr", md, re.M))
item3 = (re.search(r"^3\. .*$", md, re.M) or [""])[0]
check("원문자를 쪼갠 머리 줄에는 ① 이 남지 않고 꼬리 ` —` 도 뗀다",
      "①" not in item3 and not item3.rstrip().endswith("—"), repr(item3))
check("`prjN IssueM`(공백) 도 링크", "[prj16 Issue265](/issue?prj=16&id=265)" in md)
check("다른 mq id 는 /mq-doc 링크", "[20260928-001145-001](/mq-doc?id=20260928-001145-001)" in md)
check("원문 mq id(원문자 항목 안)도 링크", "[20260927-144540-001](/mq-doc?id=20260927-144540-001)" in md)
check("경로는 code — `resources/official/` 는 선두 경계가 없어 경로가 아니다(글자 그대로)",
      "resources/official/" in md)
check("정보 표 — ID", "| ID | `20260928-102923-001` |" in md)
check("정보 표 — 상태 due · scheduled", re.search(r"^\| 상태 \| `due` · scheduled", md, re.M))
check("정보 표 — 마감 (T → 공백)", "| 마감 | 2026-09-28 09:00:00 |" in md)
check("정보 표 — 출처", "| 출처 | claude@.claude |" in md)
check("자기 id 는 링크하지 않는다", "(/mq-doc?id=20260928-102923-001)" not in md)
check("진행 기록이 없으면 진행 절이 없다", "## 진행" not in md)

meta, md = body_of(server._mq_item_md(SINGLE))
check("code span 안은 이스케이프하지 않는다 — `in_progress` (백슬래시가 글자로 보인다)",
      "`in_progress`" in md and "`in\\_progress`" not in md)
check("단일 줄 — 제목 = ` — ` 앞", meta.get("title") == "📮 prj6#Issue17 라이선스 재동기 잔여 5건 점검",
      repr(meta.get("title")))
check("단일 줄 — 문장 3개가 불릿", len(re.findall(r"^- ", md.split("## 진행")[0], re.M)) == 3,
      md.split("## 진행")[0])
check("경로는 code 로 — `~/_git/___oracle`", "`~/_git/___oracle`" in md)
check("code 밖에는 ___ 가 날로 남지 않는다 (강조로 먹히지 않게)",
      "___" not in re.sub(r"`[^`]*`", "", md))
check("진행 절 — 집은 주체·진행·결과", "## 진행" in md and "**집은 주체**" in md
      and "**진행**" in md and "**결과**" in md)
check("결과 속 hub 문서 경로는 /md-doc 링크",
      "(/md-doc?path=%2FUsers%2Fx%2F_doc_work%2Fhtm%2Fhub_htm_20260928_a_x.md)" in md, md[-500:])

meta, md = body_of(server._mq_item_md(INLINE_ENUM))
check("한 줄 안의 `1) 2) 3)` 도 번호 목록으로 쪼갠다",
      all(re.search(rf"^{n}\. {c} 확인$", md, re.M) for n, c in ((1, "A"), (2, "B"), (3, "C"))), md)
check("쪼갠 앞부분은 제목", meta.get("title") == "📮 점검 목록", repr(meta.get("title")))

_, md = body_of(server._mq_item_md({"id": "20260928-000004-001", "status": "due",
                                     "message": "조사 점검\nprj1#Issue556을 먼저 보고 prj3#Issue84_2와 대조"}))
check("한글 조사가 붙어도 링크 — prj1#Issue556을 (한글도 \\w 라 \\b 가 서지 않는다)",
      "[prj1#Issue556](/issue?prj=1&id=556)을" in md, md)
check("서브이슈 번호도 링크 — prj3#Issue84_2와", "[prj3#Issue84_2](/issue?prj=3&id=84_2)와" in md, md)

meta, md = body_of(server._mq_item_md(HOSTILE))
body = md.split("## 정보")[0]
check("`*` 는 글자로 (이스케이프)", r"\*강조 아님\*" in body, body)
check("`_` 는 글자로 (이스케이프)", r"a\_b\_c" in body, body)
check("`<` 는 글자로 (태그가 되지 않는다)", "<b>" not in body, body)
check("`[..](..)` 는 링크가 되지 않는다", "](http://evil)" not in body.replace("\\]", ""), body)

meta, md = body_of(server._mq_item_md(MARKDOWN))
check("이미 md(표·펜스)인 본문은 그대로 통과", "| a | b |\n| --- | --- |\n| 1 | 2 |" in md, md)

# ── ④ 조회 ────────────────────────────────────────────────────────────────
for bad in ("../queue/x", "a/b", "", "..", "x" * 200, "%2e%2e"):
    try:
        server._mq_find_item(bad)
        check(f"형식 밖 id 거부 — {bad[:20]!r}", False)
    except ValueError:
        check(f"형식 밖 id 거부 — {bad[:20]!r}", True)
it, p = server._mq_find_item("20260928-102923-001")
check("미종결 조회 — 버킷 queue", it and it.get("_bucket") == "queue" and p.endswith("20260928-102923-001.json"))
it, p = server._mq_find_item("20260901-000000-001")
check("종결 40건 한도 밖도 열린다 — 버킷 done", it and it.get("_bucket") == "done")
it, p = server._mq_find_item("20990101-000000-001")
check("없는 id → (None, None)", it is None and p is None)


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


def get(url):
    h = _FakeHandler()
    h.path = url
    h._handle_mq_doc(urlparse(url))
    return h


if not hasattr(server.Handler, "_handle_mq_doc"):
    check("Handler._handle_mq_doc 가 있다", False)
else:
    h = get("/mq-doc?id=20260928-102923-001")
    page = h.raw.decode("utf-8", "replace")
    check("200 + md 셸(md-src JSON 임베드)", h._status == 200 and 'id="md-src"' in page)
    check("셸 헤더 h1 = 문서 제목", "<h1>📮 사용자 결정 묶음 (2026-09-28)</h1>" in page)
    check("CSP nonce 헤더", "nonce-" in (h.raw_headers.get("Content-Security-Policy") or ""))
    check("md 원문은 JSON 문자열로만 (`<` 이스케이프)", "\\u003c" in page or "<b>" not in page)
    h = get("/mq-doc?id=../../etc/passwd")
    check("경로 탈출 id → 400", h.json_responses and h.json_responses[0][0] == 400, str(h.json_responses))
    h = get("/mq-doc?id=20990101-000000-001")
    check("없는 id → 404", h.json_responses and h.json_responses[0][0] == 404, str(h.json_responses))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
