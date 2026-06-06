---
name: issue-hwm
description: "이슈 파일의 HWM(High Water Mark)을 검사하고 실제 데이터와 동기화합니다."
title: issue-hwm
date: 2026-03-27
---

# Issue HWM Manager Skill

`Issue.md`의 HWM(최고 이슈 번호)이 실제 이슈 내역과 일치하지 않는 문제를 해결합니다.
**Self-Healing** 메커니즘을 통해 모든 이슈 번호를 스캔하고, 헤더의 HWM 값이 실제보다 낮으면 자동 업데이트합니다.

## 사용법

```bash
python3 .agent/skills/issue-hwm/scripts/issue-hwm.py sync --file "Issue.md"
```

## 워크플로우 통합

주로 `/issue-reg`의 **Pre-flight Check** 단계에서 사용됩니다.
