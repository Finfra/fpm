#!/usr/bin/env python3
"""Issue551 — `_fbot_org_seats` 스냅샷 캐시(single-flight · stale-while-revalidate) + 보드 JS 타임아웃.

계산 본체(`_fbot_org_seats_compute`)를 느린 stub 으로 바꿔 캐시 계층만 검증한다 — 실제 레지스트리·git 을
건드리지 않는다. 실행: python3 test_fbot_org_cache_issue551.py
"""
import os, sys, time, shutil, tempfile, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


def _stub(delay, log):
    def compute(prj=None):
        log.append(prj); time.sleep(delay)
        return {"seats": [{"id": "s1", "addr": f"{prj}/s1"}], "available": True, "prj": prj, "n": len(log)}
    return compute


def main():
    print("== single-flight ==")
    server._org_seats_invalidate()
    calls = []
    server._fbot_org_seats_compute = _stub(0.3, calls)
    server._org_seats_sig = lambda: "sig1"
    res = [None] * 6
    ths = [threading.Thread(target=lambda i=i: res.__setitem__(i, server._fbot_org_seats(None))) for i in range(6)]
    t = time.time(); [th.start() for th in ths]; [th.join() for th in ths]; dt = time.time() - t
    check("동시 6요청 → 계산 1회", len(calls) == 1)
    check("전부 같은 결과", all(r == res[0] for r in res) and res[0]["n"] == 1)
    check("대기 시간 ≈ 계산 1회(0.3s) — 직렬 1.8s 아님", dt < 0.9)

    print("== TTL 내 캐시 ==")
    server._fbot_org_seats(None)
    check("TTL 내 재요청은 계산하지 않는다", len(calls) == 1)
    server._fbot_org_seats(7)
    check("prj 키는 별도 계산", len(calls) == 2 and calls[-1] == 7)

    print("== stale-while-revalidate ==")
    ts, val, sig = server._ORG_SEATS_CACHE[None]
    server._ORG_SEATS_CACHE[None] = (ts - server._ORG_SEATS_TTL - 1, val, sig)
    t = time.time(); r = server._fbot_org_seats(None); dt = time.time() - t
    check("만료 항목은 이전 값을 즉시 돌려준다", dt < 0.1 and r["n"] == 1)
    time.sleep(0.6)
    check("배경 스레드가 1회 재계산", len(calls) == 3)
    check("갱신 뒤 새 값", server._fbot_org_seats(None)["n"] == 3)

    print("== 조직 yml 서명 변경 ==")
    server._org_seats_sig = lambda: "sig2"
    t = time.time(); r = server._fbot_org_seats(None); dt = time.time() - t
    check("서명이 바뀌면 만료로 본다(즉시 반환 + 배경 갱신)", dt < 0.1 and r["n"] == 3)
    time.sleep(0.6)
    check("서명 변경 뒤 재계산 1회", len(calls) == 4)

    print("== 해산 무효화 ==")
    server._org_formed_invalidate()
    check("_org_formed_invalidate 가 스냅샷도 비운다", not server._ORG_SEATS_CACHE)
    server._fbot_org_seats(None)
    check("비운 뒤 첫 요청은 동기 계산", len(calls) == 5)

    print("== fbot-org.py 모듈 재로드 ==")
    src_path = os.path.expanduser("~/.claude/hooks/fbot-org.py")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "fbot-org.py"); shutil.copy(src_path, p)
        server._ORG_MOD_PATH = p; server._ORG_MOD = None
        m1 = server._org_mod(); m2 = server._org_mod()
        check("mtime 같으면 같은 모듈 객체", m1 is not None and m1 is m2)
        now = time.time(); os.utime(p, (now + 5, now + 5))
        m3 = server._org_mod()
        check("mtime 바뀌면 재로드", m3 is not None and m3 is not m1)
    server._ORG_MOD_PATH = src_path; server._ORG_MOD = None

    print("== 보드 JS 타임아웃 ==")
    js = server._FBOT_BOARD_JS
    load = next((l for l in js.splitlines() if "async function load(" in l), "")
    check("load() 가 AbortController 로 fetch 를 끊는다", "AbortController" in load and "signal" in load)
    check("지연 시 사용자에게 보이는 문구 + 재시도", "응답 지연" in load and "setTimeout(load" in load)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
