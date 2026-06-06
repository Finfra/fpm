---
name: README
description: ___pm 소유 htm-server (단일 공유 daemon, 역할: dashboard agent 백엔드) 운영 가이드
date: 2026-05-19
---

# htm-server (___pm 서비스) — dashboard 백엔드

> ⚠️ **역할** (Issue25 → Issue45/Issue126): 본 서버는 **3모드 공유 백엔드** — a(`..htm`/`response`)·b(`..ask`/`form`)·c(`..board`/`dashboard`). Issue25 시점 "dashboard 전용 · Mode B deprecated" 표기는 **Issue45 에서 form 자동 회수 단일 경로 부활**로 정정됨 (b모드 = 현행 1차 클라이언트). 트리거 분리 상세: `~/.claude/Issue.md` Issue126, 매핑 표: `_doc_arch/hub_htm.md`.

설계 SSOT: 서버 공통 `~/_git/___pm/_doc_arch/hub_htm.md` · dashboard 서버 구현 `_doc_arch/hub_dashboard.md` · 에이전트군 ↔ 서버 통신 계약 `_doc_arch/hub_dashboard_protocol.md`
이슈: `~/_git/___pm/Issue.md` Issue15 (단일 서버 구조), Issue25 (역할 재정렬), Issue76 (통신 계약 문서 분리)
연관 글로벌 SSOT: `~/.claude/_doc_arch/dashboard.md`, `~/.claude/agents/dashboard.md`

# 핵심

* 단일 daemon, 모든 프로젝트 공유
* port 9876 고정 (override: `HTM_SERVER_PORT`)
* 프로젝트 식별: 클라이언트가 `POST /register?cwd=<abs>` 호출 → token 발급
* inbox: `/tmp/___pm/claude-htm-inbox/{cwd_hash}/{ts}.json`
* 상태: `/tmp/___pm/claude-htm-server/{tokens.json,pid,server.log}`
* 1차 endpoint (dashboard): `/session/register`, `/session/update` (`content_type=dashboard`), `/events` (SSE), `/notify`, `/dashboards`, `/hub`, `/control`, `/register-pid`
* hub registry endpoint (Issue41): `/register-doc` (생산자 등록), `/hub-rescan` (수동 디스크 수거). hub 목록은 디렉토리 스캔 없이 `data/hub/{htm,dash}-registry.json` 기반. `clear-*` 는 registry 항목만 제거, 실제 파일 보존
* dashboard 카드 SPA 세션 라우트 (Issue75): `/register-doc` 가 `type=dash` 등록 시 `sid` 를 수신·저장 → hub 카드 "열기" 가 `/s/{h}/{sid}?token=` 세션 라우트로 연결(미전송 시 파일 라우트 fallback). `type=dash` 의 `path` 가 serve-root(`cwd` 하위·`/tmp/___pm`) 밖이면 등록 `400` 거부 — 좀비 카드 차단
* 엔드포인트 요청·응답 계약(req/resp·식별자·등록 핸드셰이크·SSE 이벤트·content 스키마)의 SSOT 는 `_doc_arch/hub_dashboard_protocol.md` — server.py 는 그 계약의 구현
* tombstone (Issue53/54/55): 명시 제거(`clear-*`·카드 닫기)된 path 를 `data/hub/{htm,dash}-cleared.json` 에 기록 → htm·dash 모두 autoheal·디스크 재스캔 부활 차단. 해제는 생산자 `/register-doc` 명시 재등록 전용
* dashboard 카드 stale 강등 (Issue58): `/dashboards` 응답 생성 시 dash entry 의 `status=running` 이고 `pid` 가 죽은 프로세스면(`_pid_alive` False) `status` 를 `stale` 로 강등. runner 크래시·SIGKILL 로 파일에 `running` 이 잔존하는 좀비 카드 차단. `pid` 미상 시 검증 불가 → `running` 유지. 강등된 `stale` 은 `_is_clearable_status` 가 clear 대상으로 인정 → "정리" 버튼(`/clear-done`)이 좀비 카드를 쓸어냄 (Issue60)
* 활동 피드 endpoint (Issue42): `/hook-event` (hook 이벤트 적재 → `data/hub/hook-feed.json`), `/open-project` (피드 제목 클릭 → VSCode 열기). 설정 파일 `data/hub_setting.yml` (`feed_limit`·`feed_default_visible`·`feed_poll_interval`·`card_limit`·`search_limit`, mtime 캐시 재로드). `search_limit`(Issue55): `/hub-rescan` 시 디렉토리당 처리 파일 수 상한(파일명 unixtime 최신순, 0=무제한). 설계 SSOT: `_doc_arch/hub_htm_history.md`
* b모드 endpoint (Issue45 부활): `/answer` (form inbox 자동 회수, 현행 1차 경로). stable URL 경로 `/session/update` (`content_type=form`)·`/s/{cwd_hash}/{sid}/answer` 는 후방호환 보존

# 명령

| 동작     | 명령                                                        |
| :------- | :---------------------------------------------------------- |
| 기동     | `python3 ~/_git/___pm/services/htm-server/server.py &`     |
| 헬스 체크| `curl http://127.0.0.1:9876/healthz`                        |
| 로그     | `tail -f /tmp/___pm/claude-htm-server/server.log`                 |
| 중지     | `kill $(cat /tmp/___pm/claude-htm-server/pid)`                    |
| 등록 테스트 | `curl -X POST "http://127.0.0.1:9876/register?cwd=$(pwd)"` |

글로벌 wrapper: `/htm-server start|stop|status|restart` (`~/.claude/commands/htm-server.md`).

# 다중 프로젝트

같은 daemon이 여러 프로젝트 동시 처리. 각 프로젝트는 첫 `..htm` 호출 시 자동 `/register` → 별도 token + inbox 격리.

# 마이그레이션 (per-project → 단일)

종전 자원 1회 정리:
```bash
rm -f ~/.claude/.htm-server-active
rm -rf /tmp/___pm/claude-htm-server-* /tmp/___pm/claude-htm-inbox-*
```
종전 server.py 프로세스 정리:
```bash
pkill -f "skills/htm-server/server.py" || true
```

# 보안

* `127.0.0.1` 바인딩 (외부 차단)
* token: `uuid4().hex`, `hmac.compare_digest` 비교
* `/data` path traversal 차단 (realpath + cwd prefix 검증)
* 확장자 화이트리스트: `.json`, `.yaml`, `.yml`
* body size 상한: `/answer` 1MiB, `/notify` 64KiB
