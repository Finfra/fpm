---
name: Harness
description: Document
date: 2026-04-18
---

> 🌐 **English** | [한국어](Harness_ko.md)

# Related Documents

* `_doc_arch/scar-layering-design.md` — **SCAR layering DESIGN SSOT** (suffix system, reference direction, responsibility split, layering decision criteria). This document is the WHY/HOW; the present file is the WHAT.
* `_doc_arch/Harness/Harness.md` — Harness detailed design
* `_doc_arch/Harness/harness_architecture.mermaid` — architecture diagram
* `_doc_arch/Harness/fapps-shared-tech.excalidraw` — fApp shared-tech diagram

# Harness Define

> **Role separation (Issue165)**: This file = **catalog** (the actual SCAR instances + per-project mapping). The layering design rationale (suffix system, reference direction, decision criteria) lives in `_doc_arch/scar-layering-design.md` (SSOT). The legend + diagram below are kept only as a navigation aid — do not duplicate design prose here.

* global General (common) : g
* global Domain
   - Web         : w
   - Macapp      : m
   - CliApp      : c (planned)
   - Exe(window) : e (planned)
* local Project (project-local) : no suffix
* {skill} → {skill}-{domain suffix} → {skill}-g
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
  - storage path: `~/_doc/scrap/{title}/` (absolute path)
* nPTiR entry (needs stage)
  - /needs          (R1 routing: superpowers:brainstorming or writing-plans)
  - /sp-plan        (writing-plans direct)
* design SSOT management (_doc_arch operations)
  - /design-doc
  - rule: doc-design-rules
* doc-work-archive (_doc_work z_done periodic archive skill)
* graphify (knowledge graph usage — token savings)
  - /graphify          (upstream CLI wrapper, graph build)
  - /graphify-prune    (GRAPH_REPORT.md → brief.md 50-line compression)
  - /graphify-setup    (auto-apply the 4 standard priority-usage settings to a project)
  - /graphify-brief    (topic-keyword 50-line summary query)
  - /gq                (graphify query wrapper)
  - rule: `~/.claude/rules/graphify-rules.md` (token-savings policy SSOT)
  - arch SSOT: `~/_git/___pm/_doc_arch/graphify-priority-setup.md` (graphify-setup application criteria)
  - tool manual: `~/_doc/3.Resource/_LLM/Claude/_Harness/graphify.md`
* pm-do (cross-prj command delegation + synchronous blocking + automatic dependency resolution)
  - /pm-do
  - wrapper: `~/.bin/pm-do` (CLI entry point, for bash invocation)
  - rule: depends on the issue-g `* depends: prj<N>#Issue<M>` field
  - mechanism: secure a pm tmux pane via cdf → boot Claude (if needed) → send command → poll Issue.md `✅ 완료` → retrieve commit hash
  - SSOT: `~/_git/___pm/projects/<number>` (path), `~/_git/___pm/Projects.md` (Domain)
