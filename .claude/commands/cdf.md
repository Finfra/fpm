---
name: cdf
description: "pm tmux 세션의 window/pane을 생성·관리하고 명령을 전달함"
date: 2026-04-04
---

인자: $ARGUMENTS

# 라우팅

query 모드(`: ` 자연어)는 Claude 스킬에 위임, 그 외는 `cdft()` 직접 실행.

```bash
# query 모드 판별 (': ' 콜론+공백 패턴)
if echo "$ARGUMENTS" | /usr/bin/grep -qE '(^|[[:space:]]): .'; then
  echo "query 모드 → 스킬 위임"
else
  # cdft 직접 실행
  cdft $ARGUMENTS
fi
```

query 모드인 경우에만 로컬 스킬 `cdf`(`.claude/skills/cdf/index.md`)에 위임.



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
