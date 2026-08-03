#!/usr/bin/env python3
# test_issue_map.py — Issue284 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 이슈맵 탐지(_issue_map_path) + /issue-map
#   라우트의 3중 게이트(loopback / 등록 프로젝트 트리 / 서버측 파일명 고정)를 검증한다.
#
# 실행: python3 services/hub/test_issue_map.py
# exit: 0=전부 PASS, 1=하나 이상 FAIL
"""server.py /issue-map 라우트 + 이슈맵 탐지 (Issue284) 단위 테스트."""
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


ISSUE_MD_DEPS = "# Issue Management\n\n## Issue2: b\n* depends: Issue1\n* 목적: x\n"
ISSUE_MD_NODEPS = "# Issue Management\n\n## Issue1: a\n* 목적: x\n"

TMP = tempfile.mkdtemp(prefix="issue-map-test-")
# prjA: Issue.md(depends 有) + Issue_map.htm 보유 (하위 폴더 sub/deep 포함)
PRJ_A = os.path.join(TMP, "prjA")
os.makedirs(os.path.join(PRJ_A, "sub", "deep"))
ISSUE_A = os.path.join(PRJ_A, "Issue.md")
open(ISSUE_A, "w").write(ISSUE_MD_DEPS)
MAP_A = os.path.join(PRJ_A, server.ISSUE_MAP_NAME)
open(MAP_A, "w").write("<html><body><h1>map A</h1></body></html>")
# prjB: Issue.md 만 보유 (맵 없음)
PRJ_B = os.path.join(TMP, "prjB")
os.makedirs(PRJ_B)
open(os.path.join(PRJ_B, "Issue.md"), "w").write(ISSUE_MD_DEPS)
# prjC: Issue.md 자체가 없음 (nPTiR 루트 아님)
PRJ_C = os.path.join(TMP, "prjC")
os.makedirs(PRJ_C)
# prjD: 맵은 있으나 Issue.md 에 depends 0 (Issue284_1 — 아이콘 미노출 대상)
PRJ_D = os.path.join(TMP, "prjD")
os.makedirs(PRJ_D)
open(os.path.join(PRJ_D, "Issue.md"), "w").write(ISSUE_MD_NODEPS)
MAP_D = os.path.join(PRJ_D, server.ISSUE_MAP_NAME)
open(MAP_D, "w").write("<html><body><h1>map D</h1></body></html>")
# outside: 화이트리스트 밖 — Issue.md + 맵을 가졌어도 serve 되면 안 됨
OUT = os.path.join(TMP, "outside")
os.makedirs(OUT)
open(os.path.join(OUT, "Issue.md"), "w").write(ISSUE_MD_DEPS)
open(os.path.join(OUT, server.ISSUE_MAP_NAME), "w").write("<html><body>leak</body></html>")


def _clear_cache():
    with server._issue_map_lock:
        server._issue_map_cache.clear()


# --- _issue_map_path 탐지 ---
_clear_cache()
check("맵 보유 프로젝트 루트 → 경로 반환",
      server._issue_map_path(PRJ_A) == os.path.realpath(MAP_A))
_clear_cache()
check("하위 폴더 cwd → 상위 Issue.md 폴더의 맵 탐지 (cwd 드리프트 대응)",
      server._issue_map_path(os.path.join(PRJ_A, "sub", "deep")) == os.path.realpath(MAP_A))
_clear_cache()
check("Issue.md 는 있으나 맵 부재 → None", server._issue_map_path(PRJ_B) is None)
_clear_cache()
check("Issue.md 자체 부재 → None", server._issue_map_path(PRJ_C) is None)
_clear_cache()
check("빈 cwd → None", server._issue_map_path("") is None)

