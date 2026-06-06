---
name: md-add
date: 2026-03-26
description: 모든 프로젝트에서 사용 가능한 범용 마크다운 문서 생성 커맨드
---

사용자가 `/md-add "주제"` 명령을 내렸을 때 실행하는 절차임.
인자: $ARGUMENTS

# 사용법

```
/md-add <주제 또는 내용>
/md-add <경로/파일명> <주제 또는 내용>
```

# 경로 결정

## Case A: 경로 미지정 (`/md-add "Title"`)
프로젝트 구조를 분석하여 최적의 위치를 결정함.

1.  **프로젝트 구조 탐색**:
    - `Glob` 도구로 기존 `.md` 파일 분포를 확인함.
    - `docs/`, `notes/`, `README` 등 일반적인 문서 디렉토리가 있으면 해당 위치 사용.
2.  **유사 문서 검색**:
    - `Grep` 도구로 주제 키워드와 관련된 기존 문서를 탐색함.
    - 관련 문서가 발견되면 동일 디렉토리에 배치.
3.  **기본값**: 적절한 위치를 찾지 못하면 현재 작업 디렉토리에 생성.

## Case B: 경로 지정 (`/md-add "path/to/file.md" "Title"`)
* 지정된 경로에 파일 생성.
* 상위 디렉토리가 없으면 자동 생성.

## Case C: 문서 업데이트 (`/md-add "기존파일.md" "수정내용"`)
기존 파일이 존재하면 내용을 수정함.

1.  **파일 확인**: `Read` 도구로 기존 내용을 읽음.
2.  **내용 수정**: `Edit` 도구로 요청사항을 반영.
    - 기존 문서의 스타일과 구조를 유지함.

# 파일명 규칙
* 스페이스 대신 언더바(`_`) 사용
    - ex) `Docker_Compose_Guide.md`, `API_설계_패턴.md`
* 확장자 `.md` 필수

# 문서 작성

## Markdown 규칙
* `~/.claude/rules/md-rules.md`의 Frontmatter·Outline·Bullet·Table 규칙을 준수할 것
* 프로젝트에 `tags` 관례가 있으면 `tags` 필드도 추가

## 문서 템플릿

### 기술 문서 (기본)
```markdown
---
title: <Title>
date: <YYYY-MM-DD>
description: <설명>
---

# 개요
<!-- 주제 정의, 핵심 특징 -->

## 주요 특징
* <!-- 기능 1 -->
* <!-- 기능 2 -->

# 설치 및 설정
<!-- 환경 설정, 의존성 -->

# 사용법
<!-- 예시, 코드 스니펫 -->

# 트러블슈팅
<!-- 알려진 이슈, 해결 방법 -->

# References
* <!-- 참고 링크 -->
```

### 간단 메모
```markdown
---
title: <Title>
date: <YYYY-MM-DD>
description: <설명>
---

# 내용
<!-- 본문 -->
```

### 슬라이드 (PPT)
사용자가 "ppt", "슬라이드", "프레젠테이션", "발표자료" 등을 언급하면 이 템플릿 사용.
```markdown
---
title: <Title>
date: <YYYY-MM-DD>
description: <설명>
type: ppt
---

# <슬라이드 1 제목>

* <항목>
* <항목>

# <슬라이드 2 제목>

* <항목>

# <슬라이드 3 제목>

* <항목>
```

* **`type: ppt` 필수**: 슬라이드용임을 표시. 각 H1이 한 슬라이드가 됨
* **md-rules 예외**: 본문 H1 다수 허용, Outline 규칙 적용 제외 (`~/.claude/rules/md-rules.md` 참조)

* **지침**: 템플릿을 빈칸으로 두지 말고, 가진 지식을 활용하여 **초안을 충실히 채워서** 생성함.
* **주제에 맞는 템플릿 선택**: 기술 문서/메모/회의록/슬라이드 등 주제 성격에 따라 적절한 구조를 선택함.

# 파일 생성
* `Write` 도구로 파일을 생성함.
* 생성 전 동일 파일명이 이미 존재하는지 `Glob` 도구로 확인함.

# 검증

1.  **md-rule-apply 실행**: `/md-rule-apply <생성된 파일 경로>`로 Markdown 가이드라인 준수 여부 검증
    - Frontmatter 완성도 (title, date, description)
    - Outline 구조 (H1 시작, 레벨 건너뛰기 없음)
    - Bullet 형식 (`*`/`-` 레벨 구분)
    - Table 정렬 (열 너비 패딩)
2.  **위반 발견 시 즉시 수정**

# 사용 예시

```bash
/md-add Docker Compose 사용법 정리
/md-add docs/architecture.md 시스템 아키텍처 설계
/md-add README.md 프로젝트 소개 업데이트
/md-add 오늘 회의 내용 메모
```

# 인수(Arguments)

* `$ARGUMENTS`: 생성할 문서의 주제, 경로, 또는 수정 내용
* 인수가 비어있을 경우 사용자에게 주제를 질문함

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석
