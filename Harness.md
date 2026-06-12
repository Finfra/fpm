---
name: Harness
description: Document
date: 2026-04-18
---

# 관련 문서

* `_doc_arch/Harness/Harness.md` — Harness 상세 설계
* `_doc_arch/Harness/harness_architecture.mermaid` — 아키텍처 다이어그램
* `_doc_arch/Harness/fapps-shared-tech.excalidraw` — fApp 공유 기술 다이어그램

# Harness Define
* global General (공통) : g
* global Domain(분야)
   - Web         : w
   - Macapp      : m
   - CliApp      : c (향후 구현)
   - Exe(window) : e (향후 구현)
* local Project (프로젝트 로컬) : suffix 없음
* {스킬} → {스킬}-{도메인서픽스} → {스킬}-g
* cf) SCAR(Skills, Commands, Agents, Rules)

```
┌─────────────────────────────────────────────────────────────────┐
│                   Commands (Local 커맨드)                       │
├──────────────────┬──────────────────┬───────────────────────────┤
│ /issue-reg-{m|w} │ /issue-fix-{m|w} │ /issue-closer-{m|w}       │
│      ↓ -g 참조   │      ↓ -g 참조   │      ↓ -g 참조            │
│ /issue-reg-g     │ /issue-fix-g     │ /issue-closer-g           │
└────────┬─────────┴────────┬─────────┴─────────┬─────────────────┘
         │                  │                   │
         ▼                  ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Project Skills (프로젝트 로컬)                │
├─────────────────┬──────────────────┬────────────────────────────┤
│ skill: "issue"  │ skill: "dev"     │ skill: "capture"           │
│  ├─ issue-hwm   │                  │                            │
│  ├─ issue-mgr   │                  │                            │
│  └─ save-point  │                  │                            │
└────────┬────────┴────────┬─────────┴──────────┬─────────────────┘
         │                 │                    │
         ▼                 ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Domain Skills (도메인 스킬)                   │
├─────────────────┬─────────────────┬─────────────────────────────┤
│ issue-w/m/c/e   │ dev-w/m/c/e     │ capture-w    capture-m      │
│                 │                 │ (Playwright) (screencapture)│
│                 │                 │ deploy-m                    │
└────────┬────────┴────────┬────────┴───────────┬─────────────────┘
         │                 │                    │
         ▼                 ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                   General Skills (공통)                         │
├─────────────────┬──────────────────┬────────────────────────────┤
│ issue-g         │ dev-g            │ capture-g                  │
└─────────────────┴──────────────────┴────────────────────────────┘
```

# global
## General Layer
* dev-g
* issue-g
  - /issue-reg-g
  - /issue-fix-g
  - /issue-closer-g
* capture-g
* fcapture
* scrap
  - /scrap
  - agent: `scrap`
  - 저장 경로: `~/_doc/scrap/{제목}/` (절대 경로)
* nPTiR 진입 (needs 단계)
  - /needs          (R1 라우팅: superpowers:brainstorming 또는 writing-plans)
  - /sp-plan        (writing-plans 직행)
* gstack ↔ nPTiR 브리지
  - /gstack-plan
  - /gstack-report
  - /gstack-retro-report
* 설계 SSOT 관리 (_doc_arch 운영)
  - /design-doc
  - rule: doc-design-rules
* doc-work-archive (_doc_work z_done 주기 아카이브 스킬)
* graphify (지식 그래프 활용 — 토큰 절감)
  - /graphify          (upstream CLI 래퍼, 그래프 빌드)
  - /graphify-prune    (GRAPH_REPORT.md → brief.md 50줄 압축)
  - /graphify-setup    (프로젝트 우선 활용 표준 4종 설정 자동 적용)
  - /graphify-brief    (주제 키워드 50줄 종합 요약 질의)
  - /gq                (graphify query 래퍼)
  - rule: `~/.claude/rules/graphify-rules.md` (토큰 절감 정책 SSOT)
  - arch SSOT: `~/_git/___pm/_doc_arch/graphify-priority-setup.md` (graphify-setup 적용 기준)
  - 도구 매뉴얼: `~/_doc/3.Resource/_LLM/Claude/_Harness/graphify.md`
