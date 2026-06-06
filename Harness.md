---
name: /Users/nowage/_git/___pm/Harness
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
  - `..hub` (a모드) / `/htm` — 응답을 HTML 문서로 Firefox 표시 (단방향 렌더)
  - `..ask` (b모드, Issue126 신설) — 양방향 Q&A 폼 → server inbox 자동 회수
  - `..board` (c모드, Issue126) — Live Dashboard (SSE + polling fallback). 구 `..hub dash`/`..dashboard` 별칭 하위호환 유지
  - `..hub stop` / `..hub off` — 모드 해제
  - `/dashboard-server start|stop|status|restart` — b/c모드 백엔드 lifecycle 제어
  - 3-mode (트리거 ↔ content_type, Issue126):
    * a모드 `..hub` (`response`) — HTML 렌더 (Issue45 이후 file:// 직접 표시)
    * b모드 `..ask` (`form`) — fetch POST + server inbox + Claude polling 자동 회수
    * c모드 `..board` (`dashboard`) — Live Dashboard (data 파일만 수정 → SSE push → 자동 갱신)
  - 자원 격리: `md5(cwd)[:8]` → PORT 9876+hash%100, STATE/INBOX/HASH별 폴더
  - 출력 경로: `_doc_work/z_htm/` 존재 시 영속, else `/tmp` fallback
  - 데이터 패턴: `*.htm.{yaml,json}`, `*.dash.{yaml,json}`, `_doc_work/z_htm/*.{yaml,yml,json}`
  - 관련 산출물:
    * skill: `~/.claude/skills/htm-server/` (Python stdlib HTTP+SSE)
    * commands: `/htm`, `/htm-server`
    * hooks:
        - `htm-trigger.sh` (UserPromptSubmit, `..hub` 트리거)
        - `htm-ask-intercept.sh` (PreToolUse AskUserQuestion, 트리거 무관 단일 form 회수 — `..hub`/`..ask`/자동)
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

# work-cyberTech
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

# ___pm (g 도메인 — 로컬 진입 커맨드 → 글로벌 `-g` 위임 방식)
## main
* dev                  (로컬 `/dev` → `dev-g` 스킬 위임. `.claude/commands/dev.md`)
* issue                (로컬 `/issue-*` → `issue-*-g` 위임. `.claude/commands/issue-*` + `skills/issue`)
    - /issue-reg
    - /issue-fix
    - /issue-closer
* fapp
* cdf
* pm
    - /pm-new
    - /pm-del
    - /pm-update
    - /pm-query
* sync-ma
    - /sync-ma

## extend
* /fapp-*
* /issue-*
* /pm-*
* /cdf-*
* /sync-ma

