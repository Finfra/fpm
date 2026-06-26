---
name: issue-reg
title: issue-reg
description: "이슈 등록 (분석 -> ID 발급 -> Issue.md 업데이트)"
date: 2026-03-28
---

> 글로벌 `/issue-reg-g` 커맨드가 있습니다. 본 로컬 커맨드는 ___pm 프로젝트 특화 절차(HWM·헬퍼 함수) 적용 후 필요 시 `-g` 버전에 위임합니다.

**역할**: 새로운 이슈를 `Issue.md`에 등록합니다.

> [!IMPORTANT]
> **등록 및 계획 전담 원칙**: 이 워크플로우는 이슈를 정식 ID로 등록하고 **계획(Planning)**을 수립하는 작업까지만 수행합니다.
> 사용자가 명시적으로 해결(Fix)을 요청하기 전까지는 **절대로 구현으로 진입하지 않습니다.**

# 사전 준비

헬퍼 함수 로드:
```bash
source ~/.bin/issue-helper.sh
```

# 워크플로우 단계

0. **분석 및 계획 (필수)**
   - 기존 코드 확인, 설정 확인, 규칙 대조
   - 가정 금지: 확인된 사실(Fact) 기반으로 계획 수립
   - **구체적 설계 포함 (필수)**:
     - **Bad**: "스크립트 수정"
     - **Good**: "`projects/` 디렉토리에 새 인덱스 파일 추가 및 README.md 매핑 테이블 업데이트"
   - 이슈 후보 섹션에 유사 항목이 있다면 등록 전 삭제

1. **다음 이슈 ID 생성**:
   ```bash
   NEXT_ID=$(issue_next_id)  # 예: Issue4
   DATE=$(issue_get_current_date)
   ```

2. **이슈 등록** (`Issue.md` 직접 편집):
   - `# 📙 일반` (또는 `# 📕 중요` / `# 📘 선택`) 섹션에 추가
   - 형식:
     ```markdown
     ## $NEXT_ID: [이슈 제목] (등록: $DATE)
     * 목적: 이슈의 목적을 한 줄로 요약
     * 상세:
         - 상세 구현 계획 1
         - 상세 구현 계획 2
     ```
   - HWM 업데이트:
     ```bash
     issue_update_hwm ${NEXT_ID#Issue}  # Issue4 → 4
     ```

3. **등록 확인**: `Issue.md`에 정상 반영 확인. 코드 수정/종결 금지.

4. **후보 정리**: `# 🌱 이슈후보`에서 등록된 항목 삭제

5. **Git 저장**:
   ```bash
   git add Issue.md
   git commit -m "Docs: Register $NEXT_ID"
   ```

6. **종료**: 이슈 등록 완료 후 **즉시 종료**. `/issue-fix`로 자동 진행 금지.



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
