---
name: fpm-hub-server
description: hub 단일 데몬(port 9876 server.py) lifecycle wrapper. start/stop/restart/status/clear/reset. a/b/c 3모드+Q&A 공통 서버. SSOT는 ~/_git/___pm/_doc_arch/hub_htm.md
date: 2026-06-24
---

> ⚠️ **글로벌 SCAR 변경 가드 (Issue46)**: 본 커맨드는 모든 프로젝트가 공유. cwd ≠ `~/.claude/` 면 즉시 수정 금지 → `~/.claude/Issue.md` 이슈 등록 후 처리. 서버 자체 변경은 ___pm SSOT (`~/_git/___pm/_doc_arch/hub_htm.md`) 와 동시 갱신 필수. 절차: `~/.claude/rules/global-scar-change-rules.md`

# 트리거

`/fpm-hub-server <subcmd>` — `<subcmd>`: `start`, `stop`, `restart`, `status`, `clear`, `reset`

* 로컬 짧은 별칭: ___pm 프로젝트에서 `/hub` (`~/_git/___pm/.claude/commands/hub.md`)
* 폐기 별칭: `/fpm-board-server` (deprecated → 본 커맨드 사용)

# 동작 모델

플러그인 번들 단일 daemon (`${CLAUDE_PLUGIN_ROOT}/services/hub/server.py`). port 9876. 모든 프로젝트가 공유. a모드 render·b모드 Q&A 회수(Issue45)·c모드 dashboard agent(Mode C) 가 공통 클라이언트로 사용. 본 wrapper 가 lifecycle 책임.

프로젝트 식별·격리는 클라이언트 hook 이 호출하는 `POST /register?cwd=...` 로 자동 처리.

설계 SSOT: `~/_git/___pm/_doc_arch/hub_htm.md`

# Endpoints (요약)

| Endpoint        | 메서드 | 인증           | 용도                                                   |
| :-------------- | :----- | :------------- | :----------------------------------------------------- |
| `/healthz`      | GET    | -              | alive check + projects/registered_pids 카운트          |
| `/register`     | POST   | cwd            | 프로젝트 등록 + token 발급                             |
| `/events`       | GET    | cwd+token      | Mode C SSE 스트림                                      |
| `/notify`       | POST   | cwd+token      | data 변경 broadcast                                    |
| `/data`         | GET    | cwd+token+path | data 파일 fetch (json/yaml/yml, cwd 하위)              |
| `/view`         | GET    | cwd+token+path | HTML serve (.html, cwd 하위) — CORS 해결               |
| `/register-pid` | POST   | cwd+token      | runner PID 등록 (stop 제어 대상)                       |
| `/control`      | POST   | cwd+token      | runner stop (`SIGTERM` → 2초 → `SIGKILL`)              |
| `/boards`       | GET    | -              | 전 cwd dash 메타 + `/view` deep link (localhost trust) |
| `/hub`          | GET    | -              | Multi-project Dashboard Hub HTML                       |
| `/hub-shell`    | GET    | -              | hub-internal 탭 쉘 (Issue194)                          |
| `/clear-done`   | POST   | 127.0.0.1      | done/stopped dash 파일 정리 (clear 서브커맨드)         |

서버 파일시스템 경로(`/tmp/___pm/claude-htm-server/`, Issue64)는 ___pm 측 호환성을 위해 유지.

# 서브커맨드

## start

이미 실행 중이면 PID 안내 후 종료. 새로 띄울 경우:

```bash
PID=$(cat /tmp/___pm/claude-htm-server/pid 2>/dev/null)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  echo "hub already running (pid=$PID)"
  curl -s http://127.0.0.1:9876/healthz
else
  mkdir -p /tmp/___pm/claude-htm-server
  nohup python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/_git/___pm}/services/hub/server.py" \
    >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
  sleep 1
  echo "hub started"
  curl -s http://127.0.0.1:9876/healthz
fi
```

