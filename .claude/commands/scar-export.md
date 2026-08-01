---
name: scar-export
description: fpm-core SCAR → Cursor·Codex·Gemini 포맷 단방향 export (글로벌 scar-export 스킬 위임 wrapper, --source 고정)
date: 2026-07-15
---

# /scar-export — 글로벌 `scar-export` 스킬 위임 (fpm-core 고정)

prj1 자체 구현(`scripts/scar-export/*`)은 Issue229_2(prj3)로 `~/.claude/skills/scar-export/`에 승격되어 `--source DIR` 인자화됨. 본 커맨드는 prj1 고유 유스케이스(`plugins/fpm-core` export)를 고정 인자로 넘기는 wrapper.

# 사용법

```bash
~/.claude/skills/scar-export/scripts/scar-export.sh --source plugins/fpm-core $ARGUMENTS
```

ex) `/scar-export --target codex`, `/scar-export --target all --full`

`--source` 를 다른 디렉토리로 바꿔야 하면 wrapper 거치지 말고 글로벌 스크립트를 직접 호출할 것.

상세 스펙(타깃 포맷·불변식·구성 요소)은 [`~/.claude/skills/scar-export/SKILL.md`](~/.claude/skills/scar-export/SKILL.md) 참조.

# 참조

* 설계 SSOT: `_doc_work/z_done/plan/scar-crosstool-export_plan.md` · 이슈: Issue234(T7, 최초 구현) → Issue281_2(본 wrapper화)
