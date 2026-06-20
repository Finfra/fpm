---
title: pm 개발자용 참고 문서
description: Projects.md 기반 프로젝트 관리 저장소 운영 시 인간이 알아야 할 절차
date: 2026-04-20
---

> 🌐 [English](noteForHuman.md) | **한국어**

# 개요
* `~/_git/__all/` 하위 프로젝트들의 경로를 번호 인덱스로 관리 (Projects.md id=1)
* zsh 함수 `cdf`를 통해 빠른 디렉토리 이동 지원

# 주요 SCAR 변경 이력

* 별도 분리: [_doc_work/refs/scar-change-history.md](_doc_work/refs/scar-change-history.md) (gstack v1.4.0.0 / superpowers×nPTiR 브리지 / nPTiR triage / gStack×nPTiR 연동)

# Info

## Promotion Plan
* `~/_git/___pm/_doc_arch/define/fApp_Plan.numbers`

## Glossary
* 자체 용어:
    - SCAR = Skills, Commands, Agents, Rules
    - nPTiR = needs(of human), Plan, Task, issue, Report
      [Issue.md, _doc_work/{plan,tasks,report}]

# fpm 공개 미러 (fpm-sync, Issue150·151·158)

___pm(개인) ↔ 공개 미러 fpm(prj7, github.com/Finfra/fpm) 양방향 동기화. post-commit hook 가 매 커밋마다 자동 forward. 역방향(reverse)·배포(deploy)·정책편집(policy)은 `fpm-sync` 단일 스킬에서 수행 (Issue158: publishable 스킬 흡수, deploy→sync 네이밍 통일).

## 핵심 경로
* **정책 데이터 SSOT**: `data/publishable-policy.yml` — `exclude`(제외)/`personal_guard`(개인정보 가드)/`sanitize`(치환) 목록. 변경은 이 파일만 편집
* **통합 dispatcher**: `scripts/fpm-sync.sh <forward|deploy|reverse|policy>` — hook·스킬 공용 진입점. 정책 YAML 직독
* **결정성 헬퍼**: `scripts/fpm-guard.sh`(개인정보 abort) · `scripts/fpm-sanitize.sh`(치환) · `scripts/fpm-policy-lib.sh`(파서)
* **스킬**: `.claude/skills/fpm-sync/` — forward/deploy/reverse/policy 오케스트레이션. (구 `publishable` 스킬은 deprecated shim)
* **아키텍처 SSOT**: `_doc_arch/publishable-policy.md` (로컬 전용)
* **sync 로그**: `_doc_work/z_log/fpm-sync.log` — 매 sync 타임스탬프 append (로컬 전용, gitignored). `tail -f` 로 추적

## 운영
* 수동 sync: `bash scripts/fpm-sync.sh forward` (단, hook 가 커밋마다 자동 실행)
* 배포: `bash scripts/fpm-sync.sh deploy [patch|minor|major] [--no-push]` (버전 bump+tag+push)
* 역방향 미리보기: `bash scripts/fpm-sync.sh reverse` (적용은 `reverse --apply`, working tree 만)
* 정책 편집: `bash scripts/fpm-sync.sh policy show|validate|exclude|guard|sanitize ...`
* push 는 정책상 수동(검토 게이트): `git -C ~/_git/__all/fpm push`
* 모델: denylist — exclude 안 된 tracked 파일은 전부 publishable. allowlist 없음

## 설치 / 제거 / 클린 재설치 (배포본, Issue161, 2026-06-13)
* 설치: `bash sh/install.sh` — rc(zshrc·bashrc)에 fpm 부트스트랩 블록 + `~/.info/__pmBasePath.txt` 생성 (멱등)
* 제거: `bash sh/uninstall.sh` — rc 블록 + `~/.info/__pmBasePath.txt` 를 백업 후 제거 (멱등, 흔적 없으면 no-op) + fpm-core 플러그인 uninstall (`--no-scar` 로 셸만)
    - 백업 위치: `<repo>/_doc_work/z_done/fpm-uninstall-<YYYYMMDD_HHMMSS>/` (env `FPM_BACKUP_DIR` 로 변경 가능)
    - **보존**: `projects/`·`Projects.md`·`Servers.md` (사용자 데이터 — 자동 삭제 안 함), marketplace `f-claude-plugins` (공유 마켓 — cascade 보호)
* 클린 재설치: `bash sh/install.sh --clean` — uninstall(백업+제거) 후 재설치를 한 번에
* 정리 범위 = 셸 아티팩트 + fpm-core 플러그인 (Issue185)
* 소스=___pm `sh/` 3파일(install.sh·uninstall.sh·check.sh) + 루트 INSTALL.md → fpm-sync 로 미러 전파(Issue185 — sh/ 이동). `_doc_work/` 백업물은 미러 제외(비공개)

