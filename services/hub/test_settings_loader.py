#!/usr/bin/env python3
# test_settings_loader.py — Issue168 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 설정 모달 raw 로더
#   (_load_hub_setting_raw / _cast_setting_value)를 검증한다.
#
# 실행: python3 services/hub/test_settings_loader.py
"""server.py 설정 모달 raw 로더 단위 테스트."""
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


SAMPLE = """# 헤더 주석
feed_limit: 300            # 인라인 주석
feed_default_visible: true
default_browser: chrome
browser_tab_reuse: false
render_target: hub
live_session_order: project
card_limit: 0
bind_host: 127.0.0.1
# advertise_host: 192.168.0.10  # 주석처리 optional
"""


def with_sample(content):
    fd, path = tempfile.mkstemp(suffix=".yml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    server.HUB_SETTING_FILE = path
    return path


def main():
    path = with_sample(SAMPLE)
    try:
        v = server._load_hub_setting_raw()
        # 타입 캐스팅
        check("feed_limit int", v["feed_limit"] == 300 and isinstance(v["feed_limit"], int))
        check("feed_default_visible bool", v["feed_default_visible"] is True)
        check("browser_tab_reuse false", v["browser_tab_reuse"] is False)
        # 인라인 주석 제거
        check("default_browser strip comment", v["default_browser"] == "chrome")
        check("render_target select", v["render_target"] == "hub")
        check("live_session_order", v["live_session_order"] == "project")
        # 0 값 보존 (무제한)
        check("card_limit 0", v["card_limit"] == 0)
        # 주석처리 optional → 미설정(빈 문자열)
        check("advertise_host unset", v["advertise_host"] == "")
        # 파일에 없는 키 → 스키마 폴백
        check("search_limit fallback", isinstance(v["search_limit"], int))
        check("all schema keys present", all(s["key"] in v for s in server.HUB_SETTING_SCHEMA))
    finally:
        os.unlink(path)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
