#!/usr/bin/env python3
# test_bots_scope_windows_issue606.py — Issue606 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
#
# 왜 이 테스트가 필요한가 — Windows 네이티브 Python 에는 os.uname 이 없다. _collect_bots() 가
#   bots_scope 를 os.uname().nodename 으로 구하던 탓에 /boards 요청마다 AttributeError 로
#   연결이 끊기고 hub 메인 화면이 «Loading…» 에서 멈췄다(2026-10-05 jpc1 Windows 10 실측).
#   macOS·Linux 에서는 재현되지 않으므로 os.uname 을 지운 상태로 Windows 조건을 만든다.
#
# 실행: python3 services/hub/test_bots_scope_windows_issue606.py
"""bots_scope 가 os.uname 없이(Windows) 구해지는지 검증."""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402
from test_fbot_bots import build_fixture  # noqa: E402

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


def main():
    print("== bots_scope Windows 호환 (Issue606) ==")

    # 1) os.uname 부재(Windows) — 봇이 있는 정상 경로에서 예외 없이 bots_scope 가 나와야 한다
    saved = getattr(os, "uname", None)
    try:
        if saved is not None:
            del os.uname
        with tempfile.TemporaryDirectory() as tmp:
            build_fixture(tmp)
            try:
                r = server._collect_bots()
                err = None
            except AttributeError as e:
                r, err = {}, e
        check("os.uname 부재에서 _collect_bots 예외 없음", err is None)
        scope = r.get("bots_scope")
        check("bots_scope 는 비어 있지 않은 문자열", isinstance(scope, str) and scope != "")
        check("bots_scope 는 도메인 접미 없는 짧은 호스트명", isinstance(scope, str) and "." not in scope)
    finally:
        if saved is not None:
            os.uname = saved

    # 2) 정적 — hub 서버 코드에 os.uname( 호출이 다시 들어오지 않는다
    with open(os.path.join(HERE, "server.py"), encoding="utf-8") as f:
        src = f.read()
    hits = [i + 1 for i, line in enumerate(src.splitlines())
            if re.search(r"\bos\.uname\(", line) and not line.lstrip().startswith("#")]
    check(f"server.py 에 os.uname( 호출 없음 (적중 행 {hits})", not hits)

    print(f"결과: pass {PASS} · fail {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