# --- Issue284_1: 아이콘 노출 조건 = 맵 존재 AND depends 링크 보유 ---
_clear_cache()
check("depends 有 + 맵 有 → 아이콘 노출", server._issue_map_visible(PRJ_A) is True)
_clear_cache()
check("depends 無 + 맵 有 → 아이콘 미노출", server._issue_map_visible(PRJ_D) is False)
_clear_cache()
check("depends 無라도 serve 경로는 유효 (북마크 보존)",
      server._issue_map_path(PRJ_D) == os.path.realpath(MAP_D))
_clear_cache()
check("맵 無 → 아이콘 미노출", server._issue_map_visible(PRJ_B) is False)
_clear_cache()
check("빈 cwd → 아이콘 미노출", server._issue_map_visible("") is False)

check("depends 파서: `* depends: Issue1` 인식", server._issue_md_has_depends(ISSUE_A) is True)
check("depends 파서: depends 없는 Issue.md → False",
      server._issue_md_has_depends(os.path.join(PRJ_D, "Issue.md")) is False)
check("depends 파서: 파일 부재 → False",
      server._issue_md_has_depends(os.path.join(TMP, "nope.md")) is False)
_DEP_VAR = os.path.join(TMP, "dep-variants.md")
open(_DEP_VAR, "w").write("* 목적: x\n    * depends: prj16#Issue42, Issue3\n")
check("depends 파서: 들여쓴 `* depends: prj16#Issue42` 인식",
      server._issue_md_has_depends(_DEP_VAR) is True)
_DEP_EMPTY = os.path.join(TMP, "dep-empty.md")
open(_DEP_EMPTY, "w").write("* depends:\n* depends:   \n")
check("depends 파서: 값 없는 `* depends:` 는 미인정",
      server._issue_md_has_depends(_DEP_EMPTY) is False)

# Issue284_3 — 완료(헤더 ✅ 접미) 이슈에만 달린 depends 는 미카운트
_DEP_DONE_ONLY = os.path.join(TMP, "dep-done-only.md")
open(_DEP_DONE_ONLY, "w").write(
    "## Issue1: a (해결) ✅\n* depends: Issue0\n\n"
    "### Issue1_2: a sub (해결) ✅\n* depends: Issue0\n"
)
check("depends 파서(Issue284_3): 완료 이슈만의 depends → False",
      server._issue_md_has_depends(_DEP_DONE_ONLY) is False)
_DEP_MIXED = os.path.join(TMP, "dep-mixed.md")
open(_DEP_MIXED, "w").write(
    "## Issue1: a (해결) ✅\n* depends: Issue0\n\n"
    "## Issue2: b\n* depends: Issue1\n"
)
check("depends 파서(Issue284_3): 완료+미완료 혼재 → 미완료 쪽으로 True",
      server._issue_md_has_depends(_DEP_MIXED) is True)

# TTL 캐시 — 첫 조회 후 파일을 지워도 캐시 유효기간 내엔 같은 값
_clear_cache()
first = server._issue_map_path(PRJ_A)
os.rename(MAP_A, MAP_A + ".bak")
check("TTL 캐시 히트 (파일 제거해도 만료 전엔 동일 결과)",
      server._issue_map_path(PRJ_A) == first)
_clear_cache()
check("캐시 무효화 후 재탐지 → 제거 반영 None", server._issue_map_path(PRJ_A) is None)
os.rename(MAP_A + ".bak", MAP_A)
_clear_cache()


# --- /issue-map 라우트 ---
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


# 화이트리스트 픽스처 — hub projects 테이블에 prjA/prjB/prjC 만 등록.
#   Projects.md 경유분(_load_projects_list)은 실제 파일을 읽으므로 TMP 와 무관.
with server.projects_lock:
    _projects_backup = dict(server.projects)
    server.projects.clear()
    for i, p in enumerate((PRJ_A, PRJ_B, PRJ_C, PRJ_D)):
        server.projects[f"test{i}"] = {"cwd": p, "name": os.path.basename(p)}


def _get(cwd, ip="127.0.0.1"):
    _clear_cache()
    h = _FakeHandler()
    h.client_address = (ip, 0)
    url = f"/issue-map?cwd={quote(cwd, safe='')}"
    h.path = url
    h._handle_issue_map(urlparse(url))
    return h


