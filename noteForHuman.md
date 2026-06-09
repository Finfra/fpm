---
title: pm 개발자용 참고 문서
description: Projects.md 기반 프로젝트 관리 저장소 운영 시 인간이 알아야 할 절차
date: 2026-04-20
---

# 개요
* `~/_git/__all/` 하위 프로젝트들의 경로를 번호 인덱스로 관리 (Projects.md id=1)
* zsh 함수 `cdf`를 통해 빠른 디렉토리 이동 지원

# 주요 SCAR 변경 이력

## gstack v1.4.0.0 업데이트 (Issue6, 2026-04-20)
* `rules/gstack-nptir-rules.md` — v1.4.0.0 기준으로 버전 갱신
* Phase D 유틸리티 스킬 4종 추가: `/context-save`, `/context-restore`, `/benchmark-models`, `/make-pdf`
* `~/.claude/CLAUDE.md` — gstack 버전 참조 v1.0.0+ → v1.4.0+

## superpowers × nPTiR 통합 브리지 (Issue5, 2026-04-20)
* 신규 커맨드 2종:
    - `/needs {주제}` — R1 라우팅 → A경로(brainstorming) 또는 B경로(sp-plan 직행)
    - `/sp-plan` — 경량 계획 경로 (컨텍스트 여유 부족 시 `/gstack-plan` 대안)
* 신규 규칙: `rules/sp-nptir-rules.md` — superpowers 14개 스킬 × nPTiR 매핑
* **선택 기준**: 방향 명확·단순 → `/sp-plan` / 4종 리뷰·대형 설계 → `/gstack-plan`
* Phase D 브리지: `release`·`dmg` 배포 시 `finishing-a-development-branch` 체크리스트 적용

## nPTiR 이슈 복잡도 triage 규칙 신설 (Issue4, 진행중)
* 복잡도 3단계 판정 (상세: `~/.claude/_doc_arch/nptir-triage-design.md`):
    - **단순** (파일 3개 이하·방법 자명): reg→fix→close만, plan/task/report 불필요
    - **중간** (설계 결정 후속 영향 없음): plan 필수, task/report 가치 판단
    - **복잡** (설계 결정이 후속 이슈에 영향): 전체 사이클 (plan+task+report)
* report 생성 기준: 미래 작업자 필요 / 완료 조건 검증 증거 / 명시 요청 / 복잡 판정

## gStack × nPTiR 연동 (Issue3, 2026-04-18)
* 신규 커맨드 3종:
    - `/gstack-plan` — office-hours·autoplan 결과를 nPTiR plan으로 저장
    - `/gstack-report` — ship·land-and-deploy 완료 후 nPTiR report 생성
    - `/gstack-retro-report` — retro 출력을 주간 report로 저장
* 신규 규칙: `rules/gstack-nptir-rules.md` — Phase A/B/C/D × nPTiR 매핑
* jargon 풀이 라인은 plan/report 본문에 **보존** (요약 시에도 제거 금지)

# Info

## Promotion Plan
* `~/_git/___pm/doc/MacOsApp_Plan.numbers`

## Mac UUID
* jm4 : <mac-hw-uuid>
* ma :

## Glossary
* 자체 용어:
    - SCAR = Skills, Commands, Agents, Rules
    - nPTiR = needs(of human), Plan, Task, issue, Report
      [Issue.md, _doc_work/{plan,tasks,report}]

# Script

## Management Work

### iTerm 여러 panel 열기 (범용)
1. 열고 싶은 개수만큼 iTerm panel 열기
2. Keyboard Maestro의 "iterm - input num for broadcast input" 매크로 실행
3. `ctl+a` → `cdf ` → Enter
4. `↑` → `ctl+a` → del*n (숫자만 남김) → `sleep 0.` → `ctl+e` → `&&vscode .` → Enter

```
╭─user@jm4 ~
╰─$ cdf 0
╭─user@jm4 ~/_git/___pm ‹main●›
╰─$ sleep 0.2&&vscode .
```

