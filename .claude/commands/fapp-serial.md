---
name: fapp-serial
description: "fApp 프로젝트 목록을 읽어 커맨드를 순차적으로 실행한 뒤 통합 리포트를 생성합니다."
date: 2026-03-31
---

인자: $ARGUMENTS (실행할 커맨드, ex: "/capture", "/issue")

Agent 도구를 사용하여 `fapp-serial` 서브에이전트를 실행:
* `subagent_type`: `fapp-serial`
* 프롬프트: `$ARGUMENTS 커맨드를 fApp 프로젝트 전체에 순차적으로 실행하세요.`



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
