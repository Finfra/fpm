---
name: aoa-mq
description: 메시지 큐 AOA — "N일 후 작업" 예약 리마인드·장기작업 완료 통지를 사용자 ACK 전까지 반복 질의. 트리거 — "mq 등록", "N일 후에 …해줘 (mq)", "이 작업 끝나면 알려줘 (mq watch)". tick 은 hub 타이머가 자동 기동(jmDashboard 는 보조).
---

> 설계 SSOT: [`_doc_arch/aoa-mq.md`](../../_doc_arch/aoa-mq.md) · 관리 규칙: [`_doc_arch/aoa__management-rules.md`](~/_git/___common/_doc_arch/aoa__management-rules.md)
> 안전가드: `data/aoa/mq/policy.yml` — 파괴적 행위 없음, 자기 데이터 디렉토리와 inbox 자기 시그니처 파일만 조작.

# 역할

시간 축 메시지 큐. 세 가지 메시지를 `data/aoa/mq/queue/`에 보관하고, tick 마다 처리한다:

* `scheduled` — 예약 리마인드. due 도달 시 "오늘 진행?"을 사용자 ACK(confirm/snooze/dismiss) 전까지 반복 질의
* `watch` — 장기작업 완료 감시. 신호 2종: `board_status`(fpm-board sentinel) | `pane_regex`(tmux pane idle/부재 — prj5#Issue14). 완료 감지 시 ACK 전까지 반복 통지
* `alert` — 상위 AOA(observer 등)가 위임한 이미 발생한 이벤트 (prj5#Issue13). 등록 즉시 `done_unacked` — ACK 전까지 반복 통지

본 AOA는 통지·확인 전담 — 작업 실행 주체가 아니다. tick(`aoa-mq-tick.sh`)의 기본 계약은 **호출되면 무조건 실행**이며, 빈도 억제는 **`--gate <sec>` 를 건 호출자**(hub 타이머)가 옵트인으로 가진다(F3-4). ⚠️ 종전의 *"jmDashboard 단독 책임"* 은 더 이상 사실이 아니다 — 게이트 파일이 경로와 무관하게 공유되므로 jmDashboard 가 없어도 ~1회/시간이 유지된다.

# enqueue 절차 (메시지 등록)

**표준 경로 (prj5#Issue10)**: helper 스크립트 사용 — 수동 JSON 조립 금지 (비원자 쓰기·스키마 누락 방지)

```bash
~/.claude/mcp/aoa-mq/aoa-mq-enqueue.sh --message "<msg>" --due +7d              # scheduled
~/.claude/mcp/aoa-mq/aoa-mq-enqueue.sh --message "<msg>" --watch "<topic>"      # watch (board_status)
~/.claude/mcp/aoa-mq/aoa-mq-enqueue.sh --message "<msg>" --watch-pane "sess:0"  # watch (pane_regex)
~/.claude/mcp/aoa-mq/aoa-mq-enqueue.sh --message "<msg>" --alert                # alert (즉시 통지 대기열)
```

* `--due`: `+Nd`(N일 후 09:00) | `YYYY-MM-DD`(09:00 부여) | `YYYY-MM-DDTHH:MM[:SS]`
* `--watch-pane`: tmux target(`session[:window[.pane]]`) — pane 부재 또는 idle(입력창 프롬프트 복귀) 시 완료 판정
* `--alert`: 등록 주체가 즉시성 필요 시 enqueue 직후 `aoa-mq-tick.sh` 를 1회 직접 kick (1h 게이트 비대기)
* `--source` 생략 시 `claude@<cwd basename>` 자동. 성공 시 `enqueued: <경로>` echo, 실패 시 exit≠0 fail-loud
* 글로벌 진입점: 모든 프로젝트에서 `/mq-send` (prj3 `commands/mq-send.md`, prj3#Issue192) — 본 helper 의 얇은 wrapper
* **재스케줄 (prj5#Issue63)**: `--reschedule <id> --due <+Nd|YYYY-MM-DD|ISO8601>` — 기존 항목의 `due_ts` 만 바꾸는 1급 경로. 등록 인자(`--message`·`--watch`·`--alert`·`--kind`·`--on-response`)와 **배타**이며 `queue/` 항목만 대상. 큐 JSON 을 손으로 고치고 digest 를 따로 돌리는 2단계는 **폐지**됐다
    - `+Nd` 는 **기존 시각을 보존**하고 날짜만 옮긴다(기준일 = `max(오늘, 기존 due 날짜)`). tick 의 `snooze` 도 이 경로에 위임하므로 원래 시각(19:00 등)이 더는 소실되지 않는다
    - tick 과 **같은 `.tick.lock`** 을 잡아 상호배제한다(mv 는 파일 1개만 원자적이라 digest 재생성 구간을 못 막는다). 10초 대기 후 거절. `AOA_MQ_LOCK_HELD=1` 은 tick 위임 전용 재진입 escape
    - 설계 근거: [`_doc_arch/aoa-mq.md`](../../_doc_arch/aoa-mq.md) "재스케줄 — `due_ts` 변경의 1급 경로"

아래는 helper 가 내부 수행하는 규약 (직접 구현 시에만 참조):

1. id 채번: `date '+%Y%m%d-%H%M%S'`-`<seq3>` (ex: `20260703-170000-001`)
2. 아래 스키마로 JSON 작성 → **temp 파일에 쓴 뒤 `mv`로 `data/aoa/mq/queue/<id>.json` 에 원자 등장** (직접 쓰기 금지)
3. 필수 필드: `type`, `message` + (`scheduled`→`due_ts`) / (`watch`→`watch.signal_type`,`watch.topic`)

```json
{
  "id": "20260703-170000-001",
  "type": "scheduled",
  "created_ts": "2026-07-03T17:00:00",
  "due_ts": "2026-07-07T09:00:00",
  "message": "fSnippet 배포 재검증 작업",
  "watch": null,
  "on_confirm": null,
  "status": "pending",
  "ask_count": 0,
  "last_ask_ts": null,
  "acked": false,
  "ack_ts": null,
  "source": "claude@___common"
}
```

* `watch` 타입은 `"status": "watching"`, `"watch": {"signal_type": "board_status"|"pane_regex", "topic": "<fpm-board topic|tmux target>"}`
* `alert` 타입은 `"status": "done_unacked"`, `due_ts`/`watch` 모두 null — ACK 액션은 `ack` (기존 시그니처 동일)
* confirm 자동 실행(prj5#Issue15): `on_response.confirm = {"kind":"spawn","cmd":"<명령>"}` 선언 + policy 이중 게이트(`allow_on_confirm_exec: true` AND cmd basename ∈ `exec_whitelist`) 통과 시에만 tick 이 detached spawn (`data/aoa/mq/exec.log`). 기본 잠금 — 미통과분은 handoff 기록만

# tick 실행

* **자동(주 구동자): hub 타이머** — htm-server 의 daemon thread 가 `--gate <sec>` 를 걸어 호출한다. **jmDashboard 에 의존하지 않는다**(F3-4)
* 자동(보조): jmDashboard `GET /` 리프레시 → 1h 게이트(`aoaMqGate()`, prj57#Issue6) → spawn. 게이트 파일(`.last-tick`)은 **어느 경로로 실행하든 갱신**되므로 두 경로가 겹쳐도 총 빈도는 ~1회/시간으로 수렴한다 — prj57 을 고치지 않고 의존을 끊은 방식
* 수동: `~/.claude/mcp/aoa-mq/aoa-mq-tick.sh` 직접 실행 — 게이트 없이 즉시 동작
* **시간축 전용으로 축소 (F3-3)**: MCP 승격(F3-2) 이후 **세션이 살아 있으면 통지 계층은 중복**이다(`session-inbox.sh` 넛지와 `aoa_mq_list` 가 같은 사실을 이미 전달). 세션 활성 시에는 통지(inbox 소비·폼 렌더·누적 경고)를 건너뛰고 **시간축 고유 처리**(watch 폴링·due 판정·post 실행·handoff 전이·retention)만 한다
    - ⚠️ **완전 제거하지 않는다** — 세션이 하나도 안 열린 기간은 세션 이벤트 트리거의 **사각지대**다. `--force-render` 로 통지를 강제할 수 있다
* 처리: inbox 소비(`sid=aoa-mq`, `aoa-mq-ack:<id>:<action>`) → watch 폴링(board_status + pane_regex) → due 판정 → 질의 폼 렌더(htm-server register-doc, alert 는 🔔 카드) → 과다 경고 → retention
* sandbox 테스트: `AOA_MQ_DIR=<dir>` 환경변수로 큐·policy 경로 오버라이드 (tick·enqueue 공통)
* 종결(confirm/dismiss/ack) 시 결과 없어도 즉시 `queue_done/` 이동. 로그: `data/aoa/mq/tick.log`

# 상태 확인

```bash
ls ~/.claude/data/aoa/mq/queue/          # 미종결 목록
tail -20 ~/.claude/data/aoa/mq/tick.log  # 최근 tick 이력
```
