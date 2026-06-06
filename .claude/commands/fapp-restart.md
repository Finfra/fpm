---
title: "FAPP-RESTART: fApp 프로세스 종료 후 재실행"
description: "fApp 프로세스 종료 후 재실행 커맨드"
date: 2026-03-29
---

인자: $ARGUMENTS

# 실행 지시

## Step 1: fApp 종료

```
/fapp-kill
```

## Step 2: fApp 실행

```
/fapp-run
```

## Step 3: 완료 보고

```bash
say "fApp restart complete"
```

# 주의사항
* `/fapp-kill` 완료 후 `/fapp-run` 실행 (순차)
* 스킬 fapp 참조



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