* pm-do (prj간 명령 위임 + 동기 블로킹 + 의존성 자동 해결)
  - /pm-do
  - wrapper: `~/.bin/pm-do` (CLI 진입점, bash 호출용)
  - rule: issue-g `* depends: prj<N>#Issue<M>` 필드 의존
  - 메커니즘: cdf로 pm tmux pane 확보 → Claude 부팅(필요 시) → 명령 전달 → Issue.md `✅ 완료` polling → commit hash 회수
  - SSOT: `~/_git/___pm/projects/<번호>`(경로), `~/_git/___pm/Projects.md`(Domain)
* htm (HTML 렌더 + 양방향 Q&A + Live Dashboard, Issue18~24)
  - `..show` (a모드, 구 `..hub`) / `/htm` — 응답을 HTML 문서로 Firefox 표시 (단방향 렌더)
  - `..ask` (b모드, Issue126 신설) — 양방향 Q&A 폼 → server inbox 자동 회수
  - `..board` (c모드, Issue126) — Live Dashboard (SSE + polling fallback). 구 `..hub dash`/`..dashboard` 별칭 하위호환 유지
  - `..hub stop` / `..hub off` — 모드 해제
  - `/dashboard-server start|stop|status|restart` — b/c모드 백엔드 lifecycle 제어
  - 3-mode (트리거 ↔ content_type, Issue126):
    * a모드 `..show` (`response`, 구 `..hub`) — HTML 렌더 (Issue45 이후 file:// 직접 표시)
    * b모드 `..ask` (`form`) — fetch POST + server inbox + Claude polling 자동 회수
    * c모드 `..board` (`dashboard`) — Live Dashboard (data 파일만 수정 → SSE push → 자동 갱신)
  - 자원 격리: `md5(cwd)[:8]` → PORT 9876+hash%100, STATE/INBOX/HASH별 폴더
  - 출력 경로: `_doc_work/z_htm/` 존재 시 영속, else `/tmp` fallback
  - 데이터 패턴: `*.htm.{yaml,json}`, `*.dash.{yaml,json}`, `_doc_work/z_htm/*.{yaml,yml,json}`
  - 관련 산출물:
    * skill: `~/.claude/skills/htm-server/` (Python stdlib HTTP+SSE)
    * commands: `/htm`, `/htm-server`
    * hooks:
        - `htm-trigger.sh` (UserPromptSubmit, `..show`(구 `..hub`) 트리거)
        - `htm-ask-intercept.sh` (PreToolUse AskUserQuestion, 트리거 무관 단일 form 회수 — `..show`/`..ask`/자동)
        - `htm-dash-notify.sh` (PostToolUse Edit|Write|MultiEdit, c모드 SSE notify)
    * arch SSOT: `~/.claude/_doc_arch/htm-mode-arch.md`

## Spec Layer
* dev-w
* dev-m
* deploy-m
* issue-w
  - /issue-reg-w
  - /issue-fix-w
  - /issue-closer-w
* issue-m
  - /issue-reg-m
  - /issue-fix-m
  - /issue-closer-m

# local (프로젝트별 로컬 커맨드 · suffix는 프로젝트 도메인 따름)

도메인 기호 `{d}` (`w`|`m`|`c`|`e`) 플레이스홀더. `g` 도메인 프로젝트는 suffix 없이 직접 호출하거나 글로벌 `-g` 위임.

* dev
* issue
    - /issue-reg-{d}
    - /issue-fix-{d}
    - /issue-closer-{d}
* capture
* capture-ui-list (m 도메인 전용: 맥 개발 UI 캡처 리스트 관리)

# ___pm / fpm

PM 도구 프로젝트 쌍. `___pm`(prj1) = 개발 원본 SSOT, `fpm`(prj7, `~/_git/__all/fpm`) = 공개 마켓플레이스 배포판. `fpm-sync` 스킬·agent 로 ___pm ↔ fpm 동기화(기본 forward, 역방향 reverse·배포 deploy·정책 policy 통합 — Issue158). `scripts/fpm-sync.sh <forward|deploy|reverse|policy>` 단일 dispatcher, 개인정보 가드는 결정성 sh 헬퍼.

## ___pm 로컬 SCAR (g 도메인 — 로컬 진입 → 글로벌 `-g` 위임)

### 프로젝트 관리 (pm)
* skill: `pm` (생성·삭제·업데이트·조회 공통 로직)
* commands (글로벌 `~/.claude/commands/`):
    - /pm-new      프로젝트 타입별 초기화 (general/web/mac)
    - /pm-del      안전 제거 (backup/done/keep)
    - /pm-update   기존 프로젝트 SCAR·템플릿 최신화
    - /pm-query    조회·검색
    - /pm-do       prj간 명령 위임 + 동기 블로킹 + `* depends:` 자동 해결
* SSOT: `projects/<번호>`(경로), `Projects.md`(Domain)

### 디렉토리 이동·tmux (cdf)
* skill: `cdf` (pm tmux window/pane 생성·명령 전달)
* commands: /cdf · /cdf-fapp · /cdf-ma · /cdf-fapp-ma
* shell func (`~/.zsh_functions`): cdf · cdff(Finder) · cdfc(clipboard) · cdfv(VSCode)

### fApp 일괄 관리 (fapp, prj 11~16·25·26)
* skill: `fapp` (상태 인식 CMD 라우팅)
* agents: `fapp-parallel`(병렬) · `fapp-serial`(순차)
* commands: /fapp-build · /fapp-run(-ma) · /fapp-kill(-ma) · /fapp-pull(-ma) · /fapp-push · /fapp-capture(-ma) · /fapp-restart · /fapp-parallel · /fapp-serial

### 개발·이슈 (로컬 진입 → -g 위임)
* /dev — → dev-g
* skill: `issue` → issue-*-g
    - /issue-reg · /issue-fix · /issue-closer

### 동기화 (sync)
* skill: `sync-ma` (jm4 → ma)
* commands: /sync-ma · /sync-jma (jm4 ↔ jma 양방향 rsync)

### 유틸
* /peacock-sync — Projects.md peacock.color ↔ .vscode/settings.json
* /server-check — Servers.md SSH 서버 상태
* /vscode-projects-update — Projects.md ↔ 각 프로젝트 .vscode 갱신
* /gq · /graphify-prune — graphify 보조

### rules
* graphify-rules · issue-rules

## fpm — 마켓플레이스 배포판 (prj7, `~/_git/__all/fpm`)

글로벌 `~/.claude` 의 hub/dashboard + pm/cdf SCAR 를 Claude Code 플러그인으로 번들 설치하는 공개판.

* marketplace: `.claude-plugin/marketplace.json` → plugin `fpm-core`
* fpm-core 번들:
    - commands: pm-new/del/do/query/update · cdf · hub · dashboard · dashboard-server
    - skills: pm · cdf
    - agents: dashboard (+ runner·queue·supervisor 스크립트)
    - hooks: hub-trigger · ask-intercept · ask-form-template · board-notify · hub-doc-register · hub-session-* · ask-*
    - services: hub (Python stdlib HTTP+SSE 서버)
* 동기화: `fpm-sync` 스킬/agent — ___pm(원본) ↔ fpm(공개판). dispatcher `scripts/fpm-sync.sh <forward|deploy|reverse|policy>`
    - forward(기본·hook 자동) / deploy(버전 bump+tag+push) / reverse(되돌리기, 동의 후 `--apply`) / policy(공개 정책 편집)
    - 결정성 헬퍼: `fpm-policy-lib.sh`(파서) · `fpm-guard.sh`(개인정보 abort) · `fpm-sanitize.sh`(치환)
    - 구 `fpm-deploy.sh`·`publishable` 스킬 → deprecated shim (Issue158)
* 라이선스: 듀얼 (개인 무료 / 기업 유료) — `COMMERCIAL.md`

# fCapture
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* qa
* save-point-update

# videoMaker
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# m2slide (g 도메인, Prj41 videoMaker 라이브러리)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# tts (g 도메인, Prj41 videoMaker 라이브러리)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# work-exampleProj
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# social (w 도메인)
## main
* dev
* issue
    - /issue-reg-w
    - /issue-fix-w
    - /issue-closer-w
* capture

# ollamaClaude (g 도메인, 외주)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# 02.01_AgenticCoding (g 도메인, 강의자료)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# GenContentProd (g 도메인, 강의자료)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# LlmFlow (g 도메인, 강의자료)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture


