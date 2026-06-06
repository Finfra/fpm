---
name: issue-g
description: "모든 프로젝트에서 사용 가능한 이슈 관리 패턴 및 워크플로우"
---

# Issue.md 글로벌 패턴

모든 프로젝트에서 **일관된 이슈 추적 시스템**을 구축하기 위한 글로벌 스킬입니다.

## Issue.md 기본 구조

```markdown
---
title: Project Name Issue
description: [프로젝트] 이슈 관리 파일
date: YYYY-MM-DD
---

# Issue Management
* Issue HWM: N
* 이슈 관리 규칙: `.claude/rules/issue-rules.md` (또는 로컬 링크)
* 오래된 Issue: `[경로]` (필요시)
* Save Point: [커밋 해시] (YYYY-MM-DD)

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

## 핵심 개념

### HWM (High Water Mark)
- **정의**: 현재까지 발급된 가장 높은 이슈 번호
- **위치**: Issue.md 상단 `Issue HWM: N`
- **사용**: 다음 이슈 ID = HWM + 1
- **관리**: 새 이슈 등록 시 HWM 증가

### 이슈 ID 형식
```
Issue1, Issue2, Issue3, ...
```
- 프로젝트 내에서 유일한 정수형 식별자
- 모든 커밋, 문서에서 참조 가능

### 섹션 의미

| 섹션        | 목적                      |
| ----------- | ------------------------- |
| 🤔 결정사항 | 아직 실행 대기 중인 결정  |
| 🌱 이슈후보 | 잠정 이슈 (미정식 등록)   |
| 🚧 진행중   | 현재 작업 중인 이슈       |
| 📕 중요     | 우선순위 높음             |
| 📙 일반     | 표준 우선순위             |
| 📘 선택     | 우선순위 낮음             |
| ✅ 완료     | 해결 + 커밋 해시 기록     |
| ⏸️ 보류     | 일시 중단                 |
| 🚫 취소     | 폐기                      |
| 📜 참고     | 아카이브/참고용           |

## 이슈 등록 형식

```markdown
## Issue[번호]: [제목] (등록: YYYY-MM-DD)
* 목적: 한 줄 요약
* plan: `_doc_work/plan/{주제}_plan.md`   ← 있을 때만
* task: `_doc_work/tasks/{주제}_task.md`   ← 있을 때만
* 상세:
    - 상세 내용 1
    - 상세 내용 2
```

## 이슈 완료 형식

```markdown
## Issue[번호]: [제목] (등록: YYYY-MM-DD, 해결: YYYY-MM-DD, commit: [hash]) ✅
* 목적: 한 줄 요약
* 구현 명세:
    - 변경 로직 1
    - 변경 로직 2
```

## 서브 이슈 형식

부모 이슈의 세부 항목을 추적할 때 사용. 부모 이슈 내에 H3 (`###`)으로 표현:

```markdown
### Issue[N]_[M]: [세부 제목] (등록: YYYY-MM-DD, 해결: YYYY-MM-DD, commit: [hash]) ✅
* 현상: 구체적 현상/증상 설명
* 원인: 근본 원인 분석
* 해결: 실제 적용된 해결책
```

**구조 예시**:
```
## Issue314: Save Alt-Key Special Characters as Shortcuts (등록: 2026-01-10)
* 목적: Alt키 특수문자를 단축키 조합으로 저장
* 현상: opt+L 입력 시 ¬ 로 저장되어 파싱 실패
* 해결: KeyRenderingManager 로직 개선

### Issue314_1: Prefix Shortcut Save Failure (등록: 2026-01-10, 해결: 2026-01-10, commit: 245cdc5) ✅
* 현상: Prefix 단축키 설정이 _rule.yml에 저장 안 됨
* 원인: ShortcutInputView에서 Modifier 없는 입력 무시 설정
* 해결: allowModifierless: true 활성화

### Issue314_2: Suffix Shortcut Empty Save (등록: 2026-01-10, 해결: 2026-01-10, commit: 245cdc5) ✅
* 현상: Suffix 단축키 설정이 "" 또는 비정상으로 저장
* 원인: 314_1과 동일
* 해결: 314_1과 동일
```

**사용 규칙**:
- 부모 이슈: `Issue[N]` - 상위 수준의 목표, 현상, 해결 방향
- 서브 이슈: `Issue[N]_[M]` - 세부 작업, 각각 개별 커밋 해시 기록
- 서브 이슈는 부모 이슈 내에 H3으로 나열하고 각각 독립적으로 완료 마크(✅) 적용
- HWM은 부모 이슈 번호만 증가 (서브 이슈는 HWM에 미반영)

## 워크플로우

### 1. 등록 (Register)
```
이슈 분석 → HWM 확인 → 새 ID 생성 → 섹션에 추가 → HWM 업데이트 → commit
```

### 2. 진행 (In Progress)
```
🌱 이슈후보/📙 일반 → 🚧 진행중으로 이동
```

