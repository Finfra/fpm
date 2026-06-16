#!/usr/bin/env python3
# test_allowlist.py — Issue175 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 원격 접근 allowlist
#   (_load_server_allowlist / _ip_allowed)의 CIDR 서브넷 지원을 검증한다.
#
# 실행: python3 services/hub/test_allowlist.py
"""server.py allowlist CIDR(서브넷) 매칭 단위 테스트."""
import ipaddress
import os
import sys
import tempfile

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


SERVERS_SAMPLE = """# Favorite Servers
| id | Name | alias | Host | Port | User | Description | check |
|----|------|-------|------|------|------|-------------|-------|
| 1 | lan | l | 192.168.0.0/24 | 22 | u | subnet 허용 | O |
| 2 | bad | b | 999.0.0.0/8 | 22 | u | 잘못된 CIDR | O |
| 3 | localhost | lo | 127.0.0.1 | 22 | u | exact IP | O |
| 4 | skip | s | 10.0.0.0/8 | 22 | u | check=X skip | X |
"""


def main():
    # 1. _load_server_allowlist — CIDR 파싱 / 잘못된 CIDR skip / check=X skip
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SERVERS_SAMPLE)
    orig = server.SERVERS_MD
    server.SERVERS_MD = path
    try:
        ips, nets = server._load_server_allowlist()
    finally:
        server.SERVERS_MD = orig
        os.unlink(path)

    check("exact IP 적재", "127.0.0.1" in ips)
    check("CIDR 1개만 적재 (잘못된 CIDR + check=X skip)", len(nets) == 1)
    check("CIDR 값 192.168.0.0/24", str(nets[0]) == "192.168.0.0/24")

    # 2. _ip_allowed — 루프백 / exact / CIDR 멤버십 / 범위 밖 / invalid
    server.ALLOWED_IPS.clear()
    server.ALLOWED_NETS.clear()
    server.ALLOWED_IPS.update({"192.168.0.50"})
    server.ALLOWED_NETS.extend([
        ipaddress.ip_network("192.168.0.0/24"),
        ipaddress.ip_network("10.1.0.0/16"),
    ])
    try:
        check("loopback v4 허용", server._ip_allowed("127.0.0.1") is True)
        check("loopback v6 허용", server._ip_allowed("::1") is True)
        check("exact IP 허용", server._ip_allowed("192.168.0.50") is True)
        check("CIDR /24 내부 허용", server._ip_allowed("192.168.0.99") is True)
        check("CIDR /24 밖 거부", server._ip_allowed("192.168.1.10") is False)
        check("CIDR /16 내부 허용", server._ip_allowed("10.1.5.5") is True)
        check("CIDR /16 밖 거부", server._ip_allowed("10.2.0.1") is False)
        check("공개 IP 거부", server._ip_allowed("8.8.8.8") is False)
        check("invalid IP 거부", server._ip_allowed("garbage") is False)
    finally:
        server.ALLOWED_IPS.clear()
        server.ALLOWED_NETS.clear()

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
