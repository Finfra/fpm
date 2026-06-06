---
name: fapp-push
description: "fApp 프로젝트 일괄 배포 및 push 커맨드"
date: 2026-03-30
---

인자: $ARGUMENTS

fApp pane 생성 후 상태별 CMD 라우팅:
* IDLE → `claude "/deploy" --dangerously-skip-permissions` 직접 실행
* CLAUDE → `/deploy` 슬래시 커맨드 전달

```
/cdf-fapp $ARGUMENTS --- claude "/deploy" --dangerously-skip-permissions
```



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
