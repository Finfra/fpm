---
name: fpm-board-server
description: dashboard agent(Mode C) 전용 ___pm 서버 lifecycle wrapper (start/stop/status/restart). SSOT는 ~/_git/___pm/_doc_arch/hub_htm.md
date: 2026-05-19
---

> ⚠️ **글로벌 SCAR 변경 가드 (Issue46)**: 본 커맨드는 모든 프로젝트가 공유. cwd ≠ `~/.claude/` 면 즉시 수정 금지 → `~/.claude/Issue.md` 이슈 등록 후 처리. 서버 자체 변경은 ___pm SSOT (`~/_git/___pm/_doc_arch/hub_htm.md`) 와 동시 갱신 필수. 절차: `~/.claude/rules/global-scar-change-rules.md`

# 트리거

`/board-server <subcmd>` — `<subcmd>`: `start`, `stop`, `status`, `restart`

# 동작 모델

플러그인 번들 단일 daemon (`${CLAUDE_PLUGIN_ROOT}/services/hub/server.py`). dashboard agent (Mode C Live Dashboard) 와 hub 스킬 Q&A 회수 (Issue45) 가 공통 클라이언트로 사용한다. 본 wrapper 가 lifecycle 책임.

모든 프로젝트가 동일 port 9876 인스턴스를 공유. 프로젝트 식별·격리는 클라이언트 hook 이 호출하는 `POST /register?cwd=...` 로 자동 처리.

설계 SSOT: `~/_git/___pm/_doc_arch/hub_htm.md` (___pm#Issue25 에서 dashboard 전용 역할로 갱신 예정)

# Endpoints (요약 — dashboard agent 가 실제 사용하는 것 위주)

| Endpoint                  | 메서드 | 인증           | 용도                                                  |
| :------------------------ | :----- | :------------- | :---------------------------------------------------- |
| `/healthz`                | GET    | -              | alive check + projects/registered_pids 카운트         |
| `/register`               | POST   | cwd            | 프로젝트 등록 + token 발급                            |
| `/events`                 | GET    | cwd+token      | Mode C SSE 스트림                                     |
| `/notify`                 | POST   | cwd+token      | data 변경 broadcast                                   |
| `/data`                   | GET    | cwd+token+path | data 파일 fetch (json/yaml/yml, cwd 하위)             |
| `/view`                   | GET    | cwd+token+path | HTML serve (.html, cwd 하위) — CORS 해결              |
| `/register-pid`           | POST   | cwd+token      | runner PID 등록 (stop 제어 대상)                      |
| `/control`                | POST   | cwd+token      | runner stop (`SIGTERM` → 2초 → `SIGKILL`)             |
| `/boards`             | GET    | -              | 전 cwd dash 메타 + `/view` deep link (localhost trust) |
| `/hub`                    | GET    | -              | Multi-project Dashboard Hub HTML (5초 polling)         |

종전 `/answer`, `/session/update?content_type=form` 등 Mode B 클라이언트 endpoint 는 ___pm 측에서 deprecated. 본 wrapper 는 dashboard 영역만 다룬다.

# 서브커맨드

## start

이미 실행 중이면 PID 안내 후 종료. 새로 띄울 경우:

```bash
mkdir -p /tmp/___pm/claude-htm-server
nohup python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/_git/___pm}/services/hub/server.py" \
  >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:9876/healthz
```

성공 시: healthz JSON 출력 + PID 안내. 실패 시: `/tmp/___pm/claude-htm-server/server.log` 참조.

port override: `HTM_SERVER_PORT=NNNN /board-server start`

## stop

```bash
PID=$(cat /tmp/___pm/claude-htm-server/pid 2>/dev/null)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "board-server stopped (pid=$PID)"
else
  echo "board-server not running"
fi
```

## status

```bash
echo "--- pid:"
cat /tmp/___pm/claude-htm-server/pid 2>/dev/null || echo "(no pid file)"
echo "--- healthz:"
curl -s http://127.0.0.1:9876/healthz 2>&1
echo
echo "--- registered projects:"
cat /tmp/___pm/claude-htm-server/tokens.json 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "(none)"
echo "--- recent log:"
tail -20 /tmp/___pm/claude-htm-server/server.log 2>/dev/null
```

## restart

`stop` + 1초 sleep + `start`.

# 비고

* 서버 파일 시스템 경로 (`/tmp/___pm/claude-htm-server/`, Issue64 — `/tmp` 평면 흩어짐 방지. `server.py` 의 `htm-server` 이름) 는 ___pm 측 호환성을 위해 유지. 슬래시 커맨드 명칭만 `/board-server` 로 변경 (Issue37 → Issue45 에서 hub 도 동일 서버 사용으로 통합)
* hub 스킬 Q&A 회수 (Issue45) — `..show` 트리거(구 `..hub`) + AskUserQuestion 호출 시 `fpm-ask-intercept.sh` 가 본 서버 healthz·register·answer 사용. 서버 down 시 fail-loud

# 참조

* 설계 SSOT: `~/_git/___pm/_doc_arch/hub_htm.md`
* ___pm 측 역할 갱신 이슈: `~/_git/___pm/Issue.md` Issue25
* 클라이언트 hook:
    - `~/.claude/hooks/fpm-board-notify.sh` (Mode C dashboard data 변경 notify)
    - `~/.claude/hooks/fpm-ask-intercept.sh` (Issue45 hub Q&A form 자동 회수)
* dashboard agent: `~/.claude/agents/fpm-board.md`
* dashboard wrapper: `~/.claude/commands/fpm-board.md`
* hub 스킬 분리 이슈: `~/.claude/Issue.md` Issue37
