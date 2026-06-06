---
name: new-project
description: 새 프로젝트 nPTiR 기본 구조 초기화
date: 2026-04-28
---

새 프로젝트의 nPTiR·SCAR 기본 구조를 초기화함.

## 실행 절차

인자가 없으면 아래 안내를 출력하고 중단:

```
Usage: /new-project <프로젝트명> [경로]

예시:
  /new-project myTool
  /new-project myWeb ~/projects/myWeb
```

인자가 있으면 아래 순서로 진행:

### 1. 대상 경로 확정

* `경로` 인자 있으면 해당 경로 사용
* 없으면 현재 디렉토리(`pwd`) 또는 사용자에게 확인

### 2. 필수 파일·폴더 생성

```
{프로젝트루트}/
├── Issue.md
├── CLAUDE.md
├── noteForHuman.md
├── PROMPTS.md
├── Harness.md
├── .claude/
│   ├── commands/
│   ├── rules/
│   └── skills/
├── _doc_work/
│   ├── plan/
│   ├── tasks/
│   ├── report/
│   └── z_done/
└── _doc_arch/
```

### 3. 파일 내용 초기화

**Issue.md**:

```markdown
---
title: {프로젝트명} Issue
description: {프로젝트명} 이슈 관리
date: {YYYY-MM-DD}
---

# Issue Management
* Issue HWM: 0

# 🤔 결정사항

# 🌱 이슈후보

# 🚧 진행중

# 📕 중요

# 📙 일반

# 📘 선택

# ✅ 완료

# ⏸️ 보류
# 🚫 취소
# 📜 참고
```

**CLAUDE.md**: 글로벌 규칙 참조 한 줄

```markdown
글로벌 규칙(언어·스타일·네이밍·모델·nPTiR)은 `~/.claude/CLAUDE.md` 참조.
```

**noteForHuman.md**: 사람이 읽는 메모 뼈대

**PROMPTS.md**: 자주 쓰는 프롬프트 뼈대

**Harness.md**: 로컬 SCAR 인덱스 (issue-reg-g, issue-fix-g, issue-closer-g 기본 포함)

### 4. 완료 보고

생성된 파일 목록을 출력하고 종료.

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석
