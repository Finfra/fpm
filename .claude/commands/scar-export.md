---
name: scar-export
description: fPm SCAR(fpm-core) → Cursor·Codex·Gemini 포맷 단방향 export (AGENTS.md/GEMINI.md/.cursor/rules)
date: 2026-06-28
---

# /scar-export — SCAR 크로스툴 export

fPm 의 SCAR(Skill/Command/Agent/Rule) 자산을 타 AI 코딩 툴 포맷으로 단방향 export. fpm-core 번들이 SSOT, 타 툴은 미러 소비처.

설계 SSOT: `_doc_work/plan/scar-crosstool-export_plan.md` · 이슈: Issue234(T7)

# 사용법

```bash
scripts/scar-export.sh [--target codex|gemini|cursor|all] [--out DIR] [--full]
```

| 옵션 | 기본 | 설명 |
| :--- | :--- | :--- |
| `--target` | `all` | codex(AGENTS.md) / gemini(GEMINI.md) / cursor(.cursor/rules/*.mdc) / all |
| `--out` | `_export` | 출력 디렉토리 |
| `--full` | off | 본문 전체 포함(기본 description 중심, cursor 는 항상 full) |

# 타깃 포맷

| 타깃 | 출력 | 형식 |
| :--- | :--- | :--- |
| Codex | `AGENTS.md` | 단일 concat — Commands/Skills/Agents 섹션별 `## name` + description |
| Gemini | `GEMINI.md` | AGENTS.md 동일 본문 |
| Cursor | `.cursor/rules/{name}.mdc` | 항목별 frontmatter(`description`·`globs`·`alwaysApply:false`) + body. 이름 충돌 시 `-{kind}` 접미사 |

# 대상 SCAR

`plugins/fpm-core/` 의 commands·skills·agents(.md frontmatter 보유분). hooks·services·vscode-ext 제외.

# 불변식

* **단방향(export-only)** — fpm-core 불변, 출력 디렉토리만 생성. 타 툴 편집 흡수 없음.
* **결정론적** — frontmatter `name`/`description` + 본문 추출. 항목 수 = 출력 수(cursor) 보존.
* **충돌 분리** — 같은 name 이 여러 kind 에 있으면 `.mdc` 파일명에 `-{kind}` 접미사(데이터 손실 방지).

# 구성 요소

* `scripts/scar-export.sh` — 진입점 wrapper
* `scripts/scar-export/scan.py` — fpm-core SCAR → 항목 리스트(frontmatter+body)
* `scripts/scar-export/emit.py` — 항목 → codex/gemini/cursor emitter

# Opus 4.8 실행 제약

* export 는 읽기 전용 + 출력 디렉토리만 생성. fpm-core 수정 금지.
* 단방향 — 라운드트립·import 로직 범위 외.
