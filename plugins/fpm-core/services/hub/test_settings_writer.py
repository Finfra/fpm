#!/usr/bin/env python3
# test_settings_writer.py — Issue168 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 설정 모달 주석보존
#   라이터(_write_hub_setting)와 검증(_validate_setting)을 검증한다.
#
# 실행: python3 services/hub/test_settings_writer.py
"""server.py 설정 모달 주석보존 라이터 단위 테스트."""
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


SAMPLE = """# 헤더 주석 (보존 대상)
feed_limit: 300            # 인라인 주석 (보존 대상)
default_browser: chrome
browser_tab_reuse: false
bind_host: 127.0.0.1       # bind 주소
# advertise_host: 192.168.0.10  # 주석처리 optional
render_target: hub
"""


def fresh():
    fd, path = tempfile.mkstemp(suffix=".yml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SAMPLE)
    server.HUB_SETTING_FILE = path
    return path


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    # 1. 값 변경 + 주석 보존
    path = fresh()
    try:
        ok, restart, code, err = server._write_hub_setting({"feed_limit": 150, "default_browser": "firefox"})
        check("write ok", ok and code == 200)
        txt = read(path)
        check("feed_limit updated", "feed_limit: 150" in txt)
        check("inline comment preserved", "# 인라인 주석 (보존 대상)" in txt)
        check("header comment preserved", "# 헤더 주석 (보존 대상)" in txt)
        check("default_browser updated", "default_browser: firefox" in txt)
        check("untouched key preserved", "render_target: hub" in txt)
    finally:
        os.unlink(path)

    # 2. optional 키 활성화 (주석 → 활성)
    path = fresh()
    try:
        ok, *_ = server._write_hub_setting({"advertise_host": "192.168.0.50"})
        txt = read(path)
        check("optional activated", "\nadvertise_host: 192.168.0.50" in txt)
        v = server._load_hub_setting_raw()
        check("optional readback", v["advertise_host"] == "192.168.0.50")
    finally:
        os.unlink(path)

    # 3. 위험 조합 차단: bind_host 0.0.0.0 + advertise 미설정
    path = fresh()
    try:
        ok, restart, code, err = server._write_hub_setting({"bind_host": "0.0.0.0"})
        check("danger combo rejected", (not ok) and code == 400)
        check("file unchanged on reject", "bind_host: 127.0.0.1" in read(path))
    finally:
        os.unlink(path)

    # 4. 위험 조합 허용: 0.0.0.0 + advertise 동시 지정
    path = fresh()
    try:
        ok, *_ = server._write_hub_setting({"bind_host": "0.0.0.0", "advertise_host": "10.0.0.1"})
        check("0.0.0.0 with advertise ok", ok)
    finally:
        os.unlink(path)

    # 5. 검증 실패: unknown key / 잘못된 타입 / select 범위 밖
    path = fresh()
    try:
        check("unknown key 400", server._write_hub_setting({"nope": 1})[2] == 400)
        check("bad type 400", server._write_hub_setting({"feed_limit": "x"})[2] == 400)
        check("select out of range 400", server._write_hub_setting({"render_target": "bogus"})[2] == 400)
        check("number below min 400", server._write_hub_setting({"feed_limit": 0})[2] == 400)
    finally:
        os.unlink(path)

    # 6. restart_required 집계 (bind_host 변경 시)
    path = fresh()
    try:
        ok, restart, code, err = server._write_hub_setting({"bind_host": "192.168.0.9", "advertise_host": "192.168.0.9"})
        check("restart_required has bind_host", "bind_host" in restart)
    finally:
        os.unlink(path)

    # 7. 동시편집 감지 (client_mtime mismatch → 409)
    path = fresh()
    try:
        code = server._write_hub_setting({"feed_limit": 99}, client_mtime=1.0)[2]
        check("stale mtime 409", code == 409)
    finally:
        os.unlink(path)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
