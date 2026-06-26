---
name: issue-fix
title: issue-fix
description: "이슈 해결 및 완료 처리 (Fix -> Verify -> Close) 워크플로우"
date: 2026-03-28
---

> 글로벌 `/issue-fix-g` 커맨드가 있습니다. 본 로컬 커맨드는 ___pm 프로젝트 특화 절차 적용 후 필요 시 `-g` 버전에 위임합니다.

# 사전 준비

헬퍼 함수 로드:
```bash
source ~/.bin/issue-helper.sh
```

# 워크플로우 단계

1. **문제 분석 및 재현**:
   - 이슈의 원인을 분석합니다.
   - `Issue.md`의 해당 이슈 내용을 정확히 파악합니다.

2. **구현**:
   - 코드/설정/문서를 수정합니다.
   - **커밋 메시지 규칙**: `Fix: Issue[번호] [제목]`

3. **검증**:
   - 변경된 스크립트/설정이 정상 동작하는지 확인
   - 관련 함수, 설정 파일 등 영향 범위 점검

4. **이슈 종결**:
   - **`/issue-closer` 워크플로우를 실행합니다.**



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
