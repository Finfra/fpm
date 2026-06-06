#!/usr/bin/env python3
# test_control_gate.py — Issue64/Issue66 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 /control 등록 게이트
#   fallback 헬퍼(_session_runner_pids)를 검증하고, Issue66 신규 기능
#   (graph validator, /control remove)을 TDD 검증한다.
#
# 실행: python3 services/htm-server/test_control_gate.py
"""server.py /control 등록 게이트 fallback (Issue64) + Issue66 신규 단위 테스트.

Issue64: 활성 세션 카드 ✕ 버튼이 403 으로 실패하던 회귀 차단.
Issue66: graph 위젯 validator, /control remove dead/alive pid 동작.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402
from validators import validate_dashboard  # noqa: E402

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


def dash_entry(pid, status="running"):
    """dashboard 세션 entry — runner 가 data content 에 pid·status 기록한 형태."""
    return {"content_type": "dashboard",
            "content": json.dumps({"pid": pid, "status": status})}


# --- 테스트 격리: server.sessions 를 픽스처로 교체 ---
server.sessions.clear()
H1 = "aaaa1111"
H2 = "bbbb2222"
server.sessions[(H1, "sid-a")] = dash_entry(49808)
server.sessions[(H1, "sid-b")] = dash_entry(50000)
server.sessions[(H2, "sid-c")] = dash_entry(60000)
# 비-dashboard 세션은 runner pid 없음
server.sessions[(H1, "sid-form")] = {"content_type": "form", "content": "{}"}
# content 파싱 실패 entry → pid 미수집
server.sessions[(H1, "sid-bad")] = {"content_type": "dashboard", "content": "not-json"}

# --- _session_runner_pids ---
check("해당 hash 의 dashboard runner pid 수집",
      server._session_runner_pids(H1) == {49808, 50000})
check("다른 hash 의 pid 는 미포함",
      server._session_runner_pids(H2) == {60000})
check("미등록 hash → 빈 set",
      server._session_runner_pids("cccc3333") == set())
check("authoritative pid 매칭 (등록 게이트 fallback 핵심)",
      49808 in server._session_runner_pids(H1))
check("비-runner pid 는 fallback 으로 인정 안 됨",
      99999 not in server._session_runner_pids(H1))

# --- content 파손 내성 ---
check("파싱 실패 content 는 수집에서 제외 (예외 없이 skip)",
      server._session_runner_pids(H1) == {49808, 50000})

# --- pid 없는 dashboard content ---
server.sessions[(H2, "sid-nopid")] = {"content_type": "dashboard",
                                      "content": json.dumps({"status": "running"})}
check("pid 키 없는 dashboard entry 는 무시",
      server._session_runner_pids(H2) == {60000})

# ============================================================
# Issue66: graph 위젯 validator 케이스
# ============================================================
print("\n--- Issue66: graph validator ---")

_gv = lambda content: validate_dashboard(json.dumps({"widgets": [content]}))

check("graph 유효 — nodes+edges 완비",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": "A", "status": "done"},
                     {"id": "b", "label": "B", "status": "blocked"}],
           "edges": [{"from": "a", "to": "b"}]}) is None)

check("graph 유효 — edges 빈 배열 허용",
      _gv({"type": "graph",
           "nodes": [{"id": "x", "label": "X"}],
           "edges": []}) is None)

check("graph 유효 — node action 옵션 허용",
      _gv({"type": "graph",
           "nodes": [{"id": "n", "label": "N",
                      "action": {"type": "link", "url": "http://example.com"}}],
           "edges": []}) is None)

check("graph 위반 — nodes missing",
      _gv({"type": "graph", "edges": []}) is not None)

check("graph 위반 — edges missing",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": "A"}]}) is not None)

check("graph 위반 — node id missing",
      _gv({"type": "graph",
           "nodes": [{"label": "A"}],
           "edges": []}) is not None)

check("graph 위반 — node label missing",
      _gv({"type": "graph",
           "nodes": [{"id": "a"}],
           "edges": []}) is not None)

check("graph 위반 — edge from missing",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": "A"}],
           "edges": [{"to": "a"}]}) is not None)

check("graph 위반 — edge to missing",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": "A"}],
           "edges": [{"from": "a"}]}) is not None)

check("graph 위반 — node action not object",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": "A", "action": "bad"}],
           "edges": []}) is not None)

# T11 통합검증 회귀 — node label 필수. {'id':'a'} (label 없음) 는 반드시 거부.
check("graph 위반 — node {'id':'a'} label 키 부재 거부 (T11 회귀)",
      _gv({"type": "graph",
           "nodes": [{"id": "a"}],
           "edges": []}) is not None)

# 빈/공백 label·id 거부 — 빈 노드 렌더·idMap 매칭 깨짐 방지
check("graph 위반 — node label 빈 문자열 거부",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": ""}],
           "edges": []}) is not None)

check("graph 위반 — node label 공백 문자열 거부",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": "   "}],
           "edges": []}) is not None)

check("graph 위반 — node id 빈 문자열 거부",
      _gv({"type": "graph",
           "nodes": [{"id": "", "label": "A"}],
           "edges": []}) is not None)

check("graph 위반 — node label 비문자열(숫자) 거부",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": 123}],
           "edges": []}) is not None)

check("graph 위반 — edge from 빈 문자열 거부",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": "A"}],
           "edges": [{"from": "", "to": "a"}]}) is not None)

check("graph 위반 — edge to 비문자열 거부",
      _gv({"type": "graph",
           "nodes": [{"id": "a", "label": "A"}],
           "edges": [{"from": "a", "to": 5}]}) is not None)

# ============================================================
# Issue66: /control remove — _handle_control_remove 단위 검증
# ============================================================
print("\n--- Issue66: /control remove ---")

# dead pid 를 simulate: 존재할 리 없는 큰 pid 사용.
_DEAD_PID = 9999997
_ALIVE_PID = os.getpid()  # 자기 자신은 살아있음

check("_pid_alive dead pid → False",
      not server._pid_alive(_DEAD_PID))
check("_pid_alive alive pid (self) → True",
      server._pid_alive(_ALIVE_PID))

# --- _session_supervisor_pid (content-authoritative 추출 헬퍼) ---
H3 = "cccc3333"
server.sessions.clear()
server.sessions[(H3, "sid-q")] = {
    "content_type": "dashboard",
    "content": json.dumps({"pid": 1234, "status": "running", "supervisor_pid": _DEAD_PID})
}
server.sessions[(H3, "sid-plain")] = {
    "content_type": "dashboard",
    "content": json.dumps({"pid": 5678, "status": "running"})  # supervisor_pid 없음
}
check("_session_supervisor_pid content-authoritative 추출",
      server.Handler._session_supervisor_pid(H3) == _DEAD_PID)
check("_session_supervisor_pid sid 한정 — 일반 dashboard sid → None",
      server.Handler._session_supervisor_pid(H3, "sid-plain") is None)
check("_session_supervisor_pid 미등록 hash → None",
      server.Handler._session_supervisor_pid("zzzz9999") is None)

# Issue86: sid 부재 + cwd_hash 내 supervisor_pid 보유 dashboard 2개 이상 → ambiguous → None
H4 = "dddd4444"
server.sessions[(H4, "sid-q1")] = {
    "content_type": "dashboard",
    "content": json.dumps({"pid": 1111, "status": "running", "supervisor_pid": 40001})
}
server.sessions[(H4, "sid-q2")] = {
    "content_type": "dashboard",
    "content": json.dumps({"pid": 2222, "status": "running", "supervisor_pid": 40002})
}
check("Issue86: _session_supervisor_pid sid 부재 + 다수 dashboard → ambiguous None",
      server.Handler._session_supervisor_pid(H4) is None)
check("Issue86: _session_supervisor_pid sid 지정 시 ambiguous 무관 정확 해석 (q1)",
      server.Handler._session_supervisor_pid(H4, "sid-q1") == 40001)
check("Issue86: _session_supervisor_pid sid 지정 시 정확 해석 (q2)",
      server.Handler._session_supervisor_pid(H4, "sid-q2") == 40002)


# --- _handle_control action 분기 흐름 검증 (fake Handler) ---
# BaseHTTPRequestHandler.__init__ 은 소켓 처리를 시작하므로 우회 — __new__ 로
# 인스턴스만 만들고 I/O 메서드를 stub. 이번 NameError(h 미정의)가 22 passed 로
# 통과한 빈틈을 메우기 위해 실제 _handle_control → remove 분기 흐름을 탄다.
class _FakeHandler(server.Handler):
    def __init__(self, body_dict):
        self._body_raw = json.dumps(body_dict).encode("utf-8")
        self.client_address = ("127.0.0.1", 0)
        self.responses = []   # [(status, body), ...]
        self.headers = {"Content-Length": str(len(self._body_raw))}

    def _send_json(self, status, body):
        self.responses.append((status, body))

    def _read_json_body(self, max_bytes=64 * 1024):
        try:
            return json.loads(self._body_raw.decode("utf-8")), None
        except Exception as e:
            return None, f"invalid JSON: {e}"


# 테스트용 프로젝트 등록 (validate 통과를 위해 cwd+token 필요)
_TEST_CWD = "/tmp/___pm-test-control-gate"
server.projects.clear()
_th = server.cwd_hash(_TEST_CWD)
_ttoken = "testtoken123"
server.projects[_th] = {"cwd": _TEST_CWD, "token": _ttoken, "name": "test",
                        "color": "#ccc", "registered_at": 0}

# remove 분기 — content-authoritative pid 추출 (세션 H 를 _TEST_CWD hash 로 등록)
server.sessions.clear()
server.sessions[(_th, "sid-q")] = {
    "content_type": "dashboard",
    "content": json.dumps({"pid": 1234, "status": "running", "supervisor_pid": _DEAD_PID})
}

from urllib.parse import urlparse as _up

# case A: action=remove, dead supervisor → 200 already_dead (NameError 없이 분기 통과)
_h = _FakeHandler({"action": "remove", "sid": "sid-q"})
_h.path = f"/control?cwd={_TEST_CWD}&token={_ttoken}"
_h._handle_control(_up(_h.path))
check("action=remove 분기 — NameError 없이 응답 1건",
      len(_h.responses) == 1)
check("action=remove dead supervisor → 200 already_dead",
      _h.responses and _h.responses[0][0] == 200
      and _h.responses[0][1].get("status") == "already_dead")

# case B: unknown action → 400
_h2 = _FakeHandler({"action": "bogus"})
_h2.path = f"/control?cwd={_TEST_CWD}&token={_ttoken}"
_h2._handle_control(_up(_h2.path))
check("action=bogus → 400 unknown action",
      _h2.responses and _h2.responses[0][0] == 400)

# case C: action=stop with missing pid → 400 (h 정의 후 분기 정상 진입 확인)
_h3 = _FakeHandler({"action": "stop"})
_h3.path = f"/control?cwd={_TEST_CWD}&token={_ttoken}"
_h3._handle_control(_up(_h3.path))
check("action=stop pid 누락 → 400 (h 분기 이동 후 정상 동작)",
      _h3.responses and _h3.responses[0][0] == 400)

# case D: body supervisor_pid 가 content 와 불일치 → content 권위 채택 (임의 pid SIGUSR2 차단)
_h4 = _FakeHandler({"action": "remove", "sid": "sid-q",
                    "supervisor_pid": 7777777})  # content 의 _DEAD_PID 와 불일치
_h4.path = f"/control?cwd={_TEST_CWD}&token={_ttoken}"
_h4._handle_control(_up(_h4.path))
# content pid(_DEAD_PID) 가 채택되므로 already_dead. body 의 7777777 무시.
check("remove — body pid ≠ content pid → content 권위 (200 already_dead)",
      _h4.responses and _h4.responses[0][0] == 200
      and _h4.responses[0][1].get("status") == "already_dead")

# ============================================================
# Issue66 Phase 7: /control approve — 승인 게이트 마커 파일
# ============================================================
print("\n--- Issue66 Phase 7: /control approve ---")

import shutil
import tempfile

# 격리된 OUT_DIR 준비 — 세션 content 에 out_dir 직접 기록
_APPROVE_OUT = tempfile.mkdtemp(prefix="___pm-approve-test-")
_AH = "dddd4444"
_acwd = "/tmp/___pm-approve-cwd"
_atok = "approvetok456"
_ah = server.cwd_hash(_acwd)
server.projects[_ah] = {"cwd": _acwd, "token": _atok, "name": "atest",
                        "color": "#ccc", "registered_at": 0}
server.sessions.clear()
server.sessions[(_ah, "sid-q")] = {
    "content_type": "dashboard",
    "content": json.dumps({
        "title": "mytopic", "status": "running",
        "supervisor_pid": _DEAD_PID, "out_dir": _APPROVE_OUT,
        "widgets": [{"type": "graph",
                     "nodes": [{"id": "item1", "label": "Item 1",
                                "status": "waiting_approval"}],
                     "edges": []}]
    })
}

try:
    # case A: action=approve 정상 — 마커 파일 생성
    _ha = _FakeHandler({"action": "approve", "item": "item1", "sid": "sid-q"})
    _ha.path = f"/control?cwd={_acwd}&token={_atok}"
    _ha._handle_control(_up(_ha.path))
    check("action=approve → 200 approved",
          _ha.responses and _ha.responses[0][0] == 200
          and _ha.responses[0][1].get("status") == "approved")
    _marker = os.path.join(_APPROVE_OUT, ".dash-approvals", "mytopic__item1")
    check("action=approve → 마커 파일 생성됨",
          os.path.isfile(_marker))
    check("action=approve → 마커 파일은 빈 파일",
          os.path.isfile(_marker) and os.path.getsize(_marker) == 0)

    # case B: itemid traversal 거부 — ../../ 포함
    _hb = _FakeHandler({"action": "approve", "item": "../../etc/passwd", "sid": "sid-q"})
    _hb.path = f"/control?cwd={_acwd}&token={_atok}"
    _hb._handle_control(_up(_hb.path))
    check("action=approve traversal itemid → 400",
          _hb.responses and _hb.responses[0][0] == 400)

    # case C: itemid 슬래시 포함 거부
    _hc = _FakeHandler({"action": "approve", "item": "a/b", "sid": "sid-q"})
    _hc.path = f"/control?cwd={_acwd}&token={_atok}"
    _hc._handle_control(_up(_hc.path))
    check("action=approve 슬래시 itemid → 400",
          _hc.responses and _hc.responses[0][0] == 400)

    # case D: item 누락 → 400
    _hd = _FakeHandler({"action": "approve", "sid": "sid-q"})
    _hd.path = f"/control?cwd={_acwd}&token={_atok}"
    _hd._handle_control(_up(_hd.path))
    check("action=approve item 누락 → 400",
          _hd.responses and _hd.responses[0][0] == 400)

    # case E: OUT_DIR 미도출 (out_dir 없는 세션) → 404
    # dash-registry 도 빈 임시 파일로 교체해 OUT_DIR 도출 경로 전부 차단
    # (실제 data/hub/dash-registry.json 미오염 — 테스트 격리).
    server.sessions[(_ah, "sid-noout")] = {
        "content_type": "dashboard",
        "content": json.dumps({"title": "t2", "status": "running",
                               "supervisor_pid": _DEAD_PID, "widgets": []})
    }
    _orig_dash_reg = server.DASH_REGISTRY
    _empty_reg = os.path.join(_APPROVE_OUT, "empty-dash-registry.json")
    with open(_empty_reg, "w", encoding="utf-8") as f:
        f.write("[]")
    server.DASH_REGISTRY = _empty_reg
    try:
        _he = _FakeHandler({"action": "approve", "item": "x", "sid": "sid-noout"})
        _he.path = f"/control?cwd={_acwd}&token={_atok}"
        _he._handle_control(_up(_he.path))
        check("action=approve OUT_DIR 미도출 → 404",
              _he.responses and _he.responses[0][0] == 404)
    finally:
        server.DASH_REGISTRY = _orig_dash_reg

    # case F: 안전한 itemid (영숫자·-·_) 허용 확인
    _hf = _FakeHandler({"action": "approve", "item": "item-2_b", "sid": "sid-q"})
    _hf.path = f"/control?cwd={_acwd}&token={_atok}"
    _hf._handle_control(_up(_hf.path))
    check("action=approve 안전 itemid (item-2_b) → 200 approved",
          _hf.responses and _hf.responses[0][0] == 200
          and _hf.responses[0][1].get("status") == "approved")
finally:
    shutil.rmtree(_APPROVE_OUT, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
