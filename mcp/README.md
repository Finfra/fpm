---
name: README
description: fpm MCP 서버 — hub/pm 기능을 Model Context Protocol 로 노출 (stdlib stdio)
date: 2026-06-06
---

# fpm MCP 서버

fpm 의 pm·hub 기능을 [Model Context Protocol](https://modelcontextprotocol.io) 도구로 노출한다. Claude·기타 MCP 클라이언트가 프로젝트 매핑 조회·서버 목록·hub 제어를 호출할 수 있다.

* 구현: `server.py` — **Python stdlib only**(무의존성, `services/hub/server.py` 와 동일 ethos). MCP stdio 전송(newline-delimited JSON-RPC 2.0).
* 프로토콜 버전: `2024-11-05`

# 제공 도구

| 도구 | 인자 | 설명 | 소스 |
| :--- | :--- | :--- | :--- |
| `fpm_list_projects` | — | 번호→경로 매핑 전체 | `projects/` |
| `fpm_resolve_project` | `id` | 번호 → 절대 경로 | `~/.info/__pmBasePath.txt` |
| `fpm_list_servers` | — | `Servers.md` 서버 목록 | `<repo>/Servers.md` |
| `hub_status` | — | hub 상태(pid/port/uptime/등록 수) | `GET /healthz` |
| `hub_open_project` | `cwd` | 프로젝트를 VS Code 로 열기 | `POST /open-project` |

# 등록 (Claude Code)

`.mcp.json`(프로젝트 루트) 또는 글로벌 설정:

```json
{
  "mcpServers": {
    "fpm": {
      "command": "python3",
      "args": ["/Users/<you>/_git/fpm/mcp/server.py"]
    }
  }
}
```

환경변수 `FPM_HUB_BASE`(기본 `http://127.0.0.1:9876`)로 hub 주소 override 가능.

# 수동 검증 (stdio)

```bash
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fpm_list_projects","arguments":{}}}' \
  | python3 mcp/server.py
```

# 의존·전제

* `fpm_*` 도구: `~/.info/__pmBasePath.txt` 존재(= `install.sh` 실행 완료)
* `hub_*` 도구: hub 서버 기동(`services/hub/server.py` 또는 `/dashboard-server start`). 미기동 시 `error` + hint 반환(graceful).

# 향후

* [TODO] hub Q&A 폼 트리거·dashboard 제어 도구 추가
* [TODO] npm/PyPI 패키징(현재는 단일 파일 직접 실행)
* [FIXME] `fpm_list_servers` 는 로컬 `Servers.md`(개인정보) 를 읽음 — MCP 클라이언트 신뢰 경계 확인 후 노출 범위 조정