## 구동 요구 사항 (런타임 의존성, 2026-06-21)

설정은 YAML 이 아니라 평문 텍스트(`projects/<번호>`)·마크다운(`Projects.md`/`Servers.md`) 기반이라 설정 파서는 불필요. 다만 기능별로 외부 런타임 도구가 필요하며, 이는 fpm 공개 미러의 `README.md` "요구 사항" 섹션 + `INSTALL.md` "요구 사항" 에 명시(SSOT=공개 미러). 요지:

* **zsh** (필수): cdf/sshf 셸 함수군
* **Claude Code CLI** (`claude`) + **Node.js**: SCAR(fpm-core 플러그인) 사용 시 필수 — claude CLI 가 npm 배포·일부 MCP 가 npx 구동
* **Python 3**: hub 대시보드(`services/hub/`)·MCP(`mcp/`) 서버
* **tmux**: dashboard 에이전트 runner·`cdft` tmux pm 세션
* 선택: iTerm2·VS Code(`code`)·Keyboard Maestro

셸 함수만 쓰면 zsh 외 의존성 없음. `sh/install.sh` 는 `claude` 부재 시 SCAR 만 건너뛰고 셸 설치는 정상 완료(exit 0).

# claude-harness 설치 롤백 (harness-uninstall.sh, 2026-06-18)

`install.sh`(fpm 셸 툴킷)와는 **별개**. claude-harness 문서(`https://finfra.kr/jg/2026/06/13/claude-harness/`)는 doc-driven 설치(URL 한 줄 → Claude 가 스켈레톤 생성)라 설치 스크립트가 없었고, 테스트 설치를 되돌릴 경로도 없었음. 이를 위해 롤백 스크립트를 신설.

* **스크립트 위치**: `~/_git/__all/social/_contents/claude-harness/harness-uninstall.sh` (claude-harness 문서와 함께 배포)
* **무엇을 되돌리나**: 하네스 설치가 만든 ① 프로젝트 루트 골격(`Issue.md`·`CLAUDE.md`·`Harness.md`·`noteForHuman.md`·`PROMPTS.md` + `_doc_work/`·`_doc_arch/`) ② 글로벌 `~/.claude` SCAR 골격(`skills`·`commands`·`agents`·`rules` + `CLAUDE.md`)
* **테스트 대상(현재)**: fg1 — `fg1:~/_git/__all/test1`(프로젝트 루트) + `fg1:~/.claude`(글로벌)
* **안전 설계**:
    - dry-run 기본 — `--apply` 없으면 무엇이 지워질지 출력만
    - 제거 전 타임스탬프 `tar.gz` 백업 → `~/.claude-harness-rollback-backups/<YYYYMMDD-HHMMSS>/` (원복: `tar -xzf`)
    - 글로벌 SCAR 디렉토리는 **비어 있을 때만** 제거(자산 설치돼 있으면 경고만). `~/.claude` 의 credentials·sessions 는 미대상
* **사용 예**:
    - `bash harness-uninstall.sh --project ~/_git/__all/test1` (dry-run)
    - `bash harness-uninstall.sh --project ~/_git/__all/test1 --apply` (프로젝트 골격만)
    - `bash harness-uninstall.sh --project ~/_git/__all/test1 --apply --keep-work` (산출물 보존, init 파일만)
    - `bash harness-uninstall.sh --project ~/_git/__all/test1 --apply --global` (글로벌 `~/.claude` 골격까지)
* **재테스트 루프**: 롤백 → 문서대로 재설치 → "적용 후 검증" 체크리스트(0바이트 init 파일 회귀 등 설치 결정성 점검)
* **관련 회귀**: 설치 시 `Issue.md` 만 골격 받고 나머지 4개 init 파일이 0바이트로 생성되던 버그 → 문서 "초기화 파일 skeleton (0바이트 금지)" 절로 차단 (2026-06-18)

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
* HTML 문서 Write + 브라우저 open (`default_browser` / `browser_tab_reuse` 따름 — 아래 섹션)

## 브라우저 / 탭 재사용 (Issue162, 2026-06-13)
hub 렌더가 어느 브라우저로 어떻게 열리는지는 `data/hub_setting.yml` 의 `default_browser` + `browser_tab_reuse` 가 결정. 핵심 트레이드오프는 "탭 재사용 가능 여부" 단 하나:

