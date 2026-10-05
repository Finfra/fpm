#!/usr/bin/env python3
# test_listen_backlog_issue513.py — Issue513 회귀 테스트 (tdd playlist #12 hub-listen-backlog)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). hub 서버의 listen backlog 가 socketserver 기본값
#   5 보다 크게 **실제 listen() 에 반영**되는지 검증한다.
#
#   배경: 기본 5 면 Firefox 의 호스트당 6 병렬 연결만으로 SYN 이 드롭되고, 브라우저는 SYN 재전송
#   간격(1~3초)만큼 멈춘 듯 보였다 — 「/mq 에서 브라우저가 죽는다」의 실체.
#   클래스 속성이 아니라 인스턴스 대입이면 listen 이 이미 끝나 반영되지 않는다(가짜 green 경로).
#
#   판정은 속성값이 아니라 **행동**이다 — accept 하지 않는 서버에 동시 연결 N 개를 걸어,
#   커널 accept 큐가 전부 받아 주는지 본다. 운영 포트(9876)는 건드리지 않는다(포트 0 = 임의).
#
# 실행: python3 services/hub/test_listen_backlog_issue513.py
"""HubHTTPServer listen backlog 행동 테스트."""
import http.server
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0
N_CONN = 20  # 기본 backlog 5 를 확실히 넘기는 동시 연결 수


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _connect_burst(cls):
    """accept 하지 않는 서버에 N_CONN 개 동시 연결 → 완료된 연결 수."""
    srv = cls(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    port = srv.server_address[1]
    socks, ok = [], 0
    try:
        for _ in range(N_CONN):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                ok += 1
            except OSError:
                pass
            socks.append(s)
    finally:
        for s in socks:
            s.close()
        srv.server_close()
    return ok


def main():
    print("[test_listen_backlog_issue513]")
    q = server.HubHTTPServer.request_queue_size
    check("HubHTTPServer.request_queue_size > 5 (클래스 속성)", q > 5, f"got={q}")
    check("request_queue_size 가 클래스 __dict__ 에 정의(인스턴스 대입 아님)",
          "request_queue_size" in server.HubHTTPServer.__dict__)

    ok = _connect_burst(server.HubHTTPServer)
    check(f"accept 없이 동시 연결 {N_CONN}개 전부 성립", ok == N_CONN, f"got={ok}")

    # 대조군 — 기본 backlog 5 에서는 일부가 막혀야 위 판정이 공허하지 않다
    #   (jm4 실측 5/20). 커널 여유분(+1 등)이 있어도 20 에는 못 미친다.
    base = _connect_burst(http.server.ThreadingHTTPServer)
    check(f"대조군 기본 backlog 5 는 {N_CONN}개를 못 받는다 (판별력)", base < N_CONN, f"got={base}")

    # 기동 경로가 실제로 HubHTTPServer 로 bind 하는지 (기본 클래스로 되돌아가면 무력)
    #   bind 는 _bind_all()(최초)·_bind_retry_loop()(재시도, Issue522) 가 소유한다.
    src = open(server.__file__, encoding="utf-8").read()
    body = src[src.index("\ndef _bind_all("):]
    check("_bind_all·_bind_retry_loop 기본 factory 가 HubHTTPServer",
          body.count("factory = factory or HubHTTPServer") == 2)
    check("main() 이 _bind_all 로 bind 한다", "servers = _bind_all(BIND_HOSTS, PORT, Handler)" in body)
    check("기동 경로에 ThreadingHTTPServer 직접 bind 없음", "ThreadingHTTPServer((" not in body)

    print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
