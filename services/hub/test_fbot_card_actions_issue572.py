#!/usr/bin/env python3
# test_fbot_card_actions_issue572.py — 핀봇 카드 «요청 보내기»·«재기동 요청» 은 관리직(총괄·팀장)만 (Issue572, prj3#Issue757)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: prj3#Issue757 — «사람의 지시를 받는 것은 총괄과 팀장뿐». 카드는 `mgr=["chief","lead","hr"]` 를 JS 에
#   하드코딩해 인사핀봇 카드에도 «요청 보내기» 를 열었다 — prj3 `fbot-inbox.py send` 는 사람 → 인사핀봇을 거부하므로
#   버튼이 곧 실패 경로였다. «재기동 요청(wake)» 은 퇴근한 모든 카드에 떴다(워커를 사람이 직접 깨우는 경로).
#   판정은 prj3 `hooks/fbot-org.py` `is_nonexec()`(카탈로그 `nonexec=true`)가 단일 지점이다 — hub 는 그 결과를
#   페이로드에 싣고 JS 는 그 값만 본다(역할 목록을 JS 에 복제하지 않는다).
#
# 실행: python3 plugins/fpm-core/services/hub/test_fbot_card_actions_issue572.py
import json
import os
import shutil
import subprocess
import sys

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


def main():
    print("[A] 관리직 판정 — prj3 fbot-org.is_nonexec 가 정본, 모듈이 없을 때만 폴백")
    fn = getattr(server, "_fbot_is_nonexec", None)
    check("_fbot_is_nonexec 존재", callable(fn))
    if callable(fn):
        orig = server._org_mod

        class _Mod:
            @staticmethod
            def is_nonexec(role):
                return role in ("chief", "special")
        server._org_mod = lambda: _Mod()
        check("prj3 판정을 그대로 쓴다(special → 관리직 · lead → 아님)", fn("special") and not fn("lead"))
        server._org_mod = lambda: None
        check("모듈 부재 폴백 — chief·lead 만", fn("chief") and fn("lead") and not fn("hr") and not fn("developer"))
        server._org_mod = orig

    print("\n[B] 페이로드 — 봇에 nonexec 를 싣는다")
    full = {"nodes": [{"bot_id": "L1", "title": "팀장", "role": "lead", "state": "checkout", "root": "L1", "nonexec": True},
                      {"bot_id": "H1", "title": "인사", "role": "hr", "state": "checkout", "root": "H1", "nonexec": False},
                      {"bot_id": "W1", "title": "워커", "role": "developer", "state": "checkout", "root": "W1"}],
            "dispatch": []}
    d = server._fbot_board_payload(full, {"available": True, "seats": []}, inbox={}, escal={}, now=1_000_000)
    bots = d.get("bots") or {}
    check("L1.nonexec True · H1·W1 False", bots.get("L1", {}).get("nonexec") is True
          and bots.get("H1", {}).get("nonexec") is False and bots.get("W1", {}).get("nonexec") is False)

    print("\n[C] 카드 JS — 관리직만 요청·재기동, 나머지는 «팀장에게» 안내(node 실행)")
    src = server._FBOT_BOARD_JS
    body = _grab_js(src, "seatCardInner")
    check("역할 목록을 JS 에 복제하지 않는다(chief·lead·hr 하드코딩 제거)", '["chief","lead","hr"]' not in body)
    node = shutil.which("node")
    if not node:
        print("  skip node 미설치 — 실행 검증 생략")
    else:
        js = (_grab_line(src, "const esc") + "\n"
              + "const ago=()=>'';const questionsHtml=()=>'';const directingHtml=()=>'';const timelineHtml=()=>'';\n"
              + "const state={data:{bots:" + json.dumps({k: dict(v, grade="", employment="") for k, v in bots.items()}) + "}};\n"
              + body + "\n"
              + "const out={};for(const [bid,rt] of [['L1','hq/hq-chief-1'],['H1','hq/hq-chief-1'],['W1','3/ops-lead-1']]){"
                "out[bid]=seatCardInner({bot_id:bid,role:state.data.bots[bid].role,addr:'x/'+bid,reports_to:rt});}"
              + "process.stdout.write(JSON.stringify(out));")
        r = subprocess.run([node, "-e", js], capture_output=True, text=True)
        try:
            h = json.loads(r.stdout)
        except ValueError:
            h = {}
            check(f"node 실행 ({r.stderr.strip()[:200]})", False)
        if h:
            check("팀장 카드: 요청 보내기", "fb-send" in h["L1"])
            check("팀장 카드(퇴근): 재기동 요청", 'data-action="wake"' in h["L1"])
            for bid, who in (("H1", "인사핀봇"), ("W1", "워커")):
                check(f"{who} 카드: 요청 보내기 없음", "fb-send" not in h[bid])
                check(f"{who} 카드(퇴근): 재기동 요청 없음", 'data-action="wake"' not in h[bid])
                check(f"{who} 카드: «팀장» 안내 + 보고선", "팀장" in h[bid] and ("ops-lead-1" in h[bid] or "hq-chief-1" in h[bid]))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
