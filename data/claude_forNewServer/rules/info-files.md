---
name: info-files
description: ~/.claude 정보 파일 목록 및 관리 방식
date: 2026-04-28
---

# 정보 파일 목록

| 파일 | 용도 | 관리 방식 |
| :--- | :--- | :--- |
| `~/.claude/knowledge_base.md` | 일반 지식·팁·요령 | auto-memory `reference` 타입 저장 시 함께 append |
| `~/.claude/learning_log.md` | 학습 내용·인사이트 | auto-memory `feedback` 타입 저장 시 함께 append |

# 저장 규칙

* `feedback` 타입 저장 시: memory 파일 저장 + `learning_log.md` 한 줄 append
    - 형식: `* YYYY-MM-DD: {규칙 요약}`
* `reference` 타입 저장 시: memory 파일 저장 + `knowledge_base.md` 한 줄 append
    - 형식: `* YYYY-MM-DD [{출처}]: {내용}`
