#!/usr/bin/env python3
# test_important_session_issue486.py — Issue486 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 중요 이벤트 R2(응답 정체)가
#   **어느 live 세션을 가리키는지**(sid/cwd/origin/session_url 부착)를 검증한다.
#
# 왜 이 테스트가 필요한가 — R2 칩은 종전에 feed_id 만 들고 있어 클릭해도 활동 피드로
#   스크롤하는 것이 전부였다. 세션으로 갈 수도, 실패했을 때 sid 를 넘겨줄 수도 없었다
#   (2026-09-08 실사고: fWarrangeCli 응답 27분 대기 칩에서 세션에 도달 불가).
#   한 프로젝트에 세션이 여러 개인 것이 상례이므로(실측 fWarrange/_public 에 vscode 1 +
#   terminal 1), "가장 최근 1개" 같은 근사는 오래 놀던 세션을 집는다. 알림 시각에 가장
#   가까운 세션을 고르는 규칙이 이 테스트의 본체다.
#
# 실행: python3 services/hub/test_important_session_issue486.py
# exit: 0=전부 PASS, 1=하나 이상 FAIL
"""중요 이벤트 R2 세션 해석(Issue486) 단위 테스트."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


compute = server.Handler._compute_important_events
CWD = "/tmp/prjX"
WAIT_EVENT = sorted(server.IMPORTANT_WAIT_EVENTS)[0]


def sess(sid, age, origin="vscode"):
    return {"cwd": CWD, "sid": sid, "origin": origin, "updated_age": age,
            "url": f"/s/hash/{sid}?token=T", "name": "prjX"}


def feed(ts, fid="F1"):
    return {"event": WAIT_EVENT, "cwd": CWD, "name": "prjX", "ts": ts, "id": fid}


def r2(events):
    """R2(⏳) 이벤트만 추린다 — R1/R3/R4 와 섞이지 않게."""
    return [e for e in events if e.get("icon") == "⏳"]


def main():
    now = time.time()
    # 대기 5분 초과 + 6h 미만이어야 R2 가 발화한다
    wait = server.IMPORTANT_RESPONSE_WAIT_SEC + 120

    print("== R2 이벤트에 세션 식별자가 실린다 (Issue486 핵심) ==")
    ev = r2(compute(None, [sess("S1", wait + 5)], [], [feed(now - wait)], []))
    check("R2 1건 발화", len(ev) == 1, f"{len(ev)}건")
    if ev:
        e = ev[0]
        check("sid 부착", e.get("sid") == "S1", repr(e.get("sid")))
        check("cwd 부착", e.get("cwd") == CWD, repr(e.get("cwd")))
        check("origin 부착", e.get("origin") == "vscode", repr(e.get("origin")))
        check("session_url 부착", "/s/hash/S1" in (e.get("session_url") or ""),
              repr(e.get("session_url")))
        check("feed_id 무회귀(기존 폴백 경로 유지)", e.get("feed_id") == "F1")

    print("== 같은 cwd 에 세션이 여럿이면 '알림 시각에 가장 가까운' 세션 ==")
    # OLD 는 10시간 놀고 있었고, WAIT 는 알림 시점 근처에 마지막으로 갱신됐다.
    #   최근순(updated_age 최소)으로 고르면 OLD 가 아니라 WAIT 가 뽑히는 게 맞지만,
    #   반대로 알림보다 **더 최근에** 갱신된 세션이 있으면 최근순은 그쪽을 집는다.
    #   아래 NEWER(갱신 30초 전)가 그 함정이다 — 정답은 여전히 WAIT.
    sessions = [sess("NEWER", 30), sess("WAIT", wait + 10), sess("OLD", 36000)]
    ev = r2(compute(None, sessions, [], [feed(now - wait)], []))
    check("가장 최근이 아니라 알림 시각 근접 세션 선택",
          ev and ev[0].get("sid") == "WAIT", ev[0].get("sid") if ev else "이벤트 없음")

    print("== 무회귀: live 세션 없는 cwd 는 R2 미발화 (Issue100 orphan 규칙) ==")
    ev = r2(compute(None, [], [], [feed(now - wait)], []))
    check("orphan wait 은 칩을 만들지 않는다", not ev, f"{len(ev)}건")

    print("== 무회귀: 5분 미만 대기는 미발화 ==")
    ev = r2(compute(None, [sess("S1", 10)], [], [feed(now - 10)], []))
    check("임계 미만 미발화", not ev, f"{len(ev)}건")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
