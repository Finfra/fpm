#!/usr/bin/env python3
"""fpm MCP 서버 — hub/pm 기능을 Model Context Protocol(stdio)로 노출.

무의존성 (Python stdlib only — services/hub/server.py 와 동일 ethos).
MCP stdio 전송: newline-delimited JSON-RPC 2.0.

도구:
  fpm_list_projects   : 프로젝트 번호→경로 매핑 전체
  fpm_resolve_project : 번호 → 절대 경로
  fpm_list_servers    : Servers.md 서버 목록
  hub_status          : hub 서버 상태 (GET /healthz)
  hub_open_project    : 프로젝트를 VS Code 로 열기 (POST /open-project)

Claude Code 등록 예시(.mcp.json):
  { "mcpServers": { "fpm": { "command": "python3",
      "args": ["/ABS/PATH/fpm/mcp/server.py"] } } }
"""
import json
import os
import re
import sys
import urllib.request

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "fpm", "version": "0.1.0"}
HUB_BASE = os.environ.get("FPM_HUB_BASE", "http://127.0.0.1:9876")


# ── pm 데이터 접근 ──────────────────────────────────────────────
def _base_dir():
    """projects/ 폴더 경로 (~/.info/__pmBasePath.txt 기준)."""
    cfg = os.path.expanduser("~/.info/__pmBasePath.txt")
    if not os.path.isfile(cfg):
        return None
    with open(cfg) as f:
        return os.path.expanduser(os.path.expandvars(f.read().strip()))


def _repo_dir():
    base = _base_dir()
    return os.path.dirname(base) if base else None


def list_projects():
    base = _base_dir()
    if not base or not os.path.isdir(base):
        return {"error": "projects dir not found (run install.sh)", "base": base}
    out = []
    for name in sorted(os.listdir(base), key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0)):
        p = os.path.join(base, name)
        if name.isdigit() and os.path.isfile(p):
            with open(p) as f:
                out.append({"id": int(name), "path": f.read().strip()})
    return {"projects": out, "count": len(out)}


def resolve_project(pid):
    base = _base_dir()
    if not base:
        return {"error": "projects dir not found"}
    p = os.path.join(base, str(pid))
    if not os.path.isfile(p):
        return {"error": f"project {pid} not found"}
    with open(p) as f:
        raw = f.read().strip()
    return {"id": int(pid), "path": raw, "resolved": os.path.expanduser(raw)}


def list_servers():
    repo = _repo_dir()
    candidates = []
    if repo:
        candidates.append(os.path.join(repo, "Servers.md"))
    candidates.append(os.path.join(os.getcwd(), "Servers.md"))
    sf = next((c for c in candidates if os.path.isfile(c)), None)
    if not sf:
        return {"error": "Servers.md not found", "looked": candidates}
    rows = []
    with open(sf) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|") or ":---" in line:
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 6 and cells[0].lower() != "id":
                rows.append({
                    "id": cells[0], "name": cells[1], "alias": cells[2],
                    "host": cells[3], "port": cells[4], "user": cells[5],
                })
    return {"servers": rows, "count": len(rows), "source": sf}


# ── hub 접근 ────────────────────────────────────────────────────
def _hub_get(path):
    with urllib.request.urlopen(HUB_BASE + path, timeout=3) as r:
        return json.loads(r.read().decode())


def _hub_post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(HUB_BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read().decode())


def hub_status():
    try:
        return _hub_get("/healthz")
    except Exception as e:
        return {"error": f"hub 미응답: {e}", "hint": "/board-server start"}


def hub_open_project(cwd):
    try:
        return _hub_post("/open-project", {"cwd": os.path.expanduser(cwd)})
    except Exception as e:
        return {"error": f"hub 미응답: {e}"}


# ── MCP 도구 정의 ───────────────────────────────────────────────
TOOLS = [
    {
        "name": "fpm_list_projects",
        "description": "fpm 프로젝트 번호→경로 매핑 전체 목록을 반환.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": lambda a: list_projects(),
    },
    {
        "name": "fpm_resolve_project",
        "description": "프로젝트 번호를 절대 경로로 해석.",
        "inputSchema": {"type": "object",
                        "properties": {"id": {"type": "integer", "description": "프로젝트 번호"}},
                        "required": ["id"]},
        "_fn": lambda a: resolve_project(a["id"]),
    },
    {
        "name": "fpm_list_servers",
        "description": "Servers.md 의 SSH 서버 목록(id/name/alias/host/port/user)을 반환.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": lambda a: list_servers(),
    },
    {
        "name": "hub_status",
        "description": "hub 서버 상태(GET /healthz) — pid/port/uptime/등록 프로젝트 수.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": lambda a: hub_status(),
    },
    {
        "name": "hub_open_project",
        "description": "지정 cwd 를 VS Code 로 연다 (POST /open-project).",
        "inputSchema": {"type": "object",
                        "properties": {"cwd": {"type": "string", "description": "프로젝트 절대 경로"}},
                        "required": ["cwd"]},
        "_fn": lambda a: hub_open_project(a["cwd"]),
    },
]
_TOOL_MAP = {t["name"]: t for t in TOOLS}


# ── JSON-RPC 처리 ───────────────────────────────────────────────
def _public_tools():
    return [{k: v for k, v in t.items() if not k.startswith("_")} for t in TOOLS]


def handle(req):
    """요청 dict → 응답 dict (notification 이면 None)."""
    method = req.get("method")
    rid = req.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    elif method in ("notifications/initialized", "initialized"):
        return None  # notification — 응답 없음
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _public_tools()}
    elif method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        tool = _TOOL_MAP.get(name)
        if not tool:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            data = tool["_fn"](args)
            is_error = isinstance(data, dict) and "error" in data
            result = {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
                "isError": bool(is_error),
            }
        except Exception as e:
            result = {"content": [{"type": "text", "text": f"tool error: {e}"}], "isError": True}
    else:
        if rid is None:
            return None
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}

    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
