#!/usr/bin/env python3
# test_session_button_issue542.py — Issue542 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). hub 문서 헤더 세션 버튼이
#   에디터 능력(세션 딥링크 유무)에 따라 표시·동작을 가르는지 검증한다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_session_button_issue542.py
"""세션 버튼 판정 단일 지점(_session_open_mode) + 헤더 렌더 + CSP 호환 (Issue542)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402
import md_shell  # noqa: E402

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


H = "h542"
server.sessions[(H, "sid-vs")] = {"capabilities": {"entrypoint": "claude-vscode"}}
server.sessions[(H, "sid-zed")] = {"capabilities": {"entrypoint": "sdk-ts", "editor": "zed"}}
server.sessions[(H, "sid-term")] = {"capabilities": {"entrypoint": "cli"}}

# --- 판정 단일 지점 ---
check("vscode 세션 → 열기 가능", server._session_open_mode("sid-vs") == ("vscode", True))
check("zed 세션 → 아이콘만(열기 불가)", server._session_open_mode("sid-zed") == ("zed", False))
ed_t, can_t = server._session_open_mode("sid-term")
check("terminal 세션 → 에디터 세션 열기 불가", can_t is False and ed_t in ("vscode", "zed"))
ed_u, can_u = server._session_open_mode("sid-unknown")
check("레지스트리 밖 세션 → 기본 에디터 능력으로",
      ed_u == server._default_editor()
      and can_u == server._EDITOR_SESSION_DEEPLINK[server._default_editor()])

# --- 헤더 렌더 ---
hv = md_shell.render_header("t", "/p", "p", "sid-vs", editor="vscode", can_open=True)
hz = md_shell.render_header("t", "/p", "p", "sid-zed", editor="zed", can_open=False)
check("vscode: 아이콘 이미지 + '열기' 텍스트",
      "/editor-icon/vscode.png" in hv and "열기</a>" in hv)
check("zed: 아이콘 이미지만 ('열기'·'세션' 텍스트 없음)",
      "/editor-icon/zed.png" in hz and "열기</a>" not in hz and "세션</a>" not in hz)
check("data-open 으로 동작 분기 표기", 'data-open="1"' in hv and 'data-open="0"' in hz)
check("data-sid·data-cwd 를 버튼에 실음 (cwd 누락 400 재발 방지)",
      'data-sid="sid-vs"' in hv and 'data-cwd="/p"' in hv)

# --- CSP 호환: nonce 전용 script-src 는 인라인 핸들러를 막는다 ---
nonce = md_shell.make_nonce()
page = md_shell.render_md_shell("---\ntitle: t\nsid: sid-vs\n---\n# b\n", "t",
                                "/p/_doc_work/htm/hub_htm_1.md", nonce, "/p", "p",
                                editor="vscode", can_open=True).decode()
header = page[page.index("<header>"):page.index("</header>")]
check("헤더에 인라인 onclick 없음(CSP 차단 대상)", "onclick=" not in header.replace('onclick="window.close()"', ""))
check("헤더 클릭 바인딩 스크립트가 nonce 로 실림",
      re.search(r'<script nonce="%s">[^<]*open-session' % re.escape(nonce), page) is not None)
live = md_shell.render_live_shell("t", "/p", "p", "sid-zed", "h", "tok", nonce,
                                  editor="zed", can_open=False).decode()
check("라이브 셸도 같은 헤더 규칙", "/editor-icon/zed.png" in live and 'data-open="0"' in live)

# --- 📋 sid 복사 shim: data-sid 우선 ---
check("SID_COPY_SHIM 이 data-sid 를 읽음", b"dataset.sid" in server.SID_COPY_SHIM)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
