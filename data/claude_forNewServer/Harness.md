---
name: Harness
description: 서버 글로벌 SCAR 인덱스 (General + Web 레이어, macOS 앱 제외)
date: 2026-04-28
---

# Harness Define

* global General (공통) : g
* global Domain(분야)
    - Web : w
* local Project (프로젝트 로컬) : suffix 없음
* {스킬} → {스킬}-{도메인서픽스} → {스킬}-g
* cf) SCAR(Skills, Commands, Agents, Rules)

```
┌─────────────────────────────────────────────────────────┐
│               Commands (Local 커맨드)                   │
├──────────────────┬──────────────────┬───────────────────┤
│ /issue-reg-{w}   │ /issue-fix-{w}   │ /issue-closer-{w} │
│      ↓ -g 참조   │      ↓ -g 참조   │      ↓ -g 참조    │
│ /issue-reg-g     │ /issue-fix-g     │ /issue-closer-g   │
└────────┬─────────┴────────┬─────────┴─────────┬─────────┘
         │                  │                   │
         ▼                  ▼                   ▼
┌─────────────────────────────────────────────────────────┐
│              Domain Skills (도메인 스킬)                │
├─────────────────┬─────────────────────────────────────  │
│ issue-w         │ dev-w                                 │
└────────┬────────┴────────┬────────────────────────────  ┘
         │                 │
         ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│              General Skills (공통)                      │
├─────────────────┬──────────────────┬────────────────────┤
│ issue-g         │ dev-g            │                    │
└─────────────────┴──────────────────┴────────────────────┘
```

# global

## General Layer

* dev-g
* issue-g
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* scrap
    - /scrap
* nPTiR 진입 (needs 단계)
    - /needs          (R1 라우팅: brainstorming 또는 writing-plans)
    - /sp-plan        (writing-plans 직행)
* gstack ↔ nPTiR 브리지
    - /gstack-plan
    - /gstack-report
    - /gstack-retro-report
* 설계 SSOT 관리 (_doc_arch 운영)
    - /design-doc
* doc-work-archive (_doc_work z_done 주기 아카이브 스킬)
* git

## Web Layer

* dev-w
* issue-w
    - /issue-reg-w
    - /issue-fix-w
    - /issue-closer-w

# local (프로젝트별 로컬 커맨드)

도메인 기호 `{d}` (`w`|`g`) 플레이스홀더.

* dev
* issue
    - /issue-reg-{d}
    - /issue-fix-{d}
    - /issue-closer-{d}
