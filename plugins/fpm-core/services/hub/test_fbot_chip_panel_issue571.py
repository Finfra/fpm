#!/usr/bin/env python3
# test_fbot_chip_panel_issue571.py — 보드 요약 배지 전부 → 목록 (Issue571)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: 보드 요약 바에서 인박스·미종결만 누르면 목록이 나오고(prj1#Issue557) «작업중·수신대기·완료대기·
#   출근중·퇴근·열린 배분·교착·자리·공석» 은 `<span>` 이라 숫자만 보였다(2026-09-28 사용자 스크린샷).
#   목록은 **배지 수와 같은 기준**이어야 한다 — «작업중 2» 옆에 3명이 뜨면 둘 중 하나는 거짓말이다.
#
# 판정은 서빙되는 JS 원문(`chipRows`)을 뽑아 node 로 실행한다 — 재구현을 검사하면 회귀를 못 잡는다
#   (Issue402·560 과 같은 방식). 픽스처 payload 는 서버 순수 함수 `_fbot_board_payload` 가 만든다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_fbot_chip_panel_issue571.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


def _grab_line(src, prefix):
    for line in src.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"상수 미발견: {prefix}")


def _grab_js(src, name):
    """`function <name>(` 부터 짝 맞는 `}` 까지 — 서빙 원문 그대로."""
    i = src.index("function " + name + "(")
    j = src.index("{", src.index(")", i))
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError(f"함수 끝 미발견: {name}")


NOW = 1_000_000


def _fixture():
    def n(bid, state, **kw):
        d = {"bot_id": bid, "title": bid + " 핀봇", "role": "lead", "state": state, "root": bid}
        d.update(kw); return d
    nodes = [n("W1", "working", seat_id="chief"), n("W2", "working"), n("WI", "waiting_input"),
             n("WC", "waiting_child"), n("CI", "checkin"),
             n("CO1", "checkout"), n("CO2", "checkout"), n("CO3", "checkout"),
             {"bot_id": "GHOST", "title": "GHOST", "state": "", "orphan": True}]

    def e(src, dst, issue, status="open", ts=NOW - 100):
        return {"src": src, "dst": dst, "issue": issue, "status": status, "ts": ts, "job_id": "j-" + issue}
    dispatch = [
        e("W1", "W2", "A", ts=NOW - 500),        # 정상 열린 배분
        e("W1", "GHOST", "B", ts=NOW - 400),     # ⛔ 명부에 없음 (hard)
        e("W1", "CO3", "C", ts=NOW - 10),        # 🚀 스폰 대기 (유예 안)
        e("W1", "CO1", "D", ts=NOW - 90_000),    # ⏳ 대상이 퇴근함 (soft — 미종결)
        e("WI", "WC", "E", ts=NOW - 300),        # ⛔ 순환 WI→WC→WI
        e("WC", "WI", "F", ts=NOW - 200),
        e("W2", "W1", "G", status="done"),       # 끝난 배분 — 열린 배분 아님
    ]
    full = {"nodes": nodes, "dispatch": dispatch}
    dl = server._fbot_deadlocks(full, now=NOW)
    seat = lambda addr, sid, prj, occ, vac=False: {
        "addr": addr, "id": sid, "role": sid, "scope_prj": prj, "scope_title": "본사" if prj is None else f"prj{prj}",
        "dept": "d", "dept_label": "부서", "vacant": vac, "occupant": occ}
    org = {"available": True, "seats": [seat("hq/chief", "chief", None, "W1"), seat("7/lead", "lead", 7, "W2"),
                                        seat("7/qa", "qa", 7, "", True), seat("1/dev", "dev", 1, "", True)]}
    items = [{"id": "r1", "owner": "W1", "payload": '{"from":"sess-a","body":"요청"}', "created_at": NOW - 50}]
    return server._fbot_board_payload(full, org, inbox={"W1": 1}, dl=dl, now=NOW, inbox_items=items)


