# fpm-core 플러그인

프로젝트 관리(pm/cdf)와 hub HTML 렌더 + 양방향 Q&A + Live Dashboard 스택을 한 번에 설치하는 Claude Code 플러그인. 글로벌 `~/.claude` 에 흩어져 있던 hub/dashboard 구동 SCAR(hooks·commands·agent·server)를 번들하여 `/plugin install` 만으로 동작하게 한다.

## 구성 요소

| 분류 | 항목 |
| :--- | :--- |
| Commands | `fpm-hub`, `fpm-dashboard`, `fpm-dashboard-server`, `fpm-pm-new`, `fpm-pm-del`, `fpm-pm-update`, `fpm-pm-query`, `fpm-pm-do`, `fpm-cdf` |
| Skills | `fpm-pm`, `fpm-cdf` |
| Agents | `fpm-dashboard` (+ runner/supervisor/queue-runner) |
| Hooks | `fpm-hub-trigger`, `fpm-ask-intercept`, `fpm-ask-marker-detect`, `fpm-ask-question-guard`, `fpm-board-notify`, `fpm-hub-session-{register,end,topic}`, `fpm-hub-doc-register` |
| Services | `services/hub/server.py` (hub/dashboard 백엔드, Python stdlib HTTP+SSE) |

## 3-mode 트리거

* **a모드 `..show`** — 응답을 완전한 HTML 문서로 렌더하여 브라우저 표시 (단방향)
* **b모드 `..ask`** — 양방향 Q&A 폼 → 서버 inbox 자동 회수
* **c모드 `..board`** — Live Dashboard (tmux runner + SSE 실시간 push)

hook(`fpm-hub-trigger`)이 트리거를 감지하여 매 응답을 자동 HTML 렌더 모드로 전환한다. 프로젝트 폴더에서 기본 on, 비프로젝트는 off.

## hub 서버 lifecycle

b/c모드는 백엔드 서버를 사용한다. `/fpm-dashboard-server start|stop|status|restart` 로 관리:

```bash
/fpm-dashboard-server start    # ${CLAUDE_PLUGIN_ROOT}/services/hub/server.py 기동
/fpm-dashboard-server status   # healthz + PID
```

서버 경로는 `${CLAUDE_PLUGIN_ROOT}` 로 해석되어 설치 위치에 자동 적응한다.

## 환경 변수

| 변수 | 기본 | 용도 |
| :--- | :--- | :--- |
| `HTM_SERVER_PORT` | `9876` | hub 서버 포트 |
| `HTM_SERVER_HOST` | `127.0.0.1` | bind 인터페이스. `0.0.0.0` 으로 원격 접근 개방(Issue141) — `Servers.md` check=O 호스트 IP allowlist 게이트. yml `bind_host` 보다 우선 |
| `FPM_SERVERS_MD` | `<repo>/Servers.md` | 개방 모드 allowlist 소스 경로 override |
| `FPM_PROJECTS_MD` | `~/_git/___pm/Projects.md` | 프로젝트 번호→경로·색상 매핑 SSOT (멀티 프로젝트 hub 색상용, 없으면 무색) |

## 주의 — 이중 등록

이 플러그인을 enable 하면 `hooks/hooks.json` 의 hook 9종이 사용자 hook 설정에 자동 병합된다. 동일 hook 을 이미 글로벌 `~/.claude/settings.json` 에 등록한 사용자(원작자 환경)는 hook 이 2번 실행되므로, 둘 중 하나만 활성할 것.

## 라이선스

PolyForm Noncommercial 1.0.0 — 개인·비영리 무료, 기업 상용은 별도 라이선스(`COMMERCIAL.md`).