* htm (HTML render + bidirectional Q&A + Live Dashboard, Issue18~24)
  - `..show` (mode a, formerly `..hub`) / `/htm` — render the response as an HTML document in Firefox (one-way render)
  - `..ask` (mode b, added in Issue126) — bidirectional Q&A form → automatic server inbox retrieval
  - `..board` (mode c, Issue126) — Live Dashboard (SSE + polling fallback). Legacy aliases `..hub dash`/`..dashboard` kept for backward compatibility
  - `..hub stop` / `..hub off` — disable the mode
  - `/fpm-hub-server start|stop|restart|status|clear|reset` — control the b/c-mode backend lifecycle
  - 3-mode (trigger ↔ content_type, Issue126):
    * mode a `..show` (`response`, formerly `..hub`) — HTML render (direct file:// display since Issue45)
    * mode b `..ask` (`form`) — fetch POST + server inbox + automatic Claude polling retrieval
    * mode c `..board` (`dashboard`) — Live Dashboard (edit data files only → SSE push → auto-refresh)
  - resource isolation: `md5(cwd)[:8]` → PORT 9876+hash%100, per-STATE/INBOX/HASH folders
  - output path: persistent if `_doc_work/z_htm/` exists, else `/tmp` fallback
  - data patterns: `*.htm.{yaml,json}`, `*.dash.{yaml,json}`, `_doc_work/z_htm/*.{yaml,yml,json}`
  - related artifacts:
    * skill: `~/.claude/skills/htm-server/` (Python stdlib HTTP+SSE)
    * commands: `/htm`, `/htm-server`
    * hooks:
        - `htm-trigger.sh` (UserPromptSubmit, `..show` (formerly `..hub`) trigger)
        - `htm-ask-intercept.sh` (PreToolUse AskUserQuestion, single-form retrieval regardless of trigger — `..show`/`..ask`/auto)
        - `htm-dash-notify.sh` (PostToolUse Edit|Write|MultiEdit, mode-c SSE notify)
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

# local (per-project local commands · suffix follows the project domain)

The domain symbol `{d}` (`w`|`m`|`c`|`e`) is a placeholder. A `g`-domain project is invoked directly without a suffix, or delegates to the global `-g`.

* dev
* issue
    - /issue-reg-{d}
    - /issue-fix-{d}
    - /issue-closer-{d}
* capture
* capture-ui-list (m-domain only: manages the Mac development UI capture list)

# ___pm / fpm

A pair of PM-tool projects. `___pm` (prj1) = development source SSOT; `fpm` (prj7, `~/_git/__all/fpm`) = public marketplace distribution. The `fpm-sync` skill/agent synchronizes ___pm ↔ fpm (default forward, with reverse rollback · deploy · policy integrated — Issue158). `scripts/fpm-sync.sh <forward|deploy|reverse|policy>` is the single dispatcher; the privacy guard is a deterministic sh helper.

## ___pm local SCAR (g domain — local entry → delegates to global `-g`)

### Project management (pm)
* skill: `pm` (shared create/delete/update/query logic)
* commands (global `~/.claude/commands/`):
    - /pm-new      project-type initialization (general/web/mac)
    - /pm-del      safe removal (backup/done/keep)
    - /pm-update   bring an existing project's SCAR/templates up to date
    - /pm-query    query/search
    - /pm-do       cross-prj command delegation + synchronous blocking + automatic `* depends:` resolution
* SSOT: `projects/<number>` (path), `Projects.md` (Domain)

### Directory navigation · tmux (cdf)
* skill: `cdf` (pm tmux window/pane creation · command dispatch)
* commands: /cdf · /cdf-fapp · /cdf-ma · /cdf-fapp-ma
* shell func (`~/.zsh_functions`): cdf · cdff(Finder) · cdfc(clipboard) · cdfv(VSCode)

### fApp batch management (fapp, prj 11~16·25·26)
* skill: `fapp` (state-aware CMD routing)
* agents: `fapp-parallel` (parallel) · `fapp-serial` (sequential)
* commands: /fapp-build · /fapp-run(-ma) · /fapp-kill(-ma) · /fapp-pull(-ma) · /fapp-push · /fapp-capture(-ma) · /fapp-restart · /fapp-parallel · /fapp-serial

### Development · issues (local entry → -g delegation)
* /dev — → dev-g
* skill: `issue` → issue-*-g
    - /issue-reg · /issue-fix · /issue-closer

### Synchronization (sync)
* skill: `sync-ma` (jm4 → ma)
* commands: /sync-ma · /sync-jma (jm4 ↔ jma bidirectional rsync)

### Utilities
* /peacock-sync — Projects.md peacock.color ↔ .vscode/settings.json
* /server-check — Servers.md SSH server status
* /vscode-projects-update — Projects.md ↔ per-project .vscode update
* /gq · /graphify-prune — graphify helpers

### rules
* graphify-rules · issue-rules

## fpm — marketplace distribution (prj7, `~/_git/__all/fpm`)

The public distribution that bundle-installs the global `~/.claude` hub/dashboard + pm/cdf SCAR as a Claude Code plugin.

* marketplace: `.claude-plugin/marketplace.json` → plugin `fpm-core`
* fpm-core bundle:
    - commands: pm-new/del/do/query/update · cdf · hub · dashboard · hub-server
    - skills: pm · cdf
    - agents: dashboard (+ runner·queue·supervisor scripts)
    - hooks: hub-trigger · ask-intercept · ask-form-template · board-notify · hub-doc-register · hub-session-* · ask-*
    - services: hub (Python stdlib HTTP+SSE server)
* synchronization: `fpm-sync` skill/agent — ___pm (source) ↔ fpm (public). dispatcher `scripts/fpm-sync.sh <forward|deploy|reverse|policy>`
    - forward (default · hook-automatic) / deploy (version bump+tag+push) / reverse (rollback, `--apply` after consent) / policy (edit publication policy)
    - deterministic helpers: `fpm-policy-lib.sh` (parser) · `fpm-guard.sh` (privacy abort) · `fpm-sanitize.sh` (substitution)
    - legacy `fpm-deploy.sh` · `publishable` skill → deprecated shim (Issue158)
* license: dual (free for individuals / paid for enterprises) — `COMMERCIAL.md`

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

# m2slide (g domain, Prj41 videoMaker library)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# tts (g domain, Prj41 videoMaker library)
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

# social (w domain)
## main
* dev
* issue
    - /issue-reg-w
    - /issue-fix-w
    - /issue-closer-w
* capture

# air-gap-claudeCode (g domain, contract work)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# 02.01_AgenticCoding (g domain, course material)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# GenContentProd (g domain, course material)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# LlmFlow (g domain, course material)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture

# test1 (g domain, fpm testing)
## main
* dev
* issue
    - /issue-reg-g
    - /issue-fix-g
    - /issue-closer-g
* capture
