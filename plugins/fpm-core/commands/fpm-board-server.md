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

> ⚠️ **제어 층은 launchd 하나다** (prj3#Issue537, 2026.09.05). 종전 `nohup python3 …` 은 **launchd 를 모르고** 띄워, 이미 `KeepAlive=true` 로 관리되는 프로세스와 port 9876 을 다투었다. 기동·정지 모두 `launchctl` 로만 한다.

```bash
PLIST="$HOME/Library/LaunchAgents/kr.finfra.htm-server.plist"
[ -f "$PLIST" ] || { echo "❌ plist 부재: $PLIST"; echo "   launchd 등재 없이는 기동하지 않는다 — plist 를 먼저 배치할 것"; exit 1; }
launchctl bootstrap gui/$UID "$PLIST" 2>/dev/null \
  || launchctl kickstart -k gui/$UID/kr.finfra.htm-server   # 이미 로드면 재시작
sleep 2
curl -s http://127.0.0.1:9876/healthz
```

* **env 해소 로직이 사라진 이유**: `AOA_MEMORY_DIR`(prj3#Issue497)은 plist 의 `EnvironmentVariables` 가 이미 소유한다. 셸에서 다시 계산하면 두 경로가 갈려 registry.db 가 둘이 된다
* `bootstrap` 은 **비멱등**이다 — 이미 로드된 상태면 `rc=5 Input/output error`(실측). 그래서 `||` 로 `kickstart -k` 에 넘긴다
* 성공 시 healthz JSON 이 출력된다. 실패 시 `/tmp/htm-server.log`·`/tmp/htm-server.err.log` 참조 (plist 의 `StandardOutPath`)

port override 는 plist 의 `EnvironmentVariables` 에 `HTM_SERVER_PORT` 를 넣는다 — 셸 env 로는 launchd 프로세스에 전달되지 않는다.

## stop

```bash
launchctl bootout gui/$UID/kr.finfra.htm-server 2>/dev/null
echo "board-server stopped (unloaded) — 다시 켜기: /board-server start"
```

* **`kill` 을 쓰지 않는 이유**: plist 가 `KeepAlive=true` 라 프로세스를 죽이면 `ThrottleInterval=10` 초 뒤 launchd 가 되살린다. 종전 pid 파일 `kill` 방식으로는 **hub 를 끌 수 없었다**
* `bootout` 은 **멱등**이다 — 이미 언로드된 상태에 재실행해도 `rc=0`(2026.09.05 실측). `bootstrap` 이 비멱등인 것과 **비대칭**이므로 대칭을 가정하지 말 것
* 언로드는 KeepAlive 자체를 걷어내므로 15초 후에도 부활하지 않는다. 단 **재부팅하면 `RunAtLoad=true` 로 다시 올라온다**

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
