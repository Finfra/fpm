#!/usr/bin/env python3
# test_bind_partial_issue522.py — Issue522 회귀 테스트 (tdd playlist #10 hub-bind-partial-failure)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). bind 주소 일부가 실패한 hub 가
#   ① /healthz 로 bound_hosts·bind_failed 를 실측대로 보고하고
#   ② 배너(_bind_result_txt)가 설정값이 아니라 실제 성공 목록을 찍으며
#   ③ 주소가 풀리면 재시도 루프가 bind 를 복구(또는 상한 소진 시 포기 보고)하는지 검증한다.
#
#   배경: 재부팅 직후 tailscale utun 주소가 할당 전이라 그 bind 만 EADDRNOTAVAIL 로 빠졌는데,
#   배너가 설정값을 찍어 «다 열렸다» 로 읽혔다 — 조용한 부분 실패(debug_TECH 2026-09-26).
#
#   격리: FPM_TMP_ROOT 를 임시 폴더로 두고 import 한다(운영 hub 상태 무접촉, Issue518).
#   포트는 OS 가 고른 빈 포트 — 운영 9876 무접촉. 실패 주소는 TEST-NET-1(192.0.2.1, RFC 5737)
#   — 어떤 인터페이스에도 할당되지 않아 bind 가 결정적으로 실패한다.
#
# 실행: python3 services/hub/test_bind_partial_issue522.py
"""hub 부분 bind 실패 보고·복구 테스트."""
import json
import shutil
import os
import socket
import sys
import tempfile
import threading
import urllib.request

_TMP = tempfile.mkdtemp(prefix="hub-bind522-")
os.environ["FPM_TMP_ROOT"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0
DEAD = "192.0.2.1"  # TEST-NET-1 — 미할당 주소


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _reset():
    with server.BIND_STATE_LOCK:
        server.BOUND_HOSTS[:] = []
        server.BIND_FAILED.clear()
    server.BIND_DONE.clear()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_partial_bind_reported():
    print("[1] 실제 소켓 부분 실패 → /healthz·배너")
    _reset()
    port = _free_port()
    servers = server._bind_all(["127.0.0.1", DEAD], port, server.Handler)
    try:
        check("살아 있는 주소만 서버가 생긴다", [h for h, _ in servers] == ["127.0.0.1"],
              f"got={[h for h, _ in servers]}")
        check("BIND_FAILED 에 실패 주소", list(server.BIND_FAILED) == [DEAD],
              f"got={dict(server.BIND_FAILED)}")
        check("BIND_DONE 이 선다", server.BIND_DONE.is_set())

        old_port = server.PORT
        server.PORT = port
        try:
            txt = server._bind_result_txt()
        finally:
            server.PORT = old_port
        check("배너가 실제 성공 목록을 찍는다(설정값 아님)",
              txt.startswith(f"['127.0.0.1']:{port}") and DEAD in txt and "failed=" in txt,
              f"got={txt!r}")

        srv = servers[0][1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
            body = json.loads(r.read().decode())
        check("/healthz bound_hosts = 실측", body.get("bound_hosts") == ["127.0.0.1"],
              f"got={body.get('bound_hosts')}")
        check("/healthz bind_failed = 실패 주소", body.get("bind_failed") == [DEAD],
              f"got={body.get('bind_failed')}")
        check("/healthz status 는 ok 유지(루프백은 살아 있다)", body.get("status") == "ok")
    finally:
        if servers:
            servers[0][1].shutdown()  # serve_forever 스레드 종료
        for _, s in servers:
            s.server_close()


class _FakeServer:
    def __init__(self, addr):
        self.addr = addr

    def serve_forever(self):
        pass


def test_retry_recovers():
    print("[2] 주소가 풀리면 재시도가 복구")
    _reset()
    with server.BIND_STATE_LOCK:
        server.BOUND_HOSTS[:] = ["127.0.0.1"]
        server.BIND_FAILED[DEAD] = "[Errno 49] Can't assign requested address"
    calls = []

    def factory(addr, handler):
        calls.append(addr)
        if len(calls) < 3:  # 처음 2회는 아직 주소 미할당
            raise OSError(49, "Can't assign requested address")
        return _FakeServer(addr)

    server._bind_retry_loop(1, server.Handler, interval=0, max_tries=5,
                            factory=factory, sleep=lambda s: None)
    check("3번째 시도에서 복구", len(calls) == 3, f"calls={len(calls)}")
    check("BIND_FAILED 가 비워진다", not server.BIND_FAILED, f"got={dict(server.BIND_FAILED)}")
    check("BOUND_HOSTS 에 복구 주소 추가", server.BOUND_HOSTS == ["127.0.0.1", DEAD],
          f"got={server.BOUND_HOSTS}")


def test_retry_gives_up():
    print("[3] 끝내 안 풀리면 상한에서 포기하고 실패를 남긴다")
    _reset()
    with server.BIND_STATE_LOCK:
        server.BOUND_HOSTS[:] = ["127.0.0.1"]
        server.BIND_FAILED[DEAD] = "x"
    calls = []

    def factory(addr, handler):
        calls.append(addr)
        raise OSError(49, "Can't assign requested address")

    server._bind_retry_loop(1, server.Handler, interval=0, max_tries=4,
                            factory=factory, sleep=lambda s: None)
    check("max_tries 만큼만 시도", len(calls) == 4, f"calls={len(calls)}")
    check("실패 주소가 BIND_FAILED 에 남는다(최신 오류)",
          "49" in server.BIND_FAILED.get(DEAD, ""), f"got={dict(server.BIND_FAILED)}")
    check("BOUND_HOSTS 불변", server.BOUND_HOSTS == ["127.0.0.1"], f"got={server.BOUND_HOSTS}")


def main():
    print("[test_bind_partial_issue522]")
    test_partial_bind_reported()
    test_retry_recovers()
    test_retry_gives_up()
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
