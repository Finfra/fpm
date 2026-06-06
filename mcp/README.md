---
name: README
description: fpm MCP 서버 — hub/pm 기능을 Model Context Protocol 로 노출 (스캐폴드)
date: 2026-06-06
---

# fpm MCP 서버 (스캐폴드)

fpm 의 hub·pm 기능을 [Model Context Protocol](https://modelcontextprotocol.io) 로 노출하여 Claude·기타 MCP 클라이언트가 활용할 수 있게 한다.

> 상태: **설계 단계 스캐폴드**. 실제 서버 구현은 `mcp-creator` 스킬로 생성 예정.

# 노출 대상 (결정 A = pm 전체)

| 도구(tool) | 설명 | 소스 |
| :--- | :--- | :--- |
| `fpm_list_projects` | 번호→경로 매핑 전체 조회 | `projects/` |
| `fpm_resolve_project` | 번호 → 절대 경로 해석 | `_pm_manager` |
| `fpm_list_servers` | `Servers.md` 서버 목록 | `Servers.md` |
| `hub_open_project` | cwd 를 VS Code 로 열기 | `POST /open-project` |
| `hub_open_session` | 세션 탭 포커스 | `POST /open-session` |
| `hub_status` | hub 서버 상태·등록 프로젝트 | `GET /healthz`, `/dashboards` |

# 생성 절차 (TODO)

1. `mcp-creator` 스킬로 stdio MCP 서버 스캐폴드 생성
2. 위 tool 들을 hub HTTP 엔드포인트(`http://127.0.0.1:9876`) 프록시로 구현
3. `projects/` 매핑은 로컬 파일 직접 읽기
4. `mcp/server.{py,ts}` + `package.json`(또는 `pyproject.toml`)
5. 테스트 → (선택) npm/PyPI 배포
6. Claude Code `.mcp.json` 등록 예시 문서화

# 미해결

* [TODO] 서버 런타임 선택 (Python stdlib vs Node MCP SDK)
* [TODO] hub 미기동 시 graceful degradation
* [FIXME] 인증 — hub 는 127.0.0.1 trust, MCP 노출 범위 확인
