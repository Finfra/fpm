---
name: gh-sync
description: Issue.md ↔ GitHub Issues 옵트인 브리지 (글로벌 gh-issue-sync 스킬 위임 wrapper)
date: 2026-07-15
---

# /gh-sync — 글로벌 `gh-issue-sync` 스킬 위임

prj1 자체 구현(`scripts/gh-sync/*`)은 Issue229_1(prj3)로 `~/.claude/skills/gh-issue-sync/`에 승격됨. 본 커맨드는 그 글로벌 스크립트를 호출하는 wrapper.

설정 파일: `.claude/gh-sync.yml`(prj1 루트, 구 `data/gh-sync.yml`에서 마이그레이션 — `guard_before_push` → `guard_cmd` 스펙 변경).

# 사용법

```bash
~/.claude/skills/gh-issue-sync/scripts/gh-issue-sync.sh $ARGUMENTS
```

ex) `/gh-sync status`, `/gh-sync push`, `/gh-sync push --apply`, `/gh-sync pull`

상세 스펙(서브커맨드·불변식·필드 매핑)은 [`~/.claude/skills/gh-issue-sync/SKILL.md`](~/.claude/skills/gh-issue-sync/SKILL.md) 참조.

# 참조

* 설계 SSOT: `_doc_work/z_done/plan/gh-issue-bridge_plan.md` · 이슈: Issue233(T6, 최초 구현) → Issue281_1(본 wrapper화)
