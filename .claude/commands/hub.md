---
name: hub
description: ___pm hub (http://127.0.0.1:9876/hub) lifecycle wrapper. start/stop/restart/status/disable/enable/clear/reset 서브커맨드 제공. SSOT는 _doc_arch/hub_htm.md
date: 2026-05-19
---

# 트리거

`/hub <subcmd>` — `<subcmd>`: `start`, `stop`, `restart`, `status`, `disable`, `enable`, `clear`, `reset`

# 동작 모델

___pm 소유 단일 daemon (`~/_git/___pm/services/hub/server.py`). port 9876. 모든 프로젝트가 공유. ___pm 프로젝트가 lifecycle 책임.

본 커맨드는 글로벌 `/fpm-hub-server` 와 동일 서버를 대상으로 함 (Issue190 통합). ___pm 프로젝트 컨텍스트에서 짧은 별칭으로 제공.

설계 SSOT: `_doc_arch/hub_htm.md`

## ⚠️ launchd 관리 모델 (2026-06-28 — 핵심)

서버는 **nohup 이 아니라 launchd LaunchAgent 가 관리**한다.

* plist: `~/Library/LaunchAgents/kr.finfra.htm-server.plist` (Label `kr.finfra.htm-server`)
* `KeepAlive=true` + `RunAtLoad=true` → **프로세스를 `kill` 하면 launchd 가 즉시 respawn**. 단순 PID kill·`lsof` kill 로는 서버가 절대 멈추지 않는다 (10초 ThrottleInterval 후 부활).
* 따라서 lifecycle 은 **`launchctl` 로 job 자체를 제어**해야 한다:
    - **정지(이번 부팅 한정)**: `launchctl bootout gui/$(id -u)/kr.finfra.htm-server` → job unload (respawn 차단). 단 SIGTERM 무시한 listener 가 남을 수 있어 **포트 listener 강제 kill 을 병행**한다.
    - **정지(영구·재부팅 후에도)**: `bootout` + `launchctl disable gui/$(id -u)/kr.finfra.htm-server` (`/hub disable`).
    - **기동**: `launchctl enable …` + `launchctl bootstrap gui/$(id -u) <plist>`.
* `/tmp/___pm/claude-htm-server/pid` pidfile 은 launchd 관리 인스턴스에선 신뢰할 수 없다 (보조 지표). 항상 **포트 9876 의 실제 listener + launchd job 상태**를 1차 기준으로 삼는다.
* plist 부재(다른 머신·수동 기동) 시에는 nohup fallback 으로 동작한다.

# 서브커맨드

## start

이미 listen 중이면 안내 후 종료. 아니면 launchd job 이 있으면 bootstrap, 없으면 nohup fallback.

```bash
PORT=${HTM_SERVER_PORT:-9876}
UID_=$(id -u); JOB="gui/$UID_/kr.finfra.htm-server"
PLIST="$HOME/Library/LaunchAgents/kr.finfra.htm-server.plist"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "hub already running (port $PORT)"
  curl -s http://127.0.0.1:"$PORT"/healthz
elif [ -f "$PLIST" ]; then
  launchctl enable "$JOB" 2>/dev/null       # disable 되어 있었으면 해제
  launchctl bootstrap "gui/$UID_" "$PLIST" 2>/dev/null
  sleep 2
  echo "hub bootstrapped (launchd)"
  curl -s http://127.0.0.1:"$PORT"/healthz
else
  mkdir -p /tmp/___pm/claude-htm-server
  nohup python3 ~/_git/___pm/services/hub/server.py \
    >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
  sleep 1
  echo "hub started (nohup fallback)"
  curl -s http://127.0.0.1:"$PORT"/healthz
fi
```

port override(`HTM_SERVER_PORT=NNNN /hub start`)는 **nohup fallback 에만** 적용된다. launchd plist 는 포트가 하드코딩(9876)이므로 override 가 무시된다 — 다른 포트가 필요하면 plist 를 수정하거나 nohup 경로를 쓴다.

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

## stop

서버를 **이번 부팅 한정** 정지한다(재부팅 시 RunAtLoad 로 자동 부활 — 영구 정지는 `/hub disable`). launchd job 이면 `bootout` 으로 KeepAlive respawn 을 차단하고, SIGTERM 을 무시한 잔존 listener·수동 인스턴스는 포트로 강제 kill 한다.

> ⚠️ launchd KeepAlive 때문에 **단순 `kill` 은 즉시 respawn → no-op**. 반드시 `launchctl bootout` 으로 job 을 내린 뒤 포트 listener 를 정리해야 실제로 멈춘다 (2026-06-28 검증).

```bash
PORT=${HTM_SERVER_PORT:-9876}
UID_=$(id -u); JOB="gui/$UID_/kr.finfra.htm-server"
PIDFILE=/tmp/___pm/claude-htm-server/pid

# 1. launchd 관리 job 이면 bootout (KeepAlive respawn 차단)
if launchctl print "$JOB" >/dev/null 2>&1; then
  echo "launchd job 감지 — bootout 으로 unload"
  launchctl bootout "$JOB" 2>/dev/null
  sleep 1
fi
# 2. bootout 후 SIGTERM 무시한 listener + nohup 수동 인스턴스 강제 종료
PIDS=$(
  { cat "$PIDFILE" 2>/dev/null
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}'
  } | grep -E '^[0-9]+$' | sort -u
)
for P in $PIDS; do kill -9 "$P" 2>/dev/null; done
rm -f "$PIDFILE"
sleep 1
# 3. 정지 검증
DOWN=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | sort -u)
if [ -z "$DOWN" ]; then
  echo "hub stopped ✅ (재부팅 시 자동 부활 — 영구 정지는 /hub disable)"
else
  echo "⚠️ 여전히 listener 존재: $DOWN — /hub disable 또는 수동 확인 필요"
fi
```

## restart

launchd job 을 `bootout` 으로 내리고 포트를 완전히 비운 뒤 다시 `bootstrap`(plist 있을 때) 또는 nohup 으로 띄운다.

> ⚠️ launchd 관리 인스턴스에서 **nohup 단독 restart 는 금물**. KeepAlive 가 구 프로세스를 respawn 하여 9876 을 계속 점유 → 새 인스턴스가 bind 실패로 즉사 → 코드 변경 미반영. 반드시 `bootout` 으로 job 을 먼저 내려야 한다. pidfile 은 launchd 관리 시 신뢰 불가 → **포트 9876 실제 listener + launchctl job 상태**를 1차 기준으로 삼는다 (2026-06-28).

```bash
PORT=${HTM_SERVER_PORT:-9876}
UID_=$(id -u); JOB="gui/$UID_/kr.finfra.htm-server"
PLIST="$HOME/Library/LaunchAgents/kr.finfra.htm-server.plist"
PIDFILE=/tmp/___pm/claude-htm-server/pid
mkdir -p /tmp/___pm/claude-htm-server

# 1. launchd job unload (KeepAlive respawn 차단)
launchctl bootout "$JOB" 2>/dev/null
sleep 1
# 2. 잔존 listener 강제 종료
PIDS=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | sort -u)
for P in $PIDS; do kill -9 "$P" 2>/dev/null; done
rm -f "$PIDFILE"
# 3. 포트가 완전히 비워질 때까지 최대 3초 대기 (bind 실패 즉사 방지)
for i in 1 2 3; do
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1' | grep -q . || break
  sleep 1
done
# 4. 재기동: plist 있으면 launchd bootstrap, 없으면 nohup
if [ -f "$PLIST" ]; then
  launchctl enable "$JOB" 2>/dev/null
  launchctl bootstrap "gui/$UID_" "$PLIST" 2>/dev/null
else
  nohup python3 ~/_git/___pm/services/hub/server.py \
    >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
fi
sleep 2
echo "--- healthz (uptime 이 한 자릿수면 재시작 성공) ---"
curl -s http://127.0.0.1:"$PORT"/healthz
```

## disable

서버를 **영구 정지**한다 — 재부팅 후에도 자동 기동되지 않는다. `bootout`(현재 인스턴스 unload) + `launchctl disable`(향후 load 차단) + 잔존 listener 강제 kill. ⚠️ **시스템 전역** — 모든 프로젝트·세션의 hub 렌더·Q&A 폼 회수·dashboard(Mode C)가 정지한다.

```bash
PORT=${HTM_SERVER_PORT:-9876}
UID_=$(id -u); JOB="gui/$UID_/kr.finfra.htm-server"
launchctl bootout "$JOB" 2>/dev/null    # 현재 인스턴스 unload
launchctl disable "$JOB" 2>/dev/null    # 재부팅·향후 load 영구 차단
PIDS=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | sort -u)
for P in $PIDS; do kill -9 "$P" 2>/dev/null; done
rm -f /tmp/___pm/claude-htm-server/pid
sleep 1
DOWN=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | sort -u)
if [ -z "$DOWN" ]; then
  echo "hub permanently disabled ✅ (재부팅 후에도 정지). 복원: /hub enable"
else
  echo "⚠️ 여전히 listener 존재: $DOWN"
fi
```

## enable

`disable` 로 영구 차단된 서버를 다시 켠다. `launchctl enable` 으로 차단 해제 후 `bootstrap` 으로 기동.

```bash
PORT=${HTM_SERVER_PORT:-9876}
UID_=$(id -u); JOB="gui/$UID_/kr.finfra.htm-server"
PLIST="$HOME/Library/LaunchAgents/kr.finfra.htm-server.plist"
launchctl enable "$JOB" 2>/dev/null
launchctl bootstrap "gui/$UID_" "$PLIST" 2>/dev/null
sleep 2
echo "--- healthz ---"
curl -s http://127.0.0.1:"$PORT"/healthz
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
nohup python3 ~/_git/___pm/services/hub/server.py \
  >/tmp/___pm/claude-htm-server/stdout.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:9876/healthz
```

비고: SSE 구독 + dashboard runner 의 SSE 연결은 끊김. runner 는 `/register` 재호출로 신규 token 자동 발급받음. UI 탭 새로고침 필요.

# 비고

* 글로벌 `/fpm-hub-server` 와 동일 서버 lifecycle 제어 (Issue190 통합). 본 커맨드는 ___pm 컨텍스트 짧은 별칭. **launchd-aware 동작은 글로벌 wrapper 에도 동기화 필요** (별도 이슈)
* 서버 down 시 dashboard agent (Mode C) + htm 스킬 Q&A 회수 (Issue45) 양쪽 모두 fail-loud
* `..hub stop`/`..hub off`(트리거 hook) 는 **이 커맨드와 무관** — 그건 폴더/시스템 단위 자동 렌더 토글(상태 파일)일 뿐 서버를 멈추지 않는다. 서버 프로세스 정지는 본 커맨드(`/hub stop`·`/hub disable`)만 수행한다.

## 서브커맨드 요약

| 서브커맨드 | 동작 | 재부팅 후 |
| :--------- | :--- | :-------- |
| `stop`     | bootout + listener kill (이번 부팅 한정 정지) | 자동 부활 |
| `disable`  | bootout + `launchctl disable` (영구 정지) | 정지 유지 |
| `enable`   | `launchctl enable` + bootstrap (disable 복원) | — |
| `start`    | bootstrap(plist) 또는 nohup fallback | — |
| `restart`  | bootout → 포트 비움 → bootstrap/nohup | — |

# 참조

* 설계 SSOT: `_doc_arch/hub_htm.md`
* 글로벌 canonical wrapper: `~/.claude/commands/fpm-hub-server.md` (구 `fpm-board-server`, Issue190 폐기)
* 서버 본체: `services/hub/server.py`
