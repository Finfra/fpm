#!/usr/bin/env python3
"""Issue553 — hub 자리 해소 경로가 connection 1개를 관통한다 (prj3#Issue732 짝). 스텁 해소기로 검증."""
import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok   {name}")
    else: FAIL += 1; print(f"  FAIL {name}")

class _FakeCon:
    def __init__(self): self.closed = False
    def close(self): self.closed = True

def _stub(with_con=True):
    m = types.ModuleType("fbot_org_stub"); m.ORG_DIR = "/nonexistent-org-dir"
    m.calls = []; m.cons = []
    m._org_files = lambda: [1, 2]
    def _resolve(prj=None, with_formed=False, **kw):
        m.calls.append(("resolve", prj, kw.get("con")))
        return {"ok": True, "prj": prj, "title": f"t{prj}", "seats": [{"id": "s", "addr": f"{prj}/s"}], "alive": True}
    def _formed(prj, **kw):
        m.calls.append(("formed", prj, kw.get("con")))
        return {"formed": True, "reason": "구성 중", "idle_days": 0.1, "disbanded_at": None}
    if with_con:
        def _ro(): c = _FakeCon(); m.cons.append(c); return c
        m._ro_con = _ro
        m.resolve, m.team_formed = _resolve, _formed
    else:  # 구버전 해소기 — con 인자 자체가 없다
        m.resolve = lambda prj=None, with_formed=False: _resolve(prj, with_formed)
        m.team_formed = lambda prj: _formed(prj)
    return m

def _use(m):
    server._ORG_MOD = m; server._ORG_MOD_MTIME = os.stat(server._ORG_MOD_PATH).st_mtime
    server._org_formed_invalidate()

def main():
    print("== 신형 해소기: connection 1개 관통 ==")
    m = _stub(True); _use(m)
    out = server._fbot_org_seats_compute(None)
    cons = {id(c) for _, _, c in m.calls}
    check("전체 뷰 계산이 connection 을 정확히 1개 연다", len(m.cons) == 1)
    check("resolve·team_formed 전 호출이 같은 connection 을 받는다", len(cons) == 1 and m.calls and m.calls[0][2] is m.cons[0])
    check("계산 끝에 닫는다", m.cons[0].closed)
    check("결과 정상", out.get("available") and out.get("scopes") == 3)
    m.calls.clear(); m.cons.clear(); server._org_formed_invalidate()
    out = server._fbot_org_seats_compute(7)
    check("prj 선택 뷰도 connection 1개·관통", len(m.cons) == 1 and all(c is m.cons[0] for _, _, c in m.calls) and m.cons[0].closed)
    print("== 구버전 해소기(con 인자 없음): 호환 ==")
    m2 = _stub(False); _use(m2)
    out = server._fbot_org_seats_compute(None)
    check("con 없이 호출되어도 동작", out.get("available") and out.get("scopes") == 3 and all(c is None for _, _, c in m2.calls))
    server._ORG_MOD = None
    print(f"\n{PASS} passed, {FAIL} failed"); return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
