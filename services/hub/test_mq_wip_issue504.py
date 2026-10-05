#!/usr/bin/env python3
# test_mq_wip_issue504.py — Issue504 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `/mq` 표의 in_progress **경과 배지**를 검증한다.
#   감시 쪽 절반은 prj3#Issue638_1(`mcp/aoa-mq/aoa-mq-tick.sh` 7.7 절)이고, 이 테스트가
#   지키는 것은 둘이 **갈라지지 않는다**는 것이다:
#     ① 임계는 prj3 policy `wip_stale_hours` 를 읽는다 — 숫자를 hub 에 복제하지 않는다
#     ② 기준 시각 부재가 감시 면제가 되지 않는다 (started_at → 큐 파일 mtime 폴백)
#     ③ 그래도 못 읽으면 **미상을 드러낸다** — 화면에서 조용히 빠지면 in_progress 를
#        재발견할 경로가 없어진다(질의 선별·stale 정리 어느 쪽도 이 상태를 안 본다)
#
# 실행: python3 plugins/fpm-core/services/hub/test_mq_wip_issue504.py
"""server.py `_mq_policy` / `_mq_wip_age` / `_mq_collect` + /mq 배지 배선 단위 테스트."""
import json
import os
import sys
import tempfile
import time

# ⚠️ MQ_DIR 은 **import 시점**에 env 로 굳는다 — server import 보다 먼저 세워야 한다.
SANDBOX = tempfile.mkdtemp(prefix="mq504-")
os.environ["AOA_MQ_DIR"] = SANDBOX
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


NOW = int(time.time())
QUEUE = os.path.join(SANDBOX, "queue")
os.makedirs(QUEUE)
os.makedirs(os.path.join(SANDBOX, "queue_done"))


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def put(name, item, mtime=None):
    path = os.path.join(QUEUE, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(item, fh, ensure_ascii=False)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def policy(text):
    with open(os.path.join(SANDBOX, "policy.yml"), "w", encoding="utf-8") as fh:
        fh.write(text)


# --- ① 임계는 policy 를 읽는다 (복제 금지) ---------------------------------
policy("lock_stale_mins: 30\nwip_stale_hours: 6          # 주석 딸린 줄\n")
check("policy 값을 읽는다", server._mq_wip_stale_hours() == 6)
check("주석이 값에 섞이지 않는다", server._mq_policy("wip_stale_hours", "x") == "6")
policy("wip_stale_hours: 12\n")
check("policy 를 바꾸면 임계도 바뀐다 (하드코딩 아님)", server._mq_wip_stale_hours() == 12)
policy("wip_stale_hours:\n")            # 값이 빈 줄 — tick pol() 도 기본으로 떨어진다
check("빈 값은 tick 기본(6)", server._mq_wip_stale_hours() == 6)
policy("wip_stale_hours: 이상한값\n")
check("오염된 값도 tick 기본(6) — 예외로 /mq 를 죽이지 않는다", server._mq_wip_stale_hours() == 6)
os.remove(os.path.join(SANDBOX, "policy.yml"))
check("policy 부재도 tick 기본(6)", server._mq_wip_stale_hours() == 6)
policy("wip_stale_hours: 6\n")

# --- ② 경과 산출: started_at → mtime 폴백 ---------------------------------
check("started_at 기준", server._mq_wip_age({"started_at": iso(NOW - 5400)}, NOW)
      == (5400, "started_at"))
check("분 단위 ISO(초 없음)도 tick iso2epoch 와 같이 받는다",
      server._mq_wip_age({"started_at": time.strftime("%Y-%m-%dT%H:%M",
                                                      time.localtime(NOW - 3600))}, NOW)[1]
      == "started_at")
check("started_at 부재 → mtime 폴백",
      server._mq_wip_age({"_mtime": NOW - 7200}, NOW) == (7200, "mtime"))
check("파싱 불가 started_at 도 mtime 으로 떨어진다 (면제 아님)",
      server._mq_wip_age({"started_at": "어제쯤", "_mtime": NOW - 60}, NOW) == (60, "mtime"))
check("둘 다 없으면 미상을 드러낸다 (0 으로 위장하지 않음)",
      server._mq_wip_age({}, NOW) == (None, ""))

# --- ③ _mq_collect 적재 ----------------------------------------------------
put("20260919-000001-001", {"id": "under", "status": "in_progress",
                            "started_at": iso(NOW - 5400)})
put("20260919-000002-001", {"id": "over", "status": "in_progress",
                            "started_at": iso(NOW - 30 * 3600)})
put("20260919-000003-001", {"id": "fallback", "status": "in_progress"},
    mtime=NOW - 7 * 3600)
put("20260919-000004-001", {"id": "control", "status": "pending"})
out = server._mq_collect()
by_id = {it["id"]: it for it in out["items"]}
check("수집 자체는 성공 (배지가 파이프라인을 깨지 않는다)", out["ok"] and out["error"] is None)
check("임계를 payload 로 내려보낸다", out.get("wip_stale_hours") == 6)
check("임계미만 항목의 경과", by_id["under"]["_wip_age_sec"] == 5400)
check("임계초과 항목의 경과", by_id["over"]["_wip_age_sec"] == 30 * 3600)
check("mtime 폴백 항목이 기준을 밝힌다",
      by_id["fallback"]["_wip_basis"] == "mtime"
      and abs(by_id["fallback"]["_wip_age_sec"] - 7 * 3600) <= 2)
check("in_progress 아닌 항목엔 경과를 달지 않는다", "_wip_age_sec" not in by_id["control"])
check("두 항목이 임계를 사이에 두고 갈린다",
      (by_id["under"]["_wip_age_sec"] // 3600) < out["wip_stale_hours"]
      <= (by_id["over"]["_wip_age_sec"] // 3600))

# --- ④ 화면 배선 (JS 를 안 실어 보내면 서버 계산은 아무 데도 안 보인다) -----
page = server._MQ_PAGE_HTML
check("배지 생성기 존재", "function wipCell(x)" in page)
check("상태 열에 배선됨", "${wipCell(x)}" in page)
check("임계는 서버에서 받는다", "d.wip_stale_hours" in page)
check("임계 비교는 tick 과 같은 규칙(시간 내림 후 >=)",
      "Math.floor(s/3600)>=STALE_H" in page)
check("경과 배지 CSS 와 초과 강조가 함께 있다",
      ".wip{" in page and ".wip.stale" in page)
check("미상도 화면에 남는다", "경과 ?" in page)

print()
print(f"PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