try:
    r = _get(PRJ_A)
    check("등록 프로젝트 + 맵 존재 → 200 HTML", r._status == 200 and b"map A" in r.raw)
    check("Content-Type text/html",
          (r.raw_headers.get("Content-Type") or "").startswith("text/html"))

    r = _get(os.path.join(PRJ_A, "sub", "deep"))
    check("등록 프로젝트 하위 폴더 cwd → 200 (prefix 매치)",
          r._status == 200 and b"map A" in r.raw)

    r = _get(PRJ_B)
    check("등록 프로젝트 + 맵 부재 → 404",
          r.json_responses and r.json_responses[0][0] == 404)

    r = _get(PRJ_D)
    check("Issue284_1: depends 無(아이콘 미노출) 프로젝트도 직접 URL 은 200",
          r._status == 200 and b"map D" in r.raw)

    r = _get(OUT)
    check("미등록 cwd(맵 보유) → 403 — 화이트리스트 밖 파일 미유출",
          r.json_responses and r.json_responses[0][0] == 403 and b"leak" not in r.raw)

    r = _get(PRJ_A, ip="192.168.0.9")
    check("Issue284_2: LAN 클라이언트도 200 (loopback 전용 게이트 제거 — /htm-doc 등급)",
          r._status == 200 and b"map A" in r.raw)

    # Issue284_2 게이트 3 — 등록 트리 안의 폴더지만 자체 Issue.md 가 없어 상향 탐색이
    # 등록 트리 **밖**(TMP 루트)의 Issue.md 로 빠져나가는 경우. 무관한 프로젝트의 맵을
    # serve 하면 안 된다.
    ESCAPE = os.path.join(PRJ_C, "nested")
    os.makedirs(ESCAPE, exist_ok=True)
    open(os.path.join(TMP, "Issue.md"), "w").write(ISSUE_MD_DEPS)
    open(os.path.join(TMP, server.ISSUE_MAP_NAME), "w").write("<html><body>escaped</body></html>")
    try:
        r = _get(ESCAPE)
        check("상향 탐색이 등록 트리 밖 Issue.md 로 탈출 → 403 (무관 프로젝트 맵 미유출)",
              r.json_responses and r.json_responses[0][0] == 403 and b"escaped" not in r.raw)
    finally:
        os.remove(os.path.join(TMP, "Issue.md"))
        os.remove(os.path.join(TMP, server.ISSUE_MAP_NAME))

    h = _FakeHandler()
    h.path = "/issue-map"
    h._handle_issue_map(urlparse("/issue-map"))
    check("cwd 누락 → 400", h.json_responses and h.json_responses[0][0] == 400)

    # 경로 조작 시도 — cwd 는 화이트리스트로 막히고, 파일명은 서버 고정이라
    # ../ 를 섞어도 결국 등록 트리 밖으로는 나갈 수 없다.
    r = _get(os.path.join(PRJ_A, "..", "outside"))
    check("../ traversal 로 미등록 트리 접근 → 403",
          r.json_responses and r.json_responses[0][0] == 403)
finally:
    with server.projects_lock:
        server.projects.clear()
        server.projects.update(_projects_backup)
    shutil.rmtree(TMP)

# --- Issue343: parse_dep_token 규약 준수 + 조용한 유실 차단 회귀 ---
# ⚠️ 검사 대상은 server.py 가 아니라 이슈맵 생성기다. 파서가 두 벌(원본 prj3 ·
#   배포본 plugins/fpm-core) 이므로 **양쪽 모두** 같은 픽스처로 돌린다 — 한쪽만
#   고치면 배포본 사용자가 구버전 동작을 만난다(2원 구조 반쪽 수정).
import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

# 위 블록의 finally 가 TMP 를 지웠으므로 자체 임시 디렉토리를 새로 잡는다
TMP2 = tempfile.mkdtemp(prefix="dep-token-test-")

