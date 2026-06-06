---
name: issue-reg-g
description: "프로젝트 범용 이슈 등록 공통 절차 (HWM 확인 -> ID 발급 -> 파일 업데이트). issue-reg-m, issue-reg-w에서 참조"
date: 2026-03-30
---

# /issue-reg-g - 이슈 등록 (공통)

새로운 이슈를 `Issue.md`에 등록함. **등록 및 계획만 수행** — 사용자 확인 없이 구현으로 넘어가지 않음.
이 문서는 `/issue-reg-m`, `/issue-reg-w`의 공통 절차를 정의.

## 절차

### 0. 분석 및 triage 판정 (필수)

- 관련 파일 확인 (프로젝트 구조에 맞게)
- 프로젝트 규칙 대조 (`.claude/rules/` 등)
- 구체적 구현 계획 수립 (모호한 표현 금지)
- **복잡도 triage 판정** (규칙: `rules/nptir-rules.md # 이슈 복잡도 triage`):
    - Q1: 변경 파일 3개 이하 + 방법 자명 → 단순 (plan/task 생성 금지, 사용자 요청 시만 예외)
    - Q1 No + Q2 No (후속 영향 없음) → 중간 (plan 권장, 사용자에게 확인)
    - Q1 No + Q2 Yes (후속 영향 있음) → 복잡 (plan+task 필수)

### 1. 프로세스 규칙 검증

- 제목/내용 한국어 작성 (전문 용어 예외)
- `* 목적`, `* 상세` 섹션 포함
- 상세 서브 불렛 4칸 들여쓰기
- 플랫폼별 이슈 카테고리 분류 (각 `-m`/`-w` 커맨드 참조)

### 2. HWM 확인

프로젝트에 `issue-hwm` 스크립트가 있으면 활용:
```bash
python3 .claude/skills/issue-hwm/scripts/issue-hwm.py sync --file "Issue.md"
```

스크립트가 없으면 `Issue.md`를 직접 읽어 현재 가장 높은 이슈 번호를 파악하고 +1로 새 ID 결정.

### 3. 이슈 등록

> **`issue-g` 스킬 참조** → 이슈 등록 형식 및 HWM 업데이트

프로젝트에 `issue-manager` 스크립트가 있으면 활용:
```bash
python3 .claude/skills/issue-manager/scripts/issue-manager.py register \
  --title "[제목]" \
  --type normal \
  --purpose "목적 한 줄" \
  --detail "- 상세 1\n- 상세 2" \
  --file "Issue.md"
```

스크립트가 없으면 `Edit` 도구로 직접 `Issue.md` 편집.

### 3-1. plan/task 파일 연결 (있을 경우)

`_doc_work/plan/` 및 `_doc_work/tasks/`에서 이 이슈와 관련된 파일을 Glob으로 탐색:

```
_doc_work/plan/{주제}_plan.md
_doc_work/tasks/{주제}_task.md
```

파일 발견 시:
1. Issue.md 해당 이슈 항목에 `* plan:`, `* task:` 경로 필드 추가 (`* 목적:` 바로 아래)
2. 발견된 plan/task 파일의 frontmatter `issue: TBD` → `issue: Issue[번호]`로 업데이트

### 4. 이슈 내용 보강

`Issue.md` 열람 후 `* 목적:` 및 `* 상세:` 항목을 Edit 도구로 구체적으로 작성. 빈칸 금지.

### 5. Git 저장

```bash
git add Issue.md
git commit -m "Docs: Issue[번호] 등록 — [제목]"
```

> 🚨 **등록 완료 후 즉시 작업 종료** — `/issue-fix-{m|w}`로 자동 진행 금지

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석
