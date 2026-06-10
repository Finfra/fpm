---
name: fpm-dashboard
description: tmux 기반 dashboard agent wrapper. window 1:1 매칭으로 runner/supervisor 가동. 순수 모니터링 + 큐 오케스트레이션 2모드
date: 2026-05-31
---

> ⚠️ **글로벌 SCAR 변경 가드 (Issue46)**: 본 커맨드는 모든 프로젝트가 공유. cwd ≠ `~/.claude/` 면 즉시 수정 금지 → `~/.claude/Issue.md` 이슈 등록 후 처리. 영속 설계 SSOT: `~/.claude/_doc_arch/dashboard.md`. 절차: `~/.claude/rules/global-scar-change-rules.md`

# /dashboard {topic}

`dashboard` agent wrapper. Agent 도구로 subagent 호출 → tmux window(1:1 매칭)에서 runner 시작 → data 파일 자동 갱신. 2개 모드 — **순수 모니터링** / **큐 오케스트레이션**(Issue84).

# 입력

## 순수 모니터링 모드

* `<topic>` (필수) — dashboard 주제 식별자
* `<commands>` (선택) — runner가 주기 실행할 외부 명령 (data 파일 `commands:` 필드)
* `<interval>` (선택, 기본 5초) — 갱신 주기

## 큐 오케스트레이션 모드 (Issue84)

* `queue` 키워드 + `<items>@<concurrency>` — DAG 큐로 여러 이슈 일괄 처리
* `<items>` — `<prj>:<issue>` 쉼표 구분 (ex: `1:57,3:7`). prj 생략 시 현재 prj
* `<concurrency>` (선택, 기본 2) — `@N` 으로 지정. 동시 running 상한
* ex: `..dashboard queue 1:57,3:7@3` / `/dashboard --queue 1:57,3:7@3`

# 동작

1. `$ARGUMENTS` 파싱:
   * 첫 토큰이 `queue` 또는 `--queue` 플래그 → **큐 모드** — 이후 토큰을 `<items>@<conc>` 로 파싱
   * 그 외 → **순수 모니터링 모드** — 첫 토큰을 `<topic>` 으로 추출
2. 필수 인자(`<topic>` 또는 `<items>`) 비어있으면 1회 질의 후 종료
3. `Agent` 도구 호출 (`subagent_type: "dashboard"`) — prompt 에 모드·인자 명시
4. agent 가 `tmux new-window -t pm -n _<topic>` 생성 + runner 실행 (data 파일 갱신)
   * 순수 모니터링 — runner 1 + worker 0~1
   * 큐 — supervisor 1 + queue-runner 1 + worker N (lazy)
5. agent 결과 메시지 그대로 사용자에게 전달 (URL + pane 명령 + 핵심 데이터/DAG 요약 포함)

## pane 모니터링 명령

runner/supervisor 진행 상황 실시간 확인 (browser 미관측 시):

```bash
# 현재 pane 내용 확인
cdft capture :_<topic>          # 순수 모니터링
cdft capture :dash-<topic>      # 큐 모드

# pane 종료
cdft kill :_<topic>
cdft kill :dash-<topic>

# runner status 확인
yq '.pid' $DATA_FILE            # runner PID
yq '.status' $DATA_FILE         # status: running|stopped|done
yq '.worker_pid' $DATA_FILE     # worker PID (큐 모드)
```

# 트리거 동등성

| 호출 방식                            | 동작                                                          |
| :----------------------------------- | :------------------------------------------------------------ |
| `/dashboard <topic>`                 | 순수 모니터링 — 본 wrapper (명시적 슬래시)                     |
| `..dashboard <topic>` / `..hub dash <topic>` | 순수 모니터링 — `fpm-hub-trigger.sh` 자동 감지 → agent 호출 |
| `/dashboard --queue <items>@<conc>`  | 큐 오케스트레이션 — 본 wrapper                                 |
| `..dashboard queue <items>@<conc>`   | 큐 오케스트레이션 — `fpm-hub-trigger.sh` 자동 감지 → agent 호출    |

# 구버전

Skill 방식(`~/.claude/skills/dashboard/`)은 main turn 점유·진행 가시성 부족·동시 작업 차단 문제로 폐기 (2026-05-19, Issue24 Phase 7).

# 산출물

* agent: `~/.claude/agents/fpm-dashboard.md`
* runner (순수 모니터링): `~/.claude/agents/fpm-dashboard-runner.sh`
* supervisor·runner (큐 모드, Issue84): `~/.claude/agents/fpm-dashboard-supervisor.sh`, `~/.claude/agents/fpm-dashboard-queue-runner.sh`
* queue.yaml 스키마: `~/.claude/agents/fpm-dashboard-queue.sample.yaml`

# Opus 4.7 실행 제약

Agent 호출 1회. 실패 시 사용자 보고 + 중단. 자동 재시도 금지.