### 한방 스크립트 (cdfv용)
```
cdfv 0 1 2 10
# New Window(cmd+shift+n) and Move Window Tab to New Window(ctl+shift+w)
cdfv 11 12 13 14 15 16
```

## Commands
* `cdf-fapp`
* `cdf-fapp-ma`
* `fapp-pull` / `fapp-pull-ma`
* `fapp-push`
* `fapp-run` / `fapp-run-ma`

# fApp

| #    | 앱 이름      | GitHub                                 | 제품 페이지                                          |
| :--- | :----------- | :------------------------------------- | :--------------------------------------------------- |
| 11   | fBanner      | https://github.com/nowage/fBanner      | https://finfra.kr/product/fBanner/kr/index.html      |
| 12   | fBoard       | https://github.com/nowage/fBoard       | https://finfra.kr/product/fBoard/kr/index.html       |
| 13   | fGoogleSheet | https://github.com/nowage/fGoogleSheet | https://finfra.kr/product/fGoogleSheet/kr/index.html |
| 14   | fQRGen       | https://github.com/nowage/fQRGen       | https://finfra.kr/product/fQRGen/kr/index.html       |
| 15   | fSnippet     | https://github.com/nowage/fSnippet     | https://finfra.kr/product/fSnippet/kr/index.html     |
| 16   | fWarrange    | https://github.com/nowage/fWarrange    | https://finfra.kr/product/fWarrange/kr/index.html    |

## Accessibility Reset Problem
* fSnippet·fWarrange는 Accessibility 권한이 필요한 앱
* 권한이 꼬이는 경우가 종종 발생

### 해결 절차
1. Xcode 설정: `img/notForHuman.png` 참고
2. Xcode Warning 제거: Xcode에서 `!` 버튼 클릭 (Claude에서 하지 말 것)
3. 아래 `t5.nk.md` 스니펫으로 확인
4. Claude Code에서 `/run` 명령 실행
5. 각종 기능 정상 작동 확인

### t5.nk.md
```
¶0:# App Name Setting
app=fSnippetCli

¶.:# App Name Setting
app=fWarrangeCli

¶1:# kill
pkill -f MacOS/$app || true

¶2:# reset
tccutil reset Accessibility kr.finfra.$app

¶3:# 1차 실행
open /Applications/_nowage_app/$app.app

¶4:# 확인
pkill -f MacOS/$app || true
open /Applications/_nowage_app/$app.app
```

# Prompt
* [PROMPTS.md](PROMPTS.md)

## 각 프로젝트 nPTiR 적용 프롬프트

1. 상황 확인 (needs)
```
nPTiR 체계로 작업할 예정임. 원활한 작업이 가능한지 report(check-nNPTiR)생성해줘.
```

2. Plan 생성
```
생성된 report(check-nNPTiR) 기반으로 원활한 작업을 위한 Plan(start-nPTiR)를 만들어줘. 없는 폴더 있는지, SCAR(Skills, Commands, Agents, Rules)는 정상으로 작동하는지 .gitignore등은 적당한지. 모든 측면에서 확인하고 잘 작동하기 위한 Plan 생성해줘.
```

3. Task 생성
```
plan으로 task만들어줘.
```

4. 구현 (issue)
```
task파일을 이슈에 등록하고 구현해줘. /dev
```

5. Report 생성
```
완료 레포트 생성해줘.
```

# Hub

## 3모드 트리거 (Issue126·133, 2026-06-03)
| 트리거    | 모드 | content_type | 역할                          |
| :-------- | :--- | :----------- | :---------------------------- |
| `..show`  | a    | `response`   | 단방향 HTML 렌더 (구 `..hub`) |
| `..ask`   | b    | `form`       | 양방향 Q&A 폼 자동 회수       |
| `..board` | c    | `dashboard`  | Live Dashboard (tmux + SSE)   |