* **Firefox** = 탭 재사용 **불가**. 네이티브·CLI·AppleScript 어느 경로로도 tab 제어가 안 됨(scriptable tab 사전 부재). 렌더할 때마다 새 탭이 무한 누적되는 것을 감수해야 함.
* **Chrome / Safari / Edge** = AppleScript 로 기존 `:9876` hub 탭을 찾아 재사용 가능 → **권장**. `browser_tab_reuse: true` + `default_browser: chrome` 조합이면 hub 탭이 항상 1개로 유지됨.
* 매칭은 origin(`http://127.0.0.1:9876`) prefix 기준이라 `/hub` 대시보드와 응답별 `htm-doc?path=…` 가 **같은 탭 하나**로 통합됨(기존 탭에 URL 덮어쓰기 = Issue162 Q2 "단일 탭 통합" 결정). 대시보드를 항상 따로 보존하고 싶으면 `browser_tab_reuse: false` 로 끄거나 대시보드만 별도 창으로 분리할 것.
* 터미널(iTerm 등)에서는 `fhub` 한 줄로 동일 동작 — Keyboard Maestro 매크로 "fPm hub page Open" 의 CLI 버전이며, hook 과 공용 helper(`plugins/fpm-core/hooks/fpm-browser-open.sh`)를 공유함.
* 구 Issue130 의 "Chrome=일반 / Firefox=hub 전용 분리" 권장은 Firefox 탭 누적 문제 때문에 철회됨.

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

## 설정 모달 — 적용 타이밍 배지 (Issue168, 2026-06-14)

hub 페이지 우상단 ⚙️ 버튼 → **인앱 3탭 설정창**(기본/세션관리/고급). 각 설정 우측의 색 배지는 그 값을 **저장한 뒤 언제 실제로 효력이 생기는지**(적용 타이밍)를 뜻함. 설정마다 그 값을 읽는 주체가 달라서 반영 시점이 3가지로 갈린다.

| 배지          | 읽는 주체                             | 저장하면 언제 적용?                                                                       |
| :------------ | :------------------------------------ | :---------------------------------------------------------------------------------------- |
| 🟢 **자동**    | hub 서버(`server.py`)                 | **즉시**. 서버가 파일 변경(mtime)을 감지해 자동 재로드 — 아무것도 안 해도 됨              |
| 🔵 **다음턴**  | 글로벌 hook (렌더할 때마다 읽음)      | **다음 렌더부터**. Claude 가 다음 응답을 그릴 때 새 값으로 동작                           |
| 🟠 **restart** | hub 서버가 **기동할 때 한 번만** 읽음 | **서버 재시작 필요**. `/dashboard-server restart` 를 해야 반영 (현재 `bind_host` 만 해당) |

* **왜 3종으로 갈리나**: 설정 키마다 소비처가 다르다. 피드·세션·표시 상한은 서버가 매번 다시 읽으니 즉시(🟢), 브라우저·렌더 경로(`default_browser`·`render_target` 등)는 hook 이 응답 그릴 때 읽으니 다음 턴(🔵), 서버가 listen 할 네트워크 주소(`bind_host`)는 떠 있는 서버를 바꿀 수 없으니 재시작(🟠).
* **저장 후 동작**: 🟠 키를 바꾸면 모달이 "♻️ 재시작 필요" 토스트를 띄운다. 🟢·🔵 는 별도 안내 없이 알아서 반영.
* **고급 탭 경고**: `bind_host: 0.0.0.0`(외부 개방) 으로 두면서 `advertise_host` 를 비우면 hub 주소가 `0.0.0.0` 이 되어 브라우저로 못 열린다 → 저장이 막힌다(차단). 0.0.0.0 쓸 때는 `advertise_host` 에 실제 IP·도메인을 반드시 적을 것.
* **raw 편집**: 모달 하단 "📄 설정 파일 열기" = 예전 동작(VSCode 로 `data/hub_setting.yml` 직접 편집). 모달이 불편하거나 주석을 손보고 싶을 때 사용.
* 키별 상세·소비처 SSOT: `_doc_arch/hub_setting.md` / 모달 UI 설계: `_doc_arch/hub_settings_ui.md`.

# 📌 ToDo
* TODO: 프로젝트 추가·삭제 시 수동 검증 절차
* TODO (2026-04-19): Context-budget 가드 구현 — `/needs`·`/sp-plan` 실행 시 예상 토큰 경고 출력. gstack-plan(~10k+) vs sp-plan(~3k) 사전 안내로 compact 재발 방지. 구현 난이도 M. 1개월 실사용 후 재평가.
* TODO (2026-04-19): SP 사용 로그 수집 — `~/.claude/sp-usage.jsonl`에 SP 스킬 호출 기록(hook 활용). 1개월 후 호출 빈도 기반 추가 브리지 SCAR 결정. 관찰 기간 필요하므로 독립 진행.
* TODO (Issue4 진행중): `_doc_arch/nptir-triage-design.md` 작성 완료 후 `/issue-reg-g`로 이슈 번호 발급 + `/issue-closer-g` 실행.
