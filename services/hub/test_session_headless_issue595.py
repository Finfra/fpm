#!/usr/bin/env python3
# test_session_headless_issue595.py — Issue595 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
#
# 왜 — 2026-10-04 `/mq` 항목의 «집은 주체 dfa96a27 ⏻» 클릭 → VSCode 에 **빈 Claude Code 탭**.
#   그 세션은 mq [진행] 이 띄운 `claude -p`(트랜스크립트 `entrypoint: sdk-cli`)였다.
#   VSCode 확장(anthropic.claude-code)의 세션 목록은 entrypoint ∈ {sdk-cli, sdk-ts, sdk-py}·
#   sessionKind ∈ {daemon, daemon-worker} 세션을 제외하므로 `open?session=<sid>` 가 못 찾고
#   새 빈 세션을 연다. hub 판정(`_session_open_mode`)은 레지스트리 밖 세션을 «VSCode 가
#   resume 가능»으로 단정해 그 딥링크를 쐈다.
#
# 검증 대상:
#   A. 레지스트리 밖 + 트랜스크립트 entrypoint sdk-* / sessionKind daemon* → 열기 불가
#   B. 레지스트리 밖 + interactive(claude-vscode·cli) 트랜스크립트 → 종전대로 기본 에디터 능력
#   C. `_mq_claimed_session` 이 can_open + 대체 URL(/s/{h}/{sid}?token=) 을 싣는다
#   D. /open-session 은 열기 불가 sid 에 딥링크를 쏘지 않는다(서버 방어)
#   E. /mq JS 가 열기 불가 세션을 «📜 기록» 으로 세우고 클릭은 트랜스크립트 뷰
#
# 실행: python3 plugins/fpm-core/services/hub/test_session_headless_issue595.py
import json
import os
import sys
import tempfile

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


_TMP = tempfile.mkdtemp(prefix="___pm-issue595-")
server.PROJECTS_BASE = os.path.join(_TMP, "projects")
CWD = os.path.join(_TMP, "claude")
os.makedirs(CWD, exist_ok=True)
H = server.cwd_hash(CWD)
TOKEN = "tok595"
server.projects[H] = {"cwd": CWD, "token": TOKEN}


