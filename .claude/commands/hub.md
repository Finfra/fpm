---
name: hub
description: ___pm hub (http://127.0.0.1:9876/hub) lifecycle wrapper. start/stop/restart/clear/reset 서브커맨드 제공. SSOT는 _doc_arch/hub_htm.md
date: 2026-05-19
---

# 트리거

`/hub <subcmd>` — `<subcmd>`: `start`, `stop`, `restart`, `clear`, `reset`

# 동작 모델

___pm 소유 단일 daemon (`~/_git/___pm/services/hub/server.py`). port 9876. 모든 프로젝트가 공유. ___pm 프로젝트가 lifecycle 책임.

본 커맨드는 글로벌 `/board-server` 와 동일 서버를 대상으로 함. ___pm 프로젝트 컨텍스트에서 짧은 별칭으로 제공.

설계 SSOT: `_doc_arch/hub_htm.md`

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
  nohup python3 ~/_git/___pm/services/hub/server.py \
    >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
  sleep 1
  echo "hub started"
  curl -s http://127.0.0.1:9876/healthz
fi
```

port override: `HTM_SERVER_PORT=NNNN /hub start`

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
nohup python3 ~/_git/___pm/services/hub/server.py \
  >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:9876/healthz
```

## clear

**재정의**: 등록된 모든 프로젝트의 `_doc_work/z_htm/*.dash.{json,yaml,yml}` + `/tmp/*.dash.*` 중 **`status: done` 또는 `status: stopped`** 인 항목과 동반 `.html` 파일을 삭제. 서버 PID/메모리 상태(tokens, sessions)는 보존.

* `done` 변형 매칭: `done`, `ALL-DONE`, `all_done`, `done(2/3)` 등 (단어 경계 검사 — `undone` 등은 비매칭)
* `stopped` 매칭: `stopped`, `stop`

서버 엔드포인트: `POST /clear-done` (127.0.0.1 trust, 토큰 불요). hub UI 우측 상단 `🧹 Clear done/stopped` 버튼과 동일 동작.

```bash
PID=$(cat /tmp/___pm/claude-htm-server/pid 2>/dev/null)
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  echo "hub not running — start with /hub start first"
  exit 1
fi
curl -sS -X POST http://127.0.0.1:9876/clear-done | python3 -m json.tool
```

응답 예:

```json
{"status":"ok","deleted_count":4,"deleted":["/tmp/foo.dash.json","/tmp/foo.html",...],"errors":[],"scanned_dirs":7}
```

* `deleted`: 삭제된 파일 절대경로 목록 (dash 파일 + 동반 .html 모두 포함)
* `errors`: `[{path, error}]` — 권한 등으로 삭제 실패한 항목

세션/토큰 파일 청소가 필요하면 본 커맨드 대신 `/hub restart` 사용 (메모리 상태도 초기화됨).

## reset

**full wipe + restart**. 순서:
1. `POST /clear-done` — done dashboard 파일 (.dash.* + 동반 .html) 삭제 (서버 실행 중에 수행)
2. 서버 stop
3. `/tmp/___pm/claude-htm-server/tokens.json`, `sessions.json`, `opened-*` 마커 삭제
4. 서버 start

clear + restart 의 상위 집합. tokens/sessions 메모리 상태까지 완전 초기화.

```bash
# 1. done dash 정리 (서버 살아있을 때만 의미 있음)
PID=$(cat /tmp/___pm/claude-htm-server/pid 2>/dev/null)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  curl -sS -X POST http://127.0.0.1:9876/clear-done | python3 -m json.tool
fi

# 2. stop
[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && kill "$PID" && sleep 1
[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
rm -f /tmp/___pm/claude-htm-server/pid

# 3. state wipe
rm -f /tmp/___pm/claude-htm-server/tokens.json
rm -f /tmp/___pm/claude-htm-server/sessions.json
rm -f /tmp/___pm/claude-htm-server/opened-*

# 4. start
mkdir -p /tmp/___pm/claude-htm-server
nohup python3 ~/_git/___pm/services/htm-server/server.py \
  >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:9876/healthz
```

비고: SSE 구독 + dashboard runner 의 SSE 연결은 끊김. runner 는 `/register` 재호출로 신규 token 자동 발급받음. UI 탭 새로고침 필요.

# 비고

* 글로벌 `/board-server` 와 동일 서버 lifecycle 제어. 차이: 본 커맨드는 `clear` 추가 + ___pm 컨텍스트 짧은 별칭
* 서버 down 시 dashboard agent (Mode C) + htm 스킬 Q&A 회수 (Issue45) 양쪽 모두 fail-loud

# 참조

* 설계 SSOT: `_doc_arch/hub_htm.md`
* 글로벌 wrapper: `~/.claude/commands/board-server.md`
* 서버 본체: `services/hub/server.py`
