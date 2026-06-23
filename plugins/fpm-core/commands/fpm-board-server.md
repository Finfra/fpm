---
name: fpm-board-server
description: "[DEPRECATED Issue190] hub 서버 lifecycle wrapper. /fpm-hub-server 로 통합됨 — 이 별칭은 하위호환용으로 동일 동작 위임"
date: 2026-06-24
---

> ⚠️ **글로벌 SCAR 변경 가드 (Issue46)**: 본 커맨드는 모든 프로젝트가 공유. cwd ≠ `~/.claude/` 면 즉시 수정 금지 → `~/.claude/Issue.md` 이슈 등록 후 처리. 절차: `~/.claude/rules/global-scar-change-rules.md`

# DEPRECATED (Issue190)

`/fpm-board-server` 는 **`/fpm-hub-server` 로 통합·폐기**되었습니다. 데몬은 hub 서버(a/b/c 3모드 + Q&A 공통)이고 board 는 한 클라이언트일 뿐이므로 명칭을 hub 기준으로 통일했습니다.

* 신규 canonical: `/fpm-hub-server <start|stop|restart|status|clear|reset>`
* 로컬 짧은 별칭(___pm): `/hub`

본 별칭은 **당분간 하위호환용으로 잔존**하며, 호출 시 `/fpm-hub-server` 와 **동일하게 동작**합니다 (동일 단일 데몬 `${CLAUDE_PLUGIN_ROOT}/services/hub/server.py`, port 9876 대상).

# 동작

`/fpm-board-server <subcmd>` 호출 시 `/fpm-hub-server <subcmd>` 의 동작을 그대로 수행합니다. 서브커맨드·구현 명세·Endpoints 는 모두 [`fpm-hub-server.md`](fpm-hub-server.md) 를 따릅니다.

지원 서브커맨드: `start` / `stop` / `restart` / `status` / `clear` / `reset` (`/fpm-hub-server` 합집합과 동일).

# 참조

* 신규 canonical: [`fpm-hub-server.md`](fpm-hub-server.md)
* 설계 SSOT: `~/_git/___pm/_doc_arch/hub_htm.md`
* 통합 이슈: `~/_git/___pm/Issue.md` Issue190