def _find_bundled_bim():
    """번들 생성기를 **파일 위치에 의존하지 않고** 찾는다 (Issue348).

    이 테스트는 원본(services/hub/)과 배포본(plugins/fpm-core/services/hub/)
    양쪽에 같은 내용으로 놓인 2원 사본이라, 고정 `parents[N]` 은 한쪽에서만
    성립한다. 상향 탐색으로 실제 존재하는 경로를 잡는다.
    """
    rel = os.path.join("plugins", "fpm-core", "skills",
                       "fpm-issue-map", "build_issue_map.py")
    here = Path(os.path.abspath(__file__))
    for _base in here.parents:
        _cand = os.path.join(_base, rel)
        if os.path.exists(_cand):
            return _cand
    return os.path.join(here.parents[2], rel)   # 미발견 시 fail-loud 용 기존 기준


_BIM_PATHS = [
    os.path.expanduser("~/.claude/skills/issue-map/build_issue_map.py"),
    _find_bundled_bim(),
]

# (입력, 기대 반환, 경고종류) — 경고종류 None 이면 규약 준수라 경고가 없어야 한다.
#   실측 8케이스 (Issue343 상세, 2026.08.01)
_DEP_CASES = [
    ("Issue170 (충족)",                      ("local", None, "Issue170"), None),
    ("prj3#Issue269 (완료 — commit bd1cb38)", ("ext", "prj3", "Issue269"), None),
    ("prj16#Issue42",                        ("ext", "prj16", "Issue42"), None),
    ("`___pm#Issue66`",                      ("ext", "___pm", "Issue66"), "named_ref"),
    ("paidApp Issue892 (구현 주체)",          None,                        "unparsed"),
    ("`~/.claude` Issue148",                 None,                        "unparsed"),
    ("fSnippet#Issue951",                    ("ext", "fSnippet", "Issue951"), "named_ref"),
    ("social#Issue30",                       ("ext", "social", "Issue30"), "named_ref"),
    # 혼합 표기 — 마지막 토큰이 실제 참조 대상이라 prj55 로 정규화되어야 한다
    ("air-gap-claudeCode prj55#Issue9",      ("ext", "prj55", "Issue9"),  None),
    ("없음",                                  None,                        None),  # 정상 no-op
    ("(없음)",                                None,                        None),  # 괄호 부기형 — 규약 허용
]

for _bim in _BIM_PATHS:
    _label = "원본" if ".claude" in _bim else "배포본"
    if not os.path.exists(_bim):
        check(f"[{_label}] 생성기 존재", False)
        continue
    _spec = importlib.util.spec_from_file_location(f"bim_{_label}", _bim)
    _bm = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_bm)

    for _tok, _want, _warn_kind in _DEP_CASES:
        check(f"[{_label}] parse_dep_token({_tok!r})",
              _bm.parse_dep_token(_tok) == _want)

    # 파싱 실패·이름 표기가 실제로 **수집**되는지 — 반환값만 맞고 경고가 없으면
    # Issue343 이 잡으려던 '조용한 유실' 이 그대로 남는다.
    _md = os.path.join(TMP2, f"dep-warn-{_label}.md")
    _body = "# 📙 일반\n\n"
    for _i, (_tok, _, _) in enumerate(_DEP_CASES, start=1):
        _body += f"## Issue{_i}: t{_i}\n* 목적: x\n* depends: {_tok}\n\n"
    open(_md, "w").write(_body)
    _warn = []
    _bm.parse_issue_md(Path(_md), warn=_warn)
    _kinds = sorted(k for k, _, _ in _warn)
    _want_kinds = sorted(w for _, _, w in _DEP_CASES if w)
    check(f"[{_label}] depends 규약 위반 수집 (기대 {len(_want_kinds)}건)",
          _kinds == _want_kinds)
    check(f"[{_label}] warn 미지정 시 종전 동작(수집 없음)",
          _bm.parse_issue_md(Path(_md)) is not None)

shutil.rmtree(TMP2)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
