#!/usr/bin/env python3
"""
htm-server — ___pm 소유 단일 공유 daemon
- 기본 127.0.0.1 바인딩 (외부 차단). HTM_SERVER_HOST 로 옵트인 개방 (Issue141)
  → 개방 시 Servers.md(check=O) 호스트 IP allowlist 로 source-IP 게이트
- 다중 프로젝트 격리: cwd query param + md5(cwd)[:8] hash
- 프로젝트별 token + inbox + SSE subscriber 분리, 포트·프로세스는 단일

설계 SSOT: ~/_git/___pm/_doc_arch/hub_htm.md
"""

import glob
import hashlib
import hmac
import html
import json
import os
import sys
import time
import uuid
import signal
import subprocess
import shlex
import re
import tempfile
import socket
import ipaddress
import threading
from collections import deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

# Issue30: SPA JS 모듈 분리 (SESSION_SHELL_HTML 조립용 string export)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validators import validate_dashboard, DASH_WIDGET_TYPES  # noqa: E402
from spa_form import FORM_JS  # noqa: E402
from spa_widgets import WIDGET_JS  # noqa: E402
from spa_dashboard import DASHBOARD_JS  # noqa: E402
import i18n  # noqa: E402  # Issue169: hub UI 다국어 catalog + t(key, lang)

# Issue141: 기본 127.0.0.1(루프백 전용=외부 차단). 옵트인 개방 우선순위:
#   env HTM_SERVER_HOST > hub_setting.yml bind_host > 기본 "127.0.0.1".
#   env 미설정 시 yml 값을 main() 에서 적용(설정 로더가 정의된 뒤). 예: bind_host: 0.0.0.0
_HOST_ENV = os.environ.get("HTM_SERVER_HOST")  # 미설정이면 None
HOST = _HOST_ENV or "127.0.0.1"  # 잠정값 — main() 에서 yml override
PORT = int(os.environ.get("HTM_SERVER_PORT", "9876"))

# Issue141: source-IP allowlist. LOOPBACK 은 무조건 허용. HOST 가 루프백이 아닐 때
# (옵트인 개방) startup 에서 Servers.md(check=O) 호스트를 resolve 하여 채운다.
LOOPBACK_IPS = frozenset(("127.0.0.1", "::1"))
ALLOWED_IPS = set()  # startup 에서 populate (개방 모드일 때만). 평소엔 빈 set.
ALLOWED_NETS = []    # Issue175: CIDR 서브넷 allowlist (ip_network 리스트). 평소엔 빈 리스트.

STATE_DIR = "/tmp/___pm/claude-htm-server"
INBOX_ROOT = "/tmp/___pm/claude-htm-inbox"
TMP_OUT_DIR = "/tmp/___pm"  # dashboard agent OUT_DIR fallback (z_htm 부재 시)
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

# 메모리 상태
projects_lock = threading.Lock()
projects = {}  # cwd_hash -> {"cwd": str, "token": str, "name": str, "color": str, "registered_at": float}

sse_lock = threading.Lock()
# Issue17 Phase 1: 채널 모델 확장 — key = (cwd_hash, sid)
# sid="" 는 기존 /events?cwd=&token= 호출자 (backward-compat 채널)
sse_subscribers = {}  # (cwd_hash, sid) -> [wfile, wfile, ...]

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
DATA_HUB_DIR = os.path.join(REPO_ROOT, "data", "hub")
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
# hook 이벤트는 항상 수신되므로 detail 의 z_htm 경로를 디스크 확인 후 보강한다.
_HTM_DOC_PATH_RE = re.compile(
    r"/[^\s`\"'<>]+/_doc_work/z_htm/claude-htm-[^\s`\"'<>]+\.html")


def _autoheal_htm_registry(feed_items: list) -> None:
    """feed 항목 detail 에서 z_htm htm html 절대경로를 추출, 디스크에 존재하나
    htm-registry 미등록인 항목을 자동 등록한다 (___pm 서버 단독 읽기 경로 보강).
    cwd 는 경로의 `/_doc_work/z_htm/` 앞부분으로 유추 — feed cwd 비신뢰.
    Issue53: HTM_CLEARED tombstone 에 든 path 는 부활시키지 않는다."""
    found = {}
    for it in feed_items:
        detail = it.get("detail") or ""
        if "z_htm" not in detail:
            continue
        for raw in _HTM_DOC_PATH_RE.findall(detail):
            # 슬래시 중복 등 비정상 prefix 정규화 (cwd_hash 분기 차단)
            m = os.path.normpath(raw)
            if m not in found and os.path.isfile(m):
                idx = m.find("/_doc_work/z_htm/")
                found[m] = m[:idx] if idx > 0 else ""
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


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
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


# Issue28: Projects.md peacock.color 매핑 (cwd 경로 → hex 컬러). mtime 기반 캐시.
PROJECTS_MD = os.path.expanduser("~/_git/___pm/Projects.md")
_projects_color_cache: dict = {}
_projects_color_cache_mtime: float = 0.0

# Issue141: Servers.md — 원격 접근 allowlist 소스. check=O 행만 신뢰 대상.
# FPM_SERVERS_MD env 로 경로 override (플러그인 설치 위치 적응 — FPM_PROJECTS_MD 대칭).
SERVERS_MD = os.environ.get("FPM_SERVERS_MD", os.path.join(REPO_ROOT, "Servers.md"))
# 사설망(RFC1918) prefix — 공개 호스트 경고 판정용.
_PRIVATE_PREFIXES = ("10.", "192.168.", "127.", "169.254.") + tuple(
    f"172.{i}." for i in range(16, 32))


def _parse_servers_md(path: str) -> list:
    """Servers.md 의 Favorite Servers 테이블 파싱 → [{name, host, check}] 리스트.
    `| id | Name | ssh alias | Host | Port | User | Description | check |` 형식."""
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
                rows.append({"name": name, "host": host, "check": check})
    except (FileNotFoundError, OSError) as e:
        log(f"[allowlist] Servers.md 읽기 실패: {e}")
    return rows


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
    """source IP 가 접근 허용 대상인지. 루프백은 무조건 허용, 그 외는
    ALLOWED_IPS(정확 일치) 또는 ALLOWED_NETS(CIDR 서브넷 멤버십, Issue175)."""
    if client_ip in LOOPBACK_IPS or client_ip in ALLOWED_IPS:
        return True
    if ALLOWED_NETS:
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        return any(addr in net for net in ALLOWED_NETS)
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
                try:
                    int(cells[0])
                except ValueError:
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
                try:
                    int(cells[0])
                except ValueError:
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
    """cwd 경로에 매핑된 Projects.md 이모지. 미등록 시 빈 문자열."""
    if not cwd:
        return ""
    abs_cwd = os.path.expanduser(cwd).rstrip("/")
    return _load_projects_emojis().get(abs_cwd, "")


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
                try:
                    pid = int(cells[0])
                except ValueError:
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
    rows.sort(key=lambda r: r["id"])
    _projects_list_cache = rows
    _projects_list_cache_mtime = st.st_mtime
    return rows


def _htm_state(path: str) -> tuple:
    """프로젝트 경로의 htm 자동 모드 effective off 여부 + 사유 계산.
    htm-trigger.sh 판정 우선순위 복제: SYSTEM_OFF_FLAG > per-cwd STATE_FILE > 프로젝트 default(on).
    Project List 행은 모두 등록 프로젝트이므로 default 는 on. 반환: (off: bool, reason: str)."""
    home = os.path.expanduser("~")
    if os.path.exists(os.path.join(home, ".claude", ".hub-system-off")):
        return True, "시스템 OFF (..hub off)"
    abs_cwd = os.path.expanduser(path).rstrip("/")
    h = hashlib.md5(abs_cwd.encode("utf-8")).hexdigest()[:8]
    state_dir = os.path.join(home, ".claude", ".hub-state")
    content = None
    try:
        for fn in os.listdir(state_dir):
            if fn == h or fn.startswith(h + "__"):
                with open(os.path.join(state_dir, fn), encoding="utf-8") as f:
                    content = f.read().strip()
                break
    except (FileNotFoundError, OSError):
        pass
    if content == "off":
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