def _write_transcript(sid, entrypoint, session_kind=None):
    enc = os.path.join(server.PROJECTS_BASE, "enc")
    os.makedirs(enc, exist_ok=True)
    rows = [{"type": "queue-operation"}]
    for t in ("attachment", "user"):
        r = {"type": t, "entrypoint": entrypoint, "cwd": CWD, "sessionId": sid}
        if session_kind:
            r["sessionKind"] = session_kind
        rows.append(r)
    with open(os.path.join(enc, f"{sid}.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(r) for r in rows) + "\n")


SID_SDK = "dfa96a27-3b60-47b8-85af-3a8777080595"
SID_SDKTS = "aaaaaaaa-0000-0000-0000-00000000a595"
SID_DAEMON = "bbbbbbbb-0000-0000-0000-00000000b595"
SID_VS = "cccccccc-0000-0000-0000-00000000c595"
SID_CLI = "dddddddd-0000-0000-0000-00000000d595"
_write_transcript(SID_SDK, "sdk-cli")
_write_transcript(SID_SDKTS, "sdk-ts")
_write_transcript(SID_DAEMON, "cli", session_kind="daemon-worker")
_write_transcript(SID_VS, "claude-vscode")
_write_transcript(SID_CLI, "cli")

ED = server._default_editor()
ED_CAN = server._EDITOR_SESSION_DEEPLINK.get(ED, False)

# --- A. headless → 열기 불가 ---
check("A1 sdk-cli 종료 세션 → 열기 불가", server._session_open_mode(SID_SDK) == (ED, False),
      repr(server._session_open_mode(SID_SDK)))
check("A2 sdk-ts 종료 세션 → 열기 불가", server._session_open_mode(SID_SDKTS)[1] is False)
check("A3 sessionKind daemon-worker → 열기 불가", server._session_open_mode(SID_DAEMON)[1] is False)

# --- B. interactive → 종전 ---
check("B1 claude-vscode 종료 세션 → 기본 에디터 능력",
      server._session_open_mode(SID_VS) == (ED, ED_CAN))
check("B2 cli 종료 세션 → 기본 에디터 능력",
      server._session_open_mode(SID_CLI) == (ED, ED_CAN))
check("B3 트랜스크립트 없는 sid → 기본 에디터 능력(종전)",
      server._session_open_mode("eeeeeeee-0000-0000-0000-00000000e595") == (ED, ED_CAN))
check("B4 트랜스크립트 cwd 판독은 그대로", server._transcript_cwd(SID_SDK) == CWD)

# --- C. mq 수집 결과 ---
sc = server._mq_claimed_session("session:" + SID_SDK)
check("C1 headless 집은 주체 → can_open False", sc and sc.get("can_open") is False, repr(sc))
check("C2 대체 URL = 종료 세션 폴백 뷰",
      sc and sc.get("view_url") == f"/s/{H}/{SID_SDK}?token={TOKEN}", repr(sc))
sc_vs = server._mq_claimed_session("session:" + SID_VS)
check("C3 interactive 집은 주체 → can_open 은 기본 에디터 능력",
      sc_vs and sc_vs.get("can_open") is ED_CAN, repr(sc_vs))
server.sessions[(H, "live-sdk-595")] = {"capabilities": {"entrypoint": "sdk-cli"}}
sc_live = server._mq_claimed_session("session:live-sdk-595")
check("C4 살아 있는 headless(레지스트리 sdk-cli) → can_open False + 라이브 뷰 URL",
      sc_live and sc_live.get("can_open") is False
      and sc_live.get("view_url") == f"/s/{H}/live-sdk-595?token={TOKEN}", repr(sc_live))
server.sessions.pop((H, "live-sdk-595"), None)


# --- D. /open-session 서버 방어 ---
class _FakeHandler(server.Handler):
    def __init__(self, body):
        self.client_address = ("127.0.0.1", 0)
        self.responses = []
        self._body = body

    def _read_json_body(self):
        return self._body, None

    def _send_json(self, status, body):
        self.responses.append((status, body))


spawned = []
_orig_popen = server.subprocess.Popen
_orig_then = server._open_editor_then_uri
_orig_colors = server._load_projects_colors
server.subprocess.Popen = lambda cmd, **kw: spawned.append(cmd)
server._open_editor_then_uri = lambda *a, **kw: spawned.append(("URI",) + a)
server._load_projects_colors = lambda: {CWD: "#fff"}
try:
    if True:
        h = _FakeHandler({"cwd": CWD, "sid": SID_SDK})
        h._handle_open_session(None)
        uris = [c for c in spawned if c and c[0] == "URI"]
        check("D1 headless sid 에 세션 딥링크 미발사", not uris, repr(spawned))
        check("D2 응답은 focused-app", h.responses and h.responses[-1][1].get("status") == "focused-app",
              repr(h.responses))
finally:
    server.subprocess.Popen = _orig_popen
    server._open_editor_then_uri = _orig_then
    server._load_projects_colors = _orig_colors

# --- E. /mq JS 문자열 계약 ---
src_all = open(server.__file__, encoding="utf-8").read()
check("E1 whoHtml 이 can_open===false 를 분기", "sc.can_open===false" in src_all)
check("E2 «📜 기록» 표시", "📜 기록" in src_all)
check("E3 headless 툴팁", "headless 세션 — VSCode 에서 열 수 없음, 대화 기록 보기" in src_all)
# Issue602: 새 탭 직접 호출 → openView 경유(hub 셸 임베드면 내부 탭, 단독이면 새 탭 — 분기 검증은 test_mq_shell_tab_issue602)
check("E4 openClaimed 가 view_url 을 새 화면으로(openView)", "dataset.view" in src_all and "if(view){ openView(view," in src_all)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
