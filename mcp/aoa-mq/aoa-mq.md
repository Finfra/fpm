---
name: aoa-mq
description: 메시지 큐 AOA — "N일 후 작업" 예약 리마인드·장기작업 완료 통지를 사용자 ACK 전까지 반복 질의. 트리거 — "mq 등록", "N일 후에 …해줘 (mq)", "이 작업 끝나면 알려줘 (mq watch)". tick 은 launchd `t-5m`(schedule.yml)이 기동 — hub 스레드·jmDashboard 경로는 폐지(Issue537·541).
---

> 설계 SSOT: [`_doc_arch/aoa-mq.md`](../../_doc_arch/aoa-mq.md) · 관리 규칙: [`_doc_arch/aoa__management-rules.md`](~/_git/___common/_doc_arch/aoa__management-rules.md)
> 안전가드: `data/aoa/mq/policy.yml` — 파괴적 행위 없음, 자기 데이터 디렉토리와 inbox 자기 시그니처 파일만 조작.

# 역할

시간 축 메시지 큐. 세 가지 메시지를 `data/aoa/mq/queue/`에 보관하고, tick 마다 처리한다:

* `scheduled` — 예약 리마인드. due 도달 시 "오늘 진행?"을 사용자 ACK(confirm/snooze/dismiss) 전까지 반복 질의
* `watch` — 장기작업 완료 감시. 신호 2종: `board_status`(fpm-board sentinel) | `pane_regex`(tmux pane idle/부재 — prj5#Issue14). 완료 감지 시 ACK 전까지 반복 통지
* `alert` — 상위 AOA(observer 등)가 위임한 이미 발생한 이벤트 (prj5#Issue13). 등록 즉시 `done_unacked` — ACK 전까지 반복 통지

본 AOA는 통지·확인 전담 — 작업 실행 주체가 아니다. tick(`aoa-mq-tick.sh`)의 기본 계약은 **호출되면 무조건 실행**이며, 게이트는 두지 않는다 — 구동 주기는 `data/schedule.yml` 의 `t-5m` 이 정한다(prj3#Issue537). `--gate` 인자는 코드에 남아 있으나 호출자는 없다. 종전 hub 스레드·jmDashboard 경로(F3-4)는 Issue537·541 로 폐지됐다.

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
* `--alert`: 등록 주체가 즉시성 필요 시 enqueue 직후 `aoa-mq-tick.sh` 를 1회 직접 kick (다음 `t-5m` 을 기다리지 않고 즉시)
* **잡 지목 (`--job <잡> [--arg V]`, prj3#Issue691)**: `--due` 와 함께만. 등록 시 `schedule.sh catalog --json` 으로 **선언 존재 검증**(없으면 exit≠0). `kind` 는 `post` 고정, `--message` 는 생략 가능(`잡 실행: <잡>[ ⟨arg⟩]` 자동). 항목에 `job`·`job_arg` 필드
    - due 도달 시 tick 이 whitelist 게이트 대신 `schedule.sh dispatch --job <잡> --event mq-<id> --json` 을 **동기 실행**(선언된 잡만 = 그 자체가 whitelist). 결과를 `job_result`·`job_rc`·`result`·`result_ts` 에 쓰고 `done_unacked` 로 올린다 — 사람이 결과를 보고 ACK
    - 멈춘(paused) 잡을 지목하면 실행하지 않고 `job_result=paused` + 사유를 남겨 `done_unacked`(조용히 삼키지 않는다). 긴 잡은 그동안 tick 을 점유한다 — 상한은 잡 선언의 `timeout`
    - 설계: [`_doc_arch/schedule-arch.md`](../../_doc_arch/schedule-arch.md) "큐 --job"
* `--target prj<N>` (prj3#Issue770): 이 항목을 **수행할 프로젝트**. 넛지 범위(그 prj 세션만 본문 주입)·기동 cwd 의 1순위 근거. 번호는 `~/_git/___pm/projects/{N}` 에 있어야 한다(매핑 없으면 거부). 생략하면 message 첫 `prjN` → source 프로젝트 순으로 판정한다
* `--source` 생략 시 `claude@<cwd basename>` 자동. 성공 시 `enqueued: <경로>` echo, 실패 시 exit≠0 fail-loud
* 글로벌 진입점: 모든 프로젝트에서 `/mq-send` (prj3 `commands/mq-send.md`, prj3#Issue192) — 본 helper 의 얇은 wrapper
* **재스케줄 (prj5#Issue63)**: `--reschedule <id> --due <+Nd|YYYY-MM-DD|ISO8601>` — 기존 항목의 `due_ts` 만 바꾸는 1급 경로. 등록 인자(`--message`·`--watch`·`--alert`·`--kind`·`--on-response`)와 **배타**이며 `queue/` 항목만 대상. 큐 JSON 을 손으로 고치고 digest 를 따로 돌리는 2단계는 **폐지**됐다
    - `+Nd` 는 **기존 시각을 보존**하고 날짜만 옮긴다(기준일 = `max(오늘, 기존 due 날짜)`). tick 의 `snooze` 도 이 경로에 위임하므로 원래 시각(19:00 등)이 더는 소실되지 않는다
    - tick 과 **같은 `.tick.lock`** 을 잡아 상호배제한다(mv 는 파일 1개만 원자적이라 digest 재생성 구간을 못 막는다). 10초 대기 후 거절. `AOA_MQ_LOCK_HELD=1` 은 tick 위임 전용 재진입 escape
    - **고아 락은 기다리지 않는다 (prj3#Issue633)**: 보유 PID(형제 파일 `.tick.lock.pid`)가 죽었으면 나이와 무관하게 즉시 탈취한다. 10초 대기·나이 30분 탈취는 *생사를 모르거나 살아는 있으나 멎은* 경우의 폴백이다
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

# 진행 기록 (Issue643 — 집은 뒤가 보이게)

**표준 경로**: helper 스크립트 사용 — 큐 JSON 직접 수정 금지(원자적 쓰기·락 규약이 여기 있다)

```bash
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh claim  <id> --by "<세션 sid|bot_id>" [--force]
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh note   <id> --text "<진행 1줄>"
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh result <id> --text "<결과 요약·산출물 경로>"
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh show   <id>

# Issue770 — 대기·사람 몫·대상 prj
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh wait      <id> --for "<조건|mq:<id>>" [--recheck <+Nd|+Nh|YYYY-MM-DD|ISO>]
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh resume    <id> [--via "<사유>"]
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh need      <id> --text "decide:<결정>|act:<사람 행동>"
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh need-done <id> (--index N | --text "<항목>") [--by <주체>]
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh target    <id> [--json]
~/.claude/mcp/aoa-mq/aoa-mq-progress.sh launch    <id> [--dry-run] [--force]   # hub [진행] 직후 즉시 기동
```

* **⏳ 대기(`wait`)**: 외부 조건을 기다려야 하면 진행 중으로 방치하지 않고 `waiting` 으로 옮긴다. 7.7 적체·7.8 기동·세션 넛지에서 빠진다. `--recheck` 생략 시 3일 뒤(policy `wait_default_recheck_days`) — 그때 `due` 로 다시 묻는다. `--for mq:<id>` 는 그 항목이 종결되면 tick 이 자동 `resume`
* **`resume` 은 원래 상태(wait_from)로만** 돌린다 — `due` 였던 항목이 `in_progress` 가 되지 않는다
* **🙋 사람 몫(`need`)**: 사람의 결정·행동이 필요하면 산문으로 적고 턴을 끝내지 말고 여기 올린다(대화 중이면 AskUserQuestion). `decide:`·`act:` 접두 필수. 해소는 `need-done`(hub 의 개별 승인이 여기로 온다)
* **`target`**: 대상 prj·cwd 판정(`aoa-mq-lib.sh` 단일 지점) — tick·session-inbox·hub 가 같은 답을 본다
* **`launch`**: 사람의 [진행] 직후 대상 prj cwd 에서 `claude -p` 를 즉시 띄운다(무인 기동 7.8 과 같은 lib 한 벌 · `wake_count` 공유). policy `allow_start_launch`(기본 true) · 재클릭 쿨다운 `start_launch_cooldown_mins`(기본 10) · 거부 rc 3. 세션이 부를 일은 없다 — hub 가 부른다(타 prj 세션 기동은 사람 클릭이 곧 승인)
* MCP: `aoa_mq_progress` 가 `wait_for`·`recheck`·`resume`·`needs_human`·`needs_human_done` 을 받는다(위 helper 위임). `aoa_mq_ack snoozed` 는 `--reschedule` 위임 — `status=pending`·원래 시각 보존

* 세션에서는 MCP `aoa_mq_progress` 가 위 helper 를 부른다 — 직접 bash 로 부를 일은 helper 가 없는 환경뿐
* **종결과 함께 결과를 남길 때는 `aoa_mq_ack` 의 `result` 인자**를 쓴다(한 트랜잭션). helper `result` 는 종결 전에 남길 때용
* `claimed_by` 는 세션 넛지가 자동 기록하므로 보통 손댈 일이 없다 — **잠금이 아니라 표식**이라 다른 주체가 적혀 있어도 착수를 막지 않는다
* ⚠️ 착수했으나 **할 수 없는 경우에도** 사유를 `note` 에 남긴다. 그러지 않으면 다음 사람이 같은 조사를 반복한다(2026-09-19 유령 항목 실발생)
* 락 대기 상한은 env `AOA_MQ_LOCK_WAIT`(초, 기본 10). 차단 경로에서 부르는 호출자는 짧게 준다
* 설계 근거: [`_doc_arch/aoa-mq.md`](../../_doc_arch/aoa-mq.md) "진행 가시성"

# tick 실행

* **자동(주 구동자): launchd `t-5m`** — `data/schedule.yml` 선언 → `schedule.sh dispatch t-5m` → `aoa-mq-tick.sh`, 게이트 없이 5분마다(prj3#Issue537)
* 보조 구동자 없음 — jmDashboard(prj57) `aoaMqGate()` 경로는 Issue541 로 제거(prj57 `3e2bd11`, 2026-09-05)
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
