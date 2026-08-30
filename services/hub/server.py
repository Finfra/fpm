#!/usr/bin/env python3
"""
htm-server — ___pm 소유 단일 공유 daemon
- 기본 127.0.0.1 바인딩 (외부 차단). HTM_SERVER_HOST 로 옵트인 개방 (Issue141)
  → 개방 시 Servers.md(check=O) 호스트 IP allowlist 로 source-IP 게이트
- 다중 프로젝트 격리: cwd query param + md5(cwd)[:8] hash
- 프로젝트별 token + inbox + SSE subscriber 분리, 포트·프로세스는 단일

설계 SSOT: ~/_git/___pm/_doc_arch/hub_htm.md
"""

import base64  # prj3#Issue438: 봇 아이콘 SVG 를 data URI 로 인라인
import glob
import hashlib
import hmac
import html
import json
import os
import platform
import sys
import time
import uuid
import signal
import subprocess
import shlex
import re
import mimetypes
import tempfile
import socket
import sqlite3  # Issue360: Zed 로컬 db(sidebar_threads.archived) 조회 — 스레드 닫힘 판정
import ipaddress
import threading
from collections import deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote

# Issue30: SPA JS 모듈 분리 (SESSION_SHELL_HTML 조립용 string export)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validators import validate_dashboard, DASH_WIDGET_TYPES  # noqa: E402
from spa_form import FORM_JS  # noqa: E402
from spa_widgets import WIDGET_JS  # noqa: E402
from spa_board import DASHBOARD_JS  # noqa: E402
import i18n  # noqa: E402  # Issue169: hub UI 다국어 catalog + t(key, lang)
import md_shell  # noqa: E402  # Issue353_1: md-first 셸 렌더 단일 템플릿 (M2 라이브 셸과 공유)
import mailbox  # noqa: E402  # Issue353_2: transcript tail → 세션 메일박스 (pull 스트리밍)
import render_gate  # noqa: E402  # Issue353_3: 적응형 렌더 게이트 (서버 기계 판정)

# Issue141: 기본 127.0.0.1(루프백 전용=외부 차단). 옵트인 개방 우선순위:
#   env HTM_SERVER_HOST > hub_setting.yml bind_host > 기본 "127.0.0.1".
#   env 미설정 시 yml 값을 main() 에서 적용(설정 로더가 정의된 뒤). 예: bind_host: 0.0.0.0
_HOST_ENV = os.environ.get("HTM_SERVER_HOST")  # 미설정이면 None
HOST = _HOST_ENV or "127.0.0.1"  # 잠정값 — main() 에서 yml override
BIND_HOSTS = [HOST]  # 실제 bind 주소 리스트 — main() 에서 yml(스칼라|리스트) override
PORT = int(os.environ.get("HTM_SERVER_PORT", "9876"))

# Issue141: source-IP allowlist. LOOPBACK 은 무조건 허용. HOST 가 루프백이 아닐 때
# (옵트인 개방) startup 에서 Servers.md(check=O) 호스트를 resolve 하여 채운다.
LOOPBACK_IPS = frozenset(("127.0.0.1", "::1"))
ALLOWED_IPS = set()  # startup 에서 populate (개방 모드일 때만). 평소엔 빈 set.
ALLOWED_NETS = []    # Issue175: CIDR 서브넷 allowlist (ip_network 리스트). 평소엔 빈 리스트.
# Issue332: allowlist 백그라운드 적재 완료 플래그. False 인 동안의 비허용 판정은
# "차단" 이 아니라 "준비 중" → 403 대신 503 + Retry-After 로 응답한다.
ALLOWLIST_READY = True  # 개방 모드 진입 시 main() 에서 False 로 내렸다가 적재 완료 시 True
# allow_server_list 분리: bind_host 와 source-IP 게이트 디커플링.
# bind 가 비루프백이고 allow_server_list=false 면 ALLOWED_IPS=self 만 적재 → bind_host(self)
# 전용(외부 source IP 전부 차단). true 면 Servers.md(check=O)+self 적재.
# ALLOW_ALL 은 더 이상 토글되지 않음(항상 False) — _ip_allowed 호환용 잔존.
ALLOW_ALL = False

# Issue379: 수신 이름(Host 헤더) 게이트 — source-IP 게이트(_ip_allowed)의 짝.
#   _ip_allowed 는 "어디서 왔는가"만 보고 "어느 이름으로 불렸는가"를 안 본다. 그래서
#   브라우저를 경유하는 DNS rebinding(외부 도메인을 127.0.0.1 로 rebind)은 src 가 루프백이라
#   그대로 통과했다. 수신 이름을 known 집합으로 제한해 그 표면을 닫는다.
#   KNOWN_HOSTS 는 main() 에서 1회 산출(순수 문자열 조립, DNS 불요) — 변경 시 restart.
KNOWN_HOSTS = frozenset()  # 공집합이면 게이트 비활성(fail-open) — 설정 사고가 hub 를 죽이지 않게
HOST_GATE = True           # yml host_gate. false 면 종전 동작(전 이름 허용)

STATE_DIR = "/tmp/___pm/claude-htm-server"
INBOX_ROOT = "/tmp/___pm/claude-htm-inbox"
TMP_OUT_DIR = "/tmp/___pm"  # dashboard agent OUT_DIR fallback (htm 폴더 부재 시)

# Issue289: htm 산출물 수명주기 — 쓰기는 활성 폴더 1곳, 읽기는 아래 목록 전체.
#   활성 `_doc_work/htm/` → 아카이브 `_doc_work/z_done/htm/` → legacy `_doc_work/z_htm/`.
#   legacy 항목은 전 프로젝트 마이그레이션(P3) 완료 후 P4 에서 제거한다.
#   설계 SSOT: _doc_arch/htm-lifecycle-design.md
HTM_ACTIVE_DIR = "htm"
HTM_DIRS = ["htm", "z_done/htm", "z_htm"]


def _htm_dirs_for(cwd: str) -> list:
    """Issue289: 프로젝트 cwd 하위 htm 읽기 경로 목록(우선순위 순, 존재 여부 무관)."""
    return [os.path.join(cwd, "_doc_work", *d.split("/")) for d in HTM_DIRS]


def _htm_output_stem(name: str) -> str:
    """Issue311: htm 단발 출력 파일명에서 확장자를 뗀 stem. 구 `claude-htm-*.html` /
    현행 `hub_htm_*.htm` / md-first `hub_htm_*.md`(Issue353_1) 인식 — 매치 안 되면
    빈 문자열(호출측이 skip). 스캔·clear 전수·autoregister 가 공유하는 단일 패턴 게이트."""
    if name.startswith("claude-htm-") and name.endswith(".html"):
        return name[:-len(".html")]
    if name.startswith("hub_htm_") and name.endswith(".htm"):
        return name[:-len(".htm")]
    if name.startswith("hub_htm_") and name.endswith(".md"):
        return name[:-len(".md")]
    return ""
TOKENS_FILE = f"{STATE_DIR}/tokens.json"
SESSIONS_FILE = f"{STATE_DIR}/sessions.json"  # Issue17 Phase 1
PIDS_FILE = f"{STATE_DIR}/pids.json"  # Issue63: runner PID 등록분 영속화
PID_FILE = f"{STATE_DIR}/pid"
LOG_FILE = f"{STATE_DIR}/server.log"

# dashboard liveness heartbeat 신선도 한계(초). runner 가 매 iter data POST 로
# session.updated 를 갱신하므로, pid 가 살아있어도 이 시간 이상 갱신이 끊기면
# 좀비(죽은 runner 의 orphan sleep/PID 재사용)로 보고 terminal 처리한다.
# pid 생존만으로 force_live 하면 dismiss/age/subs 게이트를 전부 우회해
# '지운 카드가 부활'하는 버그가 생긴다 — 이 게이트가 그 회귀를 막는다.
# 가장 느린 dashboard(jm1 모니터: 600s 주기)도 여유로 통과하도록 1800s.
DASH_HEARTBEAT_STALE = 1800.0

# Issue98: content_type="live" (일반 claude 세션) liveness. pid 없는 등록의
# heartbeat TTL — register/heartbeat 후 이 시간 내면 live, 초과 시 terminal.
# pid 가 주어지면 _pid_alive 가 권위적 신호이고 본 TTL 은 fallback.
LIVE_TTL = 300.0

# Issue374: live 세션 heartbeat 신선도 상한(초). DASH_HEARTBEAT_STALE 의 live 판.
# pid 생존만으로 판정하면 **세션보다 오래 사는 호스트 프로세스**(Claude Desktop 이
# 예약작업 종료 후에도 회수하지 않는 claude-code 호스트 등)가 끝난 세션을 영구
# live 카드로 남긴다 — 실측 74.9시간(sid e208f4c1, 2026-08-09 예약작업 jobstart).
# live 는 dashboard runner 와 달리 hook 이 발동할 때만 heartbeat 가 오르고 장시간
# 유휴가 정상이므로 창을 훨씬 넓게 잡는다(실측 정상 세션 최대 유휴 15.4시간).
# 초과분은 prune 되나 다음 hook 발동에 재등록되므로 손실은 유휴 구간의 카드뿐.
LIVE_HEARTBEAT_STALE = 172800.0  # 48h

# 메모리 상태
projects_lock = threading.Lock()
projects = {}  # cwd_hash -> {"cwd": str, "token": str, "name": str, "color": str, "registered_at": float}

sse_lock = threading.Lock()
# Issue17 Phase 1: 채널 모델 확장 — key = (cwd_hash, sid)
# sid="" 는 기존 /events?cwd=&token= 호출자 (backward-compat 채널)
sse_subscribers = {}  # (cwd_hash, sid) -> [wfile, wfile, ...]

# Issue194: hub 내부 탭 모드. hub 쉘(/hub-shell)은 cross-project·host 단위라
# cwd+token 채널을 못 쓴다 → 예약 hash 의 sse_subscribers 채널을 재사용한다.
#   key = (HUB_SHELL_HASH, client_id). sse_broadcast(HUB_SHELL_HASH, ...) 로 전 shell push.
HUB_SHELL_HASH = "__hub_shell__"
hub_lease_lock = threading.Lock()
# host(source-IP) 단위 단일 창 리스. {ip: {"client_id":str, "granted_at":float, "last_seen":float}}
hub_lease = {}

# Issue194: hub 내부 탭 쉘 페이지. __SHORTCUT__(JSON 문자열)·__SINGLE__(true/false) 치환.
#   home 탭(=/hub 멀티프로젝트 대시보드) 은 content_type "home" → 닫기 단축키 no-op(R3).
HUB_SHELL_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/fpm-icon.png">
<title>fPm Hub — 내부 탭</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  body { display: flex; flex-direction: column; }
  #tabbar { display: flex; align-items: stretch; gap: 2px; background: hsl(60,30%,88%);
    padding: 4px 6px 0; overflow-x: auto; flex: 0 0 auto; }
  .tab { display: flex; align-items: center; gap: 6px; max-width: 240px; padding: 6px 10px;
    background: rgba(0,0,0,0.06); border: 1px solid rgba(0,0,0,0.12); border-bottom: none;
    border-radius: 8px 8px 0 0; cursor: pointer; white-space: nowrap; font-size: 0.85rem; color: #1a1a1a; }
  .tab.active { background: #fff; font-weight: 600; }
  .tab .ttl { overflow: hidden; text-overflow: ellipsis; }
  .tab .x { border: none; background: transparent; cursor: pointer; font-size: 0.9rem; padding: 0 2px; color: #555; }
  .tab .x:hover { color: #c00; }
  #hint { margin-left: auto; align-self: center; font-size: 0.72rem; color: #555; padding: 0 8px; white-space: nowrap; }
  #closeall { align-self: center; margin: 0 4px; border: 1px solid rgba(0,0,0,0.18); background: rgba(0,0,0,0.04);
    border-radius: 6px; cursor: pointer; font-size: 0.75rem; color: #333; padding: 4px 8px; white-space: nowrap; }
  #closeall:hover { background: #f7d6d6; color: #c00; border-color: #c00; }
  #view { flex: 1 1 auto; border: none; width: 100%; }
  #overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.78); color: #fff; z-index: 999;
    display: none; flex-direction: column; align-items: center; justify-content: center; gap: 1rem; text-align: center; padding: 2rem; }
  #overlay.show { display: flex; }
  #overlay button { font-size: 1rem; padding: 0.6rem 1.4rem; border-radius: 8px; border: none; cursor: pointer;
    background: hsl(60,72%,70%); color: #1a1a1a; font-weight: 600; }
  @media (prefers-color-scheme: dark) {
    #tabbar { background: #26261f; }
    .tab { background: rgba(255,255,255,0.06); border-color: #444; color: #ddd; }
    .tab.active { background: #1a1a1a; }
    #hint { color: #aaa; }
    #closeall { background: rgba(255,255,255,0.06); border-color: #555; color: #ccc; }
    #closeall:hover { background: #5a1f1f; color: #fbb; border-color: #c00; }
  }
</style>
</head>
<body>
<div id="tabbar"></div>
<iframe id="view" src="/hub?_shell=1"></iframe>
<div id="overlay">
  <div id="ovmsg"></div>
  <button id="ovbtn" type="button">여기서 인계</button>
</div>
<script>
(function(){
  // Issue203: 중첩 쉘 차단. /hub-shell 이 iframe 안에서 로드되면(절대 URL 탭 등으로
  //   _shell 마커 누락 → /htm-doc 가 top-level 로 오인 → 302 /hub-shell 재진입) 탭바가
  //   2중으로 렌더되는 "탭 세로 적층" 버그가 생긴다. 자신이 top 프레임이 아니면 쉘로
  //   동작하지 않고(탭바·iframe 미초기화) 빈 본문으로 대체하여 재귀를 끊는다.
  if (window.self !== window.top) {
    document.documentElement.innerHTML = "<head><meta charset='utf-8'></head><body style='margin:0'></body>";
    return;
  }
  var SHORTCUT = __SHORTCUT__;          // ex) "alt+w"
  var SINGLE = __SINGLE__;              // 단일 창 강제 여부
  var RENDER_CT = {response:1, form:1, dashboard:1};  // R3: 단축키 노출 대상 content_type

  // client_id: sessionStorage 유지(새로고침 생존), 없으면 난수
  var cid = sessionStorage.getItem("hubShellCid");
  if(!cid){ cid = "c" + Math.random().toString(36).slice(2) + Date.now().toString(36); sessionStorage.setItem("hubShellCid", cid); }

  // Issue199: 탭 상태 sessionStorage 영속 — 페이지 reload·서버 재시작에도 열린 탭 보존.
  var TABKEY = "hubShellState";
  var _saved = (function(){ try{ return JSON.parse(sessionStorage.getItem(TABKEY)||"null"); }catch(_){ return null; } })();
  var tabs = (_saved && _saved.tabs && _saved.tabs.length) ? _saved.tabs
             : [{id:"home", view_url:"/hub", title:"🗂 Hub", sid:"", content_type:"home"}];
  var activeId = (_saved && _saved.activeId && tabs.some(function(t){return t.id===_saved.activeId;})) ? _saved.activeId : "home";
  function saveTabs(){ try{ sessionStorage.setItem(TABKEY, JSON.stringify({tabs:tabs, activeId:activeId})); }catch(_){} }
  var bar = document.getElementById("tabbar");
  var view = document.getElementById("view");
  var hint = null;

  function render(){
    bar.innerHTML = "";
    tabs.forEach(function(t){
      var el = document.createElement("div");
      el.className = "tab" + (t.id===activeId ? " active" : "");
      el.onclick = function(){ activate(t.id); };
      var ttl = document.createElement("span"); ttl.className = "ttl"; ttl.textContent = t.title || "(문서)";
      el.appendChild(ttl);
      if(t.id !== "home"){
        var x = document.createElement("button"); x.className = "x"; x.textContent = "✕";
        x.onclick = function(ev){ ev.stopPropagation(); closeTab(t.id); };
        el.appendChild(x);
      }
      bar.appendChild(el);
    });
    // 탭 1개(home만) 이하 → 탭바 자동 숨김. 2개 이상일 때만 노출.
    bar.style.display = tabs.length > 1 ? "flex" : "none";
    hint = document.createElement("span"); hint.id = "hint"; bar.appendChild(hint);
    if(tabs.length > 1){
      var ca = document.createElement("button"); ca.id = "closeall"; ca.type = "button";
      ca.textContent = "🗑️ 모든 탭 닫기";
      ca.onclick = function(ev){ ev.stopPropagation(); closeAllTabs(); };
      bar.appendChild(ca);
    }
    updateHint();
    saveTabs();
  }
  function active(){ return tabs.filter(function(t){return t.id===activeId;})[0]; }
  function updateHint(){
    var a = active();
    var parts = [];
    if(a && RENDER_CT[a.content_type]) parts.push("탭 닫기: " + SHORTCUT);
    if(tabs.length > 1) parts.push("탭 전환: alt+Tab");
    parts.push("Hub: alt+h");   // fpm 로고 버튼 단축키 (홈 탭 = 통합 Hub)
    hint.textContent = parts.join("  ·  ");
  }
  // Issue202: iframe 로드는 _shell=1 마커를 붙여 결정적으로 "쉘 임베드"임을 표시.
  //   서버 _handle_htm_doc 는 _shell 마커 없는 /htm-doc(=최상위 직접 열람)만 /hub-shell 로 302.
  //   Sec-Fetch-Dest 헤더 의존 제거(일부 네비에서 헤더 누락 → standalone 누출 차단).
  function embedUrl(u){
    if(!u) return u;
    // Issue203: 상대 경로(/...) + 동일 origin 절대 URL 모두 _shell 마커 부여. 절대 URL 에
    //   마커 누락 시 /htm-doc 가 top-level 로 오인 → 302 /hub-shell 중첩(탭 세로 적층).
    var isRel = u.charAt(0) === "/";
    var isSameOrigin = u.indexOf(location.origin + "/") === 0;
    if(!isRel && !isSameOrigin) return u;  // 외부 URL 은 그대로
    return u + (u.indexOf("?")>=0 ? "&" : "?") + "_shell=1";
  }
  // Issue223: iframe 재네비 디바운스 — 탭을 빠르게 연속으로 닫으면 closeTab→activate 가
  //   매번 view.src 를 재할당해 iframe 을 버스트 재네비게이트했다. 각 문서가 자기 SSE
  //   EventSource 를 생성/고아화 → Chrome 호스트당 연결 6개 상한 포화 → 렌더러 크래시.
  //   navTo 는 60ms 윈도로 버스트를 코얼레싱(최종 목표 1회만 네비) + 현재 로드 URL 과
  //   동일하면 skip(멱등 가드). 탭바 하이라이트(render)는 동기 유지 — 시각 지연 없음.
  var _navTimer = null, _navTarget = null, _curSrc = null;
  // Issue258(재수정): iframe `src` 재할당 대신 노드 자체를 교체(swap)한다.
  //   [이전 오판] commit 4022897 은 "내부 탭 여러 개 → SSE 호스트당 6연결 상한 포화 →
  //     크래시" 로 진단했으나, hub-shell 은 iframe 1개를 공유(내부 탭 전환/닫기 = 그 iframe
  //     하나만 재네비) → doc SSE 항상 ≤1 → hub-shell(1)+doc(1)=최대 2연결. 6상한 도달 불가.
  //     크래시 덤프(EXC_BREAKPOINT, Google Chrome Framework)는 연결 블록이 아니라 렌더러
  //     불변식 abort 였다. SSE 게이팅은 존재하지 않는 문제를 겨냥 → 재발.
  //   [실제 원인] alt+w 반복 닫기 → `view.src` 반복 재할당이 구 document 를 같은 frame
  //     슬롯에서 재사용. doc 페이지에 unload 정리가 없어 detached document·SSE 가 누적 →
  //     Chrome 렌더러 CHECK/PartitionAlloc abort. Issue223 60ms 디바운스는 동기 재진입만
  //     코얼레싱 → 느린 반복 닫기의 full 재네비 누수는 미커버였다.
  //   [수정] 매 네비마다 iframe 노드를 폐기·신규 생성 → 구 document/SSE 완전 teardown,
  //     detached 누수 사슬 절단 + frame 재사용 CHECK 클래스 제거.
  function onViewLoad(){
    try {
      var d = view.contentDocument;
      if(d){ d.removeEventListener("keydown", onKeydown); d.addEventListener("keydown", onKeydown); }
    } catch(_){ /* cross-origin 문서: 접근 불가 → 무시 */ }
  }
  function swapView(u){
    var fresh = document.createElement("iframe");
    fresh.id = "view";
    fresh.addEventListener("load", onViewLoad);
    var old = view;
    view = fresh;                          // 전역 참조 갱신(이후 navTo·onViewLoad 가 신규 노드 사용)
    old.replaceWith(fresh);               // 구 iframe DOM 제거 → 구 document 렌더러 frame 폐기
    fresh.src = u;
    _curSrc = u;
  }
  function navTo(url){
    _navTarget = url;
    if(_navTimer) return;                 // 이미 예약됨 → 최종 _navTarget 만 반영
    _navTimer = setTimeout(function(){
      _navTimer = null;
      var u = _navTarget; _navTarget = null;
      if(u == null) return;
      try{
        var abs = new URL(u, location.href).href;
        var cur = _curSrc ? new URL(_curSrc, location.href).href : null;
        if(abs === cur) return;           // 멱등 가드: 같은 문서 재로딩 차단(불필요 swap 방지)
      }catch(_){}
      swapView(u);
    }, 60);
  }
  function activate(id){
    var t = tabs.filter(function(x){return x.id===id;})[0]; if(!t) return;
    activeId = id; navTo(embedUrl(t.view_url)); render();
  }
  function closeTab(id){
    if(id === "home") return;
    var idx = tabs.findIndex(function(t){return t.id===id;}); if(idx<0) return;
    tabs.splice(idx,1);
    if(activeId === id){ activate(tabs[Math.max(0,idx-1)].id); } else { render(); }
  }
  // home 제외 전체 닫기 → home 활성화
  function closeAllTabs(){
    tabs = tabs.filter(function(t){return t.id==="home";});
    activate("home");
  }
  // focus=true → 명시적 열기(카드 ↗ 클릭·신규 렌더 SSE). 이미 열린 탭이면 그 탭으로
  //   포커스 전환. focus=false → 백그라운드 폴 폴백(조용히 메타만 갱신, 사용자 시야 방해 금지).
  function addTab(d, focus){
    if(!d || !d.view_url) return;
    // dedup: 문서 식별자(view_url=path 내포) 기준. 폴링 재발견·SSE 중복은 같은 view_url →
    //   기존 탭 재사용, 서로 다른 문서는 다른 view_url → 새 탭 추가. (이전: sid 기준 →
    //   같은 세션의 별개 문서가 한 탭으로 replace 되던 버그. 세션당 1탭 정책 폐기.)
    var ex = tabs.filter(function(t){return t.view_url===d.view_url;})[0];
    if(ex){
      // 같은 문서 재발견 — 메타 갱신. 명시적 열기(focus)이고 비활성 탭이면 그 탭으로 전환
      //   (Issue: 이미 열린 탭 카드 재클릭 시 포커스 미이동 버그 수정). 폴 폴백(focus=false)
      //   이나 이미 활성 탭이면 reload 없이 render 만(폴 루프 iframe reload 폭주 방지).
      ex.title = d.title || ex.title; ex.content_type = d.content_type; ex.sid = d.sid || ex.sid;
      if(focus && ex.id !== activeId){ activate(ex.id); } else { render(); }
      return;
    }
    var id = "t" + Math.random().toString(36).slice(2);
    tabs.push({id:id, view_url:d.view_url, title:d.title, sid:d.sid, content_type:d.content_type});
    activate(id);
  }

  // 탭 닫기 단축키 (R2/R3) — 렌더 탭(content_type response/form/dashboard) 활성 시에만
  // macOS: Option+letter 는 e.key 가 특수문자(∑ 등)로 바뀜 → 물리 키 e.code 로 비교(레이아웃·Option 무관)
  function codeOf(key){
    if(key.length===1 && key>="a" && key<="z") return "Key" + key.toUpperCase();
    if(key.length===1 && key>="0" && key<="9") return "Digit" + key;
    if(key==="tab") return "Tab";
    return "";
  }
  function matchShortcut(e){
    var parts = String(SHORTCUT).toLowerCase().split("+");
    var key = parts[parts.length-1];
    var need = {ctrl: parts.indexOf("ctrl")>=0, alt: parts.indexOf("alt")>=0,
                shift: parts.indexOf("shift")>=0, meta: parts.indexOf("meta")>=0 || parts.indexOf("cmd")>=0};
    if(!(e.ctrlKey===need.ctrl && e.altKey===need.alt && e.shiftKey===need.shift && e.metaKey===need.meta)) return false;
    var code = codeOf(key);
    return code ? e.code===code : e.key.toLowerCase()===key;
  }
  // alt+Tab(다음) / alt+shift+Tab(이전) — 모든 탭 순환(content_type 무관).
  // macOS: option+Tab 은 OS 미점유 → 정상 동작. ⚠️ Windows: Alt+Tab 은 OS 앱 전환기가
  // 전역 선점 → keydown 이 페이지에 도달 못 함 → 무동작(에러 아님). mac 전용 수용(결정 2026-06-23).
  function cycleTab(dir){
    if(tabs.length < 2) return;
    var i = tabs.findIndex(function(t){return t.id===activeId;}); if(i<0) i=0;
    activate(tabs[(i + dir + tabs.length) % tabs.length].id);
  }
  function onKeydown(e){
    // Hub(홈 탭)로 이동 — alt+h. fpm 로고(.hub-link) 버튼 단축키.
    // macOS Option+h 는 e.key 가 특수문자(˙)로 바뀜 → 물리 키 e.code 로 비교.
    if(e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.code==="KeyH"){
      e.preventDefault(); activate("home"); return;
    }
    // 탭 순환 (e.code==="Tab" — Option 무관 물리 키)
    if(e.altKey && !e.ctrlKey && !e.metaKey && e.code==="Tab"){
      e.preventDefault(); cycleTab(e.shiftKey ? -1 : 1); return;
    }
    // 탭 닫기
    if(matchShortcut(e)){
      var a = active();
      if(a && RENDER_CT[a.content_type]){ e.preventDefault(); closeTab(a.id); }
    }
  }
  window.addEventListener("keydown", onKeydown);
  // iframe(same-origin) 내부 포커스 시 단축키 수신 — onViewLoad 가 매 swap 마다 재바인딩
  //   (Issue258: 노드 교체로 이전됨. 정적 초기 iframe 은 첫 activate 의 swapView 로 교체되며
  //    그때 onViewLoad 가 부착된다).

  // 단일 창 리스 오버레이
  var overlay = document.getElementById("overlay");
  var ovmsg = document.getElementById("ovmsg");
  var ovbtn = document.getElementById("ovbtn");
  function showOverlay(msg, showBtn){
    ovmsg.textContent = msg; ovbtn.style.display = showBtn ? "" : "none"; overlay.classList.add("show");
  }
  function hideOverlay(){ overlay.classList.remove("show"); }
  ovbtn.onclick = function(){
    fetch("/hub-claim", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({cid:cid})})
      .then(function(r){return r.json();}).then(function(){ hideOverlay(); connect(); })
      .catch(function(){ ovmsg.textContent = "인계 실패 — hub 서버 미응답"; });
  };

  // SSE 연결
  var es = null;
  function connect(){
    if(es){ try{es.close();}catch(_){}}
    es = new EventSource("/hub-events?cid=" + encodeURIComponent(cid));
    es.addEventListener("granted", function(){ hideOverlay(); });
    es.addEventListener("denied", function(ev){
      var d = {}; try{ d = JSON.parse(ev.data||"{}"); }catch(_){}
      try{es.close();}catch(_){}
      showOverlay("이 호스트에는 이미 hub 창이 열려 있습니다 (" + (d.age||0) + "초 전 시작).\n기존 창을 닫거나 아래에서 인계하세요.", true);
    });
    es.addEventListener("evicted", function(){
      try{es.close();}catch(_){}
      showOverlay("다른 창이 이 호스트의 hub 를 인계했습니다. 이 창은 비활성화됩니다.", false);
    });
    es.addEventListener("tab-open", function(ev){
      try{ addTab(JSON.parse(ev.data), true); }catch(_){}   // 신규 렌더 → 포커스
    });
    // Issue378: 서버가 "이 쉘은 더 이상 유효 표면이 아니다" 를 통지 → 현재 모드의 URI 로 자기이동.
    //   Issue377 의 302 는 새 요청에만 걸려 떠 있는 탭을 교정하지 못했다(수동 새로고침 요구).
    //   replace 로 이동해 무효 표면을 히스토리에 남기지 않는다(뒤로가기 복귀 차단).
    es.addEventListener("mode-change", function(ev){
      var d = {}; try{ d = JSON.parse(ev.data||"{}"); }catch(_){}
      try{es.close();}catch(_){}
      location.replace(d.dest || "/hub");
    });
  }

  // Issue194: iframe(/hub 홈 탭 등) 카드 열기(↗) → 내부 탭. 동일 origin postMessage.
  window.addEventListener("message", function(ev){
    var d = ev.data;
    if(d && d.type === "fpm-open-tab" && d.view_url){
      addTab({view_url:d.view_url, title:d.title, sid:d.sid, content_type:d.content_type}, true);  // 카드 ↗ 클릭 → 포커스
    }
    // Issue216: 문서 헤더의 닫기 버튼(window.close())은 iframe 안에선 no-op →
    //   serve 시 주입된 close 쉼(CLOSE_SHIM)이 이 메시지를 부모 쉘로 보낸다.
    //   활성 탭(=메시지를 보낸 iframe)을 닫는다. home 탭은 닫지 않음.
    if(d && d.type === "fpm-close-tab"){
      var a = active();
      if(a && a.id !== "home"){ closeTab(a.id); }
    }
    // Issue220: 문서 헤더 🗂 Hub 링크 클릭(HUB_LINK_SHIM) → home 탭 전환 (iframe in-place 네비 대신).
    if(d && d.type === "fpm-goto-home"){ activate("home"); }
  });

  // Issue199: 폴링 fallback — SSE 끊김(서버 재시작) 구간에 누락된 신규 렌더 문서를
  //   레지스트리(/boards)에서 수거. 탭 목록 SOT 를 SSE 단독 → 레지스트리로 보강.
  //   첫 폴은 baseline(현재 최신 mtime_ts)만 잡고 기존 문서 폭주 방지 → 이후 baseline 초과분만 추가.
  var pollBaseline = 0, pollInit = false;
  function ctOf(u){ u = u || ""; return /_b_/.test(u) ? "form" : (/_c_/.test(u) ? "dashboard" : "response"); }
  function pollDocs(){
    fetch("/boards?_=" + Date.now(), {cache:"no-store"}).then(function(r){return r.json();}).then(function(j){
      // Issue378: SSE mode-change 폴백. SSE 가 끊긴 구간(서버 재시작·프록시 타임아웃)에는
      //   서버 통지가 도달하지 않으므로 폴링에서도 같은 판정을 한다(이중 안전망).
      if(j && j.render_tab_mode && j.render_tab_mode !== "hub-internal"){ location.replace("/hub"); return; }
      var docs = (j && j.htm_docs) || [];
      if(!pollInit){
        docs.forEach(function(d){ if(d.mtime_ts > pollBaseline) pollBaseline = d.mtime_ts; });
        pollInit = true; return;
      }
      docs.filter(function(d){ return d.view_url && !d.missing && d.mtime_ts > pollBaseline; })
          .sort(function(a,b){ return a.mtime_ts - b.mtime_ts; })
          .forEach(function(d){
            pollBaseline = Math.max(pollBaseline, d.mtime_ts);
            addTab({view_url:d.view_url, title:d.title, sid:d.sid || "", content_type:ctOf(d.path || d.view_url)}, false);  // 백그라운드 폴 → 포커스 미탈취
          });
    }).catch(function(){});
  }

  activate(activeId);            // 복원된 활성 탭 iframe 로드(+render)
  connect();
  pollDocs(); setInterval(pollDocs, 30000);
})();
</script>
</body>
</html>
"""

# Issue209: 외부(VSCode 등) 링크 클릭으로 열린 OS 새 탭에 serve 하는 경량 확인 페이지.
#   살아있는 hub-shell lease 보유자가 있을 때 302 /hub-shell(2번째 쉘 → takeover 오버레이)
#   대신 이 페이지를 보내고, 문서는 tab-open SSE 로 기존 쉘에 합류시킨다. __TITLE__ 치환.
HUB_OPENED_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>___pm — 기존 hub 창에 열림</title>
<link rel="icon" href="/fpm-icon.png">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    display: flex; min-height: 100vh; margin: 0; align-items: center;
    justify-content: center; background: #faf9f0; color: #1a1a1a; }
  .card { max-width: 460px; text-align: center; padding: 2rem; }
  .card h1 { font-size: 1.2rem; margin: 0 0 0.6rem; }
  .card p { line-height: 1.6; opacity: 0.85; }
  .doc { font-weight: 600; }
  button { margin-top: 1.2rem; font-size: 0.95rem; padding: 0.5rem 1.2rem;
    border-radius: 8px; border: 1px solid rgba(0,0,0,0.2);
    background: hsl(60,72%,80%); color: #1a1a1a; cursor: pointer; }
  button:hover { background: hsl(60,72%,72%); }
  @media (prefers-color-scheme: dark) {
    body { background: #1a1a1a; color: #e0e0e0; }
    button { background: #3a3a28; color: #eee; border-color: #555; }
    button:hover { background: #4a4a30; }
  }
</style>
</head>
<body>
<div class="card">
  <h1>✅ 기존 hub 창에 열었습니다</h1>
  <p><span class="doc">__TITLE__</span> 문서를 이미 열려 있는 hub 창에 새 탭으로 추가했습니다.<br>이 탭은 닫아도 됩니다.</p>
  <button type="button" onclick="window.close()">이 탭 닫기 ✕</button>
</div>
</body>
</html>
"""

# Issue216: hub-shell iframe 안에서 문서 헤더의 닫기 버튼은 window.close() 를 호출하나,
#   iframe 은 자신이 속한 탭(부모 쉘이 관리)을 닫을 수 없어 no-op 였다(Issue214 ✕ 닫기·
#   canonical 렌더 헤더 닫기 공통 결함). serve 시 window.close 를 override 하는 쉼을 주입해
#   임베드(_shell)면 부모 쉘로 fpm-close-tab postMessage(쉘이 활성 탭 닫음), 최상위
#   standalone 이면 네이티브 close 를 시도한다. 헤더 템플릿(prj3 자산) 수정 불요.
# Issue257: standalone(top-level 직접 열람 — 외부 브라우저 새 탭·주소창 입력)에서 native
#   window.close() 는 브라우저 보안상 script(window.open)로 연 창만 닫히므로 no-op(침묵 실패).
#   유저가 직접 연 탭·hub 가 `open -a` 로 연 탭은 안 닫힌다("닫기 안 됨"의 원인). native close
#   시도 후 80ms 뒤에도 창이 살아 있으면(=차단됨) /hub 로 funnel — 죽은 버튼 대신 쉘로 착지.
CLOSE_SHIM = (
    b"<script>(function(){var _c=window.close;window.close=function(){"
    b"if(window.parent&&window.parent!==window){"
    b"try{window.parent.postMessage({type:'fpm-close-tab'},'*');}catch(e){}"
    b"}else{try{_c.call(window);}catch(e){}"
    b"setTimeout(function(){try{location.href='/hub';}catch(e){}},80);}"
    b"};})();</script>"
)

# Issue214(재해결): canonical pink 헤더(prj3 자산, hook 템플릿)에는 🔗 "문서 링크 복사"
#   버튼이 없어 hub-shell iframe 안에서 주소창이 /hub-shell 만 보일 때 문서 URL 직접 복사가
#   불가했다(Issue214 의 핵심 목적이 dash 헤더에만 적용되고 메인 렌더 경로엔 누락). dash 헤더
#   _serve_dash_inline 와 동일한 복사 로직을 serve 시점에 주입해 prj3 템플릿 수정 없이 해소.
#   주입 스크립트는 nav.header-actions 의 닫기 버튼 직전에 🔗 버튼을 삽입.
# Issue(2026-07-03 링크 복사 오동작): 생성된 .htm 파일에는 hook 템플릿이 박은 구버전
#   onclick(무가드 navigator.clipboard.writeText)이 존재 — HTTP 비-localhost(host-1.local 등
#   insecure context)에선 navigator.clipboard 가 undefined 라 동기 TypeError 로 침묵 실패.
#   기존 버튼 발견 시 스킵하지 않고 **재바인딩**(onclick 교체)하여 과거 산출물도 서빙
#   시점에 교정. 복사 로직은 isSecureContext 가드 + execCommand fallback + prompt 최종 폴백.
COPY_LINK_SHIM = (
    b"<script>(function(){"
    b"function doCopy(b){var u=location.href.replace(/[?&]_shell=1$/,'');"
    b"function ok(){var o=b.textContent;b.textContent='\xe2\x9c\x93';setTimeout(function(){b.textContent=o;},1200);}"
    b"function fb(){try{var ta=document.createElement('textarea');ta.value=u;"
    b"ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);"
    b"ta.focus();ta.select();var r=document.execCommand('copy');document.body.removeChild(ta);"
    b"if(r){ok();}else{window.prompt('\xeb\xac\xb8\xec\x84\x9c \xeb\xa7\x81\xed\x81\xac \xeb\xb3\xb5\xec\x82\xac',u);}}"
    b"catch(e){window.prompt('\xeb\xac\xb8\xec\x84\x9c \xeb\xa7\x81\xed\x81\xac \xeb\xb3\xb5\xec\x82\xac',u);}}"
    b"if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(u).then(ok).catch(fb);}else{fb();}}"
    b"function ins(){"
    b"var nav=document.querySelector('header .header-actions');"
    b"if(!nav)return;"
    b"var b=nav.querySelector('.copy-link');"
    b"if(b){b.removeAttribute('onclick');b.onclick=function(){doCopy(b);};return;}"
    b"b=document.createElement('button');b.type='button';"
    b"b.className='copy-link';b.title='\xec\x9d\xb4 \xeb\xac\xb8\xec\x84\x9c \xeb\xa7\x81\xed\x81\xac \xeb\xb3\xb5\xec\x82\xac';"
    b"b.textContent='\xf0\x9f\x94\x97';"
    b"b.onclick=function(){doCopy(b);};"
    b"var c=nav.querySelector('button[onclick*=\"window.close\"]')||nav.querySelector('button:last-of-type');"
    b"if(c){nav.insertBefore(b,c);}else{nav.appendChild(b);}}"
    b"if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',ins);}else{ins();}"
    b"})();</script>"
)

# Issue278: 문서 헤더(.header-actions)에 📋 "세션 ID 복사" 버튼을 serve 시점에 주입.
#   Issue276/277 은 hub 메인 패널의 활성세션 목록 행에만 복사 버튼을 달았다. 문서를 만든
#   세션 sid 는 이미 헤더의 🆚 세션 버튼(.sess-link)이 onclick 에 `sid:'<UUID>'` 로 물고
#   있으므로, prj3 템플릿 수정 없이 그 sid 를 읽어 📋 버튼(🆚 뒤·🔗 앞)을 삽입한다.
#   COPY_LINK_SHIM 과 동형(isSecureContext 가드 + execCommand fallback + prompt 최종 폴백).
#   ⚠️ 반드시 COPY_LINK_SHIM **뒤에** 주입할 것 — COPY_LINK_SHIM 이 `.copy-link` 를
#   querySelector 로 잡아 rebind 하므로, 본 버튼은 `.copy-link` 클래스를 재사용하지 않는다.
#   표시 여부는 live_session_copy_button 옵션(Issue277)을 공유 — false 면 서버가 미주입.
#   (serve-time 주입 → 이미 열린 탭은 새로고침해야 반영, COPY_LINK_SHIM 과 동일.)
SID_COPY_SHIM = (
    "<script>(function(){"
    "function ins(){"
    "var nav=document.querySelector('header .header-actions');if(!nav)return;"
    "if(nav.querySelector('.copy-sid'))return;"
    "var sl=nav.querySelector('.sess-link');if(!sl)return;"
    "var oc=sl.getAttribute('onclick')||'';var m=oc.match(/sid:'([^']+)'/);"
    "if(!m||!m[1])return;var sid=m[1];"
    "function ok(b){var o=b.textContent;b.textContent='✓';setTimeout(function(){b.textContent=o;},1200);}"
    "function doCopy(b){function good(){ok(b);}"
    "function fb(){try{var ta=document.createElement('textarea');ta.value=sid;"
    "ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);"
    "ta.focus();ta.select();var r=document.execCommand('copy');document.body.removeChild(ta);"
    "if(r){good();}else{window.prompt('세션 ID 복사',sid);}}"
    "catch(e){window.prompt('세션 ID 복사',sid);}}"
    "if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(sid).then(good).catch(fb);}else{fb();}}"
    "var b=document.createElement('button');b.type='button';b.className='copy-sid';"
    "b.title='이 세션 ID 복사';b.setAttribute('aria-label','copy session id');"
    "b.style.justifyContent='center';b.style.padding='0.2rem 0.5rem';"
    "b.textContent='\U0001F4CB';"
    "b.onclick=function(){doCopy(b);};"
    "var c=nav.querySelector('.copy-link')||nav.querySelector('button[onclick*=\"window.close\"]')||nav.querySelector('.close-btn');"
    "if(c){nav.insertBefore(b,c);}else{nav.appendChild(b);}}"
    "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',ins);}else{ins();}"
    "})();</script>"
).encode("utf-8")

# Issue220: 문서 헤더의 🗂 Hub 링크(.hub-link, href="/hub")는 hub-shell iframe 안에서
#   클릭 시 iframe 을 in-place 로 /hub 로 네비게이트 → 현재 문서 탭이 /hub 로 바뀌어
#   "새로고침"처럼 보이고, 정작 쉘의 기존 home(🗂 Hub) 탭으로는 전환되지 않았다(alt+h 와
#   동작 불일치). serve 시 .hub-link 클릭을 가로채는 쉼을 주입해 임베드(_shell)면 부모
#   쉘로 fpm-goto-home postMessage(쉘이 home 탭 활성화), 최상위 standalone 이면 native
#   href 동작을 유지한다. 헤더 템플릿(prj3 자산) 수정 불요 — CLOSE_SHIM 패턴과 동형.
HUB_LINK_SHIM = (
    b"<script>(function(){"
    b"if(!(window.parent&&window.parent!==window))return;"
    b"document.addEventListener('click',function(e){"
    b"var a=e.target&&e.target.closest&&e.target.closest('a.hub-link');"
    b"if(!a)return;e.preventDefault();"
    b"try{window.parent.postMessage({type:'fpm-goto-home'},'*');}catch(_){}"
    b"},true);})();</script>"
)


def _inject_before_body_end(body: bytes, snippet: bytes) -> bytes:
    """snippet 을 </body> 직전에 삽입(없으면 끝에 append)."""
    idx = body.lower().rfind(b"</body>")
    return body[:idx] + snippet + body[idx:] if idx >= 0 else body + snippet


# Issue255: /htm-doc·/view 로 serve 되는 문서의 상대 <img src> 는 문서 URL path 가
#   /htm-doc 고정이라 브라우저가 서버 루트 기준으로 해석해 404. serve 시 상대 src 를
#   /htm-res?doc=&rel= 절대 URL 로 재작성한다. data:/http(s):/루트(/) src 는 제외.
# Issue283: `file://` 절대경로 src 는 (a) 브라우저가 http 페이지에서 file: 로드를 차단하고
#   (b) 상대 rel 로 재작성돼도 404 → `/htm-res?doc=&abs=` 로 별도 재작성($HOME jail).
_IMG_SRC_RE = re.compile(rb'(<img\b[^>]*?\bsrc=)(["\'])(.*?)\2', re.IGNORECASE | re.DOTALL)


def _rewrite_relative_imgs(body: bytes, doc_abs: str, extra_query: str = "") -> bytes:
    from urllib.parse import quote as _q, unquote as _unq, urlparse as _up
    doc_q = _q(doc_abs, safe="").encode("ascii")
    extra = ("&" + extra_query).encode("ascii") if extra_query else b""

    def _sub(m):
        src = m.group(3)
        low = src.lower()
        if (low.startswith((b"data:", b"http:", b"https:", b"//", b"/"))
                or not src.strip()):
            return m.group(0)
        # Issue283: `file:///abs/path` src (프로젝트 밖 절대경로 — ex 이미지 생성
        #   스킬이 ~/Desktop 에 저장한 파일)는 상대 rel 재작성으로 잡히지 않아
        #   `rel=file%3A%2F%2F%2F…` → 404. abs 모드로 별도 재작성한다.
        if low.startswith(b"file:"):
            p = _up(src.decode("utf-8", "replace"))
            if (p.netloc or "").lower() not in ("", "localhost"):
                return m.group(0)          # 원격 file://host/… 는 미변경
            abs_path = _unq(p.path or "")
            if not abs_path.startswith("/"):
                return m.group(0)
            abs_q = _q(abs_path, safe="").encode("ascii")
            return (m.group(1) + m.group(2)
                    + b"/htm-res?doc=" + doc_q + b"&abs=" + abs_q + extra
                    + m.group(2))
        rel_q = _q(src.decode("utf-8", "replace"), safe="").encode("ascii")
        return (m.group(1) + m.group(2)
                + b"/htm-res?doc=" + doc_q + b"&rel=" + rel_q + extra
                + m.group(2))

    return _IMG_SRC_RE.sub(_sub, body)


# Issue244: hub 문서의 mermaid 다이어그램이 "Syntax error in text (mermaid version
#   11.16.0)" bomb 로 간헐 깨지는 현상. 근본 원인은 문법 오류가 아니라 **런타임 drift**:
#   페이지가 제각각(esm@11 / umd@10 / umd@11 / esm@10)으로 mermaid 를 로드하고, 특히
#   비동기 esm(`mermaid.esm.min.mjs`) + `startOnLoad:true` 조합이 iframe(hub-shell·..ask
#   `<details>` 임베드) reflow 와 경쟁 → 텍스트 미확정 상태로 파싱되어 bomb 발생(standalone
#   에선 재현 안 되고 iframe 임베드 시 간헐 발생). 서버가 이미 모든 htm-doc 에 shim 을
#   주입하므로, mermaid 런타임도 서버가 단일 권위로 강제한다: 페이지가 무엇을 썼든
#   (1) 기존 mermaid <script> 를 제거하고 (2) pinned UMD(동기 로드) + startOnLoad 대신
#   명시적 mermaid.run() 을 주입 → race 제거. 페이지 저작 실수와 무관하게 결정적 렌더.
#   graceful degradation(CDN 실패 시 <pre> 원문 노출)은 그대로 유지.
_MERMAID_SCRIPT_RE = re.compile(
    rb"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL
)
# Issue299: 제거 대상은 mermaid **런타임을 싣거나 초기화하는** 스크립트로 한정한다.
#   종전 판정은 "블록 안에 mermaid 라는 문자열이 있는가"였고, 그 결과 다이어그램과 무관한
#   페이지 스크립트가 주석에 mermaid 를 언급했다는 이유만으로 통째로 사라졌다. 스크립트가
#   조용히 증발하므로 콘솔에도 아무 흔적이 없어 원인 추적이 어렵다(실측: Projects_map 의
#   활성 세션 오버레이가 이 규칙에 먹혀 배지가 하나도 뜨지 않았다).
#   Issue244 가 막으려던 것은 "페이지가 제각각 로드·초기화하는 mermaid 런타임"이므로,
#   로드(src/import)·초기화(initialize/run/render/startOnLoad)·전역 접근(window.mermaid)
#   신호가 있을 때만 지운다.
_MERMAID_LOADER_RE = re.compile(
    rb"<script\b[^>]*\bsrc\s*=\s*[\"'][^\"']*mermaid"
    rb"|mermaid\s*\.\s*(?:initialize|run|render|mermaidAPI)"
    rb"|window\s*\.\s*mermaid"
    rb"|\bimport\b[^;]{0,200}?[\"'][^\"']*mermaid"
    rb"|startOnLoad",
    re.IGNORECASE,
)
# pinned UMD(동기) + mermaid.run() — startOnLoad race 없는 결정적 렌더.
MERMAID_RUNTIME = (
    # Issue302: 다이어그램은 `<pre class="mermaid">` 로 저작되므로 페이지의 코드블록 스타일
    #   (`pre { background:#2d2d2d }`)을 그대로 상속한다. mermaid 가 그리는 SVG 는 배경이
    #   투명하므로 검은 코드블록 배경이 그대로 비쳐, theme 이 neutral(밝음)로 정상 선택돼도
    #   화면에는 밝은 노드 + 검은 캔버스라는 mismatch 가 남았다(Issue245 의 luminance 판정은
    #   `document.body` 만 보므로 `<pre>` 자체 배경은 사정권 밖). 런타임이 컨테이너 배경까지
    #   같은 자리에서 책임져 저작 실수와 무관하게 페이지와 일치시킨다.
    b"<style>pre.mermaid,.mermaid{background:transparent;color:inherit;padding:0;}</style>"
    b'<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>'
    b"<script>(function(){"
    # Issue245: 테마는 OS prefers-color-scheme 가 아니라 **실제 페이지 배경 luminance** 로
    #   결정 → 밝은 hub 페이지에 어두운 다이어그램이 얹히는 mismatch 제거(페이지와 항상 일치).
    b"function darkBg(){try{var c=getComputedStyle(document.body).backgroundColor||'';"
    b"var m=c.match(/[0-9.]+/g);if(!m)return false;"
    b"if(m.length>3&&parseFloat(m[3])===0)return false;"  # 투명 배경 = 밝은 페이지로 간주
    b"var lum=0.299*+m[0]+0.587*+m[1]+0.114*+m[2];return lum<128;}catch(e){return false;}}"
    b"function run(){if(!window.mermaid)return;try{"
    b"window.mermaid.initialize({startOnLoad:false,theme:darkBg()?'dark':'neutral'});"
    b"window.mermaid.run();}catch(e){console.error('mermaid run failed',e);}}"
    b"if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',run);}"
    b"else{run();}})();</script>"
)


# Issue256: a모드 htm 이 mermaid 를 `<div class="mermaid-box"><pre><code>flowchart…`
#   (코드펜스 산출물)로 저작하면 `class="mermaid"` 게이트를 통과 못 해 런타임이 주입되지
#   않고 소스 평문으로 노출됨. Issue244 철학(서버가 단일 권위로 결정적 렌더)을 연장하여,
#   저작 실수와 무관하게 서버가 코드펜스 mermaid 를 `<pre class="mermaid">` 로 재작성한다.
#   첫 유의미 라인이 mermaid 다이어그램 키워드일 때만 변환(non-mermaid 코드블록 false-positive 억제).
_MERMAID_KEYWORDS = (
    "sequenceDiagram", "classDiagram", "stateDiagram-v2", "stateDiagram",
    "erDiagram", "flowchart", "graph", "journey", "gantt", "pie",
    "gitGraph", "mindmap", "timeline", "quadrantChart", "requirementDiagram",
    "C4Context", "sankey-beta", "xychart-beta", "block-beta",
)
_CODEBLOCK_RE = re.compile(
    rb"<pre\b[^>]*>\s*<code\b[^>]*>(.*?)</code>\s*</pre>",
    re.IGNORECASE | re.DOTALL,
)


def _looks_like_mermaid(inner_text: str) -> bool:
    for line in inner_text.splitlines():
        t = line.strip()
        if not t or t.startswith("%%"):  # 공백·directive/comment 스킵
            continue
        first = t.split(None, 1)[0]
        return any(first == k or first.startswith(k) for k in _MERMAID_KEYWORDS)
    return False


def _rewrite_mermaid_codeblocks(body: bytes) -> bytes:
    r"""`<pre><code>` 로 저작된 mermaid 코드펜스를 `<pre class="mermaid">` 로 재작성.
    엔티티(`&gt;`·`&lt;`)는 유지 — 브라우저 textContent 가 `-->`·`<` 로 자동 복원해
    mermaid.run() 이 올바로 파싱함. 단 라벨 줄바꿈 의도의 리터럴 `\n` 은 `&lt;br/&gt;`
    (textContent = `<br/>`)로 치환해 노드 라벨이 줄바꿈되게 한다."""
    import html as _html

    def _sub(m):
        inner = m.group(1)
        text = _html.unescape(inner.decode("utf-8", "replace"))
        if not _looks_like_mermaid(text):
            return m.group(0)
        rewritten = inner.replace(rb"\n", b"&lt;br/&gt;")
        return b'<pre class="mermaid">' + rewritten + b"</pre>"

    return _CODEBLOCK_RE.sub(_sub, body)


def _normalize_mermaid_runtime(body: bytes) -> bytes:
    """페이지 저작 mermaid <script>(esm/umd·버전 제각각)를 제거하고 서버 표준
    pinned UMD 런타임으로 치환. 코드펜스 저작(`<pre><code>`)은 먼저 `class="mermaid"`
    로 재작성(Issue256) 후 처리. `class="mermaid"` 블록이 있을 때만 런타임 주입."""
    body = _rewrite_mermaid_codeblocks(body)
    if b'class="mermaid"' not in body:
        return body

    def _drop(m):
        return b"" if _MERMAID_LOADER_RE.search(m.group(0)) else m.group(0)

    body = _MERMAID_SCRIPT_RE.sub(_drop, body)
    return _inject_before_body_end(body, MERMAID_RUNTIME)


# Issue: a모드(`..show`) htm 은 Claude 가 매 렌더 `<style>` 전체를 손으로 재작성하므로
#   canonical 헤더 CSS(`header { position:sticky; background:hsl(238,45%,80%) … }`)를
#   일관되게 재현하지 못한다(관측: 5개 중 3개가 `header{}` 규칙 누락 → `<header>` 가
#   무스타일 body flow 로 흘러 보라 바·중앙 제목·버튼 chip 이 사라짐). Issue244(mermaid)
#   와 동일 철학으로 서버가 단일 권위로 강제한다: `<header>` 엘리먼트는 있는데 그것을
#   스타일하는 `header{` 규칙이 없으면 canonical 헤더 CSS 를 `<head>` 에 주입한다.
#   (이미 `header{` 규칙이 있으면 저작본을 존중하고 no-op.)
_HEADER_EL_RE = re.compile(rb"<header\b", re.IGNORECASE)
_HEADER_CSS_RE = re.compile(rb"header\s*\{", re.IGNORECASE)
HUB_HEADER_CSS = (
    b'<style id="hub-header-normalized">'
    b"header { position: sticky; top: 0; z-index: 100; display: flex; align-items: center;"
    b"  justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.9rem 1.4rem;"
    b"  margin-inline: calc(50% - 50vw); background: hsl(238,45%,80%); color: #1a1a1a; }"
    b"header > .hub-link { flex: 0 0 auto; }"
    b"header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; text-align: center; }"
    b"header .header-actions { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }"
    b"header .proj-badge, header .sess-link, header .hub-link, header button {"
    b"  display: inline-flex; align-items: center; line-height: 1; color: #1a1a1a;"
    b"  text-decoration: none; cursor: pointer; white-space: nowrap; background: rgba(0,0,0,0.08);"
    b"  border: 1px solid rgba(0,0,0,0.15); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }"
    b"header .copy-link, header .close-btn { justify-content: center; padding: 0.2rem 0.5rem; }"
    b"header .close-btn { margin-left: 0.6rem; }"
    b"header .close-btn:hover { background: rgba(200,0,0,0.18); }"
    b"header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {"
    b"  background: rgba(0,0,0,0.16); text-decoration: underline; }"
    b"</style>"
)


# 본문 폭·표 정규화 (Issue: 문서 body max-width 중앙정렬로 헤더(full-bleed)와 폭 불일치 +
#   표 셀 넘침 잘림). 저작본 body{max-width} 를 무시하고 창 전체 폭 사용 + 표/코드/이미지가
#   컨테이너를 넘지 않게 강제. 항상 주입(header CSS 와 달리 저작본 유무 무관), <body> 직전에
#   넣어 <head> 저작 스타일보다 뒤 → 동일 특이도 tie 를 이기고 !important 로 확실히 override.
HUB_BODY_CSS = (
    b'<style id="hub-body-normalized">'
    b"body { max-width: none !important; margin: 0 !important;"
    b"  padding: 0 1.4rem 3rem !important; box-sizing: border-box; }"
    b"table { width: 100% !important; table-layout: auto; }"
    b"th, td { overflow-wrap: anywhere; word-break: break-word; }"
    b"pre, code { max-width: 100%; overflow-x: auto; }"
    b"img { max-width: 100%; height: auto; }"
    b"</style>"
)


def _normalize_hub_body_css(body: bytes) -> bytes:
    """저작 문서의 body max-width 중앙정렬을 무력화하고 창 전체 폭으로 렌더,
    표·코드·이미지가 뷰포트를 넘지 않게 강제(셀 텍스트는 wrap). 항상 주입."""
    return _inject_before_body_end(body, HUB_BODY_CSS)


def _normalize_hub_header_css(body: bytes) -> bytes:
    """`<header>` 엘리먼트가 있는데 그것을 스타일하는 `header{` CSS 규칙이 없으면
    canonical 헤더 CSS 를 `<head>` 에 주입(없으면 <body> 직전, 그것도 없으면 prepend).
    이미 `header{` 규칙이 있으면 저작본 존중 no-op."""
    if not _HEADER_EL_RE.search(body):
        return body
    if _HEADER_CSS_RE.search(body):
        return body
    low = body.lower()
    idx = low.rfind(b"</head>")
    if idx < 0:
        idx = low.find(b"<body")
    if idx < 0:
        return HUB_HEADER_CSS + body
    return body[:idx] + HUB_HEADER_CSS + body[idx:]


# 구 builder 산출 issue-map/projects-map 은 `<header>` 없이 `<h1>` 바만 방출했다(신 builder,
#   prj3 Issue320 부터 canonical <header> 방출). 이미 생성된 stale 맵은 재생성 전까지 헤더
#   아이콘이 없으므로, serve 시점에 첫 `<h1>` 을 canonical <header>(🗂hub-link + 📁proj-badge +
#   ✕close)로 승격한다. 🔗 복사 버튼은 COPY_LINK_SHIM, header CSS 는 _normalize_hub_header_css
#   가 후속으로 채운다. 이미 `<header>` 가 있으면(신 builder·authored) no-op.
_H1_RE = re.compile(rb"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _synthesize_hub_header(body: bytes, proj_cwd: str, proj_label: str) -> bytes:
    """헤더 없는 builder 맵(issue-map/projects-map)에 canonical <header> 합성 주입.
    첫 <h1> 을 헤더로 승격. proj_cwd 는 📁 proj-badge 의 /open-project 대상."""
    if _HEADER_EL_RE.search(body):
        return body
    m = _H1_RE.search(body)
    if not m:
        return body
    label = html.escape(proj_label)
    cwd_esc = html.escape(proj_cwd)
    onclick = (
        "event.preventDefault();fetch('/open-project',{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({cwd:'" + cwd_esc + "'})})"
        ".then(function(r){return r.json();}).then(function(j){if(j&&j.error)"
        "alert('VSCode 열기 실패: '+j.error);})"
        ".catch(function(){alert('hub 서버 미응답 — VSCode 열기 실패');});"
    )
    pre = (
        '<header>\n'
        '  <a class="hub-link" href="/hub" target="fpm-hub" '
        'title="통합 모니터링 Hub">'
        '<img src="/fpm-icon.png" alt="Hub" '
        'style="height:1.2em;vertical-align:-0.25em;"></a>\n'
        '  <h1>'
    ).encode("utf-8")
    post = (
        '</h1>\n'
        '  <nav class="header-actions">\n'
        '    <a class="proj-badge" href="#" '
        'title="클릭 → VSCode 로 ' + label + ' 열기" '
        'onclick="' + onclick + '">\U0001F4C1 ' + label + '</a>\n'
        '    <button type="button" class="close-btn" '
        'title="이 문서 탭 닫기" '
        'onclick="window.close()">✕</button>\n'
        '  </nav>\n'
        '</header>'
    ).encode("utf-8")
    return body[:m.start()] + pre + m.group(1) + post + body[m.end():]


pids_lock = threading.Lock()
pids = {}  # cwd_hash -> set[int]  (Issue16: stop 제어 대상으로 등록된 runner PIDs)

# Issue17 Phase 1: 세션 상태 모델
sessions_lock = threading.Lock()
sessions = {}  # (cwd_hash, sid) -> {mode, content_type, content, capabilities, created, updated}

# Issue29 Phase 6: ephemeral preview entries (sessions table 미반영, SSE 미전파)
preview_lock = threading.Lock()
previews = {}  # pid -> {cwd_hash, content_type, content, mode, created}
PREVIEW_TTL = 60  # seconds

start_ts = time.time()

# Issue41: hub registry — 등록 기반 hub 목록 (스캔 제거).
# 다른 프로젝트 디렉토리를 주기적으로 스캔하지 않고, 생산자(htm 스킬·dashboard runner)가
# /register-doc 로 등록한 파일 목록(data/hub/*.json)만 hub 에 노출한다.
# REPO_ROOT = server.py(.../services/htm-server/) → ___pm 루트 (dirname 3회)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _open_cmd(target: str, app: str | None = None) -> list:
    """플랫폼별 '열기' 명령 조립 (Issue432).

    종전엔 `["open", …]` 를 7곳에서 직접 썼고 **플랫폼 분기가 없었다.**
    `open` 은 macOS 전용이라 Linux·Windows 에서 그대로 깨진다 — fg1(Linux)에서
    드러나지 않은 이유는 헤드리스라 "열기" 를 쓸 일이 없었을 뿐이다.
    cdf(Issue340)가 셸 함수 쪽은 고쳤으나 이 서버는 손대지 않은 채였다.

    ⚠️ `app` 지정(에디터로 열기)은 **macOS 만 온전하다** — `open -a` 가 앱
    *표시 이름*("Visual Studio Code")을 받기 때문이다. 다른 OS 에는 그런 개념이
    없어 실행 파일명이 필요하고, `_editor_app_name()` 의 반환값과 계약이 다르다.
    그래서 비-macOS 에서는 app 을 버리고 기본 연결 프로그램으로 연다 —
    **조용히 실패하는 것보다 낫다**(호출부가 로그를 남긴다).
    """
    sysname = platform.system()
    if sysname == "Darwin":
        return ["open"] + (["-a", app] if app else []) + [target]
    if sysname == "Windows" or sysname.startswith(("MINGW", "MSYS", "CYGWIN")):
        # `start` 는 cmd 내장이라 셸을 거쳐야 한다. 첫 "" 는 창 제목 자리(필수).
        return ["cmd", "/c", "start", "", target]
    return ["xdg-open", target]          # Linux·기타 POSIX


def _open_target(target: str, app: str | None = None, what: str = "") -> None:
    """열기 실행 + 실패를 삼키지 않는다."""
    try:
        subprocess.Popen(_open_cmd(target, app),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if app and platform.system() != "Darwin":
            log(f"[open] 앱 지정 무시({platform.system()}) — 기본 연결로 엶: {what or target}")
    except (OSError, subprocess.SubprocessError) as e:
        log(f"[open] 실패({platform.system()}): {what or target} — {e}")


DATA_HUB_DIR = os.path.join(REPO_ROOT, "data", "hub")
# Issue255: /htm-res 로 serve 허용하는 이미지 확장자 화이트리스트
_HTM_RES_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

HTM_REGISTRY = os.path.join(DATA_HUB_DIR, "htm-registry.json")
DASH_REGISTRY = os.path.join(DATA_HUB_DIR, "dash-registry.json")
# Issue53: clear 버튼으로 명시 제거된 htm path tombstone. autoheal 이 feed 버퍼에서
# 부활시키지 못하게 차단 (list[str], load_registry/save_registry 재사용).
HTM_CLEARED = os.path.join(DATA_HUB_DIR, "htm-cleared.json")
# Issue54: 명시 제거된 dash path tombstone (HTM_CLEARED 대칭). dash 는 autoheal 이
# 없고 /hub-rescan 이 유일한 재등록 경로 → rescan 이 이 tombstone path 를 skip 한다
# (htm 과 달리 rescan recover 안 함). 해제는 생산자의 명시 /register-doc 으로만.
DASH_CLEARED = os.path.join(DATA_HUB_DIR, "dash-cleared.json")
# Issue135: 수동 dismiss 된 live(claude) 세션 tombstone. dismiss 는 sessions.pop
#   만으론 부족 — VSCode 확장이 세션 UI 종료 후에도 claude native 프로세스를 살려두면
#   collect 의 live 게이트(_pid_alive(live_pid))가 영구 통과해, 다음 hook
#   register/heartbeat 가 sessions 를 재생성하며 카드가 부활한다(Issue132 후속 결함).
#   dismiss 시 (cwd_hash|sid)→ts 를 기록하고 collect 단계에서 TTL 내 항목을 표시
#   제외하여 부활을 차단한다. TTL 만료 후엔 자동 해제(살아있는 세션의 정상 재노출 허용).
#   dict[str, float] = {"{h}|{sid}": dismissed_at}. HTM_CLEARED/DASH_CLEARED 와 대칭.
LIVE_DISMISSED = os.path.join(DATA_HUB_DIR, "live-dismissed.json")
LIVE_DISMISS_TTL = 120.0
registry_lock = threading.Lock()


def load_registry(path: str) -> list:
    """data/hub/*.json 레지스트리 로드. 파일 부재·JSON 파손 시 빈 리스트 반환."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_registry(path: str, entries: list) -> None:
    """레지스트리 원자적 저장 (tmp 파일 → os.replace). data/hub/ 부재 시 생성."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _htm_entry_mtime(e: dict) -> float:
    """htm registry 항목의 신선도 기준 시각 (판정 단일 지점 — prune·clear 공용).
    파일 mtime 우선, stat 실패(이동·삭제) 시 registered_at fallback."""
    try:
        return os.path.getmtime(e.get("path", ""))
    except OSError:
        return e.get("registered_at", 0) or 0


# Issue352: htm-registry 자동 만료. 만료 정책이 없어 hub 문서 목록이 무한 누적됐고
#   (실측 jm4 168건·fg1 17건), 정리 수단이 UI 버튼 수동 호출뿐이라 `..hub off` 를 해도
#   목록이 그대로 남아 "꺼도 옛날 게 보인다"로 관측됐다. 만료를 서버가 스스로 수행한다.
#
#   판정: mtime 최신순 상위 keep 개 보존 → 나머지는 age_days 이내만 보존 → 그 외 제거.
#   ⚠️ tombstone(HTM_CLEARED)을 남기지 않는다 — clear-htm-docs 는 사용자의 명시적 삭제
#      의도라 부활을 차단하지만, 자동 만료는 사용자 의도가 아니므로 /hub-rescan 으로
#      복구 가능해야 한다. tombstone 을 남기면 무한 성장 + 영구 복구 불가가 된다.
#   파일은 삭제하지 않는다 (hub 연결만 끊음 — clear-htm-docs 와 동일 원칙).
_HTM_PRUNE_TTL = 60.0        # 실제 prune 최소 간격(초). hub 는 5초 polling 이라 가드 필수
_htm_prune_next = 0.0
_htm_prune_lock = threading.Lock()


def _prune_htm_registry(force: bool = False) -> int:
    """만료 기준 초과 htm registry 항목 제거. 반환: 제거 건수 (0=미수행·해당 없음).
    정책값 SSOT: _doc_arch/htm-lifecycle-design.md (age 7일 + keep-N 20)."""
    global _htm_prune_next
    now = time.time()
    with _htm_prune_lock:
        if not force and now < _htm_prune_next:
            return 0
        _htm_prune_next = now + _HTM_PRUNE_TTL
    setting = _load_hub_setting()
    try:
        keep = int(setting.get("htm_registry_keep", 20))
    except (TypeError, ValueError):
        keep = 20
    try:
        age_days = float(setting.get("htm_registry_age_days", 7))
    except (TypeError, ValueError):
        age_days = 7.0
    keep = max(keep, 0)
    age_days = max(age_days, 0.0)
    if keep <= 0 and age_days <= 0:
        return 0                       # 양쪽 0 = 만료 비활성 (기존 card_limit 패턴 승계)
    cutoff = (now - age_days * 86400.0) if age_days > 0 else None
    with registry_lock:
        entries = load_registry(HTM_REGISTRY)
        total = len(entries)
        if not total:
            return 0
        ordered = sorted(entries, key=_htm_entry_mtime, reverse=True)
        kept = ordered[:keep]
        if cutoff is not None:
            kept += [e for e in ordered[keep:] if _htm_entry_mtime(e) >= cutoff]
        if len(kept) >= total:
            return 0                   # 제거 대상 없음 — 쓰기 생략
        removed = total - len(kept)
        save_registry(HTM_REGISTRY, kept)
    log(f"htm-registry prune — removed={removed} kept={len(kept)} total={total} "
        f"(keep={keep}, age={age_days}d, tombstone 미기록 — rescan 복구 가능)")
    return removed


def _save_live_dismissed(d: dict) -> None:
    """live-dismissed tombstone 원자적 저장 (Issue135)."""
    os.makedirs(os.path.dirname(LIVE_DISMISSED), exist_ok=True)
    tmp = LIVE_DISMISSED + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LIVE_DISMISSED)


def _load_live_dismissed() -> dict:
    """live-dismissed tombstone 로드 + TTL 만료분 lazy purge (Issue135).
    {"{h}|{sid}": dismissed_at} 반환. 파일 부재·파손 시 빈 dict.
    만료분이 생기면 즉시 flush 하여 파일 비대를 막는다 (sid 는 일회성이라
    죽은 세션 tombstone 은 TTL 후 영구 무용 → 청소)."""
    try:
        with open(LIVE_DISMISSED, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
    except (OSError, ValueError):
        return {}
    now = time.time()
    fresh = {k: v for k, v in data.items()
             if isinstance(v, (int, float)) and now - v < LIVE_DISMISS_TTL}
    if len(fresh) != len(data):
        try:
            _save_live_dismissed(fresh)
        except OSError:
            pass
    return fresh


def _live_dismiss_add(h: str, sid: str) -> None:
    """(h, sid) dismiss 시각 기록 → TTL 시작 (Issue135). registry_lock 으로 직렬화."""
    with registry_lock:
        d = _load_live_dismissed()
        d[f"{h}|{sid}"] = time.time()
        _save_live_dismissed(d)


# Issue51: feed detail 에 등장한 htm html 경로를 htm-registry 에 자가 등록.
# /register-doc 는 글로벌 SCAR(htm 스킬)가 책임지나 서버 다운·호출 누락 시 영구 미등록 됨.
# hook 이벤트는 항상 수신되므로 detail 의 htm 경로를 디스크 확인 후 보강한다.
# Issue289: 단일 z_htm 고정에서 HTM_DIRS 전체 alternation 으로 확장.
_HTM_DOC_PATH_RE = re.compile(
    r"/[^\s`\"'<>]+/_doc_work/(?:"
    + "|".join(re.escape(d) for d in HTM_DIRS)
    # Issue353_1: 현행 hub_htm_*.{htm,md} 도 feed autoheal 대상 (md-first 산출 포함)
    + r")/(?:claude-htm-[^\s`\"'<>]+\.html|hub_htm_[^\s`\"'<>]+\.(?:htm|md))")


def _autoheal_htm_registry(feed_items: list) -> None:
    """feed 항목 detail 에서 htm html 절대경로를 추출, 디스크에 존재하나
    htm-registry 미등록인 항목을 자동 등록한다 (___pm 서버 단독 읽기 경로 보강).
    cwd 는 경로의 `/_doc_work/{HTM_DIRS 항목}/` 앞부분으로 유추 — feed cwd 비신뢰.
    Issue53: HTM_CLEARED tombstone 에 든 path 는 부활시키지 않는다."""
    found = {}
    for it in feed_items:
        detail = it.get("detail") or ""
        if "_doc_work/" not in detail:  # 저비용 prefilter (정밀 판정은 정규식)
            continue
        for raw in _HTM_DOC_PATH_RE.findall(detail):
            # 슬래시 중복 등 비정상 prefix 정규화 (cwd_hash 분기 차단)
            m = os.path.normpath(raw)
            if m not in found and os.path.isfile(m):
                cwd = ""
                for d in HTM_DIRS:
                    idx = m.find(f"/_doc_work/{d}/")
                    if idx > 0:
                        cwd = m[:idx]
                        break
                found[m] = cwd
    if not found:
        return
    with registry_lock:
        entries = load_registry(HTM_REGISTRY)
        known = {e.get("path") for e in entries}
        # Issue53: clear 로 명시 제거된 path 는 부활 금지 — clear 무효화 방지.
        cleared = set(load_registry(HTM_CLEARED))
        now = int(time.time())
        added = 0
        for path, cwd in found.items():
            if path in known or path in cleared:
                continue
            entries.append({"path": path, "cwd": cwd, "title": "",
                            "registered_at": now})
            added += 1
        if added:
            save_registry(HTM_REGISTRY, entries)
            log(f"autoheal htm-registry — +{added} from feed detail")


# Issue62: 피드 항목 ↔ htm 문서 ↗ 링크 매칭.
# 종래(Issue42_1)는 detail 에 htm 문서 절대경로가 그대로 들어있어야만 연결됐다.
# B모드(claude-htm-ask-*) 폼은 대화 도중 생성돼 완료 메시지에 경로가 없어
# 영구 미연결(↗ 미표시)이었다. 절대경로 → basename → 턴 근접 3단계로 보강.
_HTM_TS_RE = re.compile(r"claude-htm-(?:ask-|auto-)?(\d+)\.html$")
_HTM_TURN_MAX = 6 * 3600   # 첫 피드 항목 대상 최대 소급 윈도우(초)


def _htm_doc_ts(path: str) -> int:
    """htm 문서 파일명에 박힌 생성 timestamp(초) 추출. 실패 시 0."""
    m = _HTM_TS_RE.search(path or "")
    return int(m.group(1)) if m else 0


def _cwd_related(a: str, b: str) -> bool:
    """두 cwd 가 동일하거나 한쪽이 다른쪽의 하위 디렉토리이면 True.
    feed cwd 가 상위(_public), htm 문서 cwd 가 하위(_public/cli)인 사례 대응."""
    if not a or not b:
        return False
    if a == b:
        return True
    return a.startswith(b + os.sep) or b.startswith(a + os.sep)


def _link_feed_htm_docs(hook_feed: list, htm_docs: list) -> None:
    """피드 항목에 htm 문서 카드 제목(htm_title)·열기 URL(htm_view_url)을 연결.
    3단계 매칭 — 앞 단계가 성공하면 해당 항목은 다음 단계 대상에서 제외:
      1) detail 에 htm 문서 절대경로가 그대로 등장 (정확)
      2) detail 에 htm 문서 basename 이 등장 (상대경로·백틱 표기 대응)
      3) 턴 근접 — htm 문서 생성 ts 가 같은 프로젝트의 '직전 Stop ~ 해당 Stop'
         턴 구간에 들면 그 완료 피드 항목에 연결 (B모드 폼 — detail 에 경로
         언급이 전혀 없는 경우 대응)
    feed_buffer 원본 변경 없음 (호출부가 dict 복사본 전달)."""
    docs = [d for d in htm_docs
            if d.get("path") and d.get("view_url") and not d.get("missing")]
    if not docs:
        return
    # --- tier 1 + 2: 텍스트 매칭 ---
    for it in hook_feed:
        if it.get("htm_view_url"):
            continue
        detail = it.get("detail") or ""
        if not detail:
            continue
        for d in docs:
            p = d["path"]
            if p in detail or os.path.basename(p) in detail:
                it["htm_title"] = d.get("title") or ""
                it["htm_view_url"] = d.get("view_url") or ""
                break
    # --- tier 3: 턴 근접 매칭 (텍스트 미연결 항목만) ---
    indexed = sorted(
        ((it.get("ts") or 0, it) for it in hook_feed), key=lambda x: x[0])
    for d in docs:
        dts = _htm_doc_ts(d["path"]) or int(d.get("mtime_ts") or 0)
        if not dts:
            continue
        dcwd = d.get("cwd") or ""
        prev_ts = 0
        target = None
        for fts, it in indexed:
            if not _cwd_related(it.get("cwd") or "", dcwd):
                continue
            # htm 문서는 턴 종료(Stop) 전에 생성되므로 dts <= fts (동일 머신,
            # 시계 오차 무시 가능). 유예를 두면 다음 턴 문서가 직전 완료 피드로
            # 새어 들어가 오연결됨 — 유예 0.
            lower = prev_ts if prev_ts else (fts - _HTM_TURN_MAX)
            if lower < dts <= fts:
                target = it
                break
            prev_ts = fts
        if target is None or target.get("htm_view_url"):
            continue
        # 한 턴에 문서 여러 개면 가장 늦게 생성된 문서를 우선 연결
        if dts >= target.get("_htm_link_ts", 0):
            target["_htm_link_ts"] = dts
            target["htm_title"] = d.get("title") or ""
            target["htm_view_url"] = d.get("view_url") or ""
    for it in hook_feed:
        it.pop("_htm_link_ts", None)


# Issue45: hub registry 항목 파싱 결과 캐시 — (path, mtime) 불변이면 파일 재read·재parse 생략.
# hub 폴링(feed_poll_interval, 다중 브라우저)마다 등록 문서 전수 재파싱하던 오버헤드 제거.
# 추가·변경된 항목만 실제 IO. _load_projects_colors mtime 캐시와 동일 철학.
_DOC_CACHE_CAP = 256
_doc_parse_cache: dict = {}            # abs_path -> {"mtime_ts": float, "data": <any>}
_doc_parse_cache_lock = threading.Lock()


def doc_cache_get(path: str, mtime_ts: float):
    """캐시 hit(동일 mtime) 시 저장 data 반환, miss 시 None."""
    with _doc_parse_cache_lock:
        c = _doc_parse_cache.get(path)
        if c is not None and c["mtime_ts"] == mtime_ts:
            return c["data"]
    return None


def doc_cache_put(path: str, mtime_ts: float, data) -> None:
    """파싱 결과 캐시 적재. 항목 수 상한 초과 시 전체 비움 (registry clear·rename 누수 방지)."""
    with _doc_parse_cache_lock:
        if len(_doc_parse_cache) >= _DOC_CACHE_CAP and path not in _doc_parse_cache:
            _doc_parse_cache.clear()
        _doc_parse_cache[path] = {"mtime_ts": mtime_ts, "data": data}


# Issue258: 레벨 로깅 (prj15 fSnippet Logger 모델). hub_setting.yml `log_level` 이 임계값 결정.
#   config 값 미만 레벨은 파일·stderr 양쪽 억제. 기본 INFO — VERBOSE/DEBUG 는 필요 시 config 로 개방.
#   Chrome AX 크래시(Issue237/258)처럼 hub 코드로 못 잡는 크래시의 "직전 이벤트 타임라인"을
#   서버측에서 상관 분석하기 위한 진단 인프라. crank log_level→VERBOSE 하면 렌더·SSE·탭 브레드크럼 노출.
LOG_LEVELS = {"VERBOSE": 0, "DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}
LOG_EMOJI = {"VERBOSE": "💬", "DEBUG": "🐛", "INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "🚨"}
_LOG_THRESHOLD = 2  # INFO 기본. _load_hub_setting() 이 log_level 파싱 시 갱신(_apply_log_level).


def log(msg: str, level: str = "INFO") -> None:
    lv = LOG_LEVELS.get(level.upper(), 2)
    if lv < _LOG_THRESHOLD:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {LOG_EMOJI.get(level.upper(), '')} [{level.upper()}] {msg}\n"
    sys.stderr.write(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass


def cwd_hash(cwd: str) -> str:
    return hashlib.md5(cwd.encode("utf-8")).hexdigest()[:8]


# Issue127 후속: hub 활성 세션 카드 제목을 VSCode 탭 제목(ai-title)과 일치시키기.
#   세션 JSONL 의 {"type":"ai-title","aiTitle":...} 가 VSCode 가 표시하는 제목의 SSOT.
#   live_label(프롬프트 요약)보다 ai-title 을 우선해 카드와 VSCode 가 동일 제목을 보이게 함.
PROJECTS_BASE = os.path.expanduser("~/.claude/projects")
_sid_path_cache: dict = {}             # sid -> 해석된 jsonl 절대경로 (수명 동안 불변 → 1회 해석)
_sid_path_cache_lock = threading.Lock()


def _resolve_session_jsonl(cwd: str, sid: str):
    """세션 JSONL(<sid>.jsonl) 절대경로 해석. (1) cwd 인코딩 직접 경로 (2) glob fallback.
    sid→경로는 세션 수명 동안 불변 → 발견 시 캐시하여 재탐색 회피."""
    if not sid:
        return None
    with _sid_path_cache_lock:
        hit = _sid_path_cache.get(sid)
    if hit:
        return hit
    path = None
    if cwd:
        enc = re.sub(r"[^a-zA-Z0-9]", "-", cwd)   # Claude Code projects dir 인코딩 규칙
        cand = os.path.join(PROJECTS_BASE, enc, f"{sid}.jsonl")
        if os.path.exists(cand):
            path = cand
    if path is None:   # cwd 가 subdir 로 바뀐 세션 등 — 전역 glob 으로 보강
        hits = glob.glob(os.path.join(PROJECTS_BASE, "*", f"{sid}.jsonl"))
        if hits:
            path = hits[0]
    if path:
        with _sid_path_cache_lock:
            if len(_sid_path_cache) >= 512:   # rename·세션 폭증 누수 방지
                _sid_path_cache.clear()
            _sid_path_cache[sid] = path
    return path


def _session_ai_title(cwd: str, sid: str):
    """세션 JSONL 의 최신 ai-title(aiTitle) 반환 — VSCode 탭 제목과 동일. 없으면 None.
    mtime 캐시(doc_cache)로 파일 무변경 시 재파싱 차단. 최신 ai-title 은 보통 EOF 근처라
    뒤에서부터 청크를 확장하며 reverse-scan (대형 세션 파일 전수 읽기 회피)."""
    path = _resolve_session_jsonl(cwd, sid)
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    ck = f"aititle:{path}"
    cached = doc_cache_get(ck, st.st_mtime)
    if cached is not None:
        return cached or None    # "" = title 없음 (재스캔 방지용 캐시값)
    title = None
    size = st.st_size
    try:
        for win in (262144, 1048576, 8388608):
            read = min(size, win)
            with open(path, "rb") as f:
                f.seek(size - read)
                chunk = f.read(read)
            lines = chunk.decode("utf-8", "ignore").splitlines()
            if read < size and lines:
                lines = lines[1:]   # window 경계로 잘린 첫 줄 폐기
            for ln in reversed(lines):
                if '"ai-title"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if d.get("type") == "ai-title":
                    t = d.get("aiTitle")
                    if isinstance(t, str) and t.strip():
                        title = t.strip()
                        break
            if title is not None or read >= size:
                break
    except OSError:
        pass
    doc_cache_put(ck, st.st_mtime, title or "")
    return title


def _clean_prompt_excerpt(body: str) -> str:
    """Issue328: 첫 user 프롬프트 원문 → 카드 제목용 1줄 정제.

    slash 커맨드 세션의 첫 user 레코드는 `<command-message>…</command-message>
    <command-name>/dev</command-name><command-args>…` 래퍼라 원문 그대로 쓰면
    카드가 태그로 도배된다. command-name 이 있으면 `/dev 인자` 형태로 축약하고,
    없으면 XML 유사 태그만 제거한다."""
    name = re.search(r"<command-name>\s*(.*?)\s*</command-name>", body, re.S)
    if name:
        cmd = name.group(1).strip()
        args = re.search(r"<command-args>\s*(.*?)\s*</command-args>", body, re.S)
        arg = (args.group(1).strip() if args else "")
        body = f"{cmd} {arg}".strip()
    else:
        body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", body).strip()


def _session_first_prompt(cwd: str, sid: str, limit: int = 60):
    """Issue328: 세션 JSONL 의 첫 user 프롬프트 1줄 발췌. 없으면 None.

    `ai-title` 은 VSCode 확장만 기록한다 — Zed(ACP/sdk-ts)·터미널 세션 JSONL 엔
    영구히 없다. 그 결과 title 이 항상 비어 Issue166 의 빈 세션 숨김 필터에 걸려
    살아있는 세션이 hub 에서 조용히 사라졌다. 프롬프트 발췌를 최종 폴백으로 둔다.

    head 방향 스캔(첫 user 는 파일 앞쪽) + mtime 캐시 — `_session_ai_title` 동일 패턴.
    첫 user 레코드는 불변이므로 캐시 적중률이 사실상 100%."""
    path = _resolve_session_jsonl(cwd, sid)
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    ck = f"firstprompt:{path}"
    cached = doc_cache_get(ck, st.st_mtime)
    if cached is not None:
        return cached or None    # "" = 발췌 불가 (재스캔 방지용 캐시값)
    text = None
    try:
        with open(path, "rb") as f:
            # 첫 user 는 통상 수 KB 이내. 상한을 둬 거대 파일 전수 읽기를 막는다.
            chunk = f.read(1048576)
        for ln in chunk.decode("utf-8", "ignore").splitlines():
            if '"user"' not in ln:
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue   # window 경계로 잘린 마지막 줄 등
            if d.get("type") != "user":
                continue
            content = (d.get("message") or {}).get("content")
            texts, _tools, _thinks = _transcript_block_text(content)
            body = " ".join(t for t in texts if t).strip()
            if not body:
                continue   # tool_result 만 있는 user 레코드 → 다음 후보
            body = _clean_prompt_excerpt(body)
            if not body:
                continue
            text = body[:limit].strip()
            break
    except OSError:
        pass
    doc_cache_put(ck, st.st_mtime, text or "")
    return text


def _live_session_title(cwd: str, sid: str, entry: dict):
    """live 세션의 카드 제목 — **판정 단일 지점** (Issue359).

    3단 폴백: ai-title(VSCode SSOT) → live_label(등록 시 전달) → 첫 프롬프트 발췌.
    셋 다 없으면 None = **아직 프롬프트를 받지 않은 세션**이다.

    ⚠️ 이 함수가 단일 지점인 이유 (2026-08-07 실측 사고):
    좀비 킬러(`/kill-empty-live`)는 "빈 세션"을 `live_label` 하나로만 판정했다.
    그런데 제목 소스는 Issue127(ai-title)·Issue328(first-prompt)로 늘어났고 그
    판정만 낡은 채 남았다. 결과로 **Zed·터미널 세션은 화면에 제목이 멀쩡히 떠
    있어도 구조적으로 항상 '빈 세션'** 이었다 — 그 둘은 ai-title 이 없고
    (VSCode 확장 전용) label 도 안 실려 오므로 3단계로만 제목을 얻기 때문이다.
    VSCode 세션도 SessionStart 훅이 label 을 생략하면(Issue121) 똑같이 걸렸다.
    실제로 버튼 1회 클릭에 작업 중이던 7개 세션이 전부 SIGTERM(code 143) 됐다.

    따라서 카드 렌더와 좀비 판정은 **반드시 이 함수 하나를 공유한다**. 제목 소스가
    또 늘어나도 여기만 고치면 양쪽이 함께 따라온다."""
    ai_title = _session_ai_title(cwd, sid)
    if ai_title:
        return ai_title
    lbl = (entry or {}).get("live_label")
    if isinstance(lbl, str) and lbl.strip():
        return lbl.strip()
    return _session_first_prompt(cwd, sid)


def _html_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _transcript_block_text(content):
    """JSONL message.content (str|list[block]) → 표시용 (텍스트, [도구라벨]) 추출.
    thinking 블록은 접어두기 위해 별도 수집, tool_use/tool_result 는 한 줄 요약."""
    texts, tools, thinks = [], [], []
    if isinstance(content, str):
        if content.strip():
            texts.append(content.strip())
        return texts, tools, thinks
    if isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                t = b.get("text", "")
                if t and t.strip():
                    texts.append(t.strip())
            elif bt == "thinking":
                t = b.get("thinking", "")
                if t and t.strip():
                    thinks.append(t.strip())
            elif bt == "tool_use":
                tools.append("🔧 " + str(b.get("name", "tool")))
            elif bt == "tool_result":
                # 결과는 길어 한 줄 요약(앞 120자)만
                c = b.get("content", "")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                c = (str(c) or "").strip().replace("\n", " ")
                tools.append("↩ 결과: " + (c[:120] + ("…" if len(c) > 120 else "")))
    return texts, tools, thinks


_TRANSCRIPT_TURN_LIMIT = 60       # 최근 N개 user/assistant 턴만 렌더
_TRANSCRIPT_TEXT_CHARS = 4000     # 텍스트 블록 1개 최대 길이


def _session_transcript_html(cwd, sid):
    """세션 JSONL → 대화 transcript HTML. content(푸시된 렌더)가 비어 있는
    터미널(CLI) 세션 등에서 '대화 내용 보기' 용도. 최근 N턴만, 긴 텍스트는 절단."""
    path = _resolve_session_jsonl(cwd, sid)
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    ck = f"transcript:{path}"
    cached = doc_cache_get(ck, st.st_mtime)
    if cached is not None:
        return cached or None
    turns = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or '"message"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                t = d.get("type")
                if t not in ("user", "assistant"):
                    continue
                msg = d.get("message")
                if not isinstance(msg, dict):
                    continue
                texts, tools, thinks = _transcript_block_text(msg.get("content"))
                if not texts and not tools and not thinks:
                    continue
                turns.append((t, texts, tools, thinks))
    except OSError:
        return None
    if not turns:
        doc_cache_put(ck, st.st_mtime, "")
        return None
    turns = turns[-_TRANSCRIPT_TURN_LIMIT:]
    parts = ['<div class="transcript">']
    parts.append('<p class="ts-note">⌨️ 터미널(CLI) 세션 — JSONL 대화 transcript '
                 f'(최근 {len(turns)}턴). 실시간 렌더가 아닌 기록 보기.</p>')
    for role, texts, tools, thinks in turns:
        label = "🧑 User" if role == "user" else "🤖 Assistant"
        cls = "ts-user" if role == "user" else "ts-asst"
        parts.append(f'<div class="ts-turn {cls}"><div class="ts-role">{label}</div>')
        for tx in texts:
            tx = tx[:_TRANSCRIPT_TEXT_CHARS] + ("…" if len(tx) > _TRANSCRIPT_TEXT_CHARS else "")
            parts.append(f'<pre class="ts-text">{_html_escape(tx)}</pre>')
        if thinks:
            joined = _html_escape("\n\n".join(th[:_TRANSCRIPT_TEXT_CHARS] for th in thinks))
            parts.append(f'<details class="ts-think"><summary>💭 thinking</summary>'
                         f'<pre>{joined}</pre></details>')
        for tl in tools:
            parts.append(f'<div class="ts-tool">{_html_escape(tl)}</div>')
        parts.append('</div>')
    parts.append('</div>')
    html = "".join(parts)
    doc_cache_put(ck, st.st_mtime, html)
    return html


# Issue28: Projects.md peacock.color 매핑 (cwd 경로 → hex 컬러). mtime 기반 캐시.
# 설치 위치 무관 ($FPM_BASE 기반). env 우선, 없으면 self-detect:
#   server.py = <FPM_BASE>/services/hub/server.py → 3단계 상위가 FPM_BASE.
# (구: ~/_git/___pm 하드코딩 → fg1 등 fpm 설치 머신에서 Projects.md 미발견 → 빈 목록 버그)
FPM_BASE = os.environ.get("FPM_BASE") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PROJECTS_MD = os.path.join(FPM_BASE, "Projects.md")
_projects_color_cache: dict = {}
_projects_color_cache_mtime: float = 0.0

# Issue303: 프로젝트 id 정본 패턴 — 정수 | 정수+소문자 | 정수+소문자+정수 (9 / 9a / 9a1).
#   접미는 "9 의 하위 프로젝트" 소속을 나타냄. 하이픈은 cdf 범위 문법(11-16)에 예약,
#   점은 정규식 메타문자라 둘 다 구분자에서 배제됨.
#   ⚠️ id 를 int 로 캐스팅하지 말 것 — 접미 id 는 int 로 담기지 않으며, 그 행이 조용히
#      스킵되면 등록은 됐는데 hub 목록에 안 보이는 상태가 된다.
#   설계 SSOT: <FPM_BASE>/_doc_arch/project-id-scheme.md
_PID_RE = re.compile(r"^([0-9]+)(?:([a-z])([0-9]*))?$")


def _pid_sort_key(pid: str):
    """id 정렬키 — (정수부, 문자부, 하위정수부). 부모 정수 → 그 자식들 → 다음 정수 순."""
    m = _PID_RE.match(str(pid))
    if not m:
        return (float("inf"), "", 0)
    return (int(m.group(1)), m.group(2) or "", int(m.group(3) or 0))

# Issue141: Servers.md — 원격 접근 allowlist 소스. check=O 행만 신뢰 대상.
# FPM_SERVERS_MD env 로 경로 override (플러그인 설치 위치 적응 — FPM_PROJECTS_MD 대칭).
SERVERS_MD = os.environ.get("FPM_SERVERS_MD", os.path.join(REPO_ROOT, "Servers.md"))
# 사설망(RFC1918) prefix — 공개 호스트 경고 판정용.
_PRIVATE_PREFIXES = ("10.", "192.168.", "127.", "169.254.") + tuple(
    f"172.{i}." for i in range(16, 32))


def _parse_servers_md(path: str) -> list:
    """Servers.md 의 Favorite Servers 테이블 파싱 → [{name, host, check, emoji}] 리스트.
    `| id | Name | ssh alias | Host | Port | User | Description | check | Emoji |` 형식.
    Emoji 는 Issue242 로 추가된 optional 마지막 컬럼(맨 끝 배치 → 기존 cells[:8] 파싱 무손상)."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.lstrip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 8:
                    continue
                _id, name, _alias, host, _port, _user, _desc, check = cells[:8]
                # 헤더·구분선 skip (id 가 숫자가 아닌 행).
                if not _id.isdigit():
                    continue
                emoji = cells[8] if len(cells) > 8 else ""
                rows.append({"name": name, "host": host, "check": check, "emoji": emoji})
    except (FileNotFoundError, OSError) as e:
        log(f"[allowlist] Servers.md 읽기 실패: {e}")
    return rows


# Issue242: 이모지 → 헤더 그라디언트 hue 큐레이션 맵. 미등록 이모지는 codepoint 해시 fallback.
#   L(명도)은 렌더 시 42~50% 고정 → 흰 텍스트 대비(명도차) 보장.
_EMOJI_HUE = {
    "🐧": 25, "🐳": 200, "🐋": 200, "🎮": 275, "🖥": 210, "🖥️": 210, "💻": 210,
    "🍎": 355, "🍏": 110, "🐍": 140, "⚡": 48, "🔥": 14, "🌊": 195, "🦾": 285,
    "🚀": 268, "🧠": 305, "🛰": 255, "☁": 205, "☁️": 205, "🪟": 205, "🌐": 190,
    "🟢": 130, "🔵": 215, "🟣": 285, "🟠": 30, "🔴": 358, "🟡": 50,
}


def _emoji_hue(emoji: str) -> int:
    """이모지 → 헤더 hue(0~359). 큐레이션 우선, 없으면 첫 codepoint 해시."""
    if not emoji:
        return 220
    if emoji in _EMOJI_HUE:
        return _EMOJI_HUE[emoji]
    return ord(emoji[0]) % 360


def _self_server_badge() -> tuple:
    """이 hub 서버(hostname)가 Servers.md 에 이모지와 함께 등록돼 있으면 (emoji, hue, name) 반환.
    미등록·이모지 공란이면 (None, None, None). hostname 은 short(첫 `.` 앞) 소문자로 Name 매치."""
    try:
        host = socket.gethostname().split(".")[0].strip().lower()
    except Exception:
        return None, None, None
    if not host:
        return None, None, None
    for row in _parse_servers_md(SERVERS_MD):
        if row.get("name", "").strip().lower() == host and row.get("emoji"):
            emoji = row["emoji"]
            return emoji, _emoji_hue(emoji), row.get("name", host)
    return None, None, None


def _load_server_allowlist() -> tuple:
    """Servers.md 의 check=O 호스트를 allowlist 로 적재 → (exact_ips set, networks list) 반환.
    Host 값에 `/` 가 있으면 CIDR(ip_network)로 해석(Issue175), 아니면 IP 로 resolve.
    resolve/파싱 실패 호스트는 skip+log. 공개 호스트(사설망 외)는 경고 log 로 가시화.
    HOST 가 루프백이 아닐 때(옵트인 개방)만 startup 에서 호출된다."""
    allowed = set()
    nets = []
    for row in _parse_servers_md(SERVERS_MD):
        if row["check"].upper() != "O":
            continue
        host = row["host"]
        # Issue175: CIDR 표기(`host/prefix`) → 서브넷 단위 허용.
        if "/" in host:
            try:
                net = ipaddress.ip_network(host, strict=False)
            except ValueError as e:
                log(f"[allowlist] CIDR 파싱 실패 skip — {row['name']}({host}): {e}")
                continue
            nets.append(net)
            public = not net.is_private
            warn = "  ⚠️ 공개 서브넷 — 노출 위험" if public else ""
            log(f"[allowlist] 허용(CIDR) — {row['name']} → {net}{warn}")
            continue
        try:
            ip = socket.gethostbyname(host)
        except (socket.gaierror, OSError) as e:
            log(f"[allowlist] resolve 실패 skip — {row['name']}({host}): {e}")
            continue
        allowed.add(ip)
        public = not any(ip.startswith(p) for p in _PRIVATE_PREFIXES)
        warn = "  ⚠️ 공개 IP — 노출 위험" if public else ""
        log(f"[allowlist] 허용 — {row['name']}({host}) → {ip}{warn}")
    return allowed, nets


def _ip_allowed(client_ip: str) -> bool:
    """source IP 가 접근 허용 대상인지. ALLOW_ALL(전체 개방 모드)이면 무조건 허용.
    아니면 루프백은 무조건 허용, 그 외는 ALLOWED_IPS(정확 일치) 또는
    ALLOWED_NETS(CIDR 서브넷 멤버십, Issue175)."""
    if ALLOW_ALL:
        return True
    if client_ip in LOOPBACK_IPS or client_ip in ALLOWED_IPS:
        return True
    if ALLOWED_NETS:
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            log(f"[allowlist] DENY(parse) — src={client_ip!r}")
            return False
        if any(addr in net for net in ALLOWED_NETS):
            return True
    log(f"[allowlist] DENY — src={client_ip!r} IPs={sorted(ALLOWED_IPS)} NETS={[str(n) for n in ALLOWED_NETS]}")
    return False


def _normalize_host(raw: str) -> str:
    """Host 헤더·설정값 → 비교용 정규형. `:port` 분리 · IPv6 `[...]` 해제 ·
    소문자화 · trailing dot(FQDN 절대표기) 제거. 빈 입력·파손 입력은 빈 문자열."""
    h = (raw or "").strip()
    if not h:
        return ""
    if h.startswith("["):          # IPv6 리터럴 — `[::1]:9876`
        end = h.find("]")
        if end == -1:
            return ""
        h = h[1:end]
    elif h.count(":") == 1:
        # 콜론 1개 + 뒤가 전부 숫자 → 포트. 콜론이 2개 이상이면 대괄호 없는 bare IPv6
        # (`::1`)이므로 건드리지 않는다 — 마지막 `:` 뒤를 포트로 보면 `::1` → `:` 로 뭉개진다.
        head, _, tail = h.partition(":")
        if tail.isdigit():
            h = head
    return h.rstrip(".").lower()


def _is_ip_literal(host: str) -> bool:
    """정규화된 host 가 IP 리터럴인가 (rebinding 판정용)."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _build_known_hosts() -> frozenset:
    """수신 허용 이름 집합 산출 — bind_host + advertise_host + localhost +
    hostname(+short+`.local`) + yml extra_hosts. 순수 문자열 조립이라 DNS 불요(bind 지연 0).

    IP 리터럴은 _host_allowed 가 무조건 통과시키므로 판정상 불필요하나,
    거부 로그에 "무엇이 허용 중인지" 를 그대로 보이기 위해 집합에 남긴다."""
    names = set()
    for h in BIND_HOSTS:
        n = _normalize_host(h)
        if n and n != "0.0.0.0":  # 와일드카드 bind 는 이름이 아니다
            names.add(n)
    setting = _load_hub_setting()
    adv = _normalize_host(str(setting.get("advertise_host") or ""))
    if adv:
        names.add(adv)
    for extra in (setting.get("extra_hosts") or []):
        n = _normalize_host(str(extra))
        if n:
            names.add(n)
    names.add("localhost")
    try:
        hn = _normalize_host(socket.gethostname())
    except OSError:
        hn = ""
    if hn:
        names.add(hn)
        short = hn.split(".")[0]
        if short:
            names.add(short)
            names.add(short + ".local")  # mDNS
    return frozenset(n for n in names if n)


def _host_allowed(raw_host: str, client_ip: str) -> bool:
    """Issue379: 수신 이름 게이트. 요청이 도달한 소켓이 아니라 **어느 이름으로 불렸는지**를 본다.

    통과 조건:
      1. 게이트 비활성(host_gate=false) 또는 known 집합 공집합 → fail-open(종전 동작)
      2. Host 가 IP 리터럴 → 항상 통과. rebinding 은 반드시 도메인 이름을 Host 로 보내므로
         방어를 약화시키지 않는다. 반대로 게이트 오설정 시 `http://127.0.0.1:9876` 으로
         항상 복구 가능하게 하여 자물쇠에 갇히는 사고를 구조적으로 막는다
      3. Host 부재(HTTP/1.0) → 루프백 소스에 한해 통과 (로컬 스크립트·curl)
      4. known 집합 멤버십"""
    if not HOST_GATE or not KNOWN_HOSTS:
        return True
    host = _normalize_host(raw_host)
    if not host:
        if client_ip in LOOPBACK_IPS:
            return True
        log(f"[hostgate] DENY(absent) — src={client_ip!r}")
        return False
    if _is_ip_literal(host):
        return True
    if host in KNOWN_HOSTS:
        return True
    log(f"[hostgate] DENY — host={host!r} src={client_ip!r} KNOWN={sorted(KNOWN_HOSTS)}")
    return False


def _load_projects_colors() -> dict:
    """Projects.md 의 📋 프로젝트 테이블에서 cwd 경로 → peacock.color 매핑 추출."""
    global _projects_color_cache, _projects_color_cache_mtime
    try:
        st = os.stat(PROJECTS_MD)
    except FileNotFoundError:
        return {}
    if st.st_mtime == _projects_color_cache_mtime and _projects_color_cache:
        return _projects_color_cache
    mapping: dict = {}
    try:
        with open(PROJECTS_MD, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 8:
                    continue
                # Issue303: 접미 id(9a) 포함. 헤더·구분선 행은 패턴 불일치로 skip.
                if not _PID_RE.match(cells[0]):
                    continue
                path_cell = cells[4].strip("`").strip()
                if not path_cell:
                    continue
                abs_path = os.path.expanduser(path_cell).rstrip("/")
                color_cell = cells[-1].strip()
                if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color_cell):
                    mapping[abs_path] = color_cell
    except Exception as e:
        log(f"_load_projects_colors failed: {e}")
        return _projects_color_cache or {}
    _projects_color_cache = mapping
    _projects_color_cache_mtime = st.st_mtime
    return mapping


# Issue46: Projects.md 이모지 컬럼 매핑 (cwd 경로 → 이모지). mtime 기반 캐시.
_projects_emoji_cache: dict = {}
_projects_emoji_cache_mtime: float = 0.0


def _load_projects_emojis() -> dict:
    """Projects.md 의 📋 프로젝트 테이블에서 cwd 경로 → 이모지 매핑 추출."""
    global _projects_emoji_cache, _projects_emoji_cache_mtime
    try:
        st = os.stat(PROJECTS_MD)
    except FileNotFoundError:
        return {}
    if st.st_mtime == _projects_emoji_cache_mtime and _projects_emoji_cache:
        return _projects_emoji_cache
    mapping: dict = {}
    try:
        with open(PROJECTS_MD, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 8:
                    continue
                # Issue303: 접미 id(9a) 포함. 헤더·구분선 행은 패턴 불일치로 skip.
                if not _PID_RE.match(cells[0]):
                    continue
                path_cell = cells[4].strip("`").strip()
                emoji_cell = cells[6].strip()
                if not path_cell or not emoji_cell:
                    continue
                abs_path = os.path.expanduser(path_cell).rstrip("/")
                mapping[abs_path] = emoji_cell
    except Exception as e:
        log(f"_load_projects_emojis failed: {e}")
        return _projects_emoji_cache or {}
    _projects_emoji_cache = mapping
    _projects_emoji_cache_mtime = st.st_mtime
    return mapping


def _project_emoji(cwd: str) -> str:
    """cwd 경로에 매핑된 Projects.md 이모지. 미등록 시 빈 문자열.
    Issue282: exact 실패 시 _resolve_project_root prefix fallback —
    서브폴더 cwd 카드도 name(prefix 매칭)과 동일 기준으로 이모지 유지."""
    if not cwd:
        return ""
    abs_cwd = os.path.expanduser(cwd).rstrip("/")
    exact = _load_projects_emojis().get(abs_cwd, "")
    if exact:
        return exact
    return _resolve_project_root(abs_cwd).get("emoji", "")


def _classify_model_tier(model_id: str) -> str:
    """Issue273: model_id → tier 문자열 (hub 활성세션 카드 신호등 이모지용).
    소문자 substring 매칭 → 버전 접미·`[1m]` 등 무관하게 안정. 미상 → "" (카드 무표시).
    tier↔이모지 매핑은 client(HUB_HTML): 🟣 opus / 🔵 sonnet / 🟢 haiku / 🟠 fable."""
    m = (model_id or "").lower()
    for tier in ("opus", "sonnet", "haiku", "fable"):
        if tier in m:
            return tier
    return ""


# Issue: Project List 팝업용 — Projects.md 📋 프로젝트 테이블 전체 행 추출. mtime 기반 캐시.
_projects_list_cache: list = []
_projects_list_cache_mtime: float = 0.0


def _load_projects_list() -> list:
    """Projects.md 📋 프로젝트 테이블에서 전체 프로젝트 메타 추출 (id/name/domain/path/desc/emoji/color)."""
    global _projects_list_cache, _projects_list_cache_mtime
    try:
        st = os.stat(PROJECTS_MD)
    except FileNotFoundError:
        return []
    if st.st_mtime == _projects_list_cache_mtime and _projects_list_cache:
        return _projects_list_cache
    rows: list = []
    try:
        with open(PROJECTS_MD, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 8:
                    continue
                # Issue303: 접미 id(9a) 포함 — 문자열로 보존(int 캐스팅 금지).
                pid = cells[0]
                if not _PID_RE.match(pid):
                    continue  # 헤더·구분선 행 skip
                color_cell = cells[7].strip()
                if not re.fullmatch(r"#[0-9a-fA-F]{3,8}", color_cell):
                    color_cell = ""
                rows.append({
                    "id": pid,
                    "name": cells[1],
                    "domain": cells[3],
                    "path": cells[4].strip("`").strip(),
                    "desc": cells[5],
                    "emoji": cells[6],
                    "color": color_cell,
                })
    except Exception as e:
        log(f"_load_projects_list failed: {e}")
        return _projects_list_cache or []
    rows.sort(key=lambda r: _pid_sort_key(r["id"]))
    _projects_list_cache = rows
    _projects_list_cache_mtime = st.st_mtime
    return rows


# Issue284: 이슈맵 문서(`Issue_map.htm`) 탐지 — issue-map 스킬(prj3 Issue246) 산출물.
#   위치 규약: `Issue.md` 와 같은 폴더(= nPTiR 루트). 세션 cwd 가 하위 폴더로 드리프트해도
#   찾도록 상위로 최대 _ISSUE_MAP_MAX_UP 단계 거슬러 올라가며 Issue.md 보유 디렉토리를 찾는다.
#   파일명은 `Issue_map.htm` 고정 (prj1#Issue286 / prj3#Issue246 합의 — 후보 목록 없음).
ISSUE_MAP_NAME = "Issue_map.htm"
# Issue293: 프로젝트 트리 맵(`Projects_map.htm`) — `Projects.md` 의 `# Project Tree` 섹션을
#   projects-map 생성기(.claude/skills/projects-map/build_projects_map.py)가 렌더한 산출물.
#   이슈맵과 달리 **___pm 루트에 1개만** 존재하므로 cwd 파라미터가 없고 경로는 서버 고정 —
#   클라이언트 입력면이 0 이라 traversal 게이트 자체가 성립하지 않는다(진입점 `_ip_allowed()` 만 적용).
#   gitignore 대상(재생성물)이라 부재가 정상 상태일 수 있어 404 는 재생성 안내로 응답한다.
PROJECTS_MAP_NAME = "Projects_map.htm"
PROJECTS_MAP_BUILDER = ".claude/skills/projects-map/build_projects_map.py"
_ISSUE_MAP_MAX_UP = 6
_ISSUE_MAP_TTL = 30.0            # 탐지 결과 캐시 수명(초) — /hub 폴링 5s 대비 stat 6배 절감
_issue_map_cache: dict = {}      # cwd(str) -> (expire_ts, path|None, has_graph: bool, stale: bool)
_issue_map_lock = threading.Lock()
# Issue284_3: 이슈 헤더(`## Issue1: …` / `### Issue1_2: …`) 줄이 `✅` 로 끝나면 완료 —
#   issue-map 스킬(build_issue_map.py)의 done 판정과 동일 신호(섹션명 하드코딩 없음).
_ISSUE_HEADER_RE = re.compile(r"^#{2,3}\s+Issue")
# Issue290: 섹션 헤딩(`# 📙 일반` 등) 인식 — 정규식은 build_issue_map.py parse_issue_md() 미러.
_ISSUE_SECTION_RE = re.compile(r"^#\s+(.+?)\s*$")
# Issue290: issue-map 이 관계도에서 통째로 빼는 섹션(build_issue_map.py `EXCLUDED_SECTIONS` 미러).
#   화이트리스트가 아닌 블랙리스트인 이유 — 완료 섹션명은 프로젝트마다 다를 수 있어
#   (ex: `🏁 완료-해결순`, issue-g.md 참고) 포함 섹션을 열거하면 그런 프로젝트에서 판정이 죽는다.
_ISSUE_EXCLUDED_SECTIONS = {"⏸️ 보류", "🚫 취소"}
# Issue361: 완료 섹션(build_issue_map.py `DONE_SECTIONS` 미러). 헤더 접미사 `✅` 만으로는
#   구식 이슈(접미사 없이 `✅ 완료` 섹션 소속만으로 완료 표시)를 놓친다 — 빌더 자신이
#   `section in DONE_SECTIONS or 헤더 끝 ✅` 로 판정하므로 여기도 두 신호를 함께 본다.
_ISSUE_DONE_SECTIONS = {"✅ 완료"}

# ── Issue363: 판정 소스를 **서빙될 맵 파일 자신**으로 둔다 ──────────────────────────
#   카드 🗺️ 는 "누르면 관계도가 보인다"는 약속이다. 그러니 판정이 답해야 할 질문은
#   *"지금 Issue.md 를 다시 빌드하면 그래프가 나오는가"* 가 아니라
#   *"지금 서빙될 파일 안에 그래프가 있는가"* 다. 후자를 보면 아이콘과 서빙 결과는
#   **정의상** 일치한다 — 두 축의 갱신 주기가 달라도 어긋날 수 없다.
#
#   ⚠️ 이 설계 이전 두 번의 시도가 모두 같은 이유로 실패했다:
#     * `Issue.md` 정규식 미러 — 빌더 규칙(`DEP_NULL_TOKENS`·`settled`·고립 노드)을
#       따라가지 못해 세 번 갈라졌다(Issue290 → Issue361 → Issue363).
#     * 빌더 in-process import — 미러는 없앴지만 판정축이 여전히 "재빌드하면 나올 결과"라
#       스냅샷과 어긋났다. prj1 실측에서 **실제 그래프(노드 6개)가 있는 맵의 아이콘이
#       사라지는** 회귀를 냈다. 축을 바꾼 것이지 없앤 것이 아니었다.
#
#   계약: 생성기 `build_issue_map.py` 는 그래프 유무와 무관하게 `ISSUE-MAP:GRAPH:START/END`
#   블록을 쓰고, 그 안에 그래프면 렌더된 `<svg>`, 아니면 "생략했습니다" 안내를 넣는다
#   (생성기 L760~778). 따라서 **블록 안의 `<svg` 유무**가 판정이다.
#   ⚠️ 생성기는 prj3(글로벌 SCAR) 자산이다 — 이 마커 규약을 바꾸려면 양쪽을 함께 고쳐야 한다.
_ISSUE_MAP_GRAPH_START = "ISSUE-MAP:GRAPH:START"
_ISSUE_MAP_GRAPH_END = "ISSUE-MAP:GRAPH:END"
_ISSUE_MAP_HEAD_BYTES = 262144   # 마커 블록은 문서 앞부분(실측 ~100행) — 전량 로드 회피


def _issue_map_has_graph(map_path: str) -> bool:
    """맵 파일이 실제 관계도를 담고 있는가 — `ISSUE-MAP:GRAPH` 블록 안의 `<svg` 유무.

    간선이 0 이면 생성기가 블록 안에 "생략했습니다" 안내만 넣으므로 열 가치가 없다
    (Issue284_1 의 원래 의도 — 아이콘은 "볼 것이 있을 때만"). 판정 대상이 서빙될
    파일 자신이라 아이콘과 서빙 결과가 어긋날 수 없다.

    마커가 없는 구버전 맵은 문서 전체의 `<svg` 로 폴백한다 — 마커 도입 전 산출물에서
    아이콘이 통째로 사라지지 않게 하기 위함이다. 읽기 실패는 False(아이콘 숨김).
    """
    try:
        with open(map_path, encoding="utf-8", errors="replace") as f:
            head = f.read(_ISSUE_MAP_HEAD_BYTES)
    except OSError:
        return False
    i = head.find(_ISSUE_MAP_GRAPH_START)
    if i < 0:
        return "<svg" in head
    j = head.find(_ISSUE_MAP_GRAPH_END, i)
    return "<svg" in (head[i:] if j < 0 else head[i:j])


def _issue_map_scan(cwd: str) -> tuple:
    """cwd 기준 (맵 절대경로|None, 맵이 그래프 보유, 맵 stale 여부) 반환. TTL 캐시."""
    if not cwd:
        return None, False, False
    now = time.time()
    with _issue_map_lock:
        hit = _issue_map_cache.get(cwd)
        if hit and hit[0] > now:
            return hit[1], hit[2], hit[3]
    found, has_graph, stale = None, False, False
    try:
        d = os.path.realpath(os.path.expanduser(cwd))
        home = os.path.realpath(os.path.expanduser("~"))
        for _ in range(_ISSUE_MAP_MAX_UP):
            issue_md = os.path.join(d, "Issue.md")
            if os.path.isfile(issue_md):
                cand = os.path.join(d, ISSUE_MAP_NAME)
                if os.path.isfile(cand):
                    found = cand
                    # Issue363: 판정 대상은 서빙될 파일 자신 — `Issue.md` 를 보지 않는다.
                    has_graph = _issue_map_has_graph(cand)
                    # Issue363(①): 맵은 생성 시점 스냅샷이라 `Issue.md` 가 더 새로우면
                    #   내용이 낡았다. 아이콘 노출 여부는 바꾸지 않고 흐림 표식으로만
                    #   고지한다 — 재생성은 `/fpm-issue-map` 수동.
                    try:
                        stale = os.path.getmtime(issue_md) > os.path.getmtime(cand)
                    except OSError:
                        stale = False
                break
            parent = os.path.dirname(d)
            # 루트·홈 도달 시 중단 ($HOME 자체가 nPTiR 루트인 prj0 은 위 분기에서 이미 처리)
            if parent == d or d == home:
                break
            d = parent
    except OSError:
        found, has_graph, stale = None, False, False
    with _issue_map_lock:
        _issue_map_cache[cwd] = (now + _ISSUE_MAP_TTL, found, has_graph, stale)
    return found, has_graph, stale


def _issue_map_path(cwd: str):
    """cwd 기준 이슈맵 문서 절대경로 반환. 없으면 None. (serve 용 — 그래프 유무 무관)"""
    return _issue_map_scan(cwd)[0]


def _issue_map_visible(cwd: str) -> bool:
    """카드에 🗺️ 를 렌더할지 여부 — 맵 파일 존재 **AND 그 파일이 그래프를 담고 있음**.

    판정 대상이 서빙될 파일 자신이라 아이콘과 서빙 결과는 정의상 일치한다(Issue363).
    serve(`/issue-map`)는 `_issue_map_path` 기준이라, 아이콘이 사라져도 기존 URL 은 살아있다.

    ⚠️ 남는 한계: 맵에 그래프가 없는데 `Issue.md` 에 새 depends 가 생긴 경우 아이콘은 뜨지
    않는다 — 지금 서빙할 것이 없으니 옳은 동작이나, 재생성하면 그래프가 생긴다는 사실은
    카드에 드러나지 않는다. 맵 자동 갱신은 별개 문제다(생성기가 prj3 소관)."""
    path, has_graph, _stale = _issue_map_scan(cwd)
    return bool(path) and has_graph


def _issue_map_exists(cwd: str) -> bool:
    """맵 **파일** 자체가 있는가 — 그래프 유무는 묻지 않는다 (Issue372).

    `_issue_map_visible` 과 갈라 두는 이유: 그래프가 비었다고 문서가 빈 것은 아니다.
    간선이 0 이어도 이슈 목록·완료 이력은 그대로 실려 있고 `/issue-map` 은 그것을
    정상 serve 한다(serve 판정은 `_issue_map_path` — 그래프를 보지 않는다).
    "열 가치가 있는가"(문서 존재)와 "관계도가 있는가"(그래프)는 다른 질문이며,
    소비처가 둘을 3단으로 표현할 수 있도록 신호를 분리한다."""
    return bool(_issue_map_scan(cwd)[0])


def _issue_map_stale(cwd: str) -> bool:
    """맵 파일이 `Issue.md` 보다 오래됐는지 (Issue363 ①). 아이콘 표식 전용 부속 신호로,
    아이콘 노출 여부 자체(`_issue_map_visible`)에는 영향을 주지 않는다 —
    '낡았다'와 '그릴 것이 없다'는 다른 사실이다."""
    path, _has_graph, stale = _issue_map_scan(cwd)
    return bool(path) and stale


# Issue316: 카드 배지 — "활성 세션 수" 대신 "미완료 이슈 수"를 보여준다(세션 수는 카드 바디의
#   live-list 에 이미 목록으로 표시되어 정보 손실 없음). Issue_map.htm 존재 여부와 무관하게
#   Issue.md 자체 경로가 필요하므로 `_issue_map_scan`(맵 파일 기준)과 별도 탐색을 둔다.
_ISSUE_OPEN_COUNT_TTL = 30.0     # _issue_map_cache 와 동일 TTL — /hub 폴링 5s 대비 stat 절감
_issue_open_count_cache: dict = {}  # cwd(str) -> (expire_ts, count)
_issue_open_count_lock = threading.Lock()
# 완료 판정은 `_ISSUE_DONE_SECTIONS`(위, `_ISSUE_EXCLUDED_SECTIONS` 옆) 를 공유한다 —
# 섹션 판정이 1차 신호, 헤더 접미사 `✅` 가 보강 신호. 구식 이슈(Issue230/232/236 등)는
# 접미사 없이 섹션 소속만으로 완료 표시되므로 두 신호가 모두 필요하다.
# ⚠️ Issue363 정정: 카드 **아이콘**은 이제 `Issue.md` 를 아예 보지 않고 맵 파일만 본다.
#   여기 **배지**(미완료 수)는 `Issue.md` 자체 순회다 — 축이 다르지만 묻는 질문도 다르다
#   ("볼 관계도가 있는가" vs "미완료가 몇 건인가"). 같은 값을 낼 이유가 없으므로 미러가 아니다.
#   (구 주석 "두 벌로 두지 않는다"(Issue361)는 depends 판정이 사라져 대상 자체가 없어졌다)


def _find_issue_md(cwd: str) -> str | None:
    """cwd 기준 상위로 최대 _ISSUE_MAP_MAX_UP 단계 거슬러 올라가며 Issue.md 경로를 찾는다.
    `_issue_map_scan` 과 동일한 탐색 규약이나, Issue_map.htm 존재 여부와 무관하게
    Issue.md 자체 경로를 반환한다."""
    if not cwd:
        return None
    try:
        d = os.path.realpath(os.path.expanduser(cwd))
        home = os.path.realpath(os.path.expanduser("~"))
        for _ in range(_ISSUE_MAP_MAX_UP):
            issue_md = os.path.join(d, "Issue.md")
            if os.path.isfile(issue_md):
                return issue_md
            parent = os.path.dirname(d)
            if parent == d or d == home:
                break
            d = parent
    except OSError:
        return None
    return None


def _count_open_issues(issue_md: str) -> int:
    """Issue.md 의 미완료 이슈 개수 — 완료(헤더 줄 끝 ✅)·⏸️ 보류·🚫 취소 섹션을 제외한
    이슈 헤더(`## Issue1:` / `### Issue1_2:`) 개수."""
    count = 0
    try:
        section_done = False
        excluded_section = False
        with open(issue_md, encoding="utf-8", errors="replace") as f:
            for line in f:
                m_sec = _ISSUE_SECTION_RE.match(line)
                if m_sec:
                    sec = m_sec.group(1)
                    section_done = sec in _ISSUE_DONE_SECTIONS
                    excluded_section = sec in _ISSUE_EXCLUDED_SECTIONS
                    continue
                if _ISSUE_HEADER_RE.match(line):
                    done = section_done or line.rstrip().endswith("✅")
                    if not done and not excluded_section:
                        count += 1
                    continue
    except OSError:
        return 0
    return count


def _issue_open_count(cwd: str) -> int:
    """cwd 기준 미완료 이슈 개수. Issue.md 없으면 0. TTL 캐시."""
    if not cwd:
        return 0
    now = time.time()
    with _issue_open_count_lock:
        hit = _issue_open_count_cache.get(cwd)
        if hit and hit[0] > now:
            return hit[1]
    issue_md = _find_issue_md(cwd)
    count = _count_open_issues(issue_md) if issue_md else 0
    with _issue_open_count_lock:
        _issue_open_count_cache[cwd] = (now + _ISSUE_OPEN_COUNT_TTL, count)
    return count


# Issue352: .hub-state 디렉토리 스캔 결과 단기 캐시. collect(5초 polling)가 프로젝트 수만큼
#   _htm_state() 를 호출하면 listdir 이 그 횟수만큼 반복된다 — 1회 스캔 결과를 공유한다.
#   판정 로직 자체는 _htm_state() 단일 지점 유지 (규칙5).
_HTM_STATE_TTL = 2.0
_htm_state_cache = (0.0, {})
_htm_state_cache_lock = threading.Lock()


def _htm_state_entries() -> dict:
    """{hash_prefix: content} — .hub-state 디렉토리 1회 스캔 결과 (TTL 2초)."""
    global _htm_state_cache
    now = time.time()
    with _htm_state_cache_lock:
        exp, data = _htm_state_cache
        if now < exp:
            return data
    state_dir = os.path.join(os.path.expanduser("~"), ".claude", ".hub-state")
    out = {}
    try:
        for fn in os.listdir(state_dir):
            try:
                with open(os.path.join(state_dir, fn), encoding="utf-8") as f:
                    out[fn.split("__", 1)[0]] = f.read().strip()
            except OSError:
                continue
    except (FileNotFoundError, OSError):
        pass
    with _htm_state_cache_lock:
        _htm_state_cache = (now + _HTM_STATE_TTL, out)
    return out


def _htm_state_cache_clear() -> None:
    """토글 직후 캐시 무효화 — 쓴 값을 같은 요청에서 바로 되읽어야 하므로 TTL 을 못 기다린다."""
    global _htm_state_cache
    with _htm_state_cache_lock:
        _htm_state_cache = (0.0, {})


def _htm_state(path: str) -> tuple:
    """프로젝트 경로의 htm 자동 모드 effective off 여부 + 사유 계산.
    htm-trigger.sh 판정 우선순위 복제: SYSTEM_OFF_FLAG > per-cwd STATE_FILE > 프로젝트 default(on).
    Project List 행은 모두 등록 프로젝트이므로 default 는 on. 반환: (off: bool, reason: str)."""
    home = os.path.expanduser("~")
    if os.path.exists(os.path.join(home, ".claude", ".hub-system-off")):
        return True, "시스템 OFF (..hub off)"
    abs_cwd = os.path.expanduser(path).rstrip("/")
    h = hashlib.md5(abs_cwd.encode("utf-8")).hexdigest()[:8]
    if _htm_state_entries().get(h) == "off":
        return True, "프로젝트 stop (..hub stop)"
    return False, ""


def _htm_label(path: str) -> str:
    """htm-trigger.sh 라벨 규칙 복제: 마지막 path segment. basename 이 '_'로 시작하면
    parent-base 결합 (ex: _public → fSnippet-_public). 비안전 문자 → '_', 최대 48자."""
    cwd = os.path.expanduser(path).rstrip("/")
    if not cwd:
        return "unknown"
    parts = cwd.split("/")
    base = parts[-1] if parts else "unknown"
    parent = parts[-2] if len(parts) >= 2 else ""
    label = f"{parent}-{base}" if base.startswith("_") and parent else base
    return re.sub(r"[^A-Za-z0-9._-]", "_", label)[:48] or "unknown"


def _htm_state_file(path: str) -> tuple:
    """(state_dir, state_file_path) 반환. 기존 라벨 파일이 있으면 그 경로, 없으면 신규 라벨 경로."""
    home = os.path.expanduser("~")
    state_dir = os.path.join(home, ".claude", ".hub-state")
    abs_cwd = os.path.expanduser(path).rstrip("/")
    h = hashlib.md5(abs_cwd.encode("utf-8")).hexdigest()[:8]
    try:
        for fn in os.listdir(state_dir):
            if fn == h or fn.startswith(h + "__"):
                return state_dir, os.path.join(state_dir, fn)
    except (FileNotFoundError, OSError):
        pass
    return state_dir, os.path.join(state_dir, f"{h}__{_htm_label(path)}")


# ── Issue420: aoa-mq 큐 수집 ──────────────────────────────────────────────
# 경로 knob 은 tick(mcp/aoa-mq/aoa-mq-tick.sh:33)과 **같은 것**을 쓴다. 하드코딩하면
#   prj5 레거시 큐(~/_git/___common/data/aoa/mq)를 보게 되어 화면과 실제가 갈린다.
MQ_DIR = os.environ.get("AOA_MQ_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude", "data", "aoa", "mq")
MQ_DONE_LIMIT = 40          # 종결분은 최근 N 건만 — 전량이면 화면이 과거로 덮인다

def _mq_read_dir(d, limit=None):
    """큐 디렉토리의 *.json 을 dict 목록으로. 깨진 파일은 건너뛰되 개수는 센다."""
    out, broken = [], 0
    try:
        names = sorted(os.listdir(d), reverse=True)
    except OSError:
        return out, broken
    for nm in names:
        if not nm.endswith(".json"):
            continue
        if limit is not None and len(out) >= limit:
            break
        try:
            with open(os.path.join(d, nm), encoding="utf-8") as fh:
                item = json.load(fh)
        except Exception:
            broken += 1
            continue
        if isinstance(item, dict):
            item.setdefault("id", nm[:-5])
            out.append(item)
    return out, broken

def _mq_collect():
    """미종결 + 최근 종결분. 수집 실패는 숨기지 않고 error 로 올린다(조용한 0 금지)."""
    q, qb = _mq_read_dir(os.path.join(MQ_DIR, "queue"))
    d, db = _mq_read_dir(os.path.join(MQ_DIR, "queue_done"), MQ_DONE_LIMIT)
    for it in q:
        it["_bucket"] = "queue"
    for it in d:
        it["_bucket"] = "done"
    err = None
    if not os.path.isdir(MQ_DIR):
        err = "큐 디렉토리 없음: %s (AOA_MQ_DIR 확인)" % MQ_DIR
    elif qb or db:
        err = "JSON 파싱 실패 %d건 (queue %d · done %d)" % (qb + db, qb, db)
    return {
        "ok": err is None, "error": err, "mq_dir": MQ_DIR,
        "items": q + d, "open_count": len(q), "done_count": len(d),
        "ts": int(time.time()),
    }


# Issue420: /mq 페이지 template. hub 와 같은 "서버 내장" 방식 — 별도 정적 파일을 두면
#   배포 경로가 하나 늘고 hub 셸의 CSS·다크모드와 갈린다.
_MQ_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>aoa-mq — 예약 큐 관리</title>
<style>
:root{--bg:#fff;--fg:#1a1a1a;--dim:#666;--line:#e3e3e3;--card:#fafafa;--accent:#3b6fd4}
@media(prefers-color-scheme:dark){:root{--bg:#1b1b1d;--fg:#e8e8e8;--dim:#9a9a9a;--line:#333;--card:#232326;--accent:#7aa2f7}}
*{box-sizing:border-box}
body{margin:0;padding:1rem 1.2rem;background:var(--bg);color:var(--fg);
 font:14px/1.55 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif}
h1{font-size:1.15rem;margin:0 0 .2rem}
.sub{color:var(--dim);font-size:.82rem;margin-bottom:.9rem}
.bar{display:flex;flex-wrap:wrap;gap:.45rem;align-items:center;margin-bottom:.8rem;
 padding:.6rem;background:var(--card);border:1px solid var(--line);border-radius:8px}
.bar input,.bar select{padding:.32rem .5rem;border:1px solid var(--line);border-radius:5px;
 background:var(--bg);color:var(--fg);font-size:.85rem}
.bar input[type=search]{min-width:210px;flex:1}
.chip{padding:.2rem .5rem;border-radius:99px;font-size:.74rem;border:1px solid var(--line);color:var(--dim)}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{padding:.5rem .55rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:.76rem;color:var(--dim);cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--accent)}
td.msg{max-width:min(46vw,640px)}
/* 처리 열은 창이 좁아도 화면 밖으로 밀리지 않게 붙여 둔다 — 밀리면 버튼을 아예 못 찾는다 */
th:last-child,td:last-child{position:sticky;right:0;background:var(--bg);white-space:nowrap;box-shadow:-6px 0 6px -6px rgba(0,0,0,.25)}
.id{font-family:ui-monospace,Menlo,monospace;font-size:.74rem;color:var(--dim);white-space:nowrap}
.st{padding:.12rem .42rem;border-radius:4px;font-size:.72rem;white-space:nowrap}
.st-due{background:#c0392b22;color:#c0392b}
.st-pending{background:#8e44ad22;color:#8e44ad}
.st-done_unacked{background:#27ae6022;color:#27ae60}
.st-done,.st-confirmed,.st-dismissed{background:#7f8c8d22;color:#7f8c8d}
.acts{display:flex;gap:.25rem;flex-wrap:wrap}
button.a.go{border-color:var(--accent);color:var(--accent);font-weight:600}
.st-in_progress{background:#e8912233;color:#b3701a}
button.a{padding:.22rem .45rem;font-size:.74rem;border:1px solid var(--line);border-radius:5px;
 background:var(--bg);color:var(--fg);cursor:pointer;white-space:nowrap}
button.a:hover{border-color:var(--accent);color:var(--accent)}
button.a[disabled]{opacity:.45;cursor:default}
.note{margin-top:.9rem;padding:.6rem .7rem;background:var(--card);border-left:3px solid var(--accent);
 border-radius:0 6px 6px 0;font-size:.8rem;color:var(--dim)}
.err{background:#c0392b18;border-left-color:#c0392b;color:#c0392b}
tr.acked{opacity:.5}
.cnt{color:var(--dim);font-size:.8rem;margin-left:auto}
</style></head><body>
<h1>📮 aoa-mq — 예약 큐</h1>
<div class="sub" id="sub">불러오는 중…</div>

<div class="bar">
  <input type="search" id="kw" placeholder="키워드 (본문·id·출처 전문 검색)">
  <select id="f-status"><option value="">상태 전체</option></select>
  <select id="f-type"><option value="">유형 전체</option></select>
  <select id="f-source"><option value="">출처 전체</option></select>
  <select id="f-bucket">
    <option value="queue">미종결만</option>
    <option value="">전체(종결 포함)</option>
    <option value="done">종결만</option>
  </select>
  <span class="cnt" id="cnt"></span>
</div>

<table><thead><tr>
  <th data-k="id">ID</th>
  <th data-k="status">상태</th>
  <th data-k="type">유형</th>
  <th data-k="due_ts">마감</th>
  <th data-k="ask_count">질의</th>
  <th data-k="source">출처</th>
  <th>내용</th>
  <th>처리</th>
</tr></thead><tbody id="rows"></tbody></table>

<div class="note" id="note">
  <b>진행</b>=지금 착수(in_progress) — <b>종결이 아니다.</b> 세션 넛지에 작업 지시로 올라가고 큐에 남는다 ·
  <b>완료</b>=다 했음(confirmed) · <b>확인</b>=완료 통지를 봤음(acked_done) · <b>연기</b>=마감만 미룸(큐 유지) ·
  <b>취소/버림</b>=하지 않음(dismissed). 진행 외에는 누르면 목록에서 빠진다.
</div>

<script>
let DATA=[], SORT={k:"due_ts",asc:true}, ACKED={};
const $=id=>document.getElementById(id);
const esc=t=>String(t==null?"":t).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

// 액션 → 사람이 읽는 이름. 버튼 라벨과 통지 문구를 한 곳에서 맞춘다.
const LBL={start:"진행",confirm:"완료",ack:"확인",snooze:"연기",dismiss:"취소",defer:"닫기"};
// hub 셸의 toast() 는 이 페이지에 없다(별도 문서) — 최소 구현을 둔다.
function toast(msg){
  let el=document.getElementById("toast");
  if(!el){ el=document.createElement("div"); el.id="toast";
    el.style.cssText="position:fixed;left:50%;bottom:1.5rem;transform:translateX(-50%);"+
      "background:#111;color:#fff;padding:.55rem 1rem;border-radius:6px;font-size:.9rem;"+
      "opacity:0;transition:opacity .2s;z-index:99";
    document.body.appendChild(el); }
  el.textContent=msg; el.style.opacity="1";
  clearTimeout(el._t); el._t=setTimeout(()=>{el.style.opacity="0";},2600);
}
async function load(){
  const r=await fetch("/mq-data",{cache:"no-store"});
  const d=await r.json();
  DATA=d.items||[];
  $("sub").textContent=`미종결 ${d.open_count} · 종결(최근) ${d.done_count} · ${d.mq_dir}`;
  if(!d.ok){ const n=$("note"); n.className="note err"; n.textContent="⚠️ "+(d.error||"수집 실패"); }
  fillOpts("f-status","status"); fillOpts("f-type","type"); fillOpts("f-source","source");
  render();
}
function fillOpts(el,key){
  const sel=$(el), cur=sel.value;
  const vals=[...new Set(DATA.map(x=>x[key]).filter(Boolean))].sort();
  sel.innerHTML=sel.options[0].outerHTML+vals.map(v=>`<option>${esc(v)}</option>`).join("");
  sel.value=cur;
}
function pass(x){
  const kw=$("kw").value.trim().toLowerCase();
  if(kw){ const hay=[x.id,x.message,x.source,x.status,x.type].join(" ").toLowerCase();
          if(!hay.includes(kw)) return false; }
  for(const [el,key] of [["f-status","status"],["f-type","type"],["f-source","source"]]){
    const v=$(el).value; if(v && x[key]!==v) return false;
  }
  const b=$("f-bucket").value; if(b && x._bucket!==b) return false;
  return true;
}
function render(){
  const rows=DATA.filter(pass).sort((a,b)=>{
    let A=a[SORT.k], B=b[SORT.k];
    if(SORT.k==="ask_count"){A=+A||0;B=+B||0;} else {A=String(A||"");B=String(B||"");}
    return (A<B?-1:A>B?1:0)*(SORT.asc?1:-1);
  });
  $("cnt").textContent=`${rows.length} / ${DATA.length} 건`;
  $("rows").innerHTML=rows.map(x=>{
    const done=x._bucket==="done", ak=ACKED[x.id];
    // Issue423: 상태에 따라 **의미 있는 액션만** 낸다.
    //   종전엔 4개를 늘 보여줬는데, confirm 과 ack 은 tick 계약상 둘 다 종결이라
    //   (confirmed / acked_done) 사용자에겐 같은 버튼이 둘로 보였다.
    //   · done_unacked = 봇이 끝냈다는 **통지** → 사람이 할 일은 "봤다" 뿐
    //   · due·pending  = 예약된 **작업**     → 했다·미룬다·버린다
    const st0=(x.status||"");
    // Issue424: 아직 **할 일**(scheduled 계열)과 이미 **끝난 통지**(done_unacked)는
    // 사람이 취할 행동이 다르다. 전자엔 "완료" 보다 "진행" 이 먼저 오고, 후자엔
    // "완료" 가 아니라 "확인" 이 맞다.
    const notice = st0==="done_unacked";
    const wip = st0==="in_progress";
    const acts=done?'<span class="chip">종결됨</span>':
      (ak?`<span class="chip">처리 중…</span>`:
      (notice
        ? `<div class="acts">
        <button class="a" onclick="act('${x.id}','ack',this)" title="완료 통지를 확인함 → acked_done">확인</button>
        <button class="a" onclick="act('${x.id}','dismiss',this)" title="통지를 버림 → dismissed">버림</button>
      </div>`
        : `<div class="acts">
        ${wip?'':`<button class="a go" onclick="act('${x.id}','start',this)" title="지금 착수 — 세션 넛지에 작업 지시로 올린다(종결 아님)">진행</button>`}
        <button class="a" onclick="act('${x.id}','confirm',this)" title="다 했음 → confirmed 로 종결">완료</button>
        <button class="a" onclick="act('${x.id}','snooze',this)" title="마감을 N일 뒤로 — 큐에 남는다">연기</button>
        <button class="a" onclick="act('${x.id}','dismiss',this)" title="하지 않기로 함 → dismissed">취소</button>
      </div>`));
    return `<tr class="${ak?'acked':''}">
      <td class="id">${esc(x.id)}</td>
      <td><span class="st st-${esc(x.status||'')}">${esc(x.status||'-')}</span></td>
      <td>${esc(x.type||'-')}</td>
      <td class="id">${esc((x.due_ts||'-').replace('T',' '))}</td>
      <td>${x.ask_count||0}</td>
      <td>${esc(x.source||'-')}</td>
      <td class="msg">${esc(x.message||'')}</td>
      <td>${acts}</td></tr>`;
  }).join("")||'<tr><td colspan="8" style="color:var(--dim);padding:1rem">조건에 맞는 항목이 없습니다.</td></tr>';
}
async function act(id,action,btn){
  let arg="";
  if(action==="snooze"){
    const d=prompt("며칠 연기할까요?","1"); if(!d) return; arg=":"+d;
  }
  if(action==="dismiss" && !confirm("취소(드롭)하면 큐에서 제거됩니다. 진행할까요?")) return;
  btn.closest(".acts").querySelectorAll("button").forEach(b=>b.disabled=true);
  const q="aoa-mq-ack:"+id+":"+action+arg;
  try{
    const r=await fetch("/mq-ack",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({question:q})});
    const j=await r.json();
    if(!j.ok) throw new Error(j.error||"실패");
    ACKED[id]=action; render();
    // 서버가 consume 까지 마쳤으면(consumed) 데이터를 다시 읽는다 — 종결된 항목은
    // 미종결 목록에서 **실제로 사라진다**. 종전엔 화면 문구만 바뀌어 "안 지워진다" 로 보였다.
    if(j.consumed){ delete ACKED[id]; await load(); toast(`${LBL[action]||action} — 처리됨`); }
    else { toast(`${LBL[action]||action} 접수 — 다음 tick(≤5분)이 반영`); }
  }catch(e){
    alert("접수 실패: "+e.message);
    btn.closest(".acts").querySelectorAll("button").forEach(b=>b.disabled=false);
  }
}
["kw","f-status","f-type","f-source","f-bucket"].forEach(i=>$(i).addEventListener("input",render));
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{
  const k=th.dataset.k; SORT.asc = SORT.k===k ? !SORT.asc : true; SORT.k=k; render();
});
load(); setInterval(load,60000);
</script></body></html>"""


def _projects_list_with_htm() -> list:
    """_load_projects_list() 결과에 htm off 상태 주입. htm 상태는 Projects.md mtime 과
    무관하게 변하므로 캐시 밖에서 매 요청 계산 (state 파일은 소수 → IO 경량).

    Issue368: Project List 의 `Map` 컬럼용으로 이슈맵 보유 여부도 함께 싣는다. 판정은
    카드 🗺️ 와 **같은 함수**(`_issue_map_visible`/`_issue_map_stale`)를 쓴다 — 두 화면이
    같은 프로젝트를 다르게 말하지 않게 하는 것이 목적이라, 여기서 따로 판정하지 않는다.
    스캔은 TTL 30s 캐시를 공유하고 팝업 열 때만 호출되므로 폴링 비용에 영향이 없다."""
    rows = _load_projects_list()
    out = []
    for r in rows:
        path = r.get("path", "")
        off, reason = _htm_state(path)
        out.append({
            **r,
            "htm_off": off,
            "htm_reason": reason,
            "issue_map": _issue_map_visible(path),
            # Issue372: 그래프 유무와 별개로 "맵 문서가 있는가" — 소비처(Projects_map 팝업)가
            #   ①없음 ②문서만 ③문서+그래프 3단으로 갈라 표현한다. 같은 TTL 캐시를 쓴다.
            "issue_map_file": _issue_map_exists(path),
            "issue_map_stale": _issue_map_stale(path),
        })
    return out


def _hub_off_stats() -> dict:
    """Issue352: hub OFF 배지용 집계 — 등록 프로젝트(Projects.md) 중 effective off 개수 +
    시스템 전역 OFF 여부. state 스캔은 _htm_state_entries() 캐시(TTL 2초)라 5초 polling 무해."""
    sys_off = os.path.exists(
        os.path.join(os.path.expanduser("~"), ".claude", ".hub-system-off"))
    rows = _projects_list_with_htm()
    return {
        "hub_system_off": sys_off,
        "hub_off_count": sum(1 for r in rows if r.get("htm_off")),
        "hub_off_total": len(rows),
    }


# ── 핀봇(fbot) 현황 — prj3#Issue438 ③ (hub 상시 표시) ────────────────────────
# 왜 hub 가 registry.db 를 직접 읽는가: 봇 상태의 SSOT 는 레지스트리 단일 레코드이고,
#   hub 렌더와 HR 게이트가 그 레코드를 **공용**한다(prj3 fbot-arch §F1 "판정 단일 지점").
#   중간 캐시·사영 파일을 새로 만들면 그 순간 판정이 둘로 갈라진다.
# 범용 배포: fbot 미설치 환경에서는 DB·아이콘이 통째로 없다 → 조용히 빈 결과(섹션 자체 미표시).
#   경로는 env 우선 + $HOME 상대. 개인 경로 하드코딩 금지(fbot-arch §범용 배포 요건).
# 기본값은 제품 중립 `~/.claude/data/aoa` (prj3#Issue450) — 위 주석의 "개인 경로 하드코딩
#   금지" 를 정작 이 줄이 어기고 있었다. 설치 환경은 AOA_MEMORY_DIR 로 실경로를 준다.
FBOT_AOA_DIR = os.environ.get("AOA_MEMORY_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude", "data", "aoa")
# icon 컬럼은 `data/fbot/icons/<id>.svg` 처럼 **fbot 루트 기준 상대경로**로 저장된다.
FBOT_ROOT = os.environ.get("FBOT_ROOT") or os.path.join(os.path.expanduser("~"), ".claude")
# 활성 = 퇴근(checkout) 이 아닌 모든 상태. 이슈 ③ 의 표시 조건 그대로.
FBOT_ACTIVE_STATES = ("checkin", "working", "waiting_input", "waiting_child")
# prj3 hooks/fbot-state.py STATE_LABEL 과 동일 매핑 (표기 SSOT 는 prj3, 여기는 표시용 사본).
FBOT_STATE_LABEL = {
    "checkin": "출근중", "working": "작업중", "waiting_input": "수신대기",
    "waiting_child": "완료대기", "checkout": "퇴근",
}
FBOT_STATE_EMOJI = {
    "checkin": "🟡", "working": "🟢", "waiting_input": "⏳",
    "waiting_child": "🔵", "checkout": "⬜",
}
_FBOT_ICON_MAX = 16 * 1024  # data URI 인라인 상한. 초과분은 아이콘 없이 색 dot 폴백.


def _fbot_icon_data_uri(icon_rel: str) -> str:
    """봇 아이콘 SVG 를 data URI 로 인라인. 실패는 전부 빈 문자열(색 dot 폴백).

    새 정적 라우트를 만들지 않는 이유 — 아이콘은 166~340B 라 payload 인라인이 더 싸고,
    파일 경로를 URL 로 노출하지 않아 경로 탈출 대응면이 아예 생기지 않는다.
    """
    if not icon_rel or not isinstance(icon_rel, str):
        return ""
    base = os.path.realpath(os.path.join(FBOT_ROOT, "data", "fbot", "icons"))
    path = os.path.realpath(os.path.join(FBOT_ROOT, icon_rel))
    # 경로 탈출 차단 — DB 값이 오염돼도 아이콘 디렉터리 밖은 읽지 않는다.
    if not (path == base or path.startswith(base + os.sep)):
        return ""
    try:
        if os.path.getsize(path) > _FBOT_ICON_MAX:
            return ""
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


def _fbot_today_counts(con) -> dict:
    """열려 있는 registry 커넥션으로 **오늘(로컬 자정 이후)** fbot job 원장을 집계 (Issue400).

    반환 {"dispatched": n, "done": m, "cancelled": k, "last_ts": epoch|None}.
    job 테이블 부재·읽기 실패는 빈 dict — 유휴 요약 줄에서 그 항목만 생략한다
    (여기서 예외를 올리면 봇 카드 전체가 날아가므로 fail-soft).

    ⚠️ 판정 두 가지가 실측으로 정해졌다:
      * `store` 로 거르지 않는다 — 원장의 store 가 `'fbot'` 과 `''` 로 갈려 있어
        `store='fbot'` 필터는 세션 완료분을 통째로 놓친다. `kind LIKE 'fbot_%'` 가 정답
      * `job` 에 완료 시각 컬럼이 없다 — 집계 기준은 **created_at** 이다. i18n 문구·
        툴팁이 "오늘 생성분" 임을 밝힌다. 추정치를 확정치로 보이게 하지 않는다
    """
    midnight = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
    try:
        row = con.execute(
            "SELECT"
            " SUM(kind='fbot_dispatch') AS dispatched,"
            " SUM(status='done' AND kind IN ('fbot_dispatch','fbot_session')) AS done,"
            " SUM(status='cancelled' AND kind='fbot_dispatch') AS cancelled"
            " FROM job WHERE kind LIKE 'fbot_%' AND created_at >= ?",
            (midnight,)).fetchone()
        last = con.execute(
            "SELECT MAX(created_at) FROM job WHERE kind LIKE 'fbot_%'").fetchone()
    except sqlite3.Error as e:
        log(f"_fbot_today_counts skipped: {e}", "WARNING")
        return {}
    return {
        "dispatched": int(row[0] or 0),
        "done": int(row[1] or 0),
        "cancelled": int(row[2] or 0),
        "last_ts": int(last[0]) if last and last[0] else None,
    }


def _fbot_root_map(parents: dict) -> dict:
    """Issue402: bot_id → 소속 **루트 봇** id. 조직도 그룹핑의 단일 판정원이다.

    루트 = 부모가 없거나, 부모가 레지스트리에 **없는** 봇. 끊긴 채용 사슬(부모가 해고·
    삭제된 경우)을 버리면 그 봇이 조직에서 통째로 사라지므로 자기 자신을 루트로 세운다.
    순환(데이터 오염)은 방문 집합으로 끊는다 — 여기서 무한 루프가 나면 hub 홈 payload
    수집 스레드가 통째로 멈춘다.
    """
    out = {}
    for bid in parents:
        seen = {bid}
        cur = bid
        while True:
            p = parents.get(cur)
            if not p or p not in parents:
                break
            if p in seen:
                # 순환(오염 데이터) — 이 사슬엔 진짜 루트가 없다. 자기 자신을 루트로
                #   세워 어느 그룹에도 못 들어가 사라지는 일을 막는다.
                cur = bid
                break
            seen.add(p)
            cur = p
        out[bid] = cur
    return out


def _fbot_session_counts(con) -> dict:
    """열린 registry 커넥션으로 봇별 `fbot_session` 건수 집계 → 노드 배지용.

    세션 원장은 **엣지가 아니다** — "그 봇이 몇 번 일했나" 라서 위임 관계로 그리면
    자기 자신을 가리키는 헛 화살표가 된다(Issue402 상세). 실패는 빈 dict (fail-soft).
    """
    try:
        rows = con.execute(
            "SELECT owner, COUNT(*) FROM job WHERE kind='fbot_session'"
            " AND owner IS NOT NULL AND owner<>'' GROUP BY owner").fetchall()
    except sqlite3.Error as e:
        log(f"_fbot_session_counts skipped: {e}", "WARNING")
        return {}
    return {r[0]: int(r[1]) for r in rows}


def _fbot_last_seen(con) -> dict:
    """열린 registry 커넥션으로 봇별 **마지막 job 시각**(epoch) 집계 (Issue405).

    퇴근 칩의 최신성 판정원이다. `_fbot_today_counts` 의 `last_ts` 는 조직 전체 1건이라
    "어느 봇이 방금까지 일했나" 에 답하지 못한다 — 5분 전 퇴근과 두 달 전 퇴근이 같은
    칩으로 그려지던 원인이 이 결손이었다.

    `kind LIKE 'fbot_%'` 인 이유는 `_fbot_today_counts` 와 같다 — 원장의 store 가
    `'fbot'` 과 `''` 로 갈려 있어 store 필터는 세션 완료분을 통째로 놓친다.
    실패는 빈 dict (fail-soft) — 여기서 예외를 올리면 봇 카드 전체가 날아간다.
    """
    try:
        rows = con.execute(
            "SELECT owner, MAX(created_at) FROM job WHERE kind LIKE 'fbot_%'"
            " AND owner IS NOT NULL AND owner<>'' GROUP BY owner").fetchall()
    except sqlite3.Error as e:
        log(f"_fbot_last_seen skipped: {e}", "WARNING")
        return {}
    return {r[0]: int(r[1]) for r in rows if r[1]}


def _fbot_dispatch_edges(con) -> list:
    """배분 원장(`job.kind='fbot_dispatch'`) → (owner, worker, issue, status, ts) 엣지.

    payload 는 JSON 문자열이고 `worker_bot_id` 가 대상이다. 파싱 실패·대상 부재 건은
    **엣지를 만들지 않는다** — 출발지만 있는 반쪽 화살표는 조직도에서 거짓말이 된다.
    """
    try:
        rows = con.execute(
            "SELECT owner, payload, status, created_at FROM job"
            " WHERE kind='fbot_dispatch' ORDER BY created_at").fetchall()
    except sqlite3.Error as e:
        log(f"_fbot_dispatch_edges skipped: {e}", "WARNING")
        return []
    out = []
    for owner, payload, status, ts in rows:
        if not owner:
            continue
        try:
            pl = json.loads(payload or "{}")
        except (ValueError, TypeError):
            continue
        worker = (pl or {}).get("worker_bot_id") or ""
        if not worker:
            continue
        out.append({"src": owner, "dst": worker,
                    "issue": (pl or {}).get("issue") or "",
                    "status": status or "", "ts": int(ts or 0)})
    return out


def _fbot_missing_db(db: str) -> dict:
    """레지스트리 파일이 없을 때의 분기 (Issue404 ⓒ).

    ⚠️ **"미설치" 와 "설치됐는데 못 찾는다" 는 화면에서 갈라져야 한다.** 전자는 섹션을
    조용히 감추는 것이 옳지만, 후자까지 같이 감추면 조용한 실패가 된다 — 실제로
    launchd 로 뜬 hub 가 `AOA_MEMORY_DIR` 없이 기본 경로를 보다가 핀봇 섹션을 통째로
    잃었고, `bots_error` 도 로그도 남지 않아 "봇이 한 명도 없다" 와 구분되지 않았다.
    Issue400 이 없애려던 상황을 환경 변수 하나가 되살린 셈이다.

    판정은 **설치 흔적**으로 한다 — `FBOT_ROOT/data/fbot/` 이 있으면 이 머신에 fbot 이
    깔려 있다는 뜻이고, 그런데 DB 가 없으면 경로를 잘못 보고 있는 것이다. 개인 경로
    폴백으로 "찾아주는" 짓은 하지 않는다(prj3#Issue450 이 없앤 것을 되살리게 된다) —
    여기서 하는 일은 **어긋났다는 사실을 드러내는 것**뿐이다.
    """
    empty = {"bots": [], "bots_active": 0, "bots_total": 0}
    if not os.path.isdir(os.path.join(FBOT_ROOT, "data", "fbot")):
        return empty          # 진짜 미설치 — 섹션 자체를 띄우지 않는다(범용 배포 요건)
    env_set = bool(os.environ.get("AOA_MEMORY_DIR"))
    hint = "" if env_set else " (AOA_MEMORY_DIR 미설정 — 이 프로세스는 기본 경로만 봅니다)"
    log(f"_collect_bots: fbot 설치 흔적은 있으나 registry.db 부재 — {db}"
        f" (AOA_MEMORY_DIR={'set' if env_set else 'unset'})", "WARNING")
    empty["bots_error"] = f"레지스트리를 찾지 못함: {db}{hint}"
    return empty


def _collect_bots() -> dict:
    """registry.db `bot` 테이블 → 홈 봇 카드 payload.

    반환: {"bots": [활성 봇 …], "bots_active": n, "bots_total": m, "bots_today": {…}}
    활성 0 이어도 bots 만 빈 리스트일 뿐 섹션은 남는다 — 클라이언트가 `bots_total`·
    `bots_today` 로 **유휴 요약 1줄**을 그린다(Issue400). 섹션을 통째로 숨기는 것은
    `bots_total == 0`(fbot 미설치) 한 경우뿐이다. "전원 퇴근" 을 감추면 기능 사망과
    봇 유휴가 화면상 구분되지 않아 사용자가 다시 세션에 되묻게 된다.
    """
    db = os.path.join(FBOT_AOA_DIR, "registry.db")
    if not os.path.exists(db):
        return _fbot_missing_db(db)
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        try:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT bot_id, title, role, state, career, icon, color, prj,"
                " current_task, parent_bot_id, lease_expires FROM bot").fetchall()
            # 같은 커넥션으로 원장까지 읽는다 — 봇 상태와 오늘 실적이 서로 다른 스냅샷을
            #   보면 "전원 퇴근인데 지금 작업중" 같은 자기모순 요약이 나온다 (Issue400)
            today = _fbot_today_counts(con)
            # Issue405: 봇 상태와 **같은 스냅샷**에서 읽는다 — 커넥션을 새로 열면
            #   "퇴근인데 마지막 실행이 미래" 같은 자기모순이 원리적으로 가능해진다.
            last_seen = _fbot_last_seen(con)
        finally:
            con.close()
    except sqlite3.Error as e:
        msg = str(e)
        if "no such table" in msg:
            # 스키마가 아직 없는 환경(마이그레이션 전)은 "봇이 없다" 와 같다 — 섹션 미표시.
            return {"bots": [], "bots_active": 0, "bots_total": 0}
        # 그 외(WAL -shm 생성 불가·락·손상)는 "봇 0" 과 구분되어야 한다. 조용한 0 은
        #   봇이 놀고 있는 것처럼 보여 이 섹션의 목적을 정면으로 배반한다.
        return {"bots": [], "bots_active": 0, "bots_total": 0, "bots_error": msg}
    now = int(time.time())
    out = []
    for r in rows:
        state = r["state"] or ""
        if state not in FBOT_ACTIVE_STATES:
            continue
        lease = r["lease_expires"]
        out.append({
            "bot_id": r["bot_id"],
            "title": r["title"] or r["bot_id"],
            "role": r["role"] or "",
            "state": state,
            "state_label": FBOT_STATE_LABEL.get(state, state),
            "state_emoji": FBOT_STATE_EMOJI.get(state, "⚪"),
            "career": r["career"] or "",
            "color": r["color"] or "",
            # 개체 아이콘이 없으면 **종류(role) 아이콘**으로 폴백한다. 계약의 기본 단위가
            #   "종류별 동형 도형" 이므로 개체 파일 부재가 무아이콘을 뜻하지는 않는다.
            "icon_uri": (_fbot_icon_data_uri(r["icon"] or "")
                         or _fbot_icon_data_uri(f"data/fbot/icons/{r['role']}.svg"
                                                if r["role"] else "")),
            "prj": r["prj"],
            "current_task": r["current_task"] or "",
            "parent_bot_id": r["parent_bot_id"] or "",
            # lease 만료분은 크래시 의심 — 강제 퇴근(reap) 전까지 카드에서 경고로 보인다.
            "lease_stale": bool(lease and now > int(lease)),
            # Issue401: 원본 epoch 도 함께 — 펼침 상세가 잔여/경과 분을 직접 계산한다.
            #   이미 조회한 값이라 쿼리 추가는 없다(그동안 lease_stale 계산에만 쓰고 버렸다).
            "lease_expires": int(lease) if lease else None,
        })
    # 활동 상태 우선(작업중 → 출근중 → 대기), 그 다음 호칭.
    order = {s: i for i, s in enumerate(("working", "checkin", "waiting_input", "waiting_child"))}
    out.sort(key=lambda b: (order.get(b["state"], 9), b["title"]))
    return {"bots": out, "bots_active": len(out), "bots_total": len(rows),
            "bots_today": today, "bots_roster": _fbot_roster(rows, last_seen),
            # prj3#Issue461 — 봇은 **머신에 귀속**된다(2026-08-29 사용자 판정: fg1·jm4 는
            #   다른 하드웨어고 일도 다르며 봇을 공유하지 않는다). 이 섹션이 보여주는 것은
            #   전조직이 아니라 **이 머신**뿐인데 화면에는 그 한정이 없어 전조직으로 읽혔다.
            #   원격 봇이 일하는 중에도 여기 0 이 뜨는 것은 버그가 아니라 범위다 — 그걸 적는다.
            "bots_scope": os.uname().nodename.split(".")[0]}


def _fbot_roster(rows, last_seen=None) -> list:
    """Issue402 ⓑ: 홈 섹션 그룹핑용 **전원 명부**(퇴근 포함).

    활성만 보내면 "어느 핀봇 밑에 누가 있나" 가 활성 봇만의 파편이 되어 조직이 안 보인다.
    Issue400 이 "전원 퇴근을 숨기지 않는다" 를 세운 것과 같은 이유를 그룹 단위로 승계한다.

    ⚠️ 아이콘은 **루트 봇만** 싣는다 — 소비처가 그룹 헤더 하나뿐이고, 활성 봇 카드는
    `bots` 가 이미 자기 아이콘을 들고 있다. 전원분 base64 를 매 폴링마다 실으면
    payload 만 몇 배가 되고 얻는 것이 없다.
    """
    root_of = _fbot_root_map({r["bot_id"]: (r["parent_bot_id"] or "") for r in rows})
    title_of = {r["bot_id"]: (r["title"] or r["bot_id"]) for r in rows}
    roster = []
    for r in rows:
        bid = r["bot_id"]
        st = r["state"] or ""
        is_root = root_of.get(bid) == bid
        roster.append({
            "bot_id": bid,
            "title": title_of[bid],
            "role": r["role"] or "",
            "state": st,
            "state_label": FBOT_STATE_LABEL.get(st, st),
            "state_emoji": FBOT_STATE_EMOJI.get(st, "⚪"),
            "color": r["color"] or "",
            "root": root_of.get(bid, bid),
            "is_root": is_root,
            "active": st in FBOT_ACTIVE_STATES,
            "icon_uri": ((_fbot_icon_data_uri(r["icon"] or "")
                          or _fbot_icon_data_uri(f"data/fbot/icons/{r['role']}.svg"
                                                 if r["role"] else ""))
                         if is_root else ""),
        })
    # Issue405: **퇴근 봇에만** 마지막 실행 시각을 싣는다. 활성 봇은 카드가 이미 상태와
    #   현재 작업을 들고 있어 소비처가 없고, 전원분을 매 폴링 실으면 payload 만 는다
    #   (아이콘을 루트 봇에만 싣는 것과 같은 판정).
    for m in roster:
        if not m["active"]:
            ts = (last_seen or {}).get(m["bot_id"])
            if ts:
                m["last_seen"] = int(ts)
    # 그룹 정렬 — 활성이 있는 조직이 위로, 그 다음 루트 호칭순. 그룹 안에서는 루트가
    #   먼저 오고(그룹 헤더가 쓴다) 나머지는 활동 상태 → 호칭순.
    active_by_root = {}
    for m in roster:
        active_by_root[m["root"]] = active_by_root.get(m["root"], 0) + (1 if m["active"] else 0)
    order = {s: i for i, s in enumerate(FBOT_ACTIVE_STATES)}
    roster.sort(key=lambda m: (-active_by_root.get(m["root"], 0),
                               title_of.get(m["root"], m["root"]),
                               not m["is_root"],
                               order.get(m["state"], 9), m["title"]))
    return roster


def _fbot_org_data(root_filter: str = "") -> dict:
    """Issue402 ⓐ: `registry.db` 를 `mode=ro` 직독해 조직도 데이터를 **매 요청 실시간**
    생성한다. `Issue_map.htm`·`Projects_map.htm` 처럼 중간 산출 파일을 만들지 않는다 —
    prj3#Issue438 ③ 계약 "중간 사영 파일 금지 · 판정 단일 지점" 과 정면 충돌하기 때문.

    🔴 **엣지는 2원천 합성이 필수**다. 배분 원장(`job.kind='fbot_dispatch'`)만으로 그리면
    조직이 가장 많이 쓰는 경로(`fpm-do` 직접 위임)가 원장을 거치지 않아(prj3#Issue438 ④)
    사용자가 가장 보고 싶어 하는 봇 밑이 **텅 빈다** — 실측(2026-08-27) 배분 엣지 9건이
    전부 작업핀봇 소유였고 중역핀봇의 배분 엣지는 0건이었다. 채용(`bot.parent_bot_id`)과
    반드시 합친다. 한쪽만 쓰는 구현은 계약 미달이다.

    고아 노드: 배분 원장에만 있고 `bot` 테이블에 없는 대상(`fbot-research-issue4363`).
    무시하면 엣지가 조용히 사라지고, 그냥 그리면 정보 없는 노드가 뜬다 → `orphan: True`
    로 **구분해 표기**한다.

    반환 `{"error": msg|"", "nodes": [...], "hires": [...], "dispatch": [...],
           "roots": [...], "root_filter": str, "unknown_root": bool}`.
    `error` 가 비지 않으면 나머지는 비어 있다 — 호출측이 **조용히 빈 맵을 그리지 말고**
    오류를 세워야 한다(Issue400 이 `bots_error` 를 분리한 것과 같은 이유).
    """
    db = os.path.join(FBOT_AOA_DIR, "registry.db")
    empty = {"error": "", "nodes": [], "hires": [], "dispatch": [], "roots": [],
             "root_filter": root_filter, "unknown_root": False}
    if not os.path.exists(db):
        # fbot 미설치 — 오류가 아니다. 호출측이 "설치되지 않았다" 로 안내한다.
        return empty
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        try:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT bot_id, title, role, state, career, icon, color, prj,"
                " current_task, parent_bot_id FROM bot").fetchall()
            # 같은 커넥션에서 원장까지 읽는다 — 봇 상태와 위임 이력이 서로 다른 스냅샷을
            #   보면 "없는 봇에게 방금 배분" 같은 자기모순 그림이 나온다(Issue400 동일 원칙).
            sessions = _fbot_session_counts(con)
            dispatch = _fbot_dispatch_edges(con)
        finally:
            con.close()
    except sqlite3.Error as e:
        msg = str(e)
        if "no such table" in msg:
            return empty            # 마이그레이션 전 = 봇 없음
        empty = dict(empty)
        empty["error"] = msg
        return empty

    parents = {r["bot_id"]: (r["parent_bot_id"] or "") for r in rows}
    root_of = _fbot_root_map(parents)
    nodes = {}
    for r in rows:
        bid = r["bot_id"]
        st = r["state"] or ""
        nodes[bid] = {
            "bot_id": bid,
            "title": r["title"] or bid,
            "role": r["role"] or "",
            "state": st,
            "state_label": FBOT_STATE_LABEL.get(st, st),
            "state_emoji": FBOT_STATE_EMOJI.get(st, "⚪"),
            "career": r["career"] or "",
            "color": r["color"] or "",
            "prj": r["prj"],
            "current_task": r["current_task"] or "",
            "parent": parents[bid] if parents[bid] in parents else "",
            "root": root_of.get(bid, bid),
            "sessions": int(sessions.get(bid, 0)),
            "orphan": False,
            # 개체 아이콘 → 없으면 종류(role) 아이콘 폴백. _collect_bots 와 같은 규칙 —
            #   같은 봇이 홈 카드와 조직도에서 다른 그림으로 보이면 안 된다.
            "icon_uri": (_fbot_icon_data_uri(r["icon"] or "")
                         or _fbot_icon_data_uri(f"data/fbot/icons/{r['role']}.svg"
                                                if r["role"] else "")),
        }
    # 채용 엣지 — 부모가 레지스트리에 실재할 때만. 끊긴 부모는 노드를 루트로 승격시킨
    #   _fbot_root_map 판정과 어긋나면 안 되므로 여기서도 같은 조건을 쓴다.
    hires = [{"src": parents[b], "dst": b} for b in parents
             if parents[b] and parents[b] in parents]

    # 고아 — 배분 대상인데 bot 테이블에 없다. 배분한 봇의 그룹에 얹어 엣지를 살린다.
    for e in dispatch:
        for side in ("src", "dst"):
            bid = e[side]
            if bid in nodes:
                continue
            owner_root = root_of.get(e["src"], e["src"])
            nodes[bid] = {
                "bot_id": bid, "title": bid, "role": "", "state": "", "state_label": "",
                "state_emoji": "❓", "career": "", "color": "", "prj": None,
                "current_task": "", "parent": "", "root": owner_root,
                "sessions": int(sessions.get(bid, 0)), "orphan": True,
                "icon_uri": "",
            }

    roots = []
    for bid, n in nodes.items():
        if n["root"] == bid and not n["orphan"]:
            roots.append(bid)
    roots.sort(key=lambda b: nodes[b]["title"])

    unknown_root = bool(root_filter) and root_filter not in roots
    if root_filter and not unknown_root:
        keep = {b for b, n in nodes.items() if n["root"] == root_filter}
        nodes = {b: n for b, n in nodes.items() if b in keep}
        hires = [e for e in hires if e["src"] in nodes and e["dst"] in nodes]
        dispatch = [e for e in dispatch if e["src"] in nodes and e["dst"] in nodes]
    else:
        dispatch = [e for e in dispatch if e["src"] in nodes and e["dst"] in nodes]

    order = {s: i for i, s in enumerate(FBOT_ACTIVE_STATES)}
    node_list = sorted(nodes.values(),
                       key=lambda n: (nodes_root_title(nodes, n), n["root"] != n["bot_id"],
                                      n["orphan"], order.get(n["state"], 9), n["title"]))
    return {"error": "", "nodes": node_list, "hires": hires, "dispatch": dispatch,
            "roots": roots, "root_filter": root_filter, "unknown_root": unknown_root}


def nodes_root_title(nodes, n) -> str:
    """정렬 키 보조 — 그룹(루트) 호칭. 루트가 필터로 잘려나갔으면 id 로 대신한다."""
    r = nodes.get(n["root"])
    return (r or {}).get("title", n["root"])


# ── Issue402: 핀봇 조직도 mermaid 렌더 ────────────────────────────────────
# mermaid 라벨 안전화 표는 projects-map 빌더(mmd_label)와 같은 어휘를 쓴다 — hub 안에서
#   같은 문법을 두 가지로 다루면 한쪽에서만 노드가 사라지는 종류의 버그가 난다.
_FBOT_MMD_UNSAFE = str.maketrans({'"': "'", "`": "'", "[": "(", "]": ")",
                                  "{": "(", "}": ")", "|": "/", "\n": " ",
                                  "<": "(", ">": ")"})


def _fbot_mmd_label(text: str) -> str:
    """mermaid 라벨 안전화. 백틱은 markdown-string 으로 오인되어 노드가 통째로 사라진다."""
    return str(text or "").translate(_FBOT_MMD_UNSAFE).strip()


def _fbot_mmd_id(prefix: str, key: str) -> str:
    """mermaid 노드 id — 영숫자·언더스코어만."""
    return prefix + re.sub(r"[^A-Za-z0-9_]", "_", str(key))


def _fbot_text_on(color: str) -> str:
    """배경색 위 글자색 — 개체색이 어두우면 흰 글자. 새 색 체계를 만들지 않고
    `bot.color`(prj3#Issue438 ③ 채용 시 생성분)를 그대로 쓰기 위한 대비 보정일 뿐이다."""
    c = (color or "").lstrip("#")
    if len(c) != 6:
        return "#111111"
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return "#111111"
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) >= 150 else "#ffffff"


def _fbot_map_mermaid(data: dict) -> str:
    """조직도 flowchart 소스. 루트별 subgraph + 채용 실선 + 배분 화살표(이슈·status 라벨).

    채용과 배분은 **선 모양으로 구분**한다(Issue402 ⓓ) — 둘을 같은 화살표로 그리면
    "누가 뽑았나" 와 "누가 시켰나" 가 한 그림에서 섞여 조직도의 의미가 사라진다.
    """
    nodes = {n["bot_id"]: n for n in data["nodes"]}
    if not nodes:
        return ""
    # 방향은 LR 이다 — 조직은 팬아웃이 넓다(실측: 작업핀봇 한 명 밑에 7봇). TD 로 그리면
    #   형제들이 가로로 늘어서 viewBox 가 3300px 을 넘고, mermaid 의 useMaxWidth 가 그것을
    #   컨테이너 폭으로 **축소**해 글자가 읽히지 않는다(실측 35% 축소). LR 은 형제를 세로로
    #   쌓아 세로로 길어지므로 폭 축소가 걸리지 않는다.
    lines = ["flowchart LR"]
    styles, link_kinds = [], []

    def nid(b):
        return _fbot_mmd_id("B_", b)

    # 그룹(subgraph) — 루트 봇 단위. 사용자 요구 "핀봇 단위" 가 이 단위다.
    groups = {}
    for n in data["nodes"]:
        groups.setdefault(n["root"], []).append(n)
    for root_id, members in groups.items():
        root = nodes.get(root_id)
        rtitle = _fbot_mmd_label((root or {}).get("title") or root_id)
        active = sum(1 for m in members if m["state"] in FBOT_ACTIVE_STATES)
        lines.append(f'  subgraph {_fbot_mmd_id("G_", root_id)}'
                     f'["{rtitle} · {len(members)}명(활성 {active})"]')
        lines.append("    direction TB")   # 그룹 안에서는 구성원을 세로로 쌓는다
        for m in members:
            parts = [_fbot_mmd_label(m["title"])]
            sub = " · ".join([x for x in (m["role"], m["state_label"]) if x])
            if m["orphan"]:
                # 정보 없는 노드를 그냥 그리면 "왜 여기 있나" 를 알 수 없다 —
                #   원장에만 있고 명부에 없다는 사실 자체를 라벨에 적는다.
                sub = "명부에 없음(배분 원장만)"
            if sub:
                parts.append(f"<small>{_fbot_mmd_label(sub)}</small>")
            if m["sessions"]:
                # 세션 원장은 엣지가 아니라 배지다 — "몇 번 일했나".
                parts.append(f"<small>⚙ 세션 {m['sessions']}</small>")
            lines.append(f'    {nid(m["bot_id"])}["' + "<br/>".join(parts) + '"]')
            if m["orphan"]:
                styles.append(f'  style {nid(m["bot_id"])} fill:#f5f5f5,color:#666,'
                              f'stroke:#c62828,stroke-width:1.5px,stroke-dasharray: 5 3')
            elif m["color"]:
                styles.append(f'  style {nid(m["bot_id"])} fill:{m["color"]},'
                              f'color:{_fbot_text_on(m["color"])},stroke:#33333340')
        lines.append("  end")

    # 채용 엣지 — 실선(화살표 없음). 조직의 뼈대다.
    for e in data["hires"]:
        lines.append(f'  {nid(e["src"])} --- {nid(e["dst"])}')
        link_kinds.append("hire")
    # 배분 엣지 — 화살표 + 이슈·status 라벨.
    for e in data["dispatch"]:
        lab = " · ".join([x for x in (e["issue"], e["status"]) if x]) or "배분"
        lines.append(f'  {nid(e["src"])} -->|"{_fbot_mmd_label(lab)}"| {nid(e["dst"])}')
        link_kinds.append("cancelled" if e["status"] == "cancelled" else "dispatch")

    lines.extend(styles)
    # linkStyle 은 선언 순서 전역 인덱스다 — 채용 → 배분 순으로 쌓은 위 순서에 맞춘다.
    for kind, css in (("hire", "stroke:#8a8a8a,stroke-width:1.6px"),
                      ("dispatch", "stroke:#2e7d32,stroke-width:2px"),
                      # 취소분은 흐리게 — 지운 것이 아니라 "있었으나 무산" 이므로 남긴다.
                      ("cancelled", "stroke:#bdbdbd,stroke-width:1.4px,"
                                    "stroke-dasharray: 4 3,opacity:0.45")):
        idx = [str(i) for i, k in enumerate(link_kinds) if k == kind]
        if idx:
            lines.append("  linkStyle " + ",".join(idx) + " " + css)
    return "\n".join(lines)


def _resolve_project_root(abs_cwd: str) -> dict:
    """Projects.md 등록 경로 중 abs_cwd 와 exact 또는 prefix(at-or-under) 매칭되는
    가장 긴 경로의 행을 반환 (없으면 빈 dict). 서브폴더 cwd(ex: videoStudio/_doc_base/contents)를
    등록된 부모 프로젝트(videoStudio)로 귀속시켜 fpm-hub-trigger.sh 의 prefix 매칭과 정합시킴."""
    best: dict = {}
    best_len = -1
    for row in _load_projects_list():
        path_cell = row.get("path", "")
        if not path_cell:
            continue
        ph = os.path.expanduser(path_cell).rstrip("/")
        if not ph:
            continue
        if (abs_cwd == ph or abs_cwd.startswith(ph + "/")) and len(ph) > best_len:
            best = row
            best_len = len(ph)
    return best


def _frontmost_app_window() -> tuple:
    """macOS 최전면 프로세스명 + 그 프로세스의 front window 제목 (Issue288).

    반환 ("Code", "Issue.md — ___pm") 형태. 실패(비-macOS·접근성 권한 부재·osascript
    오류·timeout)면 ("", "") — 호출자는 **fail-open**(기존 동작 유지) 할 것. 조용히
    기능을 무력화하지 않기 위해 실패는 WARNING 으로 남긴다."""
    script = ('tell application "System Events"\n'
              '  set pname to name of first process whose frontmost is true\n'
              '  try\n'
              '    set wname to name of front window of process pname\n'
              '  on error\n'
              '    set wname to ""\n'
              '  end try\n'
              '  return pname & tab & wname\n'
              'end tell')
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True,
                           text=True, timeout=3)
    except Exception as e:
        log(f"_frontmost_app_window failed: {e}", "WARNING")
        return ("", "")
    if r.returncode != 0:
        log(f"_frontmost_app_window osascript rc={r.returncode}: "
            f"{(r.stderr or '').strip()[:200]}", "WARNING")
        return ("", "")
    parts = (r.stdout or "").strip().split("\t", 1)
    return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else "")


def _simple_browser_focus_skip(mode: str, front_proc: str, front_win: str,
                               target_cwd: str) -> str:
    """Issue288 포커스 게이트 판정 (순수 함수 — 부수효과 없음, 단위검증용).

    반환: skip 사유 문자열, 빈 문자열이면 진행(=open 실행).
      - never       → 항상 skip
      - always/미지 → 항상 진행 (구 동작)
      - gate        → VSCode 가 전면이고 그 창이 owner 프로젝트가 아니면 skip.
                      VSCode 가 전면이 아니면(iTerm 등) 진행 — 그 세션과 상호작용
                      중일 가능성이 높다. 판정 실패(front_proc="")도 fail-open."""
    if mode == "never":
        return "focus-never"
    if mode != "gate":
        return ""
    # Issue327: Zed 가 전면이면 skip — Simple Browser 는 VSCode 전용 표면이라 여기서 열면
    #   Zed 에서 타이핑 중인 사용자의 포커스를 VSCode 가 빼앗는다(창 제목 일치 여부와 무관).
    if front_proc == "Zed":
        return "zed-frontmost"
    if front_proc not in ("Code", "Electron"):
        return ""
    owner_base = os.path.basename(target_cwd) if target_cwd else ""
    if owner_base and owner_base in front_win:
        return ""
    return "not-frontmost"


def project_meta(cwd: str) -> dict:
    h = cwd_hash(cwd)
    # Issue28: Projects.md peacock.color 우선, 없으면 hsl fallback
    abs_cwd = os.path.expanduser(cwd).rstrip("/")
    hsl_fallback = f"hsl({int(h[:4], 16) % 360}, 60%, 45%)"
    matched = _resolve_project_root(abs_cwd)
    if matched:
        name = matched.get("name") or os.path.basename(matched.get("path", "")) or abs_cwd
        color = matched.get("color") or hsl_fallback
        emoji = matched.get("emoji") or ""
    else:
        name = os.path.basename(abs_cwd) or cwd
        color = hsl_fallback
        emoji = ""
    name = (name or cwd).replace(" ", "_")
    return {"cwd_hash": h, "name": name, "color": color, "emoji": emoji}


# Issue42: hub 활동 피드 — hub_setting.yml 설정 + hook 이벤트 버퍼.
# data/hub_setting.yml 은 사용자 설정(git 추적), data/hub/hook-feed.json 은 런타임 상태(gitignore).
HUB_SETTING_FILE = os.path.join(REPO_ROOT, "data", "hub_setting.yml")
# 설정 기본값 SSOT 템플릿 — 설정창 연필(✏️ 기본값 대비 변경) 판정의 1차 기준.
# hub_setting.yml 에서 키가 지워졌을 때의 복원 참조본이기도 함.
HUB_SETTING_ORG_FILE = os.path.join(REPO_ROOT, "data", "hub_setting_org.yml")
HUB_SETTING_DEFAULTS = {"feed_limit": 100, "feed_default_visible": True, "feed_poll_interval": 5,
                        "feed_show_project_emoji": True, "feed_show_project_name": True,
                        "card_limit": 40, "search_limit": 200, "live_session_limit": 6,
                        # Issue141: bind 주소 (문자열). env HTM_SERVER_HOST 미설정 시 사용.
                        "bind_host": "127.0.0.1",
                        # Issue267: 외부 통지 URL host (QR·hook 렌더). 빈 문자열=미설정(소비처 fallback).
                        #   과거 DEFAULTS 누락으로 _load_hub_setting 가 스킵 → _handle_qr 이 advertise_host 를
                        #   못 읽고 LAN IP 로 폴백하던 잠복 버그. 등재하여 정상 파싱. 권장값=MagicDNS hostname.
                        "advertise_host": "",
                        # allow_server_list: source-IP allowlist 게이트 토글 (bind_host 와 분리).
                        #   true(기본)=비루프백 bind 시 Servers.md(check=O)+self allowlist 적재.
                        #   false=bind_host(self)만 허용 → 외부 source IP 전부 차단. 변경 시 restart.
                        "allow_server_list": True,
                        # allow_list: hub_setting.yml inline source-IP allowlist (IP/CIDR 리스트).
                        #   Servers.md 와 additive(병합) — 추가 grant. 호스트명 미지원(IP/CIDR 만, DNS 비의존).
                        #   yml 표기: allow_list: [192.168.0.5, 192.168.0.0/24]. yml 전용(UI 미편집). 변경 시 restart.
                        "allow_list": [],
                        # Issue379: 수신 이름(Host 헤더) 게이트. true(기본)=known 집합 밖 이름은 421.
                        #   known = bind_host + advertise_host + localhost + hostname(+.local) + extra_hosts.
                        #   IP 리터럴 Host 는 항상 통과(잠김 방지). 변경 시 restart.
                        "host_gate": True,
                        # Issue379: 수신 허용 이름 추가분(리버스 프록시 도메인 등). yml 전용. 변경 시 restart.
                        "extra_hosts": [],
                        # Issue159: 활성세션 정렬 — updated(최근갱신순) / created(세션 시작순 고정)
                        #   / project(Projects.md 번호순, 미등록 cwd 는 끝)
                        "live_session_order": "updated",
                        # Issue166: 명령(프롬프트) 전 빈 live 세션 표시 여부.
                        #   false(기본)=전체 숨김 / true=프로젝트당 최신 1개 표시(Issue136 dedup)
                        "live_session_show_empty": False,
                        # Issue277: 활성세션 행 세션 ID 복사 버튼(📋) 표시 여부. true(기본)=표시.
                        "live_session_copy_button": True,
                        # Issue279: 새 피드 도착 시 헤더 토글 아이콘 깜빡임(🙉↔🙈). true(기본)=on.
                        "feed_blink_on_new": True,
                        # Issue169: hub UI 언어 — en(영어, 기본) / ko(한국어). 설계: _doc_arch/localization.md
                        "language": "en",
                        # Issue194: hub 내부 탭 렌더 모드. 설계: _doc_arch/hub_internal_tabs.md
                        #   render_tab_mode: browser-tab(OS 탭) / hub-internal(기본·/hub-shell iframe 탭, Issue201)
                        "render_tab_mode": "hub-internal",
                        "tab_close_shortcut": "alt+w",
                        "hub_single_window": True,
                        "hub_lease_ttl": 30,
                        # Issue237: 원격 브라우저 → Remote-SSH 연결 VSCode 에디터 열기.
                        #   비루프백 source IP 의 open-project/open-session 요청에 한해 서버 `open` 대신
                        #   vscode-remote://ssh-remote+<alias><path> URI 를 반환 → 브라우저가
                        #   window.location 으로 발사, 클라이언트측(브라우저 머신) VSCode 가 이미 연결된
                        #   Remote-SSH 창을 재사용해 연다. 빈 문자열(기본)=원격 분기 비활성(host-local open 폴백).
                        #   값=클라이언트 ~/.ssh/config 의 이 서버 Host alias (예: gl).
                        "ssh_remote_alias": "",
                        # Issue288: 자동 렌더(hook 경로)의 Simple Browser 전면화 가드.
                        #   gate(기본)=다른 프로젝트 VSCode 창이 전면이면 open skip(포커스 탈취 방지)
                        #   / always=구 동작(항상 전면화) / never=자동 오픈 안 함(등록·채팅 URL 만).
                        #   hub 페이지 클릭 경로(/open-project·/open-session)는 이 설정과 무관.
                        "simple_browser_focus": "gate",
                        # Issue258: 서버 로그 상세도 — VERBOSE/DEBUG/INFO(기본)/WARNING/ERROR/CRITICAL.
                        #   값 미만 레벨 로그 억제. Chrome AX 크래시 직전 이벤트 타임라인 수집 시 VERBOSE 로 상향.
                        "log_level": "INFO",
                        # Issue353_2 M2-e: 라이브 표시 모드 — auto(기본)/live-tab/browser-tab.
                        #   live-tab   = 세션당 라이브 뷰 1탭에 계속 append (기본 UX)
                        #   browser-tab= 턴마다 아카이브 md 문서를 새 탭으로 (구 동작)
                        #   auto       = live-tab 로 시작하되 브라우저가 열화(메모리·DOM 노드·
                        #                렌더 시간)를 보고하면 그 탭을 browser-tab 으로 강등
                        "render_display": "auto",
                        # 강등 임계 — DOM 노드 수 / 렌더 1회 소요(ms) / JS 힙 사용률(%)
                        "live_degrade_nodes": 12000,
                        "live_degrade_render_ms": 400,
                        "live_degrade_heap_pct": 85,
                        # Issue353_3 M3: 적응형 렌더 게이트 — always/short/page(기본)/doc.
                        #   판정 주체는 **서버 규칙 엔진**(메일박스 실측)이다. LLM 자율 판정을
                        #   쓰지 않으므로 지시문 드리프트가 없다. 상세: services/hub/render_gate.py
                        "auto_render": "page"}
_hub_setting_cache: dict = {}
_hub_setting_cache_mtime: float = 0.0


def _parse_yml_list(val: str) -> list:
    """경량 인라인 리스트 파서 — `[a, b, c]` 또는 `a, b, c` → ['a','b','c'].
    각 항목 따옴표·공백 제거, 빈 항목 drop. stdlib-only(외부 yaml 비의존)."""
    s = val.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [x.strip().strip('"').strip("'") for x in s.split(",") if x.strip()]


def _load_hub_setting() -> dict:
    """data/hub_setting.yml 의 flat key:value 설정 로드 (mtime 캐시, _load_projects_colors 패턴).
    `#` 주석·빈 줄 무시. true/false·정수 캐스팅. 파일 부재·파싱 실패 시 코드 내장 기본값 사용 —
    외부 yaml 의존 없는 stdlib-only 경량 파서."""
    global _hub_setting_cache, _hub_setting_cache_mtime
    try:
        st = os.stat(HUB_SETTING_FILE)
    except FileNotFoundError:
        return dict(HUB_SETTING_DEFAULTS)
    if st.st_mtime == _hub_setting_cache_mtime and _hub_setting_cache:
        return _hub_setting_cache
    setting = dict(HUB_SETTING_DEFAULTS)
    try:
        with open(HUB_SETTING_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                key, _, val = line.partition(":")
                key, val = key.strip(), val.strip()
                if key not in HUB_SETTING_DEFAULTS:
                    continue
                if isinstance(HUB_SETTING_DEFAULTS[key], bool):
                    setting[key] = (val.lower() == "true")
                elif isinstance(HUB_SETTING_DEFAULTS[key], list):
                    setting[key] = _parse_yml_list(val)  # allow_list 등 리스트 키
                elif isinstance(HUB_SETTING_DEFAULTS[key], str):
                    # bind_host 는 스칼라 또는 `[a, b]` 리스트 허용(멀티 bind).
                    if key == "bind_host" and val.strip().startswith("["):
                        setting[key] = _parse_yml_list(val)
                    else:
                        setting[key] = val  # Issue141: 문자열 키(bind_host 등) 그대로
                else:
                    try:
                        setting[key] = int(val)
                    except ValueError:
                        pass
    except Exception as e:
        log(f"_load_hub_setting failed: {e}")
        return _hub_setting_cache or dict(HUB_SETTING_DEFAULTS)
    _hub_setting_cache = setting
    _hub_setting_cache_mtime = st.st_mtime
    _apply_log_level(setting)  # Issue258: log_level → _LOG_THRESHOLD 갱신
    return setting


def _apply_log_level(setting: dict) -> None:
    """Issue258: hub_setting.yml log_level → 모듈 전역 _LOG_THRESHOLD 반영.
    log() 가 _load_hub_setting() 을 직접 호출하면 재귀(로더 실패 시 log() 호출)라
    로더가 임계값을 전역에 push 하는 단방향 구조."""
    global _LOG_THRESHOLD
    _LOG_THRESHOLD = LOG_LEVELS.get(str(setting.get("log_level", "INFO")).upper(), 2)


# ── 에디터 어댑터 (Issue327) ────────────────────────────────────────────────
# data/editor.yml(flat key:value) 를 읽어 앱 이름·기본 에디터를 결정한다.
# 하드코딩 `open -a "Visual Studio Code"` 를 대체 — Zed 사용자가 hub 에서 무엇을 눌러도
# VSCode 가 뜨던 결함(설계 인벤토리 #13)의 수정.
EDITOR_SETTING_FILE = os.path.join(REPO_ROOT, "data", "editor.yml")
_EDITOR_APP_DEFAULT = {"vscode": "Visual Studio Code", "zed": "Zed"}
# 아이콘 캐시 — 앱 번들 .icns 에서 첫 요청 시 생성(타사 로고를 repo 에 커밋하지 않기 위함)
EDITOR_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "editor")
_EDITOR_APP_CANDIDATES = {
    "vscode": ["/Applications/Visual Studio Code.app",
               "/Applications/_editor/Visual Studio Code.app",
               os.path.expanduser("~/Applications/Visual Studio Code.app")],
    "zed": ["/Applications/Zed.app",
            "/Applications/_editor/Zed.app",
            os.path.expanduser("~/Applications/Zed.app")],
}


def _editor_cfg(key: str, default: str = "") -> str:
    """data/editor.yml flat key:value 조회. 파일·키 부재 시 default."""
    try:
        with open(EDITOR_SETTING_FILE, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*" + re.escape(key) + r"\s*:\s*(.*)$", line)
                if m:
                    v = re.sub(r"\s*#.*$", "", m.group(1)).strip()
                    return v or default
    except OSError:
        pass
    return default


def _default_editor() -> str:
    ed = _editor_cfg("default_editor", "vscode").lower()
    return ed if ed in _EDITOR_APP_DEFAULT else "vscode"


def _editor_app_name(editor: str = "") -> str:
    """macOS `open -a` 대상 앱 이름. editor.yml 의 app_<editor> 로 override 가능."""
    ed = (editor or _default_editor()).lower()
    if ed not in _EDITOR_APP_DEFAULT:
        ed = "vscode"
    return _editor_cfg(f"app_{ed}", "") or _EDITOR_APP_DEFAULT[ed]


def _session_editor(sid: str) -> str:
    """세션 sid 의 출처 에디터(vscode|zed). 미상이면 default_editor.

    origin=terminal 세션도 "어느 앱으로 폴더를 열까"는 정해야 하므로 default 로 떨어진다.
    """
    try:
        with sessions_lock:
            for (_h, _sid), entry in sessions.items():
                if _sid != sid:
                    continue
                caps = entry.get("capabilities") or {}
                return _origin_from_caps(caps) if _origin_from_caps(caps) in _EDITOR_APP_DEFAULT \
                    else _default_editor()
    except Exception:
        pass
    return _default_editor()


def _origin_from_caps(caps: dict) -> str:
    """세션 capabilities → origin (vscode|zed|terminal). Issue327 로 3값화.

    - VSCode 확장: CLAUDE_CODE_ENTRYPOINT=claude-vscode
    - Zed: ACP 브리지라 entrypoint 가 sdk-ts 로만 보인다 → 판정 hook(prj3)이 caps.editor="zed"
      를 실어 보내야 구분 가능. 서버는 그 신호를 신뢰하고, 없으면 terminal 로 둔다.
    """
    ep = str(caps.get("entrypoint", "")).strip()
    if ep == "claude-vscode":
        return "vscode"
    ed = str(caps.get("editor", "")).strip().lower()
    if ed in _EDITOR_APP_DEFAULT:
        return ed
    return "terminal"


_CANONICAL_LAUNCHERS = ("pm-do", "board", "manual", "ide")


def _launched_by_from_caps(caps: dict) -> str:
    """세션 capabilities → 기동자(launcher). Issue342 S3.

    ⚠️ `origin` 과 혼동 금지 — `origin`(_origin_from_caps)은 **어느 에디터에서 떴나**
    (vscode|zed|terminal)이고 카드 클릭 동작을 좌우한다. 여기서 판정하는 것은
    **누가 띄웠나**(pm-do 위임인가·board runner 인가·사람이 직접인가)로 축이 다르다.
    Issue342 원문은 이 필드도 `origin` 으로 부르나, 그 이름은 Issue177 이 선점했고
    load-bearing 이라 재사용하면 에디터 판정이 깨진다. 그래서 `launched_by` 로 뗀다.

    값의 출처는 기동자가 심는 env `FPM_SESSION_ORIGIN` 이며 SessionStart 훅(prj3)이
    capabilities 에 실어 보낸다. 미상은 빈 문자열 — **추측하지 않는다**(env 가 없다는
    사실 자체가 정보다. manual 로 단정하면 배선 누락과 수동 기동이 구분되지 않는다).
    """
    v = str(caps.get("launched_by", "")).strip().lower()
    return v if v in _CANONICAL_LAUNCHERS else ""


def _editor_icon_file(editor: str) -> str:
    """에디터 아이콘 PNG 경로. 없으면 앱 번들 .icns 에서 1회 생성(실패 시 빈 문자열).

    타사 상표 이미지를 repo 에 커밋하지 않기 위해 런타임 생성·캐시한다.
    """
    ed = (editor or "").lower()
    if ed not in _EDITOR_APP_CANDIDATES:
        return ""
    out = os.path.join(EDITOR_ICON_DIR, f"{ed}.png")
    if os.path.isfile(out):
        return out
    app = next((a for a in _EDITOR_APP_CANDIDATES[ed] if os.path.isdir(a)), "")
    if not app:
        return ""
    res = os.path.join(app, "Contents", "Resources")
    icns = ""
    try:
        for fn in sorted(os.listdir(res)):
            if fn.endswith(".icns") and "document" not in fn.lower():
                icns = os.path.join(res, fn)
                break
    except OSError:
        return ""
    if not icns:
        return ""
    try:
        os.makedirs(EDITOR_ICON_DIR, exist_ok=True)
        subprocess.run(["sips", "-s", "format", "png", icns, "--out", out,
                        "--resampleWidth", "64"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        return ""
    return out if os.path.isfile(out) else ""


def _ssh_remote_uri(cwd: str, alias: str) -> str:
    """Issue237: Remote-SSH 워크스페이스 열기 URI.
    클라이언트(브라우저) OS 의 vscode-remote:// 핸들러가 alias 로 이미 연결된
    창을 재사용해 cwd 를 연다. alias 는 클라이언트 ~/.ssh/config 기준 Host 이름이며
    절대경로 cwd 를 변환 없이 그대로 사용(Remote-SSH 는 서버 파일시스템 경로 그대로)."""
    return f"vscode-remote://ssh-remote+{alias}{cwd}"


# Issue168: 설정 모달 UI 스키마 — ⚙️ 버튼이 여는 인앱 3탭 설정창의 분류·위젯·유효값·적용방식.
#   탭(tab): basic(기본)/session(세션관리)/advanced(고급)
#   위젯(widget): toggle(bool)/select/number/text
#   적용(apply): auto(server.py mtime 재로드) / hook(글로벌 hook grep, 다음 렌더 turn) / restart(서버 재시작 필요)
#   분류 SSOT: _doc_arch/hub_settings_ui.md (본 상수는 그 미러)
HUB_SETTING_SCHEMA = [
    # 탭 1: 기본 — 브라우저·언어 + 탭 동작 (Issue197: render·tab 키 advanced 이동 → Issue268:
    #   browser_tab_reuse 와의 혼동 해소를 위해 render_tab_mode 만 basic 복귀)
    {"key": "default_browser", "tab": "basic", "widget": "select",
     "options": ["firefox", "chrome", "edge", "safari"], "allow_custom": True,
     "apply": "hook", "comment": "Claude Code(렌더 hook)가 렌더 결과·hub 페이지를 열 때 사용할 브라우저 — firefox/chrome/edge/safari 또는 .app 절대경로"},
    # Issue170: 3-way 브라우저 자동 open 동작 (구 browser_focus 대체, off/background/foreground).
    {"key": "browser_open", "tab": "basic", "widget": "select",
     "options": ["off", "background", "foreground"],
     "apply": "hook", "comment": "Claude Code(렌더 hook)가 렌더 후 브라우저를 자동으로 열지 — off=열지 않고 채팅에 URL만 표시 / background=열되 포커스 미탈취(open -g) / foreground=열고 포커스 이동"},
    {"key": "browser_tab_reuse", "tab": "basic", "widget": "toggle",
     "apply": "hook", "comment": "Claude Code(렌더 hook)가 /hub 페이지를 열 때 OS 브라우저의 기존 fpm-hub 명명 탭을 재사용할지 — on=기존 탭 재사용 / off=매번 새 탭. ⚠️ Chrome/Edge/Safari 전용(AppleScript 탭 제어) — Firefox·커스텀 앱은 탭 제어 미지원이라 비활성 (Issue272). OS 브라우저 탭 전용 — hub 내부 탭바('렌더 표시 방식')와 무관. 렌더(..show/..ask) 결과는 값과 무관하게 항상 새 탭"},
    # Issue194: 렌더 표시 방식 — OS 브라우저 탭 vs hub 쉘 내부 iframe 탭 (Issue268: advanced→basic 복귀)
    {"key": "render_tab_mode", "tab": "basic", "widget": "select",
     "options": ["browser-tab", "hub-internal"],
     "apply": "hook", "comment": "Claude Code 렌더 결과를 여는 위치 — browser-tab=OS 브라우저 새 탭/창(기본) / hub-internal=hub 화면(/hub-shell) 상단 내부 탭바에 iframe 으로 열림(OS 새 탭 미생성). 내부 탭을 쓰려면 hub-internal 선택. 세부 옵션(탭 닫기 단축키·단일 창 강제·리스 TTL)은 고급 탭"},
    # Issue169: hub UI 언어 (en/ko). 저장 후 hub 페이지 reload 시 반영. 설계: _doc_arch/localization.md
    {"key": "language", "tab": "basic", "widget": "select",
     "options": ["en", "ko"],
     "apply": "auto", "comment": "hub 서버가 hub UI 를 그릴 때 쓰는 언어 — en(영어, 기본)/ko(한국어). 저장 후 페이지 reload 시 반영"},
    # 탭 2: 세션관리(표시) — 세션·피드·카드 표시 (전부 server.py 소비 → auto). Issue197: 피드 키 일원화
    {"key": "live_session_limit", "tab": "session", "widget": "number", "min": 0,
     "apply": "auto", "comment": "hub 화면 활성 세션 카드 1장에 표시할 최대 행 수 (0=무제한)"},
    {"key": "live_session_order", "tab": "session", "widget": "select",
     "options": ["updated", "created", "project"],
     "apply": "auto", "comment": "hub 화면 활성 세션 카드 정렬 기준 — updated(최근 갱신순)/created(생성순)/project(프로젝트순)"},
    {"key": "live_session_show_empty", "tab": "session", "widget": "toggle",
     "apply": "auto", "comment": "hub 화면에 아직 명령이 없는 빈 live 세션도 표시할지 (false=숨김)"},
    {"key": "card_limit", "tab": "session", "widget": "number", "min": 0,
     "apply": "auto", "comment": "hub 화면에 표시할 htm 렌더 카드 최대 수 (0=무제한)"},
    {"key": "search_limit", "tab": "session", "widget": "number", "min": 0,
     "apply": "auto", "comment": "hub 서버가 디스크 재스캔 시 디렉토리당 읽는 파일 상한 (0=무제한)"},
    # Issue352: htm registry 자동 만료 — 목록 무한 누적 차단 (정책 SSOT htm-lifecycle-design.md)
    {"key": "htm_registry_keep", "tab": "session", "widget": "number", "min": 0,
     "apply": "auto", "comment": "hub 문서 목록에 무조건 남길 최신 문서 수 (mtime 최신순). 이 개수를 넘는 오래된 문서는 '보존 기간'을 지나면 목록에서 자동으로 빠진다 — 파일은 지우지 않으므로 '디스크 재스캔'으로 되살릴 수 있다"},
    {"key": "htm_registry_age_days", "tab": "session", "widget": "number", "min": 0,
     "apply": "auto", "comment": "hub 문서 보존 기간(일). '무조건 남길 수'를 넘는 문서 중 이 기간 안에 만들어진 것만 목록에 남는다. 두 값이 모두 0이면 자동 정리를 하지 않는다(무한 누적)"},
    # 피드 키 묶음 (Issue197: feed_default_visible basic→session, feed_poll_interval advanced→session)
    {"key": "feed_default_visible", "tab": "session", "widget": "toggle",
     "apply": "auto", "comment": "hub 화면 첫 접속 시 피드 사이드바를 펼쳐 보일지"},
    {"key": "feed_limit", "tab": "session", "widget": "number", "min": 1,
     "apply": "auto", "comment": "hub 서버가 피드에 보관·표시하는 최대 항목 수"},
    {"key": "feed_poll_interval", "tab": "session", "widget": "number", "min": 1,
     "apply": "auto", "comment": "브라우저(hub 화면)가 피드를 다시 가져오는 폴링 주기(초, 참고값)"},
    {"key": "feed_show_project_emoji", "tab": "session", "widget": "toggle",
     "apply": "auto", "comment": "hub 화면 피드 항목에 프로젝트 이모지를 표시할지"},
    {"key": "feed_show_project_name", "tab": "session", "widget": "toggle",
     "apply": "auto", "comment": "hub 화면 피드 항목에 프로젝트명을 표시할지"},
    # 탭 3: 고급 — 렌더·탭 + 네트워크 (Issue197: render·tab 키 basic→advanced 이동,
    #   Issue268: render_tab_mode 는 basic 복귀 — 나머지 탭 세부 키는 잔류)
    # 렌더·탭 동작
    # Issue295: 표면(surface) 축 분리 — vscode 값 신설, hub 는 원뜻(hub http URL + 외부 브라우저) 복원
    {"key": "render_target", "tab": "advanced", "widget": "select",
     "options": ["local-open", "hub", "vscode", "both"],
     "apply": "hook", "comment": "Claude Code(렌더 hook)가 ..show 렌더 결과를 표시하는 경로 — local-open=로컬 file:// 를 외부 브라우저로 열기 / hub=hub 서버 http URL 을 외부 브라우저로 열기 / vscode=외부 브라우저 open 금지, VSCode Simple Browser 패널에 렌더(+채팅 URL fallback) / both=local-open + hub URL 병기. ⚠️ URL 형식(file:// vs http)과 표면(외부 브라우저 vs VSCode 패널)은 별개 축 — vscode 만 표면을 바꿈"},
    # Issue288: 자동 렌더의 VSCode 전면화 가드 (클릭 경로 /open-project·/open-session 은 무관)
    {"key": "simple_browser_focus", "tab": "advanced", "widget": "select",
     "options": ["gate", "always", "never"],
     "apply": "auto", "comment": "Claude Code 자동 렌더가 Simple Browser 패널을 열며 VSCode 창을 전면화할지 — gate(기본)=사용자가 다른 프로젝트 VSCode 창에서 작업 중이면 열지 않음(타이핑 중 포커스 탈취 방지) / always=항상 전면화(구 동작) / never=자동 오픈 안 함(문서 등록·채팅 URL 만). hub 페이지 버튼 클릭으로 여는 경로는 이 설정과 무관하게 항상 열림"},
    {"key": "tab_close_shortcut", "tab": "advanced", "widget": "text",
     "apply": "auto", "comment": "hub 화면 내부 탭을 닫는 단축키 ([ctrl+][alt+][shift+][meta+]<key>). ⚠️ ctrl+w/meta+w 는 브라우저가 선점할 수 있음"},
    # Issue194: hub 내부 탭 모드(render_tab_mode=hub-internal) 단일 창 강제
    {"key": "hub_single_window", "tab": "advanced", "widget": "toggle",
     "apply": "auto", "comment": "hub 서버가 호스트(source-IP)당 hub 쉘 창을 1개로 강제할지 — true=2번째 창에 takeover 안내 / false=다중 창 허용"},
    {"key": "hub_lease_ttl", "tab": "advanced", "widget": "number", "min": 5,
     "apply": "auto", "comment": "hub 서버가 hub 쉘 리스를 회수하기까지의 heartbeat 만료(초). 브라우저의 SSE keepalive 가 이 시간 이상 끊기면 회수"},
    # 네트워크
    # Issue426: 이 둘은 **짝**이다 — 외부 기기에서 hub 를 열려면 양쪽 다 필요하다.
    #   종전 설명은 서로를 가리키지 않아, 접속이 안 될 때 어느 쪽 문제인지 알 수 없었다
    #   (실발생: fg1 이 bind_host=127.0.0.1 이라 안 열렸는데 설정창만 봐선 원인 불명).
    #   "tailscale" 이라는 단어도 어디에도 없어 검색으로도 못 찾았다.
    {"key": "bind_host", "tab": "advanced", "widget": "text",
     "apply": "restart", "comment": "hub 서버가 listen 할 네트워크 인터페이스. 127.0.0.1=루프백 전용(이 PC 에서만 열림) / LAN IP=같은 공유기 안 기기 허용 / 0.0.0.0=전 인터페이스 / [a, b]=멀티. ⚠️ 다른 기기(폰·노트북)에서 접속이 안 되면 대개 여기가 127.0.0.1 이다 — 열어도 안 되면 짝인 advertise_host 를 함께 확인. 변경 시 서버 restart 필요"},
    {"key": "advertise_host", "tab": "advanced", "widget": "text", "optional": True,
     "apply": "hook", "comment": "외부 기기에서 이 hub 를 열 주소(호스트명·IP). 채팅 링크와 /healthz 의 advertise_url 에 쓰인다. 비워 두면 링크를 만들지 않는다(=외부 공유 안 함). ⚠️ bind_host=0.0.0.0 이면 생략 금지. 【Tailscale 을 쓴다면】 LAN IP 는 DHCP 로 바뀌므로 MagicDNS 이름 {host}.{tailnet}.ts.net 을 권장 — 설정 https://tailscale.com/kb/1081/magicdns (macOS 는 자기 이름 해석에 /etc/resolver/{tailnet}.ts.net → nameserver 100.100.100.100 필요). Tailscale 은 선택이며 안 쓰면 LAN IP 나 호스트명을 넣으면 된다"},
    {"key": "allow_server_list", "tab": "advanced", "widget": "toggle",
     "apply": "restart", "comment": "hub 서버 접속 허용 게이트 (source-IP 기준) — true=Servers.md 화이트리스트+자기 자신 허용 / false=자기 자신(bind_host)만 허용, 외부 전부 차단. 변경 시 서버 restart 필요"},
    # Issue379: 수신 이름(Host 헤더) 게이트 — 위 source-IP 게이트의 짝
    {"key": "host_gate", "tab": "advanced", "widget": "toggle",
     "apply": "restart", "comment": "hub 서버 접속 허용 게이트 (수신 이름=Host 헤더 기준) — true(기본)=bind_host·advertise_host·localhost·hostname(.local)·extra_hosts 만 허용하고 그 외 이름은 421 거부(DNS rebinding 방어) / false=모든 이름 허용(종전). IP 리터럴 Host 는 항상 통과. 변경 시 서버 restart 필요"},
    {"key": "ssh_remote_alias", "tab": "advanced", "widget": "text", "optional": True,
     "apply": "auto", "comment": "hub 서버가 원격 브라우저의 open-project/open-session 요청에 vscode-remote://ssh-remote+<alias> 링크로 응답할 때 쓰는 SSH alias (클라이언트 ~/.ssh/config 의 Host 이름, ex: gl). 빈 값=비활성"},
    # Issue277: 활성세션 행 세션 ID 복사 버튼(📋) 표시 여부
    {"key": "live_session_copy_button", "tab": "advanced", "widget": "toggle",
     "apply": "auto", "comment": "hub 화면 활성 세션 행 X(닫기) 왼쪽에 세션 ID 복사 버튼(📋)을 표시할지 — true(기본)=표시 / false=숨김. /cc-session id 없이 hub 에서 바로 sid 복사"},
    # Issue279: 새 피드 도착 시 헤더 활동피드 토글 아이콘 깜빡임
    {"key": "feed_blink_on_new", "tab": "advanced", "widget": "toggle",
     "apply": "auto", "comment": "새 활동피드 항목이 도착하면 헤더 토글 아이콘(🙉↔🙈)을 잠깐 깜빡여 알림 — true(기본)=on / false=off"},
]
HUB_SETTING_SCHEMA_BY_KEY = {s["key"]: s for s in HUB_SETTING_SCHEMA}
# advertise_host 는 yml 에서 기본 주석 처리(`# advertise_host: ...`)된 optional 키.
_HOST_RE = re.compile(r"^[A-Za-z0-9._\-]*$")


def _cast_setting_value(schema: dict, val: str):
    """raw 문자열 val 을 schema widget 기준 타입으로 캐스팅."""
    w = schema["widget"]
    if w == "toggle":
        return val.lower() == "true"
    if w == "number":
        try:
            return int(val)
        except ValueError:
            return 0
    return val  # select / text → 문자열 그대로


def _load_hub_setting_raw() -> dict:
    """Issue168: hub_setting.yml 의 **모든** 스키마 키 현재값을 반환 (HUB_SETTING_DEFAULTS
    화이트리스트 제한 없이 — browser_*·render_target·advertise_host 등 hook 소비 키 포함).
    주석 처리된 optional 키(advertise_host)는 미설정(빈 문자열)으로 반환. server.py 의
    _load_hub_setting 캐시와 독립 — 파일 직독."""
    values = {}
    # 스키마 기본값(파일에 라인 없을 때 폴백): toggle→False, number→0, str→""
    for s in HUB_SETTING_SCHEMA:
        if s["widget"] == "toggle":
            values[s["key"]] = bool(HUB_SETTING_DEFAULTS.get(s["key"], False))
        elif s["widget"] == "number":
            values[s["key"]] = int(HUB_SETTING_DEFAULTS.get(s["key"], 0))
        else:
            values[s["key"]] = str(HUB_SETTING_DEFAULTS.get(s["key"], ""))
    try:
        with open(HUB_SETTING_FILE, encoding="utf-8") as f:
            for line in f:
                # 주석 전용 라인은 무시 (optional 키 주석은 미설정 의미 → 폴백 유지)
                stripped = line.lstrip()
                if stripped.startswith("#") or ":" not in stripped:
                    continue
                body = line.split("#", 1)[0].strip()  # inline 주석 제거
                if ":" not in body:
                    continue
                key, _, val = body.partition(":")
                key, val = key.strip(), val.strip()
                if key in HUB_SETTING_SCHEMA_BY_KEY:
                    values[key] = _cast_setting_value(HUB_SETTING_SCHEMA_BY_KEY[key], val)
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"_load_hub_setting_raw failed: {e}")
    return values


def _load_hub_setting_org() -> dict:
    """data/hub_setting_org.yml(기본값 SSOT 템플릿)의 스키마 키 값을 반환.
    설정창 연필(기본값 대비 변경) 판정의 1차 기준. 파일 부재·파싱 실패 시 빈 dict
    반환 → 호출측이 HUB_SETTING_DEFAULTS/위젯 자연기본으로 fallback."""
    values = {}
    try:
        with open(HUB_SETTING_ORG_FILE, encoding="utf-8") as f:
            for line in f:
                stripped = line.lstrip()
                if stripped.startswith("#") or ":" not in stripped:
                    continue
                body = line.split("#", 1)[0].strip()
                if ":" not in body:
                    continue
                key, _, val = body.partition(":")
                key, val = key.strip(), val.strip()
                if key in HUB_SETTING_SCHEMA_BY_KEY:
                    values[key] = _cast_setting_value(HUB_SETTING_SCHEMA_BY_KEY[key], val)
    except FileNotFoundError:
        log(f"_load_hub_setting_org: {HUB_SETTING_ORG_FILE} 부재 — 내장 기본값 fallback")
    except Exception as e:
        log(f"_load_hub_setting_org failed: {e}")
    return values


def _validate_setting(schema: dict, val) -> str:
    """단일 키 값 검증. 통과 시 None, 실패 시 에러 문자열."""
    w = schema["widget"]
    if w == "toggle":
        if not isinstance(val, bool):
            return f"{schema['key']}: bool required"
    elif w == "number":
        if not isinstance(val, int) or isinstance(val, bool):
            return f"{schema['key']}: integer required"
        if val < schema.get("min", 0):
            return f"{schema['key']}: must be >= {schema.get('min', 0)}"
    elif w == "select":
        if val in schema["options"]:
            return None
        if schema.get("allow_custom") and isinstance(val, str) and val.startswith("/") and val.endswith(".app"):
            return None
        return f"{schema['key']}: must be one of {schema['options']} (or .app path)"
    elif w == "text":
        if not isinstance(val, str):
            return f"{schema['key']}: string required"
        if not schema.get("optional") and not val:
            return f"{schema['key']}: required"
        if not _HOST_RE.match(val):
            return f"{schema['key']}: invalid host chars"
    return None


def _setting_to_yml_value(schema: dict, val) -> str:
    """파이썬 값 → yml 표기 문자열."""
    if schema["widget"] == "toggle":
        return "true" if val else "false"
    return str(val)


def _write_hub_setting(payload: dict, client_mtime: float = None):
    """Issue168: payload(변경 diff)를 hub_setting.yml 에 주석 보존하며 기록.
    라인 in-place 치환(inline 주석 보존) + temp→os.replace 원자적 쓰기.
    반환 (ok, restart_required, status_code, err)."""
    if not isinstance(payload, dict) or not payload:
        return False, [], 400, "empty payload"
    # 1. 키 화이트리스트 + 값 검증
    for key, val in payload.items():
        sc = HUB_SETTING_SCHEMA_BY_KEY.get(key)
        if sc is None:
            return False, [], 400, f"unknown key: {key}"
        err = _validate_setting(sc, val)
        if err:
            return False, [], 400, err
    # 2. 위험 조합 차단: 결과 bind_host=0.0.0.0 + advertise_host 빈값
    cur = _load_hub_setting_raw()
    merged = dict(cur)
    merged.update(payload)
    if merged.get("bind_host") == "0.0.0.0" and not (merged.get("advertise_host") or "").strip():
        return False, [], 400, "bind_host 0.0.0.0 requires advertise_host (URL 좀비 가드)"
    # 3. 동시편집 감지 (선택): client_mtime 제공 시 현재 mtime 과 비교
    try:
        cur_mtime = os.stat(HUB_SETTING_FILE).st_mtime
    except FileNotFoundError:
        return False, [], 500, "hub_setting.yml not found"
    if client_mtime is not None and abs(cur_mtime - float(client_mtime)) > 1e-6:
        return False, [], 409, "file changed externally — reload"
    # 4. 라인 in-place 치환
    try:
        with open(HUB_SETTING_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        return False, [], 500, f"read failed: {e}"

    active_re = re.compile(r"^(\s*)([a-z_]+)(\s*:\s*)(\S+)(\s*#.*)?(\r?\n?)$")
    comment_re = re.compile(r"^(\s*)#\s*([a-z_]+)(\s*:\s*)(\S+)(\s*#.*)?(\r?\n?)$")
    handled = set()
    out = []
    for line in lines:
        m = active_re.match(line)
        if m and m.group(2) in payload:
            key = m.group(2)
            sc = HUB_SETTING_SCHEMA_BY_KEY[key]
            new_val = (payload[key] or "").strip() if sc["widget"] == "text" else payload[key]
            # optional text 키가 빈값 → 라인을 다시 주석 처리
            if sc["widget"] == "text" and sc.get("optional") and not new_val:
                out.append(f"{m.group(1)}# {key}{m.group(3)}{m.group(4)}{m.group(5) or ''}{m.group(6)}")
            else:
                yval = _setting_to_yml_value(sc, new_val)
                out.append(f"{m.group(1)}{key}{m.group(3)}{yval}{m.group(5) or ''}{m.group(6)}")
            handled.add(key)
            continue
        cm = comment_re.match(line)
        if cm and cm.group(2) in payload and cm.group(2) not in handled:
            key = cm.group(2)
            sc = HUB_SETTING_SCHEMA_BY_KEY[key]
            new_val = (payload[key] or "").strip()
            if new_val:
                # 주석 → 활성화
                yval = _setting_to_yml_value(sc, new_val)
                out.append(f"{cm.group(1)}{key}{cm.group(3)}{yval}{cm.group(5) or ''}{cm.group(6)}")
                handled.add(key)
                continue
            # 빈값 → 주석 라인 유지 (미설정)
            handled.add(key)
        out.append(line)
    # 5. payload 에 있으나 파일에 라인 없는 키 → 파일 끝 append
    tail = []
    for key, val in payload.items():
        if key in handled:
            continue
        sc = HUB_SETTING_SCHEMA_BY_KEY[key]
        if sc["widget"] == "text" and sc.get("optional") and not (val or "").strip():
            continue  # 미설정 optional → append 안 함
        tail.append(f"{key}: {_setting_to_yml_value(sc, val)}\n")
    if tail:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.extend(tail)
    # 6. 원자적 쓰기
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(HUB_SETTING_FILE), prefix=".hub_setting_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(out)
        os.replace(tmp, HUB_SETTING_FILE)
    except OSError as e:
        return False, [], 500, f"write failed: {e}"
    # 7. restart 필요 키 집계 (값이 실제 변경된 restart 키만)
    restart_required = [k for k in payload
                        if HUB_SETTING_SCHEMA_BY_KEY[k]["apply"] == "restart" and cur.get(k) != payload[k]]
    return True, restart_required, 200, None


# Issue87: 중요 이벤트 판정 모듈 임계값 — _compute_important_events 가 참조.
#   상수로 분리하여 판정 기준을 한곳에서 조정 가능하게 한다.
IMPORTANT_RESPONSE_WAIT_SEC = 300    # 응답 정체 판정 하한 (5분)
IMPORTANT_RESPONSE_CRIT_SEC = 1800   # 응답 정체 critical 승격 (30분)
IMPORTANT_RESPONSE_ABANDON_SEC = 21600  # Issue100: 6h+ 미해소 wait 는 방치(abandoned)로 간주, R2 배제
IMPORTANT_STALE_CARD_MIN = 5         # dashboard 카드 정리 권고 임계
IMPORTANT_HTM_DOC_MIN = 200          # htm 문서 정리 권고 임계
DASH_STATUS_NONE_GRACE_SEC = 120     # status 필드 없는(첫 write 전) dash 파일을 stale 로 강등하는 유예시간
# Issue403: status='running' 인데 pid 검증이 **불가능한**(pid·worker_pid 둘 다 비정수)
#   dash 를 mtime 정체로 강등하기까지 허용할 갱신 주기 수. 고정 초 상수를 쓰면 10초 보드와
#   5분 보드 중 한쪽이 반드시 틀린다 — 살아 있는 runner 는 interval 마다 파일을 다시 쓰므로
#   "연속 N주기 write 실종" 이 곧 죽음의 증거다. 배수는 오강등 여유를 위해 넉넉히 잡는다.
DASH_RUNNING_STALE_INTERVALS = 10
# R2 응답 정체 판정 대상 이벤트 — 사용자 입력을 기다리는 hook 이벤트
IMPORTANT_WAIT_EVENTS = ("AskUserQuestion", "Notification")

# Issue42: hook 이벤트 활동 피드 — in-memory deque(newest-first) + 디스크 영속
HOOK_FEED_FILE = os.path.join(DATA_HUB_DIR, "hook-feed.json")
feed_lock = threading.Lock()
feed_buffer: deque = deque(maxlen=_load_hub_setting()["feed_limit"])


def _feed_buffer_synced() -> deque:
    """hub_setting.yml 의 feed_limit 에 deque maxlen 을 동기화. 변경 시 재생성
    (축소 시 오래된 항목부터 절단). 호출자가 feed_lock 보유 상태여야 함."""
    global feed_buffer
    limit = _load_hub_setting()["feed_limit"]
    if feed_buffer.maxlen != limit:
        feed_buffer = deque(feed_buffer, maxlen=limit)
    return feed_buffer


def persist_feed() -> None:
    """feed_buffer 를 hook-feed.json 에 원자적 flush (tmp → os.replace).

    ThreadingHTTPServer 다중 요청 스레드가 persist_feed 를 동시 호출하면,
    종전엔 공유 `.tmp` 경로(HOOK_FEED_FILE + ".tmp") 에 두 스레드가 동시 쓰기 →
    내용 혼입(JSON "Extra data") + os.replace race(tmp 소실) 로 hook-feed.json 이
    손상되었다. 손상 파일은 재시작 시 load_feed json.load 예외 → feed 전체 손실
    (사용자 관찰: "활동 피드 갑자기 사라짐"). 두 축으로 차단:
      1) tmp 경로를 pid·tid 로 유니크화 — 스레드간 tmp 충돌 제거
      2) 파일 I/O 전체를 feed_lock 으로 직렬화 — snap·write·replace 원자화"""
    try:
        os.makedirs(DATA_HUB_DIR, exist_ok=True)
        with feed_lock:
            snap = list(feed_buffer)
            tmp = f"{HOOK_FEED_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
            os.replace(tmp, HOOK_FEED_FILE)
    except Exception as e:
        log(f"persist_feed failed: {e}")


def load_feed() -> None:
    """재시작 시 hook-feed.json 복원 (newest-first 순서 유지). Issue95: DASH_CLEARED tombstone 필터."""
    if not os.path.exists(HOOK_FEED_FILE):
        return
    # 손상 파싱은 별도 가드: persist race 등으로 JSON 이 깨지면("Extra data")
    #   여기서 feed 전체가 사라진다. 손상본을 .corrupt 로 보존(사후 분석) 후 빈 상태로
    #   진행 — 추가 손실 없이 재축적되게 한다.
    try:
        with open(HOOK_FEED_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log(f"load_feed: hook-feed.json corrupt ({e}) — backing up to .corrupt")
        try:
            os.replace(HOOK_FEED_FILE, HOOK_FEED_FILE + ".corrupt")
        except Exception as e2:
            log(f"load_feed: .corrupt backup failed: {e2}")
        return
    try:
        if not isinstance(data, list):
            return
        # Issue95: DASH_CLEARED tombstone 검증 — feed 복구 시 cleared dashboard 항목 제외
        cleared = set(load_registry(DASH_CLEARED))
        if cleared:
            before = len(data)
            data = [it for it in data
                    if not any(p in it.get("detail", "") for p in cleared if p)]
            if len(data) < before:
                log(f"load_feed: {before - len(data)} items filtered (DASH_CLEARED tombstone)")
        with feed_lock:
            buf = _feed_buffer_synced()
            buf.clear()
            buf.extend(data)
        log(f"restored {len(data)} hook-feed items from {HOOK_FEED_FILE}")
    except Exception as e:
        log(f"load_feed failed: {e}")


def _dash_cleared_norm() -> set:
    """DASH_CLEARED tombstone 의 path 를 realpath 정규화한 집합.
    clear-done(os.path.join)·control-remove(realpath)·_all_disk_dash_paths 가
    서로 다른 정규화로 path 를 기록 → 비교 시 양측 realpath 로 통일한다."""
    out = set()
    for p in load_registry(DASH_CLEARED):
        if not p:
            continue
        try:
            out.add(os.path.realpath(os.path.expanduser(p)))
        except Exception:
            out.add(p)
    return out


def _dash_session_candidate_paths(cwd: str, entry: dict) -> set:
    """Issue95: dashboard 세션 entry 가 가리키는 dash 파일 절대경로(realpath) 집합.
    DASH_CLEARED tombstone 매칭용. content 의 dash_path 만 권위적 신호로 사용한다 —
    title-slug 추정은 (1) 실제 파일명이 title 과 분기하면 매칭 실패하고 (2) 신규 동명
    dashboard 가 등록 전 윈도우에서 오인 차단될 위험이 있어 채택하지 않는다. dash_path
    미기록 세션은 clear-done/control-remove 의 sid 기반 제거로 source 에서 정리된다.

    cwd 인자는 향후 확장(프로젝트별 경로 보정)을 위한 자리표시 — 현재 미사용."""
    if entry.get("content_type") != "dashboard":
        return set()
    try:
        d = json.loads(entry.get("content") or "")
    except Exception:
        return set()
    if not isinstance(d, dict):
        return set()
    dp = d.get("dash_path")
    if not isinstance(dp, str) or not dp.strip():
        return set()
    try:
        return {os.path.realpath(os.path.expanduser(dp.strip()))}
    except Exception:
        return {dp.strip()}


# Issue394: 서버가 디스크로 내보내는 텍스트에서 hub 토큰을 지운다.
#
# 배경 — `const TOKEN`(SESSION_SHELL_HTML) 은 `Cache-Control: no-store` 로 **HTTP 응답에만**
# 실리고 서버가 파일로 쓰지 않는다. 그런데도 `_doc_work/htm/` 에 토큰이 박힌 파일이 쌓였다.
# 실측한 유입 경로 3종 중 둘(파일 기반 `..ask` 폼 · queue-runner shim)은 SPA 이관·코드 제거로
# 이미 소멸했고, **살아 있는 마지막 경로가 턴 아카이브**다 — Claude 응답 본문에 라이브 뷰
# URL(`/s/{h}/{sid}?token=…`)이 들어가면 `_write_turn_archive()` 가 그대로 파일로 굳힌다.
#
# 토큰을 안 만들 수는 없으니 **파일로 나가는 길목에서 지운다**. 마스킹은 비가역이고
# 아카이브는 읽기 전용 기록물이라 기능 손실이 없다(링크를 다시 쓰려면 어차피 재등록한다).
_TOKEN_CTX_RE = re.compile(r"(?i)\b(token)(\s*[=:]\s*[\"']?)([0-9a-f]{32})")
TOKEN_REDACTED = "<redacted:hub-token>"


def redact_tokens(text: str) -> str:
    """텍스트에서 hub 토큰을 마스킹한다. 2중 그물 — 문맥 + 실제 값 대조.

    * 문맥 규칙 `token=<32hex>` — 아직 발급된 적 없는 값·과거 세대까지 걸러낸다
    * 값 대조 — `projects` 에 실재하는 토큰은 문맥이 없어도(맨 hex 로 적혀도) 지운다

    문맥 규칙만 쓰면 값만 덩그러니 적힌 경우를 놓치고, 값 대조만 쓰면 이미 만료된
    과거 토큰이 그대로 파일에 남는다. 둘 다 필요하다."""
    if not text:
        return text
    out = _TOKEN_CTX_RE.sub(lambda m: m.group(1) + m.group(2) + TOKEN_REDACTED, text)
    try:
        with projects_lock:
            live = {p.get("token") for p in projects.values() if isinstance(p, dict)}
    except Exception:
        live = set()
    for tok in live:
        if isinstance(tok, str) and len(tok) == 32 and tok in out:
            out = out.replace(tok, TOKEN_REDACTED)
    return out


def persist_tokens() -> None:
    """projects dict를 tokens.json에 flush."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with projects_lock:
            snap = {h: p for h, p in projects.items()}
        with open(TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        os.chmod(TOKENS_FILE, 0o600)
    except Exception as e:
        log(f"persist_tokens failed: {e}")


def load_tokens() -> None:
    """재시작 시 tokens.json 복원."""
    if not os.path.exists(TOKENS_FILE):
        return
    try:
        with open(TOKENS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Issue28: 저장된 color 는 polluted (옛 hsl). project_meta() 재호출로 Projects.md peacock.color 반영
        for h, p in data.items():
            cwd = p.get("cwd")
            if cwd:
                meta = project_meta(cwd)
                p["color"] = meta["color"]
                p["name"] = meta.get("name", p.get("name"))
        with projects_lock:
            projects.update(data)
        log(f"restored {len(data)} project tokens from {TOKENS_FILE}")
    except Exception as e:
        log(f"load_tokens failed: {e}")


def persist_sessions() -> None:
    """Issue17 Phase 1: sessions dict 를 sessions.json 에 atomic flush."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with sessions_lock:
            snap = {f"{h}|{sid}": v for (h, sid), v in sessions.items()}
        tmp = SESSIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, SESSIONS_FILE)
    except Exception as e:
        log(f"persist_sessions failed: {e}")


def load_sessions() -> None:
    """Issue17 Phase 1: 재시작 시 sessions.json 복원."""
    if not os.path.exists(SESSIONS_FILE):
        return
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Issue95: DASH_CLEARED tombstone 검증 — cleared dashboard 세션은 복원 제외
        #   (live-session 부활 채널 차단. load_feed 의 tombstone 필터와 대칭).
        cleared = _dash_cleared_norm()
        restored = filtered = 0
        with projects_lock:
            cwd_by_h = {h: p.get("cwd", "") for h, p in projects.items()}
        with sessions_lock:
            for key, val in data.items():
                if "|" not in key:
                    continue
                h, sid = key.split("|", 1)
                if cleared and val.get("content_type") == "dashboard":
                    cwd = cwd_by_h.get(h, "")
                    if _dash_session_candidate_paths(cwd, val) & cleared:
                        filtered += 1
                        continue
                # Issue99: pid 없는 live 세션은 레거시(구 계약)·식별 불가 → 복원 제외.
                #   재시작 후 pid 죽은 live 세션도 _pid_alive 로 어차피 terminal 이지만,
                #   no-pid 는 복원 단계에서 차단해 좀비 카드 잔존을 원천 제거.
                # Issue397: 단 gc_meta.shell_pid(등록 pid 의 부모)가 살아있는 claude
                #   세션 프로세스면 오염 pid 소실분(prj3#428)이다 — pid 를 승격해
                #   복원한다. 식별 가능해지므로 좀비 카드 위험 없음(_pid_alive 게이트 유효).
                if val.get("content_type") == "live" and val.get("live_pid") is None:
                    gm = val.get("gc_meta") if isinstance(val.get("gc_meta"), dict) else {}
                    sp = gm.get("shell_pid")
                    try:
                        sp = int(sp) if sp is not None else None
                    except (TypeError, ValueError):
                        sp = None
                    if sp and _pid_alive(sp) and _claude_proc_like(sp):
                        val["live_pid"] = sp
                        gm["for_pid"] = sp
                        log(f"load_sessions: live_pid promoted via gc_meta.shell_pid — "
                            f"sid={sid} pid={sp} (Issue397)")
                    else:
                        filtered += 1
                        continue
                sessions[(h, sid)] = val
                restored += 1
        if filtered:
            log(f"load_sessions: {filtered} dashboard sessions filtered (DASH_CLEARED tombstone)")
        log(f"restored {restored} sessions from {SESSIONS_FILE}")
    except Exception as e:
        log(f"load_sessions failed: {e}")


def _pid_alive(pid: int) -> bool:
    """Issue37: PID 가 살아있는지 확인. 죽은 PID 는 zombie 판정 시 무시."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


def _claude_proc_like(pid) -> bool:
    """Issue397: pid 가 claude 세션 프로세스인지 ps 로 판정 — live_pid 승격 안전 게이트.
    훅 lib/claude-pid.sh 의 _fpm_is_claude_proc 와 동일 기준: comm basename 이 claude
    계열이거나 args 가 claude 배포본(cli.js·native-binary)일 때만 True.
    VSCode extension host(Code Helper) 등 세션보다 오래 사는 호스트로의 오승격을 막는다
    (오승격되면 끝난 세션이 영구 live 로 남는다 — Issue374 와 같은 계열 위험)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        comm = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        return False
    if comm.rsplit("/", 1)[-1] in ("claude", "claude-code"):
        return True
    try:
        args = subprocess.run(["ps", "-o", "args=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return False
    return (("claude" in args and "cli.js" in args) or "claude-code" in args
            or "native-binary/claude" in args)


def _try_promote_live_pid(h, sid, entry):
    """Issue397: 죽은·소실 live_pid 를 gc_meta.shell_pid(등록 pid 의 부모)로 승격 시도.

    배경: 훅이 단명 wrapper pid 를 등록하면(prj3#428) 등록 직후 pid 가 죽어
    live_pid 가 pop 되고, 세션이 LIVE_TTL(300s) 경로로 강등돼 idle 5분 후 카드에서
    사라진다(prj9a 실측 — 생존 4세션 중 2개만 표시). _capture_gc_meta 가 등록 pid 의
    부모를 shell_pid 로 캡처해 두므로, 그 부모가 살아있는 claude 세션 프로세스면
    pid 권위를 복구할 수 있다(실측: 등록 pid 46775 사망 → shell_pid 45312 = 실세션).

    성공 시 sessions·entry 양쪽 live_pid 갱신 후 새 pid 반환, 실패 시 None.
    시도는 세션당 1회(gc_meta.promote_tried) — terminal 후보는 매 폴링(5s) 재판정되므로
    가드 없으면 죽은 세션마다 ps 가 TERMINAL_TTL(1h) 동안 반복된다."""
    gm = entry.get("gc_meta")
    if not isinstance(gm, dict) or gm.get("promote_tried"):
        return None
    with sessions_lock:
        cur = sessions.get((h, sid))
        if cur is not None and isinstance(cur.get("gc_meta"), dict):
            cur["gc_meta"]["promote_tried"] = True
    gm["promote_tried"] = True
    sp = gm.get("shell_pid")
    try:
        sp = int(sp) if sp is not None else None
    except (TypeError, ValueError):
        return None
    if not sp or not _pid_alive(sp) or not _claude_proc_like(sp):
        return None
    with sessions_lock:
        cur = sessions.get((h, sid))
        if cur is not None:
            cur["live_pid"] = sp
            if isinstance(cur.get("gc_meta"), dict):
                cur["gc_meta"]["for_pid"] = sp
    entry["live_pid"] = sp
    gm["for_pid"] = sp
    log(f"_collect_live_sessions: live_pid promoted via gc_meta.shell_pid — "
        f"sid={sid} pid={sp} (Issue397)")
    return sp


# --- Issue280: 세션 GC (세션·터미널 pane 강제 종료) ---------------------------
# 가비지 세션(VSCode 터미널·tmux·iTerm 에 잔존)의 수동 GC. 핵심 설계:
#   - register(live) 시점에 컨테이너 메타(gc_meta)를 캡처 — claude 사후에도
#     shell/tmux pane 정리 가능 (죽은 뒤엔 ppid·pane 역추적 불가).
#   - kill 대상은 sessions entry 의 live_pid·gc_meta 만 (body pid 수신 금지, Issue86 패턴).
#   - kill 직전 comm 대조로 pid 재사용 오살 차단 (_gc_guard).

def _ps_ppid(pid: int):
    """pid 의 부모 pid. 실패 시 None."""
    try:
        r = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=3)
        v = r.stdout.strip()
        return int(v) if v else None
    except Exception:
        return None


def _ps_comm(pid: int):
    """pid 의 실행 커맨드명(comm). 실패 시 None."""
    try:
        r = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=3)
        v = r.stdout.strip()
        return v or None
    except Exception:
        return None


def _tmux_pane_for_pids(pids_set: set):
    """후보 pid 집합이 tmux pane 루트 프로세스(pane_pid)와 일치하면 pane_id 반환.
    tmux 미설치·서버 미가동·비매칭 → None."""
    try:
        r = subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_pid} #{pane_id}"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) in pids_set:
                return parts[1]
    except Exception:
        pass
    return None


def _capture_gc_meta(pid: int) -> dict:
    """register(live) 수신 시점(프로세스 생존 중) 컨테이너 메타 캡처.
    shell_cmd 는 kill 시점 pid 재사용 대조용 스냅샷."""
    meta = {"for_pid": pid, "captured": time.time(),
            "shell_pid": None, "shell_cmd": None, "tmux_pane": None}
    sp = _ps_ppid(pid)
    if sp and sp > 1:
        meta["shell_pid"] = sp
        meta["shell_cmd"] = _ps_comm(sp)
    cand = {pid}
    if meta["shell_pid"]:
        cand.add(meta["shell_pid"])
    meta["tmux_pane"] = _tmux_pane_for_pids(cand)
    return meta


def _gc_plan(entry: dict) -> list:
    """GC escalation 단계 계획 (순수 — 실행 없음). 순서 고정:
    ① tmux pane kill(pane 통째 GC) ② claude pid ③ 부모 shell.
    ①이 성공하면 ②③은 실행 단계에서 already-dead 로 수렴."""
    steps = []
    meta = entry.get("gc_meta") or {}
    live_pid = entry.get("live_pid")
    if meta.get("tmux_pane"):
        steps.append({"kind": "tmux-kill-pane", "target": meta["tmux_pane"]})
    if live_pid:
        steps.append({"kind": "kill-claude", "pid": int(live_pid)})
    if meta.get("shell_pid"):
        steps.append({"kind": "kill-shell", "pid": int(meta["shell_pid"]),
                      "expect_cmd": meta.get("shell_cmd")})
    return steps


def _gc_guard(kind: str, pid: int, expect_cmd, comm, server_pid: int):
    """kill 직전 가드 판정 (순수). 통과 None, 차단 시 사유 문자열.
    - pid ≤ 1·hub 자신 방어
    - kill-claude: comm 에 claude 포함 또는 node/bun (pid 재사용 차단)
    - kill-shell: 캡처 시점 shell_cmd 와 현재 comm 일치 요구"""
    if not pid or pid <= 1 or pid == server_pid:
        return "invalid/self pid"
    if kind == "kill-claude":
        c = (comm or "").lower()
        if "claude" not in c and os.path.basename(c) not in ("node", "bun"):
            return f"comm mismatch: {comm!r}"
    elif kind == "kill-shell":
        if expect_cmd and comm != expect_cmd:
            return f"comm mismatch: {comm!r} != {expect_cmd!r}"
    return None


def _gc_execute(steps: list) -> list:
    """GC plan 실행. 단계별 결과 리스트 반환 (분석 레코드에 그대로 저장).
    signal 단계: SIGTERM → 2s poll → SIGKILL → 1s poll."""
    stages = []
    server_pid = os.getpid()
    for st in steps:
        kind = st["kind"]
        if kind == "tmux-kill-pane":
            try:
                r = subprocess.run(["tmux", "kill-pane", "-t", st["target"]],
                                   capture_output=True, text=True, timeout=5)
                ok = r.returncode == 0
                err = (r.stderr or "").strip() or None
            except Exception as ex:
                ok, err = False, str(ex)
            stages.append({"step": kind, "target": st["target"], "ok": ok, "err": err})
            if ok:
                time.sleep(0.3)  # pane 하위 프로세스 사망 대기 → 후속 단계 already-dead 수렴
            continue
        pid = int(st.get("pid") or 0)
        if pid > 1 and not _pid_alive(pid):
            stages.append({"step": kind, "pid": pid, "ok": True, "note": "already dead"})
            continue
        reason = _gc_guard(kind, pid, st.get("expect_cmd"), _ps_comm(pid), server_pid)
        if reason:
            stages.append({"step": kind, "pid": pid, "ok": False, "note": "guard skip: " + reason})
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as ex:
            stages.append({"step": kind, "pid": pid, "ok": False, "note": f"SIGTERM failed: {ex}"})
            continue
        deadline = time.time() + 2.0
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.2)
        sig_used = "SIGTERM"
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
                sig_used = "SIGKILL"
            except OSError:
                pass
            deadline = time.time() + 1.0
            while time.time() < deadline and _pid_alive(pid):
                time.sleep(0.1)
        stages.append({"step": kind, "pid": pid, "ok": not _pid_alive(pid), "signal": sig_used})
    return stages


# --- Issue331: Zed orphan live 세션 리퍼 (하이브리드) -------------------------
# Zed 는 스레드마다 claude 를 띄우지만 스레드를 닫아도 그 프로세스를 죽이지 않아
# live 세션 카드·프로세스가 무한 누적된다. 실측(2026-07-27):
#   - 전 스레드의 부모가 단일 ACP 브리지(node claude-agent-acp) 하나였다.
#     → "부모 사망 → orphan" 판정은 Zed 앱을 종료했을 때만 발동하고,
#       스레드 닫힘은 구분하지 못한다.
#   - 프로세스 상태·CPU·fd 구성도 활성/비활성이 동일했다.
#   - 유일하게 갈라지는 신호가 heartbeat 신선도(= transcript mtime)였다.
# 따라서 하이브리드로 갔다: 브리지 사망은 즉시 리핑(부모 판정의 유효 부분),
# 그 외는 idle TTL. 대상은 origin=="zed" 세션으로 한정한다 — VSCode 확장은
# 자체 세션 관리가 있고, 터미널 세션은 사용자가 직접 띄운 것이라 오살 위험이 크다.
#
# ⚠️ idle-ttl 철회 (2026-08-05, prj5 실측) ------------------------------------
# heartbeat 신선도는 "닫힌 스레드"와 "열려 있지만 유휴인 스레드"를 구분하지 못한다.
# 그 결과 사용자가 30분 자리를 비우면 살아있는 스레드가 SIGTERM 되고, claude 는
# 핸들러에서 exit(143), ACP 브리지가 세션을 evict → 사용자가 입력하는 순간
# "Session not found" 로 스레드가 통째로 못 쓰게 됐다(Zed 0.64.2 는 session/load
# 를 부르지 않아 복구 불가). 2026-08-03~05 실측 22건 전부 reasons=['idle-ttl'].
# 리핑 이득(프로세스 누적 억제)보다 손실(작업 중 스레드 소실)이 커서 제거한다.
#
# ⚠️ 위 문단의 "스레드마다 브리지를 따로 띄운다" 는 오판이었다 (Issue360, 2026-08-07)
# 실측: 등록된 zed live 세션 27개의 부모가 전부 동일 브리지 PID 하나였고, 실제
# 브리지는 3개(창 단위)뿐이었다. 2026-07-27 의 "단일 브리지" 관측이 여전히 맞다.
# 그래서 bridge-dead 는 Zed 앱을 통째로 끄기 전에는 참이 될 수 없고, 리퍼는 기동
# 이후 단 1건도 잡지 못했다(로그에 started 만, reaped 0건). idle-ttl 을 철회한
# 자리를 메울 신호가 없어 누적이 그대로 진행됐다.
#
# --- Issue360: 스레드 닫힘의 "직접 신호" 도입 -------------------------------
# ACP 프로토콜에는 스레드 닫힘 알림이 없다 — 메서드 전수 12종(session/{new,load,
# prompt,cancel,fork,list,resume,update,set_mode,set_model,set_config_option,
# request_permission})에 close 가 없고, 브리지의 cancel() 은 cancelled 플래그만
# 세우고 세션을 delete 하지 않는다. 즉 브리지조차 닫힘을 모르므로 그 경유로는
# 원리적으로 불가능하다.
# 대신 Zed 가 자기 로컬 db 에 사실을 기록한다:
#   ~/Library/Application Support/Zed/db/<채널>/db.sqlite
#     테이블 sidebar_threads(session_id, agent_id, archived, ...)
#   agent_id='claude-acp' + archived=1 → 그 스레드는 닫혔다
# hub 의 sid 와 Zed 의 session_id 는 같은 값이다(실측 교집합 37건).
#
# idle-ttl 과의 결정적 차이: idle-ttl 은 열림/닫힘을 heartbeat 로 *추측*했으나
# archived 는 Zed 가 닫는 순간 *기록한 사실*이다. archived=0 은 절대 건드리지
# 않으므로 "유휴한 열린 스레드" 를 죽이는 Issue357 의 사고 경로가 구조적으로 없다.
# 되살아난 스레드도 안전하다 — 아카이브된 스레드를 다시 열면 Zed 가 session/load
# 로 새 프로세스를 띄우므로 "Session not found" 로 못 쓰게 되지 않는다.


ZED_DB_GLOB = os.path.expanduser("~/Library/Application Support/Zed/db/*/db.sqlite")


def _zed_archived_sids() -> frozenset:
    """Issue360: Zed 가 '닫힘'으로 기록한 ACP 스레드의 session_id 집합.

    실행 중인 db 를 읽기 전용(mode=ro)으로 붙는다 — WAL 최신 상태가 반영되고
    실측 2ms 다. 릴리즈 채널마다 db 가 갈리므로 glob 로 전부 훑어 합집합을 만든다
    (session_id 는 UUID 라 채널 간 충돌이 없다).

    fail-soft: db 부재·테이블 없음(0-global 등)·lock·권한 실패는 조용히 건너뛴다.
    빈 집합을 돌려주면 호출부가 thread-archived 판정을 하지 않을 뿐이고, 기존
    bridge-dead 판정은 그대로 산다. 여기서 loud 하게 굴면 Zed 를 안 쓰는 사용자의
    리퍼까지 매 주기 시끄러워진다."""
    sids = set()
    for path in glob.glob(ZED_DB_GLOB):
        con = None
        try:
            uri = "file:" + path.replace("?", "%3f").replace("#", "%23") + "?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=1.0)
            con.execute("PRAGMA busy_timeout=800")
            rows = con.execute(
                "SELECT session_id FROM sidebar_threads "
                "WHERE agent_id='claude-acp' AND archived=1 AND session_id IS NOT NULL"
            ).fetchall()
            sids.update(r[0] for r in rows if r and r[0])
        except sqlite3.Error:
            continue  # 테이블 없음·lock·손상 — 이 db 만 건너뛴다
        except Exception:
            continue
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    return frozenset(sids)


def _zed_orphan_reason(entry: dict, now: float, sid: str = "",
                       archived_sids: frozenset = frozenset()):
    """origin=zed live 세션의 orphan 사유 판정 (순수 — kill 없음).
    반환: 사유 문자열 또는 None(보존).
      - thread-archived : Zed 가 그 스레드를 닫음(sidebar_threads.archived=1) — Issue360
      - bridge-dead     : 등록 시 캡처한 부모(ACP 브리지)가 죽었거나 reparent 됨
    `now` 는 idle-ttl 철회 후 미사용 — 호출부 시그니처 유지를 위해 남겨 둔다.
    `archived_sids` 는 호출부가 1회 조회해 넘긴다(세션마다 db 를 열지 않기 위함).
    """
    if entry.get("content_type") != "live":
        return None
    if _origin_from_caps(entry.get("capabilities") or {}) != "zed":
        return None
    pid = entry.get("live_pid")
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 1 or not _pid_alive(pid):
        return None  # 이미 죽음 — 카드 정리는 기존 게이트가 처리
    # Issue360: 스레드 닫힘의 직접 신호. archived=1 로 *명시된* sid 만 잡는다 —
    #   db 에 아직 안 올라온 신규 세션·조회 실패는 여기서 보존된다(블랙리스트).
    if sid and sid in archived_sids:
        return "thread-archived"
    meta = entry.get("gc_meta") or {}
    captured_parent = meta.get("shell_pid")
    cur_ppid = _ps_ppid(pid)
    if captured_parent:
        if cur_ppid is None or cur_ppid <= 1 or cur_ppid != int(captured_parent):
            return "bridge-dead"
        if not _pid_alive(int(captured_parent)):
            return "bridge-dead"
    elif cur_ppid is not None and cur_ppid <= 1:
        return "bridge-dead"
    return None


def _reap_zed_orphans() -> dict:
    """orphan 판정된 zed live 세션을 종료·정리. 반환 요약 dict.
    kill 은 _gc_execute 의 kill-claude 단계를 재사용한다(comm 대조 가드 포함 —
    pid 재사용 오살 차단). 종료 후 sessions prune + dismiss tombstone 으로
    마지막 heartbeat 재등록을 막는다."""
    now = time.time()
    with sessions_lock:
        snap = list(sessions.items())
    # Issue360: db 조회는 세션당이 아니라 1회. 실패 시 빈 집합 → bridge-dead 만 산다.
    archived_sids = _zed_archived_sids()
    victims = []  # (h, sid, pid, reason)
    zed_seen = 0
    for (h, sid), entry in snap:
        if not isinstance(entry, dict):
            continue
        if (entry.get("content_type") == "live"
                and _origin_from_caps(entry.get("capabilities") or {}) == "zed"):
            zed_seen += 1
        reason = _zed_orphan_reason(entry, now, sid, archived_sids)
        if reason:
            victims.append((h, sid, int(entry.get("live_pid")), reason))
    # Issue360: 0건일 때도 판정 재료를 돌려준다. Issue331 리퍼가 반년 가까이
    #   헛돌았는데 아무도 몰랐던 이유가 "0건 잡음"과 "고장나서 0건"을 구분할
    #   수단이 없었기 때문이다. zed_seen>0 인데 archived_known=0 이면 db 조회
    #   실패를, 둘 다 0 이면 그냥 대상이 없음을 뜻한다.
    if not victims:
        return {"reaped": 0, "victims": [], "zed_seen": zed_seen,
                "archived_known": len(archived_sids)}
    results = []
    for h, sid, pid, reason in victims:
        stages = _gc_execute([{"kind": "kill-claude", "pid": pid}])
        ok = bool(stages and stages[0].get("ok"))
        _live_dismiss_add(h, sid)
        results.append({"sid": sid, "pid": pid, "reason": reason, "killed": ok,
                        "note": stages[0].get("note") if stages else None})
    pruned = 0
    with sessions_lock:
        for h, sid, _, _ in victims:
            if sessions.pop((h, sid), None) is not None:
                pruned += 1
    if pruned:
        persist_sessions()
    log(f"[reaper] zed orphans reaped={len(results)} pruned={pruned} "
        f"archived_known={len(archived_sids)} reasons={[r['reason'] for r in results]}")
    return {"reaped": len(results), "pruned": pruned, "zed_seen": zed_seen,
            "archived_known": len(archived_sids), "victims": results}


def _orphan_reaper_loop(interval: float = 120.0) -> None:
    """주기 리퍼. 대상 세션이 없으면 판정 비용도 0 에 수렴(딕셔너리 스캔뿐)."""
    log(f"[reaper] started — interval={interval}s "
        f"policy=thread-archived+bridge-dead (zed only)")
    while True:
        try:
            time.sleep(interval)
            _reap_zed_orphans()
        except Exception as e:
            log(f"[reaper] loop error: {e}")


def _resolve_aoa_mq_tick() -> str:
    """aoa-mq tick 스크립트 경로 — **자기 위치 기준을 먼저** 본다 (Issue428).

    종전엔 `~/.claude/mcp/...` 하나만 봤다. jm4 는 `~/.claude` 가 곧 prj3 repo 라
    파일이 있어 드러나지 않았지만, **소비자 머신의 `~/.claude` 는 플러그인 설치본**이라
    그 경로가 없다 — fg1 실측(2026-08-30)에서 hub 의 tick 타이머가 통째로 미기동했고,
    예약 큐가 자동으로 돈 적이 한 번도 없었다. tick 을 수동 실행할 때만 동작해서
    *"큐가 좀 늦네"* 로 보였다.
      (prj3#Issue460 이 훅 헬퍼에 쓴 처방과 같다 — 배포된 코드는 **자기가 놓인 자리**를
       기준으로 짝을 찾아야 한다. 홈 절대경로는 개발 머신에서만 맞는 가정이다.)

    우선순위: env(AOA_MQ_TICK) → repo 동거본 → 홈(~/.claude) → 빈 문자열(미기동).
    """
    env = os.environ.get("AOA_MQ_TICK")
    if env:
        return env
    for c in (os.path.join(REPO_ROOT, "mcp", "aoa-mq", "aoa-mq-tick.sh"),
              os.path.expanduser("~/.claude/mcp/aoa-mq/aoa-mq-tick.sh")):  # candidate
        if os.path.isfile(c):
            return c
    return os.path.expanduser("~/.claude/mcp/aoa-mq/aoa-mq-tick.sh")  # candidate(최종 폴백)


AOA_MQ_TICK = _resolve_aoa_mq_tick()
AOA_MQ_GATE_SEC = 3600


def _aoa_mq_tick_loop(interval: float = 300.0) -> None:
    """aoa-mq tick 주기 구동 (prj5 Issue37 F3-4).

    종전 구동 주체는 jmDashboard 의 페이지 리프레시였다 — 사람이 브라우저를 열어야 큐가
    도는 단일 장애점이었고, 자리를 비운 기간엔 예약·D-Day 가 통째로 밀렸다.
    상시 떠 있는 이 서버가 대신 구동한다.

    빈도 억제는 tick 의 `--gate` 가 공유 파일(.last-tick)로 판정한다. 여기서 5분마다
    깨우는 것은 게이트 경계를 촘촘히 넘기 위함이고, 실제 실행은 시간당 1회다.
    게이트 파일은 jmDashboard 경로로 실행된 tick 도 갱신하므로 prj57 을 수정하지 않고도
    두 구동자가 서로를 억제한다.

    fail-soft: 스크립트가 없거나 spawn 이 실패해도 서버 본체는 계속 돈다.
    """
    if not os.path.exists(AOA_MQ_TICK):
        log(f"[aoa-mq] tick script not found — 타이머 미기동: {AOA_MQ_TICK}")
        return
    log(f"[aoa-mq] tick timer started — wake={interval}s gate={AOA_MQ_GATE_SEC}s")
    while True:
        try:
            time.sleep(interval)
            subprocess.Popen(
                ["/bin/bash", AOA_MQ_TICK, "--gate", str(AOA_MQ_GATE_SEC)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,          # detached — 서버 종료가 tick 을 끊지 않는다
            )
        except Exception as e:
            log(f"[aoa-mq] tick spawn error: {e}")


def persist_pids() -> None:
    """Issue63: pids dict(runner PID 등록분)를 pids.json 에 atomic flush.
    종전 sessions 만 영속되고 pids 가 휘발 → 서버 재시작 시 복원 세션의 /control 이
    전부 'pid not registered' 403. pids 도 영속하여 종료 신호 처리를 복원한다."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with pids_lock:
            snap = {h: sorted(s) for h, s in pids.items() if s}
        tmp = PIDS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, PIDS_FILE)
    except Exception as e:
        log(f"persist_pids failed: {e}")


def load_pids() -> None:
    """Issue63: 재시작 시 pids.json 복원. 죽은 PID 는 로드 시점에 필터(zombie 차단)."""
    if not os.path.exists(PIDS_FILE):
        return
    try:
        with open(PIDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        restored = dropped = 0
        with pids_lock:
            for h, plist in (data or {}).items():
                alive = set()
                for p in plist:
                    try:
                        p = int(p)
                    except (TypeError, ValueError):
                        continue
                    if _pid_alive(p):
                        alive.add(p)
                    else:
                        dropped += 1
                if alive:
                    pids[h] = alive
                    restored += len(alive)
        log(f"restored {restored} pids from {PIDS_FILE} (dropped {dropped} dead)")
    except Exception as e:
        log(f"load_pids failed: {e}")


def _dash_runner_state(entry: dict):
    """Issue63: dashboard 세션 content(JSON 문자열)에서 runner pid 와 status 추출.
    반환 (pid|None, status|None). content_type != dashboard 또는 파싱 실패 시 (None, None).
    세션 liveness 를 runner 실제 생존에 종속시키기 위한 단일 파서."""
    if entry.get("content_type") != "dashboard":
        return None, None
    content = entry.get("content")
    if not isinstance(content, str) or not content:
        return None, None
    try:
        d = json.loads(content)
    except Exception:
        return None, None
    if not isinstance(d, dict):
        return None, None
    pid = d.get("pid")
    try:
        pid = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid = None
    status = d.get("status")
    return pid, (status if isinstance(status, str) else None)


def _session_runner_pids(h: str) -> set:
    """Issue64: cwd_hash h 의 dashboard 세션 data content 에 기록된 runner pid 집합.
    runner 는 매 iter 자기 pid 를 data content 에 써넣으므로, /register-pid(1회성 +
    pids.json 휘발 가능)보다 신뢰도 높은 authoritative 신호다. /control 의 등록
    게이트 fallback 으로 사용 — 레지스트리 누락 시에도 종료 신호 전달 보장."""
    found = set()
    with sessions_lock:
        snap = list(sessions.items())
    for (sh, _sid), entry in snap:
        if sh != h:
            continue
        d_pid, _ = _dash_runner_state(entry)
        if d_pid is not None:
            found.add(d_pid)
    return found


def determine_mode(content_type: str) -> str:
    """Issue17 Phase 1: 모드 판정 단일 진입점. Phase 1 은 'A' 만 실제 렌더."""
    if content_type == "form":
        return "B"
    if content_type == "dashboard":
        return "C"
    return "A"


# Issue30: validate_dashboard + DASH_WIDGET_TYPES → validators.py


def validate(cwd: str, token: str) -> bool:
    if not cwd or not token:
        return False
    h = cwd_hash(cwd)
    with projects_lock:
        p = projects.get(h)
    if not p:
        return False
    return hmac.compare_digest(p.get("token", ""), token)


def get_cwd_param(parsed) -> str:
    qs = parse_qs(parsed.query)
    raw = (qs.get("cwd") or [""])[0]
    return unquote(raw) if raw else ""


def get_token_param(parsed) -> str:
    qs = parse_qs(parsed.query)
    return (qs.get("token") or [""])[0]


def path_within_serve_roots(abs_path: str, cwd_real: str) -> bool:
    """/view·/data confinement: cwd 하위 또는 서버 소유 TMP_OUT_DIR flat 파일 허용.

    dashboard agent 가 htm 폴더 부재 시 dash/html 산출물을 TMP_OUT_DIR(/tmp/___pm)
    평면에 떨굼(Issue39). dash-registry 의 cwd 는 프로젝트 cwd 라 cwd-confinement
    만으로는 'path outside cwd' 403 발생. TMP_OUT_DIR flat 파일은 서버 소유
    namespace 이므로 예외 허용. subdir(claude-htm-server/inbox) 은 제외."""
    if abs_path == cwd_real or abs_path.startswith(cwd_real + os.sep):
        return True
    tmp_real = os.path.realpath(TMP_OUT_DIR)
    return os.path.dirname(abs_path) == tmp_real


# Issue393: /data·/view 가 cwd 하위 자격증명을 내주던 구멍.
#   확장자 allowlist(.json/.yaml/.yml)만으로는 부족했다 — cwd 가 `~/.claude` 인 등록에서
#   `~/.claude/.credentials.json`(Claude OAuth)이 "cwd 하위 + .json" 이라는 이유로 통과해
#   정상 토큰에 200 을 반환했다(2026-08-16 실측). 파일권한 0600 이 HTTP 로 우회된 것이다.
#   토큰은 cwd 단위 장수명 고정값(Issue392 판정)이라, 토큰 1건 유출이 곧 상위 자격증명
#   열람으로 사다리를 놓는다.
_SENSITIVE_BASENAMES = frozenset({"credentials.json", "id_rsa", "id_ed25519"})
_SENSITIVE_SUFFIXES = (".key", ".pem", ".p12", ".pfx")


def path_is_sensitive(abs_path: str) -> bool:
    """렌더·데이터 serve 가 읽으면 안 되는 파일인가.

    **dotfile 을 통째로 막는다** — 렌더가 dotfile 을 읽을 정당한 사유가 없고,
    자격증명 파일명을 일일이 열거하는 블랙리스트는 새 파일이 생길 때마다 뒤처진다.
    dotfile 차단이 1차이고 아래 이름·확장자 목록은 보조다.

    ⚠️ 판정 기준은 **basename** 이다. `<name>.dash.json`(dashboard 인라인 렌더)처럼
    이름 *안에* 점이 있는 것은 dotfile 이 아니므로 그대로 통과한다 — 실제 산출물이
    전부 이 형태라 기존 렌더는 영향받지 않는다.
    """
    base = os.path.basename(abs_path)
    if base.startswith("."):
        return True
    if base in _SENSITIVE_BASENAMES:
        return True
    return base.endswith(_SENSITIVE_SUFFIXES)


def sse_broadcast(cwd_h: str, event: str, data: dict, sid=None) -> int:
    """SSE push.
    Issue17 Phase 1: sid 인자 추가.
      - sid=None: 해당 cwd의 모든 채널(모든 sid + backward-compat 빈 sid) push
      - sid=<str>: (cwd_h, sid) 정확 채널만 push
    """
    msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
    sent = 0
    dead = []
    with sse_lock:
        if sid is None:
            targets = [(k, v) for k, v in sse_subscribers.items() if k[0] == cwd_h]
        else:
            targets = [((cwd_h, sid), sse_subscribers.get((cwd_h, sid), []))]
        for key, subs in targets:
            for wfile in subs:
                try:
                    wfile.write(msg)
                    wfile.flush()
                    sent += 1
                except Exception:
                    dead.append((key, wfile))
        for key, w in dead:
            subs = sse_subscribers.get(key, [])
            if w in subs:
                subs.remove(w)
    return sent


class Handler(BaseHTTPRequestHandler):
    server_version = "PmHTMServer/1.0"

    def log_message(self, fmt, *args):
        pass

    def _acao(self) -> str:
        # 요청 Origin 을 반향: file://(Origin: null)·host-1.local·127.0.0.1 모두 매칭.
        # 과거 "null" 하드코딩은 host-1.local:9876 로 페이지를 열면 origin 불일치 →
        # 브라우저 CORS 차단("Failed to fetch") 유발 (Simple Browser/htm-doc 경로).
        return self.headers.get("Origin") or "null"

    def _send_json(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", self._acao())
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _deny_ip(self):
        """source-IP 게이트 거부 응답. Issue332: allowlist 적재 미완이면 '차단'이 아니라
        '준비 중' 이므로 403 대신 503 + Retry-After 로 응답 — 오진(차단당했다) 차단."""
        if not ALLOWLIST_READY:
            payload = json.dumps({"error": "allowlist not ready", "retry_after": 2},
                                 ensure_ascii=False).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Retry-After", "2")
            self.send_header("Access-Control-Allow-Origin", self._acao())
            self.end_headers()
            self.wfile.write(payload)
            return
        self._send_json(403, {"error": "ip not allowed"})

    def _host_gate(self) -> bool:
        """Issue379: 수신 이름 게이트. 통과=True, 거부 시 421 응답까지 마치고 False.
        421 Misdirected Request = "이 서버는 그 이름에 대한 권한이 없다"(RFC 7540 9.1.2)."""
        ip = self.client_address[0] if self.client_address else ""
        if _host_allowed(self.headers.get("Host", ""), ip):
            return True
        self._send_json(421, {"error": "host not allowed"})
        return False

    def do_OPTIONS(self):
        # Issue379: preflight 도 게이트 대상 — 여기서 막으면 브라우저가 본 요청을 아예 안 보낸다.
        if not self._host_gate():
            return
        self._send_json(204, {})

    def do_GET(self):
        # Issue141: 전역 source-IP 게이트. 기본(127.0.0.1 bind)에선 루프백만 도달 →
        # 항상 통과. 개방 모드(HTM_SERVER_HOST)에선 비-allowlist IP 를 여기서 차단
        # → 토큰 노출 GET(/boards, /hub)·SSE 까지 일괄 보호.
        if not _ip_allowed(self.client_address[0] if self.client_address else ""):
            self._deny_ip()
            return
        # Issue379: 수신 이름 게이트(위 게이트의 짝). src 가 루프백인 DNS rebinding 은
        # _ip_allowed 를 통과하므로 여기서 이름으로 막는다.
        if not self._host_gate():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            # Issue213: hub-internal 모드면 쉘(/hub-shell)로, 아니면 종전 /hub 로.
            #   standalone /hub 진입은 _handle_hub guard 가 어차피 쉘로 302 하지만,
            #   루트는 여기서 직접 분기해 불필요한 더블 302 를 줄인다.
            dest = "/hub-shell" if _load_hub_setting().get("render_tab_mode") == "hub-internal" else "/hub"
            self.send_response(302)
            self.send_header("Location", dest)
            self.end_headers()
            return
        # Issue182: fPm 프로젝트 아이콘 서빙 (favicon + 헤더 브랜딩 공용)
        # Issue253: 배지 서버(Servers.md 이모지 등록)는 이모지 SVG 서빙 — favicon·문서
        #   헤더 hub-link 가 전부 이 경로를 참조하므로 단일 지점에서 서버 아이콘으로 전환.
        #   브라우저는 확장자가 아닌 Content-Type 으로 렌더하므로 .png 경로에 SVG 허용.
        # Issue327: 에디터 아이콘 — /editor-icon/<vscode|zed>.png.
        #   앱 번들 .icns 에서 런타임 추출·캐시(타사 로고 repo 미커밋). 없으면 404 → JS 가 emoji 폴백.
        if parsed.path.startswith("/editor-icon/"):
            name = os.path.basename(parsed.path)[:-4] if parsed.path.endswith(".png") else ""
            icon = _editor_icon_file(name)
            if not icon:
                self._send_json(404, {"error": "icon unavailable"})
                return
            try:
                data = open(icon, "rb").read()
            except OSError:
                self._send_json(404, {"error": "icon unreadable"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/fpm-icon.png":
            _emoji, _hue, _sname = _self_server_badge()
            if _emoji:
                svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                       '<text x="50" y="54" font-size="82" text-anchor="middle"'
                       ' dominant-baseline="central">%s</text></svg>' % _emoji)
                data = svg.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(data)
                return
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fpm-icon.png")
            try:
                with open(icon_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                self._send_json(404, {"error": "icon not found"})
            return
        # Issue228: vendored QR 라이브러리 서빙 (오프라인 — 런타임 외부 의존 0)
        if parsed.path == "/assets/qrcode.min.js":
            js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "qrcode.min.js")
            try:
                with open(js_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                self._send_json(404, {"error": "asset not found"})
            return
        # Issue228: 모바일 접속 QR 페이지 (반응형). LAN 접속 URL 의 QR 을 vendored JS 로 렌더.
        if parsed.path == "/qr":
            self._handle_qr(parsed)
            return
        if parsed.path == "/healthz":
            with projects_lock:
                pc = len(projects)
            with pids_lock:
                rp = sum(len(s) for s in pids.values())
            # Issue425: `advertise_url` — 이 hub 를 **외부 기기에서 열 수 있는 주소**.
            #   소비자(daily-digest 등)가 링크를 만들 때 호스트를 하드코딩하지 않게 한다.
            #   hub 가 자기 공개 주소를 아는 유일한 주체다 — 설정 파일 경로는 머신마다
            #   다르고(jm4 `___pm/data/`, fg1 `fpm/data/`), 소비자가 그걸 찾아 헤매면
            #   머신마다 다른 코드가 생긴다.
            #   ⚠️ `advertise_host` 미설정이면 **null 이다** — 빈 문자열이나 localhost 로
            #   때우지 않는다. fg1 이 실제로 미설정 + `bind_host: 127.0.0.1`(루프백 전용)
            #   이라, 여기서 그럴듯한 값을 지어내면 **열리지 않는 링크를 폰으로 보낸다**.
            #   null 을 받은 소비자는 링크 대신 로컬 안내로 폴백해야 한다.
            _adv = str((_load_hub_setting() or {}).get("advertise_host") or "").strip()
            self._send_json(200, {
                "status": "ok",
                "pid": os.getpid(),
                "port": PORT,
                "uptime": int(time.time() - start_ts),
                "projects": pc,
                "registered_pids": rp,
                "advertise_host": _adv or None,
                "advertise_url": ("http://%s:%d" % (_adv, PORT)) if _adv else None,
            })
            return
        if parsed.path == "/ob":
            self._handle_ob_open(parsed)
            return
        if parsed.path == "/events":
            self._handle_sse(parsed)
            return
        if parsed.path == "/data":
            self._handle_data(parsed)
            return
        if parsed.path == "/view":
            self._handle_view(parsed)
            return
        if parsed.path == "/htm-doc":
            self._handle_htm_doc(parsed)
            return
        if parsed.path == "/md-doc":
            self._handle_md_doc(parsed)
            return
        # Issue356_1: 훅이 라이브 뷰 URL 을 조립하기 위한 조회 진입점
        if parsed.path == "/live-url":
            self._handle_live_url(parsed)
            return
        # Issue255: htm 문서 상대 리소스(이미지) serve
        if parsed.path == "/htm-res":
            self._handle_htm_res(parsed)
            return
        # Issue284: 프로젝트 이슈맵(Issue_map.htm) serve — cwd 로 서버측 경로 재계산
        if parsed.path == "/issue-map":
            self._handle_issue_map(parsed)
            return
        # Issue293: 프로젝트 트리 맵(Projects_map.htm) serve — 경로는 REPO_ROOT 고정
        if parsed.path == "/projects-map":
            self._handle_projects_map(parsed)
            return
        # Issue402: 핀봇 조직도 — 파일 산출물 없이 registry.db 직독 실시간 생성
        if parsed.path == "/fbot-map":
            self._handle_fbot_map(parsed)
            return
        # Issue294: 맵 노드 클릭 → VSCode 열기 브리지 (GET, prj 번호만 받음)
        if parsed.path == "/open-prj":
            self._handle_open_prj(parsed)
            return
        if parsed.path == "/boards":
            self._handle_dashboards(parsed)
            return
        if parsed.path == "/api/file-stat":
            self._handle_file_stat(parsed)
            return
        if parsed.path == "/api/settings":
            self._handle_get_settings(parsed)
            return
        if parsed.path == "/api/i18n":
            # Issue169 Stage8: 클라이언트 JS i18n 사전 (lang= 쿼리, en merge)
            qs = parse_qs(parsed.query or "")
            lang = i18n.norm_lang((qs.get("lang") or [""])[0])
            self._send_json(200, {"lang": lang, "dict": i18n.merged(lang)})
            return
        if parsed.path == "/hub":
            self._handle_hub(parsed)
            return
        # Issue194: hub 내부 탭 쉘 + 전용 SSE 채널
        if parsed.path == "/hub-shell":
            self._handle_hub_shell(parsed)
            return
        if parsed.path == "/hub-events":
            self._handle_hub_events(parsed)
            return
        if parsed.path == "/projects-list":
            self._send_json(200, {"projects": _projects_list_with_htm()})
            return
        # Issue420: aoa-mq 전용 관리 페이지 + 데이터
        if parsed.path == "/mq":
            self._handle_mq_page(parsed)
            return
        if parsed.path == "/mq-data":
            self._send_json(200, _mq_collect())
            return
        # Issue66: GET /issue?prj=N&id=M — Issue.md 섹션 html 반환
        if parsed.path == "/issue":
            self._handle_issue(parsed)
            return
        # Issue17 Phase 1: /s/{cwd_hash}/{sid}[/data]
        if parsed.path.startswith("/s/"):
            self._handle_session_get(parsed)
            return
        # Issue29 Phase 6: /preview/{cwd_hash}/{pid}[/data]
        if parsed.path.startswith("/preview/"):
            self._handle_preview_get(parsed)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        # Issue141: 전역 source-IP 게이트 (do_GET 대칭).
        if not _ip_allowed(self.client_address[0] if self.client_address else ""):
            self._deny_ip()
            return
        # Issue379: 수신 이름 게이트 (do_GET 대칭). 쓰기 API 가 rebinding 의 실제 표적이다.
        if not self._host_gate():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/register":
            self._handle_register(parsed)
            return
        if parsed.path == "/register-pid":
            self._handle_register_pid(parsed)
            return
        if parsed.path == "/control":
            self._handle_control(parsed)
            return
        if parsed.path == "/answer":
            self._handle_answer(parsed)
            return
        # Issue420: aoa-mq 처리 접수 (inbox 계약 재사용 — tick 이 소비)
        if parsed.path == "/mq-ack":
            self._handle_mq_ack(parsed)
            return
        if parsed.path == "/notify":
            self._handle_notify(parsed)
            return
        if parsed.path == "/clear-done":
            self._handle_clear_done(parsed)
            return
        # Issue394: 프로젝트 토큰 회전 (유출 의심 시 즉시 무효화)
        if parsed.path == "/token-rotate":
            self._handle_token_rotate(parsed)
            return
        if parsed.path == "/kill-empty-live":
            self._handle_kill_empty_live(parsed)
            return
        # Issue331: zed orphan 리퍼 수동 트리거 (주기 스레드와 동일 판정)
        if parsed.path == "/reap-orphan-live":
            self._handle_reap_orphan_live(parsed)
            return
        if parsed.path == "/clear-htm-docs":
            self._handle_clear_htm_docs(parsed)
            return
        if parsed.path == "/unregister-doc":
            self._handle_unregister_doc(parsed)
            return
        # Issue41: hub registry — 생산자 등록 / 수동 디스크 재스캔
        if parsed.path == "/register-doc":
            self._handle_register_doc(parsed)
            return
        # Issue194: hub 쉘 단일 창 리스 인계
        if parsed.path == "/hub-claim":
            self._handle_hub_claim(parsed)
            return
        if parsed.path == "/hub-rescan":
            self._handle_hub_rescan(parsed)
            return
        # Issue42: hub 활동 피드 — hook 이벤트 수신 / 프로젝트 VSCode 열기
        if parsed.path == "/hook-event":
            self._handle_hook_event(parsed)
            return
        if parsed.path == "/feed-clear":
            self._handle_feed_clear(parsed)
            return
        if parsed.path == "/open-project":
            self._handle_open_project(parsed)
            return
        if parsed.path == "/open-session":
            self._handle_open_session(parsed)
            return
        if parsed.path == "/open-simple-browser":
            self._handle_open_simple_browser(parsed)
            return
        if parsed.path == "/htm-toggle":
            self._handle_htm_toggle(parsed)
            return
        if parsed.path == "/htm-toggle-all":
            self._handle_htm_toggle_all(parsed)
            return
        if parsed.path == "/open-projects-md":
            self._handle_open_projects_md(parsed)
            return
        # Issue398: projects-map note 박스 인라인 편집 저장
        if parsed.path == "/projects-map/note":
            self._handle_projects_map_note(parsed)
            return
        if parsed.path == "/open-settings-yml":
            self._handle_open_settings_yml(parsed)
            return
        if parsed.path == "/api/settings":
            self._handle_post_settings(parsed)
            return
        # Issue17 Phase 1
        if parsed.path == "/session/register":
            self._handle_session_register(parsed)
            return
        if parsed.path == "/session/update":
            self._handle_session_update(parsed)
            return
        # Issue29 Phase 6: preview endpoint (validate-only, no persist/broadcast)
        if parsed.path == "/session/preview":
            self._handle_session_preview(parsed)
            return
        # Issue132: live 카드 수동 dismiss (프로세스 kill 아님 — sessions entry 만 제거)
        if parsed.path == "/session/dismiss":
            self._handle_session_dismiss(parsed)
            return
        # Issue18 Phase 2: /s/{cwd_hash}/{sid}/answer
        if parsed.path.startswith("/s/") and parsed.path.endswith("/answer"):
            self._handle_session_answer(parsed)
            return
        # Issue24 Phase 3: /s/{cwd_hash}/{sid}/action (widget notify action inbox)
        if parsed.path.startswith("/s/") and parsed.path.endswith("/action"):
            self._handle_session_action(parsed)
            return
        # Issue356_1: /s/{cwd_hash}/{sid}/degrade — 라이브 탭 열화 강등 통보
        if parsed.path.startswith("/s/") and parsed.path.endswith("/degrade"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 4:
                cwd_h, sid_raw = parts[1], parts[2]
                sid = "".join(c for c in sid_raw if c.isalnum() or c in "-_")
                with projects_lock:
                    p = projects.get(cwd_h)
                token = get_token_param(parsed)
                if (p and sid == sid_raw and token
                        and hmac.compare_digest(p.get("token", ""), token)):
                    self._handle_session_degrade(parsed, cwd_h, sid)
                    return
            self._send_json(401, {"error": "invalid session or token"})
            return
        self._send_json(404, {"error": "not found"})

    def _handle_register(self, parsed):
        cwd = get_cwd_param(parsed)
        if not cwd or not os.path.isabs(cwd):
            self._send_json(400, {"error": "missing or non-absolute cwd"})
            return
        h = cwd_hash(cwd)
        meta = project_meta(cwd)
        inbox = f"{INBOX_ROOT}/{h}"
        os.makedirs(inbox, exist_ok=True)
        with projects_lock:
            existing = projects.get(h)
            if existing and existing.get("cwd") == cwd:
                token = existing["token"]
                new = False
            else:
                token = uuid.uuid4().hex
                projects[h] = {
                    "cwd": cwd,
                    "token": token,
                    "name": meta["name"],
                    "color": meta["color"],
                    "registered_at": time.time(),
                }
                new = True
        if new:
            persist_tokens()
            log(f"POST /register — new project '{meta['name']}' (hash={h}, cwd={cwd})")
        return self._send_json(200, {
            "cwd_hash": h,
            "token": token,
            "inbox": inbox,
            "name": meta["name"],
            "color": meta["color"],
            "port": PORT,
            "new": new,
        })

    def _handle_token_rotate(self, parsed):
        """Issue394: 프로젝트 토큰 회전. `?cwd=<abs>` 1건, `?all=1` 전량.

        토큰은 `cwd` 단위 장수명 고정값이라(Issue392 판정) **무효화 수단이 없었다** —
        유일한 방법이 `/hub reset`(전량 wipe + 재기동)이었고, 그건 SSE·dashboard 를
        전부 끊는다. 회전 하나 하자고 서버를 내리게 만들면 아무도 회전하지 않는다.

        여기서는 메모리 엔트리만 지우고 flush 한다 — 다음 `POST /register` 가 새 uuid 를
        민팅하므로 **재기동이 필요 없다**. 비용은 그 프로젝트의 열린 탭이 401 이 되는 것뿐이고,
        다시 렌더하면 복구된다.

        127.0.0.1 trust — 구 토큰을 인증에 요구하지 않는다. 요구하면 *"토큰을 잃어버렸다·
        유출됐다"* 는 정작 필요한 상황에서 못 쓴다(자물쇠를 여는 데 잃어버린 열쇠를 요구하는 꼴).
        `/clear-done`·`/feed-clear` 와 같은 등급이다."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        qs = parse_qs(parsed.query)
        rotate_all = (qs.get("all", ["0"])[0] or "0").lower() in ("1", "true", "yes")
        cwd = get_cwd_param(parsed)
        if not rotate_all and (not cwd or not os.path.isabs(cwd)):
            self._send_json(400, {"error": "missing or non-absolute cwd (or pass all=1)"})
            return
        with projects_lock:
            if rotate_all:
                targets = list(projects.keys())
            else:
                h = cwd_hash(cwd)
                p = projects.get(h)
                targets = [h] if p and p.get("cwd") == cwd else []
            rotated = [{"cwd_hash": t, "cwd": projects[t].get("cwd"),
                        "name": projects[t].get("name")} for t in targets]
            for t in targets:
                del projects[t]
        persist_tokens()
        log(f"POST /token-rotate — invalidated {len(rotated)} project token(s) "
            f"(all={rotate_all}); next /register mints fresh")
        self._send_json(200, {
            "status": "ok",
            "rotated_count": len(rotated),
            "rotated": rotated,
            "note": "다음 /register 가 새 토큰을 발급한다. 열려 있던 탭은 401 — 다시 렌더하면 복구.",
        })

    def _handle_answer(self, parsed):
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            log(f"POST /answer — auth fail (cwd={cwd[:60]}...)")
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        # Issue66: sid param — sid 지정 시 {INBOX_ROOT}/{cwd_hash}/{sid}/ 에 격리 저장.
        # sid 미지정 시 기존 경로({INBOX_ROOT}/{cwd_hash}/) — backward-compat 필수.
        qs = parse_qs(parsed.query or "")
        sid_vals = qs.get("sid", [])
        sid = sid_vals[0].strip() if sid_vals else ""
        if sid and not re.fullmatch(r"[a-zA-Z0-9_-]+", sid):
            self._send_json(400, {"error": "sid must be alphanumeric with - or _ only"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > 1024 * 1024:
            self._send_json(400, {"error": "invalid content length"})
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        h = cwd_hash(cwd)
        # sid 지정 시 하위 폴더 격리, 미지정 시 기존 경로 (backward-compat)
        inbox = f"{INBOX_ROOT}/{h}/{sid}" if sid else f"{INBOX_ROOT}/{h}"
        os.makedirs(inbox, exist_ok=True)
        ts = int(time.time() * 1000)
        out_path = f"{inbox}/{ts}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        log(f"POST /answer — saved {out_path}")
        # B모드 응답 성공 표시 — 해당 cwd 의 최신 미응답 ask htm 엔트리를 answered 로 마킹.
        # 카드는 파일명 unixtime(claude-htm-ask-<ts>) 으로 최신 폼을 식별한다.
        try:
            with registry_lock:
                entries = load_registry(HTM_REGISTRY)
                cand, cand_ts = None, -1
                for ent in entries:
                    if ent.get("cwd", "") != cwd or ent.get("answered"):
                        continue
                    m = re.search(r"claude-htm-ask-(\d+)",
                                  os.path.basename(ent.get("path", "")))
                    if not m:
                        continue
                    if int(m.group(1)) > cand_ts:
                        cand, cand_ts = ent, int(m.group(1))
                if cand is not None:
                    cand["answered"] = True
                    cand["answered_at"] = int(time.time())
                    save_registry(HTM_REGISTRY, entries)
                    log(f"POST /answer — marked answered: {cand.get('path')}")
        except Exception as ex:
            log(f"POST /answer — answered-mark failed: {ex}")
        self._send_json(200, {"status": "saved", "path": out_path})

    def _handle_notify(self, parsed):
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 64 * 1024:
            self._send_json(400, {"error": "payload too large"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            body = {}
        h = cwd_hash(cwd)
        sent = sse_broadcast(h, "reload", body)
        log(f"POST /notify — broadcast (hash={h}, file={body.get('file', body.get('path', '?'))}, clients={sent})")
        # Issue254: dash 산출물 auto-register — 생산자(runner)가 /register-doc 를 호출하지
        #   않는 사각(dash 는 htm 과 달리 자동 등록 경로 전무) 보강. notify 는 data 갱신마다
        #   발화하므로 이미 등록된 path 는 skip(매회 registry 재기록 금지).
        nfile = (body.get("file") or body.get("path") or "").strip()
        if nfile.endswith((".dash.yaml", ".dash.yml", ".dash.json")):
            self._auto_register_dash(cwd, nfile)
        self._send_json(200, {"status": "broadcast", "clients": sent})

    def _auto_register_dash(self, cwd: str, file_path: str):
        """Issue254: /notify 경유 dash 파일을 dash-registry 에 자동 등록.

        - 이미 등록된 path → no-op (notify heartbeat 마다 registry 재기록 방지)
        - DASH_CLEARED tombstone path → no-op (Issue54 의미 보존 — 자동 경로는 clear 를
          부활시키지 않는다. 해제는 생산자의 명시 /register-doc 전용)
        - serve-root confinement 는 /register-doc dash 분기와 동일 기준 (밖이면 skip —
          notify 본 기능(broadcast)은 이미 수행됐으므로 fail-soft)"""
        if not file_path.startswith("/"):
            file_path = os.path.join(cwd, file_path)
        path_real = os.path.realpath(os.path.expanduser(file_path))
        if not os.path.isfile(path_real):
            return
        if not path_within_serve_roots(path_real, os.path.realpath(cwd)):
            log(f"notify dash auto-register skip — outside serve-root: {path_real}")
            return
        with registry_lock:
            entries = load_registry(DASH_REGISTRY)
            if any(e.get("path") == path_real for e in entries):
                return
            if path_real in set(load_registry(DASH_CLEARED)):
                return
            meta = self._read_dash_file(path_real) or {}
            entries.append({
                "path": path_real, "cwd": cwd,
                "title": meta.get("title") or "",
                "registered_at": time.time(),
            })
            save_registry(DASH_REGISTRY, entries)
        log(f"notify dash auto-register — path={path_real} (registry={len(entries)})")

    def _read_dash_file(self, abs_path: str):
        """Issue41: 등록된 단일 dash 파일을 읽어 메타(mtime/title/status/progress/pid) 추출.
        파일 부재·접근 불가 시 None. 디렉토리 스캔 없이 등록 경로 1건만 접근.
        Issue45: mtime 불변 시 캐시된 파싱 결과 복사본 반환 (재read·재parse 생략)."""
        try:
            st = os.stat(abs_path)
        except OSError:
            return None
        cached = doc_cache_get(abs_path, st.st_mtime)
        if cached is not None:
            return dict(cached)  # 호출측이 path_display/view_url 등 mutate → 복사본 반환
        entry = {
            "path": abs_path,
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            "mtime_ts": st.st_mtime,
            "title": None, "status": None, "progress": None, "pid": None, "worker_pid": None,
            # Issue403: runner 갱신 주기(초). 부재면 None → 기존 grace 상수 준용.
            "interval": None,
        }
        try:
            with open(abs_path, encoding="utf-8") as f:
                raw = f.read()
            if abs_path.endswith(".dash.json"):
                self._fill_dash_entry_from_dict(entry, json.loads(raw))
            else:
                parsed = self._parse_dash_yaml(raw)
                for k in ("title", "status", "pid", "worker_pid", "progress", "interval"):
                    if parsed.get(k) is not None:
                        entry[k] = parsed[k]
        except Exception as e:
            log(f"read_dash_file parse fail {abs_path}: {e}")
        doc_cache_put(abs_path, st.st_mtime, dict(entry))
        return entry

    def _scan_dashes(self, cwd: str) -> list:
        """Issue16_7 / Issue31: cwd 하위 htm 폴더에서 *.dash.{json,yaml,yml} 스캔.
        Issue41: 자동 hub 갱신 경로에서 제거됨 — /hub-rescan(수동 부트스트랩) 전용.
        Issue289: 단일 z_htm 대신 HTM_DIRS 전체를 훑는다(활성→아카이브→legacy).
        yaml 은 stdlib 미지원이므로 dashboard.md 양식 한정 경량 파서 사용 (Issue31 (a))."""
        results = []
        pairs = []
        for htm_dir in _htm_dirs_for(cwd):
            if not os.path.isdir(htm_dir):
                continue
            try:
                names = sorted(os.listdir(htm_dir))
            except OSError:
                continue
            pairs.extend((htm_dir, n) for n in names)
        seen_names = set()
        for htm_dir, name in pairs:
            if not (name.endswith(".dash.json") or name.endswith(".dash.yaml") or name.endswith(".dash.yml")):
                continue
            if name in seen_names:  # 같은 파일명이 여러 경로에 있으면 우선순위 앞선 것만
                continue
            seen_names.add(name)
            abs_path = os.path.join(htm_dir, name)
            try:
                st = os.stat(abs_path)
            except OSError:
                continue
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            entry = {"path": abs_path, "mtime": mtime, "title": None, "status": None, "progress": None, "pid": None, "worker_pid": None, "interval": None}
            try:
                with open(abs_path, encoding="utf-8") as f:
                    raw = f.read()
                if name.endswith(".dash.json"):
                    parsed = json.loads(raw)
                    self._fill_dash_entry_from_dict(entry, parsed)
                else:
                    parsed = self._parse_dash_yaml(raw)
                    # _parse_dash_yaml 은 이미 entry 와 동일 키 dict 반환
                    for k in ("title", "status", "pid", "worker_pid", "progress", "interval"):
                        if parsed.get(k) is not None:
                            entry[k] = parsed[k]
            except Exception as e:
                log(f"scan_dashes parse fail {abs_path}: {e}")
            results.append(entry)
        return results

    def _scan_tmp_dashes(self) -> list:
        """Issue39: `/tmp/___pm/*.dash.{json,yaml,yml}` 평면 스캔 (dashboard agent OUT_DIR=/tmp/___pm fallback 케이스).

        cwd 매핑 정보 없음 → 가상 프로젝트 카드로 hub 에 노출. view_url/stop 비활성 (token 없음)."""
        results = []
        tmp_dir = "/tmp/___pm"
        if not os.path.isdir(tmp_dir):
            return results
        try:
            entries = sorted(os.listdir(tmp_dir))
        except OSError:
            return results
        for name in entries:
            if not (name.endswith(".dash.json") or name.endswith(".dash.yaml") or name.endswith(".dash.yml")):
                continue
            abs_path = os.path.join(tmp_dir, name)
            if not os.path.isfile(abs_path):
                continue
            try:
                st = os.stat(abs_path)
            except OSError:
                continue
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            entry = {"path": abs_path, "mtime": mtime, "title": None, "status": None, "progress": None, "pid": None, "worker_pid": None, "interval": None}
            try:
                with open(abs_path, encoding="utf-8") as f:
                    raw = f.read()
                if name.endswith(".dash.json"):
                    self._fill_dash_entry_from_dict(entry, json.loads(raw))
                else:
                    parsed = self._parse_dash_yaml(raw)
                    for k in ("title", "status", "pid", "worker_pid", "progress", "interval"):
                        if parsed.get(k) is not None:
                            entry[k] = parsed[k]
            except Exception as e:
                log(f"scan_tmp_dashes parse fail {abs_path}: {e}")
            results.append(entry)
        return results

    @staticmethod
    def _extract_html_title(abs_path: str) -> str:
        """Issue40: HTML head(앞 8KB)에서 <title> 텍스트 추출. 실패 시 빈 문자열.
        Issue353_1: `.md` 는 frontmatter `title:`/`name:` → 첫 헤딩 순으로 추출."""
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                head = f.read(8192)
        except OSError:
            return ""
        if abs_path.endswith(".md"):
            m = re.match(r"(?s)\A---\n(.*?)\n---", head)
            if m:
                fm = re.search(r'(?m)^(?:title|name):\s*["\']?([^"\'\n]+)', m.group(1))
                if fm:
                    return fm.group(1).strip()
            h = re.search(r"(?m)^#{1,6}\s+(.+)$", head)
            return h.group(1).strip() if h else ""
        low = head.lower()
        i = low.find("<title>")
        if i < 0:
            return ""
        j = low.find("</title>", i)
        if j < 0:
            return ""
        return head[i + len("<title>"):j].strip()

    @staticmethod
    def _extract_html_summary(abs_path: str) -> str:
        """Issue70: HTML <body> 앞부분에서 script/style/태그를 제거한 첫 텍스트 발췌.
        htm-doc 카드 본문 2줄 요약용. 실패 시 빈 문자열.
        Issue353_1: `.md` 는 frontmatter·헤딩·코드펜스 라인을 제외한 첫 본문 발췌."""
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                data = f.read(16384)
        except OSError:
            return ""
        if abs_path.endswith(".md"):
            body = re.sub(r"(?s)\A---\n.*?\n---\n?", "", data)
            lines = []
            for ln in body.splitlines():
                t = ln.strip()
                if not t or t.startswith(("#", "```", "---", "|", ">")):
                    continue
                lines.append(re.sub(r"[*`_\[\]()]", "", t))
                if sum(len(x) for x in lines) > 200:
                    break
            return " ".join(lines)[:200]
        low = data.lower()
        bi = low.find("<body")
        if bi >= 0:
            gt = data.find(">", bi)
            body = data[gt + 1:] if gt >= 0 else data[bi:]
        else:
            body = data
        # script/style/head/header 블록 통째 제거 후 잔여 태그 제거
        body = re.sub(r"(?is)<(script|style|head|header)\b[^>]*>.*?</\1>", " ", body)
        text = re.sub(r"(?s)<[^>]+>", " ", body)
        for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                        ("&gt;", ">"), ("&#39;", "'"), ("&quot;", '"')):
            text = text.replace(ent, ch)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:200]

    @staticmethod
    def _extract_html_sid(abs_path: str) -> str:
        """Issue169: htm 문서를 만든 세션 sid 추출. canonical 헤더의 세션 링크
        onclick(`sid:'<sid>'`) 또는 vscode URI(`open?session=<sid>`)에서 발췌.
        hub 카드 '🆚 세션' 버튼이 /open-session 으로 그 세션 탭을 포커스하게 함.
        전역 hook(register-doc) 의존 없이 파일 자체에서 회수. 실패 시 빈 문자열.
        Issue353_1: `.md` 는 frontmatter `sid:` 에서 회수(md 셸이 헤더 🆚 버튼 생성)."""
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                data = f.read(65536)
        except OSError:
            return ""
        if abs_path.endswith(".md"):
            fm = re.match(r"(?s)\A---\n(.*?)\n---", data)
            if fm:
                ms = re.search(r'(?m)^sid:\s*["\']?([A-Za-z0-9_-]{1,128})',
                               fm.group(1))
                if ms:
                    return ms.group(1)
            return ""
        m = re.search(r"sid:'([A-Za-z0-9_-]{1,128})'", data)
        if not m:
            m = re.search(r"open\?session=([A-Za-z0-9_-]{1,128})", data)
        return m.group(1) if m else ""

    def _scan_htm_docs_in(self, directory: str, skip: set = None,
                          limit: int = 0) -> list:
        """Issue40: directory 에서 htm 스킬 단발 출력(구 claude-htm-*.html / 현행
        hub_htm_*.htm, Issue311) 스캔. 동반 .dash.{json,yaml,yml} 형제가 있는 파일은
        dashboard 산출물 → 제외.
        Issue55: skip set 의 path 는 후보에서 제외 — title 추출(파일 열람) 비용 회피.
        limit>0 이면 파일명 내 unixtime 최신순 N개만 stat+title 추출 (search_limit)."""
        results = []
        if not os.path.isdir(directory):
            return results
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            return results
        entry_set = set(entries)
        skip = skip or set()
        candidates = []
        for name in entries:
            stem = _htm_output_stem(name)
            if not stem:
                continue
            if any(f"{stem}.dash.{ext}" in entry_set for ext in ("json", "yaml", "yml")):
                continue
            abs_path = os.path.join(directory, name)
            if abs_path in skip:  # Issue55: tombstone — 재등록·title 추출 모두 skip
                continue
            candidates.append((name, abs_path))
        # Issue55: search_limit — 파일명 unixtime 최신 N개만 처리.
        # htm 누적 시 전수 stat + _extract_html_title(파일 열람) 폭주를 차단.
        if limit > 0 and len(candidates) > limit:
            def _name_ts(fname):
                m = re.search(r"(\d+)\.html$", fname)
                return int(m.group(1)) if m else 0
            candidates.sort(key=lambda c: _name_ts(c[0]), reverse=True)
            candidates = candidates[:limit]
        for name, abs_path in candidates:
            if not os.path.isfile(abs_path):
                continue
            try:
                st = os.stat(abs_path)
            except OSError:
                continue
            results.append({
                "path": abs_path,
                "name": name,
                "title": self._extract_html_title(abs_path) or name,
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                "mtime_ts": st.st_mtime,
            })
        return results

    def _scan_htm_docs(self, cwd: str, skip: set = None, limit: int = 0) -> list:
        """Issue40: 프로젝트 cwd 하위 htm 폴더의 htm 단발 출력 스캔.
        Issue289: HTM_DIRS 전체(활성→아카이브→legacy)를 훑고 파일명 기준 dedup —
        같은 문서가 이동 중 두 곳에 보여도 우선순위 앞선 경로 하나만 노출한다."""
        results, seen = [], set()
        for htm_dir in _htm_dirs_for(cwd):
            for item in self._scan_htm_docs_in(htm_dir, skip, limit):
                if item["name"] in seen:
                    continue
                seen.add(item["name"])
                results.append(item)
        return results

    def _scan_tmp_htm_docs(self, skip: set = None, limit: int = 0) -> list:
        """Issue40: /tmp/___pm 평면 htm 출력 스캔 (htm 폴더 부재 시 fallback 경로)."""
        return self._scan_htm_docs_in("/tmp/___pm", skip, limit)

    def _all_disk_htm_paths(self) -> set:
        """Issue92: clear tombstone 용 — 등록 프로젝트 htm 폴더(Issue289: HTM_DIRS 전체) + /tmp/___pm 의
        htm 단발 출력(구 claude-htm-*.html / 현행 hub_htm_*.htm, Issue311) 절대경로
        전수(set). title 추출 없이 path 만 수집
        (dash 동반 .html 제외). _scan_htm_docs_in 과 동일 후보 규칙이나
        파일 열람·limit 없이 경로만 — clear 가 디스크에 권위적이도록.
        registry 미등록 orphan(register-doc 실패분·구버전 파일)도 포함되어
        clear 후 rescan/autoheal 부활을 원천 차단한다."""
        dirs = []
        with projects_lock:
            for p in projects.values():
                cwd = p.get("cwd", "")
                if cwd:
                    dirs.extend(_htm_dirs_for(cwd))
        dirs.append(TMP_OUT_DIR)
        out = set()
        for d in dirs:
            if not os.path.isdir(d):
                continue
            try:
                names = set(os.listdir(d))
            except OSError:
                continue
            for name in names:
                stem = _htm_output_stem(name)
                if not stem:
                    continue
                if any(f"{stem}.dash.{ext}" in names
                       for ext in ("json", "yaml", "yml")):
                    continue
                out.add(os.path.join(d, name))
        return out

    def _all_disk_dash_paths(self) -> set:
        """Issue95: clear tombstone용 — 등록 프로젝트 htm 폴더(Issue289: HTM_DIRS 전체) + /tmp/___pm의
        *.dash.{json,yaml,yml} 절대경로 전수(set). path만 수집(파일 열람 없음) —
        clear가 디스크에 권위적이도록. registry 미등록 orphan도 포함하여
        clear 후 rescan 부활을 원천 차단한다."""
        dirs = []
        with projects_lock:
            for p in projects.values():
                cwd = p.get("cwd", "")
                if cwd:
                    dirs.extend(_htm_dirs_for(cwd))
        dirs.append(TMP_OUT_DIR)
        out = set()
        for d in dirs:
            if not os.path.isdir(d):
                continue
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for name in names:
                if (name.endswith(".dash.json") or
                        name.endswith(".dash.yaml") or
                        name.endswith(".dash.yml")):
                    out.add(os.path.join(d, name))
        return out

    def _collect_htm_docs(self) -> list:
        """Issue40 / Issue41: htm-registry.json 에 등록된 htm 단발 문서 평탄 목록.
        디렉토리 스캔 없음 — 등록 경로 1건씩 stat. 파일 부재 시 missing=True 로 노출
        (clear 로 목록 정리 가능). cwd 로 프로젝트 메타(name/color/token) 매핑."""
        import urllib.parse as _u
        # Issue352: registry 무한 누적 차단. TTL 가드가 있어 5초 polling 에도 실제 수행은
        #   최대 60초당 1회. registry_lock 은 내부에서 잡으므로 여기서는 미보유 상태여야 함.
        _prune_htm_registry()
        with projects_lock:
            proj_snap = {h: dict(p) for h, p in projects.items()}
        with registry_lock:
            htm_entries = load_registry(HTM_REGISTRY)
        results = []
        for e in htm_entries:
            path = e.get("path", "")
            if not path:
                continue
            cwd = e.get("cwd", "") or ""
            # cwd 정규화 — 슬래시 중복 등 비정상 prefix 로 cwd_hash 가 갈려
            # 동일 프로젝트가 virtual fallback 색으로 빠지는 사례 차단.
            if cwd:
                cwd = os.path.normpath(cwd)
            title = e.get("title") or os.path.basename(path)
            missing = not os.path.isfile(path)
            mtime, mtime_ts = "", 0
            summary = ""  # Issue70: htm-doc 카드 본문 2줄 요약
            doc_sid = ""  # Issue169: 문서 생성 세션 sid (🆚 세션 버튼용)
            if not missing:
                try:
                    st = os.stat(path)
                    mtime_ts = st.st_mtime
                    mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime_ts))
                    # Issue45: mtime 불변 시 재추출 생략. Issue70: {title,summary} dict 캐시
                    doc_c = doc_cache_get(path, mtime_ts)
                    if doc_c is None or not isinstance(doc_c, dict) or "sid" not in doc_c:
                        doc_c = {"title": self._extract_html_title(path),
                                 "summary": self._extract_html_summary(path),
                                 "sid": self._extract_html_sid(path)}
                        doc_cache_put(path, mtime_ts, doc_c)
                    if doc_c.get("title"):
                        title = doc_c["title"]
                    summary = doc_c.get("summary", "")
                    doc_sid = doc_c.get("sid", "")
                except OSError:
                    missing = True
            h = cwd_hash(cwd) if cwd else "__tmp__"
            p = proj_snap.get(h)
            if p:
                name = p.get("name", "")
                color = p.get("color", "hsl(220,60%,45%)")
                token = p.get("token", "")
            elif cwd:
                meta = project_meta(cwd)
                name, color, token = meta["name"], meta["color"], ""
            else:
                name, color, token = "system/___pm-tmp", "hsl(0,0%,75%)", ""
            view_url = ""
            if not missing:
                if path.endswith(".md"):
                    # Issue353_1: md 산출은 토큰 유무 무관 md 셸 라우트 (registry 게이트)
                    view_url = f"/md-doc?path={_u.quote(path)}"
                elif token:
                    view_url = (f"/view?cwd={_u.quote(cwd)}&token={token}"
                                f"&path={_u.quote(path)}")
                else:
                    # Issue50: 토큰 없는 프로젝트도 registry 등록 htm 은 열람 가능
                    view_url = f"/htm-doc?path={_u.quote(path)}"
            try:
                if cwd and path.startswith(cwd + os.sep):
                    path_display = os.path.relpath(path, cwd)
                else:
                    path_display = path
            except Exception:
                path_display = path
            # B모드(AskUserQuestion intercept) htm 폼 = claude-htm-ask-*.html.
            # answered: /answer 수신 시 registry 엔트리에 마킹됨.
            # qa_failed: ask 폼인데 10분(Claude polling timeout) 경과까지 미응답.
            is_ask = os.path.basename(path).startswith("claude-htm-ask-")
            answered = bool(e.get("answered"))
            qa_failed = (is_ask and not answered and not missing
                         and (time.time() - mtime_ts > 600))
            results.append({
                "cwd": cwd, "cwd_hash": h, "name": name, "color": color,
                "emoji": _project_emoji(cwd),
                "title": title, "summary": summary,
                "mtime": mtime, "mtime_ts": mtime_ts,
                "path": path, "path_display": path_display,
                "view_url": view_url, "virtual": not bool(p), "missing": missing,
                "is_ask": is_ask, "answered": answered, "qa_failed": qa_failed,
                "sid": doc_sid,  # Issue169: 🆚 세션 포커스용
            })
        results.sort(key=lambda x: x["mtime_ts"], reverse=True)
        # Issue52: card_limit — mtime 최신 N개만 hub 카드로 노출 (registry 는 미변경)
        card_limit = _load_hub_setting()["card_limit"]
        if card_limit > 0:
            results = results[:card_limit]
        return results

    @staticmethod
    def _coerce_num(v):
        """Issue193: progress value 를 숫자로 강제. runner/monitor 가 문자열 '100' 으로
        기록하는 케이스 호환(소비자 방어적 coercion). bool 은 제외(int 서브클래스)."""
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                return float(s) if ("." in s or "e" in s or "E" in s) else int(s)
            except ValueError:
                return None
        return None

    def _fill_dash_entry_from_dict(self, entry: dict, d) -> None:
        """dash.json 파싱 결과(dict) 를 entry 에 반영. widgets[].id=progress 도 fallback 추출."""
        if not isinstance(d, dict):
            return
        entry["title"] = d.get("title")
        entry["status"] = d.get("status")
        entry["pid"] = d.get("pid") if isinstance(d.get("pid"), int) else None
        entry["worker_pid"] = d.get("worker_pid") if isinstance(d.get("worker_pid"), int) else None
        # Issue403: mtime 정체 강등 임계를 보드 고유 주기로 산출하기 위해 필요.
        iv = self._coerce_num(d.get("interval"))
        if iv is not None:
            entry["interval"] = iv
        prog = self._coerce_num(d.get("progress"))
        if prog is not None:
            entry["progress"] = prog
        else:
            widgets = d.get("widgets") if isinstance(d.get("widgets"), list) else []
            for w in widgets:
                if isinstance(w, dict) and w.get("type") == "progress":
                    wv = self._coerce_num(w.get("value"))
                    if wv is not None:
                        entry["progress"] = wv
                        break

    @staticmethod
    def _yaml_scalar(v: str):
        """dashboard.md yaml scalar — null/true/false/quoted/int/float/str."""
        s = v.strip()
        if s in ("", "null", "~"):
            return None
        if s == "true":
            return True
        if s == "false":
            return False
        if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
            return s[1:-1]
        try:
            if "." in s or "e" in s or "E" in s:
                return float(s)
            return int(s)
        except ValueError:
            return s

    @classmethod
    def _parse_dash_yaml(cls, text: str) -> dict:
        """경량 yaml 파서 — dashboard.md 양식 한정. PyYAML 없이 stdlib 만 사용 (Issue31 (a)).

        지원: top-level scalar (title/status/pid/...), widgets list 의 progress.value 추출.
        미지원: 임의 nested dict/list, multi-line scalar, anchor, flow style 등.
        """
        out = {"title": None, "status": None, "pid": None, "worker_pid": None,
               "progress": None, "interval": None}
        in_widgets = False
        current_widget = None

        def _flush_widget():
            if not current_widget:
                return
            if current_widget.get("id") == "progress":
                val = cls._coerce_num(current_widget.get("value"))
                if val is not None:
                    out["progress"] = val

        for raw in text.splitlines():
            line = raw.rstrip()
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(stripped)
            if indent == 0:
                # top-level key 진입 — widgets 누적 종료
                if in_widgets:
                    _flush_widget()
                    current_widget = None
                    in_widgets = False
                if ":" not in stripped:
                    continue
                k, _, v = stripped.partition(":")
                k = k.strip()
                v_stripped = v.strip()
                # widgets: (list opener — value 없거나 빈 값)
                if k == "widgets" and v_stripped in ("", "[]"):
                    in_widgets = True
                    continue
                val = cls._yaml_scalar(v_stripped) if v_stripped else None
                if k == "title" and isinstance(val, str):
                    out["title"] = val
                elif k == "status" and isinstance(val, str):
                    out["status"] = val
                elif k == "pid" and isinstance(val, int):
                    out["pid"] = val
                elif k == "worker_pid" and isinstance(val, int):
                    out["worker_pid"] = val
                elif k == "progress":
                    pv = cls._coerce_num(val)
                    if pv is not None:
                        out["progress"] = pv
                elif k == "interval":
                    # Issue403: runner 갱신 주기(초). mtime 정체 강등 임계의 기준값.
                    ivv = cls._coerce_num(val)
                    if ivv is not None:
                        out["interval"] = ivv
            elif in_widgets:
                # widget list item 또는 widget 내부 key
                if stripped.startswith("- "):
                    _flush_widget()
                    current_widget = {}
                    inner = stripped[2:].strip()
                    if ":" in inner:
                        ik, _, iv = inner.partition(":")
                        current_widget[ik.strip()] = cls._yaml_scalar(iv)
                elif current_widget is not None and ":" in stripped:
                    ik, _, iv = stripped.partition(":")
                    current_widget[ik.strip()] = cls._yaml_scalar(iv)
        # EOF flush
        if in_widgets:
            _flush_widget()
        return out

    def _handle_dashboards(self, parsed):
        """Issue16_7 / Issue41: hub 목록 반환. 디렉토리 스캔 제거 — dash-registry.json 에
        등록된 dash 파일만 1건씩 읽어 메타 구성, cwd 별 프로젝트 카드로 그룹화.
        127.0.0.1 bind localhost trust — token 인증 없음 (응답에 token 포함되나 동일 user 가정)."""
        import urllib.parse as _u
        with projects_lock:
            proj_snap = {h: dict(p) for h, p in projects.items()}
        with registry_lock:
            dash_entries = load_registry(DASH_REGISTRY)
        # cwd -> [dash dict ...] 그룹화 (등록 경로 1건씩만 read, 디렉토리 스캔 없음)
        by_cwd = {}
        for e in dash_entries:
            path = e.get("path", "")
            if not path:
                continue
            cwd = e.get("cwd", "") or ""
            # cwd 정규화 — 슬래시 중복 등 비정상 prefix 로 cwd_hash 가 갈려
            # 동일 프로젝트가 virtual fallback 색으로 빠지는 사례 차단.
            if cwd:
                cwd = os.path.normpath(cwd)
            d = self._read_dash_file(path)
            if d is None:
                # 등록 경로의 파일이 사라짐 → stale. clear-done 으로 정리 가능하게 노출.
                d = {"path": path, "mtime": "", "mtime_ts": 0,
                     "title": e.get("title") or os.path.basename(path),
                     "status": "missing", "progress": None, "pid": None, "missing": True}
            d["sid"] = e.get("sid", "")  # Issue75: SPA 세션 라우트용 (등록 엔트리에서 전달)
            by_cwd.setdefault(cwd, []).append(d)
        out_projects = []
        for cwd, dashes in by_cwd.items():
            h = cwd_hash(cwd) if cwd else "__tmp__"
            p = proj_snap.get(h)
            if p:
                name = p.get("name", "")
                color = p.get("color", "hsl(220,60%,45%)")
                token = p.get("token", "")
                virtual = False
            elif cwd:
                meta = project_meta(cwd)
                name, color, token, virtual = meta["name"], meta["color"], "", True
            else:
                name, color, token, virtual = "system/___pm-tmp", "hsl(0,0%,75%)", "", True
            cwd_q = _u.quote(cwd) if cwd else ""
            for d in dashes:
                # Issue58: status=running 이지만 runner pid 가 죽었으면 stale 강등.
                # _read_dash_file 은 mtime 불변 시 캐시를 반환하므로 죽은 status 가 박제됨
                # → 캐시 외부(매 /boards 요청)에서 _pid_alive 검증. pid None 이면
                # 검증 불가 → running 유지. _read_dash_file 이 dict 복사본을 주므로
                # d 를 mutate 해도 doc_cache 는 오염되지 않음.
                # Issue83: 렌더·정리 단일 판정원 _effective_dash_status 사용.
                d["status"] = self._effective_dash_status(d)
                # Issue138: hub 메인 dashboard 카드 stop 버튼은 클라이언트가 pid 존재만
                #   검사해 done/runner-dead 후에도 "⏹ stop pid=N" 이 잔존했다(상세 인라인
                #   페이지만 보정된 비대칭). 서버가 runner 생존을 판정해 플래그로 전달 —
                #   클라는 runner_alive && !terminal 일 때만 stop 버튼 노출.
                #   pid 정수면 pid, 아니면 worker_pid(큐/모니터) fallback (effective_dash_status 동일 규칙).
                _lpid = d.get("pid")
                if not isinstance(_lpid, int):
                    _lpid = d.get("worker_pid")
                d["runner_alive"] = bool(isinstance(_lpid, int) and _pid_alive(_lpid))
                # Issue36: 프로젝트 cwd 하위 dash 는 상대 경로 표시
                try:
                    if cwd and (d["path"].startswith(cwd + os.sep) or d["path"] == cwd):
                        d["path_display"] = os.path.relpath(d["path"], cwd)
                    else:
                        d["path_display"] = d["path"]
                except Exception:
                    d["path_display"] = d["path"]
                d["view_url"] = ""
                if token and not d.get("missing"):
                    # Issue75: sid 보유 dash 는 SPA 세션 라우트(/s/{h}/{sid})로 "열기" —
                    #   파일 라우트(/view?path=)의 serve-root confinement 를 우회한다.
                    #   sid 부재 엔트리는 종전 파일 라우트 fallback (하위호환).
                    sid = d.get("sid", "")
                    if sid:
                        d["view_url"] = f"/s/{h}/{sid}?token={token}"
                    else:
                        try:
                            html_candidate = d["path"]
                            for suffix in (".dash.json", ".dash.yaml", ".dash.yml"):
                                if html_candidate.endswith(suffix):
                                    html_candidate = html_candidate[:-len(suffix)] + ".html"
                                    break
                            # Issue35: .html 우선, 없으면 dash 파일 자체 (서버 인라인 렌더)
                            target = html_candidate if os.path.exists(html_candidate) else d["path"]
                            d["view_url"] = f"/view?cwd={cwd_q}&token={token}&path={_u.quote(target)}"
                        except Exception:
                            d["view_url"] = ""
            out_projects.append({
                "cwd": cwd, "cwd_hash": h, "name": name, "color": color,
                "token": token, "dashes": dashes, "virtual": virtual,
                "emoji": _project_emoji(cwd),
            })
        # Issue44: dash-registry 미등록 프로젝트는 dashboard 섹션에 노출하지 않음.
        # htm 스킬이 /view token 위해 /register 한 프로젝트가 dashboard 빈 카드로
        # 새던 문제 차단 — dashboard 섹션은 dash-registry.json 등록 항목만.
        out_projects.sort(key=lambda x: x["name"].lower())
        # Issue33: SSE alive + 최근 갱신 session 노출 (파일 dash 없는 live-only session 케이스)
        live_sessions = self._collect_live_sessions()
        # Issue42: hook 활동 피드 (newest-first). 신규 GET endpoint 없이 기존 폴링에 편승
        with feed_lock:
            hook_feed = [dict(it) for it in feed_buffer]
        # Issue51: feed detail 의 미등록 htm html 을 registry 에 자가 등록 (htm_docs 수집 전)
        _autoheal_htm_registry(hook_feed)
        htm_docs = self._collect_htm_docs()  # Issue40 / Issue41 registry 기반
        # Issue46: 이모지 재계산 — 기존(이모지 없는) 항목·Projects.md 라이브 편집 반영
        for it in hook_feed:
            it["emoji"] = _project_emoji(it.get("cwd") or "")
        # Issue42_1/42_2 → Issue62: 피드 항목을 htm-registry 문서와 연결.
        # 절대경로 → basename → 턴 근접 3단계 매칭 (B모드 폼 ↗ 미표시 보강).
        _link_feed_htm_docs(hook_feed, htm_docs)
        # Issue87: 중요도 결정 모듈 — hub 상태에서 주의 항목을 점수화하여 헤더에 노출
        important_events = self._compute_important_events(
            live_sessions, htm_docs, hook_feed, out_projects)
        self._send_json(200, {
            "projects": out_projects,
            "live_sessions": live_sessions,
            "htm_docs": htm_docs,
            "hook_feed": hook_feed,
            "important_events": important_events,
            # Issue378: 떠 있는 탭의 표면 자기교정용. Issue377 의 302 는 새 요청에만 걸리므로
            #   이미 열린 탭은 모드 변경을 모른 채 무효 표면에 남는다. 양 표면이 이미 /boards 를
            #   폴링하므로 여기에 실어 보내 신규 폴링·엔드포인트 추가 0 으로 해결한다.
            "render_tab_mode": _load_hub_setting().get("render_tab_mode"),
            "live_session_limit": _load_hub_setting()["live_session_limit"],  # Issue129: 카드당 세션 행 상한
            "live_session_copy_button": _load_hub_setting()["live_session_copy_button"],  # Issue277: 세션 ID 복사 버튼 표시
            "feed_blink_on_new": _load_hub_setting()["feed_blink_on_new"],  # Issue279: 새 피드 깜빡임
            # Issue352: hub OFF 배지 소스. ⚠️ 위 out_projects 는 dash-registry 기반이라
            #   dashboard 보유 프로젝트만 담긴다(실측 0건) — 배지 소스로 못 쓴다.
            #   등록 프로젝트 전체(Projects.md)를 세는 _projects_list_with_htm() 을 쓴다.
            #   시스템 전역 OFF 는 별도 플래그로 준다 — htm_reason 문자열 매칭에 기대지 않기 위함.
            **_hub_off_stats(),
            # prj3#Issue438 ③: 핀봇 현황 상시 표시. 활성(퇴근 아님) 봇이 0 이면
            #   bots 가 빈 리스트로 와서 클라이언트가 섹션을 통째로 숨긴다.
            **_collect_bots(),
            "ts": int(time.time()),
        })

    def _compute_important_events(self, live_sessions, htm_docs, hook_feed,
                                  projects) -> list:
        """Issue87: 중요 이벤트 판정 모듈.

        hub 의 현재 상태에서 *사용자 주의가 필요한* 항목만 추려 점수화한다.
        반환: [{level, icon, text, link, score}], score 내림차순.
        level — critical(즉시 대응) / warning(확인 권장) / info(정리 권고).

        판정 규칙:
          R1 워크플로우 판단 요청 — live_session 의 waiting_approval_item 보유 (critical)
          R2 응답 정체 — 프로젝트(cwd)별 최근 활동이 AskUserQuestion/Notification 이고
             IMPORTANT_RESPONSE_WAIT_SEC(5분) 이상 미경신 (warning,
             IMPORTANT_RESPONSE_CRIT_SEC(30분)+ 면 critical)
          R3 dashboard 카드 정리 — done/stopped/stale/missing dash 누적 ≥ 임계 (info)
          R4 htm 문서 정리 — htm 문서 수 ≥ 임계 (info)
        """
        now = time.time()
        events = []
        # R1: 워크플로우 판단 요청 (가장 높은 우선순위)
        for s in live_sessions or []:
            item = s.get("waiting_approval_item")
            if item:
                events.append({
                    "level": "critical", "icon": "▶", "score": 1000,
                    "text": f"{s.get('name', '?')} — 워크플로우 판단 요청: {item}",
                    "link": s.get("url", ""),
                })
        # R2: 응답 정체 — newest-first 순회, 프로젝트(cwd)별 최근 1건만 평가 (중복 억제)
        # Issue100: orphan/abandoned wait 배제. R2 가 죽은 세션의 Notification/
        #   AskUserQuestion 을 영구 critical 칩으로 남기는 부활 버그 차단.
        #   - cwd 에 live session 없음 → 응답 받을 세션 사망 → orphan wait (Stop 훅 없이
        #     세션 종료 시 Notification 이 영구 최신 피드로 잔존). 칩 노출 무의미.
        #   - age ≥ ABANDON_SEC(6h) → 명백 방치 (genuine 질문은 수 분 내 해소).
        #   둘 중 하나라도 해당하면 R2 미발화 (hub liveness 모델 Issue63/95/99 와 일관).
        live_cwds = {s.get("cwd") for s in (live_sessions or [])}
        seen_cwd = set()
        for it in hook_feed or []:
            cwd = it.get("cwd", "")
            if cwd in seen_cwd:
                continue
            seen_cwd.add(cwd)
            if it.get("event") not in IMPORTANT_WAIT_EVENTS:
                continue
            age = now - (it.get("ts") or now)
            if age < IMPORTANT_RESPONSE_WAIT_SEC:
                continue
            # Issue100: orphan(세션 사망)·방치(6h+) wait 배제
            if cwd not in live_cwds or age >= IMPORTANT_RESPONSE_ABANDON_SEC:
                continue
            mins = int(age // 60)
            crit = age >= IMPORTANT_RESPONSE_CRIT_SEC
            events.append({
                "level": "critical" if crit else "warning", "icon": "⏳",
                "score": (500 if crit else 300) + min(mins, 120),
                "text": f"{it.get('name', '?')} — 응답 {mins}분 대기, 요청 필요",
                "link": it.get("htm_view_url", ""),
                "feed_id": it.get("id", ""),
            })
        # R3: dashboard 카드 정리
        stale = sum(1 for p in projects or [] for d in p.get("dashes", [])
                    if d.get("status") in ("done", "stopped", "stale", "missing"))
        if stale >= IMPORTANT_STALE_CARD_MIN:
            events.append({
                "level": "info", "icon": "🧹", "score": 100 + stale,
                "text": f"dashboard 카드 {stale}개 정리 필요 (done/stopped/stale)",
                "link": "",
            })
        # R4: htm 문서 정리
        n_htm = len(htm_docs or [])
        if n_htm >= IMPORTANT_HTM_DOC_MIN:
            events.append({
                "level": "info", "icon": "📄", "score": 90 + n_htm,
                "text": f"hub 문서 {n_htm}개 누적 — 정리 권고",
                "link": "",
            })
        events.sort(key=lambda e: -e["score"])
        return events

    def _collect_live_sessions(self, alive_window: float = 5.0) -> list:
        """Issue33: SSE subscriber>0 또는 최근 update_at < alive_window 초 인 session 만 노출.
        Issue37: subs=0 + registered_pids=0 (정상 runner 없음) → zombie 의심으로 노출 제외.
        runner 가 /register-pid 호출 했다면 정상, 아니면 깜빡임 차단."""
        now = time.time()
        with sessions_lock:
            sess_snap = list(sessions.items())
        with sse_lock:
            sub_snap = {k: len(v) for k, v in sse_subscribers.items()}
        with projects_lock:
            proj_snap = dict(projects)
        with pids_lock:
            pid_snap = {k: {pid for pid in v if _pid_alive(pid)} for k, v in pids.items()}
        # Issue95: DASH_CLEARED tombstone — 명시 정리된 dashboard 는 live session 으로도
        #   부활시키지 않는다. clear-done/control-remove 가 sessions 를 즉시 제거하나,
        #   재시작 전 잔존분·dash_path 미기록 구버전 세션의 부활을 렌더 경로에서 재차단.
        cleared_norm = _dash_cleared_norm()
        live_dismissed_snap = _load_live_dismissed()  # Issue135: dismiss tombstone 1회 스냅샷
        results = []
        terminal_keys = []  # Issue63: TTL prune 대상 (terminal dashboard 세션)
        cleared_keys = []   # Issue95: tombstone 매칭 → 즉시 제거 대상
        # Issue99: live 세션 dedup — 동일 live_pid 는 freshest 1개만 노출.
        #   훅 중복 fire(동일 프로세스 다중 sid)로 인한 중복 카드 차단. 비-freshest 는
        #   skip set 에 담아 루프에서 제외(+ terminal prune).
        # Issue282: dedup 키를 (cwd_hash, live_pid) → live_pid 전역으로 확장.
        #   세션 중 cd 로 cwd 가 드리프트하면 동일 세션이 다른 hash 아래 재등록돼
        #   프로젝트 카드 2장으로 중복 노출됐다(hash 가 갈리면 종전 키로는 무력).
        #   한 OS 프로세스 = 한 세션이므로 pid 전역 dedup 이 안전하다.
        live_best = {}   # live_pid -> (updated, h, sid)
        for (h, sid), entry in sess_snap:
            if entry.get("content_type") != "live":
                continue
            lp = entry.get("live_pid")
            if lp is None:
                continue
            u = entry.get("updated", 0) or 0
            prev = live_best.get(lp)
            if prev is None or u > prev[0]:
                live_best[lp] = (u, h, sid)
        live_dup_skip = set()
        for (h, sid), entry in sess_snap:
            if entry.get("content_type") != "live":
                continue
            lp = entry.get("live_pid")
            if lp is None:
                continue
            if live_best.get(lp, (None, None, None))[1:] != (h, sid):
                live_dup_skip.add((h, sid))
        for (h, sid), entry in sess_snap:
            if (h, sid) in live_dup_skip:  # Issue99: 중복 live 세션 (비-freshest) 제외
                terminal_keys.append((h, sid))
                continue
            subs = sub_snap.get((h, sid), 0)
            updated = entry.get("updated", 0) or 0
            age = now - updated
            # Issue95: tombstone 된 dashboard 세션은 pid 생존·heartbeat 신선이어도 제외.
            if (cleared_norm and entry.get("content_type") == "dashboard" and
                    _dash_session_candidate_paths(
                        proj_snap.get(h, {}).get("cwd", ""), entry) & cleared_norm):
                cleared_keys.append((h, sid))
                continue
            # Issue63: dashboard(mode C) 세션 liveness 는 runner 의 실제 생존으로 판정.
            #   data content 의 pid·status 가 authoritative 신호 — runner 가 매 iter
            #   자기 pid·status 를 써넣으므로 가장 신뢰도 높다.
            #   - status terminal(done/stopped) → 제외 (TTL prune 대상)
            #   - pid 사망 → zombie 제외 (브라우저 탭이 열려 subs>0 이어도)
            #   - pid 생존 → 무조건 live (subs/registered-pid Issue37 게이트 우회).
            #     종전엔 서버 재시작 후 registered_pids=0 + 탭 닫힘(subs=0)이면 살아있는
            #     dashboard 도 숨겨졌다 → pid 생존이면 강제 노출.
            force_live = False
            runner_pid = None   # hub live 카드 kill 버튼용 (dashboard runner pid)
            supervisor_pid = None  # Issue66: 큐 dashboard supervisor pid
            waiting_approval_item = None  # Issue66 Phase 7: 첫 waiting_approval node id
            dash_title = None   # Issue80: dashboard topic (content JSON 의 title) — 카드 제목용
            if entry.get("content_type") == "dashboard":
                d_pid, d_status = _dash_runner_state(entry)
                if d_status in ("done", "stopped"):
                    terminal_keys.append((h, sid))
                    continue
                if d_pid is not None:
                    if not _pid_alive(d_pid):
                        terminal_keys.append((h, sid))
                        continue
                    # pid 생존만으론 부족 — runner 가 죽어도 orphan sleep/PID 재사용으로
                    #   pid 가 살아있으면 좀비 카드가 dismiss/age/subs 를 모두 우회해
                    #   부활한다(force_live 가 게이트 전부 무시). heartbeat 신선도(age)를
                    #   추가 게이트로 — runner 가 매 iter data POST 로 updated 를 갱신하므로
                    #   죽으면 age 가 누적돼 STALE 초과 → terminal.
                    if age > DASH_HEARTBEAT_STALE:
                        terminal_keys.append((h, sid))
                        continue
                    force_live = True  # runner 생존 + heartbeat 신선 확정
                    runner_pid = d_pid
                # Issue66: supervisor_pid 추출 (큐 dashboard 판별용)
                #   + Issue66 Phase 7: graph 위젯 node 중 첫 waiting_approval 항목 추출
                try:
                    dc = json.loads(entry.get("content") or "")
                    # Issue80: dashboard topic 추출 — 활성 세션 카드 제목용.
                    #   content_type 은 항상 "dashboard" 라 카드 구분 불가 → title 사용.
                    dt = dc.get("title")
                    if isinstance(dt, str) and dt.strip():
                        dash_title = dt.strip()
                    spid = dc.get("supervisor_pid")
                    if spid is not None:
                        supervisor_pid = int(spid)
                    for w in (dc.get("widgets") or []):
                        if not isinstance(w, dict) or w.get("type") != "graph":
                            continue
                        for node in (w.get("nodes") or []):
                            if isinstance(node, dict) and node.get("status") == "waiting_approval":
                                waiting_approval_item = node.get("id")
                                break
                        if waiting_approval_item is not None:
                            break
                except Exception:
                    pass
            # Issue98: content_type="live" (일반 claude 세션) liveness 판정.
            #   pid 주어지면 _pid_alive 가 권위적 — 죽으면 terminal, 살면 force_live.
            #   pid 없으면 heartbeat TTL(LIVE_TTL) fallback. dashboard 와 달리 runner_pid
            #   는 None 으로 둬 카드에 kill 버튼 미노출 (claude 세션 오살 방지).
            #   Issue374: 단 pid 생존은 **필요조건일 뿐** — heartbeat 가
            #   LIVE_HEARTBEAT_STALE 을 넘으면 pid 가 살아 있어도 terminal 이다.
            elif entry.get("content_type") == "live":
                # Issue135: 수동 dismiss tombstone — TTL 내면 live_pid 생존(force_live)
                #   이어도 표시 제외. sessions 는 유지(pop 안 함) → TTL 만료 후 자동 복귀.
                #   살아있는 세션의 재등록 heartbeat 부활을 렌더 단계에서 차단.
                if f"{h}|{sid}" in live_dismissed_snap:
                    continue
                # Issue374: pid 생존만으론 부족 — 세션보다 오래 사는 호스트 프로세스가
                #   있으면(Claude Desktop 예약작업 호스트 등) 끝난 세션이 영구 live 로
                #   남는다. dashboard 와 동일하게 heartbeat 신선도를 함께 요구한다.
                #   pid 유무 양쪽 경로에 걸리도록 live_pid 판정 앞에 둔다.
                if age > LIVE_HEARTBEAT_STALE:
                    terminal_keys.append((h, sid))
                    continue
                lp = entry.get("live_pid")
                if lp is not None:
                    if not _pid_alive(int(lp)):
                        # Issue341: 등록 pid 가 단기 wrapper 였던 세션 self-heal.
                        #   훅이 잘못된 pid(등록 직후 사망)를 넣으면 살아있는 세션이
                        #   전부 terminal 로 분류돼 📡 활성 세션이 통째로 비었다.
                        #   heartbeat 가 신선하면 pid 를 신뢰하지 않고 TTL 로 판정하고,
                        #   죽은 live_pid 는 제거해 이후 dedup 오염을 막는다.
                        # Issue397: pop 전에 gc_meta.shell_pid(등록 pid 의 부모) 승격을
                        #   1회 시도 — 부모가 살아있는 claude 세션이면 pid 권위를 복구해
                        #   idle 5분 후 소실(LIVE_TTL 강등)을 원천 차단한다.
                        if _try_promote_live_pid(h, sid, entry) is not None:
                            force_live = True
                        elif age <= LIVE_TTL:
                            with sessions_lock:
                                cur = sessions.get((h, sid))
                                if cur is not None and cur.get("live_pid") == lp:
                                    cur.pop("live_pid", None)
                            entry.pop("live_pid", None)
                            force_live = True
                        else:
                            terminal_keys.append((h, sid))
                            continue
                    else:
                        force_live = True
                else:
                    # Issue397: live_pid 소실분(과거 pop 잔재)도 승격 1회 시도 후 TTL 판정.
                    if _try_promote_live_pid(h, sid, entry) is not None:
                        force_live = True
                    elif age > LIVE_TTL:
                        terminal_keys.append((h, sid))
                        continue
                    else:
                        force_live = True
                # 카드 제목 (Issue127 후속): VSCode 탭 제목(ai-title) 최우선 — 세션 JSONL 의
                #   aiTitle 이 VSCode 가 표시하는 제목의 SSOT. hub 카드를 VSCode 와 일치시킴.
                #   ai-title 미생성(세션 극초기)이면 live_label(프롬프트 요약), 그다음 win fallback.
                #   Issue121 SessionStart 훅이 label 미전송·capabilities 만 보낼 때 win 대비.
                #   Issue328: 최종 폴백 — JSONL 첫 user 프롬프트 발췌(Zed·터미널용).
                #   Issue359: 3단 판정을 _live_session_title 로 추출 — 좀비 킬러가
                #     같은 함수를 쓰게 해 "제목 있음"의 정의가 갈라지지 않게 한다.
                dash_title = _live_session_title(
                    proj_snap.get(h, {}).get("cwd", ""), sid, entry)
                # else (Issue129): 명령(프롬프트) 전 세션 → dash_title None 유지 → 클라가 "-" 표기.
                #   기존 "claude · win N" fallback 제거 — VSCode 세션엔 무의미(전부 win 1).
            if not force_live:
                if subs <= 0 and age >= alive_window:
                    continue
                # Issue37: SSE subscriber 0 + alive registered PID 도 없으면 zombie 제외
                if subs <= 0 and not pid_snap.get(h):
                    continue
            p = proj_snap.get(h)
            if not p:
                continue
            token = p.get("token", "")
            # Issue177: 세션 출처 — capabilities.entrypoint(SessionStart 훅 전송)로
            #   VSCode 확장(claude-vscode)과 터미널 CLI(cli 등)를 구분.
            #   claude-vscode → "vscode"(카드 클릭 시 VSCode 탭 포커스),
            #   그 외/미상 → "terminal"(클릭 시 VSCode 재오픈 안 함).
            _entry_caps = entry.get("capabilities") or {}
            _ep = str(_entry_caps.get("entrypoint", "")).strip()
            # Issue327: 3값화 — Zed(ACP 브리지)는 entrypoint 가 sdk-ts 로만 보여
            #   판정 hook(prj3)이 caps.editor="zed" 를 실어 보낸다. _origin_from_caps 가 단일 판정점.
            origin = _origin_from_caps(_entry_caps)
            # Issue342 S3: 기동자(누가 띄웠나). origin(어느 에디터인가)과 축이 다르다.
            launched_by = _launched_by_from_caps(_entry_caps)
            # Issue273: 메인 세션 모델 — producer hook 이 caps.model 로 transcript 최신 model 전송.
            _model_id = str(_entry_caps.get("model", "")).strip()
            _model_tier = _classify_model_tier(_model_id)
            results.append({
                "cwd": p.get("cwd", ""),
                "cwd_hash": h,
                "sid": sid,
                "name": p.get("name", ""),
                "color": p.get("color", "hsl(220,60%,45%)"),
                "emoji": _project_emoji(p.get("cwd", "")),
                # Issue284: 카드 헤더 🗺️ 아이콘 조건부 렌더용. Issue284_1 — 맵 파일 존재만으론
                #   부족하고 `Issue.md` 에 `* depends:` 간선이 있어야 노출(관계도 가치 有).
                #   경로는 노출하지 않는다(/issue-map 이 cwd 로 서버측 재계산 — 경로 조작 차단).
                "issue_map": _issue_map_visible(p.get("cwd", "")),
                # Issue363: 맵 파일이 Issue.md 보다 오래됨 → 아이콘에 흐림 표식(노출 여부는 불변)
                "issue_map_stale": _issue_map_stale(p.get("cwd", "")),
                "open_issue_count": _issue_open_count(p.get("cwd", "")),  # Issue316: 카드 배지 — 미완료 이슈 수
                "mode": entry.get("mode"),
                "content_type": entry.get("content_type"),
                "origin": origin,         # Issue177: "vscode" | "terminal" (카드 배지·클릭 분기)
                # Issue342 S3: "pm-do"|"board"|"manual"|"ide"|"" (미상). origin 과 별개 축.
                "launched_by": launched_by,
                "model_tier": _model_tier,  # Issue273: opus|sonnet|haiku|fable|"" (신호등 이모지)
                "model_id": _model_id,      # Issue273: 이모지 hover 툴팁 원문
                "title": dash_title,      # Issue80: dashboard topic (없으면 None → JS fallback)
                "updated_age": round(age, 1),
                "subscribers": subs,
                "url": f"/s/{h}/{sid}?token={token}",
                "token": token,           # hub live 카드 kill 버튼용
                "pid": runner_pid,        # dashboard runner pid (없으면 None)
                "supervisor_pid": supervisor_pid,  # Issue66: 큐 dashboard supervisor pid (없으면 None)
                "waiting_approval_item": waiting_approval_item,  # Issue66 P7: 첫 승인 대기 항목 id (없으면 None)
                "created": entry.get("created", 0) or 0,  # Issue159: created 정렬 키
            })
        results.sort(key=lambda x: x["updated_age"])
        # Issue136: title 없는 빈 live 세션은 프로젝트(cwd_hash)당 1개만 표시.
        #   VSCode 가 세션 종료 후에도 claude 프로세스를 살려두면(live_pid alive)
        #   프롬프트 전 빈 세션이 force_live 로 계속 노출돼 카드가 "-" 행으로 도배된다.
        #   dismiss(tombstone LIVE_DISMISS_TTL=120s)는 살아있는 프로세스의 재등록을
        #   막지 못해 부활 → 근본 차단 불가(프로세스 kill 은 정당 세션 오살 위험).
        #   빈 세션은 정보가 없으므로 가장 최근(updated_age 최소) 1개만 남기고 collect
        #   단계에서 숨긴다. title 있는 live·dashboard 세션은 전부 유지(중요 정보).
        #   results 는 updated_age 오름차순 정렬 상태 → 순회 시 첫 빈 세션이 최신.
        # Issue166: live_session_show_empty=false(기본) 면 빈 live 세션 전체 숨김.
        #   true 면 종전 Issue136 동작(프로젝트당 최신 1개)으로 노출.
        _show_empty = _load_hub_setting().get("live_session_show_empty", False)
        _empty_live_seen = set()
        _deduped = []
        for r in results:
            t = r.get("title")
            is_empty_live = (r.get("content_type") == "live"
                             and not (isinstance(t, str) and t.strip()))
            if not is_empty_live:
                _deduped.append(r)
                continue
            if not _show_empty:
                continue  # Issue166: 명령 전 빈 세션 전체 숨김 (기본값)
            h2 = r.get("cwd_hash")
            if h2 in _empty_live_seen:
                continue  # 이 프로젝트의 빈 live 세션 이미 1개 표시함 → 숨김
            _empty_live_seen.add(h2)
            _deduped.append(r)
        results = _deduped
        # Issue159: 활성세션 정렬 옵션 — created=세션 시작 시각 오름차순 고정,
        #   project=Projects.md 번호 오름차순(미등록 cwd 는 끝, 2차 키 created).
        #   둘 다 행·카드 점프 방지. Issue136 dedup 은 updated_age 오름차순을
        #   전제하므로 재정렬은 반드시 dedup 이후에 적용한다. 기본 updated 는 현행 유지.
        _order = _load_hub_setting().get("live_session_order", "updated")
        if _order == "created":
            results.sort(key=lambda x: x.get("created") or 0)
        elif _order == "project":
            _prj_id = {os.path.expanduser(r["path"]).rstrip("/"): r["id"]
                       for r in _load_projects_list()}
            # Issue303 이후 prj id 는 문자열("9a") → int 기본값과 혼합 비교 시 TypeError.
            #   _pid_sort_key 로 튜플 정규화하여 미등록 cwd 는 (inf,"",0) 로 밀어냄.
            results.sort(key=lambda x: (_pid_sort_key(_prj_id.get((x.get("cwd") or "").rstrip("/"), "")),
                                        x.get("created") or 0))
        # Issue63: terminal(done/stopped) dashboard 세션 TTL prune — 1h 경과분은
        #   sessions 테이블에서 완전 제거하여 sessions.json 무한 성장 차단.
        #   detail page 회람을 위해 1h 동안은 entry 유지 (활성 목록엔 이미 미노출).
        TERMINAL_TTL = 3600
        stale = [(h, sid) for (h, sid) in terminal_keys
                 if now - (dict(sess_snap).get((h, sid), {}).get("updated", 0) or 0) > TERMINAL_TTL]
        if stale:
            with sessions_lock:
                for k in stale:
                    sessions.pop(k, None)
            persist_sessions()
            log(f"_collect_live_sessions: pruned {len(stale)} terminal sessions (TTL {TERMINAL_TTL}s)")
        # Issue95: tombstone 매칭 dashboard 세션은 TTL 없이 즉시 제거 (부활 잔존분 청소).
        if cleared_keys:
            with sessions_lock:
                for k in cleared_keys:
                    sessions.pop(k, None)
            persist_sessions()
            log(f"_collect_live_sessions: removed {len(cleared_keys)} tombstoned dashboard sessions")
        return results

    def _handle_file_stat(self, parsed):
        """Issue115: dashboard 데이터 파일 폴링 — htm 폴더의 *.dash.yaml mtime 반환.
        Issue289: HTM_DIRS 전체를 우선순위 순으로 훑되 같은 파일명은 앞선 경로가 이긴다."""
        qs = parse_qs(parsed.query)
        cwd = unquote(qs.get("cwd", [""])[0]) or ""

        files = {}
        if cwd:
            for htm_dir in _htm_dirs_for(cwd):
                if not os.path.isdir(htm_dir):
                    continue
                for f in os.listdir(htm_dir):
                    if f.endswith(".dash.yaml") and f not in files:
                        path = os.path.join(htm_dir, f)
                        try:
                            stat = os.stat(path)
                            files[f] = {"mtime_ts": stat.st_mtime}
                        except Exception:
                            pass

        self._send_json(200, {"files": files})

    def _handle_qr(self, parsed):
        # Issue228: 모바일 접속 QR. advertise_host 우선, 없으면 LAN IP 자동탐지.
        setting = _load_hub_setting()
        host = (setting.get("advertise_host") or "").strip()
        if not host:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))  # 실제 송신 없음 — 로컬 라우팅 소스 IP 획득
                host = s.getsockname()[0]
                s.close()
            except OSError:
                host = socket.gethostname() or "127.0.0.1"
        bind = setting.get("bind_host", "127.0.0.1")
        if isinstance(bind, list):
            bind = bind[0] if bind else "127.0.0.1"
        lan_active = str(bind) not in ("127.0.0.1", "localhost", "::1")
        url = "http://%s:%d/hub" % (host, PORT)
        # url 을 JS 문자열 리터럴로 안전 임베드
        url_js = json.dumps(url)
        warn_html = "" if lan_active else (
            '<p class="warn">⚠️ 현재 bind_host 가 로컬 전용(<code>%s</code>)이라 다른 기기에서 '
            '접속되지 않습니다. LAN 접속하려면 설정에서 <code>bind_host: 0.0.0.0</code> + '
            '<code>advertise_host</code> 지정 후 hub 재시작하세요.</p>' % bind)
        html = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/fpm-icon.png"><title>fPm — 모바일 접속 QR</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: 1.5rem 1rem 3rem; line-height: 1.6; text-align: center;
    color: #1a1a1a; background: #fff; }
  h1 { font-size: 1.3rem; margin: 0.4rem 0 1rem; }
  #qr { display: inline-block; padding: 1rem; background: #fff; border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.12); margin: 0.5rem auto 1.2rem; }
  #qr svg, #qr img { width: min(72vw, 320px); height: auto; }
  .url { font-family: ui-monospace, monospace; font-size: 1.05rem; word-break: break-all;
    background: rgba(0,0,0,0.06); padding: 0.5rem 0.8rem; border-radius: 8px;
    display: inline-block; margin-bottom: 1rem; }
  .hint { color: #555; font-size: 0.95rem; max-width: 30rem; margin: 0.5rem auto; }
  .warn { color: #9a3a00; background: hsl(40,80%,92%); border-radius: 8px;
    padding: 0.7rem 1rem; max-width: 32rem; margin: 1rem auto; text-align: left; }
  code { background: rgba(0,0,0,0.08); padding: 0.05rem 0.3rem; border-radius: 4px; }
  @media (prefers-color-scheme: dark) {
    body { color: #e0e0e0; background: #161616; }
    .url { background: rgba(255,255,255,0.1); } .hint { color: #aaa; }
    .warn { color: #ffca8a; background: hsl(40,40%,18%); }
    code { background: rgba(255,255,255,0.12); }
  }
</style></head><body>
<h1>📱 fPm hub 모바일 접속</h1>
<div id="qr">QR 생성 중…</div>
<div class="url">__URL__</div>
<p class="hint">같은 Wi-Fi 에서 휴대폰 카메라로 QR 을 스캔하면 이 hub 에 접속됩니다.</p>
__WARN__
<script src="/assets/qrcode.min.js"></script>
<script>
  (function(){
    var url = __URL_JS__;
    try {
      var qr = qrcode(0, 'M');
      qr.addData(url);
      qr.make();
      document.getElementById('qr').innerHTML = qr.createSvgTag({cellSize:6, margin:2});
    } catch (e) {
      document.getElementById('qr').textContent = 'QR 생성 실패: ' + e.message;
    }
  })();
</script>
</body></html>"""
        html = html.replace("__URL_JS__", url_js).replace("__URL__", url).replace("__WARN__", warn_html)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_hub(self, parsed):
        # Issue42/47: hub_setting.yml 값으로 HUB_HTML placeholder 치환
        setting = _load_hub_setting()
        # Issue213: hub-internal 모드에서 standalone /hub(=탭바 없는 hub 홈)를 top-level 로
        #   직접 열면 /hub-shell(쉘) 과 두 창이 공존한다. /hub 는 이미 쉘의 home 탭(iframe
        #   src=/hub?_shell=1)이므로, 최상위 직접 열람은 /hub-shell 로 302 → 단일 쉘로 funnel.
        #   임베드(_shell=1 마커 1순위 / Sec-Fetch-Dest 보조)는 raw serve 유지(redirect loop 방지).
        #   htm-doc(_handle_htm_doc) 와 동일 패턴.
        qs = parse_qs(parsed.query)
        _is_embed = ((qs.get("_shell") or [""])[0] == "1"
                     or self.headers.get("Sec-Fetch-Dest") in ("iframe", "embed"))
        if not _is_embed and setting.get("render_tab_mode") == "hub-internal":
            self.send_response(302)
            self.send_header("Location", "/hub-shell")
            self.end_headers()
            return
        # Issue242: 이 서버가 Servers.md 에 이모지 등록돼 있으면 헤더 로고=이모지 + 그라디언트=대응색.
        #   미등록(jm4 등)이면 fPm 아이콘 + 기본 파랑-보라 그라디언트(canonical).
        _emoji, _hue, _sname = _self_server_badge()
        if _emoji:
            _logo = ('<span class="hub-logo hub-emoji" title="%s">%s</span>'
                     % (html.escape(_sname or ""), html.escape(_emoji)))
            _grad = ("linear-gradient(90deg, hsl(%d,60%%,42%%), hsl(%d,62%%,50%%))"
                     % (_hue, (_hue + 40) % 360))
        else:
            _logo = '<img class="hub-logo" src="/fpm-icon.png" alt="fPm">'
            _grad = "linear-gradient(90deg, hsl(220,60%,45%), hsl(280,60%,45%))"
        html_str = (HUB_HTML
            .replace("{HUB_LOGO}", _logo)
            .replace("{HUB_HEADER_GRAD}", _grad)
            .replace("{FEED_DEFAULT_VISIBLE}",
                     "true" if setting.get("feed_default_visible", True) else "false")
            .replace("{FEED_SHOW_PROJECT_EMOJI}",
                     "true" if setting.get("feed_show_project_emoji", True) else "false")
            .replace("{FEED_SHOW_PROJECT_NAME}",
                     "true" if setting.get("feed_show_project_name", True) else "false"))
        # Issue169: i18n — {T:key} placeholder 를 현재 language 로 1패스 치환(서버 정적).
        #   차후 마이그레이션은 HUB_HTML 에 {T:key} 추가 + locale 항목 추가만으로 동작(핸들러 무변경).
        lang = i18n.norm_lang(setting.get("language"))
        # Stage8: JS 런타임 합성용 사전·lang 을 인라인 주입 (window.__i18n / window.__lang)
        html_str = (html_str
            .replace("{I18N_LANG}", lang)
            .replace("{I18N_ALL_JSON}", json.dumps(
                {lg: i18n.merged(lg) for lg in i18n.SUPPORTED}, ensure_ascii=False))
            .replace("{I18N_JSON}", json.dumps(i18n.merged(lang), ensure_ascii=False)))
        html_str = re.sub(r"\{T:([\w.]+)\}", lambda m: i18n.t(m.group(1), lang), html_str)
        body = html_str.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self, max_bytes: int = 64 * 1024):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > max_bytes:
            return None, "invalid content length"
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except Exception as e:
            return None, f"invalid JSON: {e}"

    def _handle_clear_done(self, parsed):
        """Issue41: dash-registry.json 에서 status 가 done/stopped/stale 인(또는 파일이 사라진)
        항목을 hub 목록에서 제거. 실제 .dash.* / .html 파일은 삭제하지 않음 — hub 가
        추적하던 '연결'만 끊는다. 127.0.0.1 trust → 토큰 미요구."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        # Issue95: 디스크 권위적 tombstone — registry 미등록 orphan(.dash.*) 도 함께
        #   tombstone 하여 clear 후 rescan 부활을 원천 차단. registry_lock
        #   진입 전에 수집(내부적으로 projects_lock 사용 — lock 순서 projects→registry).
        disk_dash_paths = self._all_disk_dash_paths()
        removed = []
        removed_entries = []   # Issue95: 제거 entry 원본 (sid/cwd → live session 동반 제거)
        with registry_lock:
            entries = load_registry(DASH_REGISTRY)
            kept = []
            for e in entries:
                path = e.get("path", "")
                d = self._read_dash_file(path) if path else None
                if d is None or self._is_clearable_status(self._effective_dash_status(d)):
                    removed.append(path)
                    removed_entries.append(e)
                else:
                    kept.append(e)
            if len(kept) != len(entries):
                save_registry(DASH_REGISTRY, kept)
                # Issue54: 제거된 dash path 를 tombstone 에 추가 — rescan 부활 차단.
                #   kept path 는 해제, 디스크 부재 path 는 prune (무한 성장 차단).
                cleared = set(load_registry(DASH_CLEARED))
                cleared |= {p for p in removed if p}
                cleared |= {p for p in disk_dash_paths if p}            # Issue95: orphan 포함 전 디스크
                cleared -= {e.get("path", "") for e in kept}
                cleared = {p for p in cleared if p and os.path.isfile(p)}
                save_registry(DASH_CLEARED, sorted(cleared))
        # Issue95: feed_buffer 에서 cleared dashboard 경로 언급 항목 제거
        if removed_set := {p for p in removed if p}:
            with feed_lock:
                buf = _feed_buffer_synced()
                before = len(buf)
                cleaned = [it for it in buf
                           if not any(p in it.get("detail", "") for p in removed_set)]
                buf.clear()
                buf.extend(cleaned)
            if len(cleaned) < before:
                persist_feed()
                log(f"POST /clear-done — feed {before - len(cleaned)} items cleaned")
        # Issue95: 제거 registry entry 의 sid 로 대응 live session 동반 제거 —
        #   registry/feed 만 정리하고 sessions 를 남기면 runner pid 생존 시 force_live 로,
        #   서버 재시작 시 load_sessions 로 카드가 부활하던 핵심 누락 채널 차단.
        sess_drop = []
        for e in removed_entries:
            sid = e.get("sid", "")
            cwd = e.get("cwd", "") or ""
            if sid:
                sess_drop.append((cwd_hash(cwd) if cwd else "__tmp__", sid))
        if sess_drop:
            dropped = 0
            with sessions_lock:
                for k in sess_drop:
                    if sessions.pop(k, None) is not None:
                        dropped += 1
            if dropped:
                persist_sessions()
                log(f"POST /clear-done — {dropped} live session(s) removed (sid match)")
        log(f"POST /clear-done — removed={len(removed)} (registry 항목 제거, 파일 보존)")
        self._send_json(200, {
            "status": "ok",
            "removed_count": len(removed),
            "removed": removed,
            "errors": [],
            "note": "registry 항목만 제거 — 실제 파일은 보존됨",
        })

    def _handle_kill_empty_live(self, parsed):
        """Issue137: 빈(title 없는) live 세션의 좀비 claude 프로세스를 일괄 종료.
        VSCode 확장이 세션 종료 후에도 살려둔 native claude(--output-format
        stream-json)가 프롬프트 전 빈 카드로 잔존한다 → live_pid 에
        SIGTERM(graceful) + sessions prune + dismiss tombstone(LIVE_DISMISS_TTL
        내 재등록 차단). titled live·dashboard 세션은 절대 건드리지 않는다(오살 방지).

        ⚠️ Issue359 (2026-08-07): "title 없음" 판정이 `live_label` 단독이라
        Zed·터미널 세션을 **구조적으로 전부** 빈 세션으로 오판했다(그 둘은 ai-title
        이 없고 label 도 안 실려 와 첫 프롬프트 발췌로만 제목을 얻는다). 클릭 1회에
        작업 중 세션 7개가 전멸했다. 이제 카드 렌더와 같은 `_live_session_title` 을
        공유한다 — 제목 소스가 늘어나도 판정이 갈라지지 않는다.
        Issue136 dedup 이 cwd 당 1개로 줄이나, 본 버튼은 살아있는 좀비 자체를 제거해
        부활을 원천 차단한다. 127.0.0.1 trust → 토큰 미요구."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        # 빈 live 세션 스냅샷 수집 — 제목 판정은 카드와 동일한 단일 지점을 쓴다
        #   (Issue359). ai-title·live_label·첫 프롬프트 중 **하나라도** 있으면
        #   프롬프트를 받은 작업 세션이므로 보존한다.
        targets = []  # (h, sid, pid)
        kept = []     # 보존 내역 — 무엇을 왜 안 죽였는지 응답으로 돌려준다
        with sessions_lock:
            snap = list(sessions.items())
        with projects_lock:
            proj_snap = dict(projects)
        for (h, sid), entry in snap:
            if not isinstance(entry, dict) or entry.get("content_type") != "live":
                continue
            cwd = (proj_snap.get(h) or {}).get("cwd", "")
            title = _live_session_title(cwd, sid, entry)
            if title and title.strip():
                kept.append({"sid": sid, "title": title.strip()[:60],
                             "origin": _origin_from_caps(entry.get("capabilities") or {})})
                continue  # titled = 작업 중 세션 → 보존
            targets.append((h, sid, entry.get("live_pid")))
        killed, already_dead = [], []
        for h, sid, pid in targets:
            if pid and _pid_alive(int(pid)):
                try:
                    os.kill(int(pid), signal.SIGTERM)  # graceful — claude 자가 정리 후 종료
                    killed.append(pid)
                except (ProcessLookupError, PermissionError):
                    already_dead.append(pid)
            else:
                already_dead.append(pid)
            _live_dismiss_add(h, sid)  # SIGTERM 직후 마지막 heartbeat 재등록 차단
        pruned = 0
        with sessions_lock:
            for h, sid, _ in targets:
                if sessions.pop((h, sid), None) is not None:
                    pruned += 1
        if pruned:
            persist_sessions()
        log(f"POST /kill-empty-live — killed={len(killed)} already_dead="
            f"{len(already_dead)} pruned={pruned} kept={len(kept)}")
        self._send_json(200, {
            "status": "ok",
            "killed": killed,
            "killed_count": len(killed),
            "already_dead_count": len(already_dead),
            "pruned": pruned,
            # Issue359: 보존 내역을 함께 돌려준다. 0 이면 "판정이 또 낡았다" 는
            #   신호이므로 조용히 전멸하는 대신 즉시 드러난다.
            "kept_count": len(kept),
            "kept": kept,
        })

    def _handle_reap_orphan_live(self, parsed):
        """Issue331: origin=zed live 세션 중 orphan 을 종료·정리한다.
        판정 2축 — Zed 가 닫은 스레드(thread-archived, Issue360) + 브리지 사망.
        주기 리퍼(_orphan_reaper_loop)와 동일한 판정을 즉시 1회 수행.
        idle-ttl 판정은 2026-08-05 철회됨(살아있는 스레드 오살 — 상단 주석 참조).
        VSCode·터미널 세션은 판정 대상이 아니다(오살 방지). 127.0.0.1 trust."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        summary = _reap_zed_orphans()
        summary["status"] = "ok"
        summary["policy"] = "thread-archived+bridge-dead"
        self._send_json(200, summary)

    def _handle_clear_htm_docs(self, parsed):
        """Issue41: htm-registry.json 에서 항목 제거. ?keep=N → 파일 mtime 최신 N개 보존,
        나머지 hub 목록에서 제거. keep 미지정/0 → 전체 제거. 실제 .html 파일은
        삭제하지 않음 — hub 연결만 끊는다. 127.0.0.1 trust → 토큰 미요구.
        Issue53: 제거된 path 를 HTM_CLEARED tombstone 에 기록 — autoheal 이 feed
        버퍼에서 부활시키지 못하게 차단 (clear 무효화 방지)."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        qs = parse_qs(parsed.query)
        try:
            keep = int(qs.get("keep", ["0"])[0])
        except (TypeError, ValueError):
            keep = 0
        if keep < 0:
            keep = 0
        # Issue92: 디스크 권위적 tombstone — registry 미등록 orphan(.html) 도 함께
        #   tombstone 하여 clear 후 rescan/autoheal 부활을 원천 차단. registry_lock
        #   진입 전에 수집(내부적으로 projects_lock 사용 — lock 순서 projects→registry).
        disk_paths = self._all_disk_htm_paths()
        with registry_lock:
            entries = load_registry(HTM_REGISTRY)
            total = len(entries)
            # Issue352: 정렬 기준은 _htm_entry_mtime 단일 지점 (자동 prune 과 공용)
            entries.sort(key=_htm_entry_mtime, reverse=True)
            kept = entries[:keep] if keep > 0 else []
            removed = [e.get("path", "") for e in (entries[keep:] if keep > 0 else entries)]
            save_registry(HTM_REGISTRY, kept)
            # Issue53/92: 제거된 path + kept 제외 전 디스크 .html 을 tombstone 에 추가.
            #   kept path 는 해제, 디스크 부재 path 는 prune (무한 성장 차단).
            kept_paths = {e.get("path", "") for e in kept}
            cleared = set(load_registry(HTM_CLEARED))
            cleared |= {p for p in removed if p}            # registry-removed
            cleared |= {p for p in disk_paths if p}          # Issue92: orphan 포함 전 디스크
            cleared -= kept_paths
            cleared = {p for p in cleared if p and os.path.isfile(p)}
            save_registry(HTM_CLEARED, sorted(cleared))
        log(f"POST /clear-htm-docs — keep={keep} removed={len(removed)} "
            f"total={total} (registry 항목 제거, 파일 보존)")
        self._send_json(200, {
            "status": "ok",
            "keep": keep,
            "total": total,
            "removed_count": len(removed),
            "removed": removed,
            "errors": [],
            "note": "registry 항목만 제거 — 실제 파일은 보존됨",
        })

    def _handle_unregister_doc(self, parsed):
        """Issue49: hub 카드 '닫기' — 단일 registry 항목을 path 매칭으로 제거.
        clear-* 의 일괄 제거와 달리 카드 1건만 hub 목록에서 제거. 실제 파일은 보존.
        query: type=htm|dash, path=<abs>. 127.0.0.1 trust."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        qs = parse_qs(parsed.query)
        kind = (qs.get("type", [""])[0] or "").strip()
        path = (qs.get("path", [""])[0] or "").strip()
        if kind not in ("htm", "dash") or not path:
            self._send_json(400, {"error": "type must be htm|dash and path required"})
            return
        path = os.path.abspath(os.path.expanduser(path))
        reg_path = HTM_REGISTRY if kind == "htm" else DASH_REGISTRY
        tomb_path = HTM_CLEARED if kind == "htm" else DASH_CLEARED
        with registry_lock:
            entries = load_registry(reg_path)
            kept = [e for e in entries if e.get("path") != path]
            removed = len(entries) - len(kept)
            if removed:
                save_registry(reg_path, kept)
                # Issue54: 카드 닫기도 명시 제거 — tombstone 에 기록해 부활 차단.
                #   htm: autoheal 재등록 차단 / dash: rescan 재등록 차단.
                cleared = set(load_registry(tomb_path))
                if path not in cleared:
                    cleared.add(path)
                    save_registry(tomb_path, sorted(cleared))
        log(f"POST /unregister-doc — type={kind} path={path} removed={removed} "
            f"(registry 항목 제거, 파일 보존)")
        self._send_json(200, {
            "status": "ok", "type": kind, "path": path,
            "removed": removed,
            "note": "registry 항목만 제거 — 실제 파일은 보존됨",
        })

    @staticmethod
    def _dash_stale_limit(interval) -> float:
        """Issue403: running dash 의 mtime 정체 허용 상한(초).

        보드마다 갱신 주기가 다르므로 **고정 초 상수를 쓰지 않는다** — `interval` 의
        배수로 산출한다. `interval` 이 없거나 비정상(0·음수·비수치)이면 판정 기준이
        없으므로 기존 `DASH_STATUS_NONE_GRACE_SEC`(status 부재 경로와 같은 유예)을
        준용한다.

        ⚠️ 하한 클램프의 이유(오강등 방지) — interval 이 1~2초인 보드는 배수만 쓰면
        10~20초 정체로 강등된다. 스케줄 지연·mtime 초 해상도만으로도 넘는 값이라
        살아 있는 보드가 죽은 것으로 뒤집힌다. 여유는 **관대한 쪽으로만** 준다.
        """
        try:
            iv = float(interval)
        except (TypeError, ValueError):
            return float(DASH_STATUS_NONE_GRACE_SEC)
        if iv <= 0:
            return float(DASH_STATUS_NONE_GRACE_SEC)
        return max(iv * DASH_RUNNING_STALE_INTERVALS,
                   float(DASH_STATUS_NONE_GRACE_SEC))

    @staticmethod
    def _effective_dash_status(d) -> str:
        """dash dict 의 실효 status. Issue58: status='running' 이나 runner pid 가 죽었으면
        'stale' 로 강등. pid 가 정수가 아니면 검증 불가 → Issue403 이 mtime 정체로 판정.
        Issue83: _handle_dashboards(렌더)·_handle_clear_done(정리) 가 동일 판정을 쓰도록
        단일화 — 렌더 경로만 stale 강등하고 clear 경로는 디스크 raw status('running')를
        보던 비대칭 제거. 비대칭이 곧 Issue60 불완전 수정(stale 정리 버튼 무반응)의 원인."""
        status = d.get("status")
        if status == "running":
            # liveness pid: runner 는 pid 또는 worker_pid(큐/모니터 dashboard) 에 기록.
            #   한쪽만 검사하면 다른 필드에 기록한 runner 의 죽음을 놓쳐 'running' 이
            #   디스크에 박제된다 → 카드가 clear-done·dismiss 를 우회해 부활(2차 회귀
            #   경로). pid 가 정수면 pid, 아니면 worker_pid 로 fallback 검증.
            pid = d.get("pid")
            if not isinstance(pid, int):
                pid = d.get("worker_pid")
            if isinstance(pid, int):
                if not _pid_alive(pid):
                    return "stale"
                return status
            # Issue403: **pid 검증 불가** 경로. 종전엔 여기서 무조건 running 을 유지해
            #   한 번도 가동된 적 없는 템플릿(prj3 fbot-board-init.sh 는 runner 없이
            #   status='running' · pid=None 을 쓴다)이 며칠씩 "돌고 있다" 로 박제됐고,
            #   running 은 _is_clearable_status 가 False 라 정리 버튼도 안 먹었다.
            #   조합이 우연이 아니다 — prj3 board.md 계약(prj3#Issue142)이 순수 모니터링 모드에
            #   worker_pid 생략을 요구하므로 그 계약을 지킨 보드는 전부 이 경로로 온다.
            #   판정 근거는 mtime: 살아 있는 runner 는 interval 마다 데이터 파일을 다시
            #   쓰므로 mtime 이 전진한다(fpm-board-runner.sh 는 나아가 자기 pid 까지
            #   기록하므로 실가동 보드는 애초에 위 pid 분기에서 끝난다) → 여기까지 온
            #   보드의 mtime 정체는 runner 부재의 증거다. 강등 결과 'stale' 은
            #   _is_clearable_status 가 이미 포함하므로 "정리" 버튼이 그대로 먹는다
            #   (Issue83 이 없앤 렌더·정리 비대칭을 되살리지 않기 위해 분기 추가 없음).
            mtime_ts = d.get("mtime_ts")
            if isinstance(mtime_ts, (int, float)) and mtime_ts > 0 and \
                    (time.time() - mtime_ts) > \
                    Handler._dash_stale_limit(d.get("interval")):
                return "stale"
        elif status is None:
            # runner 가 첫 write 전에 죽으면(crash-loop) status 필드 자체가 없어
            # 'running'도 'done류'도 아니라 clear-done 이 영구 무시함(정리 버튼 무반응).
            # grace 경과 시 stale 로 강등해 정리 대상에 포함시킴.
            mtime_ts = d.get("mtime_ts")
            if isinstance(mtime_ts, (int, float)) and \
                    (time.time() - mtime_ts) > DASH_STATUS_NONE_GRACE_SEC:
                return "stale"
        return status

    @staticmethod
    def _is_clearable_status(status) -> bool:
        """clear 대상 판정. status 가 'done' 변형(ALL-DONE, all_done, done(...) 등) 또는
        'stopped'/'stop'/'stale' 인 경우 True. 'done' 토큰 경계 확인하여 'undone' false positive 차단.
        'stale' 은 Issue58 의 죽은-runner 강등 상태 — '정리' 버튼이 좀비 카드를 쓸어내도록 포함."""
        if not status:
            return False
        s = str(status).lower().strip()
        if s in ("done", "stopped", "stop", "stale"):
            return True
        import re as _re
        return bool(_re.search(r'(^|[^a-z])done([^a-z]|$)', s))

    def _handle_register_doc(self, parsed):
        """Issue41: 생산자(htm 스킬·dashboard runner)가 산출 파일을 hub registry 에 등록.
        body: {type:"htm"|"dash", path:"<abs>", cwd:"<abs>", title:"..."}.
        디렉토리 스캔을 대체하는 단일 등록 경로. 동일 path 재등록 시 갱신(dedup).
        127.0.0.1 trust → 토큰 미요구."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        kind = (body.get("type") or "").strip()
        path = (body.get("path") or "").strip()
        if kind not in ("htm", "dash") or not path:
            self._send_json(400, {"error": "type must be htm|dash and path required"})
            return
        path = os.path.abspath(os.path.expanduser(path))
        cwd = (body.get("cwd") or "").strip()
        cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else ""
        title = (body.get("title") or "").strip()
        # Issue75: dashboard SPA 세션 라우트(/s/{h}/{sid})용 sid. 영숫자·-·_ 만 허용.
        #   sid 보유 dash 카드는 파일 라우트 대신 세션 라우트로 "열기" 링크를 만들어
        #   /view confinement 와 무관하게 동작한다. 부재 시 종전 파일 라우트 fallback.
        sid = (body.get("sid") or "").strip()
        if sid and not re.fullmatch(r"[a-zA-Z0-9_-]+", sid):
            self._send_json(400, {"error": "sid must be alphanumeric with - or _ only"})
            return
        # Issue75: dash 파일 경로는 serve-root(cwd 하위 또는 /tmp/___pm 직속) 안이어야
        #   /view 파일 라우트로 serve 가능. 밖이면 hub 카드 "열기" 가 403 좀비가 됨 →
        #   등록 시점에 거부해 좀비 카드를 원천 차단. htm 등록은 별도 confinement → 제외.
        if kind == "dash":
            path_real = os.path.realpath(path)
            if cwd:
                in_scope = path_within_serve_roots(path_real, os.path.realpath(cwd))
            else:
                # cwd 미상(tmp dash) — TMP_OUT_DIR 직속 flat 파일만 허용
                in_scope = os.path.dirname(path_real) == os.path.realpath(TMP_OUT_DIR)
            if not in_scope:
                log(f"POST /register-doc REJECT — dash path outside serve-root: "
                    f"{path} (cwd={cwd or '(none)'})")
                self._send_json(400, {
                    "error": "dash path outside serve-root (cwd subtree or /tmp/___pm)",
                    "path": path})
                return
            # Issue309: dash stored path 를 realpath 로 통일. _auto_register_dash(/notify)
            #   가 realpath 저장이라, abspath 로 저장하면 macOS /tmp↔/private/tmp symlink
            #   에서 표기가 갈려 dedup 이 실패 → 같은 파일이 카드 2장으로 뜬다.
            path = path_real
        reg_path = HTM_REGISTRY if kind == "htm" else DASH_REGISTRY
        tomb_path = HTM_CLEARED if kind == "htm" else DASH_CLEARED
        with registry_lock:
            entries = [e for e in load_registry(reg_path) if e.get("path") != path]
            entry = {
                "path": path, "cwd": cwd, "title": title,
                "registered_at": time.time(),
            }
            if sid:
                entry["sid"] = sid  # Issue75: SPA 세션 라우트 식별자
            entries.append(entry)
            save_registry(reg_path, entries)
            count = len(entries)
            # Issue54: 생산자(htm 스킬·dashboard runner)의 명시 재등록은 recover 의미
            #   — tombstone 에서 해제해 정상 노출 복귀.
            cleared = set(load_registry(tomb_path))
            if path in cleared:
                cleared.discard(path)
                save_registry(tomb_path, sorted(cleared))
        log(f"POST /register-doc — type={kind} path={path} (registry={count})")
        # Issue194: hub-internal 모드면 hub 쉘에 tab-open push (OS 새 탭 대신 내부 iframe 탭).
        #   render_tab_mode 는 서버가 yml 직독(설계 FIXME 채택 — hook 변경 불요로 MVP 성립).
        if kind == "htm" and _load_hub_setting().get("render_tab_mode") == "hub-internal":
            base = os.path.basename(path)
            # 파일명 mode 토큰(_a_/_b_/_c_)으로 content_type 도출 (R3 단축키 노출 판정용)
            ctype = "response"
            if "_b_" in base:
                ctype = "form"
            elif "_c_" in base:
                ctype = "dashboard"
            import urllib.parse as _u
            # Issue248 잔여: hub-shell 탭 dedup 은 view_url 문자열 완전일치 기준(프론트 addTab).
            #   여기서 항상 "/htm-doc?path=..." 로 broadcast 했으나, /boards 폴링 fallback
            #   (_collect_htm_docs, Issue199)은 프로젝트에 token 이 있으면 "/view?cwd=&token=&path="
            #   형식을 쓴다 — 같은 문서인데 두 view_url 이 달라 dedup 이 깨져 탭이 2개로 중복됐다.
            #   /boards 와 동일한 token 유무 분기로 view_url 을 맞춘다.
            cwd_q = cwd
            token = ""
            if cwd_q:
                h = cwd_hash(cwd_q)
                with projects_lock:
                    p = projects.get(h)
                token = (p or {}).get("token", "")
            if path.endswith(".md"):
                # Issue353_1: md 산출은 md 셸 라우트로 broadcast (/view·/htm-doc 는 302 우회 발생)
                view_url = "/md-doc?path=" + _u.quote(path)
            elif token:
                view_url = (f"/view?cwd={_u.quote(cwd_q)}&token={token}"
                            f"&path={_u.quote(path)}")
            else:
                view_url = "/htm-doc?path=" + _u.quote(path)
            sse_broadcast(HUB_SHELL_HASH, "tab-open", {
                "view_url": view_url,
                "title": title or base,
                "sid": sid,
                "content_type": ctype,
            })
        self._send_json(200, {"status": "ok", "type": kind, "path": path, "count": count})

    # ── Issue194: hub 내부 탭 쉘 ─────────────────────────────────────────
    def _hub_holder_alive(self, ip):
        """Issue209: 이 host(ip)에 살아있는 hub-shell lease 보유자가 있는가.
        단일 창 모드(hub_single_window) off → 다중 쉘 허용이라 충돌 없음 → False(종전 302).
        on 이면 lease 보유자의 last_seen 이 ttl 이내(heartbeat 15s 갱신)일 때만 alive."""
        setting = _load_hub_setting()
        if not bool(setting.get("hub_single_window", True)):
            return False
        ttl = int(setting.get("hub_lease_ttl", 30))
        with hub_lease_lock:
            cur = hub_lease.get(ip)
            if not cur:
                return False
            return (time.time() - cur.get("last_seen", 0)) <= ttl

    def _hub_lease_acquire(self, ip, cid, single, ttl):
        """host(ip) 단일 창 리스 획득 시도. single=False 면 항상 grant.
        리스 없음·본인 보유·TTL 만료 → grant. 타인 활성 보유 → 거부(False)."""
        if not single:
            return True
        now = time.time()
        with hub_lease_lock:
            cur = hub_lease.get(ip)
            if (cur is None or cur.get("client_id") == cid
                    or (now - cur.get("last_seen", 0)) > ttl):
                hub_lease[ip] = {"client_id": cid, "granted_at": now, "last_seen": now}
                return True
            return False

    def _handle_hub_events(self, parsed):
        """Issue194: hub 쉘 전용 SSE. cwd+token 없는 host-trusted 채널(전역 IP 게이트로 보호).
        lease 판정 → granted/denied → tab-open relay + keepalive heartbeat(last_seen 갱신).
        타 client 인계(/hub-claim) 시 heartbeat 가 evicted 감지하여 스트림 종료."""
        ip = self.client_address[0] if self.client_address else ""
        qs = parse_qs(parsed.query)
        cid = (qs.get("cid") or [""])[0].strip()
        if not cid or not re.fullmatch(r"[a-zA-Z0-9_-]+", cid):
            self._send_json(400, {"error": "missing/invalid cid"})
            return
        setting = _load_hub_setting()
        single = bool(setting.get("hub_single_window", True))
        ttl = int(setting.get("hub_lease_ttl", 30))
        granted = self._hub_lease_acquire(ip, cid, single, ttl)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Access-Control-Allow-Origin", self._acao())
            self.end_headers()
            info = {}
            if not granted:
                with hub_lease_lock:
                    cur = dict(hub_lease.get(ip, {}))
                info = {"holder": cur.get("client_id", ""),
                        "age": round(time.time() - cur.get("granted_at", time.time()))}
            ev = "granted" if granted else "denied"
            self.wfile.write(f"event: {ev}\ndata: {json.dumps(info)}\n\n".encode("utf-8"))
            self.wfile.flush()
        except Exception:
            return
        if not granted:
            return  # 거부: shell 이 denied 수신 후 takeover UI 표시 → 스트림 불요
        key = (HUB_SHELL_HASH, cid)
        with sse_lock:
            sse_subscribers.setdefault(key, []).append(self.wfile)
        log(f"hub-shell SSE connect — ip={ip} cid={cid}")
        try:
            while True:
                time.sleep(15)
                if single:
                    with hub_lease_lock:
                        cur = hub_lease.get(ip)
                        if not cur or cur.get("client_id") != cid:
                            break  # 인계됨(evicted) → 스트림 종료
                        cur["last_seen"] = time.time()
                # Issue378: 모드 자기교정(서버 주도). 쉘이 살아 있는 동안 render_tab_mode 가
                #   hub-internal 을 벗어나면 이 쉘은 그 순간부터 무효 표면이다 — Issue377 의
                #   302 는 새 요청에만 걸리므로 여기서 능동 통지하지 않으면 사용자가 수동
                #   새로고침할 때까지 무효 표면이 살아 tab-open 을 계속 받는다(중복 표면 재발).
                #   keepalive 편승이라 추가 연결·주기 0, 반응은 최대 15초.
                if _load_hub_setting().get("render_tab_mode") != "hub-internal":
                    self.wfile.write(b'event: mode-change\ndata: {"dest": "/hub"}\n\n')
                    self.wfile.flush()
                    break   # 클라가 이동한다 → 스트림 유지 불요
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with sse_lock:
                subs = sse_subscribers.get(key, [])
                if self.wfile in subs:
                    subs.remove(self.wfile)
            with hub_lease_lock:
                cur = hub_lease.get(ip)
                if cur and cur.get("client_id") == cid:
                    del hub_lease[ip]
            log(f"hub-shell SSE disconnect — ip={ip} cid={cid}")

    def _handle_hub_claim(self, parsed):
        """Issue194: 단일 창 강제 시 2번째 창의 명시 인계. 기존 보유자 lease 회수 +
        evicted push(기존 창 안내 전환) → 신규 client 에 grant."""
        ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        cid = (body.get("cid") or "").strip()
        if not cid or not re.fullmatch(r"[a-zA-Z0-9_-]+", cid):
            self._send_json(400, {"error": "missing/invalid cid"})
            return
        now = time.time()
        with hub_lease_lock:
            old = hub_lease.get(ip)
            old_cid = old.get("client_id") if old else None
            hub_lease[ip] = {"client_id": cid, "granted_at": now, "last_seen": now}
        if old_cid and old_cid != cid:
            sse_broadcast(HUB_SHELL_HASH, "evicted", {}, sid=old_cid)
        log(f"hub-shell claim — ip={ip} new_cid={cid} old_cid={old_cid}")
        self._send_json(200, {"status": "claimed"})

    def _handle_mq_ack(self, parsed):
        """Issue420: /mq 페이지의 처리 액션을 **tick 이 읽는 inbox 계약 그대로** 접수한다.

        경로·형식이 기존 폼(`hub_htm_*_b_aoa-mq-ask.htm` → POST /answer?sid=aoa-mq)과 같다:
          `{INBOX_ROOT}/{cwd_hash(큐 소유 cwd)}/aoa-mq/{ts}.json`
          `[{"question":"aoa-mq-ack:<id>:<action>[:<arg>]","answers":[<action>]}]`
        tick 의 consume_inbox() 가 이 시그니처만 소비하므로 별도 종결 경로가 생기지 않는다.

        ⚠️ **여기서 큐 파일을 직접 고치지 않는다.** 상태 전이는 tick 의 finalize() 단일
        지점이 소유한다 — 두 곳이 쓰면 ack_count·status 가 조용히 갈라진다.
        """
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
        except Exception as e:
            self._send_json(400, {"ok": False, "error": "본문 파싱 실패: %s" % e})
            return
        q = (payload or {}).get("question", "")
        if not isinstance(q, str) or not q.startswith("aoa-mq-ack:"):
            self._send_json(400, {"ok": False, "error": "시그니처 불일치(aoa-mq-ack: 필요)"})
            return
        parts = q.split(":")
        if len(parts) < 3 or not parts[1] or parts[2] not in (
                "start", "confirm", "dismiss", "ack", "defer", "snooze"):
            self._send_json(400, {"ok": False, "error": "action 이 유효하지 않음: %s" % q})
            return
        # 큐 소유 cwd = MQ_DIR 에서 `/data/aoa/mq` 를 걷어낸 것. tick 이 register 하는 cwd 와 같다.
        owner = os.path.abspath(os.path.join(MQ_DIR, "..", "..", ".."))
        inbox = os.path.join(INBOX_ROOT, cwd_hash(owner), "aoa-mq")
        try:
            os.makedirs(inbox, exist_ok=True)
            fp = os.path.join(inbox, "%d-%s.json" % (int(time.time() * 1000), parts[1]))
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump([{"question": q, "answers": [parts[2]]}], fh, ensure_ascii=False)
        except OSError as e:
            self._send_json(500, {"ok": False, "error": "inbox 기록 실패: %s" % e})
            return
        # Issue423: 접수 직후 consume 단계만 동기로 태운다.
        #   종전엔 정규 tick(5분 주기 · 1회 약 3분)이 소비할 때까지 목록이 그대로여서
        #   "눌렀는데 아무 일도 안 일어난다" 로 보였다. `--consume-only` 는 상태 전이
        #   로직을 복제하지 않고 **같은 consume_inbox() 를 태우므로** 소유는 tick 하나다.
        #   실측 1.6s — HTTP 요청 안에서 기다릴 수 있는 범위다. 실패해도 접수는 이미
        #   끝났으므로 200 을 유지하고 `consumed:false` 로만 알린다(정규 tick 이 뒤에 소비).
        #   timeout 8s 인 이유: 정규 tick(약 3분)이 돌고 있으면 mkdir 락에서 대기하는데,
        #   그 경우 더 기다려도 어차피 못 잡는다. 빨리 포기하고 "접수됨" 으로 답하는 편이
        #   낫다 — 실제로 정규 tick 중 클릭하니 버튼이 멈춘 채로 남았다(2026-08-30 실측).
        consumed = False
        try:
            r = subprocess.run(["/bin/bash", AOA_MQ_TICK, "--consume-only"],
                               capture_output=True, timeout=8)
            consumed = (r.returncode == 0)
        except (OSError, subprocess.SubprocessError):
            consumed = False
        self._send_json(200, {"ok": True, "queued": q, "inbox": fp, "consumed": consumed,
                              "note": ("상태 전이 완료" if consumed
                                       else "접수됨 — 다음 tick 이 소비한다")})

    def _handle_mq_page(self, parsed):
        """Issue420: aoa-mq 전용 관리 페이지. 목록만 있던 종전 mq_list_*.htm 과 달리
        필터(속성·키워드)·정렬·처리 액션을 갖춘다.

        🔑 ack 는 **기존 `/answer?sid=aoa-mq` 를 재사용**한다. tick 의 consume_inbox() 가
        `aoa-mq-ack:<id>:<action>[:<arg>]` 시그니처를 소비하므로, 여기서 별도 종결 API 를
        만들면 배관이 둘로 갈라져 어느 쪽이 정본인지 알 수 없게 된다.
        ⚠️ 액션은 **즉시 종결이 아니다** — inbox 에 접수되고 다음 tick 이 소비한다.
        화면이 "접수됨"과 "종결됨"을 구분해 보여야 사용자가 눌렀는데 안 변한다고 오해하지 않는다.
        """
        body = _MQ_PAGE_HTML
        enc = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(enc)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(enc)

    def _handle_hub_shell(self, parsed):
        """Issue194: hub 내부 탭 쉘 페이지. 탭 바 + iframe viewport. /hub-events SSE 로
        tab-open 수신 → iframe 탭 생성. tab_close_shortcut 으로 렌더 탭만 닫기(R3)."""
        setting = _load_hub_setting()
        # Issue377: 역방향 funnel. render_tab_mode 가 표면을 결정한다는 계약은 **양방향**이어야
        #   하는데 지금까지 `hub-internal → /hub → /hub-shell`(Issue213, _handle_hub) 한쪽만
        #   있었다. browser-tab 에서 /hub-shell 을 열면 "쓰지 않기로 한 쉘"이 200 으로 뜨고,
        #   그 쉘이 /hub-events 의 tab-open 을 받아 내부 탭을 만드는 동안 hook 은 같은 모드라
        #   OS 새 탭도 연다 → 같은 문서가 두 표면에 중복(사용자 혼란 보고).
        #   → browser-tab 이면 쉘 진입 자체를 /hub 로 되돌려 유효 표면을 1개로 유지한다.
        #   루프 불가: 두 가드의 조건이 배타(`== hub-internal` vs `!= hub-internal`).
        #   쿼리는 전달하지 않는다 — `_shell=1` 이 넘어가면 /hub 가 embed 로 오인해 정방향
        #   가드를 건너뛴다(자기 iframe 용 마커를 top-level 진입에 재사용하게 됨).
        if setting.get("render_tab_mode") != "hub-internal":
            self.send_response(302)
            self.send_header("Location", "/hub")
            self.end_headers()
            return
        shortcut = str(setting.get("tab_close_shortcut", "alt+w"))
        single = "true" if setting.get("hub_single_window", True) else "false"
        html = HUB_SHELL_HTML.replace("__SHORTCUT__", json.dumps(shortcut)) \
                             .replace("__SINGLE__", single)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_hub_rescan(self, parsed):
        """Issue41: 수동 부트스트랩. 등록 프로젝트의 htm 폴더(Issue289: HTM_DIRS 전체) + /tmp/___pm 를 1회 스캔하여
        registry 에 누락된 htm/dash 산출물을 수거(merge, dedup). 자동 호출 없음 —
        hub 의 명시적 버튼 클릭으로만 트리거되는 사용자 액션. 127.0.0.1 trust.
        Issue55: htm 스캔은 HTM_CLEARED tombstone 을 skip(부활 차단, dash 측 Issue54 대칭),
        search_limit 으로 디렉토리당 처리 파일 수를 상한."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        with projects_lock:
            snap = list(projects.items())
        now = time.time()
        # Issue55: 전체 제거한 htm 은 재스캔으로 부활시키지 않음. tombstone skip set
        #   으로 _scan_htm_docs_in 후보에서 제외 — 해제는 register-doc(생산자) 전용.
        with registry_lock:
            htm_skip = set(load_registry(HTM_CLEARED))
        search_limit = _load_hub_setting()["search_limit"]
        dash_found, htm_found = [], []
        for h, p in snap:
            cwd = p.get("cwd", "")
            if not (cwd and os.path.isdir(cwd)):
                continue
            for d in self._scan_dashes(cwd):
                dash_found.append({"path": d["path"], "cwd": cwd,
                                   "title": d.get("title") or "", "registered_at": now})
            for doc in self._scan_htm_docs(cwd, htm_skip, search_limit):
                htm_found.append({"path": doc["path"], "cwd": cwd,
                                  "title": doc.get("title") or "", "registered_at": now})
        for d in self._scan_tmp_dashes():
            dash_found.append({"path": d["path"], "cwd": "",
                               "title": d.get("title") or "", "registered_at": now})
        for doc in self._scan_tmp_htm_docs(htm_skip, search_limit):
            htm_found.append({"path": doc["path"], "cwd": "",
                              "title": doc.get("title") or "", "registered_at": now})
        added = {}
        with registry_lock:
            dash_tomb = set(load_registry(DASH_CLEARED))
            for kind, reg_path, found in (("dash", DASH_REGISTRY, dash_found),
                                          ("htm", HTM_REGISTRY, htm_found)):
                entries = load_registry(reg_path)
                existing = {e.get("path") for e in entries}
                n = 0
                for f in found:
                    # Issue54: 명시 닫힌 dash 는 rescan 으로 부활시키지 않는다
                    #   (htm 과 달리 recover 안 함 — 해제는 생산자 register-doc 전용).
                    if kind == "dash" and f["path"] in dash_tomb:
                        continue
                    if f["path"] not in existing:
                        entries.append(f)
                        existing.add(f["path"])
                        n += 1
                if n:
                    save_registry(reg_path, entries)
                added[kind] = n
        log(f"POST /hub-rescan — added htm={added['htm']} dash={added['dash']}")
        self._send_json(200, {"status": "ok", "added": added})

    def _handle_hook_event(self, parsed):
        """Issue42: Claude Code hook 이벤트 수신 → 활동 피드 버퍼에 newest-first 적재.
        body: {event, cwd, summary, detail, ts}. project_meta(cwd) 로 name·color 보강.
        127.0.0.1 trust → 토큰 미요구. body 64KiB 상한 (_read_json_body 기본)."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        event = (body.get("event") or "").strip()
        cwd = (body.get("cwd") or "").strip()
        if not event:
            self._send_json(400, {"error": "event required"})
            return
        if not cwd:
            self._send_json(400, {"error": "cwd required"})
            return
        cwd = os.path.abspath(os.path.expanduser(cwd))
        meta = project_meta(cwd)
        now = time.time()
        item = {
            "event": event,
            "cwd": cwd,
            "cwd_hash": meta["cwd_hash"],
            "name": meta["name"],
            "color": meta["color"],
            "emoji": meta["emoji"],
            "summary": (body.get("summary") or "").strip()[:300],
            "detail": (body.get("detail") or "").strip()[:8000],
            "ts": int(body.get("ts") or now),
            "id": str(int(now * 1000)),
        }
        with feed_lock:
            buf = _feed_buffer_synced()
            buf.appendleft(item)
            count = len(buf)
        persist_feed()
        # Issue132: session_end → 해당 live 세션 즉시 prune. 종전엔 SessionEnd 훅이
        #   event=session_end + sid 를 보내도 본 핸들러가 피드에만 적재하고 sessions
        #   테이블은 건드리지 않아, VSCode 가 세션 종료 후에도 claude 프로세스를 살려두면
        #   (_pid_alive True) live 카드가 영구 잔존했다. sid 단위로 entry 를 제거해
        #   SessionEnd 훅을 실효화한다 (pid kill 아님 — 등록 해제만).
        if event == "session_end":
            sid = str(body.get("sid", "")).strip()
            if sid:
                h = cwd_hash(cwd)
                with sessions_lock:
                    pruned = sessions.pop((h, sid), None) is not None
                if pruned:
                    persist_sessions()
                    log(f"POST /hook-event — session_end pruned live session hash={h} sid={sid}")
        # Issue353_3 M3: Stop(턴 종료) 시점에 서버가 **메일박스를 실측해** 이번 턴이
        #   아카이브 임계를 넘는지 판정하고, 넘으면 최종본 md 를 자동 생성한다.
        #   판정 주체가 LLM 이 아니라 규칙 엔진이므로 지시문 드리프트가 없다.
        gate = None
        if event in ("stop", "session_stop", "turn_end"):
            sid = str(body.get("sid", "")).strip()
            if sid:
                # `..show`/`..text` 턴 단발 오버라이드 — 훅이 실어 보내면 설정보다 우선.
                # 사용자 의사가 임계 판정을 이긴다(arch G안 오버라이드 규약).
                override = str(body.get("render_override", "")).strip().lower()
                if override not in ("show", "text"):
                    override = ""
                gate = self._archive_turn_if_over_threshold(cwd, sid, override)
        log(f"POST /hook-event — event={event} cwd={cwd} (feed={count})")
        out = {"status": "ok", "count": count}
        if gate:
            out["gate"] = gate
        self._send_json(200, out)

    def _archive_turn_if_over_threshold(self, cwd: str, sid: str, override: str = ""):
        """Issue353_3 M3: 턴 종료 시 게이트 판정 + 임계 초과 시 아카이브 md 생성.

        게이트 재료는 **메일박스 실측**이다(M2 전제). 이번 턴 범위는 마지막 `turn`
        블록 이후의 블록들이며, 그 안의 assistant 텍스트만 분량·리치 요소 판정에 쓴다.

        표시 모드별 효과(arch 1.2):
        * `live-tab`  — 라이브 뷰는 이미 상시 표시 중이므로 게이트는 **아카이브 생성
          여부**만 정한다.
        * `browser-tab` — 임계를 넘은 **이 시점에** 문서를 만들고 그 URL 을 돌려준다
          (턴 시작 일괄 오픈 없음 → 선오픈·후생략 모순이 생기지 않는다).

        실패는 전부 fail-soft 다 — 아카이브가 없다고 사용자의 턴이 막히면 안 된다.
        """
        try:
            path = _resolve_session_jsonl(cwd, sid)
            if not path:
                return None
            box = mailbox.get_box(cwd_hash(cwd), sid, path)
            if box.changed():
                box.sync()
            blocks = list(box.blocks)
            # 이번 턴 = 마지막 turn 마커 이후
            last_turn_idx = -1
            for i in range(len(blocks) - 1, -1, -1):
                if blocks[i].get("kind") == "turn":
                    last_turn_idx = i
                    break
            turn_blocks = blocks[last_turn_idx + 1:] if last_turn_idx >= 0 else blocks
            question = blocks[last_turn_idx]["text"] if last_turn_idx >= 0 else ""
            setting = _load_hub_setting()
            level = setting.get("auto_render", "page")
            decision = render_gate.decide(turn_blocks, level,
                                          created_docs=self._turn_doc_count(cwd),
                                          override=override)
            result = {"render": decision["render"], "reason": decision["reason"],
                      "level": decision["level"], "lines": decision["metrics"]["lines"]}
            if not decision["render"]:
                log(f"POST /hook-event — gate skip ({decision['reason']}) cwd={cwd}")
                return result
            out = self._write_turn_archive(cwd, sid, question, turn_blocks)
            if out:
                result["archive"] = out
                log(f"POST /hook-event — gate archive ({decision['reason']}): {out}")
            return result
        except Exception as e:                     # fail-soft — 턴을 막지 않는다
            log(f"POST /hook-event — gate failed (무시): {e}", "WARNING")
            return None

    def _turn_doc_count(self, cwd: str) -> int:
        """`doc` 단계 재료 — 이번 턴에 생성·갱신된 문서 산출물 수(최근 5분 내 registry).

        registry 는 생산자가 `register-doc` 로 등록한 것만 담으므로, 여기서 세는 것은
        **hub 에 노출된 산출물**이다. 임의 파일 생성을 훑지 않는다(권한·성능 양쪽 이유).
        """
        try:
            now = time.time()
            with registry_lock:
                entries = load_registry(HTM_REGISTRY)
            n = 0
            for e in entries:
                if e.get("cwd") != cwd:
                    continue
                p = e.get("path") or ""
                try:
                    if p and os.path.isfile(p) and now - os.path.getmtime(p) < 300:
                        n += 1
                except OSError:
                    continue
            return n
        except Exception:
            return 0

    def _write_turn_archive(self, cwd: str, sid: str, question: str, blocks) -> str:
        """턴 최종본을 md 아카이브로 저장하고 `/register-doc` 와 같은 경로로 등록.

        경로·파일명은 htm 수명주기 규약을 그대로 따른다(`_doc_work/htm/hub_htm_*`) —
        `doc-work-archive` 스킬의 age·keep-N 정리 대상에 자동으로 포함되기 위해서다.
        별도 수명주기를 만들면 정리되지 않는 파일 더미가 생긴다.
        """
        # Issue394: 파일로 굳기 **전에** 토큰을 지운다. 라이브 뷰 URL(`?token=…`)이
        # 응답 본문에 섞이면 아카이브가 곧 자격증명 파일이 된다 — 실측 2건 발생.
        texts = [redact_tokens(b.get("text", "")) for b in blocks if b.get("kind") == "text"]
        if not texts:
            return ""
        out_dir = os.path.join(cwd, "_doc_work", "htm")
        if not os.path.isdir(out_dir):
            return ""      # htm 폴더가 없는 프로젝트 — 생성하지 않는다(pm-check 소관)
        # 파일명 유일성 — 초 단위 timestamp 만으로는 같은 초에 끝난 두 턴이 같은 이름을
        # 얻어 앞의 것이 덮인다. seq 는 **세션별** 카운터라 세션이 다르면 또 겹치므로
        # (실측: 두 픽스처 세션이 나란히 seq=2) sid 조각까지 넣어야 유일해진다.
        ts = time.strftime("%Y%m%d_%H%M%S")
        last_seq = blocks[-1].get("seq", 0) if blocks else 0
        sid_frag = re.sub(r"[^A-Za-z0-9]", "", sid)[:8] or "sess"
        name = f"hub_htm_{ts}_a_turn-{sid_frag}-{last_seq}.md"
        path = os.path.join(out_dir, name)
        # title 도 사용자 입력 유래라 같은 그물을 통과시킨다 (frontmatter 로도 파일에 남는다)
        title = redact_tokens((question or "세션 턴 기록").strip().replace("\n", " "))[:80]
        head = (f"---\ntitle: {title}\nsid: {sid}\n---\n\n"
                f"> 이 문서는 hub 서버가 턴 종료 시 자동 생성한 아카이브입니다"
                f" (Issue353_3 렌더 게이트).\n\n")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(head + "\n\n".join(texts) + "\n")
        except OSError as e:
            log(f"gate archive write failed: {e}", "WARNING")
            return ""
        with registry_lock:
            entries = [e for e in load_registry(HTM_REGISTRY) if e.get("path") != path]
            entries.append({"path": path, "cwd": cwd, "title": title,
                            "registered_at": time.time(), "sid": sid})
            save_registry(HTM_REGISTRY, entries)
        return path

    def _handle_feed_clear(self, parsed):
        """활동 피드 비우기 — feed_buffer deque + hook-feed.json 디스크 영속 모두 반영.
        ?keep=N 지정 시 newest-first 기준 최신 N개를 보존하고 나머지만 제거,
        keep 미지정/0 → 전체 비움. 127.0.0.1 trust → 토큰 미요구."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        qs = parse_qs(parsed.query)
        try:
            keep = int(qs.get("keep", ["0"])[0])
        except (TypeError, ValueError):
            keep = 0
        if keep < 0:
            keep = 0
        with feed_lock:
            buf = _feed_buffer_synced()
            total = len(buf)
            if keep > 0:
                # deque 는 newest-first → 앞쪽 keep 개가 최신.
                kept = list(buf)[:keep]
                removed = total - len(kept)
                buf.clear()
                buf.extend(kept)
            else:
                removed = total
                buf.clear()
        persist_feed()
        log(f"POST /feed-clear — keep={keep} removed={removed} total={total} "
            f"(feed 버퍼 + hook-feed.json 반영)")
        self._send_json(200, {
            "status": "ok", "keep": keep, "total": total, "removed_count": removed,
        })

    def _handle_ob_open(self, parsed):
        """Issue266: 채팅 http 링크 → Obsidian 점프 브리지 (prj3 ob-* SCAR 보고 링크용).
        VSCode 채팅 webview 는 obsidian:// 커스텀 스킴 앵커를 차단하므로
        http://localhost:9876/ob?path=<절대경로> 를 대신 노출하고, 서버가
        host-local `open "obsidian://open?path=..."` 를 실행해 Obsidian 을 연다.
        (Simple Browser 가 obsidian:// redirect 를 막을 수 있어 302 대신 직접 open.)
        보안: loopback only + $HOME 하위 실존 파일만 허용 (임의 경로 open 차단)."""
        client_ip = self.client_address[0] if self.client_address else ""
        if client_ip not in LOOPBACK_IPS:
            self._send_json(403, {"error": "loopback only"})
            return
        qs = parse_qs(parsed.query or "")
        raw = (qs.get("path", [""])[0] or "").strip()
        if not raw:
            self._send_json(400, {"error": "path required"})
            return
        target = os.path.abspath(os.path.expanduser(raw))
        home = os.path.expanduser("~")
        if not target.startswith(home + os.sep):
            self._send_json(403, {"error": "path outside home"})
            return
        if not os.path.isfile(target):
            self._send_json(404, {"error": "file not found"})
            return
        uri = "obsidian://open?path=" + quote(target)
        try:
            subprocess.Popen(_open_cmd(uri),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log(f"GET /ob — {target}")
        page = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Obsidian으로 이동</title></head>"
            '<body style="font:14px/1.6 -apple-system,sans-serif;padding:2em">'
            f"<p>Obsidian으로 열었음: <code>{html.escape(target)}</code></p>"
            "<p style='color:#888'>이 탭은 닫아도 됨.</p>"
            "<script>setTimeout(function(){window.close()},1500)</script>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def _handle_open_project(self, parsed):
        """Issue42: 피드 항목 제목 클릭 → 해당 프로젝트를 VSCode 로 연다 (cdfv 효과 재현).
        cwd 는 Projects.md 등록 경로 또는 서버 projects 레지스트리 경로일 때만 허용 —
        localhost trust 라도 임의 경로 open 차단. 127.0.0.1 trust → 토큰 미요구."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        cwd = (body.get("cwd") or "").strip()
        if not cwd:
            self._send_json(400, {"error": "cwd required"})
            return
        cwd = os.path.abspath(os.path.expanduser(cwd)).rstrip("/")
        # 화이트리스트: Projects.md 등록 경로 ∪ 서버 projects 레지스트리 경로
        allowed = set(_load_projects_colors().keys())
        with projects_lock:
            allowed.update((p.get("cwd", "") or "").rstrip("/") for p in projects.values())
        if cwd not in allowed:
            self._send_json(403, {"error": "cwd not in registered projects"})
            return
        if not os.path.isdir(cwd):
            self._send_json(404, {"error": "cwd not a directory"})
            return
        # 서브폴더 cwd(ex: unity_base/Examples) 는 등록 프로젝트 루트로 정규화 후 오픈.
        #   원본 cwd 그대로 `open -a VSCode`에 넘기면 이미 열린 루트 워크스페이스 창을
        #   "이미 열림"으로 인식 못 하고 별도 새 창을 띄운다 — 다른 프로젝트가 열린 것처럼 보이는
        #   원인(hub 카드는 _resolve_project_root 로 루트 이름·색을 표시하는데 open 은 원본 cwd 사용).
        matched_root = _resolve_project_root(cwd)
        open_cwd = os.path.expanduser(matched_root.get("path", "")).rstrip("/") if matched_root else ""
        if not open_cwd or not os.path.isdir(open_cwd):
            open_cwd = cwd
        # Issue237: 비루프백 클라이언트 + alias 설정 시 서버 host-local `open` 대신
        #   vscode-remote:// URI 반환 → 브라우저(같은 머신의 VSCode)가 Remote-SSH 창 재사용해 연다.
        if client_ip not in LOOPBACK_IPS:
            alias = (_load_hub_setting().get("ssh_remote_alias") or "").strip()
            if alias:
                uri = _ssh_remote_uri(open_cwd, alias)
                log(f"POST /open-project — remote client={client_ip} → {uri}")
                self._send_json(200, {"status": "remote", "uri": uri, "cwd": open_cwd})
                return
        try:
            subprocess.Popen(_open_cmd(open_cwd, _editor_app_name()),  # Issue327
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log(f"POST /open-project — cwd={cwd} open_cwd={open_cwd}")
        self._send_json(200, {"status": "opened", "cwd": open_cwd})

    def _handle_open_prj(self, parsed):
        """Issue294: 프로젝트 맵 노드 클릭 → VSCode 로 그 프로젝트 열기 (GET 브리지).

        왜 POST `/open-project` 를 쓰지 않고 GET 을 새로 두는가 — 맵은 mermaid 가
        렌더하는 SVG 이고, 노드 링크는 `<a href>` 하나로만 표현된다(폼·JS 훅 없음).
        게다가 mermaid 는 `securityLevel: strict` 라 `vscode://` 같은 커스텀 스킴을
        sanitize 하므로 http 앵커여야 한다 — `/ob` 브리지와 같은 해법.

        입력면: **prj 번호 하나뿐**. 경로는 서버가 `projects/<id>` 인덱스에서 조회하므로
        클라이언트가 경로를 넘길 방법이 없다(traversal 불가).

        Issue317(Issue284_2 재발): 애초 `/ob`·`/open-session` 과 같은 loopback 전용
        등급으로 묶었으나, `/open-project`(Issue42/237)는 동일하게 host-local `open`
        을 실행하면서도 `_ip_allowed()`(bind self·allowlist 포함) + 비루프백일 때
        `ssh_remote_alias` 원격 URI 폴백을 쓴다. bind_host 를 비루프백(예: host-1.local
        LAN IP)으로 연 사용자가 `/projects-map` 페이지 자체는 `_ip_allowed()` 로 열람
        가능한데, 정작 노드 클릭(`/open-prj`)만 strict loopback 이라 403 — 페이지는
        뜨고 클릭만 죽는 오작동. `/open-project` 와 동일한 게이트+폴백으로 통일한다.
        """
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        qs = parse_qs(parsed.query or "")
        raw = (qs.get("id", [""])[0] or "").strip()
        # Issue303: 정수 id + 접미 id(9a / 9a1). 패턴이 곧 traversal 방어 —
        # `/`·`.` 이 문법에 없으므로 통과한 값은 경로 조각으로 안전하다.
        if not _PID_RE.match(raw):
            self._send_json(400, {"error": "id must match <int>[<letter>[<int>]] (e.g. 15 or 9a)"})
            return
        idx = os.path.join(REPO_ROOT, "projects", raw)
        if not os.path.isfile(idx):
            self._send_json(404, {"error": f"prj{raw} not registered"})
            return
        try:
            with open(idx, encoding="utf-8") as f:
                target = os.path.expanduser(f.read().strip()).rstrip("/")
        except OSError as e:
            self._send_json(500, {"error": f"index read failed: {e}"})
            return
        if not target or not os.path.isdir(target):
            self._send_json(404, {"error": f"path not found: {target}"})
            return
        # Issue317: /open-project(Issue237) 와 동일 — 비루프백(LAN self bind 등) +
        #   alias 설정 시 host-local open 대신 vscode-remote:// URI 로 응답.
        if client_ip not in LOOPBACK_IPS:
            alias = (_load_hub_setting().get("ssh_remote_alias") or "").strip()
            if alias:
                uri = _ssh_remote_uri(target, alias)
                log(f"GET /open-prj — remote client={client_ip} id={raw} → {uri}")
                self.send_response(302)
                self.send_header("Location", uri)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        try:
            subprocess.Popen(_open_cmd(target, _editor_app_name()),  # Issue327
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log(f"GET /open-prj — id={raw} → {target}")
        # 새 탭이 열린 채 남지 않도록 본문 없이 204 — 맵 페이지는 그대로 유지된다.
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_open_session(self, parsed):
        """Issue131: 활성 세션 카드 행 클릭 → VSCode 의 해당 Claude Code 세션 탭으로 포커스.
        메커니즘: extension URI `vscode://anthropic.claude-code/open?session=<sid>` — 세션이
        현재 열린 워크스페이스(cwd)에 속하고 탭이 열려 있으면 그 탭을 포커스(공식 문서).
        먼저 폴더를 열어 워크스페이스 창을 보장·전면화한 뒤 세션 URI 를 호출한다.
        보안: localhost only + cwd 화이트리스트(open-project 동일) + sid 형식 엄격 검증
        (셸·URI 주입 차단)."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        cwd = (body.get("cwd") or "").strip()
        sid = (body.get("sid") or "").strip()
        if not cwd or not sid:
            self._send_json(400, {"error": "cwd and sid required"})
            return
        # sid 엄격 검증 — UUID/영숫자·-·_ 만 (셸·URI 주입 차단)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sid):
            self._send_json(400, {"error": "invalid sid format"})
            return
        cwd = os.path.abspath(os.path.expanduser(cwd)).rstrip("/")
        allowed = set(_load_projects_colors().keys())
        with projects_lock:
            allowed.update((p.get("cwd", "") or "").rstrip("/") for p in projects.values())
        if cwd not in allowed:
            self._send_json(403, {"error": "cwd not in registered projects"})
            return
        if not os.path.isdir(cwd):
            self._send_json(404, {"error": "cwd not a directory"})
            return
        # 서브폴더 cwd 는 등록 프로젝트 루트로 정규화 후 워크스페이스를 연다 — 세션 URI(uri)는
        # sid 로 탭을 찾으므로 cwd 무관하지만, 앞단 `open -a VSCode` 는 원본(서브폴더) cwd 를
        # 쓰면 이미 열린 루트 창을 "이미 열림"으로 인식 못 해 별개 새 창을 띄운다(다른 프로젝트가
        # 열린 것처럼 보이는 원인 — hub 카드는 _resolve_project_root 로 루트 이름을 표시하는데
        # open 은 원본 cwd 를 써서 실제로는 다른 폴더가 열림).
        matched_root = _resolve_project_root(cwd)
        open_cwd = os.path.expanduser(matched_root.get("path", "")).rstrip("/") if matched_root else ""
        if not open_cwd or not os.path.isdir(open_cwd):
            open_cwd = cwd
        uri = f"vscode://anthropic.claude-code/open?session={sid}"
        # Issue237: 원격 클라이언트 + alias 설정 시 클라이언트측 URI 반환.
        #   세션 포커스 URI(uri)는 이미 연결된 워크스페이스 창에서 탭을 포커스한다.
        #   워크스페이스가 안 열려 있을 때를 대비해 folder_uri(vscode-remote)를 함께 반환 —
        #   브라우저 JS 가 folder_uri 로 창을 보장한 뒤 세션 URI 로 포커스한다.
        if client_ip not in LOOPBACK_IPS:
            alias = (_load_hub_setting().get("ssh_remote_alias") or "").strip()
            if alias:
                folder_uri = _ssh_remote_uri(open_cwd, alias)
                log(f"POST /open-session — remote client={client_ip} sid={sid}")
                self._send_json(200, {"status": "remote", "uri": uri,
                                      "folder_uri": folder_uri, "sid": sid})
                return
        # Issue327: Zed 세션은 세션 딥링크가 없다(능력 매트릭스 session_deeplink 영구 미지원)
        #   → 워크스페이스만 연다. vscode:// URI 를 그대로 던지면 VSCode 가 열려 오동작.
        sess_editor = _session_editor(sid)
        try:
            if sess_editor == "zed":
                subprocess.Popen(_open_cmd(open_cwd, _editor_app_name("zed")),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log(f"POST /open-session — zed workspace only (딥링크 미지원) cwd={open_cwd} sid={sid}")
                self._send_json(200, {"status": "opened-workspace", "editor": "zed",
                                      "cwd": open_cwd, "sid": sid})
                return
            # 워크스페이스 창 보장·전면화 후(0.4s) 세션 URI 로 탭 포커스.
            subprocess.Popen(
                ["bash", "-c",
                 f'open -a {shlex.quote(_editor_app_name(sess_editor))} '
                 f'{shlex.quote(open_cwd)}; '
                 f'sleep 0.4; open {shlex.quote(uri)}'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log(f"POST /open-session — cwd={cwd} open_cwd={open_cwd} sid={sid}")
        self._send_json(200, {"status": "opened", "sid": sid})

    def _handle_open_simple_browser(self, parsed):
        """Issue216: hub 렌더 문서(htm)를 VSCode Simple Browser 패널에 띄운다.
        VSCode 내장 `simpleBrowser.show` 는 외부 vscode:// URI·CLI 로 직접 호출 불가 →
        전용 확장 finfra.fpm-simple-browser 가 등록한 URI 핸들러를 경유한다:
          open "vscode://finfra.fpm-simple-browser/open?url=<htm-doc URL>"
        보안: localhost only + register-doc 화이트리스트 exact-match(htm-doc 동일 보안 모델).
        임의 경로/외부 URL open 차단. 확장 측에서도 host 화이트리스트 재검증."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        path = (body.get("path") or "").strip()
        if not path:
            self._send_json(400, {"error": "path required"})
            return
        # prj3#Issue187 잔여(Issue180 각주) + Issue250:
        #   render_tab_mode:hub-internal 의 유일 표면은 hub-shell — register-doc 이 tab-open
        #   SSE 로 즉시 표시하고, SSE 부재(서버 재시작·탭 freeze) 구간도 폴링 fallback(Issue199)
        #   + 재연결이 복귀 시 수거한다. 종전에는 `_any_hub_shell_alive()` 일 때만 skip 했으나,
        #   Chrome 이 백그라운드 hub-shell 탭을 freeze 하면 lease(ttl 30s)가 즉시 죽어
        #   "shell 없음"으로 오판 → 매 렌더마다 VSCode 강제 전면화(포커스 탈취) + Simple
        #   Browser 중복 표시가 재발했다(Issue250). hub-internal 이면 alive 여부 무관 항상 skip.
        #   Simple Browser 를 표면으로 쓰려면 render_tab_mode: browser-tab + render_target: hub.
        if _load_hub_setting().get("render_tab_mode") == "hub-internal":
            log(f"POST /open-simple-browser SKIP — render_tab_mode=hub-internal "
                f"(hub-shell 이 유일 표면, Issue250) path={path}")
            self._send_json(200, {"status": "skipped-hub-internal", "path": path})
            return
        abs_path = os.path.realpath(os.path.expanduser(path))
        # register-doc 화이트리스트 검증 (htm-doc 동일 패턴)
        with registry_lock:
            reg = load_registry(HTM_REGISTRY)
        reg_paths = set()
        owner_cwd = ""   # Issue232: 매칭 엔트리의 owner 프로젝트 cwd
        for e in reg:
            p = e.get("path") or ""
            if p:
                rp = os.path.realpath(p)
                reg_paths.add(p)
                reg_paths.add(rp)
                if abs_path in (p, rp) or path in (p, rp):
                    owner_cwd = (e.get("cwd") or "").rstrip("/")
        if abs_path not in reg_paths and path not in reg_paths:
            log(f"POST /open-simple-browser REJECT — unregistered path: {abs_path}")
            self._send_json(403, {"error": "not a registered htm doc"})
            return
        if not abs_path.endswith((".html", ".htm")):
            self._send_json(403, {"error": "extension not allowed"})
            return
        if not os.path.isfile(abs_path):
            self._send_json(404, {"error": "file not found"})
            return
        # Simple Browser 에는 raw 문서를 띄운다 — _shell=1 로 hub-shell 302 우회.
        import urllib.parse as _u
        doc_url = f"http://127.0.0.1:{PORT}/htm-doc?path={_u.quote(abs_path)}&_shell=1"
        uri = f"vscode://finfra.fpm-simple-browser/open?url={_u.quote(doc_url, safe='')}"
        # Issue232: `open <uri>` 는 macOS 가 frontmost VSCode 창으로 라우팅 →
        #   직전 포커스한 다른 프로젝트 창에 패널이 열리는 문제. owner cwd 가
        #   등록 프로젝트면 그 폴더를 먼저 전면화 후 URI 호출(open-session 동일 패턴).
        # Issue287: owner_cwd 가 프로젝트 루트의 하위 폴더(ex: m2slide/Projects/aTest)일 때
        #   과거엔 `allowed` 정확 일치만 검사해 실패 → target_cwd="" → else 분기로 빠져
        #   frontmost 창(이미 열린 루트 창과 다른 폴더)에 URI 가 라우팅 → 새 창 발생.
        #   open-project/open-session 과 동일하게 _resolve_project_root() 로 등록 루트 정규화.
        target_cwd = ""
        if owner_cwd and os.path.isdir(owner_cwd):
            matched_root = _resolve_project_root(owner_cwd)
            resolved_cwd = (os.path.expanduser(matched_root.get("path", "")).rstrip("/")
                            if matched_root else "")
            allowed = set(_load_projects_colors().keys())
            with projects_lock:
                allowed.update((p.get("cwd", "") or "").rstrip("/") for p in projects.values())
            if resolved_cwd and os.path.isdir(resolved_cwd):
                target_cwd = resolved_cwd
            elif owner_cwd in allowed:
                target_cwd = owner_cwd
        # Issue288: 포커스 탈취 가드. 본 엔드포인트는 클라이언트 JS 호출자가 0건 —
        #   전량 hook 자동 렌더 경로(사용자 제스처 없음)인데 클릭 경로(/open-session)의
        #   전면화 패턴을 그대로 이식해, 백그라운드 세션의 렌더가 사용자가 타이핑 중인
        #   다른 프로젝트 VSCode 창에서 포커스를 빼앗았다. hub 페이지 버튼(/open-project·
        #   /open-session)은 별도 엔드포인트라 이 가드와 무관(전면화 유지가 맞음).
        #   skip 해도 register-doc 등록은 이미 끝나 hub-shell 탭·폴링(Issue199)·채팅
        #   fallback URL 로 수거 가능 → 정보 유실 0.
        focus_mode = (_load_hub_setting().get("simple_browser_focus") or "gate").strip()
        front_proc, front_win = ("", "")
        if focus_mode == "gate":
            front_proc, front_win = _frontmost_app_window()
        skip = _simple_browser_focus_skip(focus_mode, front_proc, front_win, target_cwd)
        if skip:
            log(f"POST /open-simple-browser SKIP — {skip} "
                f"(mode={focus_mode} front='{front_proc}|{front_win}' "
                f"owner='{os.path.basename(target_cwd) if target_cwd else '-'}') path={abs_path}")
            self._send_json(200, {"status": f"skipped-{skip}", "front": front_win,
                                  "owner": os.path.basename(target_cwd) if target_cwd else "",
                                  "path": abs_path})
            return
        try:
            if target_cwd:
                subprocess.Popen(
                    ["bash", "-c",
                     # Simple Browser 는 VSCode 전용 표면 → 앱 고정 (Issue327: 능력 매트릭스 inline_browser)
                     f'open -a {shlex.quote(_editor_app_name("vscode"))} '
                     f'{shlex.quote(target_cwd)}; '
                     f'sleep 0.4; open {shlex.quote(uri)}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(_open_cmd(uri),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log(f"POST /open-simple-browser — path={abs_path} owner_cwd={target_cwd or '-'}")
        self._send_json(200, {"status": "opened", "path": abs_path})

    def _handle_open_settings_yml(self, parsed):
        """⚙️ 설정 버튼 — data/hub_setting.yml 을 VSCode 로 연다."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        if not os.path.isfile(HUB_SETTING_FILE):
            self._send_json(404, {"error": "hub_setting.yml not found"})
            return
        try:
            subprocess.Popen(_open_cmd(HUB_SETTING_FILE, _editor_app_name()),  # Issue327
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log("POST /open-settings-yml — hub_setting.yml")
        self._send_json(200, {"status": "opened", "path": HUB_SETTING_FILE})

    def _handle_get_settings(self, parsed):
        """Issue168: GET /api/settings — 현재 yml 값 + schema 반환 (설정 모달 폼 렌더용)."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        try:
            mtime = os.stat(HUB_SETTING_FILE).st_mtime
        except FileNotFoundError:
            mtime = 0.0
        # Issue169 Stage2: 필드 설명(comment)을 현재 language 로 번역(settings.field.<key>).
        #   키 부재 시 schema 내장 comment(ko) fallback.
        #   lang 쿼리 파라미터(?lang=ko|en)로 override — 모달 헤더 KO/EN 뷰 토글이 재-fetch 시 사용.
        qs = parse_qs(parsed.query or "")
        lang_q = (qs.get("lang", [None])[0])
        lang = i18n.norm_lang(lang_q if lang_q else _load_hub_setting().get("language"))
        schema = []
        for s in HUB_SETTING_SCHEMA:
            item = dict(s)
            tk = "settings.field." + s["key"]
            tr = i18n.t(tk, lang)
            item["comment"] = s["comment"] if tr == tk else tr
            schema.append(item)
        # 기본값 대비 변경분(연필 ✏️) 판정용 defaults.
        #   1차: hub_setting_org.yml(기본값 SSOT 템플릿) → 2차: HUB_SETTING_DEFAULTS
        #   → 3차: 위젯별 자연기본 추정(select 첫 옵션, toggle→False, number→0, 그 외 "").
        #   org.yml 이 곧 시스템 기본이므로 템플릿 그대로 쓰면 연필 미표시.
        org_defaults = _load_hub_setting_org()
        defaults = {}
        for s in HUB_SETTING_SCHEMA:
            k = s["key"]
            if k in org_defaults:
                defaults[k] = org_defaults[k]
            elif k in HUB_SETTING_DEFAULTS:
                dv = HUB_SETTING_DEFAULTS[k]
                if s["widget"] == "toggle":
                    defaults[k] = bool(dv)
                elif s["widget"] == "number":
                    defaults[k] = int(dv)
                else:
                    defaults[k] = str(dv)
            elif s["widget"] == "toggle":
                defaults[k] = False
            elif s["widget"] == "number":
                defaults[k] = 0
            elif s["widget"] == "select" and s.get("options"):
                defaults[k] = str(s["options"][0])
            else:
                defaults[k] = ""
        self._send_json(200, {
            "values": _load_hub_setting_raw(),
            "schema": schema,
            "defaults": defaults,
            "mtime": mtime,
        })

    def _handle_post_settings(self, parsed):
        """Issue168: POST /api/settings — 변경 diff 를 yml 에 주석 보존 기록."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        payload = body.get("values") if isinstance(body, dict) else None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "values object required"})
            return
        client_mtime = body.get("mtime") if isinstance(body, dict) else None
        ok, restart_required, code, werr = _write_hub_setting(payload, client_mtime)
        if not ok:
            self._send_json(code, {"error": werr})
            return
        log(f"POST /api/settings — keys={list(payload.keys())} restart={restart_required}")
        self._send_json(200, {"status": "saved", "restart_required": restart_required})

    def _handle_htm_toggle(self, parsed):
        """Project List 토글 버튼 — 프로젝트의 per-cwd htm 상태 파일을 on↔off 플립.
        `..htm start/stop` 과 동일 효과 (STATE_FILE 기록). 시스템 OFF 플래그가 있으면
        effective off 는 유지되나 per-cwd 의도는 기록됨. 등록 프로젝트만 허용."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        path = (body.get("path") or "").strip()
        if not path:
            self._send_json(400, {"error": "path required"})
            return
        abs_cwd = os.path.expanduser(path).rstrip("/")
        # 화이트리스트: Projects.md 등록 경로만 (임의 경로로 state 파일 생성 차단)
        allowed = {os.path.expanduser(r["path"]).rstrip("/") for r in _load_projects_list()}
        if abs_cwd not in allowed:
            self._send_json(403, {"error": "path not in registered projects"})
            return
        state_dir, state_file = _htm_state_file(path)
        # 현재 per-cwd 상태 읽기 (파일 없으면 default on)
        cur = "on"
        try:
            with open(state_file, encoding="utf-8") as f:
                c = f.read().strip()
                if c in ("on", "off"):
                    cur = c
        except (FileNotFoundError, OSError):
            pass
        new = "off" if cur == "on" else "on"
        try:
            os.makedirs(state_dir, exist_ok=True)
            with open(state_file, "w", encoding="utf-8") as f:
                f.write(new)
        except OSError as e:
            self._send_json(500, {"error": f"write failed: {e}"})
            return
        _htm_state_cache_clear()   # Issue352: 방금 쓴 값을 같은 요청에서 되읽어야 함
        off, reason = _htm_state(path)
        log(f"POST /htm-toggle — {abs_cwd} → {new} (effective_off={off})")
        self._send_json(200, {"path": abs_cwd, "state": new, "htm_off": off, "htm_reason": reason})

    def _handle_htm_toggle_all(self, parsed):
        """Project List 헤더 전체 토글 — 등록 프로젝트 전부를 target state(on/off)로 일괄 SET.
        flip 이 아닌 명시적 set 이라 mixed 상태도 일관되게 정렬됨. 등록 프로젝트만 허용."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        target = (body.get("state") or "").strip()
        if target not in ("on", "off"):
            self._send_json(400, {"error": "state must be 'on' or 'off'"})
            return
        # Issue215: 마스터 토글 = 진짜 hub 마스터(`..hub on/off` 동치). per-cwd 만
        #   기록하면 dominant 플래그 `.hub-system-off` 가 모두 마스킹 → 토글 무력.
        #   target=on → 시스템 OFF 플래그 해제, target=off → 시스템 OFF 플래그 생성.
        sys_off_flag = os.path.join(os.path.expanduser("~"), ".claude", ".hub-system-off")
        try:
            if target == "on":
                if os.path.exists(sys_off_flag):
                    os.remove(sys_off_flag)
            else:
                os.makedirs(os.path.dirname(sys_off_flag), exist_ok=True)
                with open(sys_off_flag, "w", encoding="utf-8") as f:
                    f.write("")
        except OSError as e:
            log(f"POST /htm-toggle-all — system flag {target} failed: {e}")
            self._send_json(500, {"error": f"system flag update failed: {e}"})
            return
        results = []
        for r in _load_projects_list():
            path = r["path"]
            state_dir, state_file = _htm_state_file(path)
            try:
                os.makedirs(state_dir, exist_ok=True)
                with open(state_file, "w", encoding="utf-8") as f:
                    f.write(target)
            except OSError as e:
                log(f"POST /htm-toggle-all — write failed {path}: {e}")
                continue
            _htm_state_cache_clear()   # Issue352: 방금 쓴 값 기준으로 재판정
            off, reason = _htm_state(path)
            results.append({"path": os.path.expanduser(path).rstrip("/"),
                            "htm_off": off, "htm_reason": reason})
        log(f"POST /htm-toggle-all — {len(results)} projects → {target}")
        self._send_json(200, {"state": target, "count": len(results), "projects": results})

    def _handle_open_projects_md(self, parsed):
        """Project List 팝업의 'VSCode로 수정' — Projects.md 를 VSCode 로 연다 (고정 경로)."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        if not os.path.isfile(PROJECTS_MD):
            self._send_json(404, {"error": "Projects.md not found"})
            return
        try:
            subprocess.Popen(_open_cmd(PROJECTS_MD, _editor_app_name()),  # Issue327
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log("POST /open-projects-md — Projects.md")
        self._send_json(200, {"status": "opened", "path": PROJECTS_MD})

    def _handle_issue(self, parsed):
        """Issue66: GET /issue?prj=N&id=M — ___pm projects/{N} 경로 해석 후
        해당 프로젝트 Issue.md 에서 ## Issue{M}: 섹션 추출 → HTML 반환.
        prj 는 숫자만 허용 (path traversal 방어). id 는 숫자[_숫자]* 형식."""
        qs = parse_qs(parsed.query or "")
        prj_vals = qs.get("prj", [])
        id_vals = qs.get("id", [])
        if not prj_vals or not id_vals:
            self._send_json(400, {"error": "prj and id are required"})
            return
        prj = prj_vals[0].strip()
        issue_id = id_vals[0].strip()
        # path traversal 방어 — prj 는 정수 id 또는 접미 id(9a / 9a1, Issue303).
        # 문법에 `/`·`.` 이 없으므로 통과한 값은 경로 조각으로 안전하다.
        if not _PID_RE.match(prj):
            self._send_json(400, {"error": "prj must match <int>[<letter>[<int>]] (e.g. 15 or 9a)"})
            return
        # id 검증 — 숫자 또는 숫자_숫자(서브이슈) 형식만
        if not re.fullmatch(r"\d+(?:_\d+)*", issue_id):
            self._send_json(400, {"error": "id must be numeric (e.g. 84 or 84_2)"})
            return
        # projects/{N} 파일에서 경로 읽기
        proj_file = os.path.join(REPO_ROOT, "projects", prj)
        if not os.path.isfile(proj_file):
            self._send_json(404, {"error": f"project {prj} not found"})
            return
        try:
            with open(proj_file, encoding="utf-8") as f:
                proj_path = f.read().strip()
        except Exception as e:
            self._send_json(500, {"error": f"read project file failed: {e}"})
            return
        # projects/{N} 파일 값은 ~/... 형식이 흔함 → expanduser 필수
        proj_path = os.path.expanduser(proj_path)
        if not proj_path or not os.path.isabs(proj_path):
            self._send_json(404, {"error": "invalid project path"})
            return
        # Issue.md 경로
        issue_md = os.path.join(proj_path, "Issue.md")
        if not os.path.isfile(issue_md):
            self._send_json(404, {"error": "Issue.md not found"})
            return
        # ## Issue{M}: 헤더 섹션 추출
        try:
            with open(issue_md, encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self._send_json(500, {"error": f"read Issue.md failed: {e}"})
            return
        # 헤더 패턴: ## Issue{id}: 또는 ## Issue{id} (공백 포함)
        header_pattern = re.compile(
            r'^(## Issue' + re.escape(issue_id) + r'[:\s].*)', re.MULTILINE)
        m = header_pattern.search(content)
        if not m:
            self._send_json(404, {"error": f"Issue{issue_id} not found in Issue.md"})
            return
        start = m.start()
        # 다음 ## 또는 # 섹션까지 추출
        end_pattern = re.compile(r'^#{1,2} ', re.MULTILINE)
        end_m = end_pattern.search(content, start + 1)
        section = content[start:end_m.start()].rstrip() if end_m else content[start:].rstrip()
        # 간단한 HTML 렌더
        section_html = html.escape(section)
        body_html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<link rel="icon" href="/fpm-icon.png">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Issue{html.escape(issue_id)} — prj {html.escape(prj)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
  background: #fff; color: #111; margin: 0; padding: 1.5rem; line-height: 1.7; }}
pre {{ background: #f5f5f5; padding: 1rem; border-radius: 4px; overflow-x: auto;
  white-space: pre-wrap; word-break: break-word; }}
</style>
</head>
<body>
<pre>{section_html}</pre>
</body>
</html>"""
        body_bytes = body_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_bytes)
        log(f"GET /issue — prj={prj} id={issue_id} len={len(section)}")

    def _handle_register_pid(self, parsed):
        """Issue16: runner가 자신의 PID를 cwd_hash에 등록 (stop 권한 대상이 됨)."""
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        try:
            pid = int(body.get("pid"))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "missing or invalid pid"})
            return
        if pid <= 0:
            self._send_json(400, {"error": "pid must be positive"})
            return
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            self._send_json(404, {"error": "pid not running"})
            return
        except PermissionError:
            self._send_json(403, {"error": "pid owned by other user"})
            return
        h = cwd_hash(cwd)
        with pids_lock:
            pids.setdefault(h, set()).add(pid)
        persist_pids()  # Issue63: 재시작 후 /control 복구
        log(f"POST /register-pid — hash={h} pid={pid}")
        self._send_json(200, {"status": "registered", "pid": pid, "cwd_hash": h})

    def _handle_control(self, parsed):
        """Issue16: 등록된 runner PID 정지 (TERM → 2s → KILL)."""
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        action = body.get("action")
        if action not in ("stop", "kill_pane", "refresh", "remove", "approve"):
            self._send_json(400, {"error": f"unknown action: {action}"})
            return
        h = cwd_hash(cwd)
        # Issue66: remove action — supervisor PID 에 SIGUSR2 + tombstone.
        # pid 필드 불필요 (supervisor pid 는 content-authoritative 추출). 이 분기로 조기 반환.
        if action == "remove":
            self._handle_control_remove(body, cwd, h)
            return
        # Issue66 Phase 7: approve action — 큐 dashboard 승인 게이트 마커 파일 생성.
        # pid 불필요 (마커 파일 경유로 supervisor 가 진행 판단). 이 분기로 조기 반환.
        if action == "approve":
            self._handle_control_approve(body, cwd, h)
            return
        try:
            pid = int(body.get("pid"))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "missing or invalid pid"})
            return
        # Issue138: kill_pane 은 window_name(tmux window) 대상 — runner pid liveness 무관.
        #   registration 게이트 앞에서 처리해야 done(runner pid dead) 후에도 잔존 window 종료 가능.
        #   기존엔 dead pid → 게이트의 already_dead 조기반환에 막혀 window 가 살아남던 버그.
        #   cwd+token 인증은 함수 상단에서 이미 통과 → window kill 권한 충분.
        if action == "kill_pane":
            window_name = (body.get("window_name") or "").strip()
            # Issue183: 한글/유니코드 window명도 허용. 기존 ASCII-only 화이트리스트
            #   (`^[a-zA-Z0-9_.:-]+$`)는 `_테스트` 등 한글 window 를 tmux 도달 전 400 으로
            #   거부했다. subprocess 는 list 인자(shell=False)라 셸 인젝션은 없으나, tmux
            #   `-t pm:<name>` 타깃 파싱 보호용으로 제어문자·공백·셸 메타문자만 블랙리스트로
            #   거부하고 그 외(한글 포함)는 통과시킨다.
            if (not window_name or len(window_name) > 200
                    or re.search(r'''[\x00-\x1f\x7f\s;$`'"()&|<>\\]''', window_name)):
                self._send_json(400, {"error": "invalid window_name"})
                return
            try:
                result = subprocess.run(
                    ["tmux", "kill-window", "-t", f"pm:{window_name}"],
                    capture_output=True, timeout=5, text=True
                )
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                self._send_json(500, {"error": f"tmux exec failed: {e}"})
                return
            if result.returncode != 0:
                # window 가 이미 없으면(완료 후 정리됨) graceful 200 — 사용자 입장 목적 달성.
                stderr = result.stderr.strip()
                if "can't find window" in stderr or "no such window" in stderr.lower():
                    with pids_lock:
                        pids.get(h, set()).discard(pid)
                    persist_pids()
                    self._send_json(200, {"status": "already_gone", "window": window_name})
                    return
                self._send_json(500, {"error": f"tmux kill-window failed: {stderr}"})
                return
            with pids_lock:
                pids.get(h, set()).discard(pid)
            persist_pids()  # Issue63
            log(f"POST /control — killed pane window={window_name} hash={h} pid={pid}")
            self._send_json(200, {"status": "killed_pane", "window": window_name, "pid": pid})
            return
        with pids_lock:
            registered = pid in pids.get(h, set())
        # Issue64: pids 레지스트리는 /register-pid 1회성 + pids.json 휘발(빈 {}로
        #   재시작)로 live runner 가 누락될 수 있다. dashboard 세션 data content 의
        #   runner pid 는 매 iter 갱신되는 authoritative 신호 → 등록 게이트 fallback
        #   으로 인정하고 레지스트리에 self-heal. 활성 세션 카드 ✕ 버튼이 403 으로
        #   실패하던 문제 해소.
        if not registered and pid in _session_runner_pids(h):
            registered = True
            with pids_lock:
                pids.setdefault(h, set()).add(pid)
            persist_pids()
            log(f"POST /control — pid={pid} self-healed into registry "
                f"(authoritative dash runner) hash={h}")
        if not registered:
            # Issue63: 미등록 pid — 죽은 runner 면 graceful 200(already_dead), 살아있으면 403.
            #   pids 영속화(Issue63 Fix A)로 정상 케이스 대부분 복원되나, runner 가
            #   /register-pid 전 죽었거나 외부 종료된 경우 미등록 상태가 남는다.
            #   죽은 runner 에 stop 버튼을 눌렀을 때 에러 대신 '이미 종료됨' 으로 응답.
            if not _pid_alive(pid):
                log(f"POST /control — pid={pid} not registered & dead → already_dead hash={h}")
                self._send_json(200, {"status": "already_dead", "pid": pid})
                return
            log(f"POST /control — pid={pid} not registered for hash={h}")
            self._send_json(403, {"error": "pid not registered for this cwd"})
            return
        # Issue27: refresh 분기 — runner SIGUSR1 (sleep 인터럽트 → 즉시 1 iter). 비파괴
        if action == "refresh":
            try:
                os.kill(pid, signal.SIGUSR1)
            except ProcessLookupError:
                with pids_lock:
                    pids.get(h, set()).discard(pid)
                persist_pids()  # Issue63
                self._send_json(404, {"error": "pid dead", "pid": pid})
                return
            except PermissionError:
                self._send_json(403, {"error": "signal permission denied"})
                return
            log(f"POST /control — refresh (SIGUSR1) hash={h} pid={pid}")
            self._send_json(200, {"status": "refreshed", "pid": pid})
            return
        # Issue138: kill_pane 분기는 registration 게이트 앞으로 이동됨 (위 참조)
        sig_used = None
        try:
            os.kill(pid, signal.SIGTERM)
            sig_used = "TERM"
        except ProcessLookupError:
            with pids_lock:
                pids.get(h, set()).discard(pid)
            persist_pids()  # Issue63
            self._send_json(200, {"status": "already_dead", "pid": pid})
            return
        except PermissionError:
            self._send_json(403, {"error": "kill permission denied"})
            return
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            try:
                os.kill(pid, signal.SIGKILL)
                sig_used = "KILL"
            except ProcessLookupError:
                pass
            except PermissionError:
                self._send_json(500, {"error": "SIGKILL permission denied", "pid": pid})
                return
        with pids_lock:
            pids.get(h, set()).discard(pid)
        persist_pids()  # Issue63
        log(f"POST /control — stopped pid={pid} hash={h} signal={sig_used}")
        self._send_json(200, {"status": "stopped", "pid": pid, "signal": sig_used})

    @staticmethod
    def _session_supervisor_pid(h: str, sid: str = ""):
        """Issue66: cwd_hash h 의 dashboard 세션 content 에 기록된 supervisor_pid 추출.
        sid 지정 시 해당 세션 한정. content-authoritative pid 의 단일 파서.
        Issue86: sid 부재 + cwd_hash 내 supervisor_pid 보유 dashboard 가 2개 이상이면
        ambiguous → None 반환 (첫 dashboard 임의 선택 금지 — stale/오대상 SIGUSR2 차단).
        정확히 1개면 그 값. sid 지정 시 세션 키 (h,sid) 가 유일하므로 첫 매치 반환.
        반환 int|None."""
        with sessions_lock:
            snap = list(sessions.items())
        found = []
        for (sh, ssid), entry in snap:
            if sh != h:
                continue
            if sid and ssid != sid:
                continue
            if entry.get("content_type") != "dashboard":
                continue
            try:
                d = json.loads(entry.get("content") or "")
                pid_val = d.get("supervisor_pid")
                if pid_val is not None:
                    found.append(int(pid_val))
            except Exception:
                continue
        if sid:
            return found[0] if found else None
        # sid 부재 — ambiguous(2개 이상)면 임의 선택 금지, content-authoritative 포기
        if len(found) == 1:
            return found[0]
        return None

    def _handle_control_remove(self, body: dict, cwd: str, h: str):
        """Issue66: /control action=remove — 큐 dashboard graceful 제거.
        supervisor pid 는 content-authoritative(queue.yaml 최상위 supervisor_pid 필드)
        — pids 레지스트리·body 값 단독 신뢰 금지 (Issue63·64 반영).
        dead supervisor → 200 {status:already_dead} + tombstone 만 처리 (Issue63 Fix C 패턴)."""
        # dash id/path — tombstone 기록용. body 에 dash_path 또는 sid 로 식별.
        # _handle_unregister_doc 와 동일하게 realpath 정규화하여 tombstone path 일관성 확보.
        dash_path = (body.get("dash_path") or "").strip()
        if dash_path:
            dash_path = os.path.realpath(os.path.expanduser(dash_path))
        sid = (body.get("sid") or "").strip()
        # supervisor_pid 결정 — content 가 권위. body 값은 content 와 일치할 때만 사용.
        #   content 부재 시에만 body fallback. 불일치 시 content 값 채택(임의 pid SIGUSR2 차단).
        content_pid = self._session_supervisor_pid(h, sid)
        body_pid = body.get("supervisor_pid")
        if body_pid is not None:
            try:
                body_pid = int(body_pid)
            except (TypeError, ValueError):
                body_pid = None
        if content_pid is not None:
            sup_pid = content_pid
            if body_pid is not None and body_pid != content_pid:
                log(f"POST /control remove — body supervisor_pid={body_pid} ≠ "
                    f"content {content_pid}; content 권위 채택 hash={h}")
        else:
            # content 에 supervisor_pid 없음 → body fallback (큐 dashboard 미등록 가능)
            sup_pid = body_pid
            if sup_pid is not None:
                log(f"POST /control remove — content supervisor_pid 부재, "
                    f"body 값 fallback pid={sup_pid} hash={h}")
        # tombstone 기록 (supervisor 죽어있어도 항상 처리)
        if dash_path or sid:
            try:
                with registry_lock:
                    cleared = load_registry(DASH_CLEARED)
                    if dash_path and dash_path not in cleared:
                        cleared.append(dash_path)
                        save_registry(DASH_CLEARED, cleared)
                        log(f"POST /control remove — tombstone dash_path={dash_path}")
                    # dash-registry 에서도 제거
                    if dash_path:
                        entries = load_registry(DASH_REGISTRY)
                        before = len(entries)
                        entries = [e for e in entries
                                   if os.path.realpath(os.path.expanduser(
                                       e.get("path", ""))) != dash_path]
                        if len(entries) < before:
                            save_registry(DASH_REGISTRY, entries)
                            log(f"POST /control remove — removed from dash-registry path={dash_path}")
            except Exception as ex:
                log(f"POST /control remove — tombstone failed: {ex}")
        # Issue95: 대응 live session 동반 제거 — supervisor 생사와 무관하게 즉시.
        #   sid 지정 시 정확 제거, 미지정 시 dash_path 매칭으로 후보 세션 제거.
        if sid:
            with sessions_lock:
                if sessions.pop((h, sid), None) is not None:
                    log(f"POST /control remove — live session removed hash={h} sid={sid}")
                    _drop = True
                else:
                    _drop = False
            if _drop:
                persist_sessions()
        elif dash_path:
            with projects_lock:
                _cwd = (projects.get(h) or {}).get("cwd", "")
            with sessions_lock:
                match = [(sh, ssid) for (sh, ssid), ent in sessions.items()
                         if sh == h and dash_path in _dash_session_candidate_paths(_cwd, ent)]
                for k in match:
                    sessions.pop(k, None)
            if match:
                persist_sessions()
                log(f"POST /control remove — {len(match)} live session(s) removed (dash_path match)")
        if sup_pid is None:
            log(f"POST /control remove — supervisor_pid not found hash={h} sid={sid}")
            self._send_json(200, {"status": "already_dead", "reason": "supervisor_pid_not_found"})
            return
        # supervisor pid 생사 확인 (Issue63 Fix C 패턴)
        if not _pid_alive(sup_pid):
            log(f"POST /control remove — supervisor pid={sup_pid} already dead hash={h}")
            self._send_json(200, {"status": "already_dead", "pid": sup_pid})
            return
        # SIGUSR2 로 graceful 회수 트리거
        try:
            os.kill(sup_pid, signal.SIGUSR2)
        except ProcessLookupError:
            log(f"POST /control remove — pid={sup_pid} died before SIGUSR2 hash={h}")
            self._send_json(200, {"status": "already_dead", "pid": sup_pid})
            return
        except PermissionError:
            self._send_json(403, {"error": "SIGUSR2 permission denied", "pid": sup_pid})
            return
        log(f"POST /control remove — SIGUSR2 sent to supervisor pid={sup_pid} hash={h}")
        self._send_json(200, {"status": "removing", "pid": sup_pid})

    # Issue66 Phase 7: 승인 게이트 마커 파일명 안전 문자 — 영숫자·`-`·`_` 만.
    _APPROVAL_SAFE_RE = re.compile(r"^[A-Za-z0-9_-]+$")

    def _queue_dash_meta(self, h: str, sid: str = ""):
        """Issue66: cwd_hash h 의 큐 dashboard 세션에서 (out_dir, topic) 추출.
        OUT_DIR 우선순위:
          1) 세션 content 의 `out_dir` 필드 (supervisor 가 직접 기록 — 권위)
          2) 세션 content 의 `dash_path` 필드 dirname
          3) dash-registry 에서 동일 cwd 의 dash 파일 path dirname (title 매칭 우선)
        topic 은 content 의 `title`. sid 지정 시 해당 세션 한정.
        반환 (out_dir|None, topic|None)."""
        with sessions_lock:
            snap = list(sessions.items())
        sess_cwd = None
        with projects_lock:
            p = projects.get(h)
            if p:
                sess_cwd = p.get("cwd")
        for (sh, ssid), entry in snap:
            if sh != h:
                continue
            if sid and ssid != sid:
                continue
            if entry.get("content_type") != "dashboard":
                continue
            try:
                d = json.loads(entry.get("content") or "")
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            topic = d.get("title")
            topic = topic if isinstance(topic, str) else None
            # 1) content out_dir 직접 기록
            out_dir = d.get("out_dir")
            if isinstance(out_dir, str) and out_dir.strip():
                return os.path.realpath(os.path.expanduser(out_dir.strip())), topic
            # 2) content dash_path dirname
            dash_path = d.get("dash_path")
            if isinstance(dash_path, str) and dash_path.strip():
                dp = os.path.realpath(os.path.expanduser(dash_path.strip()))
                return os.path.dirname(dp), topic
            # 3) dash-registry 에서 동일 cwd dash 파일 dirname (title 매칭 우선)
            with registry_lock:
                entries = load_registry(DASH_REGISTRY)
            cand = None
            for e in entries:
                e_path = e.get("path", "")
                if not e_path:
                    continue
                e_cwd = e.get("cwd", "") or ""
                if sess_cwd and e_cwd and e_cwd != sess_cwd:
                    continue
                if topic and e.get("title") == topic:
                    cand = e_path
                    break
                if cand is None:
                    cand = e_path
            if cand:
                dp = os.path.realpath(os.path.expanduser(cand))
                return os.path.dirname(dp), topic
            return None, topic
        return None, None

    def _handle_control_approve(self, body: dict, cwd: str, h: str):
        """Issue66 Phase 7: /control action=approve — 큐 dashboard 승인 게이트.
        body {item: <itemid>, sid?: <sid>}. 동작 — 큐 dashboard 세션의 OUT_DIR 을
        구해 `<OUT_DIR>/.dash-approvals/<topic>__<itemid>` 빈 마커 파일을 write.
        supervisor 가 이 마커 존재를 보고 waiting_approval 항목을 진행한다.
        itemid·topic 은 영숫자·`-`·`_` 만 허용 (경로 traversal 방어)."""
        item = (body.get("item") or "").strip()
        sid = (body.get("sid") or "").strip()
        if not item:
            self._send_json(400, {"error": "missing item"})
            return
        # itemid traversal 방어 — 영숫자·-·_ 만
        if not self._APPROVAL_SAFE_RE.match(item):
            self._send_json(400, {"error": "item must be alphanumeric with - or _ only"})
            return
        out_dir, topic = self._queue_dash_meta(h, sid)
        if not out_dir:
            log(f"POST /control approve — out_dir not found hash={h} sid={sid} item={item}")
            self._send_json(404, {"error": "queue dashboard OUT_DIR not found"})
            return
        # topic 도 마커 파일명에 들어가므로 안전화. 부재·불량 시 'queue' 로 대체.
        if not topic or not self._APPROVAL_SAFE_RE.match(topic):
            safe_topic = "queue"
        else:
            safe_topic = topic
        approvals_dir = os.path.join(out_dir, ".dash-approvals")
        marker = os.path.join(approvals_dir, f"{safe_topic}__{item}")
        # marker 가 approvals_dir 밖으로 새지 않는지 최종 확인 (이중 방어)
        if os.path.dirname(os.path.realpath(marker)) != os.path.realpath(approvals_dir):
            self._send_json(400, {"error": "invalid marker path"})
            return
        try:
            os.makedirs(approvals_dir, exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write("")  # 빈 마커 — 존재 자체가 승인 신호
        except OSError as e:
            log(f"POST /control approve — marker write failed: {e}")
            self._send_json(500, {"error": f"marker write failed: {e}"})
            return
        log(f"POST /control approve — marker created {marker} hash={h}")
        self._send_json(200, {"status": "approved", "item": item, "marker": marker})

    def _handle_sse(self, parsed):
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        qs = parse_qs(parsed.query)
        sid = (qs.get("sid") or [""])[0]  # Issue17 Phase 1: sid 채널 분리 (미존재 시 빈 sid = backward-compat)
        h = cwd_hash(cwd)
        key = (h, sid)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Access-Control-Allow-Origin", self._acao())
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
        except Exception:
            return
        with sse_lock:
            sse_subscribers.setdefault(key, []).append(self.wfile)
            count = len(sse_subscribers[key])
        log(f"SSE connect — hash={h} sid={sid!r} ({count} active)")
        try:
            while True:
                time.sleep(15)
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with sse_lock:
                subs = sse_subscribers.get(key, [])
                if self.wfile in subs:
                    subs.remove(self.wfile)
                count = len(subs)
            log(f"SSE disconnect — hash={h} sid={sid!r} ({count} active)")

    def _handle_data(self, parsed):
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        qs = parse_qs(parsed.query)
        rel = (qs.get("path") or [""])[0]
        if not rel:
            self._send_json(400, {"error": "missing path"})
            return
        abs_path = rel if os.path.isabs(rel) else os.path.join(cwd, rel)
        abs_path = os.path.realpath(abs_path)
        cwd_real = os.path.realpath(cwd)
        if not path_within_serve_roots(abs_path, cwd_real):
            log(f"GET /data — path outside cwd rejected: {abs_path}")
            self._send_json(403, {"error": "path outside cwd"})
            return
        # Issue393: confinement 를 통과해도 dotfile·자격증명은 거부 (cwd 하위여도 마찬가지)
        if path_is_sensitive(abs_path):
            log(f"GET /data — sensitive path rejected: {os.path.basename(abs_path)}")
            self._send_json(403, {"error": "path not allowed"})
            return
        if not abs_path.endswith((".json", ".yaml", ".yml")):
            self._send_json(403, {"error": "extension not allowed"})
            return
        try:
            with open(abs_path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json(404, {"error": "file not found"})
            return
        ct = "application/json" if abs_path.endswith(".json") else "application/yaml"
        self.send_response(200)
        self.send_header("Content-Type", ct + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", self._acao())
        self.end_headers()
        self.wfile.write(body)

    def _handle_htm_res(self, parsed):
        """Issue255: htm 문서의 상대 리소스(이미지) serve.
        인증 2모드 — (1) cwd+token(=/view 대칭, cwd-jail) (2) htm-registry
        exact-match(토큰리스, /htm-doc 대칭). registry 모드의 jail 은 doc 의
        `_doc_work/` 상위(없으면 doc 디렉토리) — 프로젝트 임의 파일 노출 차단."""
        qs = parse_qs(parsed.query)
        doc = (qs.get("doc") or [""])[0]
        rel = (qs.get("rel") or [""])[0]
        # Issue283: abs= 는 file:// 절대경로 모드 (프로젝트 jail 밖 이미지)
        abs_p = (qs.get("abs") or [""])[0]
        if not doc or (not rel and not abs_p):
            self._send_json(400, {"error": "missing doc or rel/abs"})
            return
        doc_real = os.path.realpath(doc)
        jail = None
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if cwd and token and validate(cwd, token):
            cwd_real = os.path.realpath(cwd)
            if path_within_serve_roots(doc_real, cwd_real):
                jail = cwd_real
        if jail is None:
            with registry_lock:
                reg = load_registry(HTM_REGISTRY)
            reg_paths = set()
            for e in reg:
                p = e.get("path") or ""
                if p:
                    reg_paths.add(p)
                    reg_paths.add(os.path.realpath(p))
            if doc_real not in reg_paths and doc not in reg_paths:
                log(f"GET /htm-res — unauthorized doc rejected: {doc_real}")
                self._send_json(403, {"error": "doc not authorized"})
                return
            marker = os.sep + "_doc_work" + os.sep
            i = doc_real.find(marker)
            jail = (doc_real[:i + len(marker) - 1] if i >= 0
                    else os.path.dirname(doc_real))
        if abs_p:
            # Issue283: file:// 절대경로 모드. jail 이 $HOME 으로 완화되므로
            # loopback 전용 + (위에서 통과한) doc 등록 인증을 함께 요구한다.
            # /ob 브리지(Issue266)와 동일한 보안 등급.
            client_ip = self.client_address[0] if self.client_address else ""
            if client_ip not in LOOPBACK_IPS:
                self._send_json(403, {"error": "loopback only"})
                return
            res = os.path.realpath(os.path.abspath(os.path.expanduser(abs_p)))
            home = os.path.realpath(os.path.expanduser("~"))
            if not res.startswith(home + os.sep):
                log(f"GET /htm-res — abs outside home rejected: {res}")
                self._send_json(403, {"error": "abs outside home"})
                return
        else:
            res = os.path.realpath(os.path.join(os.path.dirname(doc_real), rel))
            if res != jail and not res.startswith(jail + os.sep):
                log(f"GET /htm-res — rel escapes jail rejected: {res}")
                self._send_json(403, {"error": "rel outside jail"})
                return
        ext = os.path.splitext(res)[1].lower()
        if ext not in _HTM_RES_EXTS:
            self._send_json(403, {"error": "extension not allowed"})
            return
        try:
            with open(res, "rb") as f:
                data = f.read()
        except OSError:
            self._send_json(404, {"error": "file not found"})
            return
        ctype = mimetypes.guess_type(res)[0] or "application/octet-stream"
        if ext == ".svg":
            ctype = "image/svg+xml"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_htm_doc_tmp_hint(self, abs_path: str):
        """/tmp fallback 문서가 미등록 403 일 때, raw JSON 대신 원인·해결 안내 HTML serve.
        원인: 프로젝트에 활성 htm 폴더 부재 → 트리거가 /tmp/___pm 로 fallback → register 훅
        (htm 경로만 매칭)이 등록 스킵 → whitelist 403. 해결: 프로젝트에 htm 폴더 생성 후 재렌더.
        Issue289: 안내 폴더를 legacy `z_htm` 에서 활성 `_doc_work/htm/` 으로 교체."""
        base = os.path.basename(abs_path)
        port = self.server.server_address[1]
        reg_cmd = (
            "curl -s -X POST http://127.0.0.1:%d/register-doc "
            "-H 'Content-Type: application/json' "
            "-d '{\"type\":\"htm\",\"path\":\"%s\",\"title\":\"%s\"}'"
            % (port, abs_path, base)
        )
        html = (
            "<!doctype html><html lang=ko><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>미등록 htm — htm 폴더 필요</title><style>"
            "body{font:15px/1.6 -apple-system,system-ui,sans-serif;max-width:760px;"
            "margin:3rem auto;padding:0 1.2rem;color:#222}"
            "h1{font-size:1.3rem}code{background:#f2f2f5;padding:.15em .4em;border-radius:4px}"
            "pre{background:#1e1e24;color:#e8e8ee;padding:1rem;border-radius:8px;overflow-x:auto}"
            ".box{background:#fff7e6;border:1px solid #f0c36d;border-radius:8px;padding:1rem 1.2rem;margin:1.2rem 0}"
            "@media(prefers-color-scheme:dark){body{background:#16161a;color:#ddd}"
            "code{background:#2a2a33}.box{background:#2b2410;border-color:#7a5c1e}}"
            "</style></head><body>"
            "<h1>⚠️ 미등록 htm 문서 — 프로젝트에 <code>_doc_work/htm/</code> 필요</h1>"
            "<p>이 문서는 <code>/tmp/___pm/</code> fallback 경로에 저장됐습니다. "
            "프로젝트 루트에 <code>_doc_work/htm/</code> 폴더가 <b>없어서</b> hub 렌더가 "
            "/tmp 로 회피했고, 등록 훅이 /tmp 경로를 매칭하지 못해 hub registry 에 "
            "등록되지 않았습니다 → <code>/htm-doc</code> 화이트리스트 403.</p>"
            "<div class=box><b>영구 해결</b> — 프로젝트 루트에서 htm 폴더 생성 후 다시 렌더:"
            "<pre>mkdir -p _doc_work/htm</pre>"
            "이후 hub 렌더는 프로젝트 <code>_doc_work/htm/</code> 에 저장되어 자동 등록됩니다. "
            "(legacy <code>_doc_work/z_htm/</code> 도 읽기는 계속 지원 — Issue289)</div>"
            "<p><b>이 문서만 즉시 복구</b> (수동 등록):</p>"
            "<pre>" + reg_cmd + "</pre>"
            "<p style=color:#888>파일: <code>" + abs_path + "</code></p>"
            "</body></html>"
        )
        body = html.encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _htm_resolve_moved(self, abs_path: str, cleared: set) -> str:
        """Issue289 (축 2 — ENOENT self-heal): 등록 경로가 디스크에 없을 때
        **같은 프로젝트 루트 하위 HTM_DIRS** 에서 basename 으로 재탐색한다.
        아카이브 이동(`htm/` → `z_done/htm/`)으로 죽은 URL·북마크를 흡수하는 경로.

        보안 불변식:
        * 요청/registry 경로에서 취하는 것은 `basename` 뿐이다 — 경로 성분은 전부 폐기하므로
          `../` 류 traversal 로 화이트리스트 밖 파일에 도달할 수 없다.
        * 후보가 symlink 등으로 프로젝트 루트 밖을 가리키면 거부한다.
        * HTM_CLEARED tombstone 에 든 경로는 되살리지 않는다 — clear 무효화 금지.

        찾지 못하면 빈 문자열."""
        marker = "/_doc_work/"
        idx = abs_path.find(marker)
        if idx <= 0:
            return ""
        root = abs_path[:idx]
        base = os.path.basename(abs_path)
        if not base or base in (".", ".."):
            return ""
        for d in HTM_DIRS:
            cand = os.path.realpath(
                os.path.join(root, "_doc_work", *d.split("/"), base))
            if not cand.startswith(root + os.sep):
                continue  # 프로젝트 밖으로 새는 후보 거부
            if cand == abs_path or not os.path.isfile(cand):
                continue
            if cand in cleared:
                continue  # clear 된 문서가 fallback 으로 부활하지 않도록
            return cand
        return ""

    def _htm_registry_rewrite(self, old_paths: set, new_path: str) -> None:
        """Issue289: self-heal 성공 시 registry 의 옛 경로를 새 위치로 갱신(1회성 자가 치유).
        이후 조회는 registry 가 새 경로를 직접 가리키므로 fallback 비용이 없다."""
        with registry_lock:
            entries = load_registry(HTM_REGISTRY)
            changed = False
            for e in entries:
                if (e.get("path") or "") in old_paths:
                    e["path"] = new_path
                    changed = True
            if changed:
                save_registry(HTM_REGISTRY, entries)
                log(f"htm-doc self-heal — registry rewrite -> {new_path}")

    def _htm_doc_autoregister(self, abs_path: str) -> bool:
        """Issue337: 미등록 htm 요청의 self-heal 등록. 생산자 훅(PostToolUse matcher: Write)이
        Bash heredoc·스크립트 생성 경로에서 발동하지 않아 생기는 영구 403 을 서버가 흡수한다.

        허용 조건(전부 충족해야 등록 — 화이트리스트 보안 모델 유지):
          1. 실존 일반 파일 + 확장자 .htm/.html/.md (Issue353_1: md-first 산출 포함)
          2. 부모 폴더가 canonical htm 출력 폴더 (`_doc_work/{htm,z_done/htm,z_htm}`) 또는 TMP_OUT_DIR
          3. 파일명이 htm 출력 규약(`hub_htm_*` / legacy `claude-htm-*`) 준수
          4. HTM_CLEARED tombstone 에 없음 — 사용자가 명시 제거한 문서는 부활시키지 않음
        임의 경로 노출은 2·3 이 막고, 사용자 의사(clear)는 4 가 존중한다."""
        if not os.path.isfile(abs_path) or not abs_path.endswith((".htm", ".html", ".md")):
            return False
        if not _htm_output_stem(os.path.basename(abs_path)):
            return False
        parent = os.path.dirname(abs_path)
        ok_dir = os.path.realpath(parent) == os.path.realpath(TMP_OUT_DIR)
        if not ok_dir:
            norm = parent.replace(os.sep, "/")
            ok_dir = any(norm.endswith("/_doc_work/" + d) for d in HTM_DIRS)
        if not ok_dir:
            return False
        with registry_lock:
            if abs_path in set(load_registry(HTM_CLEARED)):
                return False
            entries = load_registry(HTM_REGISTRY)
            if any(os.path.realpath(e.get("path") or "") == abs_path for e in entries if e.get("path")):
                return True
            # cwd 추정: `_doc_work/...` 상위가 프로젝트 루트 (tmp fallback 은 빈 문자열)
            cwd = ""
            marker = "/_doc_work/"
            norm_abs = abs_path.replace(os.sep, "/")
            if marker in norm_abs:
                cwd = norm_abs[:norm_abs.index(marker)]
            entries.insert(0, {
                "path": abs_path,
                "cwd": cwd,
                "title": self._extract_html_title(abs_path) or os.path.basename(abs_path),
                "registered_at": time.time(),
            })
            save_registry(HTM_REGISTRY, entries)
        log(f"GET /htm-doc — self-heal autoregister (Issue337): {abs_path}")
        return True

    def _handle_htm_doc(self, parsed):
        """Issue50: htm-registry 등록 htm html 을 토큰 없이 serve. registry 는
        localhost 전용 endpoint(/register-doc·/hub-rescan·autoheal)로만 기록되는
        서버 관리 화이트리스트 → 등록 경로 exact-match 만 허용, cwd-jail·토큰 불요.
        토큰 없는 프로젝트(/register 미수행)의 htm 문서 열람 경로."""
        qs = parse_qs(parsed.query)
        rel = (qs.get("path") or [""])[0]
        if not rel:
            self._send_json(400, {"error": "missing path"})
            return
        abs_path = os.path.realpath(rel)
        with registry_lock:
            reg = load_registry(HTM_REGISTRY)
        reg_paths = set()
        for e in reg:
            p = e.get("path") or ""
            if p:
                reg_paths.add(p)
                reg_paths.add(os.path.realpath(p))
        if abs_path not in reg_paths and rel not in reg_paths:
            # Issue337: 생산자가 Write 툴이 아닌 경로(Bash heredoc·스크립트)로 htm 을 쓰면
            #   PostToolUse(matcher: Write) 훅 `fpm-hub-doc-register` 가 아예 발동하지 않아
            #   영구 403 dead link 가 된다(2026-07-28 <private-project-5> 실측 — 훅 정상, 트리거 부재).
            #   서버가 canonical 경로/파일명 규약을 만족하는 실존 파일을 self-heal 등록한다.
            if self._htm_doc_autoregister(abs_path):
                with registry_lock:
                    reg = load_registry(HTM_REGISTRY)
            else:
                log(f"GET /htm-doc — unregistered path rejected: {abs_path}")
                # Issue: /tmp fallback 경로(=프로젝트에 htm 폴더 부재로 트리거가 /tmp 로 회피)
                #   는 register 훅(fpm-hub-doc-register, htm 경로만 매칭)이 등록을 스킵 → 영구 403.
                #   이 경우 raw JSON 대신 "htm 폴더 만들라" 안내 HTML 을 serve (원인·해결 즉시 인지).
                if os.path.dirname(abs_path) == os.path.realpath(TMP_OUT_DIR):
                    self._send_htm_doc_tmp_hint(abs_path)
                    return
                self._send_json(403, {"error": "not a registered htm doc"})
                return
        # Issue102: htm 스킬(Issue123)이 .htm 확장자로 문서를 씀 → .html/.htm 모두 허용
        if not abs_path.endswith((".html", ".htm")):
            # Issue353_1: md 산출이 /htm-doc URL 로 들어오면 md 셸 경로로 안내(링크 호환)
            if abs_path.endswith(".md"):
                self.send_response(302)
                self.send_header("Location", "/md-doc?path=" + quote(abs_path))
                self.end_headers()
                return
            self._send_json(403, {"error": "extension not allowed"})
            return
        # Issue201/Issue202: hub-internal 모드에서 최상위 직접 열람(주소창/링크/새 탭)은 raw 문서
        #   대신 hub 쉘로 302 → 표준 htm-doc URL 을 어디서 열어도 OS 새 탭이 아니라 /hub-shell
        #   내부 iframe 탭으로 착지(쉘 onload pollDocs 가 등록분을 탭으로 수거).
        #   임베드 판정은 결정적 마커 _shell=1(쉘 JS embedUrl 부여)을 1순위로 사용 — Sec-Fetch-Dest
        #   헤더는 보조(일부 네비에서 헤더 누락 시 standalone 누출하던 Issue201 한계 보완).
        #   iframe src(_shell=1 또는 Sec-Fetch-Dest: iframe/embed)·메타데이터는 그대로 serve(redirect loop 방지).
        # Issue221: 외부 브라우저에서 채팅 fallback URL(/htm-doc?path=, non-embed) 클릭 시
        #   funnel(Issue209/213) 이 살아있는 hub-shell(=VSCode 패널, Issue170)에 tab-open SSE 를
        #   push + 클릭한 브라우저엔 "기존 hub 창에 열림" 확인 페이지를 serve → 같은 문서가
        #   VSCode 패널·외부 브라우저 양쪽에 이중 노출됐다(funnel 은 모든 표면이 같은 브라우저라는
        #   Issue209 시절 전제. Issue170 으로 render_target 이 VSCode 패널로 분리되며 그 전제 붕괴).
        #   해결: non-embed 외부 클릭은 funnel 하지 않고 "클릭한 그 브라우저에 standalone serve"
        #   (아래로 fall-through). 단일 표면. VSCode 패널 경로는 /open-simple-browser →
        #   /htm-doc?...&_shell=1(_is_embed=True) 라 이 블록 자체를 타지 않아 무영향.
        #   (구 funnel: _hub_holder_alive → tab-open SSE + HUB_OPENED_HTML / else 302 /hub-shell)
        try:
            with open(abs_path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            # Issue289: 아카이브 이동 등으로 등록 경로가 비었을 때 basename 재탐색(자가 치유).
            #   whitelist 는 이미 위에서 통과했고(=등록된 문서), tombstone 은 아래에서 재적용한다.
            with registry_lock:
                cleared = set(load_registry(HTM_CLEARED))
            moved = self._htm_resolve_moved(abs_path, cleared)
            if not moved:
                self._send_json(404, {"error": "file not found"})
                return
            try:
                with open(moved, "rb") as f:
                    body = f.read()
            except OSError:
                self._send_json(404, {"error": "file not found"})
                return
            log(f"GET /htm-doc — self-heal {abs_path} -> {moved}")
            self._htm_registry_rewrite({abs_path, rel}, moved)
            abs_path = moved
        self._send_htm_html(body, abs_path)

    def _send_htm_html(self, body: bytes, abs_path: str):
        """htm 문서 공통 serve 파이프라인 (정규화 + 쉘 shim 주입 + 200 응답).
        Issue284: /htm-doc 와 /issue-map 이 동일 표현을 갖도록 추출 — 렌더 규약이 한 곳."""
        # Issue255: 상대 <img src> → /htm-res 재작성 (registry 모드)
        #   주의: /htm-res 는 registry 등록 doc 만 인증하므로, 미등록 문서(/issue-map 경로)의
        #   상대 이미지는 403 이 된다. 이슈맵은 자립형(SVG 인라인) 규약이라 해당 없음.
        body = _rewrite_relative_imgs(body, abs_path)
        # Issue244: mermaid 런타임을 서버 표준(pinned UMD + run())으로 정규화 — esm race bomb 제거.
        body = _normalize_mermaid_runtime(body)
        # a모드 htm 의 header CSS 누락 정규화 — `<header>` 있으나 `header{}` 없으면 canonical 주입.
        body = _normalize_hub_header_css(body)
        # 본문 폭·표 정규화 — body max-width 중앙정렬 무력화(전체 폭) + 표/코드/이미지 넘침 차단.
        body = _normalize_hub_body_css(body)
        # Issue216: 닫기 버튼이 쉘 탭을 닫도록 window.close override 쉼 주입.
        body = _inject_before_body_end(body, CLOSE_SHIM)
        # Issue214(재해결): canonical 헤더에 🔗 문서 링크 복사 버튼 주입.
        body = _inject_before_body_end(body, COPY_LINK_SHIM)
        # Issue278: 헤더에 📋 세션 ID 복사 버튼 주입 (COPY_LINK_SHIM 뒤·옵션 공유).
        if _load_hub_setting()["live_session_copy_button"]:
            body = _inject_before_body_end(body, SID_COPY_SHIM)
        # Issue220: 🗂 Hub 링크 클릭 → 쉘 home 탭 전환(in-place 네비 차단).
        body = _inject_before_body_end(body, HUB_LINK_SHIM)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_md_doc(self, parsed):
        """Issue353_1 (arch A안 md-first): registry 등록 `.md` 를 서버 고정 셸로 렌더 serve.

        보안 모델은 `/htm-doc` 와 동일 등급 — registry exact-match 화이트리스트
        (+ canonical 규약 self-heal autoregister) + tombstone + ENOENT moved self-heal.
        차이는 표장뿐: md 원문을 `md_shell` 템플릿(JSON 임베드 + DOMPurify sanitize +
        CSP nonce)에 실어 반환한다. LLM 이 HTML 을 쓰지 않으므로 헤더·CSS 드리프트
        실패 클래스가 구조적으로 소멸한다."""
        qs = parse_qs(parsed.query)
        rel = (qs.get("path") or [""])[0]
        if not rel:
            self._send_json(400, {"error": "missing path"})
            return
        abs_path = os.path.realpath(rel)
        with registry_lock:
            reg = load_registry(HTM_REGISTRY)
        reg_paths = set()
        for e in reg:
            p = e.get("path") or ""
            if p:
                reg_paths.add(p)
                reg_paths.add(os.path.realpath(p))
        if abs_path not in reg_paths and rel not in reg_paths:
            if not self._htm_doc_autoregister(abs_path):
                log(f"GET /md-doc — unregistered path rejected: {abs_path}")
                self._send_json(403, {"error": "not a registered md doc"})
                return
        if not abs_path.endswith(".md"):
            self._send_json(403, {"error": "extension not allowed"})
            return
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                md_text = f.read()
        except FileNotFoundError:
            with registry_lock:
                cleared = set(load_registry(HTM_CLEARED))
            moved = self._htm_resolve_moved(abs_path, cleared)
            if not moved:
                self._send_json(404, {"error": "file not found"})
                return
            try:
                with open(moved, encoding="utf-8", errors="replace") as f:
                    md_text = f.read()
            except OSError:
                self._send_json(404, {"error": "file not found"})
                return
            log(f"GET /md-doc — self-heal {abs_path} -> {moved}")
            self._htm_registry_rewrite({abs_path, rel}, moved)
            abs_path = moved
        title = self._extract_html_title(abs_path) or os.path.basename(abs_path)
        # 헤더 📁 배지용 프로젝트 — registry cwd 우선, 없으면 `_doc_work/` 앞부분에서 유추
        proj_cwd = ""
        for e in reg:
            if os.path.realpath(e.get("path") or "") == abs_path:
                proj_cwd = e.get("cwd") or ""
                break
        if not proj_cwd:
            norm = abs_path.replace(os.sep, "/")
            if "/_doc_work/" in norm:
                proj_cwd = norm[:norm.index("/_doc_work/")]
        label = project_meta(proj_cwd)["name"] if proj_cwd else "system/___pm-tmp"
        self._send_md_html(md_text, title, abs_path, proj_cwd, label)

    def _send_md_html(self, md_text: str, title: str, abs_path: str,
                      proj_cwd: str = "", proj_label: str = ""):
        """md 문서 serve 파이프라인 — 셸 생성 + `/htm-doc` 공통 shim 주입 + CSP.

        shim(닫기·링크 복사 등)은 `_send_htm_html` 와 같은 세트를 재사용하되, CSP 가
        nonce 없는 인라인 스크립트를 차단하므로 마지막에 서버 유래 인라인 `<script>`
        전부에 nonce 를 부여한다. 이 시점의 모든 `<script>` 는 서버 템플릿·shim 산출이다
        — md 저작 내용은 JSON 문자열로만 실려 serve 시점 태그가 될 수 없다(md_shell 참조).
        mermaid 는 셸이 클라이언트 렌더 시점에 처리하므로 `_normalize_mermaid_runtime`
        는 태우지 않는다(코드펜스가 HTML 에 없어 no-op 이기도 함)."""
        nonce = md_shell.make_nonce()
        body = md_shell.render_md_shell(md_text, title, abs_path, nonce,
                                        proj_cwd, proj_label)
        # 셸이 canonical <header> 를 직접 갖고 CSS 는 htm 과 같은 정규화기가 붙인다
        # (헤더 표현이 두 경로에서 갈리지 않도록 — 셸 1벌 원칙의 CSS 판).
        body = _normalize_hub_header_css(body)
        body = _normalize_hub_body_css(body)
        body = _inject_before_body_end(body, CLOSE_SHIM)
        body = _inject_before_body_end(body, COPY_LINK_SHIM)
        if _load_hub_setting()["live_session_copy_button"]:
            body = _inject_before_body_end(body, SID_COPY_SHIM)
        body = _inject_before_body_end(body, HUB_LINK_SHIM)
        body = body.replace(b"<script>", b'<script nonce="' + nonce.encode("ascii") + b'">')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", md_shell.csp_header(nonce))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_issue_map(self, parsed):
        """Issue284: 프로젝트 이슈맵(`Issue_map.htm`) serve.

        보안 모델 — registry 화이트리스트를 쓸 수 없어(프로젝트 루트 파일은 등록 대상이
        아님) 다음 게이트를 조합한다:
          1. source-IP — 전역 `_ip_allowed()` (Servers.md allowlist / bind self). 모든
             요청 진입점에서 이미 적용되므로 본 핸들러에 추가 게이트를 두지 않는다.
             Issue284_2: 종전의 loopback 전용 게이트는 **오분류**였다. loopback 전용은
             호스트에서 부수효과를 실행하는 엔드포인트(`/ob`·`/open-session` 의 `open`)와
             $HOME 전역 jail(`/htm-res` abs) 의 등급이고, 이슈맵은 문서를 읽어 돌려주는
             `/htm-doc` 등급이다. LAN(`bind_host` 비루프백) 접속에서 403 이 나 기능이
             통째로 죽었다.
          2. cwd 화이트리스트 — hub 등록 프로젝트(projects) ∪ Projects.md 목록의 트리
             안쪽만. 세션 cwd 가 하위 폴더로 드리프트해도(Issue282) 카드 링크가 살아있어야
             하므로 exact 가 아닌 at-or-under 매치.
          3. 해석 결과 재검증 — 상향 탐색이 등록 트리 **밖의** 조상 `Issue.md` 로 빠져나가
             무관한 프로젝트의 맵을 serve 하지 않도록, 찾아낸 맵의 디렉토리에도 2 와 같은
             at-or-under 판정을 다시 적용한다.
          4. 파일명 서버 고정 — 클라이언트는 cwd 만 넘기고 실제 경로는 서버가 재계산
             (`_issue_map_path`) → path traversal 입력면 자체가 없음
        """
        cwd = get_cwd_param(parsed)
        if not cwd:
            self._send_json(400, {"error": "missing cwd"})
            return
        cwd_real = os.path.realpath(os.path.expanduser(cwd))
        allowed = set()
        with projects_lock:
            for p in projects.values():
                c = p.get("cwd") or ""
                if c:
                    allowed.add(os.path.realpath(os.path.expanduser(c)))
        for r in _load_projects_list():
            p = (r.get("path") or "").strip()
            if p:
                allowed.add(os.path.realpath(os.path.expanduser(p)))

        def _within(target: str) -> bool:
            return any(target == root or target.startswith(root.rstrip(os.sep) + os.sep)
                       for root in allowed)

        if not _within(cwd_real):
            log(f"GET /issue-map — unknown cwd rejected: {cwd_real}")
            self._send_json(403, {"error": "cwd not a registered project"})
            return
        path = _issue_map_path(cwd_real)
        if not path:
            self._send_json(404, {"error": f"{ISSUE_MAP_NAME} not found"})
            return
        # 게이트 3 — 상향 탐색이 등록 트리 밖으로 빠져나간 경우 차단.
        if not _within(os.path.dirname(path)):
            log(f"GET /issue-map — resolved map outside registered tree: {path}")
            self._send_json(403, {"error": "map outside registered project"})
            return
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._send_json(404, {"error": "file not found"})
            return
        # 구 builder stale 맵 헤더 합성 (신 builder 산출은 no-op). proj_cwd = 맵의 프로젝트 루트.
        proj_root = os.path.dirname(path)
        body = _synthesize_hub_header(body, proj_root, os.path.basename(proj_root))
        self._send_htm_html(body, path)

    def _handle_fbot_map(self, parsed):
        """Issue402 ⓐ: 핀봇 조직도(`/fbot-map`) — `registry.db` 직독 **실시간 생성**.

        게이트는 `/projects-map` 과 같은 등급(데이터를 읽어 돌려줌)이라 진입점 공통
        `_ip_allowed()` 만 적용한다. 경로 입력면이 없고(DB 경로는 서버 고정) 쿼리는
        `root` 하나뿐이며 그 값도 레지스트리 루트 목록과 **대조**해서만 쓰므로
        traversal·주입 면이 생기지 않는다.

        파일 산출물을 만들지 않는 이유 — prj3#Issue438 ③ "중간 사영 파일 금지 · 판정
        단일 지점". `Issue_map.htm`·`Projects_map.htm` 패턴을 여기에 복제하면 조직 상태의
        판정원이 DB 와 파일 둘로 갈라진다.
        """
        import urllib.parse as _u
        root = (_u.parse_qs(parsed.query).get("root") or [""])[0].strip()
        data = _fbot_org_data(root)
        if data["error"]:
            # 조용히 빈 맵을 그리면 "봇이 없다" 로 읽힌다 — Issue400 이 bots_error 를
            #   분리한 것과 같은 이유로 오류는 세운다.
            log(f"GET /fbot-map — registry error: {data['error']}", "WARNING")
            self._send_fbot_map_notice(
                503, "핀봇 레지스트리를 읽지 못했습니다",
                f"<p>조직도는 <code>registry.db</code> 를 직접 읽어 그립니다. "
                f"읽기가 실패해 <b>조직이 없는 것인지 못 읽은 것인지</b> 구분할 수 없어 "
                f"빈 그림 대신 이 오류를 표시합니다.</p>"
                f"<pre>{html.escape(data['error'])}</pre>")
            return
        if not data["nodes"]:
            self._send_fbot_map_notice(
                404, "핀봇이 아직 없습니다",
                "<p>레지스트리에 등록된 핀봇이 없습니다. fbot 미설치이거나 "
                "채용(스폰)이 아직 한 건도 없는 상태입니다.</p>"
                "<p>설계·절차: <code>~/.claude/_doc_arch/fbot-arch.md</code></p>")
            return
        self._send_htm_html(self._render_fbot_map(data),
                            os.path.join(REPO_ROOT, "fbot-map.htm"))

    def _send_fbot_map_notice(self, code: int, title: str, body_html: str):
        """조직도 비정상 경로(레지스트리 오류·봇 0)의 안내 HTML. raw JSON 을 돌려주면
        새 탭에 문자열만 뜨므로 사람이 읽는 페이지로 내보낸다 (`/projects-map` 선례)."""
        page = (
            "<!doctype html><html lang=ko><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>"
            "body{font:15px/1.6 -apple-system,system-ui,sans-serif;max-width:760px;"
            "margin:3rem auto;padding:0 1.2rem;color:#222}"
            "h1{font-size:1.25rem}code{background:#f2f2f5;padding:.15em .4em;border-radius:4px}"
            "pre{background:#1e1e24;color:#e8e8ee;padding:1rem;border-radius:8px;overflow-x:auto}"
            "@media(prefers-color-scheme:dark){body{background:#16161a;color:#ddd}"
            "code{background:#2a2a33}}"
            "</style></head><body>"
            f"<h1>🤖 {html.escape(title)}</h1>{body_html}"
            "</body></html>").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    @staticmethod
    def _render_fbot_map(data: dict) -> bytes:
        """조직도 페이지 HTML. mermaid 는 서버 표준 런타임(`_normalize_mermaid_runtime`)이
        `_send_htm_html` 에서 주입하므로 여기서 `<script>` 를 저작하지 않는다.

        명부·원장 표를 **함께** 싣는 이유 — 다이어그램이 못 뜨는 환경(런타임 차단·구
        브라우저)에서도 같은 사실을 읽을 수 있어야 한다. 조직 관측이 렌더 성공 여부에
        걸리면 "묻지 않아도 안다"(prj3#Issue438) 가 그 순간 무너진다.
        """
        import urllib.parse as _u
        nodes = {n["bot_id"]: n for n in data["nodes"]}
        root = data["root_filter"]
        esc = html.escape

        # 루트 필터 칩 — ⓓ `?root=` 로 해당 루트 하위 트리만 본다.
        chips = ['<a class="fm-chip%s" href="/fbot-map">전체</a>'
                 % ("" if root else " on")]
        for rid in data["roots"]:
            t = nodes.get(rid, {}).get("title") or rid
            chips.append('<a class="fm-chip%s" href="/fbot-map?root=%s">%s</a>'
                         % (" on" if rid == root else "",
                            esc(_u.quote(rid)), esc(t)))

        warn = ""
        if data["unknown_root"]:
            warn = ('<div class="fm-warn">⚠ <code>root=%s</code> 는 루트 핀봇이 아닙니다 '
                    '— 전체 조직도를 표시합니다.</div>' % esc(root))
        orphans = [n for n in data["nodes"] if n["orphan"]]
        if orphans:
            warn += ('<div class="fm-warn">⚠ 배분 원장에만 있고 명부(<code>bot</code> 테이블)에 '
                     '없는 대상 %d건: %s — 노드를 지우면 엣지가 조용히 사라지므로 '
                     '점선으로 구분해 남겨둡니다.</div>'
                     % (len(orphans), esc(", ".join(n["bot_id"] for n in orphans))))

        # 아이콘·개체색은 채용 시 생성된 것(prj3#Issue438 ③)을 재사용한다 —
        #   조직도용 새 색 체계를 만들지 않는다(Issue402 ⓔ).
        def _icon_cell(n):
            if n["orphan"]:
                return '<span class="fm-dot fm-dot-orphan">?</span>'
            uri = n.get("icon_uri") or ""
            if uri:
                return '<img class="fm-icon" src="%s" alt="%s">' % (esc(uri), esc(n["role"]))
            c = n["color"] or "#999"
            return '<span class="fm-dot" style="background:%s"></span>' % esc(c)

        tbody = []
        for n in data["nodes"]:
            group = nodes.get(n["root"], {}).get("title") or n["root"]
            task = n["current_task"] or ""
            tbody.append(
                "<tr%s><td>%s</td><td>%s%s</td><td><code>%s</code></td><td>%s</td>"
                "<td>%s %s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    ' class="fm-orphan"' if n["orphan"] else "",
                    _icon_cell(n),
                    esc(n["title"]),
                    ' <span class="fm-badge">루트</span>' if n["root"] == n["bot_id"] and not n["orphan"] else "",
                    esc(n["bot_id"]), esc(n["role"]),
                    esc(n["state_emoji"]), esc(n["state_label"] or "—"),
                    esc(n["career"] or "—"),
                    ("prj%s" % esc(str(n["prj"]))) if n["prj"] is not None else "—",
                    esc(group),
                    esc(task) if task else '<span class="fm-mute">—</span>'))

        dbody = []
        for e in sorted(data["dispatch"], key=lambda x: -x["ts"]):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["ts"])) if e["ts"] else "—"
            dbody.append(
                "<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    ' class="fm-cancel"' if e["status"] == "cancelled" else "",
                    esc(when),
                    esc(nodes.get(e["src"], {}).get("title") or e["src"]),
                    esc(nodes.get(e["dst"], {}).get("title") or e["dst"]),
                    esc(e["issue"] or "—"), esc(e["status"] or "—")))
        if not dbody:
            dbody.append('<tr><td colspan="5" class="fm-mute">배분 원장에 이 범위의 '
                         '기록이 없습니다 — 채용 관계만으로 그려진 그룹입니다.</td></tr>')

        mermaid = _fbot_map_mermaid(data)
        css = (
            "body{font:15px/1.65 -apple-system,system-ui,sans-serif;color:#222;background:#fff}"
            ".fm-meta{color:#666;font-size:.88em;margin:.2rem 0 .8rem}"
            ".fm-chips{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0 1rem}"
            ".fm-chip{display:inline-block;padding:.18rem .6rem;border:1px solid #ccd;"
            "border-radius:12px;font-size:.85em;text-decoration:none;color:#334}"
            ".fm-chip.on{background:hsl(238,45%,88%);border-color:hsl(238,45%,62%);font-weight:600}"
            ".fm-warn{background:#fff7e6;border:1px solid #f0c36d;border-radius:8px;"
            "padding:.6rem .9rem;margin:.5rem 0;font-size:.9em}"
            ".fm-legend{font-size:.85em;color:#555;margin:.6rem 0 1.2rem}"
            ".fm-legend b{color:#222}"
            # mermaid 런타임의 useMaxWidth 는 SVG 에 인라인 max-width 를 박아 다이어그램을
            #   컨테이너 폭으로 **축소**한다. 조직도는 팬아웃이 넓어 축소율이 0.5 밑으로
            #   떨어지고(실측) 노드 글자가 읽히지 않는다 → 축소 대신 가로 스크롤을 준다.
            #   인라인 스타일을 이기려면 !important 가 필요하다.
            "pre.mermaid{overflow-x:auto;overflow-y:hidden}"
            "pre.mermaid svg{max-width:none !important;width:auto !important;height:auto !important}"
            "table{border-collapse:collapse;width:100%;font-size:.88em;margin-bottom:1.6rem}"
            "th,td{border:1px solid #e2e2e8;padding:.35rem .55rem;text-align:left;vertical-align:top}"
            "th{background:#f4f4f8}"
            ".fm-icon{width:22px;height:22px;border-radius:50%;display:block}"
            ".fm-dot{width:18px;height:18px;border-radius:50%;display:inline-block}"
            ".fm-dot-orphan{background:#f5f5f5;border:1.5px dashed #c62828;color:#c62828;"
            "text-align:center;line-height:15px;font-size:.75em;font-weight:700}"
            ".fm-orphan{background:#fff5f5}"
            ".fm-cancel{opacity:.5}"
            ".fm-badge{font-size:.72em;background:hsl(238,45%,88%);border-radius:3px;padding:0 .3rem}"
            ".fm-mute{color:#999}"
            "code{background:#f2f2f5;padding:.1em .35em;border-radius:4px;font-size:.92em}"
            "@media(prefers-color-scheme:dark){body{background:#16161a;color:#ddd}"
            "th{background:#24242c}th,td{border-color:#33333c}.fm-chip{color:#ccd;border-color:#44445a}"
            ".fm-orphan{background:#2b1a1a}.fm-warn{background:#2b2410;border-color:#7a5c1e}"
            "code{background:#2a2a33}.fm-legend{color:#aaa}.fm-legend b{color:#eee}}"
        )
        total = len(data["nodes"])
        active = sum(1 for n in data["nodes"] if n["state"] in FBOT_ACTIVE_STATES)
        page = (
            "<!doctype html><html lang=ko><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>핀봇 조직도</title><style>" + css + "</style></head><body>"
            "<h1>🤖 핀봇 조직도</h1>"
            + warn
            + '<div class="fm-chips">' + "".join(chips) + "</div>"
            + '<div class="fm-meta">'
            + "그룹 %d · 봇 %d(활성 %d) · 채용 엣지 %d · 배분 엣지 %d"
              % (len(data["roots"]), total, active,
                 len(data["hires"]), len(data["dispatch"]))
            + " · <code>registry.db</code> 직독(요청 시각 기준 실시간)</div>"
            + '<div class="fm-legend">'
            "<b>엣지 2원천</b> — <b>실선</b>은 채용(<code>bot.parent_bot_id</code>), "
            "<b>화살표</b>는 배분(<code>job.kind=fbot_dispatch</code>)입니다. "
            "배분 원장만으로 그리면 <code>fpm-do</code> 직접 위임이 원장을 거치지 않아 "
            "(prj3#Issue438 ④) 중역핀봇 밑이 비어 보입니다 — 두 원천을 합성해야 조직이 보입니다. "
            "취소된 배분은 흐리게, 명부에 없는 대상은 점선으로 남깁니다. "
            "<code>⚙ 세션 N</code> 은 엣지가 아니라 그 봇의 활동 횟수입니다.</div>"
            + '<pre class="mermaid">' + html.escape(mermaid) + "</pre>"
            + "<h2>명부</h2><table><thead><tr><th></th><th>호칭</th><th>bot_id</th>"
            "<th>role</th><th>상태</th><th>career</th><th>prj</th><th>소속</th>"
            "<th>현재 작업</th></tr></thead><tbody>" + "".join(tbody) + "</tbody></table>"
            + "<h2>배분 원장</h2><table><thead><tr><th>생성</th><th>배분자</th>"
            "<th>대상</th><th>이슈</th><th>status</th></tr></thead><tbody>"
            + "".join(dbody) + "</tbody></table>"
            # mermaid 런타임(`_normalize_mermaid_runtime`)의 useMaxWidth 가 SVG 를 컨테이너
            #   폭으로 **축소**한다. 조직도는 팬아웃이 넓어(실측 viewBox 2222px) 축소율이
            #   0.52 까지 떨어져 노드 글자가 8px 로 뭉개졌다. CSS 만으로는 못 이긴다 —
            #   svg 의 width="100%" 속성 때문에 max-width:none·width:auto 를 줘도 여전히
            #   컨테이너를 채운다(실측). 렌더 후 viewBox 의 원래 픽셀 폭을 되돌리고, 넘치는
            #   만큼은 <pre> 가 가로 스크롤한다. 공용 런타임은 건드리지 않는다(다른 맵 영향 0).
            #   ⚠️ 런타임이 렌더 완료를 알려주지 않으므로 폴링한다 — projects-map 의
            #   오버레이 스크립트와 같은 방식이다.
            "<script>(function(){var n=0;function fit(){"
            "var s=document.querySelector('pre.mermaid svg');if(!s)return false;"
            "var v=(s.getAttribute('viewBox')||'').split(' ');"
            "var w=parseFloat(v[2]),h=parseFloat(v[3]);if(!(w>0))return false;"
            "s.style.setProperty('width',Math.ceil(w)+'px','important');"
            "if(h>0)s.style.setProperty('height',Math.ceil(h)+'px','important');return true;}"
            "var t=setInterval(function(){if(fit()||++n>40)clearInterval(t);},150);})();</script>"
            "</body></html>")
        return _synthesize_hub_header(page.encode("utf-8"), REPO_ROOT,
                                      os.path.basename(REPO_ROOT))

    def _handle_projects_map(self, parsed):
        """Issue293: 프로젝트 트리 맵(`Projects_map.htm`) serve.

        `/issue-map` 과 같은 등급(문서를 읽어 돌려줌)이라 게이트도 같다 — 진입점 공통
        `_ip_allowed()` 만 적용한다. 다만 이 맵은 ___pm 루트에 1개뿐이라 cwd 를 받지 않고
        경로를 `REPO_ROOT` 로 고정하므로, 이슈맵이 필요로 했던 cwd 화이트리스트·상향 탐색
        재검증·traversal 방어가 **입력면 부재로 불필요**하다.

        파일은 `Projects.md` 로부터 재생성되는 gitignore 산출물이라 부재가 정상일 수 있다.
        그 경우 raw 404 JSON 대신 재생성 커맨드를 담은 안내 HTML 을 돌려준다.

        Issue321: 새로고침 시 `Projects.md` 가 산출물보다 최신이면(mtime 비교) serve
        직전에 빌더를 자동 실행해 stale 맵을 재생성한다. 빌더 실패·부재는 조용히
        무시하고 기존 파일을 그대로 돌려준다(fail-safe).
        """
        path = os.path.join(REPO_ROOT, PROJECTS_MAP_NAME)
        self._rebuild_projects_map_if_stale(path)
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            log(f"GET /projects-map — not built yet: {path}")
            self._send_projects_map_hint(path)
            return
        # 구 builder stale 맵 헤더 합성 (신 builder 산출·authored 는 no-op).
        body = _synthesize_hub_header(body, REPO_ROOT, os.path.basename(REPO_ROOT))
        self._send_htm_html(body, path)

    def _send_projects_map_hint(self, path: str):
        """Issue293: 트리 맵 미생성 시 원인·재생성 커맨드 안내 HTML (raw JSON 404 대체)."""
        cmd = f"cd {REPO_ROOT} && python3 {PROJECTS_MAP_BUILDER}"
        html = (
            "<!doctype html><html lang=ko><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>프로젝트 트리 맵 미생성</title><style>"
            "body{font:15px/1.6 -apple-system,system-ui,sans-serif;max-width:760px;"
            "margin:3rem auto;padding:0 1.2rem;color:#222}"
            "h1{font-size:1.3rem}code{background:#f2f2f5;padding:.15em .4em;border-radius:4px}"
            "pre{background:#1e1e24;color:#e8e8ee;padding:1rem;border-radius:8px;overflow-x:auto}"
            ".box{background:#fff7e6;border:1px solid #f0c36d;border-radius:8px;padding:1rem 1.2rem;margin:1.2rem 0}"
            "@media(prefers-color-scheme:dark){body{background:#16161a;color:#ddd}"
            "code{background:#2a2a33}.box{background:#2b2410;border-color:#7a5c1e}}"
            "</style></head><body>"
            f"<h1>🌳 <code>{PROJECTS_MAP_NAME}</code> 가 아직 생성되지 않았습니다</h1>"
            "<p>이 맵은 <code>Projects.md</code> 의 <code># Project Tree</code> 섹션으로부터 "
            "생성되는 산출물이며 git 추적 대상이 아닙니다(재생성물). 클론 직후이거나 "
            "정리된 뒤에는 없는 것이 정상입니다.</p>"
            "<div class=box><b>재생성</b>"
            f"<pre>{cmd}</pre>"
            "생성 후 이 페이지를 새로고침하면 트리가 표시됩니다.</div>"
            f"<p style=color:#888>기대 경로: <code>{path}</code></p>"
            "</body></html>"
        )
        body = html.encode("utf-8")
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _rebuild_projects_map_if_stale(self, out_path: str):
        """Issue321: `Projects.md` mtime > `Projects_map.htm` mtime 이면 빌더 재실행.

        새로고침만으로 최신 트리를 보게 하는 목적. 판정·실행 모두 best-effort —
        소스 부재·빌더 부재·빌더 실패·타임아웃은 모두 조용히 무시하고 기존 산출물을
        그대로 serve 한다(맵 표시가 소스 편집에 막히지 않게).
        """
        src = os.path.join(REPO_ROOT, "Projects.md")
        builder = os.path.join(REPO_ROOT, PROJECTS_MAP_BUILDER)
        try:
            src_mtime = os.path.getmtime(src)
        except OSError:
            return  # 소스 없음 → 재빌드 불가
        # Issue398: note 인라인 편집은 `_note.md` 만 갱신한다 — 소스 2개 중 최신을 기준으로
        # 삼아야 새로고침이 방금 저장한 메모를 되돌려 보여준다. 부재는 무시(선택 파일).
        try:
            src_mtime = max(src_mtime,
                            os.path.getmtime(os.path.join(REPO_ROOT, "_note.md")))
        except OSError:
            pass
        try:
            out_mtime = os.path.getmtime(out_path)
        except OSError:
            out_mtime = 0.0  # 산출물 없음 → 재빌드 시도(빌더가 있으면)
        if src_mtime <= out_mtime:
            return  # 최신 — no-op
        if not os.path.isfile(builder):
            return  # 빌더 부재 → 안내 HTML 경로에 위임
        try:
            subprocess.run(
                ["python3", builder],
                cwd=REPO_ROOT,
                capture_output=True,
                timeout=20,
            )
            log(f"GET /projects-map — rebuilt (Projects.md stale): {out_path}")
        except Exception as e:
            log(f"GET /projects-map — rebuild skipped: {e}")

    def _handle_projects_map_note(self, parsed):
        """Issue398: note 박스 인라인 편집 저장 — `{REPO_ROOT}/_note.md` 고정 경로 기록.

        `/projects-map` GET 과 같은 등급의 게이트(do_POST 공통 `_ip_allowed` + host gate)만
        적용한다 — 대상 경로가 REPO_ROOT 고정이라 traversal 입력면이 없고, 평문 md 로만
        기록한다. 쓰기는 tmp → `os.replace` 원자 교체 — 초단위 자동 저장과 새로고침
        재빌드(`_rebuild_projects_map_if_stale`)가 겹쳐도 절반 파일을 읽지 않게.
        """
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > 64 * 1024:
            self._send_json(400, {"error": "invalid content length (1..65536)"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        md = body.get("md")
        if not isinstance(md, str):
            self._send_json(400, {"error": "md (string) is required"})
            return
        md = md.replace("\r\n", "\n").strip()
        path = os.path.join(REPO_ROOT, "_note.md")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(md + ("\n" if md else ""))
            os.replace(tmp, path)
        except OSError as e:
            self._send_json(500, {"error": f"write failed: {e}"})
            return
        log(f"POST /projects-map/note — saved {len(md.encode('utf-8'))}B")
        self._send_json(200, {"status": "saved"})

    def _handle_view(self, parsed):
        """Issue16_2: dashboard·form HTML을 동일 origin(http://127.0.0.1)으로 serve.
        Chrome/Safari가 file://+http 조합 fetch를 CORS로 거부하는 문제 해결."""
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        qs = parse_qs(parsed.query)
        rel = (qs.get("path") or [""])[0]
        if not rel:
            self._send_json(400, {"error": "missing path"})
            return
        abs_path = rel if os.path.isabs(rel) else os.path.join(cwd, rel)
        abs_path = os.path.realpath(abs_path)
        cwd_real = os.path.realpath(cwd)
        if not path_within_serve_roots(abs_path, cwd_real):
            log(f"GET /view — path outside cwd rejected: {abs_path}")
            self._send_json(403, {"error": "path outside cwd"})
            return
        # Issue393: /data 와 동일 게이트. dash 인라인 렌더보다 **앞**에 둔다 —
        #   뒤에 두면 `.dash.json` 분기가 먼저 먹어 dotfile 이 렌더 경로로 빠져나간다.
        if path_is_sensitive(abs_path):
            log(f"GET /view — sensitive path rejected: {os.path.basename(abs_path)}")
            self._send_json(403, {"error": "path not allowed"})
            return
        # Issue35: .dash.{json,yaml,yml} 동적 렌더 (인라인 dashboard HTML wrapper)
        # Issue138: cwd/token 전달 — 컨트롤바(stop/kill/refresh) /control 호출 wiring
        if abs_path.endswith((".dash.json", ".dash.yaml", ".dash.yml")):
            self._serve_dash_inline(abs_path, cwd, token)
            return
        # Issue102: htm 스킬(Issue123)이 .htm 확장자로 문서를 씀 → .html/.htm 모두 허용
        if not abs_path.endswith((".html", ".htm")):
            # Issue353_1: 토큰 라우트로 md 가 오면 md 셸로 위임 (registry 게이트는 저쪽이 재검)
            if abs_path.endswith(".md"):
                self.send_response(302)
                self.send_header("Location", "/md-doc?path=" + quote(abs_path))
                self.end_headers()
                return
            self._send_json(403, {"error": "extension not allowed"})
            return
        try:
            with open(abs_path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json(404, {"error": "file not found"})
            return
        # Issue26: 세션 고정 페이지(claude-htm-session-*.html)에 SSE auto-reload 스크립트 주입
        # 동일 파일 broadcast(reload) 수신 시 location.reload()
        basename = os.path.basename(abs_path)
        if basename.startswith("claude-htm-session-") and basename.endswith(".html"):
            inject = (
                b"<script>(function(){"
                b"try{"
                b"var p=new URLSearchParams(window.location.search);"
                b"var cwd=p.get('cwd'),tok=p.get('token'),tgt=p.get('path');"
                b"if(!cwd||!tok)return;"
                b"var url='/events?cwd='+encodeURIComponent(cwd)+'&token='+encodeURIComponent(tok);"
                # Issue258: Page Visibility 게이팅 — 백그라운드 탭 SSE 연결 반납, 가시 복귀
                #   시 재연결. (재수정: 크래시 근본은 iframe 재네비 detached-doc 누수 →
                #   navTo 노드 swap + pagehide 반납이 담당. 게이팅은 보조.)
                b"var es=null;"
                b"function openSSE(){if(es)return;es=new EventSource(url);"
                b"es.addEventListener('reload',function(ev){"
                b"try{var b=JSON.parse(ev.data||'{}');var f=b.file||'';"
                b"var tn=tgt?tgt.split('/').pop():'';"
                b"if(!tn||f.endsWith(tn)){location.reload();}"
                b"}catch(e){location.reload();}"
                b"});"
                b"es.addEventListener('error',function(){});}"
                b"function closeSSE(){if(es){try{es.close();}catch(e){}es=null;}}"
                b"document.addEventListener('visibilitychange',function(){"
                b"if(document.visibilityState==='hidden'){closeSSE();}else{openSSE();}"
                b"});"
                # Issue258(재수정): doc 폐기 직전 SSE 반납 — detached document 누수 차단.
                b"window.addEventListener('pagehide',function(){closeSSE();});"
                b"if(document.visibilityState!=='hidden'){openSSE();}"
                b"}catch(e){}"
                b"})();</script>"
            )
            lower = body.lower()
            idx = lower.rfind(b"</body>")
            if idx >= 0:
                body = body[:idx] + inject + body[idx:]
            else:
                body = body + inject
        # Issue214(재해결): /view 로 serve 되는 문서(form `_b_`·response 등)도 hub-shell
        #   iframe 안에서 열리므로 닫기 버튼의 window.close() 가 no-op 였다(간헐적 닫기 실패의
        #   원인 — 탭이 /htm-doc 경로로 열리면 닫히고 /view 경로면 안 닫힘). _handle_htm_doc 와
        #   동일하게 CLOSE_SHIM(닫기 정상화) + COPY_LINK_SHIM(🔗 링크 복사) 주입.
        # Issue255: 상대 <img src> → /htm-res 재작성 (cwd+token 모드)
        from urllib.parse import quote as _q255
        body = _rewrite_relative_imgs(
            body, abs_path,
            extra_query=f"cwd={_q255(cwd, safe='')}&token={_q255(token, safe='')}")
        # Issue244: mermaid 런타임 정규화(esm race bomb 제거) — htm-doc 경로와 동일.
        body = _normalize_mermaid_runtime(body)
        # header CSS 누락 정규화 — htm-doc 경로와 동일.
        body = _normalize_hub_header_css(body)
        # 본문 폭·표 정규화 — htm-doc 경로와 동일.
        body = _normalize_hub_body_css(body)
        body = _inject_before_body_end(body, CLOSE_SHIM)
        body = _inject_before_body_end(body, COPY_LINK_SHIM)
        # Issue278: 헤더에 📋 세션 ID 복사 버튼 주입 (COPY_LINK_SHIM 뒤·옵션 공유).
        if _load_hub_setting()["live_session_copy_button"]:
            body = _inject_before_body_end(body, SID_COPY_SHIM)
        body = _inject_before_body_end(body, HUB_LINK_SHIM)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    @classmethod
    def _render_chart_svg(cls, value) -> str:
        """chart/sparkline 위젯 value → inline SVG 라인+area 차트 문자열.
        허용 형태:
          - list[number]                          → y 시계열, x=index
          - "1,2,3" / "1 2 3"                      → 파싱
          - {points:[...], ymax?, ymin?, unit?, label?}
          - '{"points":[...]}' / '[1,2,3]'         → JSON 문자열 자동 역직렬화
        파싱 실패·포인트<2 → "" 반환(호출부가 일반 value 렌더로 fallback)."""
        # dict/배열 JSON 문자열 → 객체 (dynamic_eval 견고성, _coerce 일관 적용)
        value = cls._coerce_widget_value(value)
        ymax = ymin = None
        unit = ""
        label = ""
        pts_raw = value
        if isinstance(value, dict):
            pts_raw = value.get("points") or value.get("series") or value.get("data")
            ymax = value.get("ymax")
            ymin = value.get("ymin")
            unit = str(value.get("unit") or "")
            label = str(value.get("label") or "")
        nums = []
        if isinstance(pts_raw, str):
            for tok in pts_raw.replace(",", " ").split():
                try:
                    nums.append(float(tok))
                except ValueError:
                    pass
        elif isinstance(pts_raw, (list, tuple)):
            for v in pts_raw:
                try:
                    nums.append(float(v))
                except (TypeError, ValueError):
                    pass
        if len(nums) < 2:
            return ""
        # 시계열은 0 기준 시작이 기본 — ymin 미지정 시 min(nums) 가 아니라 0.0 사용
        #   (작은 변화 과장 방지, 절대 스케일 표시). 음수 데이터면 실제 최소로 하강.
        if isinstance(ymin, (int, float)) and not isinstance(ymin, bool):
            lo = float(ymin)
        else:
            lo = min(0.0, min(nums))
        hi = float(ymax) if isinstance(ymax, (int, float)) and not isinstance(ymax, bool) else max(nums)
        if hi <= lo:
            hi = lo + 1.0
        W, H = 320.0, 90.0
        PADL, PADR, PADT, PADB = 6.0, 6.0, 8.0, 8.0
        pw, ph = W - PADL - PADR, H - PADT - PADB
        n = len(nums)
        def X(idx):
            return PADL + (idx / (n - 1)) * pw
        def Y(v):
            return PADT + (1 - (v - lo) / (hi - lo)) * ph
        line = " ".join(
            ("M" if i == 0 else "L") + f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(nums)
        )
        area = (
            f"M{X(0):.1f},{PADT + ph:.1f} "
            + " ".join("L" + f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(nums))
            + f" L{X(n - 1):.1f},{PADT + ph:.1f} Z"
        )
        cur = nums[-1]
        cur_txt = f"{cur:.1f}{unit}" if (cur != int(cur)) else f"{int(cur)}{unit}"
        cx, cy = X(n - 1), Y(cur)
        cap = html.escape(label) if label else ""
        cap_html = f'<div class="chart-cap">{cap}</div>' if cap else ""
        return (
            f'<svg class="w-chart" viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none">'
            f'<path d="{area}" fill="hsla(273,60%,55%,0.18)"/>'
            f'<path d="{line}" fill="none" stroke="hsl(273,70%,55%)" stroke-width="2"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="hsl(273,70%,55%)"/>'
            f'</svg>'
            f'<div class="chart-cur">{html.escape(cur_txt)}'
            f'<span class="chart-range"> (min {lo:g} · max {hi:g} · n={n})</span></div>'
            f'{cap_html}'
        )

    @staticmethod
    def _coerce_widget_value(v):
        """dynamic_eval 결과는 value 에 JSON 문자열로 실림 → list/dict 로 역직렬화.
        '[' 또는 '{' 로 시작하는 문자열만 파싱 시도, 실패·비대상은 원본 반환."""
        if isinstance(v, str):
            s = v.strip()
            if s and s[0] in "[{":
                try:
                    return json.loads(s)
                except (ValueError, TypeError):
                    return v
        return v

    @classmethod
    def _render_checklist(cls, value, items_field) -> str:
        """checklist → ✅/⬜ 리스트. value(문자열 JSON) 우선, 없으면 items 필드."""
        data = cls._coerce_widget_value(value)
        if not isinstance(data, list):
            data = items_field if isinstance(items_field, list) else None
        if not isinstance(data, list) or not data:
            return ""
        lis = []
        for it in data:
            if isinstance(it, dict):
                done = bool(it.get("done"))
                label = str(it.get("label", ""))
            else:
                done = False
                label = str(it)
            mark = "✅" if done else "⬜"
            ccls = "done" if done else "todo"
            lis.append(f'<li class="ck-{ccls}">{mark} {html.escape(label)}</li>')
        return f'<ul class="w-checklist">{"".join(lis)}</ul>'

    @classmethod
    def _render_table_widget(cls, value, columns, rows_field) -> str:
        """table → HTML table. value(문자열 JSON rows) 우선, 없으면 rows 필드."""
        data = cls._coerce_widget_value(value)
        if not isinstance(data, list):
            data = rows_field if isinstance(rows_field, list) else None
        if not isinstance(data, list):
            return ""
        thead = ""
        if isinstance(columns, list) and columns:
            thead = "<thead><tr>" + "".join(
                f"<th>{html.escape(str(c))}</th>" for c in columns
            ) + "</tr></thead>"
        trs = []
        for row in data:
            if isinstance(row, (list, tuple)):
                tds = "".join(f"<td>{html.escape(str(c))}</td>" for c in row)
            else:
                tds = f"<td>{html.escape(str(row))}</td>"
            trs.append(f"<tr>{tds}</tr>")
        if not trs and not thead:
            return ""
        return f'<table class="w-table">{thead}<tbody>{"".join(trs)}</tbody></table>'

    @classmethod
    def _render_pie_svg(cls, value) -> str:
        """pie/donut/gauge → 진행률 도넛 SVG (0 기준 고정). value 허용:
          - number 0~100 (퍼센트)
          - {value, max?, label?, unit?} → max 지정 시 value/max*100, center 텍스트=label/퍼센트
          - '{"value":7,"max":8}'  → JSON 문자열 자동 역직렬화
        파싱 실패 → 빈 문자열(일반 value 렌더 fallback)."""
        value = cls._coerce_widget_value(value)
        mx = None
        label = None
        unit = ""
        raw = value
        if isinstance(value, dict):
            raw = value.get("value")
            mx = value.get("max")
            label = value.get("label")
            unit = str(value.get("unit") or "")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return ""
        if isinstance(mx, (int, float)) and not isinstance(mx, bool) and mx:
            pct = val / float(mx) * 100.0
            center = label or f"{val:g}/{mx:g}"
        else:
            pct = val
            center = label or (f"{val:g}{unit}" if unit else f"{val:.0f}%")
        pct = max(0.0, min(100.0, pct))
        r = 52.0
        cx = cy = 64.0
        import math
        C = 2 * math.pi * r
        dash = pct / 100.0 * C
        return (
            f'<svg class="w-pie" viewBox="0 0 128 128">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e8e8ee" stroke-width="16"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="hsl(273,70%,55%)" '
            f'stroke-width="16" stroke-linecap="round" '
            f'stroke-dasharray="{dash:.2f} {C - dash:.2f}" transform="rotate(-90 {cx} {cy})"/>'
            f'<text x="{cx}" y="{cy + 7:.0f}" text-anchor="middle" class="pie-pct">{pct:.0f}%</text>'
            f'</svg>'
            f'<div class="pie-cap">{html.escape(str(center))}</div>'
        )

    @staticmethod
    def _render_progress_widget(value, mx, label) -> str:
        """progress → bar. max 지정 시 value/max*100 정규화."""
        try:
            val = float(value)
        except (TypeError, ValueError):
            return ""
        if isinstance(mx, (int, float)) and not isinstance(mx, bool) and mx:
            pct = val / float(mx) * 100.0
        else:
            pct = val
        pct = max(0.0, min(100.0, pct))
        lab = html.escape(str(label)) if label else f"{pct:.0f}%"
        return (
            f'<div class="w-pbar"><div class="w-pbar-fill" style="width:{pct:.1f}%"></div>'
            f'<span class="w-pbar-lab">{lab}</span></div>'
        )

    @staticmethod
    def _render_badge_widget(value, label, state) -> str:
        """badge → state 아이콘 + 라벨."""
        st = state if state is not None else value
        lab = label if label is not None else (value if value is not None else st)
        st_s = str(st or "").lower()
        icon = {"alive": "🟢", "done": "✅", "dead": "🔴", "pending": "⏳",
                "error": "❌", "running": "🟢", "ok": "🟢", "warn": "⚠️"}.get(st_s, "")
        return f'<div class="w-badge w-badge-{html.escape(st_s)}">{icon} {html.escape(str(lab))}</div>'

    @staticmethod
    def _render_log_widget(value) -> str:
        """log → monospace <pre> (다행 보존, pre-wrap). 비문자열은 그대로 str()."""
        if value is None:
            return ""
        return f'<pre class="w-log">{html.escape(str(value))}</pre>'

    @staticmethod
    def _render_diff_widget(value) -> str:
        """diff → 라인별 +/- 컬러 monospace. 비문자열은 str()."""
        if value is None:
            return ""
        out = []
        for ln in str(value).split("\n"):
            if ln.startswith("+") and not ln.startswith("+++"):
                cls = "diff-add"
            elif ln.startswith("-") and not ln.startswith("---"):
                cls = "diff-del"
            elif ln.startswith("@@"):
                cls = "diff-hunk"
            else:
                cls = "diff-ctx"
            out.append(f'<span class="{cls}">{html.escape(ln)}</span>')
        return f'<pre class="w-diff">{chr(10).join(out)}</pre>'

    @classmethod
    def _render_nodegraph_svg(cls, nodes, edges, value=None) -> str:
        """graph/dag/tree → 레이어드 DAG SVG (이슈 트리 강화판). chart(시계열)와 별개.
        입력: nodes=[{id,label,status,progress?,sub?,current?}|str], edges=[{from,to}|[a,b]].
          top-level 미존재 시 value dict({nodes,edges}) 또는 JSON 문자열 fallback.
        노드: 상태 아이콘(✅🔴🟢⏳🚫⬜) + 상태색 테두리 + 연한 tint 배경 + 라벨 +
          (sub 보조줄) + (이슈별 progress 바). current=true → 굵은 강조 + 외곽 글로우.
          progress/sub 유무에 따라 노드 높이 동적(전 노드 균일). 토폴로지 레벨로 행 배치.
        빈 그래프 → 빈 문자열."""
        if not nodes and value is not None:
            v = cls._coerce_widget_value(value)
            if isinstance(v, dict):
                nodes = v.get("nodes")
                edges = edges or v.get("edges")
        if not isinstance(nodes, list) or not nodes:
            return ""

        def _norm_prog(p):
            """progress 필드 → (pct 0~100, 라벨). 파싱 실패 → None."""
            if p is None:
                return None
            mx = None
            lab = None
            raw = p
            if isinstance(p, dict):
                raw = p.get("value")
                mx = p.get("max")
                lab = p.get("label")
            try:
                val = float(raw)
            except (TypeError, ValueError):
                return None
            if isinstance(mx, (int, float)) and not isinstance(mx, bool) and mx:
                pct = val / float(mx) * 100.0
                lab = lab or f"{val:g}/{mx:g}"
            else:
                pct = val
                lab = lab or f"{pct:.0f}%"
            return (max(0.0, min(100.0, pct)), str(lab))

        # 노드 정규화 (강화 필드: progress/sub/current)
        norm = []
        ids = []
        for nd in nodes:
            if isinstance(nd, dict):
                nid = str(nd.get("id", nd.get("label", "")))
                label = str(nd.get("label", nid))
                st = str(nd.get("status", "") or "").lower()
                prog = _norm_prog(nd.get("progress"))
                sub = nd.get("sub") or nd.get("note") or ""
                sub = str(sub)
                cur = bool(nd.get("current"))
            else:
                nid = label = str(nd)
                st = ""
                prog = None
                sub = ""
                cur = False
            norm.append({"id": nid, "label": label, "status": st,
                         "prog": prog, "sub": sub, "current": cur})
            ids.append(nid)
        idset = set(ids)
        # 엣지 정규화 (from,to)
        E = []
        for e in (edges or []):
            if isinstance(e, dict):
                a, b = str(e.get("from", "")), str(e.get("to", ""))
            elif isinstance(e, (list, tuple)) and len(e) >= 2:
                a, b = str(e[0]), str(e[1])
            else:
                continue
            if a in idset and b in idset:
                E.append((a, b))
        # 레벨 산출 (parent level+1, 사이클 방어로 노드수 cap)
        level = {nid: 0 for nid in ids}
        for _ in range(len(ids)):
            changed = False
            for a, b in E:
                if level[b] < level[a] + 1:
                    level[b] = level[a] + 1
                    changed = True
            if not changed:
                break
        # 레벨별 그룹
        from collections import defaultdict
        rows = defaultdict(list)
        for nid in ids:
            rows[level[nid]].append(nid)
        maxlvl = max(level.values()) if level else 0
        maxw = max((len(r) for r in rows.values()), default=1)
        # 노드 높이 — sub/progress 유무로 동적 결정(전 노드 균일 배치)
        has_sub = any(n["sub"] for n in norm)
        has_prog = any(n["prog"] for n in norm)
        NW, GX, GY = 198.0, 26.0, 34.0
        PAD = 9.0
        LABEL_H = 19.0
        SUB_H = 15.0 if has_sub else 0.0
        PROG_H = 18.0 if has_prog else 0.0
        NH = PAD * 2 + LABEL_H + SUB_H + PROG_H
        W = max(1.0, maxw) * (NW + GX) + GX
        H = (maxlvl + 1) * (NH + GY) + GY
        pos = {}
        for lvl in range(maxlvl + 1):
            row = rows.get(lvl, [])
            roww = len(row) * (NW + GX) - GX
            x0 = (W - roww) / 2.0
            y = GY + lvl * (NH + GY)
            for i, nid in enumerate(row):
                pos[nid] = (x0 + i * (NW + GX), y)
        # 상태 → (아이콘, 테두리색, 배경 tint, 텍스트색)
        st_map = {
            "done":       ("✅", "hsl(140,55%,42%)", "hsl(140,55%,96%)", "hsl(140,45%,30%)"),
            "running":    ("🟢", "hsl(210,72%,52%)", "hsl(210,72%,96%)", "hsl(210,58%,38%)"),
            "active":     ("🟢", "hsl(210,72%,52%)", "hsl(210,72%,96%)", "hsl(210,58%,38%)"),
            "error":      ("🔴", "hsl(0,72%,55%)",   "hsl(0,72%,97%)",   "hsl(0,58%,44%)"),
            "unresolved": ("🔴", "hsl(0,72%,55%)",   "hsl(0,72%,97%)",   "hsl(0,58%,44%)"),
            "open":       ("🔴", "hsl(0,72%,55%)",   "hsl(0,72%,97%)",   "hsl(0,58%,44%)"),
            "waiting":    ("⏳", "hsl(40,85%,48%)",  "hsl(42,90%,95%)",  "hsl(38,70%,36%)"),
            "blocked":    ("🚫", "hsl(0,0%,55%)",    "hsl(0,0%,95%)",    "hsl(0,0%,38%)"),
            "pending":    ("⬜", "hsl(0,0%,62%)",    "hsl(0,0%,97%)",    "hsl(0,0%,42%)"),
        }
        DEF = ("•", "hsl(273,40%,55%)", "hsl(273,40%,97%)", "hsl(273,30%,40%)")
        parts = [f'<svg class="w-graph" viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="xMidYMid meet">']
        # 엣지 (부모 박스 하단 중앙 → 자식 상단 중앙)
        for a, b in E:
            ax, ay = pos[a]
            bx, by = pos[b]
            parts.append(
                f'<line x1="{ax + NW / 2:.1f}" y1="{ay + NH:.1f}" x2="{bx + NW / 2:.1f}" y2="{by:.1f}" '
                f'stroke="#c4c4cc" stroke-width="1.6"/>')
        # 노드
        for nd in norm:
            nid = nd["id"]
            if nid not in pos:
                continue
            x, y = pos[nid]
            icon, bcol, fill, tcol = st_map.get(nd["status"], DEF)
            sw = 3.0 if nd["current"] else 1.8
            if nd["current"]:  # 현재 노드 외곽 글로우
                parts.append(
                    f'<rect x="{x - 4:.1f}" y="{y - 4:.1f}" width="{NW + 8:.0f}" height="{NH + 8:.0f}" '
                    f'rx="10" fill="none" stroke="{bcol}" stroke-width="1.2" opacity="0.35"/>')
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{NW:.0f}" height="{NH:.0f}" rx="7" '
                f'fill="{fill}" stroke="{bcol}" stroke-width="{sw}"/>')
            tx = x + PAD
            lab_y = y + PAD + LABEL_H - 5
            lab = nd["label"]
            if len(lab) > 22:
                lab = lab[:21] + "…"
            parts.append(
                f'<text x="{tx:.1f}" y="{lab_y:.1f}" class="graph-lbl" fill="{tcol}">'
                f'{html.escape(icon)} {html.escape(lab)}</text>')
            if has_sub and nd["sub"]:
                sub = nd["sub"]
                if len(sub) > 30:
                    sub = sub[:29] + "…"
                parts.append(
                    f'<text x="{tx:.1f}" y="{lab_y + SUB_H:.1f}" class="graph-sub" '
                    f'fill="#8a8a93">{html.escape(sub)}</text>')
            if has_prog:
                pby = y + NH - PAD - 11.0
                lab_w = 40.0 if nd["prog"] else 0.0
                bar_x = x + PAD
                bar_w = NW - PAD * 2 - lab_w
                parts.append(
                    f'<rect x="{bar_x:.1f}" y="{pby:.1f}" width="{bar_w:.1f}" height="9" '
                    f'rx="4.5" fill="#e6e6ee"/>')
                if nd["prog"]:
                    pct, plab = nd["prog"]
                    parts.append(
                        f'<rect x="{bar_x:.1f}" y="{pby:.1f}" width="{bar_w * pct / 100.0:.1f}" '
                        f'height="9" rx="4.5" fill="{bcol}"/>')
                    parts.append(
                        f'<text x="{x + NW - PAD:.1f}" y="{pby + 8:.1f}" text-anchor="end" '
                        f'class="graph-prog-lab" fill="{tcol}">{html.escape(plab)}</text>')
        parts.append("</svg>")
        return "".join(parts)

    def _serve_dash_inline(self, abs_path: str, cwd: str = "", token: str = "") -> None:
        """Issue35: .dash.{json,yaml,yml} 파일을 simple HTML wrapper로 렌더.
        파싱: json은 stdlib, yaml은 PyYAML 우선 + _parse_dash_yaml fallback (제한적).
        화면: title + meta(status/pid/progress) + widgets 카드 리스트 + raw text pre.
        Issue138: cwd/token 수신 시 canonical hub 헤더 + 컨트롤바(stop/kill/refresh) +
        runner pid dead 감지(status 보정) + status≠terminal 자동 reload 추가."""
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except FileNotFoundError:
            self._send_json(404, {"error": "file not found"})
            return
        except OSError as e:
            self._send_json(500, {"error": f"read failed: {e}"})
            return

        data = None
        parse_err = None
        if abs_path.endswith(".dash.json"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                parse_err = f"JSON parse error: {e}"
        else:
            # yaml — PyYAML 우선, 없으면 minimal fallback
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(raw)
            except ImportError:
                data = self._parse_dash_yaml(raw)
            except Exception as e:
                parse_err = f"YAML parse error: {e}"

        if not isinstance(data, dict):
            data = {}

        title = data.get("title") or os.path.basename(abs_path)
        status = data.get("status") or "—"
        pid = data.get("pid")
        progress = data.get("progress")
        widgets = data.get("widgets") if isinstance(data.get("widgets"), list) else []

        esc = html.escape

        # Issue138: runner pid 생존 감지 + status 보정. 완료/종료 후 runner self-terminate
        #   하지만 마지막 위젯 값("🟢 alive")은 yaml 에 박혀 stale → 서버가 실제 생존을 판정해 보정.
        win_name = (str(data.get("window_name") or "").strip())
        status_l = str(status).lower()
        terminal = status_l in ("done", "stopped", "stale", "halted")
        runner_alive = bool(pid) and _pid_alive(int(pid)) if str(pid).lstrip("-").isdigit() else False
        runner_dead = bool(pid) and not runner_alive
        # 표시 status: terminal 아니어도 runner dead 면 'stopped' 로 보정 표기
        eff_status = status
        if runner_dead and not terminal:
            eff_status = "stopped (runner dead)"
            terminal = True
        widget_html_parts = []
        for i, w in enumerate(widgets):
            if not isinstance(w, dict):
                widget_html_parts.append(
                    f'<div class="w"><div class="w-meta">#{i}</div><pre>{esc(str(w))}</pre></div>'
                )
                continue
            wtype = w.get("type", "?")
            wtitle = w.get("title") or w.get("label") or w.get("id") or ""
            value = w.get("value")
            # text/log/timer 등은 핵심 필드가 content — value 비면 content 로 보강 (SSOT ### type).
            if value is None:
                value = w.get("content")
            value_html = ""
            # type별 전용 렌더 — dynamic_eval 결과(value 에 실린 JSON 문자열)를 사람이 보기 좋은
            #   HTML 로 변환. 실패 시 아래 일반 value 처리(JSON pre)로 자연 fallback.
            wtype_l = str(wtype).lower()
            if wtype_l in ("chart", "sparkline", "line"):
                # 숫자 시계열 → inline SVG 라인+area. value: [n,...] | "n,n,n" | {points,ymax,ymin,unit,label}
                value_html = self._render_chart_svg(value) or ""
            elif wtype_l in ("graph", "dag", "tree"):
                # 노드 그래프(DAG) — chart 와 별개. nodes/edges (top-level 또는 value dict).
                value_html = self._render_nodegraph_svg(
                    w.get("nodes"), w.get("edges"), value) or ""
            elif wtype_l in ("pie", "donut", "gauge"):
                # 진행률 도넛 (0 기준 고정). value: number 0~100 | {value, max?, label?, unit?}
                value_html = self._render_pie_svg(value) or ""
            elif wtype_l == "checklist":
                value_html = self._render_checklist(value, w.get("items"))
            elif wtype_l == "table":
                value_html = self._render_table_widget(value, w.get("columns"), w.get("rows"))
            elif wtype_l == "progress":
                value_html = self._render_progress_widget(value, w.get("max"), w.get("label"))
            elif wtype_l == "badge":
                value_html = self._render_badge_widget(value, w.get("label"), w.get("state"))
            elif wtype_l == "log":
                value_html = self._render_log_widget(value)
            elif wtype_l == "diff":
                value_html = self._render_diff_widget(value)
            if not value_html:
                if isinstance(value, (str, int, float, bool)):
                    value_html = f'<div class="w-value">{esc(str(value))}</div>'
                elif value is not None:
                    try:
                        value_html = f'<pre class="w-json">{esc(json.dumps(value, ensure_ascii=False, indent=2))}</pre>'
                    except (TypeError, ValueError):
                        value_html = f'<pre class="w-json">{esc(str(value))}</pre>'
            # width 힌트 → grid-column span. "full"=전폭, 정수 N=N셀 span, 기본=1셀.
            span_style = ""
            wwidth = w.get("width")
            if isinstance(wwidth, str) and wwidth.lower() == "full":
                span_style = ' style="grid-column: 1 / -1"'
            elif isinstance(wwidth, (int, float)) and not isinstance(wwidth, bool) and int(wwidth) > 1:
                span_style = f' style="grid-column: span {int(wwidth)}"'
            elif isinstance(wwidth, str) and wwidth.strip().isdigit() and int(wwidth) > 1:
                span_style = f' style="grid-column: span {int(wwidth)}"'
            widget_html_parts.append(
                f'<div class="w"{span_style}><div class="w-meta"><span class="w-type">{esc(wtype)}</span>'
                f' <span class="w-title">{esc(str(wtitle))}</span></div>{value_html}</div>'
            )
        widgets_html = "\n".join(widget_html_parts) or '<em>(no widgets)</em>'

        pid_cell = (esc(str(pid)) if pid is not None else "—")
        if runner_dead:
            pid_cell += ' <span class="rdead">⚠ 종료됨</span>'
        elif runner_alive:
            pid_cell += ' <span class="ralive">🟢 alive</span>'
        meta_rows = [
            f'<tr><th>status</th><td>{esc(str(eff_status))}</td></tr>',
            f'<tr><th>pid</th><td>{pid_cell}</td></tr>',
            f'<tr><th>progress</th><td>{esc(str(progress)) if progress is not None else "—"}</td></tr>',
            f'<tr><th>path</th><td><code>{esc(abs_path)}</code></td></tr>',
        ]
        try:
            mt = os.path.getmtime(abs_path)
            mt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt))
            meta_rows.append(f'<tr><th>mtime</th><td>{esc(mt_str)}</td></tr>')
        except OSError:
            pass

        progress_bar = ""
        if isinstance(progress, (int, float)):
            pct = max(0, min(100, int(progress)))
            progress_bar = (
                f'<div class="pbar"><div class="pbar-fill" style="width:{pct}%"></div>'
                f'<span class="pbar-label">{pct}%</span></div>'
            )

        err_banner = f'<div class="err">⚠ {esc(parse_err)}</div>' if parse_err else ""

        # ─── Issue138: canonical hub 헤더 + 컨트롤바 + JS ───
        proj_label = esc(os.path.basename(cwd.rstrip("/")) or "프로젝트") if cwd else "프로젝트"
        cwd_js = json.dumps(cwd or "")
        token_js = json.dumps(token or "")
        win_js = json.dumps(win_name or "")
        pid_js = json.dumps(int(pid)) if str(pid).lstrip("-").isdigit() else "null"

        onclick_open = (
            'event.preventDefault();'
            'fetch("/open-project",{method:"POST",headers:{"Content-Type":"application/json"},'
            'body:JSON.stringify({cwd:' + cwd_js + '})})'
            '.then(function(r){return r.json();})'
            '.then(function(j){if(j&&j.uri){window.location.href=j.uri;}else if(j&&j.error)alert("VSCode 열기 실패: "+j.error);})'
            '.catch(function(){alert("hub 서버 미응답 — VSCode 열기 실패");});'
        )
        # Issue214: 헤더 액션 개편 — (1) 🔗 문서 링크 복사 버튼 추가(쉘 iframe 내에선
        #   주소창이 /hub-shell 만 보여 문서 URL 직접 복사 불가) (2) 닫기를 ✕ 아이콘화 +
        #   맨 오른쪽 끝 분리(margin) (3) 전 액션 title 툴팁 부착.
        #   Issue213: hub-link target="_blank" 제거 — 새 OS 창(중복) 차단, 쉘 iframe 안 in-place 합류.
        copy_onclick = (
            "(function(b){var u=location.href.replace(/[?&]_shell=1$/,'');"
            "function ok(){var o=b.textContent;b.textContent='✓';setTimeout(function(){b.textContent=o;},1200);}"
            "function fb(){try{var ta=document.createElement('textarea');ta.value=u;"
            "ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);"
            "ta.focus();ta.select();var r=document.execCommand('copy');document.body.removeChild(ta);"
            "if(r){ok();}else{window.prompt('문서 링크 복사',u);}}"
            "catch(e){window.prompt('문서 링크 복사',u);}}"
            "if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(u).then(ok).catch(fb);}else{fb();}})(this)"
        )
        header_html = (
            '<header class="dash-hdr"><h1>' + esc(title) + '</h1>'
            '<nav class="hdr-actions">'
            '<a class="proj-badge" href="#" title="' + _editor_app_name() + ' 로 ' + proj_label + ' 프로젝트 열기" onclick=\'' + onclick_open + '\'>📁 ' + proj_label + '</a>'  # Issue327
            '<a class="sess-link" href="/hub" title="활성 세션 목록 보기 (hub)">🛰 활성 세션</a>'
            '<button type="button" class="copy-link" title="이 문서 링크 복사" onclick="' + copy_onclick + '">🔗</button>'
            '<a class="hub-link" href="/hub" title="통합 Hub 대시보드로 이동">🗂 Hub</a>'
            '<button type="button" class="close-btn" title="이 문서 탭 닫기" onclick="window.close()">✕</button>'
            '</nav></header>'
        )

        ctrl_html = ""
        dash_script = ""
        if cwd and token and str(pid).lstrip("-").isdigit():
            btns = []
            if runner_alive:
                btns.append('<button class="dctl refresh" onclick="dashRefresh(this)">🔄 새로고침</button>')
            if runner_alive and not terminal:
                btns.append('<button class="dctl stop" onclick="dashStop(this)">⏹ 정지 (stop)</button>')
            if win_name:
                if terminal or runner_dead:
                    btns.append('<button class="dctl kill done" onclick="dashKill(this)">✕ 종료 (window 정리)</button>')
                else:
                    btns.append('<button class="dctl kill" onclick="dashKill(this)">✕ 강제 종료</button>')
            note = '<span class="ctl-note">⚠ runner 종료됨 — 잔존 window 정리만 가능</span>' if runner_dead else ''
            if btns or note:
                ctrl_html = '<div class="dctl-bar">' + ''.join(btns) + note + '</div>'

            iv = data.get("interval")
            try:
                iv = max(2, min(60, int(iv)))
            except (TypeError, ValueError):
                iv = 5
            auto_reload = "" if terminal else ("setTimeout(function(){location.reload();}," + str(iv) + "000);")
            dash_script = (
                "<script>\n"
                "var DCWD=" + cwd_js + ",DTOKEN=" + token_js + ",DPID=" + pid_js + ",DWIN=" + win_js + ";\n"
                "function _ctl(body,btn,okmsg){var o=btn.textContent;btn.disabled=true;btn.textContent='...';"
                "return fetch('/control?cwd='+encodeURIComponent(DCWD)+'&token='+encodeURIComponent(DTOKEN),"
                "{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})"
                ".then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})"
                ".then(function(res){if(res.ok){btn.textContent='✅ '+(okmsg||res.j.status||'ok');"
                "setTimeout(function(){location.reload();},700);}else{btn.disabled=false;btn.textContent='❌ '+(res.j.error||'err');}})"
                ".catch(function(e){btn.disabled=false;btn.textContent='❌ '+e.message;});}\n"
                "function dashStop(b){if(!confirm('runner pid='+DPID+' 정지? (graceful SIGTERM)'))return;_ctl({action:'stop',pid:DPID},b,'정지됨');}\n"
                "function dashRefresh(b){_ctl({action:'refresh',pid:DPID},b,'갱신');}\n"
                "function dashKill(b){if(!confirm('tmux window pm:'+DWIN+' 종료? (runner+worker+pane 동반)'))return;_ctl({action:'kill_pane',pid:DPID,window_name:DWIN},b,'종료됨');}\n"
                + auto_reload +
                "\n</script>"
            )

        page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<link rel="icon" href="/fpm-icon.png">
<title>{esc(title)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1100px; margin: 1rem auto; padding: 0 1rem; color: #222; }}
  h1 {{ margin: 0 0 0.5rem; font-size: 1.4rem; }}
  .banner {{ color: #888; font-size: 0.85rem; margin-bottom: 1rem; }}
  table.meta {{ border-collapse: collapse; margin-bottom: 1rem; font-size: 0.9rem; }}
  table.meta th, table.meta td {{ border: 1px solid #ddd; padding: 4px 10px; text-align: left; }}
  table.meta th {{ background: #f5f5f5; min-width: 80px; }}
  .pbar {{ position: relative; background: #eee; border-radius: 4px; height: 22px; margin-bottom: 1rem; overflow: hidden; }}
  .pbar-fill {{ background: linear-gradient(90deg, #4a9eff, #2a6); height: 100%; transition: width 0.3s; }}
  .pbar-label {{ position: absolute; top: 0; left: 50%; transform: translateX(-50%); line-height: 22px; font-size: 0.85rem; font-weight: 600; color: #222; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0.8rem; margin-bottom: 1.5rem; }}
  .w {{ border: 1px solid #ddd; border-radius: 6px; padding: 0.7rem; background: #fafafa; }}
  .w-meta {{ font-size: 0.8rem; color: #666; margin-bottom: 0.3rem; }}
  .w-type {{ background: #2a6; color: white; padding: 1px 6px; border-radius: 3px; font-weight: 600; }}
  .w-title {{ font-weight: 600; color: #222; margin-left: 0.4rem; }}
  .w-value {{ font-size: 1.1rem; font-weight: 600; }}
  .w-json {{ background: #fff; padding: 0.4rem; border-radius: 3px; font-size: 0.8rem; max-height: 200px; overflow: auto; }}
  .w-chart {{ width: 100%; height: 90px; display: block; background: #fff; border-radius: 4px; }}
  .chart-cur {{ font-size: 1.05rem; font-weight: 700; color: hsl(273,60%,45%); margin-top: 0.2rem; }}
  .chart-range {{ font-size: 0.75rem; font-weight: 400; color: #999; }}
  .chart-cap {{ font-size: 0.78rem; color: #777; }}
  .w-pie {{ width: 100%; max-width: 150px; height: 120px; display: block; margin: 0.2rem auto 0; }}
  .pie-pct {{ font-size: 26px; font-weight: 700; fill: hsl(273,60%,45%); }}
  .pie-cap {{ text-align: center; font-size: 0.82rem; color: #777; }}
  @media (prefers-color-scheme: dark) {{ .pie-pct {{ fill: hsl(273,70%,68%); }} }}
  .w-checklist {{ list-style: none; padding: 0; margin: 0.2rem 0 0; }}
  .w-checklist li {{ padding: 0.2rem 0; font-size: 0.95rem; }}
  .w-checklist .ck-done {{ color: #2a7; }}
  .w-checklist .ck-todo {{ color: #999; }}
  .w-table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; margin-top: 0.2rem; }}
  .w-table th, .w-table td {{ border: 1px solid #e0e0e0; padding: 3px 8px; text-align: left; }}
  .w-table th {{ background: #f0f0f0; font-weight: 600; }}
  .w-table tr:nth-child(even) td {{ background: #fafafa; }}
  .w-pbar {{ position: relative; background: #eee; border-radius: 4px; height: 22px; overflow: hidden; margin-top: 0.2rem; }}
  .w-pbar-fill {{ background: linear-gradient(90deg, hsl(273,70%,60%), hsl(273,60%,45%)); height: 100%; transition: width 0.3s; }}
  .w-pbar-lab {{ position: absolute; top: 0; left: 50%; transform: translateX(-50%); line-height: 22px; font-size: 0.82rem; font-weight: 600; color: #222; }}
  .w-badge {{ display: inline-block; padding: 0.2rem 0.7rem; border-radius: 12px; font-weight: 600; font-size: 0.95rem; background: #eee; margin-top: 0.2rem; }}
  .w-badge-alive, .w-badge-running, .w-badge-ok {{ background: #e3f7ea; color: #1a7; }}
  .w-badge-done {{ background: #e3eefe; color: #36c; }}
  .w-badge-dead, .w-badge-error {{ background: #fde3e3; color: #c33; }}
  .w-badge-pending {{ background: #fff4e0; color: #b80; }}
  .w-badge-warn {{ background: #fff4e0; color: #b80; }}
  .w-graph {{ width: 100%; max-height: 560px; display: block; margin-top: 0.2rem; }}
  .graph-lbl {{ font-size: 12.5px; font-weight: 700; }}
  .graph-sub {{ font-size: 10.5px; font-weight: 400; }}
  .graph-prog-lab {{ font-size: 10px; font-weight: 700; }}
  .w-log {{ background: #1e1e22; color: #d6d6d6; padding: 0.5rem 0.7rem; border-radius: 4px; font-family: ui-monospace, Menlo, monospace; font-size: 0.78rem; line-height: 1.45; white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; margin: 0.2rem 0 0; }}
  .w-diff {{ background: #1e1e22; padding: 0.5rem 0.7rem; border-radius: 4px; font-family: ui-monospace, Menlo, monospace; font-size: 0.78rem; line-height: 1.45; white-space: pre-wrap; max-height: 260px; overflow: auto; margin: 0.2rem 0 0; }}
  .w-diff span {{ display: block; }}
  .w-diff .diff-add {{ color: #6ad46a; }}
  .w-diff .diff-del {{ color: #f08a8a; }}
  .w-diff .diff-hunk {{ color: #6ab0f0; }}
  .w-diff .diff-ctx {{ color: #b0b0b0; }}
  details {{ margin-top: 1rem; }}
  details > summary {{ cursor: pointer; color: #555; font-size: 0.9rem; }}
  pre.raw {{ background: #f5f5f5; padding: 0.8rem; border-radius: 4px; overflow: auto; max-height: 400px; font-size: 0.8rem; }}
  .err {{ background: #fee; border: 1px solid #c33; color: #a22; padding: 0.5rem 0.8rem; border-radius: 4px; margin-bottom: 1rem; }}
  /* Issue138: canonical hub 헤더 — /view·/hub 와 디자인 통일 */
  body {{ padding-top: 0 !important; }}
  .dash-hdr {{ position: sticky; top: 0; z-index: 100; display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.8rem 1.2rem; margin: 0 -1rem 1rem; background: hsl(273,60%,45%); color: #fff; }}
  .dash-hdr h1 {{ margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; color: #fff; }}
  .hdr-actions {{ display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }}
  .hdr-actions .proj-badge, .hdr-actions .sess-link, .hdr-actions .hub-link, .hdr-actions button {{ display: inline-flex; align-items: center; line-height: 1; color: #fff; text-decoration: none; cursor: pointer; white-space: nowrap; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.35); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }}
  .hdr-actions .proj-badge:hover, .hdr-actions .sess-link:hover, .hdr-actions .hub-link:hover, .hdr-actions button:hover {{ background: rgba(255,255,255,0.28); text-decoration: underline; }}
  /* Issue214: 🔗 복사·✕ 닫기 아이콘 버튼 — 정사각 정렬 + 닫기는 맨 오른쪽 분리 */
  .hdr-actions .copy-link, .hdr-actions .close-btn {{ justify-content: center; padding: 0.2rem 0.5rem; }}
  .hdr-actions .close-btn {{ margin-left: 0.6rem; }}
  .hdr-actions .close-btn:hover {{ background: rgba(255,90,90,0.45); border-color: #fff; text-decoration: none; }}
  /* Issue138: 컨트롤바 */
  .dctl-bar {{ display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; padding: 0.6rem 0.8rem; background: #f5f3fa; border: 1px solid #e0d8f0; border-radius: 8px; }}
  .dctl {{ font-size: 0.88rem; padding: 0.35rem 0.8rem; border-radius: 6px; cursor: pointer; border: 1px solid #ccc; background: #fff; font-weight: 600; }}
  .dctl.refresh {{ border-color: #6ab0f0; color: #2a6; }}
  .dctl.stop {{ border-color: #e0a000; color: #b80; }}
  .dctl.kill {{ border-color: #e08080; color: #c33; }}
  .dctl.kill.done {{ background: hsl(273,60%,45%); color: #fff; border-color: hsl(273,60%,40%); }}
  .dctl:hover {{ filter: brightness(0.96); }}
  .ctl-note {{ color: #b80; font-size: 0.85rem; }}
  .rdead {{ color: #c33; font-weight: 600; font-size: 0.85rem; }}
  .ralive {{ color: #1a7; font-weight: 600; font-size: 0.85rem; }}
</style>
</head>
<body>
{header_html}
{err_banner}
{ctrl_html}
{progress_bar}
<table class="meta">{''.join(meta_rows)}</table>
<div class="grid">{widgets_html}</div>
<details><summary>Raw source ({esc(os.path.basename(abs_path))})</summary>
<pre class="raw">{esc(raw)}</pre>
</details>
{dash_script}
</body>
</html>"""
        body = page.encode("utf-8")
        # Issue216: dash 헤더 닫기(✕)도 쉘 탭을 닫도록 window.close override 쉼 주입.
        body = _inject_before_body_end(body, CLOSE_SHIM)
        # Issue220: dash 헤더 🗂 Hub 링크 클릭 → 쉘 home 탭 전환.
        body = _inject_before_body_end(body, HUB_LINK_SHIM)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ─────────────── Issue17 Phase 1: 세션 중심 endpoint ───────────────

    def _handle_session_register(self, parsed):
        """POST /session/register?cwd=<abs> body={sid, capabilities?} → {url, token, cwd_hash}.
        기존 /register token 재사용 (해당 cwd 미등록 시 자동 등록)."""
        cwd = get_cwd_param(parsed)
        if not cwd or not os.path.isabs(cwd):
            self._send_json(400, {"error": "missing or non-absolute cwd"})
            return
        body, err = self._read_json_body()
        if err:
            self._send_json(400, {"error": err})
            return
        sid = str(body.get("sid", "")).strip()
        if not sid:
            self._send_json(400, {"error": "missing sid"})
            return
        # sid 안전화: 영문/숫자/하이픈/언더스코어만
        safe = "".join(c for c in sid if c.isalnum() or c in "-_")
        if not safe or safe != sid:
            self._send_json(400, {"error": "invalid sid (alphanumeric/-/_ only)"})
            return
        caps = body.get("capabilities") if isinstance(body.get("capabilities"), dict) else {}
        # Issue98: content_type="live" 일반 claude 세션 등록 지원.
        #   - 기본 "response" → 기존 htm Mode B/C 부트스트랩 동작 불변.
        #   - "live" → 활성 세션 카드 노출. pid 생존(_pid_alive) 또는 heartbeat
        #     TTL(LIVE_TTL) 로 liveness 판정 (_collect_live_sessions live 분기).
        reg_ctype = str(body.get("content_type", "response")).strip() or "response"
        if reg_ctype not in ("response", "live"):
            self._send_json(400, {"error": f"unsupported content_type for register: {reg_ctype}"})
            return
        live_pid = body.get("pid")
        try:
            live_pid = int(live_pid) if live_pid is not None else None
        except (TypeError, ValueError):
            live_pid = None
        # Issue99: live 등록은 pid 필수 — pid 가 세션 식별(dedup)·liveness 권위 신호.
        #   pid 없으면 식별 불가 중복 카드·좀비 잔존이 발생 → 거부.
        if reg_ctype == "live" and live_pid is None:
            self._send_json(400, {"error": "live registration requires integer pid"})
            return
        live_label = str(body.get("label", "")).strip() or None  # tmux window/topic 등 카드 제목
        # Issue282: sid-sticky — 세션 중 cd 로 cwd 가 드리프트해도 최초 등록 프로젝트에
        #   고정. hook 이 세션 현재 cwd 를 보내므로 cd 후 heartbeat 가 다른 cwd_hash 로
        #   재등록돼 카드가 2장으로 갈라졌다. 동일 sid 가 이미 다른 hash 아래 존재하면
        #   그 프로젝트의 cwd 로 치환해 기존 (h, sid) key 를 재사용한다
        #   (sid 는 uuid4 — 프로젝트 간 우연 충돌 없음. projects[h] 덮어쓰기도 방지).
        if reg_ctype == "live":
            h_new = cwd_hash(cwd)
            h_prev = None
            with sessions_lock:
                for (h_old, s_old) in sessions.keys():
                    if s_old == sid and h_old != h_new:
                        h_prev = h_old
                        break
            if h_prev:
                with projects_lock:
                    p_old = projects.get(h_prev)
                prev_cwd = (p_old or {}).get("cwd", "")
                if prev_cwd:
                    log(f"POST /session/register — sid-sticky remap (Issue282): "
                        f"sid={sid} cwd {cwd} → {prev_cwd}")
                    cwd = prev_cwd
        h = cwd_hash(cwd)
        meta = project_meta(cwd)
        # 프로젝트 자동 등록 (기존 /register 동일 로직)
        inbox = f"{INBOX_ROOT}/{h}"
        os.makedirs(inbox, exist_ok=True)
        new_proj = False
        with projects_lock:
            existing = projects.get(h)
            if existing and existing.get("cwd") == cwd:
                token = existing["token"]
            else:
                token = uuid.uuid4().hex
                projects[h] = {
                    "cwd": cwd,
                    "token": token,
                    "name": meta["name"],
                    "color": meta["color"],
                    "registered_at": time.time(),
                }
                new_proj = True
        if new_proj:
            persist_tokens()
        # 세션 entry 보장
        now = time.time()
        with sessions_lock:
            entry = sessions.get((h, sid))
            if not entry:
                entry = {
                    "mode": "A",
                    "content_type": reg_ctype,
                    "content": "",
                    "capabilities": caps,
                    "created": now,
                    "updated": now,
                }
                sessions[(h, sid)] = entry
            else:
                # Issue336: 교체가 아니라 **병합**. 통째 교체하면 SessionStart 훅이 1회만
                #   싣는 신호(capabilities.editor="zed")가 이후 heartbeat(topic·model 훅,
                #   editor 미포함)에서 지워져 origin 이 terminal 로 강등된다.
                #   매 등록에서 재전송되는 source·kind·model·entrypoint 는 병합해도 최신값이 이긴다.
                merged = dict(entry.get("capabilities") or {})
                merged.update(caps or {})
                entry["capabilities"] = merged
                entry["updated"] = now  # heartbeat (live TTL 갱신)
                # Issue98: 명시 "live" 재등록만 content_type 승격 — dashboard 등 기존
                #   세션 타입은 보존 (response 기본값이 덮어쓰지 않도록).
                if reg_ctype == "live":
                    entry["content_type"] = "live"
            # Issue98: live 메타 기록 (pid·label) — register/heartbeat 마다 갱신.
            need_gc_meta = False
            if reg_ctype == "live":
                entry["live_pid"] = live_pid
                entry["live_label"] = live_label
                # Issue280: 컨테이너 메타는 pid 당 1회 캡처 (heartbeat 마다 ps/tmux 재실행 방지)
                gm = entry.get("gc_meta")
                need_gc_meta = not gm or gm.get("for_pid") != live_pid
        if need_gc_meta:
            # Issue280: subprocess 호출은 sessions_lock 밖에서 — 캡처 후 재획득 저장
            gm = _capture_gc_meta(live_pid)
            with sessions_lock:
                e2 = sessions.get((h, sid))
                if e2 is not None:
                    e2["gc_meta"] = gm
        persist_sessions()
        url = f"http://{HOST}:{PORT}/s/{h}/{sid}?token={token}"
        # Issue21: SSE subscriber 수 회신 → 클라이언트 hook 이 first_open 정확 판정
        # (marker 파일만으로는 탭이 사용자에 의해 닫힌 경우를 못 잡음)
        with sse_lock:
            subscribers = len(sse_subscribers.get((h, sid), []))
        log(f"POST /session/register — hash={h} sid={sid} subs={subscribers}")
        self._send_json(200, {
            "url": url,
            "token": token,
            "cwd_hash": h,
            "sid": sid,
            "mode": entry["mode"],
            "subscribers": subscribers,
        })

    def _handle_session_update(self, parsed):
        """POST /session/update?cwd=&sid=&token= body={content_type, content}.
        mode 판정 → sessions table 갱신 → 해당 (cwd_hash, sid) 채널 sse_broadcast."""
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        qs = parse_qs(parsed.query)
        sid = (qs.get("sid") or [""])[0]
        if not sid:
            self._send_json(400, {"error": "missing sid"})
            return
        body, err = self._read_json_body(max_bytes=4 * 1024 * 1024)  # 4 MiB
        if err:
            self._send_json(400, {"error": err})
            return
        ctype = body.get("content_type", "response")
        if ctype not in ("response", "form", "dashboard"):
            self._send_json(400, {"error": f"unknown content_type: {ctype}"})
            return
        content = body.get("content", "")
        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)
            except Exception:
                self._send_json(400, {"error": "content not serializable"})
                return
        # Issue24 Phase 2: dashboard schema 검증 (?lenient=1 로 우회)
        if ctype == "dashboard":
            lenient = (qs.get("lenient") or ["0"])[0] in ("1", "true", "yes")
            if not lenient:
                verr = validate_dashboard(content)
                if verr:
                    self._send_json(400, {"error": verr})
                    return
        mode = determine_mode(ctype)
        h = cwd_hash(cwd)
        now = time.time()
        with sessions_lock:
            entry = sessions.get((h, sid))
            if not entry:
                entry = {
                    "mode": mode,
                    "content_type": ctype,
                    "content": content,
                    "capabilities": {},
                    "created": now,
                    "updated": now,
                }
                sessions[(h, sid)] = entry
            else:
                entry["mode"] = mode
                entry["content_type"] = ctype
                entry["content"] = content
                entry["updated"] = now
        persist_sessions()
        clients = sse_broadcast(h, "session_update", {"sid": sid, "mode": mode, "content_type": ctype}, sid=sid)
        log(f"POST /session/update — hash={h} sid={sid} mode={mode} ctype={ctype} clients={clients}")
        self._send_json(200, {"ok": True, "mode": mode, "clients": clients})

    def _dash_entry_for_sid(self, cwd_h, cwd, sid):
        """Issue229: DASH_REGISTRY 에 등록된 dash 중 (cwd_h, sid) 매칭 파일을 풀 파싱해
        sessions 엔트리 형태로 합성 반환. dashboard runner 는 dash.yaml 파일만 갱신하고
        /session/register 로 sessions dict 에 push 하지 않으므로(파일 기반·HTTP 없음),
        /s/{sid}/data 가 sessions 에서 못 찾는다. registry(디스크)에서 직접 읽어 메운다.
        반환: sessions entry 호환 dict(content_type=dashboard, content=full dash JSON) 또는 None."""
        if not sid:
            return None
        try:
            with registry_lock:
                dash_entries = load_registry(DASH_REGISTRY)
        except Exception:
            return None
        for e in dash_entries:
            if e.get("sid", "") != sid:
                continue
            ecwd = os.path.normpath(e.get("cwd", "") or "")
            if ecwd and cwd_hash(ecwd) != cwd_h:
                continue
            path = e.get("path", "")
            if not path:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
                if path.endswith(".dash.json"):
                    data = json.loads(raw)
                else:
                    try:
                        import yaml  # type: ignore
                        data = yaml.safe_load(raw)
                    except ImportError:
                        data = self._parse_dash_yaml(raw)
                if not isinstance(data, dict):
                    return None
                st = os.stat(path)
                return {
                    "content_type": "dashboard",
                    # SPA reload() 는 mode 로 렌더 분기 — dashboard 는 "C"(renderDashboard).
                    #   "A" 면 raw content 를 그대로 innerHTML 덤프(JSON 문자열 노출). (Issue229)
                    "content": json.dumps(data, ensure_ascii=False),
                    "mode": "C",
                    "updated": st.st_mtime,
                    "capabilities": {},
                }
            except Exception as ex:
                log(f"_dash_entry_for_sid fail {path}: {ex}")
                return None
        return None

    def _handle_session_get(self, parsed):
        """GET /s/{cwd_hash}/{sid}?token=  → SPA shell HTML
        GET /s/{cwd_hash}/{sid}/data?token= → session JSON
        """
        path = parsed.path
        # path 패턴 파싱
        parts = path.strip("/").split("/")
        # ["s", cwd_hash, sid] 또는 ["s", cwd_hash, sid, "data"]
        if len(parts) < 3 or parts[0] != "s":
            self._send_json(404, {"error": "not found"})
            return
        cwd_h = parts[1]
        sid_raw = parts[2]
        # sid 안전화
        sid = "".join(c for c in sid_raw if c.isalnum() or c in "-_")
        if not sid or sid != sid_raw:
            self._send_json(400, {"error": "invalid sid"})
            return
        is_data = len(parts) >= 4 and parts[3] == "data"
        # Issue353_2 M2-b: /s/{h}/{sid}/mail?since= — 메일박스 pull
        is_mail = len(parts) >= 4 and parts[3] == "mail"
        # Issue353_2 M2-c: /s/{h}/{sid}/live — 라이브 셸(md-first 셸 재사용)
        is_live = len(parts) >= 4 and parts[3] == "live"
        # cwd_hash 로 cwd 회수
        with projects_lock:
            p = projects.get(cwd_h)
        if not p:
            self._send_json(404, {"error": "unknown cwd_hash"})
            return
        cwd = p.get("cwd", "")
        expected = p.get("token", "")
        token = get_token_param(parsed)
        if not token or not hmac.compare_digest(expected, token):
            self._send_json(401, {"error": "invalid token"})
            return
        if is_mail:
            self._handle_session_mail(parsed, cwd_h, sid, cwd)
            return
        if is_live:
            self._handle_session_live(parsed, cwd_h, sid, cwd, token, p)
            return
        if is_data:
            with sessions_lock:
                entry = sessions.get((cwd_h, sid))
            if not entry:
                # Issue229: 디스크 dashboard(runner 가 파일만 갱신, sessions 미push)는
                #   registry 에서 sid 매칭 dash 파일을 직접 읽어 serve (SPA "대기 중" 해소).
                entry = self._dash_entry_for_sid(cwd_h, cwd, sid)
            if not entry:
                self._send_json(404, {"error": "session not registered"})
                return
            content_out = entry.get("content", "")
            # Issue63: dashboard detail — runner pid 가 죽었는데 status 가 terminal 이 아니면
            #   마지막 stale 데이터(running)를 그대로 렌더. served status 를 stopped 로 보정.
            if entry.get("content_type") == "dashboard":
                d_pid, d_status = _dash_runner_state(entry)
                if d_pid is not None and not _pid_alive(d_pid) \
                        and d_status not in ("done", "stopped"):
                    try:
                        d = json.loads(content_out)
                        d["status"] = "stopped"
                        d["_runner_dead"] = True
                        content_out = json.dumps(d, ensure_ascii=False)
                    except Exception:
                        pass
            ctype_out = entry.get("content_type", "response")
            mode_out = entry.get("mode", "A")
            # Issue219: 푸시된 렌더 content 가 비어 있으면(터미널 CLI 세션 등 — content_type
            #   "live") JSONL 대화 transcript 로 fallback. '대화 내용 보기' 충족.
            if not content_out:
                tr = _session_transcript_html(cwd, sid)
                if tr:
                    content_out = tr
                    ctype_out = "response"
                    mode_out = "A"
            gm = entry.get("gc_meta") or {}
            self._send_json(200, {
                "content_type": ctype_out,
                "content": content_out,
                "mode": mode_out,
                "updated": entry.get("updated", 0),
                "capabilities": entry.get("capabilities", {}),
                # Issue280: GC 버튼 활성 판정 — kill 대상 정보 보유 여부
                "can_gc": bool(entry.get("live_pid") or gm.get("shell_pid")
                               or gm.get("tmux_pane")),
            })
            return
        # SPA shell HTML serve
        try:
            import urllib.parse as _u
            cwd_q = _u.quote(cwd)
        except Exception:
            cwd_q = ""
        name = p.get("name", "session")
        color = p.get("color", "hsl(220,60%,45%)")
        title = f"{name} — session {sid}"
        html = (SESSION_SHELL_HTML
                .replace("{TITLE}", title)
                .replace("{NAME}", name)
                .replace("{COLOR}", color)
                .replace("{CWD_HASH}", cwd_h)
                .replace("{SID}", sid)
                .replace("{TOKEN}", token)
                .replace("{CWD_Q}", cwd_q)
                .replace("{PREVIEW}", "0"))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _handle_live_url(self, parsed):
        """Issue356_1: `GET /live-url?cwd=&sid=` → 라이브 뷰 URL + 표시 모드.

        훅(prj3#Issue341)이 턴 시작에 라이브 뷰를 열려면 `cwd_hash`·token 이 필요한데,
        그것을 **훅이 `tokens.json` 을 직접 파싱해 얻게 하면 상태 파일 포맷에 결합**된다.
        포맷이 바뀌는 순간 훅이 조용히 깨지므로, 서버가 조립해 돌려준다.

        localhost trust(다른 로컬 endpoint 와 동일 등급) — 반환하는 token 은 그 프로젝트가
        이미 `/register` 로 발급받은 값이고, 이 응답이 새 권한을 만들지 않는다.

        응답: `{url, display, ready}` — `ready` 는 transcript 가 실제로 존재하는가다.
        훅은 `ready:false` 면 열지 않고 조용히 기존 경로로 간다(빈 뷰를 띄우지 않는다).
        """
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        qs = parse_qs(parsed.query)
        cwd = (qs.get("cwd") or [""])[0]
        sid = (qs.get("sid") or [""])[0]
        if not cwd or not sid:
            self._send_json(400, {"error": "cwd and sid required"})
            return
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", sid):
            self._send_json(400, {"error": "invalid sid"})
            return
        cwd = os.path.abspath(os.path.expanduser(cwd))
        h = cwd_hash(cwd)
        with projects_lock:
            p = projects.get(h)
        if not p:
            self._send_json(404, {"error": "project not registered"})
            return
        token = p.get("token", "")
        if not token:
            self._send_json(404, {"error": "project has no token"})
            return
        setting = _load_hub_setting()
        display, warn = render_gate.normalize_display(setting.get("render_display", "auto"))
        if warn:
            log(f"GET /live-url — {warn}", "WARNING")
        # 강등이 보고된 세션은 훅에게 archive 를 돌려준다(다음 턴부터 문서 경로)
        if display != "archive" and self._live_degraded(h, sid):
            display = "archive"
        ready = bool(_resolve_session_jsonl(cwd, sid))
        self._send_json(200, {
            "url": f"http://{HOST}:{PORT}/s/{h}/{sid}/live?token={token}",
            "display": display,
            "ready": ready,
        })

    # Issue356_1: 브라우저가 보고한 열화 강등 세션 (프로세스 메모리 — 재기동 시 초기화)
    _live_degraded_set = set()
    _live_degraded_lock = threading.Lock()

    def _live_degraded(self, cwd_h: str, sid: str) -> bool:
        with Handler._live_degraded_lock:
            return (cwd_h, sid) in Handler._live_degraded_set

    def _handle_session_degrade(self, parsed, cwd_h: str, sid: str):
        """Issue356_1: `POST /s/{h}/{sid}/degrade` — 브라우저의 열화 강등 통보.

        라이브 탭이 스스로 물러났다는 사실을 서버가 알아야 **다음 턴에 훅이 또
        라이브 뷰를 열지 않는다**. 모르면 매 턴 같은 열화를 반복한다.
        상태는 메모리에만 둔다 — 새로고침으로 회복 가능한 일시 상태이고, 서버가
        재기동되면 다시 시도해 보는 편이 맞다.
        """
        body, err = self._read_json_body()
        reason = (body or {}).get("reason", "") if not err else ""
        with Handler._live_degraded_lock:
            Handler._live_degraded_set.add((cwd_h, sid))
        log(f"POST /s/{cwd_h}/{sid}/degrade — 라이브 강등 보고: {reason}")
        self._send_json(200, {"status": "ok"})

    def _handle_session_mail(self, parsed, cwd_h: str, sid: str, cwd: str):
        """Issue353_2 M2-b: `GET /s/{h}/{sid}/mail?since=<seq>&epoch=<gen>&token=`.

        메일박스 pull 엔드포인트. 인가는 상위 라우트가 이미 마쳤다(세션 token 32hex
        + source-IP allowlist) — 라이브 뷰는 **새 인가 체계를 만들지 않는다**.

        응답 규약:
        * `304` — 신규 블록 없음. 무변경 poll 은 stat 1회 + 정수 비교로 끝나고
          파일을 읽지 않는다(폴링 비용 상한).
        * `205` — 세대 불일치·보유 범위 밖 커서. 클라가 DOM 을 비우고 재동기화한다.
        * `200` — `{epoch, max_seq, min_seq, turn_active, blocks:[…]}`
        """
        path = _resolve_session_jsonl(cwd, sid)
        if not path:
            self._send_json(404, {"error": "transcript not found"})
            return
        qs = parse_qs(parsed.query)
        try:
            since = int((qs.get("since") or ["0"])[0])
        except ValueError:
            since = 0
        epoch = (qs.get("epoch") or [""])[0]
        # Issue357: TTL 지난 메일박스 정리 — 간격 내 호출은 비교 1회(전수 스캔 없음).
        #   별도 타이머를 두지 않는 이유는 메일박스가 **라이브 뷰를 볼 때만** 생기기 때문이다.
        mailbox.maybe_gc()
        box = mailbox.get_box(cwd_h, sid, path)
        # 변경이 있을 때만 파일을 읽는다 — 무변경 poll 은 여기서 stat 1회로 끝난다
        if box.changed():
            box.sync()
        status, payload = box.read_since(since, epoch)
        # Issue353_2 M2-d: 미응답 폼은 블록과 별개 축이다(응답되면 사라지는 상태) →
        #   증분이 아니라 **매 응답에 현재 상태**로 싣는다. 304 일 때도 폼 상태만 바뀔 수
        #   있으므로, 폼이 있으면 304 대신 200 으로 승격해 클라가 카드를 띄우게 한다.
        pending = self._pending_ask_form(cwd)
        if status == 304:
            if pending and pending.get("form_ts") != (qs.get("form") or [""])[0]:
                status = 200
                payload = {"epoch": box.epoch, "max_seq": box.max_seq,
                           "min_seq": box.min_seq, "turn_active": box.turn_active,
                           "blocks": []}
            else:
                self.send_response(304)
                self.send_header("X-Mail-Epoch", payload.get("epoch", ""))
                self.send_header("X-Mail-Max-Seq", str(payload.get("max_seq", 0)))
                self.end_headers()
                return
        if status == 200:
            payload["pending_form"] = pending
        self._send_json(status, payload)

    def _pending_ask_form(self, cwd: str):
        """Issue353_2 M2-d: 이 프로젝트의 **미응답 b모드 폼** 최신 1건.

        멱등은 이 함수가 만들지 않는다 — 기존 `/answer` 경로가 registry 엔트리에
        `answered` 를 마킹하는 **1회 소비**가 유일한 중재자다(Issue45). 라이브 뷰는
        표시 표면을 하나 더 얹을 뿐이므로, 터미널·다른 탭에서 먼저 응답하면 다음
        poll 에서 이 값이 `None` 이 되어 카드가 사라진다(first-submit-wins 자동 성립).
        """
        import urllib.parse as _u
        try:
            with registry_lock:
                entries = load_registry(HTM_REGISTRY)
        except Exception:
            return None
        cand, cand_ts = None, -1
        for e in entries:
            if e.get("cwd", "") != cwd or e.get("answered"):
                continue
            base = os.path.basename(e.get("path", ""))
            if not (base.startswith("claude-htm-ask-") or "_b_" in base):
                continue
            m = re.search(r"(\d{9,})", base)
            ts = int(m.group(1)) if m else 0
            if ts > cand_ts:
                cand, cand_ts = e, ts
        if cand is None:
            return None
        path = cand.get("path", "")
        if not path or not os.path.isfile(path):
            return None
        # 10분(Claude polling timeout) 넘긴 폼은 이미 죽은 질문 — 카드로 띄우지 않는다
        try:
            if time.time() - os.path.getmtime(path) > 600:
                return None
        except OSError:
            return None
        return {
            "form_ts": str(cand_ts),
            "title": cand.get("title") or os.path.basename(path),
            # iframe 임베드라 `_shell=1` 를 붙여 top-level 오인 302 를 피한다
            "url": "/htm-doc?path=" + _u.quote(path) + "&_shell=1",
        }

    def _handle_session_live(self, parsed, cwd_h: str, sid: str, cwd: str,
                             token: str, proj: dict):
        """Issue353_2 M2-c: `GET /s/{h}/{sid}/live?token=` — 라이브 뷰 셸.

        md-first 셸(`md_shell`)의 **같은 CSS·렌더 파이프라인**을 재사용한다 —
        셸이 2벌이면 스타일 드리프트가 서버 안에서 재발하기 때문이다(arch 셸 1벌 원칙).
        차이는 본문을 정적 md 로 채우는 대신 폴러가 메일박스에서 블록을 받아
        **완결 블록만 append** 한다는 점이다.
        """
        label = proj.get("name") or project_meta(cwd)["name"]
        title = _session_ai_title(cwd, sid) or f"라이브 세션 — {label}"
        nonce = md_shell.make_nonce()
        setting = _load_hub_setting()
        display, warn = render_gate.normalize_display(
            setting.get("render_display", "auto"))
        if warn:
            log(f"GET /s/{cwd_h}/{sid}/live — {warn}", "WARNING")
        body = md_shell.render_live_shell(
            title, cwd, label, sid, cwd_h, token, nonce,
            display=display,
            degrade={"nodes": setting.get("live_degrade_nodes", 12000),
                     "render_ms": setting.get("live_degrade_render_ms", 400),
                     "heap_pct": setting.get("live_degrade_heap_pct", 85)})
        body = _normalize_hub_header_css(body)
        body = _normalize_hub_body_css(body)
        body = _inject_before_body_end(body, CLOSE_SHIM)
        body = _inject_before_body_end(body, COPY_LINK_SHIM)
        body = _inject_before_body_end(body, HUB_LINK_SHIM)
        body = body.replace(b"<script>", b'<script nonce="' + nonce.encode("ascii") + b'">')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", md_shell.csp_header(nonce))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_session_answer(self, parsed):
        """Issue18 Phase 2: POST /s/{cwd_hash}/{sid}/answer?token=
        body: {answers:[{question, value}, ...]} → inbox JSON 저장 (Mode B Claude polling 호환)."""
        parts = parsed.path.strip("/").split("/")
        # ["s", cwd_hash, sid, "answer"]
        if len(parts) != 4 or parts[0] != "s" or parts[3] != "answer":
            self._send_json(404, {"error": "not found"})
            return
        cwd_h = parts[1]
        sid_raw = parts[2]
        sid = "".join(c for c in sid_raw if c.isalnum() or c in "-_")
        if not sid or sid != sid_raw:
            self._send_json(400, {"error": "invalid sid"})
            return
        with projects_lock:
            p = projects.get(cwd_h)
        if not p:
            self._send_json(404, {"error": "unknown cwd_hash"})
            return
        token = get_token_param(parsed)
        expected = p.get("token", "")
        if not token or not hmac.compare_digest(expected, token):
            self._send_json(401, {"error": "invalid token"})
            return
        body, err = self._read_json_body(max_bytes=1024 * 1024)
        if err:
            self._send_json(400, {"error": err})
            return
        if "answers" not in body or not isinstance(body["answers"], list):
            self._send_json(400, {"error": "missing or invalid 'answers' array"})
            return
        # Mode B Claude polling 호환 inbox JSON
        # ___pm Issue20 / .claude Issue31: sid 서브폴더로 격리하여
        # 동일 cwd 내 다중 세션 cross-sid 답변 오염 방지.
        inbox = f"{INBOX_ROOT}/{cwd_h}/{sid}"
        os.makedirs(inbox, exist_ok=True)
        ts = int(time.time() * 1000)
        record = {
            "sid": sid,
            "ts": ts,
            "answers": body["answers"],
            "source": "session_answer",
        }
        out_path = f"{inbox}/{ts}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        # Issue26: 답변 JSON + 복사 버튼 placeholder (paste-back fallback)
        # Claude polling 누락·timeout·세션 교체 시 사용자가 JSON 복사하여 채팅에 paste 가능
        record_json_str = json.dumps(record, ensure_ascii=False, indent=2)
        record_json_attr = html.escape(record_json_str, quote=True)
        record_json_text = html.escape(record_json_str, quote=False)
        placeholder_html = (
            '<div class="answer-placeholder">'
            '<p><strong>✓ 답변 전송됨</strong> — Claude 처리 대기 중...</p>'
            '<p style="color:var(--muted);font-size:0.9em">'
            'polling 누락·timeout·세션 교체로 회수 실패 시 아래 JSON 을 채팅에 paste 하면 회수 가능.'
            '</p>'
            '<div class="answer-actions">'
            f'<button type="button" class="copy-btn" data-json="{record_json_attr}" '
            'onclick="copyAnswersJSON(this)">📋 JSON 복사</button>'
            '<span class="copy-msg" id="copy-msg"></span>'
            '</div>'
            f'<pre class="answer-json">{record_json_text}</pre>'
            '</div>'
        )
        now = time.time()
        with sessions_lock:
            entry = sessions.get((cwd_h, sid))
            if entry:
                entry["mode"] = "A"
                entry["content_type"] = "response"
                entry["content"] = placeholder_html
                entry["updated"] = now
        persist_sessions()
        sse_broadcast(cwd_h, "session_update", {"sid": sid, "mode": "A", "content_type": "response"}, sid=sid)
        log(f"POST /s/{cwd_h}/{sid}/answer — saved {out_path}")
        self._send_json(200, {"ok": True, "path": out_path, "ts": ts, "record": record})

    def _handle_session_dismiss(self, parsed):
        """Issue132: POST /session/dismiss?cwd=&sid=&token= → live 카드 수동 제거.
        VSCode 가 세션 종료 후에도 claude 프로세스를 살려두면 _pid_alive 게이트가
        영원히 통과해 빈 live 카드가 잔존한다. 본 엔드포인트는 sessions entry 만
        제거(prune)하고 프로세스는 건드리지 않는다 (claude 오살 방지). dashboard
        runner 종료는 별도 /control(action=stop) 경로 — 여기선 등록 해제만."""
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        qs = parse_qs(parsed.query)
        sid_raw = (qs.get("sid") or [""])[0]
        sid = "".join(c for c in sid_raw if c.isalnum() or c in "-_")
        if not sid or sid != sid_raw:
            self._send_json(400, {"error": "missing or invalid sid"})
            return
        h = cwd_hash(cwd)
        with sessions_lock:
            pruned = sessions.pop((h, sid), None) is not None
        # Issue135: pop 만으론 살아있는 claude native 프로세스의 재등록(register/
        #   heartbeat)을 못 막아 카드가 부활한다 → tombstone 기록(TTL 내 collect 제외).
        #   pop 여부와 무관히 기록(이미 재등록된 직후일 수 있음).
        _live_dismiss_add(h, sid)
        if pruned:
            persist_sessions()
            log(f"POST /session/dismiss — pruned live session hash={h} sid={sid}")
        self._send_json(200, {"status": "ok" if pruned else "not_found",
                              "pruned": pruned, "cwd_hash": h, "sid": sid})

    def _handle_session_action(self, parsed):
        """Issue24 Phase 3: POST /s/{cwd_hash}/{sid}/action?token=
        body: {widget_index, widget_type, action_type, payload?, label?} → inbox action-{ts}.json.
        Claude polling 이 'action-' prefix 필터로 회수 가능. answer 파일과 분리."""
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "s" or parts[3] != "action":
            self._send_json(404, {"error": "not found"})
            return
        cwd_h = parts[1]
        sid_raw = parts[2]
        sid = "".join(c for c in sid_raw if c.isalnum() or c in "-_")
        if not sid or sid != sid_raw:
            self._send_json(400, {"error": "invalid sid"})
            return
        with projects_lock:
            p = projects.get(cwd_h)
        if not p:
            self._send_json(404, {"error": "unknown cwd_hash"})
            return
        token = get_token_param(parsed)
        expected = p.get("token", "")
        if not token or not hmac.compare_digest(expected, token):
            self._send_json(401, {"error": "invalid token"})
            return
        body, err = self._read_json_body(max_bytes=256 * 1024)
        if err:
            self._send_json(400, {"error": err})
            return
        action_type = body.get("action_type")
        if action_type not in ("notify", "link", "control", "terminate"):
            self._send_json(400, {"error": f"invalid action_type: {action_type!r}"})
            return
        # Issue280: terminate = 세션 GC — 서버가 직접 kill 체인 실행
        if action_type == "terminate":
            self._handle_session_terminate(cwd_h, sid, body, p)
            return
        # link/control 은 클라이언트 측에서 처리, server 는 notify 인 경우에만 inbox 저장
        if action_type != "notify":
            self._send_json(200, {"ok": True, "note": "non-notify actions handled client-side"})
            return
        inbox = f"{INBOX_ROOT}/{cwd_h}/{sid}"
        os.makedirs(inbox, exist_ok=True)
        ts = int(time.time() * 1000)
        record = {
            "sid": sid,
            "ts": ts,
            "source": "session_action",
            "action_type": action_type,
            "widget_index": body.get("widget_index"),
            "widget_type": body.get("widget_type"),
            "label": body.get("label"),
            "payload": body.get("payload"),
        }
        out_path = f"{inbox}/action-{ts}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        log(f"POST /s/{cwd_h}/{sid}/action — saved {out_path}")
        self._send_json(200, {"ok": True, "path": out_path, "ts": ts})

    def _handle_session_terminate(self, cwd_h: str, sid: str, body: dict, proj: dict):
        """Issue280: 세션 GC — /s/{h}/{sid}/action action_type=terminate.
        kill 대상은 sessions entry 의 live_pid·gc_meta 만 (body pid 수신 금지).
        message 는 실전달 없이 레코드로만 저장 (향후 분석용).
        절차: plan → execute → 분석 로그(JSONL)+inbox 레코드 → tombstone·prune → SSE."""
        with sessions_lock:
            entry = sessions.get((cwd_h, sid))
            snap = dict(entry) if entry else None
        if not snap:
            self._send_json(404, {"error": "session not registered"})
            return
        steps = _gc_plan(snap)
        if not steps:
            self._send_json(409, {"error": "no GC target — live_pid/gc_meta 미등록 세션"})
            return
        message = str(body.get("message", "") or "")[:2000]
        stages = _gc_execute(steps)
        ok_any = any(s.get("ok") for s in stages)
        method = ("tmux-pane" if any(s["step"] == "tmux-kill-pane" and s.get("ok")
                                     for s in stages) else "signal")
        ts = int(time.time() * 1000)
        record = {
            "ts": ts, "cwd_hash": cwd_h, "sid": sid, "cwd": proj.get("cwd", ""),
            "live_pid": snap.get("live_pid"), "gc_meta": snap.get("gc_meta"),
            "method": method, "ok": ok_any, "stages": stages, "message": message,
            "client": self.client_address[0] if self.client_address else None,
        }
        # 분석용 GC 로그 (JSONL append — server.log 와 동일 STATE_DIR)
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(f"{STATE_DIR}/session-gc.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as ex:
            log(f"session-gc.jsonl append 실패: {ex}", "WARNING")
        # inbox terminate 레코드 — 세션이 아직 폴링 중이면 회수 가능 + 분석 원천
        try:
            inbox = f"{INBOX_ROOT}/{cwd_h}/{sid}"
            os.makedirs(inbox, exist_ok=True)
            with open(f"{inbox}/action-{ts}.json", "w", encoding="utf-8") as f:
                json.dump({"sid": sid, "ts": ts, "source": "session_action",
                           "action_type": "terminate", "message": message,
                           "method": method, "stages": stages},
                          f, ensure_ascii=False, indent=2)
        except Exception as ex:
            log(f"terminate inbox 레코드 실패: {ex}", "WARNING")
        # tombstone + prune — 활성 카드 즉시 소멸·heartbeat 재등록 부활 차단 (Issue135 재사용)
        with sessions_lock:
            pruned = sessions.pop((cwd_h, sid), None) is not None
        _live_dismiss_add(cwd_h, sid)
        if pruned:
            persist_sessions()
        sse_broadcast(cwd_h, "session_terminated", {"sid": sid, "method": method}, sid=sid)
        log(f"POST /s/{cwd_h}/{sid}/action terminate — ok={ok_any} method={method} "
            f"stages={len(stages)}")
        self._send_json(200, {"ok": ok_any, "method": method, "stages": stages, "ts": ts})

    def _handle_session_preview(self, parsed):
        """Issue29 Phase 6: POST /session/preview?cwd=&token= body={content_type, content}.
        sessions table 미반영, SSE 미전파. 응답: {ok, preview_url, ttl}.
        publish 전 dashboard/form/response 렌더 검증 채널."""
        cwd = get_cwd_param(parsed)
        token = get_token_param(parsed)
        if not validate(cwd, token):
            self._send_json(401, {"error": "invalid cwd or token"})
            return
        body, err = self._read_json_body(max_bytes=4 * 1024 * 1024)
        if err:
            self._send_json(400, {"error": err})
            return
        ctype = body.get("content_type", "response")
        if ctype not in ("response", "form", "dashboard"):
            self._send_json(400, {"error": f"unknown content_type: {ctype}"})
            return
        content = body.get("content", "")
        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)
            except Exception:
                self._send_json(400, {"error": "content not serializable"})
                return
        if ctype == "dashboard":
            qs = parse_qs(parsed.query)
            lenient = (qs.get("lenient") or ["0"])[0] in ("1", "true", "yes")
            if not lenient:
                verr = validate_dashboard(content)
                if verr:
                    self._send_json(400, {"error": verr})
                    return
        mode = determine_mode(ctype)
        h = cwd_hash(cwd)
        # ephemeral preview id (URL-safe, non-guessable)
        pid = uuid.uuid4().hex[:16]
        now = time.time()
        with preview_lock:
            # GC expired entries
            for k in list(previews.keys()):
                if now - previews[k]["created"] > PREVIEW_TTL:
                    del previews[k]
            previews[pid] = {
                "cwd_hash": h,
                "content_type": ctype,
                "content": content,
                "mode": mode,
                "created": now,
            }
        log(f"POST /session/preview — hash={h} pid={pid} ctype={ctype} ttl={PREVIEW_TTL}")
        self._send_json(200, {
            "ok": True,
            "mode": mode,
            "preview_url": f"/preview/{h}/{pid}?token={token}",
            "ttl": PREVIEW_TTL,
        })

    def _handle_preview_get(self, parsed):
        """Issue29 Phase 6: GET /preview/{cwd_hash}/{pid}?token= → SPA shell HTML (PREVIEW=1).
        GET /preview/{cwd_hash}/{pid}/data?token= → preview JSON."""
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "preview":
            self._send_json(404, {"error": "not found"})
            return
        cwd_h = parts[1]
        pid_raw = parts[2]
        pid = "".join(c for c in pid_raw if c.isalnum())
        if not pid or pid != pid_raw:
            self._send_json(400, {"error": "invalid preview id"})
            return
        is_data = len(parts) >= 4 and parts[3] == "data"
        with projects_lock:
            p = projects.get(cwd_h)
        if not p:
            self._send_json(404, {"error": "unknown cwd_hash"})
            return
        cwd = p.get("cwd", "")
        expected = p.get("token", "")
        token = get_token_param(parsed)
        if not token or not hmac.compare_digest(expected, token):
            self._send_json(401, {"error": "invalid token"})
            return
        now = time.time()
        with preview_lock:
            entry = previews.get(pid)
            if entry and now - entry["created"] > PREVIEW_TTL:
                del previews[pid]
                entry = None
        if not entry:
            self._send_json(404, {"error": "preview expired or not found"})
            return
        if entry.get("cwd_hash") != cwd_h:
            self._send_json(404, {"error": "preview cwd mismatch"})
            return
        if is_data:
            self._send_json(200, {
                "content_type": entry["content_type"],
                "content": entry["content"],
                "mode": entry["mode"],
                "updated": entry["created"],
                "capabilities": {},
                "preview": True,
            })
            return
        # PREVIEW SPA shell HTML
        try:
            import urllib.parse as _u
            cwd_q = _u.quote(cwd)
        except Exception:
            cwd_q = ""
        name = p.get("name", "session")
        color = p.get("color", "hsl(280,60%,45%)")
        title = f"PREVIEW — {name} ({pid})"
        html = (SESSION_SHELL_HTML
                .replace("{TITLE}", title)
                .replace("{NAME}", "🔍 PREVIEW: " + name)
                .replace("{COLOR}", color)
                .replace("{CWD_HASH}", cwd_h)
                .replace("{SID}", pid)
                .replace("{TOKEN}", token)
                .replace("{CWD_Q}", cwd_q)
                .replace("{PREVIEW}", "1"))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


HUB_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<link rel="icon" href="/fpm-icon.png">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fPm Hub</title>
<style>
/* Issue28: 흰색 배경 고정. @media prefers-color-scheme dark override 제거 (다중 탭 일관성). */
:root { --fg:#111; --bg:#fff; --muted:#666; --border:#ddd; --card:#fafafa; --code-bg:#f0f0f0; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
  background: var(--bg); color: var(--fg); margin: 0; padding: 0; line-height: 1.5; }
header { background: {HUB_HEADER_GRAD}; color: white; padding: 1rem 1.5rem;
  display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
header .hub-logo { height: 3em; flex: 0 0 auto; }
/* Issue242: 서버 이모지 로고 — fPm 아이콘(img) 대체. img 3em 높이에 맞춤. */
header .hub-logo.hub-emoji { height: auto; font-size: 2.5rem; line-height: 1; display: flex; align-items: center;
  filter: drop-shadow(0 1px 2px rgba(0,0,0,0.3)); }
header .header-text { display: flex; flex-direction: column; flex: 1 1 auto; min-width: 0; }
header h1 { margin: 0; font-size: 1.3rem; }
header h1 #hub-headline { font-weight: 400; opacity: 0.92; font-size: 0.92em; }
header .sub { font-size: 0.85em; opacity: 0.9; margin-top: 0.3rem; }
/* Issue87: 중요 이벤트 칩 — 중요도 결정 모듈 산출(important_events) 렌더 */
.imp-chip { display: inline-block; margin: 0.15rem 0.35rem 0.15rem 0; padding: 0.14rem 0.55rem;
  border-radius: 11px; font-size: 0.95em; line-height: 1.45; text-decoration: none; white-space: nowrap;
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
.imp-chip.imp-critical { background: #d33; color: #fff; }
.imp-chip.imp-warning { background: #e8a020; color: #fff; }
.imp-chip.imp-info { background: rgba(255,255,255,0.2); color: #fff; border: 1px solid rgba(255,255,255,0.45); }
a.imp-chip:hover { filter: brightness(1.12); }
span.imp-chip { cursor: pointer; }
span.imp-chip:hover { filter: brightness(1.12); }
.imp-chip-wrap { display: inline-flex; align-items: center; margin: 0.15rem 0.35rem 0.15rem 0; }
.imp-chip-wrap .imp-chip { margin: 0; }
.imp-dismiss { background: none; border: none; color: inherit; cursor: pointer; padding: 0 0.1rem 0 0.2rem; opacity: 0.65; font-size: 0.88em; line-height: 1; }
.imp-dismiss:hover { opacity: 1; }
.imp-none { opacity: 0.82; }
.btn-project-list { flex: none; background: rgba(255,255,255,0.18); border: 1px solid rgba(255,255,255,0.55);
  color: white; padding: 0.5rem 0.95rem; border-radius: 6px; font-size: 0.85em; cursor: pointer; white-space: nowrap; }
.btn-project-list:hover { background: rgba(255,255,255,0.34); }
/* Issue293: 🌳 Tree 는 <a>(fpmOpenInShell 경유) — <button> 과 높이·정렬을 맞춘다. */
a.btn-project-list { text-decoration: none; display: inline-flex; align-items: center; line-height: 1.2; }
.header-actions { display: flex; align-items: center; gap: 0.4rem; flex-shrink: 0; }
.btn-settings { flex: none; background: transparent; border: none;
  color: white; padding: 0.4rem 0.5rem; border-radius: 6px; font-size: 1.1em; cursor: pointer; line-height: 1; }
.btn-settings:hover { background: rgba(255,255,255,0.2); }
/* 설정 모달 헤더 KO/EN 뷰 토글 (다국어 보기 — 저장값 미변경, 기본=서버 language) */
.set-lang { display: inline-flex; border: 1px solid rgba(255,255,255,0.55); border-radius: 6px; overflow: hidden; margin-right: 0.6rem; }
.set-lang button { background: transparent; border: none; color: #fff; padding: 0.12rem 0.55rem; font-size: 0.72em; font-weight: 700; cursor: pointer; line-height: 1.7; }
.set-lang button.active { background: rgba(255,255,255,0.92); color: #333; }
/* Issue168: 설정 모달 (3탭) */
/* Issue205/207: 탭바를 modal-body 밖(head 직후 비스크롤 형제)에 배치 → 자연 고정. 음수마진 sticky 폐기 */
.set-tabs { display: flex; gap: 0.3rem; border-bottom: 1px solid var(--border);
  background: var(--bg); padding: 0 1.1rem; flex: 0 0 auto; }
.set-tab { background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--muted);
  padding: 0.5rem 0.9rem; font-size: 0.95em; cursor: pointer; }
.set-tab:hover { color: var(--fg); }
.set-tab.active { color: var(--fg); border-bottom-color: hsl(220,80%,55%); font-weight: 600; }
/* Issue: 탭 전환 시 모달 높이 점프 제거 — 3 pane 을 같은 grid cell 에 적층하여
   숨은 pane 도 높이를 점유 → modal-body 높이 = 가장 높은 탭 기준으로 고정 */
.set-pane { grid-area: 1 / 1; visibility: hidden; }
.set-pane.active { visibility: visible; }
/* 키 라벨 좌측정렬 + 컨트롤 42% 컬럼 이후 배치 · 행 높이 균일 (Issue261) */
.set-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.25rem 0.7rem; padding: 0.6rem 0; border-bottom: 1px dashed var(--border); min-height: 2.6em; }
.set-row:last-child { border-bottom: none; }
.set-row label.set-key { flex: 0 0 42%; text-align: left; font-family: ui-monospace, monospace; font-size: 0.9em; }
/* Issue208: 키의 `_` 를 배경색과 동색으로 숨김(비가시). 문자 유지 → 복붙 시 실제 키명 보존 */
.set-row label.set-key .set-us { color: var(--bg); }
/* 기본값에서 변경된 항목 연필 마커 (라벨 우측 = 중심선 옆) */
.set-row label.set-key .set-pencil { color: #c60; margin-left: 0.35em; font-size: 0.92em; cursor: help; }
.set-row .set-input { flex: 0 0 auto; min-height: 1.9em; display: inline-flex; align-items: center; gap: 0.3rem; }
.set-row .set-input input[type=number] { width: 7em; }
.set-row .set-input input[type=text] { width: 22em; max-width: 100%; }
.set-row .set-input select, .set-row .set-input input { padding: 0.25rem 0.4rem; border: 1px solid var(--border);
  border-radius: 5px; background: var(--bg); color: var(--fg); font-size: 0.9em; }
/* Issue196: 설명을 컨트롤 아래 전체폭(2행)으로 — 단어당 줄바꿈 깨짐 해소 */
.set-row .set-desc { flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center;
  width: 1.35em; height: 1.35em; font-size: 0.78em; font-weight: 700; color: var(--muted);
  border: 1px solid var(--border); border-radius: 50%; cursor: help; user-select: none; }
.set-row .set-badge { flex: 0 0 auto; margin-left: auto; font-size: 0.72em; padding: 0.05rem 0.4rem; border-radius: 9px; white-space: nowrap; }
.set-badge.b-auto { background: #d3f0d3; color: #1a5d1a; }
.set-badge.b-hook { background: #d0e4f7; color: #134a78; }
.set-badge.b-restart { background: #fbe3c5; color: #8a4b08; }
.set-badge { cursor: help; }
/* Issue168: 배지 hover 즉시 풍선 도움말 (position:fixed → modal-body overflow 비절단, 배지 위쪽 표시) */
#set-tip { position: fixed; z-index: 3000; max-width: 270px; background: #222; color: #fff;
  padding: 0.5rem 0.7rem; border-radius: 7px; font-size: 0.8rem; line-height: 1.55; text-align: left;
  box-shadow: 0 6px 20px rgba(0,0,0,0.35); pointer-events: none; white-space: normal; }
#set-tip[hidden] { display: none; }
#set-tip::after { content: ''; position: absolute; top: 100%; border: 7px solid transparent;
  border-top-color: #222; left: var(--tip-arrow, 50%); transform: translateX(-50%); }
/* 토글 스위치 */
.set-sw { width: 2.4em; height: 1.3em; border-radius: 999px; border: none; padding: 0; cursor: pointer;
  position: relative; background: rgba(128,128,128,0.45); transition: background 0.15s; }
.set-sw.on { background: #2ca02c; }
.set-sw .set-sw-knob { width: 1em; height: 1em; border-radius: 50%; background: #fff; position: absolute;
  top: 50%; transform: translateY(-50%); left: 0.15em; transition: left 0.15s; box-shadow: 0 1px 2px rgba(0,0,0,0.3); }
.set-sw.on .set-sw-knob { left: calc(100% - 1.15em); }
.set-warn { background: rgba(250,180,80,0.15); border: 1px solid rgba(200,120,20,0.4); border-radius: 6px;
  padding: 0.5rem 0.7rem; font-size: 0.8em; margin-bottom: 0.8rem; line-height: 1.5; }
.set-ok-btn { flex: none; background: #2ca02c; color: #fff; border: 1px solid #1a7a1a; border-radius: 5px;
  padding: 0.4rem 1.1rem; font-size: 0.95em; cursor: pointer; }
.set-ok-btn:hover { background: #1a7a1a; }
.set-ok-btn:disabled { opacity: 0.5; cursor: default; }
@media (prefers-color-scheme: dark) {
  .set-badge.b-auto { background: #1e3a1e; color: #8fd98f; }
  .set-badge.b-hook { background: #16314a; color: #8ec6f0; }
  .set-badge.b-restart { background: #4a3410; color: #e0a860; }
}
/* Project List 팝업 모달 */
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 2000;
  display: flex; align-items: center; justify-content: center; }
.modal-backdrop[hidden] { display: none; }
.modal { background: var(--bg); border-radius: 10px; width: min(940px, 92vw); max-height: 86vh;
  display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.45); }
.modal-head { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1.1rem;
  background: linear-gradient(90deg, hsl(220,60%,45%), hsl(280,60%,45%)); color: white; }
.modal-title { font-weight: 700; font-size: 1.05em; }
.modal-close { background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.45); color: white;
  width: 1.9em; height: 1.9em; border-radius: 50%; cursor: pointer; font-size: 0.9em; line-height: 1; }
.modal-close:hover { background: #c33; border-color: #c33; }
.modal-body { padding: 0.9rem 1.1rem; overflow-y: auto; }
/* 설정 모달 body: pane 적층(grid) → 탭 전환해도 높이 불변(가장 높은 탭 기준) */
#set-modal .modal-body { display: grid; align-items: start; }
.modal-foot { padding: 0.5rem 1.1rem; font-size: 0.78em; color: var(--muted); border-top: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center; gap: 0.8rem; }
.pl-edit-btn { flex: none; background: #36c; color: white; border: 1px solid #258; border-radius: 4px;
  padding: 0.35rem 0.8rem; font-size: 1rem; cursor: pointer; }
.pl-edit-btn:hover { background: #258; }
.cf-btn { flex: none; border-radius: 5px; padding: 0.4rem 1rem; font-size: 0.92em; cursor: pointer; }
.cf-cancel { background: var(--bg); color: var(--fg); border: 1px solid var(--border); }
.cf-cancel:hover { background: var(--code-bg); }
.cf-ok { background: #c33; color: #fff; border: 1px solid #a22; }
.cf-ok:hover { background: #a22; }
.pl-table { border-collapse: collapse; width: 100%; font-size: 0.86em; }
.pl-table th, .pl-table td { border: 1px solid var(--border); padding: 0.35rem 0.55rem; text-align: left; vertical-align: top; }
.pl-table th { background: var(--code-bg); position: sticky; top: 0; }
.pl-table tbody tr { cursor: pointer; }
/* Issue370: hover 행 전체를 그 프로젝트 색으로. Issue368 로 색이 Map 셀 배경이 된 뒤,
   기존 파란 hover 는 한 행을 두 색으로 쪼개 보이게 했다. 색은 `<tr>` 의 `--pl-color` 한 곳에
   싣고 셀은 그것을 읽기만 한다 — 셀마다 인라인을 반복하면 같은 값이 7군데로 흩어진다.
   색 미지정 프로젝트는 fallback 으로 종전 파란 hover 를 그대로 쓴다. */
.pl-table tbody tr:hover td { background: var(--pl-color, #e8eef9); }
.pl-table tbody tr.pl-sel td { background: #d4e2fb; box-shadow: inset 3px 0 0 hsl(220,80%,50%); }
/* 선택 행도 hover 는 프로젝트 색 — 선택 표식은 배경이 아니라 좌측 box-shadow 바가 담당한다 */
.pl-table tbody tr.pl-sel:hover td { background: var(--pl-color, #c7d8f7); }
.pl-table td.pl-id { font-weight: 700; font-size: 1.15em; text-align: center;
  font-variant-numeric: tabular-nums; background: var(--card); white-space: nowrap; }
/* htm 자동 모드 off 프로젝트: 번호 셀 회색 배경(gray 10%) */
.pl-table tr.htm-off td.pl-id { background: rgba(128,128,128,0.10); color: var(--muted); }
/* htm on/off 토글 버튼 (번호 왼쪽 좁은 컬럼) */
.pl-table th.pl-toggle, .pl-table td.pl-toggle { width: 2.4em; text-align: center; padding: 0.25rem 0.3rem; }
.pl-table th.pl-toggle { font-size: 0.82em; font-weight: 600; opacity: 0.75; }
.htm-tgl { width: 1.85em; height: 1.05em; border-radius: 999px; border: none; padding: 0; cursor: pointer;
  position: relative; display: inline-flex; align-items: center; transition: background 0.15s; vertical-align: middle; }
.htm-tgl.on { background: #2ca02c; }
.htm-tgl.off { background: rgba(128,128,128,0.45); }
.htm-tgl.mixed { background: linear-gradient(90deg, #2ca02c 50%, rgba(128,128,128,0.45) 50%); }
.htm-tgl.mixed .htm-tgl-knob { left: 50%; transform: translate(-50%, -50%); }
.pl-table th.pl-toggle .pl-toggle-lbl { font-size: 0.82em; font-weight: 600; opacity: 0.75; margin-top: 0.15em; line-height: 1; }
.htm-tgl .htm-tgl-knob { width: 0.8em; height: 0.8em; border-radius: 50%; background: #fff; position: absolute;
  top: 50%; transform: translateY(-50%); transition: left 0.15s; box-shadow: 0 1px 2px rgba(0,0,0,0.3); }
.htm-tgl.on .htm-tgl-knob { left: calc(100% - 0.95em); }
.htm-tgl.off .htm-tgl-knob { left: 0.15em; }
.htm-tgl:focus-visible { outline: 2px solid #36c; outline-offset: 1px; }
.pl-table td.pl-path code { font-size: 0.92em; background: var(--code-bg); padding: 0.05rem 0.3rem; border-radius: 3px; }
/* Issue368: Project List 마지막 컬럼 = `Map`. 색은 스와치를 없애고 셀 배경으로 내렸다
   (인라인 style 이라 행 hover/선택 배경보다 우선 — 색이 계속 보인다).
   아이콘 3단 가시성: 보유 0.85(카드 .issue-map 과 동일) / 미보유 0.22 무채색 / hover 1.0 확대. */
.pl-table td.pl-map { text-align: center; width: 3em; padding: 0.2rem 0.3rem; }
.pl-map-ico { display: inline-block; font-size: 1.15em; line-height: 1.4; text-decoration: none;
  opacity: 0.85; transition: opacity 0.12s, transform 0.12s; }
.pl-map-ico.none { opacity: 0.22; filter: grayscale(1); cursor: default; }
/* stale 은 카드(0.5/grayscale .6)보다 덜 흐리게 둔다 — 카드는 한 장을 볼 때의 표식이지만
   표에서는 바로 아래 행의 '맵 없음'(0.22) 과 나란히 놓이므로, 카드 값 그대로면 두 상태가
   같은 회색 덩어리로 읽힌다. 판정 자체는 카드와 동일 필드를 쓴다(표현만 다름). */
.pl-map-ico.stale { filter: grayscale(0.4); opacity: 0.62; }
.pl-table td.pl-map:hover .pl-map-ico, .pl-map-ico:hover { opacity: 1; filter: none; transform: scale(1.25); }
.pl-map-ico:focus-visible { outline: 2px solid #36c; outline-offset: 1px; }
/* Issue42: hub 2-컬럼 — .hub-main(2fr) + .hub-feed(1fr) */
main { padding: 1.5rem; max-width: 1600px; margin: 0 auto; display: flex; gap: 1rem; align-items: flex-start; }
.hub-main { flex: 2; min-width: 0; }
.status-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; font-size: 0.9em; color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.4rem; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; transition: transform 0.15s; }
.card:hover { transform: translateY(-2px); }
/* Issue28: peacock.color (파스텔) → 어두운 글자 기본 */
.card-head { padding: 0.6rem 0.9rem; color: #1a1a1a; display: flex; justify-content: space-between; align-items: center; }
.card-head .name { font-weight: 600; font-size: 0.95em; }
.card-head .name code { color: var(--fg); background: rgba(255,255,255,0.7); padding: 0.05rem 0.35rem; border-radius: 3px; font-size: 0.85em; }
.card-head .badge { background: rgba(0,0,0,0.12); color: #1a1a1a; padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.75em; }
.card-head .head-right { display: flex; align-items: center; gap: 0.35rem; }
.card-head .card-close { width: 1.6em; height: 1.6em; padding: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; border: 1px solid rgba(0,0,0,0.18); background: rgba(255,255,255,0.55); color: #1a1a1a; cursor: pointer; font-size: 0.85em; line-height: 1; }
.card-head .card-close:hover { background: #c33; color: white; border-color: #c33; }
.card-head .card-close:disabled { opacity: 0.5; cursor: not-allowed; }
.card-head .qa-icon { font-size: 0.95em; font-weight: 700; line-height: 1; }
.card-head .qa-icon.ok { color: #1a7f1a; }
.card-head .qa-icon.err { color: #c00; }
.card-head .qa-icon.pending { color: #1a1a1a; opacity: 0.65; }
.card-body { padding: 0.8rem 0.9rem; }
.dash-title { font-weight: 500; margin-bottom: 0.4rem; }
/* Issue69: htm-doc 카드 헤드 우측 날짜 */
.card-head .card-date { font-size: 0.72em; opacity: 0.85; white-space: nowrap; }
/* Issue70: htm-doc 카드 본문 2줄 요약 */
.card-summary { font-size: 0.82em; color: var(--muted); margin-bottom: 0.5rem;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; line-height: 1.4; }
.card.htm-doc.expanded .card-summary { -webkit-line-clamp: unset; display: block; overflow: visible; }
.card.htm-doc.expanded { box-shadow: 0 0 0 2px hsl(273,60%,55%); }
.progress-wrap { background: var(--border); height: 6px; border-radius: 3px; overflow: hidden; margin: 0.5rem 0; }
.progress-bar { height: 100%; background: hsl(140,60%,45%); transition: width 0.3s; }
.meta { font-size: 0.8em; color: var(--muted); display: flex; justify-content: space-between; }
/* Issue69: htm-doc 카드 actions 행 파일명 (열기 버튼 옆) */
.actions .doc-fname { font-size: 0.76em; color: var(--muted); align-self: center;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.actions { margin-top: 0.6rem; display: flex; gap: 0.4rem; }
.actions a, .actions button { font-size: 0.8em; padding: 0.3rem 0.6rem; border-radius: 4px; border: 1px solid var(--border); background: var(--bg); color: var(--fg); cursor: pointer; text-decoration: none; white-space: nowrap; flex-shrink: 0; }
.actions a:hover { background: var(--card); }
/* Issue169: 열기(↗) 이모지 버튼 + 🆚 세션 버튼 */
.actions .doc-open { font-size: 1em; line-height: 1; }
.actions .doc-sess { font-weight: 600; }
.actions .stop { background: #c33; color: white; border-color: #c33; }
.actions .stop:hover { background: #a22; }
.actions .approve-btn { background: #e8a020; color: white; border-color: #c8861a; font-weight: 600; }
.actions .approve-btn:hover { background: #c8861a; }
.actions .approve-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.actions .card-close { margin-left: auto; color: var(--muted); width: 1.7em; height: 1.7em; padding: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; line-height: 1; }
.actions .card-close:hover { background: #c33; color: white; border-color: #c33; }
.actions .card-close:disabled { opacity: 0.5; cursor: not-allowed; }
.empty { color: var(--muted); padding: 2rem; text-align: center; font-style: italic; }
.no-dash { color: var(--muted); font-style: italic; font-size: 0.9em; }
.error-bar { background: #fee; color: #800; padding: 0.5rem 0.9rem; border-radius: 4px; margin-bottom: 1rem; display: none; }
.hub-controls { display: flex; gap: 0.8rem; align-items: center; }
.hub-controls .btn-rescan { background: #36c; color: white; border: 1px solid #258; border-radius: 4px; padding: 0.3rem 0.7rem; font-size: 0.85em; cursor: pointer; }
.hub-controls .btn-rescan:hover { background: #258; }
.hub-controls .btn-rescan:disabled { background: var(--muted); border-color: var(--muted); cursor: not-allowed; }
.section-title .btn-zombie { margin-left: 0.6rem; background: #8a4; color: #fff; border: 1px solid #693; border-radius: 4px; padding: 0.2rem 0.6rem; font-size: 0.82em; cursor: pointer; font-weight: 600; }
.section-title .btn-zombie:hover { background: #693; }
.section-title .btn-zombie:disabled { background: var(--muted); border-color: var(--muted); cursor: not-allowed; }
.dash-section-bar { display: flex; align-items: center; justify-content: space-between; margin: 0.5rem 0 0.4rem; }
.dash-section-bar .section-title { margin: 0; }
.dash-controls { display: flex; gap: 0.8rem; align-items: center; }
.dash-controls label { font-size: 0.85em; color: var(--muted); }
.dash-controls select { background: var(--card); color: var(--fg); border: 1px solid var(--border); border-radius: 4px; padding: 0.2rem 0.4rem; font-size: 0.85em; }
.dash-controls .btn-clear { background: #d80; color: white; border: 1px solid #b60; border-radius: 4px; padding: 0.3rem 0.7rem; font-size: 0.85em; cursor: pointer; }
.dash-controls .btn-clear:hover { background: #b60; }
.dash-controls .btn-clear:disabled { background: var(--muted); border-color: var(--muted); cursor: not-allowed; }
.toast { position: fixed; bottom: 1.5rem; right: 1.5rem; background: #333; color: white; padding: 0.7rem 1rem; border-radius: 6px; font-size: 0.9em; opacity: 0; transition: opacity 0.2s; z-index: 1000; max-width: 360px; }
.toast.show { opacity: 0.95; }
.toast.err { background: #c33; }
.toast.ok { background: #2a8; }
.card.diff-recent { box-shadow: 0 0 0 2px var(--accent, hsl(220,60%,55%)); }
.sparkline { width: 100%; height: 24px; display: block; margin: 0.3rem 0; }
/* Issue32/Issue39: 가상 프로젝트 (system/___pm-tmp) 카드 — 점선 테두리 + view/stop 비활성 표시 */
.card.virtual { border-style: dashed; }
/* Issue56: htm-doc 가상 카드는 /htm-doc 으로 열람 가능(Issue50) → 링크 차단 제외.
   dashboard 가상 카드(token 미발급, /view 불가)만 링크 비활성. */
.card.virtual:not(.htm-doc) .actions a { pointer-events: none; opacity: 0.4; }
/* Issue33: live-session 별도 섹션 + 카드 좌측 그린 바 */
.section-title { margin: 2rem 0 0.9rem; font-size: 1.05em; color: var(--muted); display: flex; align-items: center; gap: 0.5rem; }
/* Issue63: 첫 섹션만 상단 margin 제거. 각 h2 가 section 의 first-child 라
   :first-child 를 쓰면 모든 섹션 제목이 margin-top:0 → 섹션 간 간격 소실.
   prj3#Issue438 후속: id 하드코딩(#live-sessions-section)이던 것을 구조 선택자로 교체.
   그 위에 핀봇 섹션이 새로 들어오자 live 가 더는 첫 섹션이 아닌데 규칙만 남아
   앞 섹션과 갭 0 으로 붙었다 — "첫 섹션"을 CSS 가 스스로 판정하게 한다. */
.hub-main > section:first-of-type > .section-title { margin-top: 0; }
.count-badge { background: var(--card); padding: 0.1rem 0.5rem; border-radius: 10px; font-size: 0.8em; border: 1px solid var(--border); }
.card.live { border-left: 3px solid hsl(140,60%,45%); }
/* Issue101: 활성 세션 카드 클릭 → VSCode 열기 (cdfv 효과). hover 로 클릭 가능 시각화 */
.card.live[data-cwd] { transition: box-shadow .12s, transform .12s; }
.card.live[data-cwd]:hover { box-shadow: 0 2px 10px rgba(0,0,0,.18); transform: translateY(-1px); }
/* Issue101: 프로젝트별 그룹 카드 — head 에 세션 수 배지, body 는 세션 topic 리스트 */
/* Issue284: live-badge 를 .name 밖 .head-right 로 이동(🗺️ 와 함께 우측 정렬) — 셀렉터에서 .name 제거 */
.card-head .live-badge { background: rgba(0,0,0,0.16); color: #1a1a1a; padding: 0.02rem 0.42rem; border-radius: 10px; font-size: 0.78em; font-weight: 600; }
/* Issue284: 이슈맵(Issue_map.htm) 바로가기 — 숫자 배지 왼쪽 */
.card-head .issue-map { text-decoration: none; font-size: 0.95em; line-height: 1; opacity: 0.85; }
.card-head .issue-map:hover { opacity: 1; transform: scale(1.15); }
/* Issue363: 맵이 Issue.md 보다 오래됨 — 열리기는 하되 '낡음' 을 시각적으로 고지 */
.card-head .issue-map.stale { filter: grayscale(0.6); opacity: 0.5; }
.card-head .issue-map.stale:hover { opacity: 0.85; }
.live-list { list-style: none; margin: 0; padding: 0; }
.live-item { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0; border-top: 1px solid var(--border); }
.live-item:first-child { border-top: none; }
.live-item .live-topic { flex: 1; min-width: 0; color: var(--fg); font-size: 0.9em; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.live-item.live-more .live-topic { color: var(--muted); font-style: italic; }
/* Issue104: "외 N개 더" 클릭 → 카드 확장. 초과 행은 기본 숨김, expanded 시 노출. more 행은 클릭 가능. */
.live-item.live-hidden { display: none; }
.card.live.expanded .live-item.live-hidden { display: flex; }
.live-item.live-more { cursor: pointer; border-radius: 5px; margin: 0 -0.25rem; padding-left: 0.25rem; padding-right: 0.25rem; transition: background .1s; }
.live-item.live-more:hover { background: rgba(127,127,127,.12); }
/* Issue131: 세션 행 클릭 → VSCode 세션 탭 포커스. 클릭 가능 시각화 */
.live-item[data-sid] { cursor: pointer; border-radius: 5px; margin: 0 -0.25rem; padding-left: 0.25rem; padding-right: 0.25rem; transition: background .1s; }
.live-item[data-sid]:hover { background: rgba(127,127,127,.12); }
/* Issue177: 세션 출처 배지 (🆚 VSCode / ⌨️ 터미널) — topic 앞 작은 아이콘 */
.live-origin { flex-shrink: 0; font-size: 0.82em; line-height: 1; opacity: 0.85; cursor: help; position: relative; }
/* Issue327: 에디터 로고 배지 — emoji 와 같은 광학 크기로 고정(배지 줄 높이 변화 0) */
.live-origin-ico { width: 1em; height: 1em; display: inline-block; vertical-align: -0.12em; border-radius: 2px; }
/* Issue273: 메인 세션 모델 신호등 배지 (🟣 opus / 🔵 sonnet / 🟢 haiku / 🟠 fable) — origin 배지 옆 */
.live-model { flex-shrink: 0; font-size: 0.78em; line-height: 1; cursor: help; margin-left: -0.25rem; position: relative; }
/* Issue221: 네이티브 title 툴팁은 브라우저가 지연(~1.5~2.5s) 소유·조정 불가 → data-tip 커스텀 툴팁으로 즉시 표시(지연 0)
   Issue281: CSS ::after(position:absolute)는 조상 .card{overflow:hidden}에 잘림 → #live-tip(position:fixed, body 직속)로 전환
   Issue369: nowrap 폐기 — 툴팁이 행 설명·sid 까지 싣게 되어 max-width 를 nowrap 이 무력화하면 화면을 넘는다.
   pre-line 으로 줄바꿈을 살리고, overflow-wrap:anywhere 로 공백 없는 sid(UUID)도 끊어 접는다 */
#live-tip { position: fixed; z-index: 3000; max-width: 340px; background: #222; color: #fff;
  padding: 4px 8px; border-radius: 5px; font-size: 11px; line-height: 1.35;
  white-space: pre-line; overflow-wrap: anywhere; text-align: left;
  box-shadow: 0 2px 8px rgba(0,0,0,.35); pointer-events: none; font-weight: 400; }
/* Issue369: 세션 ID 줄 — 본문과 구분되게 모노스페이스·디밍 */
#live-tip .tip-sid { display: block; margin-top: 2px; opacity: .75; font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
#live-tip[hidden] { display: none; }
/* Issue383: 📋 클릭 메뉴 — "복사할지 내용을 볼지" 를 명시적 2지선다로.
   종전 Issue300 은 같은 선택을 "녹색 상태에서 재클릭" 이라는 숨은 모드로 제공했는데,
   툴팁이 복사만 안내해 발견이 불가능했고 3초 타이머로 원복되면 그 모드도 사라졌다. */
#sid-menu { position: fixed; z-index: 3100; min-width: 168px; padding: 4px;
  background: var(--bg); color: var(--fg); border: 1px solid var(--border);
  border-radius: 7px; box-shadow: 0 4px 16px rgba(0,0,0,.28); font-size: 12px; }
#sid-menu[hidden] { display: none; }
#sid-menu button { display: flex; align-items: center; gap: 0.45rem; width: 100%;
  padding: 0.34rem 0.5rem; background: none; border: 0; border-radius: 5px;
  color: inherit; font: inherit; text-align: left; cursor: pointer; }
#sid-menu button:hover:not(:disabled) { background: rgba(127,127,127,.16); }
#sid-menu button:disabled { opacity: .38; cursor: default; }
/* 메뉴 머리 — 어느 세션에 대한 메뉴인지. 잘못된 행에 대고 누르는 사고 방지 */
#sid-menu .sid-menu-head { padding: 0.2rem 0.5rem 0.3rem; margin-bottom: 2px;
  border-bottom: 1px solid var(--border); opacity: .7; font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.live-item[data-origin="terminal"] { cursor: pointer; }
.live-item[data-origin="terminal"]:hover { background: rgba(127,127,127,.12); }
.live-acts { display: flex; align-items: center; gap: 0.3rem; flex-shrink: 0; }
.live-acts .approve-btn { background: #e8a020; color: #fff; border: 1px solid #c8861a; font-weight: 600; font-size: 0.76em; padding: 0.12rem 0.45rem; border-radius: 4px; cursor: pointer; }
.live-acts .approve-btn:hover { background: #c8861a; }
.live-acts .card-close { width: 1.5em; height: 1.5em; padding: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; border: 1px solid var(--border); background: var(--bg); color: var(--muted); cursor: pointer; font-size: 0.78em; line-height: 1; }
.live-acts .card-close:hover { background: #c33; color: #fff; border-color: #c33; }
/* Issue276: 세션 ID 복사 버튼 — X 왼쪽, 초록 hover/복사완료 피드백 */
.live-acts .copy-sid { width: 1.5em; height: 1.5em; padding: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; border: 1px solid var(--border); background: var(--bg); color: var(--muted); cursor: pointer; font-size: 0.72em; line-height: 1; }
.live-acts .copy-sid:hover { background: #2a9d5c; color: #fff; border-color: #2a9d5c; }
.live-acts .copy-sid.copied { background: #2a9d5c; color: #fff; border-color: #2a9d5c; }
.live-meta { font-size: 0.8em; color: var(--muted); margin: 0.2rem 0; }
.live-meta code { background: var(--code-bg); padding: 0.05rem 0.3rem; border-radius: 3px; font-size: 0.9em; }
/* Issue40: htm 스킬 단발 출력 카드 — 보라색 좌측 바 */
.card.htm-doc { border-left: 3px solid hsl(280,60%,55%); }
/* htm 문서 섹션 정리 버튼 */
.htm-btn { background: #c33; color: white; border: 1px solid #a22; border-radius: 4px;
  padding: 0.25rem 0.6rem; font-size: 0.78em; cursor: pointer; font-weight: normal; }
.htm-btn.keep { background: #d80; border-color: #b60; }
.htm-btn:hover { filter: brightness(0.9); }
.htm-btn:disabled { background: var(--muted); border-color: var(--muted); cursor: not-allowed; }
.htm-section-bar { margin: 2rem 0 0.9rem; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.htm-bar-left { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; flex: 1; min-width: 0; }
.htm-bar-right { display: flex; align-items: center; gap: 0.4rem; flex-shrink: 0; }
.htm-bar-title { font-size: 1.05em; color: var(--muted); font-weight: normal; margin: 0; }
.htm-filter-chips { display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: center; }
.htm-chip { display: inline-flex; align-items: center; gap: 0.2rem; background: hsl(220,55%,88%); color: hsl(220,55%,28%); border: 1px solid hsl(220,55%,72%); border-radius: 12px; padding: 0.1rem 0.45rem 0.1rem 0.6rem; font-size: 0.78em; white-space: nowrap; }
.htm-chip-rm { background: none; border: none; color: inherit; cursor: pointer; padding: 0; line-height: 1; opacity: 0.65; font-size: 0.85em; margin-left: 0.1rem; }
.htm-chip-rm:hover { opacity: 1; }
.htm-filter-sel { font-size: 0.78em; padding: 0.22rem 0.45rem; border: 1px solid var(--border); border-radius: 4px; background: var(--bg); color: var(--fg); cursor: pointer; }
.htm-prj-selected { outline: 2.5px solid hsl(220,80%,50%); outline-offset: -1px; }
/* Issue160: 섹션 접기/펼치기 토글 — 접힘 시 헤더(제목·카운트)만 남기고 본문·컨트롤 숨김 */
/* prj3#Issue438 ③: 핀봇 현황 카드 — 활성 봇만, 아이콘(종류별 동형 SVG)+색(개체별) */
.bot-card { background: var(--card); border: 1px solid var(--border); border-left: 4px solid var(--muted); border-radius: 8px; padding: 0.7rem 0.85rem; display: flex; gap: 0.7rem; align-items: flex-start; }
.bot-icon { width: 30px; height: 30px; flex-shrink: 0; border-radius: 50%; }
.bot-dot { width: 30px; height: 30px; flex-shrink: 0; border-radius: 50%; background: var(--muted); }
.bot-body { min-width: 0; flex: 1; }
.bot-name { font-weight: 600; font-size: 0.95em; display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.bot-role { font-size: 0.78em; color: var(--muted); border: 1px solid var(--border); border-radius: 3px; padding: 0 0.3rem; }
.bot-state { font-size: 0.82em; color: var(--muted); }
.bot-task { font-size: 0.85em; margin-top: 0.25rem; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.bot-task.none { color: var(--muted); font-style: italic; }
.bot-stale { color: #c62828; font-size: 0.78em; font-weight: 600; }
.bot-card.bot-err { border-left-color: #c62828; color: #c62828; font-size: 0.88em; display: block; }
/* Issue400: 활성 0 일 때의 유휴 요약 1줄. 카드와 같은 틀을 쓰되 한 줄로 눕는다 —
   섹션이 사라지면 "기능 사망" 과 "봇 유휴" 가 구분되지 않는다 */
.bot-card.bot-idle { border-left-color: var(--muted); color: var(--muted); font-size: 0.88em; display: block; grid-column: 1 / -1; }
.bot-card.bot-idle .bot-idle-sep { opacity: 0.5; margin: 0 0.45rem; }
/* Issue401(prj3#Issue444): 카드 클릭 → 세부 펼침. 활동 피드의 .feed-item.open 과
   동형 어휘를 쓴다 — hub 안에서 "클릭=펼침" 규칙이 갈리지 않게. */
.bot-card[data-bot] { cursor: pointer; }
.bot-card[data-bot]:focus-visible { outline: 2px solid #36c; outline-offset: 1px; }
.bot-detail { display: none; margin-top: 0.4rem; padding-top: 0.4rem;
  border-top: 1px dashed var(--border); font-size: 0.8em; color: var(--muted);
  white-space: pre-wrap; word-break: break-word; }
.bot-card.open .bot-detail { display: block; }
/* 펼치면 잘린 작업 전문이 복구된다 — 이것이 펼침의 주된 목적이다 */
.bot-card.open .bot-task { -webkit-line-clamp: unset; display: block; }
/* Issue402 ⓑⓒ: 루트 봇 단위 그룹. 그룹 자체가 .grid 의 한 칸이 되어 조직이 열로 선다.
   🗺 링크는 **그룹 헤더에만** 둔다 — 카드 본체 클릭은 Issue401 아코디언 소유다. */
.bot-group { display: flex; flex-direction: column; gap: 0.5rem; min-width: 0; }
.bot-group-head { display: flex; align-items: center; gap: 0.45rem; padding: 0.1rem 0.1rem 0.35rem; border-bottom: 1px solid var(--border); }
.bot-group-icon { width: 22px; height: 22px; }
.bot-group-name { font-weight: 700; font-size: 0.92em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bot-group-count { font-size: 0.76em; color: var(--muted); white-space: nowrap; }
.bot-map-link { margin-left: auto; text-decoration: none; font-size: 0.95em; opacity: 0.65; padding: 0 0.28rem; border-radius: 4px; line-height: 1.4; }
.bot-map-link:hover, .bot-map-link:focus-visible { opacity: 1; background: rgba(127,127,127,.16); }
#bots-map-all { margin-left: 0.15rem; }
/* 퇴근 봇 — 조직 구성원이라 지우지 않되, 카드로 세우면 홈이 명부가 된다 */
.bot-group-rest { display: flex; flex-wrap: wrap; gap: 0.28rem; }
.bot-chip { font-size: 0.76em; color: var(--muted); border: 1px solid var(--border); border-radius: 10px; padding: 0.02rem 0.45rem; white-space: nowrap; }
/* Issue405: 24h 이내 퇴근 — 테두리·본문색만 올린다. 배지를 새로 만들면 활성 카드와
   경쟁해 "지금 도는 봇" 이 묻힌다. 최신성만 보이면 충분하다. */
.bot-chip-recent { color: var(--fg); border-color: var(--accent, hsl(220,60%,55%)); }
.bot-chip-age { opacity: 0.72; }
.sec-toggle { background: none; border: 1px solid var(--border); border-radius: 4px; color: var(--muted); cursor: pointer; font-size: 0.8em; line-height: 1; padding: 0.15rem 0.4rem; flex-shrink: 0; }
.sec-toggle:hover { background: rgba(127,127,127,.12); color: var(--fg); }
section.sec-collapsed > .grid { display: none; }
section.sec-collapsed .btn-zombie,
section.sec-collapsed .dash-controls,
section.sec-collapsed .htm-filter-sel,
section.sec-collapsed .htm-filter-chips,
section.sec-collapsed .htm-bar-right { display: none; }
/* Issue42: 활동 피드 패널 (우측 1/3 aside) */
.hub-feed { flex: 1; min-width: 280px; max-width: 420px; align-self: stretch;
  position: sticky; top: 0; max-height: 100vh; overflow-y: auto;
  border: 1px solid var(--border); border-radius: 8px; background: var(--card); }
.hub-feed.hidden { display: none; }
.feed-head { display: flex; justify-content: space-between; align-items: center;
  gap: 0.3rem; padding: 0.6rem 0.5rem; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--card); z-index: 1; }
.feed-title-label { font-weight: 600; font-size: 0.95em; white-space: nowrap;
  min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.feed-actions { display: flex; gap: 0.2rem; align-items: center; flex-shrink: 0; }
#feed-toggle, #feed-collapse-all, #feed-keep, #feed-clear { background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
  cursor: pointer; padding: 0.2rem 0.4rem; font-size: 0.8em; color: var(--fg); white-space: nowrap; }
#feed-toggle:hover, #feed-collapse-all:hover, #feed-keep:hover { background: var(--code-bg); }
#feed-clear:hover { background: #fee2e2; border-color: #fca5a5; }
.feed-list { padding: 0.5rem; display: flex; flex-direction: column; gap: 0.4rem; }
.feed-empty { color: var(--muted); font-style: italic; text-align: center; padding: 1.5rem 0.5rem; font-size: 0.9em; }
.feed-item { border: 1px solid var(--border); border-left: 4px solid var(--muted);
  border-radius: 6px; background: var(--bg); overflow: hidden; }
.feed-item-head { display: flex; align-items: baseline; gap: 0.4rem; padding: 0.45rem 0.6rem; cursor: pointer; }
.feed-proj-emoji { flex: none; cursor: pointer; }
.feed-proj-emoji:hover { filter: brightness(1.4); }
.feed-title { font-weight: 600; color: var(--fg); cursor: pointer; text-decoration: none; flex: none; }
.feed-title:hover { text-decoration: underline; }
.feed-summary { color: var(--muted); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feed-age { flex: none; font-size: 0.78em; color: var(--muted); }
.feed-open { flex: none; color: #36c; text-decoration: none; font-size: 0.9em; padding: 0 0.1rem; }
.feed-open:hover { color: #1a4ea8; }
.feed-detail { display: none; padding: 0.45rem 0.65rem 0.6rem; border-top: 1px dashed var(--border);
  font-size: 0.82em; color: var(--muted); white-space: pre-wrap; word-break: break-word; }
.feed-item.open .feed-detail { display: block; }
.hub-controls .btn-feed-vis { background: var(--bg); border: 1px solid var(--border);
  border-radius: 4px; cursor: pointer; padding: 0.25rem 0.5rem; font-size: 0.95em; line-height: 1;
  transition: background 80ms, transform 80ms; }
.hub-controls .btn-feed-vis:hover { background: var(--code-bg); }
/* Issue279: 새 피드 도착 깜빡 프레임 — 배경 녹색 + 이모지 15% 확대 */
.hub-controls .btn-feed-vis.blinking { background: #22c55e; border-color: #16a34a; transform: scale(1.15); }
@media (max-width: 900px) {
  main { flex-direction: column; }
  .hub-main, .hub-feed { flex: none; width: 100%; }
  .hub-feed { max-width: none; position: static; max-height: 60vh; }
}
</style>
</head>
<body>
<header>
  {HUB_LOGO}
  <div class="header-text">
    <h1>fPm Hub<span id="hub-headline"></span></h1>
    <div class="sub" id="hub-important">{T:common.loading}</div>
  </div>
  <div class="header-actions">
    <!-- Issue420: aoa-mq 전용 페이지. Projects **왼쪽** 배치(사용자 지정). 링크로 두는 이유는
         새 탭 개방이 hub 셸의 탭 정책과 얽히지 않게 하기 위함 — 목록/처리는 독립 화면이 낫다. -->
    <a class="btn-project-list" id="btn-mq" href="/mq" target="_blank" rel="noopener"
       title="aoa-mq 예약 큐 — 필터·정렬·처리">📮 Aoa-mq</a>
    <button class="btn-project-list" id="btn-project-list" title="{T:projectList.openTitle}">📋 Projects</button>
    <a class="btn-project-list" id="btn-projects-map" href="/projects-map" target="_blank"
       data-title="Project Map" onclick="return fpmOpenInShell(event,this)"
       title="{T:projectsMap.openTitle}">🗺️ Map</a>
    <button class="btn-settings" id="btn-settings" title="{T:settings.openBtnTitle}">⚙️</button>
  </div>
</header>
<main>
<div class="hub-main">
<div class="status-bar">
  <span id="hub-stats">—</span>
  <span class="hub-controls">
    <span id="updated" style="font-size:0.85em;color:var(--muted)">—</span>
    <button class="btn-rescan" id="btn-rescan" title="{T:statusbar.rescanTitle}">{T:statusbar.rescan}</button>
    <button class="btn-feed-vis" id="feed-vis-toggle" title="{T:feed.visToggleTitle}">🙉</button>
  </span>
</div>
<div class="error-bar" id="error-bar"></div>
<section id="bots-section" style="display:none">
  <h2 class="section-title"><button class="sec-toggle" data-sec="bots-section" title="{T:common.collapseSection}">▾</button>{T:bots.title} <span id="bots-count" class="count-badge"></span><span id="bots-scope" class="bot-scope" style="margin-left:6px;font-size:.72em;font-weight:400;opacity:.6"></span> <a class="bot-map-link" id="bots-map-all" href="/fbot-map" target="_blank" rel="noopener" title="{T:bots.mapAllTitle}">🗺</a></h2>
  <div class="grid" id="bots-grid"></div>
</section>
<section id="live-sessions-section" style="display:none">
  <h2 class="section-title"><button class="sec-toggle" data-sec="live-sessions-section" title="{T:common.collapseSection}">▾</button>{T:liveSessions.title} <span id="live-count" class="count-badge"></span><button class="btn-zombie" id="btn-zombie" title="{T:liveSessions.zombieTitle}">{T:liveSessions.zombie}</button></h2>
  <div class="grid" id="live-grid"></div>
</section>
<section id="dashboard-section" style="display:none">
  <div class="dash-section-bar">
    <h2 class="section-title"><button class="sec-toggle" data-sec="dashboard-section" title="{T:common.collapseSection}">▾</button>📊 dashboard</h2>
    <span class="dash-controls">
      <label>filter: <select id="filter-status">
        <option value="all" selected>{T:dashboard.filter.all}</option>
        <option value="running">{T:dashboard.filter.running}</option>
        <option value="done">done</option>
        <option value="stopped">stopped</option>
      </select></label>
      <label>sort: <select id="sort-by">
        <option value="recent">{T:dashboard.sort.recent}</option>
        <option value="name">{T:dashboard.sort.name}</option>
        <option value="progress">{T:dashboard.sort.progress}</option>
      </select></label>
      <button class="btn-clear" id="btn-clear-done" title="{T:dashboard.clearTitle}">{T:dashboard.clear}</button>
    </span>
  </div>
  <div class="grid" id="grid"><div class="empty">{T:common.loading}</div></div>
</section>
<section id="htm-docs-section" style="display:none">
  <div class="htm-section-bar">
    <div class="htm-bar-left">
      <button class="sec-toggle" data-sec="htm-docs-section" title="{T:common.collapseSection}">▾</button>
      <span class="htm-bar-title">{T:htmDocs.title} <span id="htm-count" class="count-badge"></span></span>
      <select id="htm-prj-filter" class="htm-filter-sel" title="{T:htmDocs.filterTitle}"><option value="">{T:htmDocs.filterAdd}</option></select>
      <div class="htm-filter-chips" id="htm-filter-chips"></div>
    </div>
    <div class="htm-bar-right">
      <button class="htm-btn keep" id="btn-htm-keep" title="{T:htmDocs.keepTitle}">{T:htmDocs.keep}</button>
      <button class="htm-btn" id="btn-htm-clear" title="{T:htmDocs.clearTitle}">{T:htmDocs.clear}</button>
    </div>
  </div>
  <div class="grid" id="htm-grid"></div>
</section>
</div>
<aside class="hub-feed" id="hub-feed">
  <div class="feed-head">
    <span class="feed-title-label">{T:feed.title} <span id="feed-count" class="count-badge"></span></span>
    <span class="feed-actions">
      <button id="feed-collapse-all" title="{T:feed.collapseAllTitle}">⊟</button>
      <button id="feed-keep" title="{T:feed.keepTitle}">{T:feed.keep}</button>
      <button id="feed-clear" title="{T:feed.clearTitle}">{T:feed.clear}</button>
    </span>
  </div>
  <div class="feed-list" id="feed-list"><div class="feed-empty">{T:common.loading}</div></div>
</aside>
</main>
<div class="toast" id="toast"></div>
<div class="modal-backdrop" id="pl-modal" hidden>
  <div class="modal" role="dialog" aria-modal="true" aria-label="Project List">
    <div class="modal-head">
      <span class="modal-title">📋 Project List</span>
      <button class="modal-close" id="pl-close" title="{T:settings.close}" aria-label="{T:common.close}">✕</button>
    </div>
    <div class="modal-body" id="pl-body"><div class="empty">{T:common.loading}</div></div>
    <div class="modal-foot">
      <span id="pl-foot-status">{T:projectList.footStatus}</span>
      <button class="pl-edit-btn" id="pl-edit" title="{T:projectList.openSelectedTitle}">{T:projectList.openVscode}</button>
    </div>
  </div>
</div>
<div class="modal-backdrop" id="cf-modal" hidden>
  <div class="modal" role="dialog" aria-modal="true" aria-label="{T:common.confirm}" style="width:min(440px,92vw)">
    <div class="modal-head">
      <span class="modal-title">{T:common.confirmTitle}</span>
      <button class="modal-close" id="cf-x" title="{T:common.cancelEsc}" aria-label="{T:common.cancel}">✕</button>
    </div>
    <div class="modal-body"><p id="cf-msg" style="white-space:pre-line;line-height:1.65;margin:0"></p></div>
    <div class="modal-foot" style="justify-content:flex-end;gap:0.5rem">
      <button class="cf-btn cf-cancel" id="cf-cancel">{T:common.cancel}</button>
      <button class="cf-btn cf-ok" id="cf-ok">{T:common.proceed}</button>
    </div>
  </div>
</div>
<div class="modal-backdrop" id="set-modal" hidden>
  <div class="modal" role="dialog" aria-modal="true" aria-label="{T:settings.title}" style="width:min(960px,92vw)">
    <div class="modal-head">
      <span class="modal-title" data-i18n="settings.title">{T:settings.title}</span>
      <span style="display:inline-flex;align-items:center">
        <span class="set-lang" id="set-lang">
          <button type="button" data-lang="ko">KO</button>
          <button type="button" data-lang="en">EN</button>
        </span>
        <button class="modal-close" id="set-close" title="{T:settings.close}" aria-label="{T:settings.close}">✕</button>
      </span>
    </div>
    <div class="set-tabs" id="set-tabs">
      <button class="set-tab active" data-tab="basic" data-i18n="settings.tab.basic">{T:settings.tab.basic}</button>
      <button class="set-tab" data-tab="session" data-i18n="settings.tab.session">{T:settings.tab.session}</button>
      <button class="set-tab" data-tab="advanced" data-i18n="settings.tab.advanced">{T:settings.tab.advanced}</button>
    </div>
    <div class="modal-body">
      <div class="set-pane active" data-pane="basic" id="set-pane-basic"></div>
      <div class="set-pane" data-pane="session" id="set-pane-session"></div>
      <div class="set-pane" data-pane="advanced" id="set-pane-advanced">
        <div class="set-warn" data-i18n="settings.advancedWarn">{T:settings.advancedWarn}</div>
      </div>
    </div>
    <div class="modal-foot" style="gap:0.5rem">
      <button class="pl-edit-btn" id="set-open-file" title="{T:settings.openFileTitle}" style="background:#555;border-color:#444" data-i18n="settings.openFile">{T:settings.openFile}</button>
      <span style="flex:1 1 auto"></span>
      <button class="cf-btn cf-cancel" id="set-cancel" data-i18n="settings.cancel">{T:settings.cancel}</button>
      <button class="set-ok-btn" id="set-save" data-i18n="settings.save">{T:settings.save}</button>
    </div>
  </div>
</div>
<div id="set-tip" hidden></div>
<div id="live-tip" hidden></div>
<div id="sid-menu" hidden></div>
<script>
// Issue169 Stage8: 클라이언트 i18n — 서버가 주입한 사전(window.__i18n)·언어(window.__lang).
//   t(key, vars): 사전 조회 후 {var} 보간. 누락 키 → key 자체(가시화). vars 값은 그대로 삽입(호출부에서 escape).
window.__lang = "{I18N_LANG}";
window.__i18n = {I18N_JSON};
window.__i18n_all = {I18N_ALL_JSON};   // {ko:{...}, en:{...}} — 모달 KO/EN 뷰 토글 라이브 재번역용
function t(key, vars) {
  let s = (window.__i18n && window.__i18n[key]) || key;
  if (vars) for (const k in vars) s = s.split('{' + k + '}').join(vars[k]);
  return s;
}
const grid = document.getElementById('grid');
const updated = document.getElementById('updated');
const hubStats = document.getElementById('hub-stats');
const errorBar = document.getElementById('error-bar');
// Issue24 Phase 5: hub UX — filter/sort/diff highlight/sparkline 상태
const filterSel = document.getElementById('filter-status');
const sortSel = document.getElementById('sort-by');
let lastSnap = {};        // {key: {progress, mtime}} — diff highlight 용 직전 snapshot
let progressHist = {};    // {key: [n1, n2, ...]} — sparkline 용 진행률 히스토리 (max 20)
let allHtmDocs = [];                   // htm 전체 목록 (프로젝트 필터용)
let htmSelectedProjects = new Set();  // 선택된 프로젝트 복수 필터
const htmPrjFilter = document.getElementById('htm-prj-filter');

function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function dashKey(p, d) { return p.cwd_hash + ':' + d.path; }

function sparkSvg(series) {
  if (!series || series.length < 2) return '';
  const W = 200, H = 24, pad = 1;
  const min = Math.min(...series, 0), max = Math.max(...series, 100);
  const range = max - min || 1;
  const stepX = (W - pad * 2) / (series.length - 1);
  const pts = series.map((v, i) => `${pad + i * stepX},${H - pad - ((v - min) / range) * (H - pad * 2)}`).join(' ');
  return `<svg class="sparkline" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="hsl(140,60%,45%)" stroke-width="1.5"/></svg>`;
}

async function reload() {
  try {
    const r = await fetch('/boards?_=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    // Issue378: 표면 자기교정. 모드가 hub-internal 로 바뀌면 이 standalone /hub 는 무효
    //   표면이 되므로 쉘로 자기이동한다(Issue377 302 는 새 요청에만 걸려 떠 있는 탭 미교정).
    //   ⚠️ embed 가드 필수 — /hub 는 쉘의 home 탭 iframe(/hub?_shell=1)으로도 로드된다.
    //   거기서 이동시키면 iframe 안에 쉘이 다시 뜨는 중첩 재귀(Issue203)가 재발한다.
    if (window.top === window.self && data.render_tab_mode === 'hub-internal') {
      location.replace('/hub-shell');
      return;
    }
    errorBar.style.display = 'none';
    renderProjects(data.projects || []);
    BOTS_ERROR = data.bots_error || '';
    renderBots(data.bots || [], data.bots_total || 0, data.bots_today || {},
               data.bots_roster || []);
    // prj3#Issue461 — 관측 범위 표기. 값이 없으면 아무것도 쓰지 않는다(거짓 한정 금지)
    const scopeEl = document.getElementById('bots-scope');
    if (scopeEl) scopeEl.textContent = data.bots_scope ? ('· ' + data.bots_scope) : '';
    renderLiveSessions(data.live_sessions || [], data.live_session_limit, data.live_session_copy_button);
    renderHtmDocs(data.htm_docs || []);
    FEED_BLINK_ON_NEW = data.feed_blink_on_new !== false;  // Issue279: 기본 on
    renderFeed(data.hook_feed || []);
    renderHeadline(data.hook_feed || []);
    renderImportant(data.important_events || []);
    const dashCount = (data.projects || []).reduce((s,p)=>s+p.dashes.length,0);
    // dashboard 0건이면 섹션(헤더 포함) 숨김
    document.getElementById('dashboard-section').style.display = dashCount > 0 ? '' : 'none';
    const liveCount = (data.live_sessions || []).length;
    const htmCount = (data.htm_docs || []).length;
    // Issue352: hub OFF 배지. off 는 "새 렌더 중단"이지 "과거 문서 숨김"이 아니므로
    //   목록은 그대로 두고 상태만 표시한다 (빈 페이지로 덮지 않음).
    const offCount = data.hub_off_count || 0, offTotal = data.hub_off_total || 0;
    const offTxt = data.hub_system_off ? ' · ⏸ hub OFF (system)'
                 : (offCount ? ` · ⏸ ${offCount}/${offTotal} hub OFF` : '');
    if (hubStats) hubStats.textContent = `${(data.projects||[]).length} project · ${dashCount} dashboard · ${liveCount} live session · ${htmCount} hub doc` + offTxt;
    updated.textContent = t('statusbar.updated', {time: new Date().toLocaleTimeString()});
  } catch (e) {
    errorBar.textContent = '❌ ' + e.message;
    errorBar.style.display = 'block';
  }
}

// Issue104: "외 N개 더" 로 확장된 카드의 cwd 집합. 5초 reload() 재렌더에도 확장 상태 유지.
const expandedCards = new Set();
// Issue33: SSE alive + 최근 갱신 session 노출 (별도 섹션)
function renderLiveSessions(list, limit, showCopy) {
  // Issue277: showCopy 미정의(구 payload)면 기본 표시(true). false 일 때만 복사 버튼 숨김.
  showCopy = (showCopy !== false);
  const sec = document.getElementById('live-sessions-section');
  const lg = document.getElementById('live-grid');
  const lc = document.getElementById('live-count');
  if (!list || !list.length) { sec.style.display = 'none'; lg.innerHTML = ''; return; }
  sec.style.display = '';
  lc.textContent = list.length;
  // Issue129: 카드(프로젝트 그룹)당 세션 행 상한. 0/누락 시 무제한. 초과분은 "외 N개 더" 요약 행.
  const lim = (typeof limit === 'number' && limit > 0) ? limit : Infinity;
  // Issue101: 프로젝트(cwd)별로 세션을 묶어 1카드 = 1프로젝트. 카드 body 는 세션 topic 리스트.
  //   같은 프로젝트가 여러 카드로 흩어지던 문제 해결 — 눈으로 찾을 필요 없음.
  const groups = new Map();
  for (const s of list) {
    const key = s.cwd || s.name;
    if (!groups.has(key)) groups.set(key, {cwd: s.cwd, name: s.name, color: s.color, emoji: s.emoji, issueMap: false, issueMapStale: false, openIssueCount: 0, items: []});
    const g = groups.get(key);
    g.items.push(s);
    // Issue284: 그룹 내 한 세션이라도 이슈맵 보유면 카드에 🗺️ 노출
    if (s.issue_map) g.issueMap = true;
    // Issue363: 같은 cwd 라 값은 동일 — 맵이 Issue.md 보다 낡았으면 아이콘을 흐리게
    if (s.issue_map_stale) g.issueMapStale = true;
    // Issue316: 같은 cwd 세션은 동일 값 — 그대로 그룹에 복사(마지막 세션 값으로 덮여도 동일).
    g.openIssueCount = s.open_issue_count || 0;
  }
  const rowHtml = (s, extraCls) => {
    // Issue66: 큐 dashboard(supervisor_pid 존재)는 graceful remove, 일반은 stop
    // Issue369: 행 툴팁이 커스텀(#live-tip)으로 바뀐 이상 자식 버튼에 네이티브 title 을 남기면 둘이 겹쳐 뜬다 → 전부 data-tip 통일
    const killBtn = s.pid
      ? (s.supervisor_pid
          ? `<button class="card-close" onclick="removeQueueDash('${escapeHtml(s.cwd)}','${escapeHtml(s.token)}',${s.supervisor_pid},'${escapeHtml(s.sid)}',this)" data-tip="${escapeHtml(t('liveSessions.removeQueueTitle', {pid: s.supervisor_pid}))}" aria-label="remove">✕</button>`
          : `<button class="card-close" onclick="stopRunner('${escapeHtml(s.cwd)}','${escapeHtml(s.token)}',${s.pid},this)" data-tip="${escapeHtml(t('liveSessions.killRunnerTitle', {pid: s.pid}))}" aria-label="kill">✕</button>`)
      // Issue132: pid 없는 live(claude) 세션 — dismiss 버튼(프로세스 kill 아님, 카드만 제거)
      : `<button class="card-close" onclick="dismissSession('${escapeHtml(s.cwd)}','${escapeHtml(s.token)}','${escapeHtml(s.sid)}',this)" data-tip="${escapeHtml(t('liveSessions.dismissTitle'))}" aria-label="dismiss">✕</button>`;
    // Issue276: 세션 ID 복사 버튼 (X 왼쪽). /cc-session id 없이 hub 에서 바로 sid 확보.
    //   sid 없는 행(가상/집계)은 미표시. 클릭 위임은 closest('button,a') 로 제외되어 행-클릭 미발동.
    const copyBtn = (s.sid && showCopy)
      // Issue383: 클릭 → 즉시 복사가 아니라 2지선다 메뉴(복사 / 내용 보기).
      // Issue384: hover 툴팁을 걷어낸다. 툴팁이 "복사 / 내용 보기" 라는 선택지를 미리 보여 주는 바람에
      //   이미 열린 메뉴로 읽혔는데, 정작 pointer-events:none 이라 고르려고 마우스를 가져가면
      //   버튼을 벗어나 사라졌다. 같은 자리에 진짜 메뉴를 띄우는 쪽이 맞다(sid 는 메뉴 머리에 있다).
      ? `<button class="copy-sid" onclick="sidMenuOpen(this)" aria-haspopup="menu" aria-label="${escapeHtml(t('liveSessions.sidMenuTitle'))}">📋</button>`
      : '';
    // Issue66 Phase 7: 큐 dashboard 에 waiting_approval 항목이 있으면 승인 버튼
    const approveBtn = (s.supervisor_pid && s.waiting_approval_item)
      ? `<button class="approve-btn" onclick="approveQueueItem('${escapeHtml(s.cwd)}','${escapeHtml(s.token)}','${escapeHtml(s.sid)}','${escapeHtml(s.waiting_approval_item)}',this)" data-tip="${escapeHtml(t('liveSessions.approveTitle', {item: s.waiting_approval_item}))}">▶ ${escapeHtml(s.waiting_approval_item)}</button>`
      : '';
    // Issue129: 명령(프롬프트) 전 세션은 title 없음 → "-" 표기 (기존 content_type/'response' fallback 폐기)
    const topic = s.title || '-';
    // Issue177: 세션 출처 배지 — VSCode(🆚) vs 터미널(⌨️). origin 은 서버가 capabilities.entrypoint 로 판정.
    //   터미널 세션은 클릭해도 VSCode 재오픈 안 함(아래 위임 핸들러 분기). data-origin 으로 핸들러에 전달.
    // Issue327: 3값 — vscode|zed 는 실제 앱 로고 이미지, terminal 은 emoji(앱이 아니므로 로고 없음).
    //   아이콘 404(에디터 미설치 등)면 onerror 로 emoji 폴백 → 배지가 비지 않는다.
    const origin = (s.origin === 'vscode' || s.origin === 'zed') ? s.origin : 'terminal';
    // Issue221: title→data-tip (커스텀 CSS 툴팁, 지연 0). CSS .live-origin[data-tip]:hover::after
    const ORIGIN_META = {
      vscode: {tip: 'VSCode 세션 — 클릭 시 탭 포커스', fallback: '🆚'},
      zed:    {tip: 'Zed 세션 — 클릭 시 워크스페이스 열기(세션 복귀 불가)', fallback: '🅩'},
    };
    const originBadge = ORIGIN_META[origin]
      ? `<span class="live-origin ${origin}" data-tip="${escapeHtml(ORIGIN_META[origin].tip)}">`
        + `<img class="live-origin-ico" src="/editor-icon/${origin}.png" alt="${origin}"`
        + ` onerror="this.replaceWith(document.createTextNode('${ORIGIN_META[origin].fallback}'))"></span>`
      : `<span class="live-origin term" data-tip="터미널 세션(CLI) — 클릭 시 대화 내용 보기(뷰어)">⌨️</span>`;
    // Issue273: 메인 세션 모델 신호등 배지 — 🟣 opus / 🔵 sonnet / 🟢 haiku / 🟠 fable. 미상→무표시.
    const modelDot = {opus:'🟣', sonnet:'🔵', haiku:'🟢', fable:'🟠'}[s.model_tier] || '';
    const modelBadge = modelDot
      ? `<span class="live-model" data-tip="모델: ${escapeHtml(s.model_id || s.model_tier)}">${modelDot}</span>`
      : '';
    // Issue131: 행 클릭 → 해당 Claude Code 세션 탭 포커스 (data-sid·data-cwd). 툴팁으로 전체 표시(ellipsis 보완).
    // Issue104: extraCls 로 초과 행에 live-hidden 부여 (접힘 상태 기본 숨김).
    // Issue369: 행도 네이티브 title → data-tip. 네이티브를 남겨 두면 자식(📋) 위에서도 조상 title 이 커서 옆에 떠
    //   커스텀 툴팁과 이중으로 겹친다.
    // Issue373: 행 툴팁에는 sid 를 붙이지 않는다 — sid 병기는 📋(.copy-sid) 의 역할이다.
    //   제목 hover 는 "무슨 세션인가"(topic)만 알면 되고, 36자 uuid 는 읽히지 않는 소음이다.
    const cls = 'live-item' + (extraCls ? ' ' + extraCls : '');
    return `<li class="${cls}" data-sid="${escapeHtml(s.sid)}" data-cwd="${escapeHtml(s.cwd)}" data-origin="${origin}" data-url="${escapeHtml(s.url || '')}" data-tip="${escapeHtml(t('liveSessions.topicTitle', {topic: topic}))}">${originBadge}${modelBadge}<span class="live-topic">${escapeHtml(topic)}</span><span class="live-acts">${approveBtn}${copyBtn}${killBtn}</span></li>`;
  };
  const cards = [...groups.values()].map(g => {
    // Issue129/Issue104: limit 초과 시 첫 (lim-1)개는 표시, 초과분은 live-hidden 으로 렌더(잘라내지 않음)
    //   + "외 N개 더" 토글 행. 클릭 시 expanded 토글로 초과 행을 펼침. 이하면 전체 표시.
    let rows;
    if (g.items.length > lim) {
      const visible = g.items.slice(0, lim - 1).map(s => rowHtml(s)).join('');
      const hidden = g.items.slice(lim - 1).map(s => rowHtml(s, 'live-hidden')).join('');
      const more = g.items.length - (lim - 1);
      const expanded = expandedCards.has(g.cwd);
      const label = expanded ? t('liveSessions.collapse') : t('liveSessions.moreCount', {n: more});
      const moreRow = `<li class="live-item live-more" data-action="toggle-more" data-more="${more}"><span class="live-topic">${label}</span></li>`;
      rows = visible + hidden + moreRow;
    } else {
      rows = g.items.map(s => rowHtml(s)).join('');
    }
    // Issue104: expandedCards 에 cwd 가 있으면 expanded 클래스로 초과 행 노출 (5초 reload 재렌더 시 상태 유지).
    const expCls = expandedCards.has(g.cwd) ? ' expanded' : '';
    // Issue101: 카드 클릭 → VSCode 열기(cdfv). 리스트 항목 버튼은 위임 핸들러가 closest('button,a') 로 제외.
    // Issue284: 이슈맵 보유 프로젝트만 🗺️ 렌더(미보유는 아이콘 자체 없음 — 빈 아이콘·404 금지).
    //   서버가 cwd 로 경로를 재계산하므로 링크는 cwd 만 전달. 카드 클릭(VSCode 열기)은
    //   위임 핸들러가 closest('button,a') 로 제외하므로 <a> 만으로 충돌 없음.
    // Issue363: stale(맵이 Issue.md 보다 오래됨) 이면 흐린 아이콘 + 전용 툴팁. 링크는 그대로 —
    //   낡은 맵도 여는 것이 못 여는 것보다 낫고, 재생성 방법은 툴팁이 안내한다.
    //   ⚠️ t() 인자는 **리터럴로** 둔다 — test_i18n_parity.py 의 참조 키 스캔이
    //   `t('네임스페이스.키')` 정규식이라, 삼항을 t() 안에 넣으면 두 키 모두 검사에서 샌다.
    const mapTitle = g.issueMapStale ? t('liveSessions.issueMapStaleTitle')
                                     : t('liveSessions.issueMapTitle');
    const mapLink = g.issueMap
      ? `<a class="issue-map${g.issueMapStale ? ' stale' : ''}" href="/issue-map?cwd=${encodeURIComponent(g.cwd)}" target="_blank" data-title="${escapeHtml(g.name)} — Issue Map" onclick="return fpmOpenInShell(event,this)" title="${escapeHtml(mapTitle)}">🗺️</a>`
      : '';
    return `<div class="card live${expCls}" data-cwd="${escapeHtml(g.cwd)}" title="{T:common.openVscodeTitle}">
      <div class="card-head" style="background:${escapeHtml(g.color)}">
        <span class="name">${escapeHtml(g.emoji || '📁')} ${escapeHtml(g.name)}</span>
        <span class="head-right">${mapLink}<span class="live-badge" data-tip="미완료 이슈 ${g.openIssueCount}개 · 세션 ${g.items.length}개">${g.openIssueCount}</span></span>
      </div>
      <!-- Issue384: title="" 로 카드의 네이티브 title 상속을 끊는다. 카드에 붙은 title(위 .card.live)은
           세션 행 위에서도 커서 옆에 떠, 행·버튼의 커스텀 툴팁·메뉴와 이중으로 겹쳤다(Issue369 가
           자식에서 없앤 겹침이 조상 레벨로 남아 있었다). 행별 안내는 .live-item[data-tip] 이 더 정확하다. -->
      <div class="card-body"><ul class="live-list" title="">${rows}</ul></div>
    </div>`;
  });
  lg.innerHTML = cards.join('');
}

// Issue276: 세션 ID 클립보드 복사. isSecureContext 가드 + execCommand fallback + prompt 최종 폴백.
//   HTTP 비-localhost(host-1.local 등 insecure context)에선 navigator.clipboard 미정의 → execCommand 경유.
// Issue300(숨은 기능): 복사 직후 ✓ 녹색(.copied) 상태에서 한 번 더 클릭하면 그 세션의
//   VSCode 세션 탭으로 이동한다(POST /open-session — Projects_map 활성 세션 🟢 아이콘과 동일 동작).
//   버튼을 늘리지 않고 세션 이동을 얹기 위한 2단 클릭. 녹색 유지 시간은 두 번째 클릭 여유를
//   위해 1.2s → 3s. 문서: noteForHuman.md "숨은 기능".
//   ⚠️ origin=terminal 세션은 VSCode 로 포커스 불가(Issue177) → JSONL transcript 뷰어로 폴백.
// Issue383: 📋 클릭 2지선다 메뉴. Issue300 의 "녹색 재클릭 = 세션 이동" 숨은 모드를 대체한다
//   (기능 제거가 아니라 같은 선택을 발견 가능한 형태로 승격 — 그쪽은 툴팁이 복사만 안내해
//    아무도 찾을 수 없었고, 3초 타이머로 원복되면 선택지 자체가 사라졌다).
const sidMenu = document.getElementById('sid-menu');
function sidMenuClose() { sidMenu.hidden = true; sidMenu.innerHTML = ''; sidMenu.dataset.sid = ''; }
function sidMenuOpen(btn) {
  const row = btn.closest('.live-item[data-sid]');
  if (!row) return;
  const sid = row.dataset.sid || '';
  // Issue384: 같은 세션 메뉴가 이미 열려 있으면 아무것도 하지 않는다(멱등).
  //   ① hover 로 열리게 된 이상 "재호출 = 토글" 은 성립하지 않는다 — 5초 reload 가 행을 다시 그리면
  //      커서 아래에서 mouseover 가 재발화하는데, 그때 토글로 닫으면 마우스를 올려둔 채 메뉴가 저 혼자 깜빡인다.
  //   ② 다른 세션 버튼으로 옮겨 간 경우는 아래로 흘러 그 세션 메뉴로 교체된다.
  if (!sidMenu.hidden && sidMenu.dataset.sid === sid) return;
  liveTipHide();                                      // 툴팁과 겹쳐 뜨지 않게
  const url = row.dataset.url || '';
  const topicEl = row.querySelector('.live-topic');
  const topic = topicEl ? topicEl.textContent : '세션';
  // url 이 빈 세션(transcript 미해석)은 항목을 비활성 — 눌러도 아무 일 없는 항목을
  // 살아 있는 것처럼 두지 않는다. 이유는 title 로 노출한다.
  const viewDisabled = url ? '' : ' disabled title="' + escapeHtml(t('liveSessions.sidMenuViewNoUrl')) + '"';
  sidMenu.innerHTML =
      `<div class="sid-menu-head">${escapeHtml(sid)}</div>`
    + `<button type="button" data-act="copy">📋 <span>${escapeHtml(t('liveSessions.sidMenuCopy'))}</span></button>`
    + `<button type="button" data-act="view"${viewDisabled}>👁 <span>${escapeHtml(t('liveSessions.sidMenuView'))}</span></button>`;
  sidMenu.hidden = false;
  sidMenu.dataset.sid = sid;   // Issue384: 어느 세션 메뉴인지 — 리렌더 후 멱등 판정의 기준
  // 위치: 버튼 아래 정렬. 화면 밖으로 나가면 안쪽으로 당기고, 아래 공간이 없으면 위로.
  const br = btn.getBoundingClientRect(), mr = sidMenu.getBoundingClientRect(), gap = 6;
  let left = Math.min(br.left, window.innerWidth - mr.width - 8);
  let top = br.bottom + gap;
  if (top + mr.height > window.innerHeight - 8) top = Math.max(8, br.top - mr.height - gap);
  sidMenu.style.left = Math.max(8, left) + 'px';
  sidMenu.style.top = top + 'px';
  sidMenu.onclick = e => {
    const b = e.target.closest('button[data-act]');
    if (!b || b.disabled) return;
    const act = b.dataset.act;
    sidMenuClose();
    if (act === 'copy') copySid(sid, btn);
    // Issue383 핵심: origin 무관하게 뷰어. 종전에는 terminal 만 뷰어이고 vscode·zed 는
    //   에디터 탭 포커스로 빠져 브라우저에서 대화 내용을 볼 경로가 아예 없었다.
    else if (act === 'view') openSessionViewer(url, topic);
  };
}
// 바깥 클릭·ESC·스크롤로 닫기 (capture 로 먼저 받아 행-클릭 위임보다 앞서 처리)
document.addEventListener('mousedown', e => {
  if (sidMenu.hidden) return;
  if (e.target.closest('#sid-menu') || e.target.closest('.copy-sid')) return;
  sidMenuClose();
}, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !sidMenu.hidden) sidMenuClose(); });
window.addEventListener('scroll', () => { if (!sidMenu.hidden) sidMenuClose(); }, true);
// Issue384: hover 로 연다. 클릭 전용이던 종전(Issue383)에는 같은 자리 툴팁이 선택지를 미리 보여 줘
//   "떠 있는 메뉴" 로 읽혔고, 그리로 마우스를 가져가면 버튼을 벗어나 사라져 고를 수가 없었다.
//   클릭 경로는 그대로 살려 둔다 — 터치·키보드(포커스+Enter)에는 hover 가 없다.
const SID_HOVER_IN = 220;    // hover intent — 지나가다 스친 것만으로 열리지 않게 하는 지연
const SID_HOVER_OUT = 260;   // 버튼 → 메뉴 사이 간격(gap 6px)을 건너는 동안의 유예
let sidOpenTimer = null, sidCloseTimer = null;
document.addEventListener('mouseover', e => {
  const btn = e.target.closest('.copy-sid');
  if (btn) {
    clearTimeout(sidOpenTimer); clearTimeout(sidCloseTimer);
    sidOpenTimer = setTimeout(() => sidMenuOpen(btn), SID_HOVER_IN);
  } else if (e.target.closest('#sid-menu')) {
    clearTimeout(sidCloseTimer);   // 메뉴 위에 있는 동안은 닫지 않는다
  }
});
document.addEventListener('mouseout', e => {
  if (!e.target.closest('.copy-sid, #sid-menu')) return;
  // 버튼 ↔ 메뉴 사이의 이동은 이탈이 아니다. 이 브리지가 빠지면 고르러 가는 도중에 닫혀
  //   Issue384 가 고치려던 바로 그 증상(가져가면 사라짐)이 메뉴 쪽에서 재발한다.
  const rt = e.relatedTarget;
  if (rt && rt.closest && rt.closest('.copy-sid, #sid-menu')) return;
  clearTimeout(sidOpenTimer); clearTimeout(sidCloseTimer);
  sidCloseTimer = setTimeout(sidMenuClose, SID_HOVER_OUT);
});

function copySid(sid, btn) {
  function ok() {
    if (!btn) return;
    const orig = btn.textContent;
    btn.textContent = '✓';
    btn.classList.add('copied');
    if (btn._sidTimer) clearTimeout(btn._sidTimer);
    btn._sidTimer = setTimeout(() => {
      btn.textContent = orig; btn.classList.remove('copied'); btn._sidTimer = null;
    }, 3000);
  }
  function fb() {
    try {
      const ta = document.createElement('textarea');
      ta.value = sid; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.focus(); ta.select();
      const r = document.execCommand('copy');
      document.body.removeChild(ta);
      if (r) { ok(); return; }
    } catch (_) {}
    window.prompt(t('liveSessions.copySidTitle'), sid);
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(sid).then(ok).catch(fb);
  } else { fb(); }
}

// Issue194: hub-shell(/hub-shell) iframe 안에서 열렸으면 카드 열기(↗) 클릭을
//   부모 쉘 내부 탭으로 라우팅(새 OS 탭 미생성). 비임베드(직접 /hub)면 기존 새 탭.
function fpmOpenInShell(ev, a) {
  if (window.top === window.self) return true;   // 비임베드 → 기존 target=_blank 동작
  ev.preventDefault();
  var url = a.getAttribute('href') || '';
  var t = a.getAttribute('data-title') || '';
  var sid = a.getAttribute('data-sid') || '';
  var ct = /_b_/.test(url) ? 'form' : (/_c_/.test(url) ? 'dashboard' : 'response');
  try { window.parent.postMessage({type:'fpm-open-tab', view_url:url, title:t, sid:sid, content_type:ct}, '*'); }
  catch (e) { return true; }
  return false;
}

// Issue40: htm 스킬 단발 출력 문서 노출 (별도 섹션)
function _htmCardHtml(d) {
  // Issue69: htm 폴더 기본 경로는 생략, 파일명만 열기 버튼 옆에 표시
  const fname = (d.path || '').split('/').pop();
  // Issue169: '열기' 텍스트 → 열기 이모지(↗)만. title 로 의미 보강.
  // Issue194: 임베드(/hub-shell) 시 onclick 으로 부모 쉘 내부 탭 라우팅.
  const openLink = d.view_url
    ? `<a class="doc-open" href="${escapeHtml(d.view_url)}" target="_blank" data-title="${escapeHtml(d.title || fname)}" data-sid="${escapeHtml(d.sid || '')}" onclick="return fpmOpenInShell(event,this)" title="{T:htmDocs.openDocShort}">↗</a>`
    : `<span class="no-dash" title="{T:htmDocs.missing}">📂 ${escapeHtml(fname)}</span>`;
  // Issue169: 🆚 세션 — 이 문서를 만든 세션 탭으로 VSCode 포커스 (/open-session).
  //   sid 는 서버가 HTML 본문에서 추출. 없으면 버튼 미표시.
  const sessLink = d.sid
    ? `<a class="doc-sess" href="#" title="{T:htmDocs.focusSessionTitle}"`
      + ` onclick="event.preventDefault();event.stopPropagation();openSession('${escapeHtml(d.cwd)}','${escapeHtml(d.sid)}')">🆚</a>`
    : '';
  // B모드(ask 폼)만 API 응답 성공/실패 아이콘 표시. 비-B모드는 아이콘 없음.
  const qaIcon = d.is_ask
    ? (d.answered
        ? `<span class="qa-icon ok" title="{T:msg.qaOk}">✓</span>`
        : d.qa_failed
          ? `<span class="qa-icon err" title="{T:msg.qaErr}">✗</span>`
          : `<span class="qa-icon pending" title="{T:msg.qaPending}">⋯</span>`)
    : '';
  // Issue68: 본문 문서제목에서 중복 프로젝트명 접두사 제거 (헤드에 이미 표시)
  let cleanTitle = d.title || '';
  if (d.name && cleanTitle.toLowerCase().startsWith(d.name.toLowerCase())) {
    const rest = cleanTitle.slice(d.name.length).replace(/^[\\s—:-]+/, '');
    if (rest) cleanTitle = rest;
  }
  // Issue89: 선택된 프로젝트 카드 하이라이트 + 카드 전체 클릭 제거
  const selected = htmSelectedProjects.has(d.name);
  const cardCls = `card htm-doc${d.virtual ? ' virtual' : ''}${selected ? ' htm-prj-selected' : ''}`;
  return `<div class="${cardCls}" style="cursor:pointer" data-htmpath="${escapeHtml(d.path)}">
    <div class="card-head" style="background:${escapeHtml(d.color)}">
      <span class="name">${escapeHtml(d.emoji || '📁')} ${escapeHtml(d.name)}</span>
      <span class="head-right">${d.mtime ? `<span class="card-date">${escapeHtml(d.mtime)}</span>` : ''}${qaIcon}<button class="card-close" onclick="closeCard('htm','${escapeHtml(d.path)}',this)" title="{T:htmDocs.removeFromListTitle}" aria-label="{T:common.close}">✕</button></span>
    </div>
    <div class="card-body">
      <div class="dash-title">${escapeHtml(cleanTitle)}</div>
      ${d.summary ? `<div class="card-summary">${escapeHtml(d.summary)}</div>` : ''}
      <div class="actions">${openLink}${sessLink}<span class="doc-fname" title="${escapeHtml(d.path_display)}">${escapeHtml(fname)}</span></div>
    </div>
  </div>`;
}

function _htmFilterOptions() {
  const names = [...new Set(allHtmDocs.map(d => d.name).filter(Boolean))].sort();
  htmPrjFilter.innerHTML = '<option value="">{T:htmDocs.filterAdd}</option>' +
    names.filter(n => !htmSelectedProjects.has(n))
         .map(n => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
}

function _htmRenderChips() {
  const chips = document.getElementById('htm-filter-chips');
  if (!chips) return;
  chips.innerHTML = [...htmSelectedProjects].map(n =>
    `<span class="htm-chip">${escapeHtml(n)}<button class="htm-chip-rm" data-prjname="${escapeHtml(n)}" onclick="htmRemoveChip(this.dataset.prjname)" title="{T:htmDocs.filterRemove}" aria-label="{T:htmDocs.filterRemove}">✕</button></span>`
  ).join('');
}

const _HTM_FILTER_LS = 'htmPrjFilter';
function _htmSaveFilter() {
  try { localStorage.setItem(_HTM_FILTER_LS, JSON.stringify([...htmSelectedProjects])); } catch(e) {}
}
function _htmLoadFilter() {
  try {
    const v = localStorage.getItem(_HTM_FILTER_LS);
    if (v) { const a = JSON.parse(v); if (Array.isArray(a)) htmSelectedProjects = new Set(a); }
  } catch(e) {}
}

function htmRemoveChip(name) {
  htmSelectedProjects.delete(name);
  _htmSaveFilter();
  _htmFilterOptions();
  _htmRenderChips();
  applyHtmFilter();
}

async function closeHtmCard(event, cardEl) {
  // 링크·card-close ✕ 버튼은 각자 핸들러로 처리
  if (event.target.closest('a')) return;
  if (event.target.closest('.card-close')) return;
  const path = cardEl.dataset.htmpath;
  if (!path) return;
  cardEl.style.opacity = '0.35';
  cardEl.style.pointerEvents = 'none';
  try {
    const r = await fetch('/unregister-doc?type=htm&path=' + encodeURIComponent(path), {method: 'POST'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    setTimeout(reload, 120);
  } catch (e) {
    toast('❌ ' + e.message, 'err');
    cardEl.style.opacity = '';
    cardEl.style.pointerEvents = '';
  }
}

function htmToggleProjectFilter(event, name) {
  // card-close 버튼·링크 클릭 버블링 차단
  if (event.target.closest('.card-close')) return;
  if (event.target.closest('a')) return;
  if (htmSelectedProjects.has(name)) {
    htmSelectedProjects.delete(name);
  } else {
    htmSelectedProjects.add(name);
  }
  _htmSaveFilter();
  _htmFilterOptions();
  _htmRenderChips();
  applyHtmFilter();
}

function applyHtmFilter() {
  const sec = document.getElementById('htm-docs-section');
  const hg = document.getElementById('htm-grid');
  const hc = document.getElementById('htm-count');
  if (!allHtmDocs.length) { sec.style.display = 'none'; hg.innerHTML = ''; return; }
  const list = htmSelectedProjects.size === 0
    ? allHtmDocs
    : allHtmDocs.filter(d => htmSelectedProjects.has(d.name));
  sec.style.display = '';
  hc.textContent = list.length < allHtmDocs.length
    ? `${list.length}/${allHtmDocs.length}` : String(allHtmDocs.length);
  hg.innerHTML = list.map(_htmCardHtml).join('');
}

let _htmFilterLoaded = false;
function renderHtmDocs(list) {
  allHtmDocs = list || [];
  if (!_htmFilterLoaded) { _htmLoadFilter(); _htmFilterLoaded = true; }
  _htmFilterOptions();
  _htmRenderChips();
  applyHtmFilter();
}

// Issue42: hook 활동 피드 — newest-first 스트림
const feedList = document.getElementById('feed-list');
const feedCount = document.getElementById('feed-count');
const hubFeed = document.getElementById('hub-feed');
const feedVisToggle = document.getElementById('feed-vis-toggle');
const feedCollapseAll = document.getElementById('feed-collapse-all');
const feedKeep = document.getElementById('feed-keep');
const feedClear = document.getElementById('feed-clear');
const FEED_KEEP_N = 20;  // "20개만" 버튼이 보존하는 최신 항목 수

// Issue279: 새 피드 도착 시 헤더 토글 아이콘 깜빡임 (기본 on, 고급옵션 feed_blink_on_new 으로 off)
let FEED_BLINK_ON_NEW = true;
let feedTopId = null;      // 직전 렌더의 최신(top) 항목 id — 변하면 신규 도착
let feedBlinkTimer = null;
function feedStateEmoji() { return hubFeed.classList.contains('hidden') ? '🙈' : '🙉'; }
function blinkFeedToggle() {
  if (!feedVisToggle) return;
  if (feedBlinkTimer) { clearInterval(feedBlinkTimer); feedBlinkTimer = null; }
  const alt = hubFeed.classList.contains('hidden') ? '🙉' : '🙈';  // 현재 상태의 반대
  let n = 0;
  feedBlinkTimer = setInterval(() => {
    const on = (n % 2 === 0);  // 켜진 프레임 = alt 이모지 + 녹색 배경 + 15% 확대
    feedVisToggle.textContent = on ? alt : feedStateEmoji();
    feedVisToggle.classList.toggle('blinking', on);
    if (++n >= 6) {  // 3회 깜빡(6스텝×120ms≈720ms)
      clearInterval(feedBlinkTimer); feedBlinkTimer = null;
      feedVisToggle.classList.remove('blinking');
      feedVisToggle.textContent = feedStateEmoji();  // 상태 아이콘 복원
    }
  }, 120);
}

// 펼친 detail 항목 일괄 접기
feedCollapseAll.addEventListener('click', () => {
  openFeedItems.clear();
  feedList.querySelectorAll('.feed-item.open').forEach(el => el.classList.remove('open'));
});

// 최신 N개만 남기고 나머지 제거 (hook-feed 버퍼 + hook-feed.json)
feedKeep.addEventListener('click', async () => {
  if (!await confirmModal(`활동 피드에서 최신 ${FEED_KEEP_N}개만 남기고 나머지를 제거합니다. 진행할까요?`)) return;
  feedKeep.disabled = true;
  try {
    const r = await fetch('/feed-clear?keep=' + FEED_KEEP_N, {method: 'POST'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    openFeedItems.clear();
    await reload();
    toast(`✅ 활동 피드 ${j.removed_count}개 항목 제거 (최신 ${j.keep}개 보존)`, 'ok');
  } catch (e) {
    toast('❌ ' + e.message, 'err');
  } finally {
    feedKeep.disabled = false;
  }
});

// 활동 피드 전체 비우기 (hook-feed 버퍼 + hook-feed.json)
// confirmModal 사용 — 네이티브 confirm() 은 Firefox '추가 대화상자 차단' 시 무조건
// false 를 반환해 버튼이 조용히 죽는다 (Issue79 대칭 수정).
feedClear.addEventListener('click', async () => {
  if (!await confirmModal(t('feed.clearConfirm'))) return;
  feedClear.disabled = true;
  try {
    const r = await fetch('/feed-clear', {method: 'POST'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    openFeedItems.clear();
    renderFeed([]);
    toast(`✅ 활동 피드 ${j.removed_count}개 항목 제거`, 'ok');
  } catch (e) {
    toast('❌ ' + e.message, 'err');
  } finally {
    feedClear.disabled = false;
  }
});
const FEED_ICONS = { Stop: '✅', Notification: '🔔', AskUserQuestion: '❓' };
const openFeedItems = new Set();  // 열린 detail 항목 id (reload 후에도 펼침 상태 유지)

function relTime(ts) {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - (Number(ts) || 0)));
  if (sec < 60) return sec + 's';
  if (sec < 3600) return Math.floor(sec / 60) + 'm';
  if (sec < 86400) return Math.floor(sec / 3600) + 'h';
  return Math.floor(sec / 86400) + 'd';
}

// Issue87: 헤더 H1 동적 부분 — 마지막 활동 피드(newest-first 첫 항목) 반영.
//   형식: " - {프로젝트 이모지} {프로젝트명} - {활동 요약}"
let BOTS_ERROR = '';   // 레지스트리 접근 실패 메시지 (빈 문자열이면 정상)
// Issue401: 펼쳐둔 카드의 bot_id. 주기 갱신이 grid.innerHTML 로 카드를 통째
//   재생성하므로, 이걸 두지 않으면 열어둔 상세가 갱신마다 닫힌다.
const openBotCards = new Set();
// prj3#Issue438 ③: 핀봇 현황 카드 — 활성(퇴근 아님) 봇은 카드로 렌더.
//   Issue400: 활성 0 이어도 섹션은 남기고 **유휴 요약 1줄**을 그린다. 전원 퇴근을 숨기면
//   "묻지 않아도 안다" 가 정작 필요한 순간(유휴가 정상인지 이상인지 판단할 때)에 무너진다.
//   숨기는 것은 fbot 미설치(total 0) 한 경우뿐.
function renderBotsIdle(total, today) {
  const parts = [escapeHtml(t('bots.idle', { n: total }))];
  // 원장을 못 읽었으면(빈 dict) 실적 절은 통째로 생략한다 — 0 으로 채우면 "오늘 아무 일도
  //   없었다" 는 **없는 사실**을 단언하게 된다.
  if (today && today.dispatched !== undefined) {
    let line = t('bots.todayLine', { d: today.dispatched, c: today.done });
    if (today.cancelled) line += ' · ' + t('bots.todayCancelled', { n: today.cancelled });
    parts.push(`<span title="${escapeHtml(t('bots.todayTitle'))}">${escapeHtml(line)}</span>`);
    parts.push(escapeHtml(today.last_ts
      ? t('bots.lastActivity', { t: relTime(today.last_ts) })
      : t('bots.lastNone')));
  }
  return `<div class="bot-card bot-idle">`
    + parts.join('<span class="bot-idle-sep">|</span>') + `</div>`;
}

function renderBots(bots, total, today, roster) {
  const sec = document.getElementById('bots-section');
  const grid = document.getElementById('bots-grid');
  const cnt = document.getElementById('bots-count');
  if (!sec || !grid) return;
  if (BOTS_ERROR) {
    // 레지스트리를 못 읽은 것과 "봇이 전원 퇴근" 은 다르다 — 전자는 오류로 세운다.
    sec.style.display = '';
    cnt.textContent = '!';
    grid.innerHTML = `<div class="bot-card bot-err">⚠ ${escapeHtml(t('bots.error'))}: ${escapeHtml(BOTS_ERROR)}</div>`;
    return;
  }
  // Issue400: 섹션을 통째로 숨기는 것은 **fbot 미설치**(total 0) 한 경우뿐이다.
  //   봇은 있는데 전원 퇴근인 상태를 숨기면, 사용자는 기능이 죽은 건지 봇이 노는
  //   건지 화면만 봐선 알 수 없어 결국 세션에 되묻는다 — prj3#Issue438 이 없애려던 상황.
  if (!total) { sec.style.display = 'none'; grid.innerHTML = ''; return; }
  sec.style.display = '';
  cnt.textContent = `${(bots || []).length}/${total}`;
  // Issue402 ⓑ: 개체 나열이 아니라 **조직 구조**로 보여준다. 진입 단위는 루트 봇(= 나와
  //   소통하는 핀봇)이다. roster(전원 명부)가 없으면 구버전 payload 이므로 평면 렌더로
  //   폴백한다 — 조직도 때문에 봇 카드가 통째로 사라지는 일은 없어야 한다.
  const idle = (!bots || !bots.length) ? renderBotsIdle(total, today || {}) : '';
  if (roster && roster.length) {
    grid.innerHTML = idle + renderBotGroups(bots || [], roster);
    return;
  }
  if (idle) { grid.innerHTML = idle; return; }
  grid.innerHTML = (bots || []).map(botCard).join('');
}

// Issue402 ⓑ: 루트 봇 단위 그룹. 활성 봇은 기존 카드 그대로 쓰고(Issue401 아코디언
//   무회귀), 퇴근 봇은 한 줄 칩으로 남긴다 — 조직 구성원이므로 지우지 않되, 카드로
//   세우면 홈이 명부가 되어 "지금 무슨 일이 도는가" 가 묻힌다.
// Issue405: 퇴근 칩. 마지막 실행이 24h 이내면 상대시각을 덧붙여 "방금 퇴근" 과 "오래 전
//   퇴근" 을 화면에서 가른다 — 이 구분이 없어 사용자가 "나래 지금 도는가" 를 세션에
//   되물어야 했다. 24h 초과분은 칩을 그대로 두되 **툴팁에 절대시각**을 남긴다:
//   정보를 버리지 않으면서 홈이 명부로 번지는 것도 막는 절충이다.
const BOT_RECENT_SEC = 86400;
function botChip(m) {
  const label = `${m.state_emoji} ${m.title}`;
  const ts = Number(m.last_seen) || 0;
  // 기록이 아예 없는 봇(한 번도 일한 적 없음)은 없는 시각을 지어내지 않는다.
  if (!ts) return `<span class="bot-chip">${escapeHtml(label)}</span>`;
  const tip = t('bots.chipLastSeen', { t: new Date(ts * 1000).toLocaleString() });
  const fresh = (Date.now() / 1000 - ts) < BOT_RECENT_SEC;
  if (!fresh) return `<span class="bot-chip" title="${escapeHtml(tip)}">${escapeHtml(label)}</span>`;
  return `<span class="bot-chip bot-chip-recent" title="${escapeHtml(tip)}">${escapeHtml(label)}`
    + ` <span class="bot-chip-age">${escapeHtml(t('bots.chipCheckout', { t: relTime(ts) }))}</span></span>`;
}

function renderBotGroups(bots, roster) {
  const active = new Map(bots.map(b => [b.bot_id, b]));
  const order = [];
  const byRoot = new Map();
  roster.forEach(m => {
    if (!byRoot.has(m.root)) { byRoot.set(m.root, { root: m.root, head: null, members: [] }); order.push(m.root); }
    const g = byRoot.get(m.root);
    g.members.push(m);
    if (m.is_root) g.head = m;
  });
  return order.map(rid => {
    const g = byRoot.get(rid);
    // 루트가 명부에서 사라진(끊긴 사슬) 경우에도 그룹은 남긴다 — 소속 봇이 통째로
    //   화면에서 증발하는 것보다 id 만 뜨는 편이 낫다.
    const head = g.head || { title: rid, role: '', color: '', icon_uri: '', state_emoji: '⚪' };
    // 활성 수는 **실제로 카드가 선 수**로 센다 — roster 의 active 플래그로 세면
    //   "활성 2" 라 써놓고 카드가 1장인 상태가 원리적으로 가능해진다(같은 스냅샷이라
    //   현실에선 안 갈리지만, 머리말이 본문과 어긋나는 종류의 거짓말은 구조로 막는다).
    const act = g.members.filter(m => active.has(m.bot_id)).length;
    const badge = head.icon_uri
      ? `<img class="bot-icon bot-group-icon" src="${escapeHtml(head.icon_uri)}" alt="${escapeHtml(head.role || '')}">`
      : `<span class="bot-dot bot-group-icon"${head.color ? ` style="background:${escapeHtml(head.color)}"` : ''}></span>`;
    const cards = g.members.filter(m => active.has(m.bot_id))
                           .map(m => botCard(active.get(m.bot_id))).join('');
    const rest = g.members.filter(m => !active.has(m.bot_id));
    const chips = rest.length
      ? `<div class="bot-group-rest" title="${escapeHtml(t('bots.restTitle'))}">`
        + rest.map(botChip).join('')
        + `</div>`
      : '';
    // ⚠️ 조직도 링크는 **그룹 헤더**에만 둔다. 카드 본체 클릭은 Issue401 아코디언이
    //   이미 점유했고, 그것을 빼앗으면 상세 펼침이 통째로 죽는다(Issue401 25항 회귀).
    return `<div class="bot-group" data-group="${escapeHtml(rid)}">`
      + `<div class="bot-group-head">${badge}`
      + `<span class="bot-group-name">${escapeHtml(head.title)}</span>`
      + `<span class="bot-group-count">${escapeHtml(t('bots.groupCount', { a: act, n: g.members.length }))}</span>`
      + `<a class="bot-map-link" href="/fbot-map?root=${encodeURIComponent(rid)}" target="_blank"`
      + ` rel="noopener" title="${escapeHtml(t('bots.mapTitle'))}">🗺</a>`
      + `</div>${cards}${chips}</div>`;
  }).join('');
}

function botCard(b) {
    // 아이콘 부재(파일 없음·상한 초과)는 개체 색 dot 으로 폴백 — 카드가 깨지지 않는다.
    const color = b.color || '';
    const badge = b.icon_uri
      ? `<img class="bot-icon" src="${escapeHtml(b.icon_uri)}" alt="${escapeHtml(b.role)}">`
      : `<span class="bot-dot"${color ? ` style="background:${escapeHtml(color)}"` : ''}></span>`;
    const stateTxt = (window.__i18n && window.__i18n['bots.state.' + b.state]) || b.state_label || b.state;
    const task = b.current_task
      ? `<div class="bot-task">${escapeHtml(b.current_task)}</div>`
      : `<div class="bot-task none">${t('bots.noTask')}</div>`;
    const stale = b.lease_stale ? ` <span class="bot-stale" title="${t('bots.staleTitle')}">${t('bots.stale')}</span>` : '';
    const prj = (b.prj !== null && b.prj !== undefined) ? `<span class="bot-role">prj${escapeHtml(b.prj)}</span>` : '';
    const style = color ? ` style="border-left-color:${escapeHtml(color)}"` : '';
    const isOpen = openBotCards.has(b.bot_id);
    return `<div class="bot-card${isOpen ? ' open' : ''}"${style} data-bot="${escapeHtml(b.bot_id)}"`
      + ` role="button" tabindex="0" aria-expanded="${isOpen}" title="${escapeHtml(t('bots.toggleTitle'))}">`
      + `${badge}<div class="bot-body">`
      + `<div class="bot-name">${escapeHtml(b.title)}<span class="bot-role">${escapeHtml(b.role)}</span>${prj}</div>`
      + `<div class="bot-state">${escapeHtml(b.state_emoji)} ${escapeHtml(stateTxt)}${stale}</div>${task}`
      + botDetail(b)
      + `</div></div>`;
}

// Issue401(prj3#Issue444): 펼침 상세 — payload 가 이미 들고 있는 값만 쓴다(서버 왕복 없음).
function botDetail(b) {
  const CAREER = { probation: 'career.probation', active: 'career.active',
                   leave: 'career.leave', terminated: 'career.terminated' };
  const rows = [[t('bots.d.id'), b.bot_id]];
  if (b.career) rows.push([t('bots.d.career'), t(CAREER[b.career] ? 'bots.' + CAREER[b.career] : b.career)]);
  if (b.parent_bot_id) rows.push([t('bots.d.parent'), b.parent_bot_id]);
  // lease 는 "얼마나 남았나 / 얼마나 지났나" 가 알고 싶은 것이지 epoch 이 아니다.
  if (b.lease_expires) {
    const d = Math.round((b.lease_expires * 1000 - Date.now()) / 60000);
    rows.push([t('bots.d.lease'), d >= 0 ? t('bots.leaseLeft', { m: d })
                                         : t('bots.leaseGone', { m: -d })]);
  }
  // 헤드의 .bot-task 는 2줄 clamp 다. 펼침에서 clamp 가 풀리므로 전문을 여기 다시
  //   싣지 않는다 — 같은 문자열을 두 번 보여주면 상세가 아니라 중복이다.
  return `<div class="bot-detail">` + rows.map(([k, v]) =>
    `${escapeHtml(k)}: ${escapeHtml(v)}`).join('\\n') + `</div>`;
}

// 카드 클릭·키보드 → 펼침 토글. 이벤트 위임이라 재렌더된 카드에도 그대로 붙는다.
//   유휴 요약 줄(.bot-idle)·오류 줄(.bot-err)에는 data-bot 이 없어 자동으로 제외된다.
(function bindBotToggle() {
  const grid = document.getElementById('bots-grid');
  if (!grid) return;
  const toggle = (card) => {
    const id = card.dataset.bot;
    if (openBotCards.has(id)) { openBotCards.delete(id); card.classList.remove('open'); }
    else { openBotCards.add(id); card.classList.add('open'); }
    card.setAttribute('aria-expanded', String(openBotCards.has(id)));
  };
  grid.addEventListener('click', (e) => {
    const card = e.target.closest('.bot-card[data-bot]');
    if (card) toggle(card);
  });
  grid.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const card = e.target.closest('.bot-card[data-bot]');
    if (!card) return;
    e.preventDefault();   // Space 로 페이지가 스크롤되지 않게
    toggle(card);
  });
})();

function renderHeadline(feed) {
  const el = document.getElementById('hub-headline');
  if (!feed || !feed.length) { el.textContent = ''; return; }
  const it = feed[0];
  const name = it.name || '?';
  let title = it.summary || it.htm_title || it.event || '';
  // 요약이 프로젝트명으로 시작하면 중복 접두사 제거 (htm_title 폴백 대비)
  if (title.toLowerCase().startsWith(name.toLowerCase())) {
    title = title.slice(name.length).replace(/^[\\s—:\\-]+/, '') || title;
  }
  const emoji = it.emoji || '📁';
  el.textContent = ` - ${emoji} ${name}${title ? ' - ' + title : ''}`;
}

// Issue87: 중요 이벤트 칩 스트립 — 서버 중요도 결정 모듈(important_events) 렌더
const IMP_SNOOZE_MS = 30 * 60 * 1000;
function _impSnoozeKey(text) {
  try { return 'imp_sn_' + btoa(encodeURIComponent(text || '')).slice(0, 32); }
  catch { return 'imp_sn_' + (text || '').slice(0, 32); }
}
function _impIsSnoozed(text) {
  try { return parseInt(localStorage.getItem(_impSnoozeKey(text)) || '0', 10) > Date.now(); }
  catch { return false; }
}
function impDismiss(text) {
  try { localStorage.setItem(_impSnoozeKey(text), String(Date.now() + IMP_SNOOZE_MS)); } catch {}
  document.querySelectorAll('.imp-chip-wrap[data-imptext]').forEach(w => {
    if (w.dataset.imptext === text) w.remove();
  });
  const el = document.getElementById('hub-important');
  if (el && !el.querySelector('.imp-chip-wrap'))
    el.innerHTML = '<span class="imp-none">{T:msg.noImportant}</span>';
}
// Issue87 후속: chip 본문 click → 활동 피드 해당 항목으로 스크롤 + 펼침
function impFocusFeed(feedId) {
  if (!feedId) return;
  const item = document.querySelector(`.feed-item[data-id="${CSS.escape(feedId)}"]`);
  if (!item) { toast(t('msg.itemNotFound'), 'err'); return; }
  openFeedItems.add(feedId);
  item.classList.add('open');
  item.scrollIntoView({ behavior: 'smooth', block: 'center' });
  item.style.transition = 'background 0.4s';
  const orig = item.style.background;
  item.style.background = 'color-mix(in srgb, var(--accent, #6cf) 30%, var(--bg))';
  setTimeout(() => { item.style.background = orig; }, 1200);
}
function renderImportant(list) {
  const el = document.getElementById('hub-important');
  const visible = (list || []).filter(ev => !_impIsSnoozed(ev.text || ''));
  if (!visible.length) {
    el.innerHTML = '<span class="imp-none">{T:msg.noImportant}</span>';
    return;
  }
  el.innerHTML = visible.map(ev => {
    const lvl = ['critical','warning','info'].includes(ev.level) ? ev.level : 'info';
    const inner = `${escapeHtml(ev.icon || '▪')} ${escapeHtml(ev.text || '')}`;
    const textAttr = escapeHtml(ev.text || '');
    let chip;
    if (ev.link) {
      chip = `<a class="imp-chip imp-${lvl}" href="${escapeHtml(ev.link)}" target="_blank" title="${escapeHtml(ev.text || '')}">${inner} ↗</a>`;
    } else if (ev.feed_id) {
      const fid = escapeHtml(String(ev.feed_id));
      chip = `<span class="imp-chip imp-${lvl}" title="{T:msg.viewDetail}" onclick="impFocusFeed('${fid}')">${inner}</span>`;
    } else {
      chip = `<span class="imp-chip imp-${lvl}" title="${escapeHtml(ev.text || '')}">${inner}</span>`;
    }
    return `<span class="imp-chip-wrap" data-imptext="${textAttr}">${chip}<button class="imp-dismiss" onclick="impDismiss(this.closest('[data-imptext]').dataset.imptext)" title="{T:msg.hide30min}" aria-label="{T:common.hideLabel}">✕</button></span>`;
  }).join('');
}

// Issue47: 활동 피드 프로젝트 이모지·이름 표시 토글 (hub_setting.yml)
const FEED_SHOW_EMOJI = {FEED_SHOW_PROJECT_EMOJI};
const FEED_SHOW_NAME = {FEED_SHOW_PROJECT_NAME};
function renderFeed(list) {
  feedCount.textContent = list.length;
  // Issue279: 최신 항목 id 변화 = 신규 도착 → 헤더 토글 깜빡 (첫 렌더는 skip)
  const newTop = list.length ? list[0].id : null;
  if (FEED_BLINK_ON_NEW && feedTopId !== null && newTop && newTop !== feedTopId) blinkFeedToggle();
  feedTopId = newTop;
  if (!list.length) {
    feedList.innerHTML = '<div class="feed-empty">{T:feed.empty}</div>';
    return;
  }
  feedList.innerHTML = list.map(it => {
    const isOpen = openFeedItems.has(it.id);
    // Issue42_1: htm 문서 연결 시 카드 제목(htm_title)을 피드 제목으로 사용
    const summaryText = it.htm_title || it.summary || it.event;
    // Issue65: detail 에 제목 포함 — 한 줄 클램프로 잘린 전체 제목 복구 경로
    const detail = ['event: ' + (it.event || ''), 'cwd: ' + (it.cwd || ''),
                    t('feed.titlePrefix') + (summaryText || ''),
                    (it.detail || t('feed.noDetail'))].map(escapeHtml).join('\\n');
    // Issue42_2: htm view_url 있으면 열기 아이콘
    const openIcon = it.htm_view_url
      ? `<a class="feed-open" href="${escapeHtml(it.htm_view_url)}" target="_blank" title="{T:htmDocs.openDoc}">↗</a>`
      : '';
    // Issue67: 항목 배경에 프로젝트색 좌→우 그래디언트 (좌측만 옅게, 우측은 카드 배경 수렴)
    const feedStyle = `border-left-color:${escapeHtml(it.color)};background:linear-gradient(to right, color-mix(in srgb, ${escapeHtml(it.color)} 22%, var(--bg)), var(--bg))`;
    return `<div class="feed-item${isOpen ? ' open' : ''}" data-id="${escapeHtml(it.id)}" style="${feedStyle}">
      <div class="feed-item-head">
        ${(FEED_SHOW_EMOJI && it.emoji) ? `<span class="feed-proj-emoji" data-cwd="${escapeHtml(it.cwd)}" title="{T:common.openVscodeTitle}">${escapeHtml(it.emoji)}</span>` : ''}
        ${FEED_SHOW_NAME ? `<a class="feed-title" data-cwd="${escapeHtml(it.cwd)}" title="{T:common.openVscodeTitle}">${escapeHtml(it.name)}</a>` : ''}
        <span class="feed-summary" title="${escapeHtml(summaryText)}">${escapeHtml(summaryText)}</span>
        ${openIcon}
        <span class="feed-age">${relTime(it.ts)}</span>
      </div>
      <div class="feed-detail">${detail}</div>
    </div>`;
  }).join('');
}

// 제목 클릭 → VSCode 열기 / 본문 클릭 → detail 토글 (이벤트 위임 + 버블링 분리)
feedList.addEventListener('click', (e) => {
  // 아이콘·프로젝트 이모지·프로젝트명 어느 것을 눌러도 VSCode 로 연다
  const openEl = e.target.closest('.feed-title, .feed-proj-emoji');
  if (openEl) {
    e.stopPropagation();
    openProject(openEl.dataset.cwd);
    return;
  }
  // Issue42_2: 열기 아이콘 클릭 — anchor 기본 동작(새 탭)만, detail 토글 차단
  if (e.target.closest('.feed-open')) { e.stopPropagation(); return; }
  const item = e.target.closest('.feed-item');
  if (!item) return;
  const id = item.dataset.id;
  if (openFeedItems.has(id)) { openFeedItems.delete(id); item.classList.remove('open'); }
  else { openFeedItems.add(id); item.classList.add('open'); }
});

async function openProject(cwd) {
  if (!cwd) { toast(t('msg.noCwd'), 'err'); return; }
  try {
    const r = await fetch('/open-project', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cwd})
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    // Issue237: 원격 응답이면 클라이언트측 vscode-remote:// URI 를 브라우저가 발사.
    if (j.uri) { window.location.href = j.uri; return; }
    toast(t('msg.vscodeOpened', {cwd: cwd}), 'ok');
  } catch (e) {
    toast('❌ ' + e.message, 'err');
  }
}

// Issue131: 활성 세션 행 클릭 → 해당 Claude Code 세션 탭으로 포커스
//   (vscode://anthropic.claude-code/open?session=<sid>). 워크스페이스(cwd)가 열려 있어야 포커스됨.
async function openSession(cwd, sid) {
  if (!cwd || !sid) { toast(t('msg.noCwdSid'), 'err'); return; }
  try {
    const r = await fetch('/open-session', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cwd, sid})
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    // Issue237: 원격 응답이면 folder_uri 로 Remote-SSH 창 보장 후 세션 URI 로 탭 포커스.
    if (j.uri) {
      if (j.folder_uri) { try { window.open(j.folder_uri); } catch (e2) {} }
      window.location.href = j.uri; return;
    }
    toast(t('msg.sessionTabOpened'), 'ok');
  } catch (e) {
    toast('❌ ' + e.message, 'err');
  }
}

// Issue219: 터미널(CLI) 세션 클릭 → JSONL transcript 뷰어(/s/{h}/{sid}?token=) 열기.
//   VSCode 포커스 불가 세션도 대화 내용 확인 가능. 임베드(hub-shell) 시 부모 쉘 내부 탭으로,
//   비임베드(직접 /hub)면 새 탭. 뷰어 SPA 는 origin 무관하게 jsonl 을 읽어 렌더한다.
function openSessionViewer(url, title) {
  if (!url) { toast('세션 뷰어 URL 없음 (transcript 미해석)', 'err'); return; }
  if (window.top !== window.self) {
    try {
      window.parent.postMessage({type:'fpm-open-tab', view_url:url, title:(title||'세션'), content_type:'response'}, '*');
      return;
    } catch (e) { /* fall through to new tab */ }
  }
  window.open(url, '_blank');
}

// 사이드바 숨김/보기 — localStorage 우선, 없으면 hub_setting.yml 기본값
function applyFeedVisible(visible) {
  hubFeed.classList.toggle('hidden', !visible);
  // 헤더 토글 아이콘: 현재 상태 표현 — 보임=🙉(눈 뜸) / 숨김=🙈(눈 가림)
  if (feedVisToggle) feedVisToggle.textContent = visible ? '🙉' : '🙈';
}
function setFeedVisible(visible) {
  applyFeedVisible(visible);
  localStorage.setItem('hubFeedVisible', visible ? '1' : '0');
}
feedVisToggle.addEventListener('click', () => setFeedVisible(hubFeed.classList.contains('hidden')));
(function initFeedVisible() {
  const stored = localStorage.getItem('hubFeedVisible');
  const def = {FEED_DEFAULT_VISIBLE};
  applyFeedVisible(stored == null ? def : stored === '1');
})();

function renderProjects(projects) {
  if (!projects.length) { grid.innerHTML = ''; return; }  // Issue43: dashboard 없으면 비워둠
  const filterVal = filterSel.value;
  const sortVal = sortSel.value;
  // 모든 dash 를 평탄화 + project 메타 동행
  const items = [];
  for (const p of projects) {
    if (!p.dashes.length) {
      items.push({proj: p, dash: null});
      continue;
    }
    for (const d of p.dashes) items.push({proj: p, dash: d});
  }
  // filter
  const filtered = items.filter(it => {
    if (!it.dash) return filterVal === 'all';
    if (filterVal === 'all') return true;
    return (it.dash.status || '').toLowerCase() === filterVal;
  });
  // Issue38: sort. dashed 카드 우선, dashless 끼리는 name 으로 stable.
  // 진행률순은 null progress 를 뒤로 보내고 동률은 mtime desc tiebreaker 적용.
  const mtimeDesc = (a, b) => (b.dash.mtime || '').localeCompare(a.dash.mtime || '');
  filtered.sort((a, b) => {
    if (!a.dash && !b.dash) return (a.proj.name || '').localeCompare(b.proj.name || '');
    if (!a.dash) return 1;
    if (!b.dash) return -1;
    if (sortVal === 'name') {
      const byName = (a.proj.name || '').localeCompare(b.proj.name || '');
      return byName !== 0 ? byName : mtimeDesc(a, b);
    }
    if (sortVal === 'progress') {
      const pa = a.dash.progress, pb = b.dash.progress;
      const naN = (pa == null), nbN = (pb == null);
      if (naN && nbN) return mtimeDesc(a, b);
      if (naN) return 1;
      if (nbN) return -1;
      const diff = pb - pa;
      return diff !== 0 ? diff : mtimeDesc(a, b);
    }
    // recent (mtime desc)
    return mtimeDesc(a, b);
  });
  const cards = [];
  const newSnap = {};
  for (const it of filtered) {
    const p = it.proj, d = it.dash;
    if (!d) {
      cards.push(`<div class="card"><div class="card-head" style="background:${escapeHtml(p.color)}"><span class="name">${escapeHtml(p.emoji || '📁')} ${escapeHtml(p.name)}</span></div><div class="card-body"><div class="no-dash">{T:dashboard.empty}</div></div></div>`);
      continue;
    }
    const pct = (typeof d.progress === 'number') ? Math.max(0, Math.min(100, d.progress)) : null;
    const isVirtual = !!p.virtual;
    // Issue138: stop 버튼은 runner 생존 + non-terminal 일 때만. done/stopped/stale/missing
    //   또는 runner pid 사망(서버 runner_alive=false) 후에는 "stop" 이 의미 없고 오히려
    //   "아직 살아있음"으로 오인된다 → 숨김. 카드 제거는 ✕(card-close)/하단 정리 버튼.
    const stTerm = (d.status || '').toLowerCase();
    const isTerminal = /(^|[^a-z])(done|stopped|stop|stale|missing)([^a-z]|$)/.test(stTerm);
    // Issue32/Issue39: 가상 프로젝트 (system/___pm-tmp) 는 token 없음 → stop/open 비활성
    const stopBtn = (d.pid && p.token && !isVirtual && d.runner_alive && !isTerminal) ? `<button class="stop" onclick="stopRunner('${escapeHtml(p.cwd)}','${escapeHtml(p.token)}',${d.pid},this)">⏹ stop pid=${d.pid}</button>` : '';
    const openLink = (d.view_url && p.token && !isVirtual)
      ? `<a href="${escapeHtml(d.view_url)}" target="_blank">{T:common.open}</a>`
      : `<span class="no-dash" title="{T:dashboard.externalNoView}">📂 ${escapeHtml(d.path_display || d.path)}</span>`;
    const key = dashKey(p, d);
    newSnap[key] = {progress: pct, mtime: d.mtime};
    const prev = lastSnap[key];
    const changed = prev && (prev.progress !== pct || prev.mtime !== d.mtime);
    // sparkline history accumulation
    if (pct != null) {
      progressHist[key] = (progressHist[key] || []).slice(-19);
      const hist = progressHist[key];
      if (!hist.length || hist[hist.length - 1] !== pct) hist.push(pct);
    }
    const spark = sparkSvg(progressHist[key] || []);
    cards.push(`<div class="card${changed ? ' diff-recent' : ''}${isVirtual ? ' virtual' : ''}">
      <div class="card-head" style="background:${escapeHtml(p.color)}">
        <span class="name">${escapeHtml(p.emoji || '📁')} ${escapeHtml(p.name)}</span>
        <span class="head-right">${d.status ? `<span class="badge">${escapeHtml(d.status)}</span>` : ''}<button class="card-close" onclick="closeCard('dash','${escapeHtml(d.path)}',this)" title="{T:htmDocs.removeFromListTitle}" aria-label="{T:common.close}">✕</button></span>
      </div>
      <div class="card-body">
        <div class="dash-title">${escapeHtml(d.title || d.path.split('/').pop())}</div>
        ${pct != null ? `<div class="progress-wrap"><div class="progress-bar" style="width:${pct}%"></div></div>${spark}<div class="meta"><span>${pct}%</span><span>${escapeHtml(d.mtime || '')}</span></div>` : `<div class="meta"><span>—</span><span>${escapeHtml(d.mtime || '')}</span></div>`}
        <div class="actions">
          ${openLink}
          ${stopBtn}
        </div>
      </div>
    </div>`);
  }
  grid.innerHTML = cards.join('') || '<div class="empty">{T:dashboard.filterEmpty}</div>';
  lastSnap = newSnap;
}

filterSel.addEventListener('change', reload);
sortSel.addEventListener('change', reload);

// Issue137: 빈(프롬프트 전) 좀비 claude 세션 일괄 종료 + 새로고침.
//   서버가 titled/dashboard 는 제외하고 빈 live 세션의 live_pid 만 SIGTERM.
async function killEmptyLive(btn) {
  if (!confirm(t('liveSessions.zombieConfirm'))) return;
  if (btn) btn.disabled = true;
  try {
    const r = await fetch('/kill-empty-live', {method: 'POST', headers: {'Content-Type': 'application/json'}});
    const j = await r.json();
    if (r.ok) {
      toast(`🧟 좀비 ${j.killed_count}개 종료 (카드 ${j.pruned}개 정리)`, 'ok');
      setTimeout(reload, 400);
    } else {
      toast(`❌ ${j.error || 'fail'}`, 'err');
      if (btn) btn.disabled = false;
    }
  } catch (e) {
    toast('❌ ' + e.message, 'err');
    if (btn) btn.disabled = false;
  }
}

async function stopRunner(cwd, token, pid, btn) {
  if (!confirm(`PID ${pid} runner 중단?`)) return;
  // Issue64: 결과/에러는 toast 로만 표시. 종전엔 btn.textContent 에 긴 에러문
  //   ('pid not registered for this cwd')을 주입해 1.6em 아이콘 버튼(✕)의
  //   레이아웃이 깨졌다. 실패 시 원래 버튼 내용을 복원한다.
  const orig = btn.innerHTML;
  btn.disabled = true;
  try {
    const cwd_enc = encodeURIComponent(cwd);
    const tok_enc = encodeURIComponent(token);
    const r = await fetch(`/control?cwd=${cwd_enc}&token=${tok_enc}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'stop', pid: pid})
    });
    const j = await r.json();
    if (r.ok) {
      toast(`✅ runner ${j.status} (pid ${pid})`, 'ok');
      setTimeout(reload, 500);
    } else {
      toast(`❌ ${j.error || 'fail'}`, 'err');
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  } catch (e) {
    toast('❌ ' + e.message, 'err');
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

// Issue66: 큐 dashboard graceful 제거 — supervisor 에 SIGUSR2 (action=remove)
async function removeQueueDash(cwd, token, supervisorPid, sid, btn) {
  if (!confirm(`큐 dashboard (supervisor PID ${supervisorPid}) 를 graceful 회수합니다. 진행 중인 작업은 sentinel 출력 후 종료됩니다. 계속할까요?`)) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  try {
    const cwd_enc = encodeURIComponent(cwd);
    const tok_enc = encodeURIComponent(token);
    const r = await fetch(`/control?cwd=${cwd_enc}&token=${tok_enc}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'remove', supervisor_pid: supervisorPid, sid: sid})
    });
    const j = await r.json();
    if (r.ok) {
      const statusMsg = j.status === 'already_dead' ? t('liveSessions.alreadyDead', {pid: supervisorPid}) : t('liveSessions.removing', {pid: supervisorPid});
      toast(`✅ ${statusMsg}`, 'ok');
      setTimeout(reload, 800);
    } else {
      toast(`❌ ${j.error || 'fail'}`, 'err');
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  } catch (e) {
    toast('❌ ' + e.message, 'err');
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

// Issue132: live(claude) 세션 카드 수동 dismiss — 프로세스 kill 아님, 카드(sessions entry)만 제거.
//   VSCode 가 세션 종료 후에도 claude 프로세스를 살려둬 빈 카드가 잔존할 때 수동 정리용.
async function dismissSession(cwd, token, sid, btn) {
  if (!confirm(t('liveSessions.dismissConfirm'))) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  try {
    const cwd_enc = encodeURIComponent(cwd);
    const tok_enc = encodeURIComponent(token);
    const sid_enc = encodeURIComponent(sid);
    const r = await fetch(`/session/dismiss?cwd=${cwd_enc}&token=${tok_enc}&sid=${sid_enc}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}
    });
    const j = await r.json();
    if (r.ok) {
      toast(j.pruned ? t('msg.cardHidden') : t('msg.alreadyRemoved'), 'ok');
      setTimeout(reload, 400);
    } else {
      toast(`❌ ${j.error || 'fail'}`, 'err');
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  } catch (e) {
    toast('❌ ' + e.message, 'err');
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

// Issue66 Phase 7: 큐 dashboard 승인 게이트 — waiting_approval 항목 진행 승인
async function approveQueueItem(cwd, token, sid, item, btn) {
  if (!confirm(t('liveSessions.approveConfirm', {item: item}))) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  try {
    const cwd_enc = encodeURIComponent(cwd);
    const tok_enc = encodeURIComponent(token);
    const r = await fetch(`/control?cwd=${cwd_enc}&token=${tok_enc}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'approve', item: item, sid: sid})
    });
    const j = await r.json();
    if (r.ok) {
      toast(t('msg.approved', {item: item}), 'ok');
      setTimeout(reload, 800);
    } else {
      toast(`❌ ${j.error || 'fail'}`, 'err');
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  } catch (e) {
    toast('❌ ' + e.message, 'err');
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

const toastEl = document.getElementById('toast');
let toastTimer = null;
function toast(msg, kind) {
  toastEl.textContent = msg;
  toastEl.className = 'toast show ' + (kind || '');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.className = 'toast'; }, 4000);
}

// 인페이지 확인 모달 — 브라우저 네이티브 confirm() 은 Firefox '추가 대화상자
// 차단' 체크 시 무조건 false 를 반환해 버튼이 조용히 죽는다. 모달은 차단 불가.
function confirmModal(msg) {
  return new Promise(resolve => {
    const m = document.getElementById('cf-modal');
    document.getElementById('cf-msg').textContent = msg;
    let done = false;
    const ok = document.getElementById('cf-ok');
    const cancel = document.getElementById('cf-cancel');
    const x = document.getElementById('cf-x');
    const finish = (v) => {
      if (done) return;
      done = true;
      m.hidden = true;
      ok.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      x.removeEventListener('click', onCancel);
      m.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      resolve(v);
    };
    const onOk = () => finish(true);
    const onCancel = () => finish(false);
    const onBackdrop = (e) => { if (e.target === m) finish(false); };
    const onKey = (e) => { if (e.key === 'Escape') finish(false); };
    ok.addEventListener('click', onOk);
    cancel.addEventListener('click', onCancel);
    x.addEventListener('click', onCancel);
    m.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
    m.hidden = false;
    ok.focus();
  });
}

// Issue41: clear 는 registry 항목만 제거 — 실제 파일은 보존
const clearBtn = document.getElementById('btn-clear-done');
clearBtn.addEventListener('click', async () => {
  if (!await confirmModal(t('dashboard.clearConfirm'))) return;
  clearBtn.disabled = true;
  const origLabel = clearBtn.textContent;
  clearBtn.textContent = t('common.cleaning');
  try {
    const r = await fetch('/clear-done', {method: 'POST'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    if (j.removed_count === 0) {
      toast(t('dashboard.noClearTarget'), 'ok');
    } else {
      toast(`✅ ${j.removed_count}개 목록에서 제거 (파일 보존)`, 'ok');
    }
    setTimeout(reload, 300);
  } catch (e) {
    toast('❌ ' + e.message, 'err');
  } finally {
    clearBtn.disabled = false;
    clearBtn.textContent = origLabel;
  }
});

// Issue137: 좀비 킬러 버튼 바인딩 (활성 세션 섹션 헤더)
const zombieBtn = document.getElementById('btn-zombie');
if (zombieBtn) zombieBtn.addEventListener('click', () => killEmptyLive(zombieBtn));

// Issue41: 디스크 재스캔 — 등록 누락분 registry 수거 (수동 부트스트랩)
const rescanBtn = document.getElementById('btn-rescan');
rescanBtn.addEventListener('click', async () => {
  rescanBtn.disabled = true;
  const origLabel = rescanBtn.textContent;
  rescanBtn.textContent = t('statusbar.scanning');
  try {
    const r = await fetch('/hub-rescan', {method: 'POST'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    const a = j.added || {};
    const total = (a.htm || 0) + (a.dash || 0);
    if (total === 0) {
      toast(t('statusbar.noRescan'), 'ok');
    } else {
      toast(`✅ registry 수거 — hub ${a.htm || 0} / dash ${a.dash || 0}`, 'ok');
    }
    setTimeout(reload, 300);
  } catch (e) {
    toast('❌ ' + e.message, 'err');
  } finally {
    rescanBtn.disabled = false;
    rescanBtn.textContent = origLabel;
  }
});

// htm 문서 목록 정리 — keep=0 전체 제거 / keep=12 최신 12개 보존 (registry 만, 파일 보존)
async function clearHtmDocs(keep, btn) {
  const allBtns = [document.getElementById('btn-htm-keep'),
                   document.getElementById('btn-htm-clear')];
  const labels = allBtns.map(b => b.textContent);
  allBtns.forEach(b => b.disabled = true);
  btn.textContent = t('common.cleaning');
  try {
    const r = await fetch('/clear-htm-docs?keep=' + keep, {method: 'POST'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    if (j.removed_count === 0) {
      toast(t('htmDocs.noClearTarget'), 'ok');
    } else {
      toast(`✅ hub 문서 ${j.removed_count}개 목록에서 제거 (${j.total}개 중, 파일 보존)`, 'ok');
    }
    setTimeout(reload, 300);
  } catch (e) {
    toast('❌ ' + e.message, 'err');
  } finally {
    allBtns.forEach((b, i) => { b.disabled = false; b.textContent = labels[i]; });
  }
}
htmPrjFilter.addEventListener('change', () => {
  const v = htmPrjFilter.value;
  if (!v) return;
  htmSelectedProjects.add(v);
  htmPrjFilter.value = '';
  _htmSaveFilter();
  _htmFilterOptions();
  _htmRenderChips();
  applyHtmFilter();
});
document.getElementById('htm-grid').addEventListener('click', e => {
  if (e.target.closest('.card-close')) return;
  if (e.target.closest('a')) return;
  const card = e.target.closest('[data-htmpath]');
  if (!card) return;
  card.classList.toggle('expanded');
});
document.getElementById('btn-htm-keep').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  if (!await confirmModal(t('htmDocs.keepConfirm'))) return;
  clearHtmDocs(12, btn);
});
document.getElementById('btn-htm-clear').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  if (!await confirmModal(t('htmDocs.clearConfirm'))) return;
  clearHtmDocs(0, btn);
});

// Issue49: 카드 '닫기' — 단일 registry 항목 제거 (hub 목록에서만, 실제 파일 보존)
async function closeCard(type, path, btn) {
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = '⋯';
  try {
    const r = await fetch('/unregister-doc?type=' + encodeURIComponent(type)
      + '&path=' + encodeURIComponent(path), {method: 'POST'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    toast(j.removed ? t('htmDocs.removed') : t('htmDocs.alreadyRemoved'), 'ok');
    setTimeout(reload, 200);
  } catch (e) {
    toast('❌ ' + e.message, 'err');
    btn.disabled = false;
    btn.textContent = orig;
  }
}

// Project List 팝업 — Projects.md 목록 표시 (읽기 전용, 수정 기능 추후 구현)
const plModal = document.getElementById('pl-modal');
const plBody = document.getElementById('pl-body');

function renderProjectList(list) {
  if (!list.length) { plBody.innerHTML = '<div class="empty">{T:projectList.empty}</div>'; return; }
  // Issue368: `Map` 셀 — 판정·툴팁·링크 규약을 카드 🗺️ 와 공유한다(같은 서버 필드, 같은 URL).
  //   미보유도 아이콘 자리를 비우지 않는다 — 카드는 목록이 아니라 "볼 것이 있을 때만" 뜨는
  //   자리지만, 표에서는 빈 칸이 "맵 없음"인지 "판정 실패"인지 구분되지 않기 때문이다.
  //   ⚠️ t() 인자는 리터럴 고정 — test_i18n_parity.py 의 참조 키 스캔이 정규식이다.
  const mapTitleOk = t('liveSessions.issueMapTitle');
  const mapTitleStale = t('liveSessions.issueMapStaleTitle');
  const mapTitleNone = t('projectList.mapNone');
  const rows = list.map(p => {
    const off = !!p.htm_off;
    const reason = off ? (p.htm_reason || 'hub off') : t('projectList.reasonOn');
    const mapCell = p.issue_map
      ? `<a class="pl-map-ico${p.issue_map_stale ? ' stale' : ''}" href="/issue-map?cwd=${encodeURIComponent(p.path)}" target="_blank" data-title="${escapeHtml(p.name)} — Issue Map" onclick="return fpmOpenInShell(event,this)" title="${escapeHtml(p.issue_map_stale ? mapTitleStale : mapTitleOk)}">🗺️</a>`
      : `<span class="pl-map-ico none" title="${escapeHtml(mapTitleNone)}" aria-hidden="true">🗺️</span>`;
    return `<tr data-path="${escapeHtml(p.path)}"${off ? ' class="htm-off"' : ''}${p.color ? ` style="--pl-color:${escapeHtml(p.color)}"` : ''} data-htm-reason="${escapeHtml(reason)}" title="${escapeHtml(t('projectList.rowTitle', {name: p.name}))}">
    <td class="pl-toggle"><button type="button" class="htm-tgl ${off ? 'off' : 'on'}" data-path="${escapeHtml(p.path)}" role="switch" aria-checked="${off ? 'false' : 'true'}" aria-label="${escapeHtml(t('projectList.toggleAria', {state: off ? 'off' : 'on', name: p.name}))}" title="${escapeHtml(t('projectList.toggleTitle', {reason: reason}))}"><span class="htm-tgl-knob"></span></button></td>
    <td class="pl-id">${escapeHtml(p.id)}</td>
    <td>${escapeHtml(p.emoji || '')} ${escapeHtml(p.name)}</td>
    <td>${escapeHtml(p.domain)}</td>
    <td class="pl-path"><code>${escapeHtml(p.path)}</code></td>
    <td>${escapeHtml(p.desc)}</td>
    <td class="pl-map"${p.color ? ` style="background:${escapeHtml(p.color)}"` : ''}>${mapCell}</td>
  </tr>`;
  }).join('');
  // 마스터 상태: 전부 on→on, 전부 off→off, 섞임→mixed
  const offCnt = list.filter(p => !!p.htm_off).length;
  const masterCls = offCnt === 0 ? 'on' : (offCnt === list.length ? 'off' : 'mixed');
  // mixed/off → 클릭 시 전체 on, on → 전체 off
  const masterTarget = masterCls === 'on' ? 'off' : 'on';
  const masterTitle = masterCls === 'mixed' ? t('projectList.masterMixed', {off: offCnt, total: list.length, target: masterTarget})
    : (masterCls === 'on' ? t('projectList.masterAllOn') : t('projectList.masterAllOff'));
  plBody.innerHTML = `<table class="pl-table"><thead><tr>
    <th class="pl-toggle" title="{T:projectList.toggleColTitle}"><button type="button" id="htm-tgl-all" class="htm-tgl ${masterCls}" data-target="${masterTarget}" role="switch" aria-checked="${masterCls === 'on' ? 'true' : 'false'}" aria-label="{T:projectList.masterAria}" title="${escapeHtml(masterTitle)}"><span class="htm-tgl-knob"></span></button><div class="pl-toggle-lbl">hub</div></th><th>{T:projectList.col.id}</th><th>{T:projectList.col.name}</th><th>Domain</th><th>{T:projectList.col.path}</th><th>{T:projectList.col.desc}</th><th class="pl-map">{T:projectList.col.map}</th>
  </tr></thead><tbody>${rows}</tbody></table>`;
}

async function openProjectList() {
  plModal.hidden = false;
  plBody.innerHTML = '<div class="empty">{T:common.loading}</div>';
  try {
    const r = await fetch('/projects-list?_=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    renderProjectList(data.projects || []);
  } catch (e) {
    plBody.innerHTML = '<div class="empty">❌ ' + escapeHtml(e.message) + '</div>';
  }
}
function closeProjectList() { plModal.hidden = true; }

document.getElementById('btn-project-list').addEventListener('click', openProjectList);
document.getElementById('pl-close').addEventListener('click', closeProjectList);
plModal.addEventListener('click', (e) => { if (e.target === plModal) closeProjectList(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !plModal.hidden) closeProjectList(); });

const plFootStatus = document.getElementById('pl-foot-status');
const plFootDefault = plFootStatus.textContent;
let plSelectedPath = null;  // 행 single-click 으로 선택된 프로젝트 경로

// 토글 버튼 → htm on/off 플립 (행 클릭=VSCode 열기와 분리)
plBody.addEventListener('click', async (e) => {
  const allTgl = e.target.closest('#htm-tgl-all');
  if (allTgl) {
    e.stopPropagation();
    allTgl.disabled = true;
    const target = allTgl.dataset.target || 'on';
    try {
      const r = await fetch('/htm-toggle-all', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({state: target})});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
      // 응답으로 모든 행 토글 + 헤더 마스터 재계산. 가장 간단·정확: 재조회 후 재렌더
      const lr = await fetch('/projects-list?_=' + Date.now(), {cache: 'no-store'});
      renderProjectList((await lr.json()).projects || []);
      plFootStatus.textContent = t('projectList.masterResult', {icon: (target === 'off' ? '🚫' : '✅'), target: target, count: j.count});
    } catch (err) {
      plFootStatus.textContent = t('projectList.toggleAllFail', {err: err.message});
      allTgl.disabled = false;
    }
    return;
  }
  const tgl = e.target.closest('.htm-tgl');
  if (tgl) {
    e.stopPropagation();
    tgl.disabled = true;
    try {
      const r = await fetch('/htm-toggle', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: tgl.dataset.path})});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
      const off = !!j.htm_off, reason = off ? (j.htm_reason || 'hub off') : t('projectList.reasonOn');
      tgl.classList.toggle('on', !off); tgl.classList.toggle('off', off);
      tgl.setAttribute('aria-checked', off ? 'false' : 'true');
      tgl.title = t('projectList.toggleTitle', {reason: reason});
      const tr = tgl.closest('tr');
      tr.classList.toggle('htm-off', off);
      tr.dataset.htmReason = reason;
      plFootStatus.textContent = (off ? '🚫 ' : '✅ ') + reason + ' (state=' + j.state + ')';
    } catch (err) {
      plFootStatus.textContent = t('projectList.toggleFail', {err: err.message});
    } finally { tgl.disabled = false; }
    return;
  }
  // Issue368: `Map` 아이콘 링크 클릭은 행 선택으로 새지 않게 한다 — 맵을 여는 동작과
  //   행 선택은 별개이고, 선택 상태가 바뀌면 footer 안내가 엉뚱하게 갱신된다.
  if (e.target.closest('a')) return;
  // 행 single-click → 선택만 (하이라이트). VSCode 열기는 더블클릭/버튼.
  const tr = e.target.closest('tr[data-path]');
  if (tr) {
    plBody.querySelectorAll('tr.pl-sel').forEach(r => r.classList.remove('pl-sel'));
    tr.classList.add('pl-sel');
    plSelectedPath = tr.dataset.path;
    plFootStatus.textContent = t('projectList.selected', {path: plSelectedPath});
  }
});

// Issue101/Issue131: 활성 세션 카드 클릭 동작.
//   - 세션 행(.live-item[data-sid]) 클릭 → 해당 Claude Code 세션 탭 포커스 (우선)
//   - 그 외 카드 영역(헤드 등) 클릭 → 해당 프로젝트 VSCode 폴더 열기 (기존 cdfv 효과)
//   버튼/링크·"외 N개 더"(data-sid 없음)는 제외.
document.getElementById('live-grid').addEventListener('click', (e) => {
  if (e.target.closest('button, a')) return;
  // Issue104: "외 N개 더"(또는 "접기") 클릭 → 해당 카드 확장/축소 토글. session/openProject 분기보다 우선.
  const moreRow = e.target.closest('.live-item.live-more');
  if (moreRow) {
    const card = moreRow.closest('.card.live[data-cwd]');
    if (card && card.dataset.cwd) {
      const cwd = card.dataset.cwd;
      const expanded = card.classList.toggle('expanded');
      if (expanded) expandedCards.add(cwd); else expandedCards.delete(cwd);
      const topic = moreRow.querySelector('.live-topic');
      if (topic) topic.textContent = expanded ? t('liveSessions.collapse') : t('liveSessions.moreCount', {n: (moreRow.dataset.more || '')});
    }
    return;
  }
  const row = e.target.closest('.live-item[data-sid]');
  if (row && row.dataset.sid) {
    // Issue177: 터미널(CLI) 세션은 VSCode 로 포커스 불가 → openSession(vscode URI) 호출 안 함.
    //   기존엔 출처 무관하게 openSession 을 호출해 iTerm 세션도 VSCode 가 잘못 열렸음.
    // Issue219: 터미널 세션은 포커스 대신 JSONL transcript 뷰어(/s/{h}/{sid})로 대화 내용 표시.
    if (row.dataset.origin === 'terminal') {
      const topicEl = row.querySelector('.live-topic');
      openSessionViewer(row.dataset.url, topicEl ? topicEl.textContent : '세션');
      return;
    }
    openSession(row.dataset.cwd, row.dataset.sid);
    return;
  }
  const card = e.target.closest('.card.live[data-cwd]');
  if (card && card.dataset.cwd) openProject(card.dataset.cwd);
});

// 행 더블클릭 → cdfv 효과: 해당 프로젝트를 VSCode 로 열기
plBody.addEventListener('dblclick', (e) => {
  if (e.target.closest('.htm-tgl, #htm-tgl-all')) return;
  const tr = e.target.closest('tr[data-path]');
  if (tr) openProject(tr.dataset.path);
});

// 행/토글 hover·focus → 푸터 status bar 에 htm 상태 사유 표시
function plShowReason(el) {
  const tr = el.closest('tr[data-path]'); if (!tr) return;
  const off = tr.classList.contains('htm-off');
  plFootStatus.textContent = (off ? '🚫 ' : '✅ ') + (tr.dataset.htmReason || '');
}
plBody.addEventListener('mouseover', (e) => plShowReason(e.target));
plBody.addEventListener('mouseout', (e) => { if (e.target.closest('tr[data-path]')) plFootStatus.textContent = plFootDefault; });
plBody.addEventListener('focusin', (e) => plShowReason(e.target));
plBody.addEventListener('focusout', () => { plFootStatus.textContent = plFootDefault; });

// 'VSCode로 열기' — 선택된 프로젝트를 VSCode 로 열기 (더블클릭과 동일)
document.getElementById('pl-edit').addEventListener('click', () => {
  if (!plSelectedPath) { toast(t('projectList.selectFirst'), 'err'); return; }
  openProject(plSelectedPath);
});

// Issue168: 설정 모달 (3탭) — ⚙️ 클릭 시 GET /api/settings → 폼 렌더 → 변경 diff 저장
const setModal = document.getElementById('set-modal');
let setSchema = [], setInitial = {}, setValues = {}, setDefaults = {}, setMtime = 0;
// 모달 뷰 언어 (기본=서버 language). 저장값 미변경 — 다국어 "보기" 전용.
let setLang = (window.__lang === 'ko' || window.__lang === 'en') ? window.__lang : 'en';
// 모달 텍스트 번역: 주입된 양쪽 카탈로그(window.__i18n_all)에서 setLang 조회, fb 폴백.
function ttf(key, fb) {
  const c = (window.__i18n_all && window.__i18n_all[setLang]) || window.__i18n || {};
  return (c[key] != null) ? c[key] : (fb != null ? fb : key);
}

function setEsc(html) {
  return String(html).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function setBadge(apply) {
  const m = {auto: ['b-auto', ttf('settings.applyBadge.auto')], hook: ['b-hook', ttf('settings.applyBadge.hook')], restart: ['b-restart', ttf('settings.applyBadge.restart')]}[apply] || ['',''];
  const tipMap = {auto: 'settings.apply.auto', hook: 'settings.apply.hook', restart: 'settings.apply.restart'};
  const tip = (apply && tipMap[apply]) ? ttf(tipMap[apply]) : '';
  return `<span class="set-badge ${m[0]}" data-tip="${setEsc(tip)}">${m[1]}</span>`;
}
function setReadKey(key) {
  const s = setSchema.find(x => x.key === key); if (!s) return undefined;
  const el = document.getElementById('setf-' + key); if (!el) return undefined;
  if (s.widget === 'toggle') return el.classList.contains('on');
  if (s.widget === 'number') return parseInt(el.value, 10) || 0;
  if (s.widget === 'select') {
    if (el.value === '__custom__') { const c = document.getElementById('setf-' + key + '-c'); return c ? c.value.trim() : ''; }
    return el.value;
  }
  return el.value.trim();
}
// 연필(✏️ 기본값 대비 변경) 라이브 갱신
function setRefreshPencil(key) {
  const el = document.getElementById('setf-' + key); if (!el) return;
  const row = el.closest('.set-row'); if (!row) return;
  const lab = row.querySelector('.set-key'); if (!lab) return;
  const changed = JSON.stringify(setReadKey(key)) !== JSON.stringify(setDefaults[key]);
  const p = lab.querySelector('.set-pencil');
  if (changed && !p) lab.insertAdjacentHTML('beforeend', ` <span class="set-pencil" title="${setEsc(ttf('settings.changedFromDefault', setLang === 'ko' ? '기본값에서 변경됨' : 'Changed from default'))}">✏️</span>`);
  else if (!changed && p) p.remove();
}
function setRenderField(s, val) {
  const id = 'setf-' + s.key;
  if (s.widget === 'toggle') {
    const on = val === true;
    return `<button type="button" class="set-sw ${on?'on':''}" id="${id}" data-key="${s.key}" data-type="toggle" role="switch" aria-checked="${on}"><span class="set-sw-knob"></span></button>`;
  }
  if (s.widget === 'select') {
    const opts = s.options.slice();
    const isCustom = s.allow_custom && val && !opts.includes(val);
    let html = `<select id="${id}" data-key="${s.key}" data-type="select">`;
    for (const o of opts) html += `<option value="${setEsc(o)}" ${o===val?'selected':''}>${setEsc(o)}</option>`;
    if (s.allow_custom) html += `<option value="__custom__" ${isCustom?'selected':''}>${ttf('settings.customApp')}</option>`;
    html += '</select>';
    if (s.allow_custom) html += ` <input type="text" id="${id}-c" data-key="${s.key}" data-type="custom" value="${isCustom?setEsc(val):''}" placeholder="/Applications/X.app" style="${isCustom?'':'display:none'};width:13em">`;
    return html;
  }
  if (s.widget === 'number') {
    return `<input type="number" id="${id}" data-key="${s.key}" data-type="number" min="${s.min||0}" value="${setEsc(val)}">`;
  }
  return `<input type="text" id="${id}" data-key="${s.key}" data-type="text" value="${setEsc(val)}" placeholder="${s.optional?ttf('settings.optional'):''}">`;
}
function setRenderForm() {
  for (const tab of ['basic','session','advanced']) {
    const pane = document.getElementById('set-pane-' + tab);
    // advanced 탭은 경고 배너 보존 → 배너 이후만 재구성
    const warn = pane.querySelector('.set-warn');
    pane.innerHTML = '';
    if (warn) pane.appendChild(warn);
    for (const s of setSchema.filter(x => x.tab === tab)) {
      const row = document.createElement('div');
      row.className = 'set-row' + (s.deprecated ? ' set-deprecated' : '');
      if (s.deprecated) row.style.opacity = '0.55';
      const changed = JSON.stringify(setValues[s.key]) !== JSON.stringify(setDefaults[s.key]);
      const pencil = changed ? ` <span class="set-pencil" title="${setEsc(ttf('settings.changedFromDefault', setLang === 'ko' ? '기본값에서 변경됨' : 'Changed from default'))}">✏️</span>` : '';
      // 라벨: ko 카탈로그에 settings.label.<key> 있으면 한국어 표시, 없으면(=en 뷰·미번역) 원본 키
      //   (원본 키는 `_` 숨김 + 복붙 시 실제 키 보존 — Issue208)
      const koLbl = ttf('settings.label.' + s.key, '');
      const keyHtml = koLbl ? setEsc(koLbl) : setEsc(s.key).replaceAll('_','<span class="set-us">_</span>');
      row.innerHTML = `<label class="set-key" for="setf-${s.key}" title="${setEsc(s.key + ' — ' + (s.comment||''))}">${keyHtml}${pencil}${s.deprecated?' <span style="font-size:0.75em;color:#c60">(deprecated)</span>':''}</label>`
        + `<span class="set-input">${setRenderField(s, setValues[s.key])}</span>`
        + `<span class="set-desc" data-tip="${setEsc(s.comment||'')}">?</span>`
        + setBadge(s.apply);
      pane.appendChild(row);
    }
  }
  // 토글 스위치 클릭
  setModal.querySelectorAll('.set-sw').forEach(b => b.addEventListener('click', () => {
    // Issue272: browser_tab_reuse 는 Chrome/Edge/Safari 전용 — 미지원 브라우저면 토글 차단 + 팝업 안내
    if (b.dataset.key === 'browser_tab_reuse' && !setTabReuseSupported()) {
      toast(setTabReuseGateMsg(), 'err');
      return;
    }
    const on = !b.classList.contains('on');
    b.classList.toggle('on', on); b.setAttribute('aria-checked', on);
    setRefreshPencil(b.dataset.key);
  }));
  // 사용자 지정 select → 텍스트 토글
  setModal.querySelectorAll('select[data-type="select"]').forEach(sel => sel.addEventListener('change', () => {
    const c = document.getElementById('setf-' + sel.dataset.key + '-c');
    if (c) c.style.display = sel.value === '__custom__' ? '' : 'none';
  }));
  // 연필(기본값 대비) 라이브 갱신 — 토글 외 입력/선택/커스텀
  setModal.querySelectorAll('#set-modal [data-key]').forEach(el => {
    const k = el.dataset.key;
    el.addEventListener('input', () => setRefreshPencil(k));
    el.addEventListener('change', () => setRefreshPencil(k));
    // Issue272: default_browser 변경 시 browser_tab_reuse 게이트 라이브 재판정
    if (k === 'default_browser') {
      el.addEventListener('input', setGateTabReuse);
      el.addEventListener('change', setGateTabReuse);
    }
  });
  setGateTabReuse();
  // Issue153: advanced 경고 배너는 위험 조합일 때만 표시 (정적 상시노출 → 조건부)
  ['bind_host', 'advertise_host'].forEach(k => {
    const el = document.getElementById('setf-' + k);
    if (el) el.addEventListener('input', setUpdateWarn);
  });
  setUpdateWarn();
}
// Issue272: browser_tab_reuse 게이팅 — AppleScript 탭 제어는 Chrome/Edge/Safari 만 지원
//   (Firefox·커스텀 .app 은 탭 제어 사전 부재 → helper 가 open 폴백 = 재사용 무의미).
//   미지원 브라우저 선택 시 토글을 시각적 비활성(dim) + 클릭 시 toast 팝업 안내.
function setTabReuseSupported() {
  const v = String(setReadKey('default_browser') || '').toLowerCase();
  return v === 'chrome' || v === 'edge' || v === 'safari';
}
function setTabReuseGateMsg() {
  return ttf('settings.tabReuseGate', setLang === 'ko'
    ? 'browser_tab_reuse 는 Chrome/Edge/Safari 에서만 활성화됩니다 — 현재 브라우저는 탭 제어(AppleScript) 미지원'
    : 'browser_tab_reuse is only available for Chrome/Edge/Safari — current browser has no tab-control scripting');
}
function setGateTabReuse() {
  const sw = document.getElementById('setf-browser_tab_reuse');
  if (!sw) return;
  const ok = setTabReuseSupported();
  sw.style.opacity = ok ? '' : '0.35';
  sw.style.cursor = ok ? '' : 'not-allowed';
  sw.title = ok ? '' : setTabReuseGateMsg();
}
// Issue153: bind_host 에 0.0.0.0 포함 + advertise_host 빈값일 때만 경고 표시.
function setUpdateWarn() {
  const warn = document.querySelector('#set-pane-advanced .set-warn');
  if (!warn) return;
  const bh = (document.getElementById('setf-bind_host') || {}).value || '';
  const ah = ((document.getElementById('setf-advertise_host') || {}).value || '').trim();
  // bind_host 는 "0.0.0.0" 또는 "[127.0.0.1, 0.0.0.0]" 형태 — 구분자 정규화 후 토큰 일치
  const bhNorm = ' ' + bh.split('[').join(' ').split(']').join(' ').split(',').join(' ') + ' ';
  const hasAny = bhNorm.indexOf(' 0.0.0.0 ') >= 0;
  warn.style.display = (hasAny && !ah) ? '' : 'none';
}
function setReadForm() {
  // 현재 폼 값 수집 → {key: value}
  const cur = {};
  for (const s of setSchema) {
    const el = document.getElementById('setf-' + s.key);
    if (!el) continue;
    if (s.widget === 'toggle') cur[s.key] = el.classList.contains('on');
    else if (s.widget === 'number') cur[s.key] = parseInt(el.value, 10) || 0;
    else if (s.widget === 'select') {
      if (el.value === '__custom__') { const c = document.getElementById('setf-' + s.key + '-c'); cur[s.key] = c ? c.value.trim() : ''; }
      else cur[s.key] = el.value;
    } else cur[s.key] = el.value.trim();
  }
  return cur;
}
function setApplyLangButtons() {
  document.querySelectorAll('#set-lang button').forEach(b => b.classList.toggle('active', b.dataset.lang === setLang));
}
async function openSettings() {
  try {
    const r = await fetch('/api/settings?lang=' + encodeURIComponent(setLang));
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    setSchema = j.schema; setInitial = j.values; setValues = Object.assign({}, j.values);
    setDefaults = j.defaults || {}; setMtime = j.mtime;
    setApplyLangButtons();
    setRenderForm();
    setModal.hidden = false;
  } catch (e) { toast(t('settings.loadFail', {err: e.message}), 'err'); }
}
// KO/EN 뷰 토글 — 저장값 미변경. 현재 편집값 보존한 채 언어별 comment 재-fetch + 정적 chrome 재번역.
async function switchLang(l) {
  if (l === setLang || (l !== 'ko' && l !== 'en')) return;
  const cur = setModal.hidden ? {} : setReadForm();
  setLang = l; setApplyLangButtons();
  setModal.querySelectorAll('[data-i18n]').forEach(el => { const k = el.getAttribute('data-i18n'); const v = ttf(k); if (v != null) el.textContent = v; });
  try {
    const r = await fetch('/api/settings?lang=' + encodeURIComponent(l));
    const j = await r.json();
    if (r.ok) { setSchema = j.schema; setDefaults = j.defaults || setDefaults; setValues = Object.assign({}, j.values, cur); setRenderForm(); }
  } catch (e) { /* 폼 재-fetch 실패 시 정적 chrome 번역만 반영 */ }
}
function closeSettings() { setModal.hidden = true; }
async function saveSettings() {
  const cur = setReadForm();
  const diff = {};
  for (const k in cur) if (JSON.stringify(cur[k]) !== JSON.stringify(setInitial[k])) diff[k] = cur[k];
  if (Object.keys(diff).length === 0) { toast(t('settings.noChange'), 'ok'); closeSettings(); return; }
  try {
    const r = await fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({values: diff, mtime: setMtime})});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    toast(t('settings.saved'), 'ok');
    if (j.restart_required && j.restart_required.length)
      toast(t('settings.restartNeeded', {keys: j.restart_required.join(', ')}), 'err');
    closeSettings();
  } catch (e) { toast(t('settings.saveFail', {err: e.message}), 'err'); }
}
// Issue168: 배지 hover → 즉시 풍선 도움말 (배지 위쪽, modal-body overflow 비절단)
const setTip = document.getElementById('set-tip');
function setTipShow(badge) {
  const tip = badge.getAttribute('data-tip'); if (!tip) return;
  setTip.textContent = tip; setTip.hidden = false;
  const br = badge.getBoundingClientRect();
  const tw = setTip.offsetWidth, th = setTip.offsetHeight, gap = 9;
  let left = br.left + br.width/2 - tw/2;
  left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
  let top = br.top - th - gap;            // 기본: 배지 위쪽
  if (top < 8) top = br.bottom + gap;     // 위 공간 부족 시에만 아래로
  setTip.style.left = left + 'px';
  setTip.style.top = top + 'px';
  setTip.style.setProperty('--tip-arrow', (br.left + br.width/2 - left) + 'px');
}
function setTipHide() { setTip.hidden = true; }
setModal.addEventListener('mouseover', e => { const b = e.target.closest('.set-badge, .set-desc'); if (b) setTipShow(b); });
setModal.addEventListener('mouseout', e => { if (e.target.closest('.set-badge, .set-desc')) setTipHide(); });
// Issue281: 활성 세션 카드의 🆚/모델 배지 툴팁 — .card{overflow:hidden}에 안 잘리게 body 직속 #live-tip 사용
const liveTip = document.getElementById('live-tip');
function liveTipShow(badge) {
  // Issue384: 세션 작업 메뉴가 열려 있는 동안은 툴팁을 띄우지 않는다. 5초 reload 가 행을 다시 그리면
  //   커서 아래 요소가 교체돼 mouseover 가 재발화하고, sidMenuOpen 이 꺼 둔 툴팁이 메뉴 위로 되살아난다(실측).
  if (!sidMenu.hidden) return;
  const tip = badge.getAttribute('data-tip'); if (!tip) return;
  liveTip.textContent = tip;
  // Issue369: data-tip-sid 가 있으면 세션 ID 를 둘째 줄에 붙인다(모노스페이스·디밍).
  //   textContent + DOM 조립만 사용 — innerHTML 금지(topic 은 임의 문자열이다).
  const sid = badge.getAttribute('data-tip-sid');
  if (sid) { const el = document.createElement('span'); el.className = 'tip-sid'; el.textContent = sid; liveTip.appendChild(el); }
  liveTip.hidden = false;
  const br = badge.getBoundingClientRect();
  const tw = liveTip.offsetWidth, th = liveTip.offsetHeight, gap = 7;
  let left = br.left + br.width/2 - tw/2;
  left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
  let top = br.top - th - gap;            // 기본: 배지 위쪽
  if (top < 8) top = br.bottom + gap;     // 위 공간 부족 시에만 아래로
  liveTip.style.left = left + 'px';
  liveTip.style.top = top + 'px';
}
function liveTipHide() { liveTip.hidden = true; }
// Issue369: .live-item 편입 — 행 네이티브 title 이 남아 있으면 버튼 위에서도 커서 옆에 떠 가림이 재발한다
// Issue384: .copy-sid 는 목록에서 뺐다 — 그 버튼은 이제 툴팁이 아니라 hover 메뉴를 띄운다(둘은 같은 자리를 다툰다)
const LIVE_TIP_SEL = '.live-origin[data-tip], .live-model[data-tip], .live-badge[data-tip], '
  + '.card-close[data-tip], .approve-btn[data-tip], .live-item[data-tip]';
document.addEventListener('mouseover', e => { const b = e.target.closest(LIVE_TIP_SEL); if (b) liveTipShow(b); });
document.addEventListener('mouseout', e => { if (e.target.closest(LIVE_TIP_SEL)) liveTipHide(); });
document.getElementById('btn-settings').addEventListener('click', openSettings);
document.getElementById('set-lang').addEventListener('click', e => {
  const b = e.target.closest('button[data-lang]'); if (b) switchLang(b.dataset.lang);
});
document.getElementById('set-close').addEventListener('click', () => { setTipHide(); closeSettings(); });
document.getElementById('set-cancel').addEventListener('click', closeSettings);
document.getElementById('set-save').addEventListener('click', saveSettings);
setModal.addEventListener('click', e => { if (e.target === setModal) closeSettings(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !setModal.hidden) closeSettings(); });
document.getElementById('set-tabs').addEventListener('click', e => {
  const t = e.target.closest('.set-tab'); if (!t) return;
  setModal.querySelectorAll('.set-tab').forEach(x => x.classList.toggle('active', x === t));
  setModal.querySelectorAll('.set-pane').forEach(p => p.classList.toggle('active', p.dataset.pane === t.dataset.tab));
});
document.getElementById('set-open-file').addEventListener('click', async () => {
  try {
    const r = await fetch('/open-settings-yml', {method: 'POST'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    toast(t('settings.fileOpened'), 'ok');
    closeSettings();
  } catch (e) { toast('❌ ' + e.message, 'err'); }
});

// Issue115: dashboard 데이터 파일 자동 리프레쉬 폴링
(async () => {
  let lastMtimes = {};
  const params = new URLSearchParams(window.location.search);
  const cwd = params.get('cwd') || '';
  if (!cwd) return; // dashboard 진입 시 cwd가 필요함

  setInterval(async () => {
    try {
      const r = await fetch(`/api/file-stat?cwd=${encodeURIComponent(cwd)}`);
      if (!r.ok) return;
      const data = await r.json();
      let changed = false;

      for (const [fname, fstat] of Object.entries(data.files || {})) {
        if (lastMtimes[fname] !== undefined && lastMtimes[fname] !== fstat.mtime_ts) {
          changed = true;
          break;
        }
        lastMtimes[fname] = fstat.mtime_ts;
      }

      if (changed) {
        location.reload();
      }
    } catch (e) {
      // 폴링 실패 무시
    }
  }, 5000);
})();

// Issue160: 섹션 접기/펼치기 — 활성 세션/dashboard/hub 문서 3개 섹션을 헤더만 남기고 접음.
// 상태는 localStorage 영속. reload() 재렌더는 grid innerHTML 만 교체하므로
// <section> 의 sec-collapsed 클래스는 유지됨 (Issue104 expandedCards 와 동일 원리).
const SEC_COLLAPSE_KEY = 'hubSecCollapsed';
function secCollapseState() {
  try { return JSON.parse(localStorage.getItem(SEC_COLLAPSE_KEY) || '{}'); } catch (e) { return {}; }
}
function applySecCollapse() {
  const st = secCollapseState();
  document.querySelectorAll('.sec-toggle').forEach(btn => {
    const sec = document.getElementById(btn.dataset.sec);
    if (!sec) return;
    const on = !!st[btn.dataset.sec];
    sec.classList.toggle('sec-collapsed', on);
    btn.textContent = on ? '▸' : '▾';
    btn.title = on ? t('common.expandSection') : t('common.collapseSection');
  });
}
document.querySelectorAll('.sec-toggle').forEach(btn => {
  btn.addEventListener('click', e => {
    e.stopPropagation();
    const st = secCollapseState();
    st[btn.dataset.sec] = !st[btn.dataset.sec];
    try { localStorage.setItem(SEC_COLLAPSE_KEY, JSON.stringify(st)); } catch (e2) {}
    applySecCollapse();
  });
});
applySecCollapse();

reload();
setInterval(reload, 5000);
</script>
</body>
</html>
"""


# Issue17 Phase 1: SPA shell — Mode A (response) 컴포넌트만. Mode B/C는 Phase 2~3 확장
SESSION_SHELL_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<link rel="icon" href="/fpm-icon.png">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<style>
/* Issue28: 흰색 배경 고정. @media prefers-color-scheme dark override 제거 (다중 탭 일관성). */
:root { --fg:#111; --bg:#fff; --muted:#666; --border:#ddd; --code-bg:#f5f5f5; --card:#fafafa; --accent:#2a8; --danger:#c33; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
  background: var(--bg); color: var(--fg); margin: 0; padding: 0; line-height: 1.7; }
/* Issue28: peacock.color (파스텔) → 어두운 글자 기본. 진한 헤더가 필요한 프로젝트는 Projects.md 컬러 조정으로 처리 */
header.sess { background: {COLOR}; color: #1a1a1a; padding: 0.8rem 1.5rem; display: flex; justify-content: space-between; align-items: center; }
header.sess h1 { margin: 0; font-size: 1rem; }
header.sess h1 code { color: var(--fg); background: rgba(255,255,255,0.92); padding: 0.05rem 0.35rem; border-radius: 3px; }
header.sess .meta { font-size: 0.8em; opacity: 0.9; }
/* Issue280: 세션 GC 버튼 (헤더+푸터 공용) */
.gc-btn { background: #c33; color: #fff; border: 1px solid #a22; border-radius: 6px; padding: 0.25rem 0.7rem; cursor: pointer; font-size: 0.85rem; white-space: nowrap; }
.gc-btn:hover { background: #a22; }
.gc-btn:disabled { opacity: 0.5; cursor: not-allowed; }
header.sess .hdr-right { display: flex; align-items: center; gap: 0.6rem; }
footer.sess-foot { padding: 0.8rem 1.5rem 1.4rem; display: flex; justify-content: flex-end; }
.status { padding: 0.3rem 1.5rem; font-size: 0.8em; color: var(--muted); border-bottom: 1px solid var(--border); }
.status.connected { color: var(--accent); }
.status.polling { color: #d80; }
.status.error { color: var(--danger); }
main#content { padding: 1.5rem; max-width: 980px; margin: 0 auto; }
main#content pre { background: var(--code-bg); padding: 1rem; border-radius: 4px; overflow-x: auto; }
main#content code { background: var(--code-bg); padding: 0.1rem 0.3rem; border-radius: 3px; }
main#content table { border-collapse: collapse; width: 100%; }
main#content th, main#content td { border: 1px solid var(--border); padding: 0.4rem 0.6rem; }
main#content th { background: var(--code-bg); }
/* Issue219: 터미널 세션 JSONL transcript */
.transcript .ts-note { color: var(--muted); font-size: 0.85rem; font-style: italic; margin: 0 0 1rem; }
.ts-turn { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 8px; border: 1px solid var(--border); }
.ts-turn.ts-user { background: rgba(120,120,180,0.08); }
.ts-turn.ts-asst { background: rgba(120,180,120,0.06); }
.ts-role { font-weight: 600; font-size: 0.85rem; margin-bottom: 0.4rem; opacity: 0.8; }
.ts-text { white-space: pre-wrap; word-break: break-word; background: transparent !important; padding: 0 !important; margin: 0.3rem 0; font-family: inherit; }
.ts-think { margin: 0.3rem 0; font-size: 0.85rem; color: var(--muted); }
.ts-think summary { cursor: pointer; }
.ts-think pre { white-space: pre-wrap; word-break: break-word; }
.ts-tool { font-family: ui-monospace, monospace; font-size: 0.82rem; color: var(--muted); margin: 0.15rem 0; }
/* Issue18 Phase 2: form */
.q-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.2rem; margin-bottom: 1rem; }
.q-card .q-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.6rem; }
.q-card .q-header { font-size: 0.75em; padding: 0.15rem 0.5rem; border-radius: 12px; background: var(--code-bg); color: var(--muted); }
.q-card .q-title { font-weight: 600; font-size: 1rem; }
.q-opt { display: flex; align-items: flex-start; gap: 0.6rem; padding: 0.6rem 0.7rem; border: 1px solid var(--border); border-radius: 6px; margin-bottom: 0.4rem; cursor: pointer; transition: background 0.1s; }
.q-opt:hover { background: var(--code-bg); }
.q-opt input { margin-top: 0.25rem; transform: scale(1.2); cursor: pointer; }
.q-opt-body .q-opt-label { font-weight: 500; }
.q-opt-body .q-opt-desc { font-size: 0.85em; color: var(--muted); margin-top: 0.15rem; }
.form-actions { display: flex; gap: 0.6rem; align-items: center; margin-top: 1rem; }
.btn-submit { background: var(--accent); color: white; border: none; padding: 0.6rem 1.4rem; border-radius: 6px; font-size: 0.95rem; cursor: pointer; }
.btn-submit:hover { filter: brightness(1.1); }
.btn-submit:disabled { background: var(--muted); cursor: not-allowed; }
.form-msg { font-size: 0.85em; color: var(--muted); }
.form-msg.ok { color: var(--accent); }
.form-msg.err { color: var(--danger); }
/* Issue26: answer paste-back placeholder */
.answer-placeholder { border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.2rem; background: var(--card); }
.answer-placeholder p { margin: 0.3rem 0; }
.answer-actions { display: flex; gap: 0.6rem; align-items: center; margin: 0.7rem 0; }
.copy-btn { background: var(--accent); color: white; border: none; padding: 0.45rem 0.9rem; border-radius: 5px; font-size: 0.9rem; cursor: pointer; }
.copy-btn:hover { filter: brightness(1.1); }
.copy-btn:disabled { background: var(--muted); cursor: not-allowed; }
.copy-msg { font-size: 0.85em; color: var(--muted); }
.copy-msg.ok { color: var(--accent); }
.copy-msg.err { color: var(--danger); }
.answer-json { background: var(--code-bg); padding: 0.7rem 1rem; border-radius: 6px; font-size: 0.85em; max-height: 320px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
/* Issue: field type 확장 (text/textarea/number/slider/date) */
.q-field { display: flex; flex-direction: column; gap: 0.35rem; }
.q-field input[type=text], .q-field input[type=number], .q-field input[type=date], .q-field textarea {
  width: 100%; padding: 0.55rem 0.7rem; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); color: var(--fg); font-size: 0.95rem; font-family: inherit;
}
.q-field textarea { min-height: 5rem; resize: vertical; }
.q-field input[type=range] { width: 100%; }
.q-field .q-slider-row { display: flex; align-items: center; gap: 0.7rem; }
.q-field .q-slider-val { min-width: 3rem; text-align: right; font-variant-numeric: tabular-nums; color: var(--accent); font-weight: 600; }
.q-field .q-hint { font-size: 0.8em; color: var(--muted); }
.q-required-mark { color: var(--danger); margin-left: 0.2rem; }
/* Issue19 Phase 3: dashboard widgets */
.dash-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; grid-auto-flow: row dense; align-items: start; }
/* Issue77 (글로벌 .claude#Issue91 짝): width:full 위젯 — 그리드 전폭 1컬럼 행 점유 */
.dash-grid > .w-full { grid-column: 1 / -1; }
.widget { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.2rem; }
.widget .w-title { font-weight: 600; font-size: 0.95rem; margin-bottom: 0.6rem; }
.widget.progress .bar { background: var(--border); height: 8px; border-radius: 4px; overflow: hidden; margin: 0.4rem 0; }
.widget.progress .bar-fill { background: var(--accent); height: 100%; transition: width 0.3s; }
.widget.progress .pct { font-size: 0.85em; color: var(--muted); }
.widget.table table { border-collapse: collapse; width: 100%; font-size: 0.9em; }
.widget.table th, .widget.table td { border: 1px solid var(--border); padding: 0.35rem 0.55rem; text-align: left; }
.widget.table th { background: var(--code-bg); }
.widget.checklist ul { list-style: none; padding: 0; margin: 0; }
.widget.checklist li { padding: 0.25rem 0; }
.widget.checklist li.done { color: var(--muted); text-decoration: line-through; }
.widget.text pre { background: var(--code-bg); padding: 0.6rem; border-radius: 4px; overflow-x: auto; margin: 0; }
.widget.unknown { color: var(--danger); font-style: italic; }
/* Issue24 Phase 1: chart/log/diff/timer/badge widgets */
.widget.chart svg { width: 100%; height: 60px; display: block; }
.widget.chart .chart-bar { fill: var(--accent); }
.widget.chart .chart-line { fill: none; stroke: var(--accent); stroke-width: 2; }
.widget.chart .chart-dot { fill: var(--accent); }
.widget.chart .chart-label { font-size: 0.85em; color: var(--muted); margin-top: 0.3rem; }
.widget.log .log-box { background: var(--code-bg); padding: 0.5rem; border-radius: 4px; font-family: monospace; font-size: 0.85em; max-height: 200px; overflow-y: auto; white-space: pre-wrap; }
.widget.log .log-line { padding: 0.1rem 0; border-bottom: 1px solid var(--border); }
.widget.log .log-line:last-child { border-bottom: none; }
.widget.diff .diff-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
.widget.diff .diff-col { background: var(--code-bg); padding: 0.5rem; border-radius: 4px; font-family: monospace; font-size: 0.85em; white-space: pre-wrap; overflow-x: auto; }
.widget.diff .diff-col.before { border-left: 3px solid #c33; }
.widget.diff .diff-col.after { border-left: 3px solid #2a2; }
.widget.diff .diff-label { font-size: 0.75em; color: var(--muted); margin-bottom: 0.3rem; }
.widget.timer .timer-value { font-size: 1.8em; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--accent); }
.widget.timer .timer-mode { font-size: 0.8em; color: var(--muted); }
.widget.badge { display: flex; align-items: center; gap: 0.6rem; }
.widget.badge .badge-dot { width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0; background: var(--muted); }
.widget.badge .badge-icon { width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0; }  /* prj3#Issue438: icon 필드 렌더 */
.widget.badge .badge-label { font-weight: 500; }
.widget.badge.ok .badge-dot { background: #2a2; }
.widget.badge.warn .badge-dot { background: #d80; }
.widget.badge.err .badge-dot { background: #c33; }
.widget.badge.info .badge-dot { background: #29c; }
/* Issue24 Phase 3: actionable widget wrapper */
.widget-actionable { cursor: pointer; position: relative; transition: transform 0.1s, box-shadow 0.1s; }
.widget-actionable:hover { transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
.widget-actionable:hover::after { content: '↗'; position: absolute; top: 0.4rem; right: 0.6rem; color: var(--accent); font-size: 0.9em; opacity: 0.7; }
.widget-actionable.action-ok > .widget { outline: 2px solid #2a2; }
.widget-actionable.action-err > .widget { outline: 2px solid #c33; }
/* Issue50: dashboard 종료 컨트롤 버튼 */
.dash-controls { display: flex; gap: 0.6rem; margin: 0.5rem 0 1rem; flex-wrap: wrap; }
.dash-ctrl { padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; font-size: 0.85em; border: 1px solid; }
.dash-ctrl.stop { background: #c33; color: white; border-color: #c33; }
.dash-ctrl.stop:hover { background: #a22; }
.dash-ctrl.kill { background: #555; color: white; border-color: #555; }
.dash-ctrl.kill:hover { background: #333; }
.dash-ctrl.refresh { background: #2a6; color: white; border-color: #2a6; }
.dash-ctrl.refresh:hover { background: #185; }
.dash-ctrl:disabled { opacity: 0.5; cursor: not-allowed; }
/* Issue63: dashboard status 배지 + 메타 칩 — runner 생존 가시화 */
.dash-head { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; margin: 0 0 0.5rem; }
.dash-head h2 { margin: 0; }
.dash-status { font-size: 0.82em; font-weight: 600; padding: 0.25rem 0.75rem; border-radius: 999px; border: 1px solid; white-space: nowrap; }
.dash-status.st-running { background: rgba(42,138,42,0.13); color: #2a8a2a; border-color: #2a8a2a; }
.dash-status.st-stopped { background: rgba(204,51,51,0.13); color: #cc3333; border-color: #cc3333; }
.dash-status.st-done    { background: rgba(41,108,221,0.13); color: #296cdd; border-color: #296cdd; }
.dash-status.st-unknown { background: var(--code-bg); color: var(--muted); border-color: var(--border); }
.dash-status .st-deadnote { margin-left: 0.45rem; font-weight: 700; }
.dash-meta { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0 0 0.95rem; }
.dash-meta .chip { font-size: 0.74em; color: var(--muted); background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px; padding: 0.16rem 0.5rem; font-family: monospace; }
</style>
</head>
<body>
<header class="sess"><h1>📁 {NAME} — session <code>{SID}</code></h1><span class="hdr-right"><span class="meta">mode <span id="mode-tag">?</span></span><button class="gc-btn" data-gc title="세션 GC — 세션·터미널 pane 강제 종료">🗑 세션 GC</button></span></header>
<div class="status" id="status">초기 로드 중...</div>
<main id="content"><em>대기 중...</em></main>
<footer class="sess-foot"><button class="gc-btn" data-gc title="세션 GC — 세션·터미널 pane 강제 종료">🗑 세션 GC</button></footer>
<script>
const CWD_HASH = "{CWD_HASH}";
const SID = "{SID}";
const TOKEN = "{TOKEN}";
const CWD_Q = "{CWD_Q}";
const NAME_LABEL = (document.querySelector('header.sess h1') || {}).textContent || 'session';
// Issue29 Phase 6: PREVIEW mode (ephemeral, no SSE, no broadcast)
const PREVIEW = "{PREVIEW}" === "1";
// Issue28 fix: string concat (Python .replace 가 ${CWD_HASH} 의 {CWD_HASH} 도 치환하여 $ea6aeb24 되는 버그 회피)
const ROOT_PREFIX = PREVIEW ? '/preview/' : '/s/';
const DATA_URL = ROOT_PREFIX + CWD_HASH + '/' + SID + '/data?token=' + encodeURIComponent(TOKEN);
const ANSWER_URL = '/s/' + CWD_HASH + '/' + SID + '/answer?token=' + encodeURIComponent(TOKEN);
const ACTION_URL = '/s/' + CWD_HASH + '/' + SID + '/action?token=' + encodeURIComponent(TOKEN);
const SSE_URL = '/events?cwd=' + CWD_Q + '&token=' + encodeURIComponent(TOKEN) + '&sid=' + encodeURIComponent(SID);
const statusEl = document.getElementById('status');
const contentEl = document.getElementById('content');
const modeEl = document.getElementById('mode-tag');

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function parseJSON(s) {
  if (typeof s !== 'string') return s;
  try { return JSON.parse(s); } catch (e) { return null; }
}

""" + FORM_JS + WIDGET_JS + DASHBOARD_JS + r"""

let lastSig = null;
// ___pm Issue82: reload() 가 status 를 갱신할 때 SSE 연결 상태를 존중.
// 종전엔 reload() 성공 시 무조건 'status connected' 로 덮어써, polling fallback 이
// 3초마다 reload() 를 돌리면 SSE 끊김 배지(🟡/🔴)가 즉시 사라졌다.
let connState = 'sse';  // 'sse' | 'polling' | 'error' — setStatus() 가 동기 갱신
function showRefreshed(prefix) {
  const t = new Date().toLocaleTimeString();
  if (connState === 'polling') {
    statusEl.textContent = '🟡 SSE 끊김 · polling · ' + prefix + ' ' + t;
    statusEl.className = 'status polling';
  } else if (connState === 'error') {
    statusEl.textContent = '🔴 SSE 끊김 · ' + prefix + ' ' + t;
    statusEl.className = 'status error';
  } else {
    statusEl.textContent = '🟢 ' + prefix + ' ' + t;
    statusEl.className = 'status connected';
  }
}
async function reload(force) {
  try {
    const r = await fetch(DATA_URL + '&_=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const sig = (d.mode || '?') + '|' + (d.content || '');
    if (!force && sig === lastSig) {
      showRefreshed('확인');
      return;
    }
    lastSig = sig;
    // Issue280: GC 대상 정보(live_pid/gc_meta) 없는 구세션은 버튼 비활성
    if (typeof d.can_gc !== 'undefined') setGcEnabled(!!d.can_gc);
    modeEl.textContent = d.mode || '?';
    if (d.mode === 'A') {
      contentEl.innerHTML = d.content || '<em>(빈 응답)</em>';
    } else if (d.mode === 'B') {
      contentEl.innerHTML = renderForm(d.content);
      const btn = document.getElementById('qa-submit');
      if (btn) btn.addEventListener('click', submitForm);
    } else if (d.mode === 'C') {
      contentEl.innerHTML = renderDashboard(d.content);
      // Issue29 Phase 6: progress 임계치 알림 (hysteresis)
      try { maybeNotifyProgress(parseJSON(d.content)); } catch (e) {}
      // 디스크 전용 대시보드(runner 가 파일만 갱신, sessions 미push)는 SSE reload 이벤트가
      // 발생하지 않아 SSE 정상 시 동결된다. dash interval 주기로 /data 를 자체 폴링해 라이브 유지.
      try { ensureDashPoll((parseJSON(d.content) || {}).interval); } catch (e) {}
    } else {
      contentEl.innerHTML = `<em>unknown mode: ${esc(d.mode)}</em>`;
    }
    showRefreshed('갱신');
  } catch (e) {
    statusEl.textContent = '❌ ' + e.message;
    statusEl.className = 'status error';
  }
}

reload();
// Issue24 Phase 4: SSE-only + es.onerror polling fallback (status 표시 🟢🟡🔴)
let pollingId = null;
// 디스크 전용 대시보드 전용 주기 폴링 — SSE 연결 여부와 무관하게 dash interval 마다
// /data 재fetch. reload() 의 sig 디듑으로 변화 없으면 재렌더 생략(저비용).
let dashPollId = null;
function ensureDashPoll(sec) {
  if (PREVIEW || dashPollId) return;
  const ms = Math.max(5, Number(sec) || 10) * 1000;
  dashPollId = setInterval(() => reload(), ms);
}
function setStatus(state, text) {
  statusEl.classList.remove('connected', 'polling', 'error');
  let icon = '🔴';
  if (state === 'connected') { icon = '🟢'; statusEl.classList.add('connected'); connState = 'sse'; }
  else if (state === 'polling') { icon = '🟡'; statusEl.classList.add('polling'); connState = 'polling'; }
  else { icon = '🔴'; statusEl.classList.add('error'); connState = 'error'; }
  statusEl.textContent = icon + ' ' + text;
}
function startPolling() {
  if (pollingId) return;
  setStatus('polling', 'SSE 끊김 — polling 3s fallback');
  pollingId = setInterval(() => reload(), 3000);
}
function stopPolling() {
  if (pollingId) { clearInterval(pollingId); pollingId = null; }
}
// Issue258: Page Visibility 게이팅 — 백그라운드 탭은 SSE 연결을 반납한다.
//   Chrome HTTP/1.1 호스트당 6연결 상한 → hub 탭 여러 개면 SSE 포화 → 렌더러 크래시.
//   hidden = 연결 close(반납), visible 복귀 = 재연결 + reload(백그라운드 누락분 수거).
//   "여러 탭" 대부분은 hidden → 활성 SSE ≈ hub-shell(1)+가시 doc(≈1) → 상한 도달 불가.
let es = null;
function openSSE() {
  if (PREVIEW || es) return;
  try {
    es = new EventSource(SSE_URL);
    es.addEventListener('reload', () => reload(true));
    es.addEventListener('session_update', () => reload(true));
    // Issue280: 다른 탭/hub 에서 이 세션이 GC 되면 즉시 terminated 표시
    es.addEventListener('session_terminated', ev => {
      let m = '';
      try { m = (JSON.parse(ev.data) || {}).method || ''; } catch (e) {}
      markTerminated(m);
    });
    es.onopen = () => { setStatus('connected', 'SSE 연결됨'); stopPolling(); };
    es.onerror = () => { setStatus('error', 'SSE error — reconnect 대기'); startPolling(); };
  } catch (e) {
    console.warn('SSE failed, polling only:', e);
    startPolling();
  }
}
function closeSSE() {
  if (es) { try { es.close(); } catch (_) {} es = null; }
}
if (PREVIEW) {
  setStatus('connected', 'PREVIEW (정적 · TTL ' + 60 + 's)');
} else {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') { closeSSE(); stopPolling(); }
    else { openSSE(); reload(true); }
  });
  // Issue258(재수정): iframe 재네비/탭 닫기로 이 doc 이 폐기되기 직전 SSE·polling 을 명시적
  //   반납. 노드 swap 과 함께 detached document 누수를 확정 차단(렌더러 CHECK abort 방지).
  window.addEventListener('pagehide', () => { closeSSE(); stopPolling(); });
  if (document.visibilityState !== 'hidden') { openSSE(); }
}
// Issue29 Phase 6: Notification API — progress widget 임계치(50/80/100%) hysteresis 알림
const NOTIFY_THRESHOLDS = [50, 80, 100];
let progressNotified = {};  // widget_index -> highest threshold already notified
if (!PREVIEW && typeof Notification !== 'undefined' && Notification.permission === 'default') {
  try { Notification.requestPermission().catch(() => {}); } catch (e) {}
}
function maybeNotifyProgress(data) {
  if (PREVIEW) return;
  if (!data || !Array.isArray(data.widgets)) return;
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  data.widgets.forEach((w, i) => {
    if (!w || w.type !== 'progress') return;
    const v = typeof w.value === 'number' ? w.value : 0;
    const key = String(i);
    const lastTh = progressNotified[key] || 0;
    for (const th of NOTIFY_THRESHOLDS) {
      if (v >= th && lastTh < th) {
        progressNotified[key] = th;
        const title = (data.title || NAME_LABEL) + ' — ' + th + '%';
        const body = (w.title || ('widget#' + i)) + ': ' + Math.round(v) + '%';
        try { new Notification(title, {body: body, tag: CWD_HASH + ':' + SID + ':' + key + ':' + th}); }
        catch (e) {}
      }
    }
  });
}
// Issue24 Phase 1: timer 위젯 live tick
function tickTimers() {
  const now = Date.now() / 1000;
  document.querySelectorAll('.widget.timer').forEach(el => {
    const startTs = parseFloat(el.dataset.startTs) || 0;
    const mode = el.dataset.mode || 'up';
    const target = parseFloat(el.dataset.target) || 0;
    let sec;
    if (mode === 'down' && target) sec = Math.max(0, target - now);
    else sec = now - startTs;
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    const valEl = el.querySelector('.timer-value');
    if (valEl) valEl.textContent = (h > 0 ? h + ':' : '') + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  });
}
setInterval(tickTimers, 1000);
// Issue280: 세션 GC 버튼 — action_type=terminate POST. GC 주목적(가비지 세션·pane 정리),
//   memo 는 실전달 없이 서버 레코드(session-gc.jsonl·inbox)로만 저장(향후 분석용).
let gcDone = false;
function setGcEnabled(on) {
  if (gcDone) return;
  document.querySelectorAll('[data-gc]').forEach(b => {
    b.disabled = !on;
    b.title = on ? '세션 GC — 세션·터미널 pane 강제 종료'
                 : 'GC 대상 정보 없음 (live_pid/gc_meta 미등록 구세션)';
  });
}
function resetGcButtons() {
  document.querySelectorAll('[data-gc]').forEach(b => { b.disabled = false; b.textContent = '🗑 세션 GC'; });
}
function markTerminated(method) {
  gcDone = true;
  document.querySelectorAll('[data-gc]').forEach(b => { b.disabled = true; b.textContent = '☠️ terminated'; });
  setStatus('error', '☠️ 세션 종료됨' + (method ? ' (' + method + ')' : ''));
  closeSSE(); stopPolling();
}
function gcSession() {
  if (gcDone) return;
  if (!window.confirm('이 세션과 터미널 pane 을 강제 종료(GC)할까요?\n' + NAME_LABEL)) return;
  const memo = window.prompt('종료 메모 (선택 — 분석용 기록)', '') || '';
  document.querySelectorAll('[data-gc]').forEach(b => { b.disabled = true; b.textContent = '⏳ GC 중...'; });
  fetch(ACTION_URL, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action_type: 'terminate', message: memo})
  }).then(r => r.json().then(j => ({httpOk: r.ok, j})))
    .then(({httpOk, j}) => {
      if (httpOk && j.ok) { markTerminated(j.method); }
      else { alert('GC 실패: ' + (j.error || JSON.stringify(j))); resetGcButtons(); }
    })
    .catch(e => { alert('GC 요청 실패: ' + e); resetGcButtons(); });
}
if (PREVIEW) {
  document.querySelectorAll('[data-gc]').forEach(b => { b.style.display = 'none'; });
} else {
  document.querySelectorAll('[data-gc]').forEach(b => b.addEventListener('click', gcSession));
}
</script>
</body>
</html>
"""


def cleanup(*_):
    log("SIGTERM/SIGINT — flushing tokens, removing pid")
    persist_tokens()
    persist_sessions()
    # Issue59: PID_FILE 내용이 자기 pid 일 때만 제거 — 살아있는 다른 서버의 pid 파일 파괴 방지
    try:
        with open(PID_FILE) as f:
            if int(f.read().strip()) == os.getpid():
                os.remove(PID_FILE)
    except Exception:
        pass
    sys.exit(0)


def already_running() -> int:
    """기존 PID 살아있으면 그 pid 반환, 아니면 0."""
    if not os.path.exists(PID_FILE):
        return 0
    try:
        with open(PID_FILE) as f:
            old_pid = int(f.read().strip())
        os.kill(old_pid, 0)
        return old_pid
    except (ValueError, ProcessLookupError, PermissionError):
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
        return 0


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(INBOX_ROOT, exist_ok=True)

    pid = already_running()
    if pid:
        sys.stderr.write(f"[hub] already running (pid={pid}, port={PORT}). Use stop first.\n")
        sys.exit(1)

    load_tokens()
    load_sessions()  # Issue17 Phase 1
    load_pids()      # Issue63: runner PID 등록분 복원 (재시작 후 /control 복구)
    load_feed()      # Issue42: hook 활동 피드 복원

    # Issue141: env 미설정 시 hub_setting.yml bind_host 적용 (env > yml > 기본).
    # bind_host 는 스칼라 또는 리스트 — 리스트면 각 주소에 개별 bind(멀티소켓).
    global HOST, ALLOW_ALL, BIND_HOSTS, ALLOWLIST_READY
    if _HOST_ENV is not None:
        BIND_HOSTS = [_HOST_ENV.strip()]
    else:
        _bh = _load_hub_setting().get("bind_host")
        if isinstance(_bh, list):
            BIND_HOSTS = [h.strip() for h in _bh if h and h.strip()] or ["127.0.0.1"]
        else:
            BIND_HOSTS = [(_bh or "127.0.0.1").strip() or "127.0.0.1"]
    # 순서 보존 dedup
    _seen = set()
    BIND_HOSTS = [h for h in BIND_HOSTS if not (h in _seen or _seen.add(h))]
    HOST = BIND_HOSTS[0]  # primary — self-ip·pid·로그·advertise fallback 기준
    # 개방 모드 = bind 주소 중 하나라도 비루프백 (멀티 bind 일반화).
    _open_mode = any(h not in LOOPBACK_IPS for h in BIND_HOSTS)

    # Issue379: 수신 이름 게이트 산출. 순수 문자열 조립(DNS 불요)이라 bind 이전에 동기 실행해도
    # 다운타임 증가 0 — allowlist(Issue200/332) 처럼 백그라운드로 미룰 이유가 없다.
    global KNOWN_HOSTS, HOST_GATE
    HOST_GATE = bool(_load_hub_setting().get("host_gate", True))
    KNOWN_HOSTS = _build_known_hosts()
    if HOST_GATE and KNOWN_HOSTS:
        log(f"[hostgate] 활성 — KNOWN={sorted(KNOWN_HOSTS)} (IP 리터럴 Host 는 항상 통과)")
    else:
        _why = "host_gate=false" if not HOST_GATE else "known 집합 공집합"
        log(f"[hostgate] 비활성({_why}) — 모든 Host 헤더 허용(종전 동작)")

    # allow_server_list 분리: source-IP 게이트는 bind_host 와 독립 토글.
    # 기본 True = Servers.md(check=O) 화이트리스트 + self 허용.
    # False = bind_host(self) 만 허용 — 외부 source IP 전부 차단(가장 보수적).
    _allow_server_list = bool(_load_hub_setting().get("allow_server_list", True))

    def _resolve_self_ips() -> set:
        """bind IP + 로컬 인터페이스 IP 집합 (루프백 제외). self 항상 허용용.
        Servers.md 의 자기 호스트가 공개 도메인으로 resolve 되면 LAN self IP 와
        불일치하여 로컬 브라우저·hook 이 403 당하던 문제도 함께 차단.
        BIND_HOSTS 전체를 seed 해 모든 bind 인터페이스(예: tailscale IP)를 self 로 인식 —
        advertise_host(tailscale MagicDNS)로 열린 로컬 iframe 이 자기 tailscale IP 로
        도달할 때 allowlist 미포함으로 403 당하던 문제 차단(자기 자신은 항상 self)."""
        _ips = set(BIND_HOSTS)
        try:
            _ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
        except (socket.gaierror, OSError):
            pass
        try:
            _probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _probe.connect(("192.168.255.255", 1))  # 라우팅만, 패킷 미전송
            _ips.add(_probe.getsockname()[0])
            _probe.close()
        except OSError:
            pass
        return {ip for ip in _ips if ip and ip not in LOOPBACK_IPS}

    # Issue200: allowlist 적재(DNS resolve 포함)를 bind 와 분리하여 백그라운드 데몬
    # 스레드로 지연 실행. 개방 모드의 Servers.md gethostbyname / self gethostbyname_ex 는
    # 호스트당 DNS 타임아웃(~5s) 까지 동기 블로킹 가능 → 그동안 bind 가 지연되어 재시작
    # 다운타임을 유발했다. bind 는 BIND_HOSTS(스칼라 IP/호스트, DNS 불요)만 쓰므로 allowlist
    # 적재를 미뤄도 bind 시각에 영향 없음.
    #
    # Issue332: 위 주석의 "루프백은 항상 허용 → 로컬 무영향" 전제는 tailnet 호스트명
    # (advertise_host MagicDNS)으로 자기 자신을 열 때 깨진다 — 소스 IP 가 루프백이 아니라
    # 자기 tailscale IP 라 적재 완료 전 창에서 403 당한다. 따라서 DNS resolve 가 필요 없는
    # 항목(BIND_HOSTS self IP + hub_setting.yml inline allow_list IP/CIDR)은 bind 이전에
    # 동기 적재한다(다운타임 증가 0). resolve 가 필요한 Servers.md·로컬 인터페이스 조회만
    # 백그라운드에 남긴다. 그래도 남는 창은 ALLOWLIST_READY 플래그로 503 처리.
    def _populate_allowlist_sync():
        """DNS 불요 항목만 즉시 적재 — bind 전 호출. 실패 없음(순수 파싱)."""
        if not _open_mode:
            return
        # bind 주소 자체는 항상 self → 리터럴 IP 만 즉시 허용(호스트명은 백그라운드 resolve).
        _bind_ips = set()
        for _h in BIND_HOSTS:
            if _h in LOOPBACK_IPS:
                continue
            try:
                ipaddress.ip_address(_h)
            except ValueError:
                continue  # 호스트명 — resolve 필요, 백그라운드에서 처리
            _bind_ips.add(_h)
        ALLOWED_IPS.update(_bind_ips)
        # inline allow_list (IP/CIDR) — yml 파싱만, resolve 불요.
        _inline = _load_hub_setting().get("allow_list") or []
        _added_ips, _added_nets = [], []
        for item in _inline:
            if "/" in item:
                try:
                    ALLOWED_NETS.append(ipaddress.ip_network(item, strict=False))
                    _added_nets.append(item)
                except ValueError as e:
                    log(f"[allowlist] inline allow_list CIDR 파싱 실패 skip — {item}: {e}")
            else:
                try:
                    ipaddress.ip_address(item)  # IP 검증(호스트명 미지원)
                    ALLOWED_IPS.add(item)
                    _added_ips.append(item)
                except ValueError:
                    log(f"[allowlist] inline allow_list 항목 무시(IP/CIDR 아님) — {item}")
        log(f"[allowlist] 동기 선적재(Issue332) — bind self IP {sorted(_bind_ips)}, "
            f"inline IP {_added_ips}, inline CIDR {_added_nets}")

    def _populate_allowlist():
        # 비루프백 bind + allow_server_list=false → bind_host(self) 만 허용.
        # Servers.md 미적재. 외부 source IP 는 _ip_allowed 게이트에서 전부 403.
        if _open_mode and not _allow_server_list:
            _self_ips = _resolve_self_ips()
            ALLOWED_IPS.update(_self_ips)
            log(f"[allowlist] bind_host 전용 — bind={BIND_HOSTS}, allow_server_list=false → "
                f"self 허용 {sorted(_self_ips)} (+루프백), 외부 source IP 전부 차단")
            sys.stderr.write(
                f"[hub] bind_host 전용 모드 — bind={BIND_HOSTS}:{PORT}, "
                f"allow_server_list=false → self+루프백만 허용\n")

        # 개방 모드(비루프백 bind + allow_server_list=true)에서만 Servers.md allowlist 적재.
        # 기본 127.0.0.1 이면 빈 set 유지 → 루프백만 통과(기존 동작 그대로).
        if _open_mode and _allow_server_list:
            _ips, _nets = _load_server_allowlist()
            ALLOWED_IPS.update(_ips)
            ALLOWED_NETS.extend(_nets)
            # 자기 자신은 항상 허용 — bind IP + 로컬 인터페이스 IP 자동 추가.
            _self_ips = _resolve_self_ips()
            ALLOWED_IPS.update(_self_ips)
            log(f"[allowlist] self 자동 허용 — {sorted(_self_ips)}")
            log(f"[allowlist] 개방 모드 — bind={BIND_HOSTS}, 허용 IP {len(ALLOWED_IPS)}개: "
                f"{sorted(ALLOWED_IPS)}, CIDR {len(ALLOWED_NETS)}개: "
                f"{[str(n) for n in ALLOWED_NETS]} (+루프백)")
            sys.stderr.write(
                f"[hub] ⚠️ 외부 개방 모드 — bind={BIND_HOSTS}:{PORT}, "
                f"allowlist {len(ALLOWED_IPS)} hosts + {len(ALLOWED_NETS)} CIDR (+loopback)\n")

        # Issue332: inline allow_list 는 _populate_allowlist_sync() 로 이관(bind 전 동기 적재).

    # 개방 모드에서만 백그라운드 적재 스레드 가동(루프백 전용 기본 모드는 적재 불요 → no-op).
    if _open_mode:
        _populate_allowlist_sync()  # DNS 불요 항목 — bind 전 동기 (Issue332)
        ALLOWLIST_READY = False     # resolve 항목 적재 완료 전까지 비허용 판정 = 503

        def _populate_allowlist_bg():
            global ALLOWLIST_READY
            try:
                _populate_allowlist()
            finally:
                ALLOWLIST_READY = True
                log("[allowlist] 적재 완료 — ALLOWLIST_READY=True (Issue332)")

        threading.Thread(target=_populate_allowlist_bg, name="allowlist-populate",
                         daemon=True).start()

    # Issue331: zed orphan live 세션 주기 리퍼 (브리지 사망 즉시 + idle TTL)
    threading.Thread(target=_orphan_reaper_loop, name="orphan-reaper",
                     daemon=True).start()

    # prj5 Issue37 F3-4: aoa-mq tick 구동 — jmDashboard 브라우저 리프레시 의존 제거
    threading.Thread(target=_aoa_mq_tick_loop, name="aoa-mq-tick",
                     daemon=True).start()

    # Issue59: bind 를 PID_FILE 기록보다 먼저 수행 — bind 실패 시 PID_FILE 미생성·미삭제.
    #          (실패 경로의 cleanup 이 살아있는 다른 서버의 pid 파일을 지우던 버그 차단)
    # 멀티 bind: BIND_HOSTS 의 각 주소에 ThreadingHTTPServer 1개. 첫 성공 전 전부 실패 시 종료.
    servers = []
    for _h in BIND_HOSTS:
        try:
            _s = ThreadingHTTPServer((_h, PORT), Handler)
            _s.daemon_threads = True
            servers.append((_h, _s))
        except OSError as e:
            sys.stderr.write(f"[hub] bind failed on {_h}:{PORT}: {e}\n")
            log(f"[hub] bind failed on {_h}:{PORT}: {e}")
    if not servers:
        sys.stderr.write(f"[hub] all binds failed on port {PORT} — exiting\n")
        sys.exit(2)

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    _bound = [h for h, _ in servers]
    log(f"started on http://{_bound}:{PORT} (pid={os.getpid()}, projects_restored={len(projects)})")

    # 2번째 이후 bind 는 데몬 스레드에서 serve, 첫 번째는 메인 스레드에서 blocking.
    for _h, _s in servers[1:]:
        threading.Thread(target=_s.serve_forever, name=f"serve-{_h}", daemon=True).start()
    try:
        servers[0][1].serve_forever()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