def _projects_list_with_htm() -> list:
    """_load_projects_list() 결과에 htm off 상태 주입. htm 상태는 Projects.md mtime 과
    무관하게 변하므로 캐시 밖에서 매 요청 계산 (state 파일은 소수 → IO 경량)."""
    rows = _load_projects_list()
    out = []
    for r in rows:
        off, reason = _htm_state(r.get("path", ""))
        out.append({**r, "htm_off": off, "htm_reason": reason})
    return out


def project_meta(cwd: str) -> dict:
    h = cwd_hash(cwd)
    name = (os.path.basename(cwd) or cwd).replace(" ", "_")
    # Issue28: Projects.md peacock.color 우선, 없으면 hsl fallback
    abs_cwd = os.path.expanduser(cwd).rstrip("/")
    colors = _load_projects_colors()
    color = colors.get(abs_cwd) or f"hsl({int(h[:4], 16) % 360}, 60%, 45%)"
    # Issue46: Projects.md 이모지 보강 (미등록 시 빈 문자열)
    emoji = _load_projects_emojis().get(abs_cwd, "")
    return {"cwd_hash": h, "name": name, "color": color, "emoji": emoji}


# Issue42: hub 활동 피드 — hub_setting.yml 설정 + hook 이벤트 버퍼.
# data/hub_setting.yml 은 사용자 설정(git 추적), data/hub/hook-feed.json 은 런타임 상태(gitignore).
HUB_SETTING_FILE = os.path.join(REPO_ROOT, "data", "hub_setting.yml")
HUB_SETTING_DEFAULTS = {"feed_limit": 100, "feed_default_visible": True, "feed_poll_interval": 5,
                        "feed_show_project_emoji": True, "feed_show_project_name": True,
                        "card_limit": 40, "search_limit": 200, "live_session_limit": 6,
                        # Issue141: bind 주소 (문자열). env HTM_SERVER_HOST 미설정 시 사용.
                        "bind_host": "127.0.0.1",
                        # Issue159: 활성세션 정렬 — updated(최근갱신순) / created(세션 시작순 고정)
                        #   / project(Projects.md 번호순, 미등록 cwd 는 끝)
                        "live_session_order": "updated",
                        # Issue166: 명령(프롬프트) 전 빈 live 세션 표시 여부.
                        #   false(기본)=전체 숨김 / true=프로젝트당 최신 1개 표시(Issue136 dedup)
                        "live_session_show_empty": False,
                        # Issue169: hub UI 언어 — en(영어, 기본) / ko(한국어). 설계: _doc_arch/localization.md
                        "language": "en"}
_hub_setting_cache: dict = {}
_hub_setting_cache_mtime: float = 0.0


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
                elif isinstance(HUB_SETTING_DEFAULTS[key], str):
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
    return setting