port override: `HTM_SERVER_PORT=NNNN /fpm-hub-server start`

## stop

```bash
PID=$(cat /tmp/___pm/claude-htm-server/pid 2>/dev/null)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  sleep 1
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID"
  fi
  rm -f /tmp/___pm/claude-htm-server/pid
  echo "hub stopped (pid=$PID)"
else
  echo "hub not running"
fi
```

## restart

`stop` + 1초 sleep + `start`.

```bash
PID=$(cat /tmp/___pm/claude-htm-server/pid 2>/dev/null)
[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && kill "$PID" && sleep 1
[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
rm -f /tmp/___pm/claude-htm-server/pid
mkdir -p /tmp/___pm/claude-htm-server
nohup python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/_git/___pm}/services/hub/server.py" \
  >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:9876/healthz
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

## clear

등록된 모든 프로젝트의 `_doc_work/z_htm/*.dash.{json,yaml,yml}` + `/tmp/*.dash.*` 중 **`status: done` 또는 `status: stopped`** 인 항목과 동반 `.html` 파일을 삭제. 서버 PID/메모리 상태(tokens, sessions)는 보존.

* `done` 변형 매칭: `done`, `ALL-DONE`, `all_done`, `done(2/3)` 등 (단어 경계 — `undone` 비매칭)
* `stopped` 매칭: `stopped`, `stop`

서버 엔드포인트 `POST /clear-done` (127.0.0.1 trust, 토큰 불요). hub UI `🧹 Clear done/stopped` 버튼과 동일.

```bash
PID=$(cat /tmp/___pm/claude-htm-server/pid 2>/dev/null)
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  echo "hub not running — start with /fpm-hub-server start first"
  exit 1
fi
curl -sS -X POST http://127.0.0.1:9876/clear-done | python3 -m json.tool
```

응답: `{"status":"ok","deleted_count":N,"deleted":[...],"errors":[],"scanned_dirs":N}`. 세션/토큰까지 청소하려면 `reset` 사용.

## reset

**full wipe + restart**. 순서:

1. `POST /clear-done` — done/stopped dash (.dash.* + 동반 .html) 삭제 (서버 살아있을 때)
2. 서버 stop
3. `tokens.json`, `sessions.json`, `opened-*` 마커 삭제
4. 서버 start

clear + restart 의 상위 집합. tokens/sessions 메모리 상태까지 완전 초기화.

```bash
PID=$(cat /tmp/___pm/claude-htm-server/pid 2>/dev/null)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  curl -sS -X POST http://127.0.0.1:9876/clear-done | python3 -m json.tool
fi
[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && kill "$PID" && sleep 1
[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
rm -f /tmp/___pm/claude-htm-server/pid
rm -f /tmp/___pm/claude-htm-server/tokens.json
rm -f /tmp/___pm/claude-htm-server/sessions.json
rm -f /tmp/___pm/claude-htm-server/opened-*
mkdir -p /tmp/___pm/claude-htm-server
nohup python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/_git/___pm}/services/hub/server.py" \
  >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:9876/healthz
```

비고: SSE 구독 + dashboard runner SSE 연결 끊김. runner 는 `/register` 재호출로 신규 token 자동 발급. UI 탭 새로고침 필요.

# 비고

* 서버 down 시 a/b/c 3모드 + Q&A 회수(Issue45) 모두 fail-loud
* 본 커맨드는 구 `/fpm-board-server`(Issue37/45) + 로컬 `/hub` lifecycle 의 통합본 (Issue190). board 는 데몬의 한 클라이언트일 뿐 → hub 기준 명명

# 참조

* 설계 SSOT: `~/_git/___pm/_doc_arch/hub_htm.md`
* 서버 본체: `${CLAUDE_PLUGIN_ROOT}/services/hub/server.py`
* render 커맨드: `fpm-hub.md` (a모드)
* dashboard agent: `~/.claude/agents/fpm-board.md`
* 폐기 별칭: `fpm-board-server.md`
