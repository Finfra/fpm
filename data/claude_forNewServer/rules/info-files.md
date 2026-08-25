---
name: info-files
description: ~/.claude 정보 파일 목록 및 관리 방식
date: 2026-04-14
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: passive** — 런타임 집행 없음. memory 저장 시 동반 append 를 검사하는 hook 이 없다.
> 📚 **분류: 사실** — 어느 파일이 무슨 용도인지의 **목록**. 규칙이 아니라 환경 정보

# 정보 파일 목록

| 파일 | 용도 | 관리 방식 |
| :--- | :--- | :--- |
| `~/.claude/past_prompts.md` | 의미 있는 프롬프트 기록 | Stop hook(save-prompt.sh) 자동 append — Claude 직접 쓰지 않음 |
| `~/.claude/knowledge_base.md` | 일반 지식·팁·요령 | auto-memory `reference` 타입 저장 시 함께 append |
| `~/.claude/learning_log.md` | 학습 내용·인사이트 | auto-memory `feedback` 타입 저장 시 함께 append |
| `~/.claude/instincts.md` | 행동 패턴 요약 | `/sync-instincts` 커맨드로 homunculus 동기화 — Claude 직접 쓰지 않음 |

# 저장 규칙

* `feedback` 타입 저장 시: memory 파일 저장 + `learning_log.md` 한 줄 append
    - 형식: `* YYYY-MM-DD: {규칙 요약}`
* `reference` 타입 저장 시: memory 파일 저장 + `knowledge_base.md` 한 줄 append
    - 형식: `* YYYY-MM-DD [{출처}]: {내용}`
* `past_prompts.md`, `instincts.md` 는 자동화로만 관리 (Claude가 직접 쓰지 않음)