* 별칭·하위호환 (Issue133)
    - a모드: 구 `..hub` / `/hub` → `..show` 로 rename. 구 트리거는 deprecated alias 로 한시 유지
    - 우산 토글 `..hub on|off|start|stop` 은 그대로 보존 — 토글(`..hub`)과 렌더 트리거(`..show`)의 단어 충돌을 푼 것이 rename 의 목적
    - c모드: 구 `..hub dash` / `..dashboard` → `..board`
* 트리거 파싱 = 글로벌 hook 책임, hub 서버는 content_type 만 판정 (서버 코드 무변경)

## show (a모드)
SSOT: `~/.claude/_doc_arch/hub-mode-arch.md`
* 기본 on (prj 폴더) / 명시적 on (`..show`, 구 `..hub`)
* HTML 문서 Write + Firefox open

## ask (b모드)
* `..ask` 명시 트리거 또는 `AskUserQuestion` intercept (`ask-intercept.sh`)
* HTML 폼 → fetch POST → server inbox → Claude polling 자동 회수 (Issue45 단일 경로)

## board (c모드, dashboard)
SSOT: `_doc_arch/hub_dashboard_tmux_design.md` / Ops: `~/.claude/agents/dashboard.md`, `.claude/commands/dashboard.md`
* `..board <topic>` (구 `..dashboard` 별칭) — tmux window 1:1 매칭 + `_<topic>` 접두사 (로컬 pm 세션)
* 각 dashboard = pmux window 자동 생명주기 관리
* 재현 키트: 9개 시나리오 재현 프롬프트·fixture → `_doc_work/board/` (s1~s9, 인덱스 `_doc_work/board/README.md`) (Issue148)

#### 시나리오 1: 대량 순차 파일 생성 (폴더 1000개)
폴더 1000개를 1초 간격 생성 → progress 실시간 추적 (n/1000) → 소요 시간 기록
→ 구현: window `_build-1000` 에서 queue.yaml (item 1000개) + synthetic worker (1초 sleep) + progress badge

#### 시나리오 2: 크로스 프로젝트 이슈 위임
prj A에서 prj B 이슈 자동 생성 → /pm-do 호출 → prj B worker 디스패치 → 진행 추적
→ 구현: window `_cross-prj` 에서 queue.yaml DAG (a→b,c 의존성) + cross-prj worker spawn + graph 위젯

#### 시나리오 3: Issue tree (이슈 의존성 트리)
여러 선행·선후 이슈들의 의존성 트리 → 각 이슈 진행 상태 (등록→분석→계획→구현→검증→종결) 추적
→ 구현: window `_issue-tree-<project>` 에서 queue.yaml (DAG: issue 다중 경로) + graph (트리 시각화) + 각 이슈별 progress bar

#### 시나리오 4: nPTiR 파이프라인 진행
needs 탐색 → plan 작성 → task 분해 → issue 등록 → 구현 → 검증 → report 생성 (6단계)
→ 구현: window `_nptir-<topic>` 에서 queue.yaml (6개 item 순차) + 각 단계 파일 생성 확인

#### 시나리오 5: /goal 마일스톤 진행도
목표 분해 → M1, M2, M3... 각 마일스톤 진행률 추적 → 예상·실제 소요 시간 비교
→ 구현: window `_goal-<name>` 에서 queue.yaml (마일스톤별 task) + graph (의존성) + progress (각 마일스톤별)

#### 시나리오 6: Task 병렬 관리
15개 task, 병렬도 3 → 각 task 할당→진행→완료 자동 순환 → worker 3개 활성 상태 추적
→ 구현: window `_tasks-parallel` 에서 queue.yaml (concurrency: 3) + badge (3/15 running) + table (task별 소요시간)

#### 시나리오 7: 주기적 모니터링
10분 주기 헬스체크 (server 상태, 프로세스, 디스크) → 각 실행 결과·시간 누적 기록 → 마지막 상태 표시
→ 구현: window `_monitor-health` 에서 while 루프 (10분 sleep) + 각 실행 pane 누적 log + badge (마지막 상태)