def main():
    src = server._FBOT_BOARD_JS
    d = _fixture()
    s = d["summary"]
    print("[픽스처 — 배지 수]")
    print("       " + json.dumps({k: s.get(k) for k in ("working", "waiting_input", "waiting_child", "checkin", "checkout",
                                                        "open_dispatch", "deadlocks", "spawning", "vacant", "inbox_open")},
                                 ensure_ascii=False))
    check("픽스처가 키마다 0 이 아닌 수를 만든다(공허한 0=0 비교 방지)",
          all((s.get(k) or 0) > 0 for k in ("working", "waiting_input", "waiting_child", "checkin", "checkout",
                                             "open_dispatch", "deadlocks", "spawning", "vacant", "inbox_open")))

    print("\n[화면 — 패널 배선]")
    bh = server._fbot_board_html("", None)
    check("공용 목록 패널 컨테이너(id=fb-chip-panel)", 'id="fb-chip-panel"' in bh)
    check("같은 배지 재클릭 = 접기 · 다른 배지 = 전환", "state.chip=state.chip===k?null:k" in src)
    check("패널 항목 클릭 위임 1벌", 'el("fb-chip-panel").addEventListener("click"' in src)

    node = shutil.which("node")
    if not node:
        print("  skip node 미설치 — summaryHtml·chipRows 검증 생략")
        print(f"\n{PASS} passed, {FAIL} failed")
        return 1 if FAIL else 0
    try:
        js = (_grab_line(src, "const esc") + "\n" + _grab_line(src, "const STATE_KEYS") + "\n"
              + _grab_js(src, "summaryHtml") + "\n" + _grab_js(src, "chipRows") + "\n")
    except (ValueError, AssertionError) as ex:
        check(f"summaryHtml·chipRows 서빙 원문 존재 ({ex})", False)
        print(f"\n{PASS} passed, {FAIL} failed")
        return 1
    js += "const d=" + json.dumps(d, ensure_ascii=False) + ";\n" + r"""
const keys=["working","waiting_input","waiting_child","checkin","checkout","open_dispatch","deadlocks","spawning","seats","inbox","nope"];
const out={}; for(const k of keys){ out[k]=chipRows(d,k); }
const s2=Object.assign({},d.summary,{unsettled:1});
out.__html=summaryHtml(s2,d.labels,null); out.__htmlOn=summaryHtml(s2,d.labels,"working");
console.log(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "chip.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([node, p], capture_output=True, text=True)
    try:
        o = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        check("summaryHtml·chipRows node 실행: " + (r.stderr or "")[:300], False)
        print(f"\n{PASS} passed, {FAIL} failed")
        return 1

    print("\n[summaryHtml — 요약 배지가 전부 버튼, 서빙 JS 를 node 로 실행]")
    html = o.get("__html") or ""
    check("숫자만 보이는 <span> 배지가 남지 않는다", html and '<span class="fb-badge' not in html)
    for k in ("working", "waiting_input", "waiting_child", "checkin", "checkout",
              "open_dispatch", "spawning", "unsettled", "inbox", "deadlocks", "seats"):
        check(f"배지 → <button data-go={k}>", f'data-go="{k}"' in html)
    check("버튼 수 = 배지 수(11)", html.count("<button") == 11)
    on = o.get("__htmlOn") or ""
    check("열린 배지만 on 표시", on.count(" on\"") == 1 and 'fb-go on" data-go="working"' in on)

    print("\n[chipRows — 행 수 = 배지 수]")
    cnt = {"working": s["working"], "waiting_input": s["waiting_input"], "waiting_child": s["waiting_child"],
           "checkin": s["checkin"], "checkout": s["checkout"], "open_dispatch": s["open_dispatch"],
           "deadlocks": s["deadlocks"], "spawning": s["spawning"], "seats": s["vacant"], "inbox": s["inbox_open"]}
    for k, v in cnt.items():
        check(f"{k}: 행 {len(o.get(k) or [])} = 배지 {v}", len(o.get(k) or []) == v)
    check("모르는 키 → 빈 목록", o.get("nope") == [])
    wk = {x.get("bot") for x in o["working"]}
    check("작업중 = 그 상태 봇들", wk == {"W1", "W2"})
    w1 = next((x for x in o["working"] if x.get("bot") == "W1"), {})
    check("봇 행은 자리 주소를 싣는다(클릭 착지)", w1.get("addr") == "hq/chief")
    check("봇 행 표시명 = title", w1.get("label") == "W1 핀봇")
    od = o["open_dispatch"]
    check("열린 배분 행은 job id 를 싣는다", all(x.get("job") for x in od))
    check("열린 배분은 오래된 것이 먼저(기다린 순)", [x.get("job") for x in od] == ["j-D", "j-A", "j-B", "j-E", "j-F", "j-C"])
    check("끝난 배분(done)은 열린 배분 목록에 없다", "j-G" not in {x.get("job") for x in od})
    dk = o["deadlocks"]
    check("교착 = 명부에 없음 고아 + 순환", any(x.get("job") == "j-B" for x in dk) and any(x.get("kind") == "cycle" for x in dk))
    b_row = next((x for x in dk if x.get("job") == "j-B"), {})
    check("명부에 없는 대상 → 착지는 배분한 봇(없는 봇에 포커스 금지)", b_row.get("bot") == "W1" and b_row.get("addr") == "hq/chief")
    check("교착에 소프트(대상 퇴근)·스폰 대기는 섞이지 않는다", not any(x.get("job") in ("j-D", "j-C") for x in dk))
    check("스폰 대기 = 유예 안 배분", [x.get("job") for x in o["spawning"]] == ["j-C"])
    check("공석 행 = 빈 자리 주소", {x.get("addr") for x in o["seats"]} == {"7/qa", "1/dev"})
    ib = o["inbox"]
    check("인박스 행 = 받은 봇 + 요청 id", ib and ib[0].get("bot") == "W1" and ib[0].get("job") == "r1")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