# Issue168: 설정 모달 UI 스키마 — ⚙️ 버튼이 여는 인앱 3탭 설정창의 분류·위젯·유효값·적용방식.
#   탭(tab): basic(기본)/session(세션관리)/advanced(고급)
#   위젯(widget): toggle(bool)/select/number/text
#   적용(apply): auto(server.py mtime 재로드) / hook(글로벌 hook grep, 다음 렌더 turn) / restart(서버 재시작 필요)
#   분류 SSOT: _doc_arch/hub_settings_ui.md (본 상수는 그 미러)
HUB_SETTING_SCHEMA = [
    # 탭 1: 기본 — 렌더·브라우저
    {"key": "default_browser", "tab": "basic", "widget": "select",
     "options": ["firefox", "chrome", "edge", "safari"], "allow_custom": True,
     "apply": "hook", "comment": "렌더 브라우저 (firefox/chrome/edge/safari 또는 .app 절대경로)"},
    # Issue170: 3-way 브라우저 자동 open 동작. browser_focus 흡수(off/background/foreground).
    {"key": "browser_open", "tab": "basic", "widget": "select",
     "options": ["off", "background", "foreground"],
     "apply": "hook", "comment": "브라우저 자동 open — off(채팅 URL만)/background(open -g, 포커스 미탈취)/foreground(포커스 탈취)"},
    {"key": "browser_focus", "tab": "basic", "widget": "toggle",
     "apply": "hook", "deprecated": True,
     "comment": "[deprecated → browser_open] 포커스 탈취. hook 이 browser_open 미설정 시에만 fallback 참조"},
    {"key": "browser_tab_reuse", "tab": "basic", "widget": "toggle",
     "apply": "hook", "comment": "/hub 단일 탭 재사용 (Issue171). 렌더(..show/..ask)는 값 무관 항상 새 탭. 🚧 신 의미 hook 구현 글로벌 Issue153"},
    {"key": "render_target", "tab": "basic", "widget": "select",
     "options": ["local-open", "hub", "both"],
     "apply": "hook", "comment": "..show 표시 경로 — local-open(file://)/hub(서버 URL)/both"},
    # Issue169: hub UI 언어 (en/ko). 저장 후 hub 페이지 reload 시 반영. 설계: _doc_arch/localization.md
    {"key": "language", "tab": "basic", "widget": "select",
     "options": ["en", "ko"],
     "apply": "auto", "comment": "hub UI 언어 — en(영어, 기본)/ko(한국어). 저장 후 페이지 reload 반영"},
    {"key": "feed_default_visible", "tab": "basic", "widget": "toggle",
     "apply": "auto", "comment": "피드 사이드바 최초 표시 여부"},
    # 탭 2: 세션관리 — 세션·피드·표시 상한 (전부 server.py 소비 → auto)
    {"key": "live_session_limit", "tab": "session", "widget": "number", "min": 0,
     "apply": "auto", "comment": "세션 카드당 최대 행 (0=무제한)"},
    {"key": "live_session_order", "tab": "session", "widget": "select",
     "options": ["updated", "created", "project"],
     "apply": "auto", "comment": "활성세션 정렬 — updated/created/project"},
    {"key": "live_session_show_empty", "tab": "session", "widget": "toggle",
     "apply": "auto", "comment": "명령 전 빈 live 세션 표시 (false=숨김)"},
    {"key": "card_limit", "tab": "session", "widget": "number", "min": 0,
     "apply": "auto", "comment": "htm 카드 최대 표시 수 (0=무제한)"},
    {"key": "search_limit", "tab": "session", "widget": "number", "min": 0,
     "apply": "auto", "comment": "디스크 재스캔 디렉토리당 파일 상한 (0=무제한)"},
    {"key": "feed_limit", "tab": "session", "widget": "number", "min": 1,
     "apply": "auto", "comment": "피드 보관·표시 최대 항목 수"},
    {"key": "feed_show_project_emoji", "tab": "session", "widget": "toggle",
     "apply": "auto", "comment": "피드 항목 프로젝트 이모지 표시"},
    {"key": "feed_show_project_name", "tab": "session", "widget": "toggle",
     "apply": "auto", "comment": "피드 항목 프로젝트명 표시"},
    # 탭 3: 고급 — 네트워크
    {"key": "bind_host", "tab": "advanced", "widget": "text",
     "apply": "restart", "comment": "hub 서버 listen 인터페이스 (127.0.0.1/0.0.0.0/IP). 변경 시 restart 필요"},
    {"key": "advertise_host", "tab": "advanced", "widget": "text", "optional": True,
     "apply": "hook", "comment": "hub|both URL host (생략 시 bind_host fallback). 0.0.0.0+생략 금지"},
    {"key": "feed_poll_interval", "tab": "advanced", "widget": "number", "min": 1,
     "apply": "auto", "comment": "피드 폴링 주기(초, 참고값)"},
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
                if val.get("content_type") == "live" and val.get("live_pid") is None:
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

    dashboard agent 가 z_htm 부재 시 dash/html 산출물을 TMP_OUT_DIR(/tmp/___pm)
    평면에 떨굼(Issue39). dash-registry 의 cwd 는 프로젝트 cwd 라 cwd-confinement
    만으로는 'path outside cwd' 403 발생. TMP_OUT_DIR flat 파일은 서버 소유
    namespace 이므로 예외 허용. subdir(claude-htm-server/inbox) 은 제외."""
    if abs_path == cwd_real or abs_path.startswith(cwd_real + os.sep):
        return True
    tmp_real = os.path.realpath(TMP_OUT_DIR)
    return os.path.dirname(abs_path) == tmp_real


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

    def _send_json(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self._send_json(204, {})

    def do_GET(self):
        # Issue141: 전역 source-IP 게이트. 기본(127.0.0.1 bind)에선 루프백만 도달 →
        # 항상 통과. 개방 모드(HTM_SERVER_HOST)에선 비-allowlist IP 를 여기서 차단
        # → 토큰 노출 GET(/dashboards, /hub)·SSE 까지 일괄 보호.
        if not _ip_allowed(self.client_address[0] if self.client_address else ""):
            self._send_json(403, {"error": "ip not allowed"})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(302)
            self.send_header("Location", "/hub")
            self.end_headers()
            return
        # Issue182: fPm 프로젝트 아이콘 서빙 (favicon + 헤더 브랜딩 공용)
        if parsed.path == "/fpm-icon.png":
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
        if parsed.path == "/healthz":
            with projects_lock:
                pc = len(projects)
            with pids_lock:
                rp = sum(len(s) for s in pids.values())
            self._send_json(200, {
                "status": "ok",
                "pid": os.getpid(),
                "port": PORT,
                "uptime": int(time.time() - start_ts),
                "projects": pc,
                "registered_pids": rp,
            })
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
        if parsed.path == "/dashboards":
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
        if parsed.path == "/projects-list":
            self._send_json(200, {"projects": _projects_list_with_htm()})
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
            self._send_json(403, {"error": "ip not allowed"})
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
        if parsed.path == "/notify":
            self._handle_notify(parsed)
            return
        if parsed.path == "/clear-done":
            self._handle_clear_done(parsed)
            return
        if parsed.path == "/kill-empty-live":
            self._handle_kill_empty_live(parsed)
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
        if parsed.path == "/htm-toggle":
            self._handle_htm_toggle(parsed)
            return
        if parsed.path == "/htm-toggle-all":
            self._handle_htm_toggle_all(parsed)
            return
        if parsed.path == "/open-projects-md":
            self._handle_open_projects_md(parsed)
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
        self._send_json(200, {"status": "broadcast", "clients": sent})

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
        }
        try:
            with open(abs_path, encoding="utf-8") as f:
                raw = f.read()
            if abs_path.endswith(".dash.json"):
                self._fill_dash_entry_from_dict(entry, json.loads(raw))
            else:
                parsed = self._parse_dash_yaml(raw)
                for k in ("title", "status", "pid", "worker_pid", "progress"):
                    if parsed.get(k) is not None:
                        entry[k] = parsed[k]
        except Exception as e:
            log(f"read_dash_file parse fail {abs_path}: {e}")
        doc_cache_put(abs_path, st.st_mtime, dict(entry))
        return entry

    def _scan_dashes(self, cwd: str) -> list:
        """Issue16_7 / Issue31: cwd 하위 _doc_work/z_htm/ 에서 *.dash.{json,yaml,yml} 스캔.
        Issue41: 자동 hub 갱신 경로에서 제거됨 — /hub-rescan(수동 부트스트랩) 전용.
        yaml 은 stdlib 미지원이므로 dashboard.md 양식 한정 경량 파서 사용 (Issue31 (a))."""
        results = []
        z_htm = os.path.join(cwd, "_doc_work", "z_htm")
        if not os.path.isdir(z_htm):
            return results
        try:
            entries = sorted(os.listdir(z_htm))
        except OSError:
            return results
        for name in entries:
            if not (name.endswith(".dash.json") or name.endswith(".dash.yaml") or name.endswith(".dash.yml")):
                continue
            abs_path = os.path.join(z_htm, name)
            try:
                st = os.stat(abs_path)
            except OSError:
                continue
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            entry = {"path": abs_path, "mtime": mtime, "title": None, "status": None, "progress": None, "pid": None, "worker_pid": None}
            try:
                with open(abs_path, encoding="utf-8") as f:
                    raw = f.read()
                if name.endswith(".dash.json"):
                    parsed = json.loads(raw)
                    self._fill_dash_entry_from_dict(entry, parsed)
                else:
                    parsed = self._parse_dash_yaml(raw)
                    # _parse_dash_yaml 은 이미 entry 와 동일 키 dict 반환
                    for k in ("title", "status", "pid", "worker_pid", "progress"):
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
            entry = {"path": abs_path, "mtime": mtime, "title": None, "status": None, "progress": None, "pid": None, "worker_pid": None}
            try:
                with open(abs_path, encoding="utf-8") as f:
                    raw = f.read()
                if name.endswith(".dash.json"):
                    self._fill_dash_entry_from_dict(entry, json.loads(raw))
                else:
                    parsed = self._parse_dash_yaml(raw)
                    for k in ("title", "status", "pid", "worker_pid", "progress"):
                        if parsed.get(k) is not None:
                            entry[k] = parsed[k]
            except Exception as e:
                log(f"scan_tmp_dashes parse fail {abs_path}: {e}")
            results.append(entry)
        return results

    @staticmethod
    def _extract_html_title(abs_path: str) -> str:
        """Issue40: HTML head(앞 8KB)에서 <title> 텍스트 추출. 실패 시 빈 문자열."""
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                head = f.read(8192)
        except OSError:
            return ""
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
        htm-doc 카드 본문 2줄 요약용. 실패 시 빈 문자열."""
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                data = f.read(16384)
        except OSError:
            return ""
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
        전역 hook(register-doc) 의존 없이 파일 자체에서 회수. 실패 시 빈 문자열."""
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                data = f.read(65536)
        except OSError:
            return ""
        m = re.search(r"sid:'([A-Za-z0-9_-]{1,128})'", data)
        if not m:
            m = re.search(r"open\?session=([A-Za-z0-9_-]{1,128})", data)
        return m.group(1) if m else ""

    def _scan_htm_docs_in(self, directory: str, skip: set = None,
                          limit: int = 0) -> list:
        """Issue40: directory 에서 htm 스킬 단발 출력(claude-htm-*.html) 스캔.
        동반 .dash.{json,yaml,yml} 형제가 있는 .html 은 dashboard 산출물 → 제외.
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
            if not (name.startswith("claude-htm-") and name.endswith(".html")):
                continue
            stem = name[:-len(".html")]
            if any(f"{stem}.dash.{ext}" in entry_set for ext in ("json", "yaml", "yml")):
                continue
            abs_path = os.path.join(directory, name)
            if abs_path in skip:  # Issue55: tombstone — 재등록·title 추출 모두 skip
                continue
            candidates.append((name, abs_path))
        # Issue55: search_limit — 파일명 unixtime 최신 N개만 처리.
        # z_htm 누적 시 전수 stat + _extract_html_title(파일 열람) 폭주를 차단.
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
        """Issue40: 프로젝트 cwd 하위 _doc_work/z_htm/ 의 htm 단발 출력 스캔."""
        return self._scan_htm_docs_in(os.path.join(cwd, "_doc_work", "z_htm"),
                                      skip, limit)

    def _scan_tmp_htm_docs(self, skip: set = None, limit: int = 0) -> list:
        """Issue40: /tmp/___pm 평면 htm 출력 스캔 (z_htm 부재 시 fallback 경로)."""
        return self._scan_htm_docs_in("/tmp/___pm", skip, limit)

    def _all_disk_htm_paths(self) -> set:
        """Issue92: clear tombstone 용 — 등록 프로젝트 z_htm + /tmp/___pm 의
        claude-htm-*.html 절대경로 전수(set). title 추출 없이 path 만 수집
        (dash 동반 .html 제외). _scan_htm_docs_in 과 동일 후보 규칙이나
        파일 열람·limit 없이 경로만 — clear 가 디스크에 권위적이도록.
        registry 미등록 orphan(register-doc 실패분·구버전 파일)도 포함되어
        clear 후 rescan/autoheal 부활을 원천 차단한다."""
        dirs = []
        with projects_lock:
            for p in projects.values():
                cwd = p.get("cwd", "")
                if cwd:
                    dirs.append(os.path.join(cwd, "_doc_work", "z_htm"))
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
                if not (name.startswith("claude-htm-") and name.endswith(".html")):
                    continue
                stem = name[:-len(".html")]
                if any(f"{stem}.dash.{ext}" in names
                       for ext in ("json", "yaml", "yml")):
                    continue
                out.add(os.path.join(d, name))
        return out

    def _all_disk_dash_paths(self) -> set:
        """Issue95: clear tombstone용 — 등록 프로젝트 z_htm + /tmp/___pm의
        *.dash.{json,yaml,yml} 절대경로 전수(set). path만 수집(파일 열람 없음) —
        clear가 디스크에 권위적이도록. registry 미등록 orphan도 포함하여
        clear 후 rescan 부활을 원천 차단한다."""
        dirs = []
        with projects_lock:
            for p in projects.values():
                cwd = p.get("cwd", "")
                if cwd:
                    dirs.append(os.path.join(cwd, "_doc_work", "z_htm"))
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
                if token:
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

    def _fill_dash_entry_from_dict(self, entry: dict, d) -> None:
        """dash.json 파싱 결과(dict) 를 entry 에 반영. widgets[].id=progress 도 fallback 추출."""
        if not isinstance(d, dict):
            return
        entry["title"] = d.get("title")
        entry["status"] = d.get("status")
        entry["pid"] = d.get("pid") if isinstance(d.get("pid"), int) else None
        entry["worker_pid"] = d.get("worker_pid") if isinstance(d.get("worker_pid"), int) else None
        prog = d.get("progress")
        if isinstance(prog, (int, float)):
            entry["progress"] = prog
        else:
            widgets = d.get("widgets") if isinstance(d.get("widgets"), list) else []
            for w in widgets:
                if isinstance(w, dict) and w.get("type") == "progress" and isinstance(w.get("value"), (int, float)):
                    entry["progress"] = w["value"]
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
        out = {"title": None, "status": None, "pid": None, "worker_pid": None, "progress": None}
        in_widgets = False
        current_widget = None

        def _flush_widget():
            if not current_widget:
                return
            if current_widget.get("id") == "progress":
                val = current_widget.get("value")
                if isinstance(val, (int, float)):
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
                elif k == "progress" and isinstance(val, (int, float)):
                    out["progress"] = val
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
                # → 캐시 외부(매 /dashboards 요청)에서 _pid_alive 검증. pid None 이면
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
            "live_session_limit": _load_hub_setting()["live_session_limit"],  # Issue129: 카드당 세션 행 상한
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
        # Issue99: live 세션 dedup — (cwd_hash, live_pid) 동일분은 freshest 1개만 노출.
        #   훅 중복 fire(동일 프로세스 다중 sid)로 인한 중복 카드 차단. 비-freshest 는
        #   skip set 에 담아 루프에서 제외(+ terminal prune).
        live_best = {}   # (h, live_pid) -> (updated, sid)
        for (h, sid), entry in sess_snap:
            if entry.get("content_type") != "live":
                continue
            lp = entry.get("live_pid")
            if lp is None:
                continue
            u = entry.get("updated", 0) or 0
            prev = live_best.get((h, lp))
            if prev is None or u > prev[0]:
                live_best[(h, lp)] = (u, sid)
        live_dup_skip = set()
        for (h, sid), entry in sess_snap:
            if entry.get("content_type") != "live":
                continue
            lp = entry.get("live_pid")
            if lp is None:
                continue
            if live_best.get((h, lp), (None, None))[1] != sid:
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
            elif entry.get("content_type") == "live":
                # Issue135: 수동 dismiss tombstone — TTL 내면 live_pid 생존(force_live)
                #   이어도 표시 제외. sessions 는 유지(pop 안 함) → TTL 만료 후 자동 복귀.
                #   살아있는 세션의 재등록 heartbeat 부활을 렌더 단계에서 차단.
                if f"{h}|{sid}" in live_dismissed_snap:
                    continue
                lp = entry.get("live_pid")
                if lp is not None:
                    if not _pid_alive(int(lp)):
                        terminal_keys.append((h, sid))
                        continue
                    force_live = True
                else:
                    if age > LIVE_TTL:
                        terminal_keys.append((h, sid))
                        continue
                    force_live = True
                # 카드 제목 (Issue127 후속): VSCode 탭 제목(ai-title) 최우선 — 세션 JSONL 의
                #   aiTitle 이 VSCode 가 표시하는 제목의 SSOT. hub 카드를 VSCode 와 일치시킴.
                #   ai-title 미생성(세션 극초기)이면 live_label(프롬프트 요약), 그다음 win fallback.
                #   Issue121 SessionStart 훅이 label 미전송·capabilities 만 보낼 때 win 대비.
                ai_title = _session_ai_title(proj_snap.get(h, {}).get("cwd", ""), sid)
                lbl = entry.get("live_label")
                if ai_title:
                    dash_title = ai_title
                elif isinstance(lbl, str) and lbl.strip():
                    dash_title = lbl.strip()
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
            origin = "vscode" if _ep == "claude-vscode" else "terminal"
            results.append({
                "cwd": p.get("cwd", ""),
                "cwd_hash": h,
                "sid": sid,
                "name": p.get("name", ""),
                "color": p.get("color", "hsl(220,60%,45%)"),
                "emoji": _project_emoji(p.get("cwd", "")),
                "mode": entry.get("mode"),
                "content_type": entry.get("content_type"),
                "origin": origin,         # Issue177: "vscode" | "terminal" (카드 배지·클릭 분기)
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
            results.sort(key=lambda x: (_prj_id.get((x.get("cwd") or "").rstrip("/"), 10**9),
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
        """Issue115: dashboard 데이터 파일 폴링 — _doc_work/z_htm/*.dash.yaml 의 mtime 반환"""
        qs = parse_qs(parsed.query)
        cwd = unquote(qs.get("cwd", [""])[0]) or ""

        files = {}
        if cwd:
            z_htm_dir = os.path.join(cwd, "_doc_work", "z_htm")
            if os.path.isdir(z_htm_dir):
                for f in os.listdir(z_htm_dir):
                    if f.endswith(".dash.yaml"):
                        path = os.path.join(z_htm_dir, f)
                        try:
                            stat = os.stat(path)
                            files[f] = {"mtime_ts": stat.st_mtime}
                        except Exception:
                            pass

        self._send_json(200, {"files": files})

    def _handle_hub(self, parsed):
        # Issue42/47: hub_setting.yml 값으로 HUB_HTML placeholder 치환
        setting = _load_hub_setting()
        html_str = (HUB_HTML
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
        stream-json)가 프롬프트 전(live_label 없음) 빈 카드로 잔존한다 → live_pid
        에 SIGTERM(graceful) + sessions prune + dismiss tombstone(LIVE_DISMISS_TTL
        내 재등록 차단). titled live·dashboard 세션은 절대 건드리지 않는다(오살 방지).
        Issue136 dedup 이 cwd 당 1개로 줄이나, 본 버튼은 살아있는 좀비 자체를 제거해
        부활을 원천 차단한다. 127.0.0.1 trust → 토큰 미요구."""
        client_ip = self.client_address[0] if self.client_address else ""
        if not _ip_allowed(client_ip):
            self._send_json(403, {"error": "localhost only"})
            return
        # 빈 live 세션 스냅샷 수집 (content_type=="live" + live_label 빈)
        targets = []  # (h, sid, pid)
        with sessions_lock:
            snap = list(sessions.items())
        for (h, sid), entry in snap:
            if not isinstance(entry, dict) or entry.get("content_type") != "live":
                continue
            lbl = entry.get("live_label")
            if isinstance(lbl, str) and lbl.strip():
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
            f"{len(already_dead)} pruned={pruned}")
        self._send_json(200, {
            "status": "ok",
            "killed": killed,
            "killed_count": len(killed),
            "already_dead_count": len(already_dead),
            "pruned": pruned,
        })

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

            def _mtime_key(e):
                try:
                    return os.path.getmtime(e.get("path", ""))
                except OSError:
                    return e.get("registered_at", 0) or 0
            entries.sort(key=_mtime_key, reverse=True)
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
    def _effective_dash_status(d) -> str:
        """dash dict 의 실효 status. Issue58: status='running' 이나 runner pid 가 죽었으면
        'stale' 로 강등. pid 가 정수가 아니면 검증 불가 → 원본 status 유지.
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
            if isinstance(pid, int) and not _pid_alive(pid):
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
        self._send_json(200, {"status": "ok", "type": kind, "path": path, "count": count})

    def _handle_hub_rescan(self, parsed):
        """Issue41: 수동 부트스트랩. 등록 프로젝트의 z_htm + /tmp/___pm 를 1회 스캔하여
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
        log(f"POST /hook-event — event={event} cwd={cwd} (feed={count})")
        self._send_json(200, {"status": "ok", "count": count})

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
        try:
            subprocess.Popen(["open", "-a", "Visual Studio Code", cwd],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log(f"POST /open-project — cwd={cwd}")
        self._send_json(200, {"status": "opened", "cwd": cwd})

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
        uri = f"vscode://anthropic.claude-code/open?session={sid}"
        try:
            # 워크스페이스 창 보장·전면화 후(0.4s) 세션 URI 로 탭 포커스.
            subprocess.Popen(
                ["bash", "-c",
                 f'open -a "Visual Studio Code" {shlex.quote(cwd)}; '
                 f'sleep 0.4; open {shlex.quote(uri)}'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._send_json(500, {"error": f"spawn failed: {e}"})
            return
        log(f"POST /open-session — cwd={cwd} sid={sid}")
        self._send_json(200, {"status": "opened", "sid": sid})

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
            subprocess.Popen(["open", "-a", "Visual Studio Code", HUB_SETTING_FILE],
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
        lang = i18n.norm_lang(_load_hub_setting().get("language"))
        schema = []
        for s in HUB_SETTING_SCHEMA:
            item = dict(s)
            tk = "settings.field." + s["key"]
            tr = i18n.t(tk, lang)
            item["comment"] = s["comment"] if tr == tk else tr
            schema.append(item)
        self._send_json(200, {
            "values": _load_hub_setting_raw(),
            "schema": schema,
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
            subprocess.Popen(["open", "-a", "Visual Studio Code", PROJECTS_MD],
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
        # path traversal 방어 — prj 는 숫자만
        if not re.fullmatch(r"\d+", prj):
            self._send_json(400, {"error": "prj must be a number"})
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
            if not window_name or not re.match(r'^[a-zA-Z0-9_.:-]+$', window_name):
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
            self.send_header("Access-Control-Allow-Origin", "null")
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
        self.send_header("Access-Control-Allow-Origin", "null")
        self.end_headers()
        self.wfile.write(body)

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
            log(f"GET /htm-doc — unregistered path rejected: {abs_path}")
            self._send_json(403, {"error": "not a registered htm doc"})
            return
        # Issue102: htm 스킬(Issue123)이 .htm 확장자로 문서를 씀 → .html/.htm 모두 허용
        if not abs_path.endswith((".html", ".htm")):
            self._send_json(403, {"error": "extension not allowed"})
            return
        try:
            with open(abs_path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json(404, {"error": "file not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        # Issue35: .dash.{json,yaml,yml} 동적 렌더 (인라인 dashboard HTML wrapper)
        # Issue138: cwd/token 전달 — 컨트롤바(stop/kill/refresh) /control 호출 wiring
        if abs_path.endswith((".dash.json", ".dash.yaml", ".dash.yml")):
            self._serve_dash_inline(abs_path, cwd, token)
            return
        # Issue102: htm 스킬(Issue123)이 .htm 확장자로 문서를 씀 → .html/.htm 모두 허용
        if not abs_path.endswith((".html", ".htm")):
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
                b"var es=new EventSource(url);"
                b"es.addEventListener('reload',function(ev){"
                b"try{var b=JSON.parse(ev.data||'{}');var f=b.file||'';"
                b"var tn=tgt?tgt.split('/').pop():'';"
                b"if(!tn||f.endsWith(tn)){location.reload();}"
                b"}catch(e){location.reload();}"
                b"});"
                b"es.addEventListener('error',function(){});"
                b"}catch(e){}"
                b"})();</script>"
            )
            lower = body.lower()
            idx = lower.rfind(b"</body>")
            if idx >= 0:
                body = body[:idx] + inject + body[idx:]
            else:
                body = body + inject
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
            '.then(function(j){if(j&&j.error)alert("VSCode 열기 실패: "+j.error);})'
            '.catch(function(){alert("hub 서버 미응답 — VSCode 열기 실패");});'
        )
        header_html = (
            '<header class="dash-hdr"><h1>' + esc(title) + '</h1>'
            '<nav class="hdr-actions">'
            '<a class="proj-badge" href="#" title="VSCode 로 ' + proj_label + ' 열기" onclick=\'' + onclick_open + '\'>📁 ' + proj_label + '</a>'
            '<a class="sess-link" href="/hub" title="활성 세션 목록 (hub)">🛰 활성 세션</a>'
            '<a class="hub-link" href="/hub" target="_blank">🗂 Hub</a>'
            '<button type="button" onclick="window.close()">닫기 ✕</button>'
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
  .hdr-actions .proj-badge, .hdr-actions .sess-link, .hdr-actions .hub-link, .hdr-actions button {{ color: #fff; text-decoration: none; cursor: pointer; white-space: nowrap; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.35); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }}
  .hdr-actions .proj-badge:hover, .hdr-actions .sess-link:hover, .hdr-actions .hub-link:hover, .hdr-actions button:hover {{ background: rgba(255,255,255,0.28); text-decoration: underline; }}
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
                entry["capabilities"] = caps or entry.get("capabilities", {})
                entry["updated"] = now  # heartbeat (live TTL 갱신)
                # Issue98: 명시 "live" 재등록만 content_type 승격 — dashboard 등 기존
                #   세션 타입은 보존 (response 기본값이 덮어쓰지 않도록).
                if reg_ctype == "live":
                    entry["content_type"] = "live"
            # Issue98: live 메타 기록 (pid·label) — register/heartbeat 마다 갱신.
            if reg_ctype == "live":
                entry["live_pid"] = live_pid
                entry["live_label"] = live_label
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
        if is_data:
            with sessions_lock:
                entry = sessions.get((cwd_h, sid))
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
            self._send_json(200, {
                "content_type": entry.get("content_type", "response"),
                "content": content_out,
                "mode": entry.get("mode", "A"),
                "updated": entry.get("updated", 0),
                "capabilities": entry.get("capabilities", {}),
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
        if action_type not in ("notify", "link", "control"):
            self._send_json(400, {"error": f"invalid action_type: {action_type!r}"})
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
header { background: linear-gradient(90deg, hsl(220,60%,45%), hsl(280,60%,45%)); color: white; padding: 1rem 1.5rem;
  display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
header .hub-logo { height: 3em; flex: 0 0 auto; }
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
.header-actions { display: flex; align-items: center; gap: 0.4rem; flex-shrink: 0; }
.btn-settings { flex: none; background: transparent; border: none;
  color: white; padding: 0.4rem 0.5rem; border-radius: 6px; font-size: 1.1em; cursor: pointer; line-height: 1; }
.btn-settings:hover { background: rgba(255,255,255,0.2); }
/* Issue168: 설정 모달 (3탭) */
.set-tabs { display: flex; gap: 0.3rem; border-bottom: 1px solid var(--border); margin-bottom: 0.9rem; }
.set-tab { background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--muted);
  padding: 0.5rem 0.9rem; font-size: 0.95em; cursor: pointer; }
.set-tab:hover { color: var(--fg); }
.set-tab.active { color: var(--fg); border-bottom-color: hsl(220,80%,55%); font-weight: 600; }
.set-pane { display: none; }
.set-pane.active { display: block; }
.set-row { display: flex; align-items: center; gap: 0.7rem; padding: 0.5rem 0; border-bottom: 1px dashed var(--border); }
.set-row:last-child { border-bottom: none; }
.set-row label.set-key { flex: 0 0 13.5em; font-family: ui-monospace, monospace; font-size: 0.9em; }
.set-row .set-input { flex: 0 0 auto; }
.set-row .set-input input[type=number] { width: 6em; }
.set-row .set-input input[type=text] { width: 14em; }
.set-row .set-input select, .set-row .set-input input { padding: 0.25rem 0.4rem; border: 1px solid var(--border);
  border-radius: 5px; background: var(--bg); color: var(--fg); font-size: 0.9em; }
.set-row .set-desc { flex: 1 1 auto; min-width: 0; font-size: 0.78em; color: var(--muted); }
.set-row .set-badge { flex: 0 0 auto; font-size: 0.72em; padding: 0.05rem 0.4rem; border-radius: 9px; white-space: nowrap; }
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
.pl-table tbody tr:hover td { background: #e8eef9; }
.pl-table tbody tr.pl-sel td { background: #d4e2fb; box-shadow: inset 3px 0 0 hsl(220,80%,50%); }
.pl-table tbody tr.pl-sel:hover td { background: #c7d8f7; }
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
.pl-table td.pl-color { text-align: center; }
.pl-swatch { width: 1.5em; height: 1.5em; border-radius: 4px; border: 1px solid rgba(0,0,0,0.25); display: inline-block; }
/* Issue42: hub 2-컬럼 — .hub-main(2fr) + .hub-feed(1fr) */
main { padding: 1.5rem; max-width: 1600px; margin: 0 auto; display: flex; gap: 1rem; align-items: flex-start; }
.hub-main { flex: 2; min-width: 0; }
.status-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; font-size: 0.9em; color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.4rem; }
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
.dash-section-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.4rem; }
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
/* Issue63: 첫 섹션(활성 세션)만 상단 margin 제거. 각 h2 가 section 의 first-child
   라 :first-child 를 쓰면 모든 섹션 제목이 margin-top:0 → 섹션 간 간격 소실. */
#live-sessions-section .section-title { margin-top: 0; }
.count-badge { background: var(--card); padding: 0.1rem 0.5rem; border-radius: 10px; font-size: 0.8em; border: 1px solid var(--border); }
.card.live { border-left: 3px solid hsl(140,60%,45%); }
/* Issue101: 활성 세션 카드 클릭 → VSCode 열기 (cdfv 효과). hover 로 클릭 가능 시각화 */
.card.live[data-cwd] { transition: box-shadow .12s, transform .12s; }
.card.live[data-cwd]:hover { box-shadow: 0 2px 10px rgba(0,0,0,.18); transform: translateY(-1px); }
/* Issue101: 프로젝트별 그룹 카드 — head 에 세션 수 배지, body 는 세션 topic 리스트 */
.card-head .name .live-badge { background: rgba(0,0,0,0.16); color: #1a1a1a; padding: 0.02rem 0.42rem; border-radius: 10px; font-size: 0.78em; font-weight: 600; margin-left: 0.3rem; }
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
.live-origin { flex-shrink: 0; font-size: 0.82em; line-height: 1; opacity: 0.85; cursor: help; }
.live-item[data-origin="terminal"] { cursor: default; }
.live-item[data-origin="terminal"]:hover { background: rgba(127,127,127,.06); }
.live-acts { display: flex; align-items: center; gap: 0.3rem; flex-shrink: 0; }
.live-acts .approve-btn { background: #e8a020; color: #fff; border: 1px solid #c8861a; font-weight: 600; font-size: 0.76em; padding: 0.12rem 0.45rem; border-radius: 4px; cursor: pointer; }
.live-acts .approve-btn:hover { background: #c8861a; }
.live-acts .card-close { width: 1.5em; height: 1.5em; padding: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; border: 1px solid var(--border); background: var(--bg); color: var(--muted); cursor: pointer; font-size: 0.78em; line-height: 1; }
.live-acts .card-close:hover { background: #c33; color: #fff; border-color: #c33; }
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
  padding: 0.6rem 0.8rem; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--card); z-index: 1; }
.feed-title-label { font-weight: 600; font-size: 0.95em; }
.feed-actions { display: flex; gap: 0.3rem; align-items: center; }
#feed-toggle, #feed-collapse-all, #feed-keep, #feed-clear { background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
  cursor: pointer; padding: 0.2rem 0.55rem; font-size: 0.8em; color: var(--fg); white-space: nowrap; }
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
.feed-strip { display: none; flex: none; align-self: stretch; cursor: pointer;
  background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  writing-mode: vertical-rl; text-align: center; padding: 0.6rem 0.35rem;
  color: var(--muted); font-size: 0.82em; }
.feed-strip:hover { background: var(--code-bg); }
.hub-feed.hidden + .feed-strip { display: block; }
@media (max-width: 900px) {
  main { flex-direction: column; }
  .hub-main, .hub-feed { flex: none; width: 100%; }
  .hub-feed { max-width: none; position: static; max-height: 60vh; }
}
</style>
</head>
<body>
<header>
  <img class="hub-logo" src="/fpm-icon.png" alt="fPm">
  <div class="header-text">
    <h1>fPm Hub<span id="hub-headline"></span></h1>
    <div class="sub" id="hub-important">{T:common.loading}</div>
  </div>
  <div class="header-actions">
    <button class="btn-project-list" id="btn-project-list" title="{T:projectList.openTitle}">📋 Projects</button>
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
  </span>
</div>
<div class="error-bar" id="error-bar"></div>
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
      <button id="feed-toggle" title="{T:feed.hideTitle}">{T:feed.hide}</button>
    </span>
  </div>
  <div class="feed-list" id="feed-list"><div class="feed-empty">{T:common.loading}</div></div>
</aside>
<div class="feed-strip" id="feed-strip" title="{T:feed.showTitle}">{T:feed.show}</div>
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
  <div class="modal" role="dialog" aria-modal="true" aria-label="{T:settings.title}" style="width:min(720px,94vw)">
    <div class="modal-head">
      <span class="modal-title">{T:settings.title}</span>
      <button class="modal-close" id="set-close" title="{T:settings.close}" aria-label="{T:settings.close}">✕</button>
    </div>
    <div class="modal-body">
      <div class="set-tabs" id="set-tabs">
        <button class="set-tab active" data-tab="basic">{T:settings.tab.basic}</button>
        <button class="set-tab" data-tab="session">{T:settings.tab.session}</button>
        <button class="set-tab" data-tab="advanced">{T:settings.tab.advanced}</button>
      </div>
      <div class="set-pane active" data-pane="basic" id="set-pane-basic"></div>
      <div class="set-pane" data-pane="session" id="set-pane-session"></div>
      <div class="set-pane" data-pane="advanced" id="set-pane-advanced">
        <div class="set-warn">{T:settings.advancedWarn}</div>
      </div>
    </div>
    <div class="modal-foot" style="gap:0.5rem">
      <button class="pl-edit-btn" id="set-open-file" title="{T:settings.openFileTitle}" style="background:#555;border-color:#444">{T:settings.openFile}</button>
      <span style="flex:1 1 auto"></span>
      <button class="cf-btn cf-cancel" id="set-cancel">{T:settings.cancel}</button>
      <button class="set-ok-btn" id="set-save">{T:settings.save}</button>
    </div>
  </div>
</div>
<div id="set-tip" hidden></div>
<script>
// Issue169 Stage8: 클라이언트 i18n — 서버가 주입한 사전(window.__i18n)·언어(window.__lang).
//   t(key, vars): 사전 조회 후 {var} 보간. 누락 키 → key 자체(가시화). vars 값은 그대로 삽입(호출부에서 escape).
window.__lang = "{I18N_LANG}";
window.__i18n = {I18N_JSON};
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
    const r = await fetch('/dashboards?_=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    errorBar.style.display = 'none';
    renderProjects(data.projects || []);
    renderLiveSessions(data.live_sessions || [], data.live_session_limit);
    renderHtmDocs(data.htm_docs || []);
    renderFeed(data.hook_feed || []);
    renderHeadline(data.hook_feed || []);
    renderImportant(data.important_events || []);
    const dashCount = (data.projects || []).reduce((s,p)=>s+p.dashes.length,0);
    // dashboard 0건이면 섹션(헤더 포함) 숨김
    document.getElementById('dashboard-section').style.display = dashCount > 0 ? '' : 'none';
    const liveCount = (data.live_sessions || []).length;
    const htmCount = (data.htm_docs || []).length;
    if (hubStats) hubStats.textContent = `${(data.projects||[]).length} project · ${dashCount} dashboard · ${liveCount} live session · ${htmCount} hub doc`;
    updated.textContent = t('statusbar.updated', {time: new Date().toLocaleTimeString()});
  } catch (e) {
    errorBar.textContent = '❌ ' + e.message;
    errorBar.style.display = 'block';
  }
}

// Issue104: "외 N개 더" 로 확장된 카드의 cwd 집합. 5초 reload() 재렌더에도 확장 상태 유지.
const expandedCards = new Set();
// Issue33: SSE alive + 최근 갱신 session 노출 (별도 섹션)
function renderLiveSessions(list, limit) {
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
    if (!groups.has(key)) groups.set(key, {cwd: s.cwd, name: s.name, color: s.color, emoji: s.emoji, items: []});
    groups.get(key).items.push(s);
  }
  const rowHtml = (s, extraCls) => {
    // Issue66: 큐 dashboard(supervisor_pid 존재)는 graceful remove, 일반은 stop
    const killBtn = s.pid
      ? (s.supervisor_pid
          ? `<button class="card-close" onclick="removeQueueDash('${escapeHtml(s.cwd)}','${escapeHtml(s.token)}',${s.supervisor_pid},'${escapeHtml(s.sid)}',this)" title="${escapeHtml(t('liveSessions.removeQueueTitle', {pid: s.supervisor_pid}))}" aria-label="remove">✕</button>`
          : `<button class="card-close" onclick="stopRunner('${escapeHtml(s.cwd)}','${escapeHtml(s.token)}',${s.pid},this)" title="${escapeHtml(t('liveSessions.killRunnerTitle', {pid: s.pid}))}" aria-label="kill">✕</button>`)
      // Issue132: pid 없는 live(claude) 세션 — dismiss 버튼(프로세스 kill 아님, 카드만 제거)
      : `<button class="card-close" onclick="dismissSession('${escapeHtml(s.cwd)}','${escapeHtml(s.token)}','${escapeHtml(s.sid)}',this)" title="${escapeHtml(t('liveSessions.dismissTitle'))}" aria-label="dismiss">✕</button>`;
    // Issue66 Phase 7: 큐 dashboard 에 waiting_approval 항목이 있으면 승인 버튼
    const approveBtn = (s.supervisor_pid && s.waiting_approval_item)
      ? `<button class="approve-btn" onclick="approveQueueItem('${escapeHtml(s.cwd)}','${escapeHtml(s.token)}','${escapeHtml(s.sid)}','${escapeHtml(s.waiting_approval_item)}',this)" title="${escapeHtml(t('liveSessions.approveTitle', {item: s.waiting_approval_item}))}">▶ ${escapeHtml(s.waiting_approval_item)}</button>`
      : '';
    // Issue129: 명령(프롬프트) 전 세션은 title 없음 → "-" 표기 (기존 content_type/'response' fallback 폐기)
    const topic = s.title || '-';
    // Issue177: 세션 출처 배지 — VSCode(🆚) vs 터미널(⌨️). origin 은 서버가 capabilities.entrypoint 로 판정.
    //   터미널 세션은 클릭해도 VSCode 재오픈 안 함(아래 위임 핸들러 분기). data-origin 으로 핸들러에 전달.
    const origin = s.origin === 'vscode' ? 'vscode' : 'terminal';
    const originBadge = origin === 'vscode'
      ? `<span class="live-origin vs" title="VSCode 세션 — 클릭 시 탭 포커스">🆚</span>`
      : `<span class="live-origin term" title="터미널 세션(CLI) — 포커스 불가, 클릭 무동작">⌨️</span>`;
    // Issue131: 행 클릭 → 해당 Claude Code 세션 탭 포커스 (data-sid·data-cwd). title 툴팁으로 전체 표시(ellipsis 보완).
    // Issue104: extraCls 로 초과 행에 live-hidden 부여 (접힘 상태 기본 숨김).
    const cls = 'live-item' + (extraCls ? ' ' + extraCls : '');
    return `<li class="${cls}" data-sid="${escapeHtml(s.sid)}" data-cwd="${escapeHtml(s.cwd)}" data-origin="${origin}" title="${escapeHtml(t('liveSessions.topicTitle', {topic: topic}))}">${originBadge}<span class="live-topic">${escapeHtml(topic)}</span><span class="live-acts">${approveBtn}${killBtn}</span></li>`;
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
    return `<div class="card live${expCls}" data-cwd="${escapeHtml(g.cwd)}" title="{T:common.openVscodeTitle}">
      <div class="card-head" style="background:${escapeHtml(g.color)}">
        <span class="name">${escapeHtml(g.emoji || '📁')} ${escapeHtml(g.name)} <span class="live-badge">${g.items.length}</span></span>
      </div>
      <div class="card-body"><ul class="live-list">${rows}</ul></div>
    </div>`;
  });
  lg.innerHTML = cards.join('');
}

// Issue40: htm 스킬 단발 출력 문서 노출 (별도 섹션)
function _htmCardHtml(d) {
  // Issue69: z_htm 기본 경로는 생략, 파일명만 열기 버튼 옆에 표시
  const fname = (d.path || '').split('/').pop();
  // Issue169: '열기' 텍스트 → 열기 이모지(↗)만. title 로 의미 보강.
  const openLink = d.view_url
    ? `<a class="doc-open" href="${escapeHtml(d.view_url)}" target="_blank" title="{T:htmDocs.openDocShort}">↗</a>`
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
const feedToggle = document.getElementById('feed-toggle');
const feedStrip = document.getElementById('feed-strip');
const feedCollapseAll = document.getElementById('feed-collapse-all');
const feedKeep = document.getElementById('feed-keep');
const feedClear = document.getElementById('feed-clear');
const FEED_KEEP_N = 20;  // "20개만" 버튼이 보존하는 최신 항목 수

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
    toast(t('msg.sessionTabOpened'), 'ok');
  } catch (e) {
    toast('❌ ' + e.message, 'err');
  }
}

// 사이드바 숨김/보기 — localStorage 우선, 없으면 hub_setting.yml 기본값
function applyFeedVisible(visible) { hubFeed.classList.toggle('hidden', !visible); }
function setFeedVisible(visible) {
  applyFeedVisible(visible);
  localStorage.setItem('hubFeedVisible', visible ? '1' : '0');
}
feedToggle.addEventListener('click', () => setFeedVisible(false));
feedStrip.addEventListener('click', () => setFeedVisible(true));
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
  const rows = list.map(p => {
    const off = !!p.htm_off;
    const reason = off ? (p.htm_reason || 'hub off') : t('projectList.reasonOn');
    return `<tr data-path="${escapeHtml(p.path)}"${off ? ' class="htm-off"' : ''} data-htm-reason="${escapeHtml(reason)}" title="${escapeHtml(t('projectList.rowTitle', {name: p.name}))}">
    <td class="pl-toggle"><button type="button" class="htm-tgl ${off ? 'off' : 'on'}" data-path="${escapeHtml(p.path)}" role="switch" aria-checked="${off ? 'false' : 'true'}" aria-label="${escapeHtml(t('projectList.toggleAria', {state: off ? 'off' : 'on', name: p.name}))}" title="${escapeHtml(t('projectList.toggleTitle', {reason: reason}))}"><span class="htm-tgl-knob"></span></button></td>
    <td class="pl-id">${escapeHtml(p.id)}</td>
    <td>${escapeHtml(p.emoji || '')} ${escapeHtml(p.name)}</td>
    <td>${escapeHtml(p.domain)}</td>
    <td class="pl-path"><code>${escapeHtml(p.path)}</code></td>
    <td>${escapeHtml(p.desc)}</td>
    <td class="pl-color">${p.color ? `<span class="pl-swatch" style="background:${escapeHtml(p.color)}" title="${escapeHtml(p.color)}"></span>` : ''}</td>
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
    <th class="pl-toggle" title="{T:projectList.toggleColTitle}"><button type="button" id="htm-tgl-all" class="htm-tgl ${masterCls}" data-target="${masterTarget}" role="switch" aria-checked="${masterCls === 'on' ? 'true' : 'false'}" aria-label="{T:projectList.masterAria}" title="${escapeHtml(masterTitle)}"><span class="htm-tgl-knob"></span></button><div class="pl-toggle-lbl">hub</div></th><th>{T:projectList.col.id}</th><th>{T:projectList.col.name}</th><th>Domain</th><th>{T:projectList.col.path}</th><th>{T:projectList.col.desc}</th><th>{T:projectList.col.color}</th>
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
    if (row.dataset.origin === 'terminal') {
      toast('⌨️ 터미널 세션 — VSCode 로 포커스 불가', 'err');
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
let setSchema = [], setInitial = {}, setMtime = 0;

function setEsc(html) {
  return String(html).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
const SET_BADGE_TIP = {
  auto: t('settings.apply.auto'),
  hook: t('settings.apply.hook'),
  restart: t('settings.apply.restart'),
};
function setBadge(apply) {
  const m = {auto: ['b-auto', t('settings.applyBadge.auto')], hook: ['b-hook', t('settings.applyBadge.hook')], restart: ['b-restart', t('settings.applyBadge.restart')]}[apply] || ['',''];
  const tip = SET_BADGE_TIP[apply] || '';
  return `<span class="set-badge ${m[0]}" data-tip="${setEsc(tip)}">${m[1]}</span>`;
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
    if (s.allow_custom) html += `<option value="__custom__" ${isCustom?'selected':''}>${t('settings.customApp')}</option>`;
    html += '</select>';
    if (s.allow_custom) html += ` <input type="text" id="${id}-c" data-key="${s.key}" data-type="custom" value="${isCustom?setEsc(val):''}" placeholder="/Applications/X.app" style="${isCustom?'':'display:none'};width:13em">`;
    return html;
  }
  if (s.widget === 'number') {
    return `<input type="number" id="${id}" data-key="${s.key}" data-type="number" min="${s.min||0}" value="${setEsc(val)}">`;
  }
  return `<input type="text" id="${id}" data-key="${s.key}" data-type="text" value="${setEsc(val)}" placeholder="${s.optional?t('settings.optional'):''}">`;
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
      row.innerHTML = `<label class="set-key" for="setf-${s.key}" title="${setEsc(s.comment||'')}">${setEsc(s.key)}${s.deprecated?' <span style="font-size:0.75em;color:#c60">(deprecated)</span>':''}</label>`
        + `<span class="set-input">${setRenderField(s, setInitial[s.key])}</span>`
        + `<span class="set-desc" title="${setEsc(s.comment||'')}">${setEsc(s.comment||'')}</span>`
        + setBadge(s.apply);
      pane.appendChild(row);
    }
  }
  // 토글 스위치 클릭
  setModal.querySelectorAll('.set-sw').forEach(b => b.addEventListener('click', () => {
    const on = !b.classList.contains('on');
    b.classList.toggle('on', on); b.setAttribute('aria-checked', on);
  }));
  // 사용자 지정 select → 텍스트 토글
  setModal.querySelectorAll('select[data-type="select"]').forEach(sel => sel.addEventListener('change', () => {
    const c = document.getElementById('setf-' + sel.dataset.key + '-c');
    if (c) c.style.display = sel.value === '__custom__' ? '' : 'none';
  }));
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
async function openSettings() {
  try {
    const r = await fetch('/api/settings');
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    setSchema = j.schema; setInitial = j.values; setMtime = j.mtime;
    setRenderForm();
    setModal.hidden = false;
  } catch (e) { toast(t('settings.loadFail', {err: e.message}), 'err'); }
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
setModal.addEventListener('mouseover', e => { const b = e.target.closest('.set-badge'); if (b) setTipShow(b); });
setModal.addEventListener('mouseout', e => { if (e.target.closest('.set-badge')) setTipHide(); });
document.getElementById('btn-settings').addEventListener('click', openSettings);
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
.dash-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
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
<header class="sess"><h1>📁 {NAME} — session <code>{SID}</code></h1><span class="meta">mode <span id="mode-tag">?</span></span></header>
<div class="status" id="status">초기 로드 중...</div>
<main id="content"><em>대기 중...</em></main>
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
if (PREVIEW) {
  setStatus('connected', 'PREVIEW (정적 · TTL ' + 60 + 's)');
} else {
  try {
    const es = new EventSource(SSE_URL);
    es.addEventListener('reload', () => reload(true));
    es.addEventListener('session_update', () => reload(true));
    es.onopen = () => { setStatus('connected', 'SSE 연결됨'); stopPolling(); };
    es.onerror = () => { setStatus('error', 'SSE error — reconnect 대기'); startPolling(); };
  } catch (e) {
    console.warn('SSE failed, polling only:', e);
    startPolling();
  }
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
    global HOST
    if _HOST_ENV is None:
        HOST = (_load_hub_setting().get("bind_host") or "127.0.0.1").strip() or "127.0.0.1"

    # 개방 모드(HOST 가 루프백 아님)에서만 Servers.md allowlist 적재.
    # 기본 127.0.0.1 이면 빈 set 유지 → 루프백만 통과(기존 동작 그대로).
    if HOST not in LOOPBACK_IPS:
        _ips, _nets = _load_server_allowlist()
        ALLOWED_IPS.update(_ips)
        ALLOWED_NETS.extend(_nets)
        log(f"[allowlist] 개방 모드 — bind={HOST}, 허용 IP {len(ALLOWED_IPS)}개: "
            f"{sorted(ALLOWED_IPS)}, CIDR {len(ALLOWED_NETS)}개: "
            f"{[str(n) for n in ALLOWED_NETS]} (+루프백)")
        sys.stderr.write(
            f"[hub] ⚠️ 외부 개방 모드 — bind={HOST}:{PORT}, "
            f"allowlist {len(ALLOWED_IPS)} hosts + {len(ALLOWED_NETS)} CIDR (+loopback)\n")

    # Issue59: bind 를 PID_FILE 기록보다 먼저 수행 — bind 실패 시 PID_FILE 미생성·미삭제.
    #          (실패 경로의 cleanup 이 살아있는 다른 서버의 pid 파일을 지우던 버그 차단)
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        sys.stderr.write(f"[hub] bind failed on port {PORT}: {e}\n")
        sys.exit(2)
    srv.daemon_threads = True

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    log(f"started on http://{HOST}:{PORT} (pid={os.getpid()}, projects_restored={len(projects)})")

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
