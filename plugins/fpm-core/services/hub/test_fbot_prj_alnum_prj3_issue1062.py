#!/usr/bin/env python3
# test_fbot_prj_alnum_prj3_issue1062.py — 핀봇 조직도·보드가 영숫자 prj id(`9t`)를 받는다 (prj3#Issue1061·1062)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 짝: prj3 `hooks/test-fbot-prj-id.py`(판정 단일 지점 `hooks/lib/fbot-prj.py`)
#   실발생 2026-10-10: prj3 가 fTyping(prj9t) 조직을 구성했는데 hub `/fbot-map?tab=org&prj=9t` 가
#   `isdigit()` 판정에 걸려 필터 없음(전체 뷰)으로 떨어졌다. 보드 셸은 `"prj=%d"` 라 문자열이면 TypeError.
#   계약: prj 파싱은 `_fbot_prj` 한 곳 — 해소기(`fbot-org.py`)의 `try_prj` 를 빌리고, 해소기가 없으면 같은 형식 폴백.
#
# 실행: python3 services/hub/test_fbot_prj_alnum_prj3_issue1062.py
import os
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
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
        print(f"  FAIL {name} {str(detail)[:200]}")


def main():
    print("== A 판정 단일 지점 _fbot_prj ==")
    f = getattr(server, "_fbot_prj", None)
    check("_fbot_prj 가 있다", callable(f))
    if callable(f):
        for raw, want in (("9t", "9t"), ("3", 3), ("prj9t", "9t"), ("9T", "9t"), (" 42 ", 42),
                          ("", None), (None, None), ("../x", None), ("9-t", None), ("t9", None), (7, 7)):
            got = f(raw)
            check(f"_fbot_prj({raw!r}) == {want!r}", got == want and type(got) is type(want), got)
        _orig = server._org_mod
        server._org_mod = lambda: None                 # 해소기 부재 — 폴백도 같은 판정
        try:
            check("해소기 부재 폴백: 9t", f("9t") == "9t")
            check("해소기 부재 폴백: 숫자는 int", f("12") == 12)
            check("해소기 부재 폴백: 형식 밖 None", f("a/b") is None)
        finally:
            server._org_mod = _orig

    print("== B 보드 셸이 문자열 prj 를 싣는다 ==")
    try:
        html = server._fbot_board_html("", "9t")
        check("prj=9t 가 쿼리에 실린다", "prj=9t" in html, html[:200])
    except Exception as e:
        check("문자열 prj 로 보드 셸 생성(TypeError 없음)", False, repr(e))
    check("숫자 prj 는 종전 그대로", "prj=3" in server._fbot_board_html("", 3))

    print("== C /fbot-map.json 이 9t 를 필터로 넘긴다 ==")
    seen = []
    _orig_data = server._fbot_board_data
    server._fbot_board_data = lambda root, prj: (seen.append(prj) or {"ok": True})
    sent = []

    class _H:
        def _send_json(self, status, body):
            sent.append((status, body))
    try:
        server.Handler._handle_fbot_map_json(_H(), urlparse("/fbot-map.json?prj=9t"))
        check("org_prj == '9t'", seen[-1:] == ["9t"], seen)
        server.Handler._handle_fbot_map_json(_H(), urlparse("/fbot-map.json?prj=..%2Fx"))
        check("형식 밖은 None(전체 뷰)", seen[-1:] == [None], seen)
    finally:
        server._fbot_board_data = _orig_data

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