#### 시나리오 8: 정기 작업 스케줄
일일 브리핑 (09:00), 주간 리뷰 (월 10:00), 월간 리포트 (1일 14:00) → 실행 예정·완료·다음 시간
→ 구현 (Issue118): crontab 미사용. "정기 실행 = 주기 모니터링 패턴(infinite heartbeat) 재사용" 으로 일원화 — window `_schedule-tasks` 에서 단일 `interval` 주기 반복 + table (작업별 예정/완료/다음) + badge. 항목별 상이 주기 필요 시 별도 window(각자 INTERVAL) 분리. (cron 파서·스케줄 daemon 불필요 — tmux 세션 종료 시 전체 종료 보장)

#### 시나리오 9: 대용량 전송 진행 + SVG 시계열 그래프 (scp/rsync)
원격 호스트로 100GB+ scp/rsync 전송 → 진행률·전송량·속도·ETA 를 실시간 추적 + **시간축 SVG 라인차트**로 추세 시각화.
* 진행률 산출: 대상 호스트 여유공간 델타(`fsutil`/`df`) 역산. Windows host 는 `LC_ALL=C` 필수(한글 출력 → BSD grep/sed "illegal byte sequence" 회피), epoch 파싱은 `python3 time.strptime`.
* 시계열 누적: monitor 가 매 폴링마다 `history.tsv`(`epoch \t progress_pct \t transferred_gb`) 1줄 append (단일 writer 책임).
* **SVG 차트 렌더 (server.py _render_chart_svg)**: widget `type: chart`|`graph`|`sparkline` + `value` 가 숫자배열/공백·콤마문자열/`{points,ymax,ymin,unit,label}` dict 면 인라인 `/view` 가 라인+area SVG 곡선을 그림. 포인트<2·파싱불가 시 기존 value 렌더로 자연 fallback. 유니코드 스파크라인은 텍스트 fallback.
* 속도·ETA: history 최근 ~10포인트 기울기 → GB/min, 남은량/속도 → ETA.
* 자동 종료: scp 프로세스 생존 watcher → 사라지면 runner `status=done` 마킹 후 자가 정지.
→ 구현: window `_scp-<dest>` 에서 monitor(interval 15s) + 그래프 위젯 + rate_eta(text) + scp_status(badge) + dest_list(table). 정적 스냅샷 그래프가 별도로 필요하면 `_doc_work/z_htm/` 에 history.tsv → SVG HTML 생성 후 Firefox open (재현: "그래프로 보여줘").
* **그래프 구성 (의미 중복 회피)**: 진행률·누적 전송량은 단조 증가라 line 곡선 2개가 동일 모양 → 중복. 권장: **진행률 = `pie` 도넛(순간값, 1셀 고정)** + **전송량 = 시계열 line(GB, width 2)** + **파일 갯수 = 시계열 line chart(`{points:[완료수 추이], ymin:0, ymax:전체수, unit:"개"}`)** — 개수 증가 추세 표시(pie 는 순간 비율만이라 추세 안 보임). 모든 시계열 0 기준 시작(ymin 미지정 시 자동 0).

# 📌 ToDo
* TODO: 프로젝트 추가·삭제 시 수동 검증 절차
* TODO: `cdf` 함수 동작 확인 시나리오
* TODO: `sync-ma`, `fapp-*` 커맨드 수동 테스트 절차
* TODO (2026-04-19): Context-budget 가드 구현 — `/needs`·`/sp-plan` 실행 시 예상 토큰 경고 출력. gstack-plan(~10k+) vs sp-plan(~3k) 사전 안내로 compact 재발 방지. 구현 난이도 M. 1개월 실사용 후 재평가.
* TODO (2026-04-19): SP 사용 로그 수집 — `~/.claude/sp-usage.jsonl`에 SP 스킬 호출 기록(hook 활용). 1개월 후 호출 빈도 기반 추가 브리지 SCAR 결정. 관찰 기간 필요하므로 독립 진행.
* TODO (Issue4 진행중): `_doc_arch/nptir-triage-design.md` 작성 완료 후 `/issue-reg-g`로 이슈 번호 발급 + `/issue-closer-g` 실행.