### 3. 완료 (Close)
```
구현 → 검증 → ✅ 완료로 이동 → 커밋 해시 기록 → commit
```

## 공통 커맨드

- `/issue-reg`: 이슈 등록
- `/issue-fix`: 이슈 해결 (구현 + 검증)
- `/issue-closer`: 이슈 종결 (커밋 해시 기록 + 완료 처리)

## 공통 헬퍼 함수

`~/.bin/issue-helper.sh`에서 제공:

```bash
source ~/.bin/issue-helper.sh

# HWM 관리
issue_get_hwm()           # 현재 HWM 읽기
issue_next_id()           # 다음 이슈 ID 생성
issue_update_hwm(N)       # HWM 업데이트

# 섹션 관리
issue_read_section()      # 섹션 내용 읽기
issue_move()              # 섹션 간 이동
issue_has_issue_in_section()  # 이슈 존재 여부

# 정보 추가
issue_append_to_entry()   # 항목에 텍스트 추가
issue_get_current_date()  # 현재 날짜 (YYYY-MM-DD)
```

## 로컬 프로젝트별 커스터마이징

### 3레이어 참조 구조

```
로컬 issue.md → issue-m (macOS) 또는 프로젝트별 중간층 → issue-g (글로벌)
```

- **issue-m**: macOS 앱 특화 (Xcode 빌드 카테고리, Python 스크립트 자동화, Save Point 패턴, 코드 서명 관련 이슈 추적)

각 프로젝트는 로컬 `issue.md` 스킬에서:
1. **중간층 스킬 참조** (해당하는 경우):
   - macOS 앱: `~/.claude/skills/issue-m.md` (Xcode 빌드/배포, Python 스크립트 자동화, Save Point 패턴)
   - 다른 프로젝트: 해당 중간층 스킬 또는 직접 issue-g
2. **프로젝트 특화 규칙** 정의:
   - Issue.md 파일 위치
   - 추가 섹션 (필요시)
   - 특화 워크플로우
   - 자동화 스크립트 경로 (해당시)
3. **로컬 커맨드** 정의 (필요시)

---

## 예제

### 1. Issue.md 생성
프로젝트 루트에서:
```bash
cat > Issue.md << 'EOF'
---
title: [프로젝트명] Issue
description: [프로젝트] 이슈 관리
date: 2026-03-29
---

# Issue Management
* Issue HWM: 0
* 이슈 관리 규칙: `.claude/rules/issue-rules.md`

# 🤔 결정사항
# 🌱 이슈후보
# 🚧 진행중
# 📙 일반
# ✅ 완료
# 📜 참고
EOF
```

### 2. 이슈 등록
```bash
source ~/.bin/issue-helper.sh
NEXT_ID=$(issue_next_id)
# 또는 직접 편집하고 HWM 업데이트
issue_update_hwm 1
```

### 3. 이슈 완료
```bash
COMMIT_HASH=$(git log -1 --format="%h")
issue_append_to_entry "Issue1" "(commit: $COMMIT_HASH)"
```

### 4. 3레이어 로컬 스킬 구성 예시

macOS 앱 프로젝트의 `<project>/.claude/skills/issue.md` 상단:
```markdown
> **기반**: 이 스킬은 `~/.claude/skills/issue-m.md` (macOS 앱 특화)를 기반으로 합니다.
> `issue-m` → `issue-g` 순서로 글로벌 패턴을 상속합니다.
> - Issue.md 구조, HWM, 이슈 형식, 서브이슈 → issue-g 정의
> - Python 자동화 스크립트, Save Point, Xcode 카테고리 → issue-m 정의
> - 이 문서는 **이 프로젝트 특화 내용만** 추가 정의합니다.
```

일반 프로젝트(issue-g 직접 참조)의 `<project>/.claude/skills/issue.md` 상단:
```markdown
> **기반**: 이 스킬은 `~/.claude/skills/issue-g.md`를 기반으로 합니다.
> Issue.md 구조, HWM, 이슈 형식 등 → issue-g 정의
> 이 문서는 **이 프로젝트 특화 내용만** 추가 정의합니다.
```

---

## 설계 원칙

✅ **단순성**: 모든 프로젝트가 동일한 구조 사용
✅ **추적성**: HWM과 커밋 해시로 완전한 추적
✅ **확장성**: 프로젝트별 커스터마이징 가능
✅ **일관성**: 글로벌 헬퍼 함수로 중복 제거

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../../rules/opus-4-7-execution-rules.md) 참조 (종료 조건·재시도·루프 상한·리터럴 해석·사용자 승인 지점).

이 스킬 특화 제약:
* 각 워크플로우 단계는 명시된 종료 조건 충족 시에만 다음 단계로 진행
* 외부 명령 실패 시 기본 재시도 1회, 실패 지속 시 사용자에게 원인 보고
* 파일·git·외부 시스템 변경은 dry-run 또는 승인 절차 포함
* 애매 표현("시도해봐", "필요 시", "가능하면") 금지 — 조건문으로 해석
