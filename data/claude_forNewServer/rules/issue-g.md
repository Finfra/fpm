---
name: issue-g
description: 모든 프로젝트 공통 이슈 관리 규칙
date: 2026-04-04
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> **관리 위치**: 이슈는 프로젝트 루트의 `Issue.md`에서 **통합 관리**한다. 하위 독립 레포에 별도 이슈 파일을 두지 않는다.

> 🔒 **집행: advisory (일부 조항만)** — [`hooks/rule-guard.sh`](../hooks/rule-guard.sh) 가 검출해 경고하는 것은 셋이다: `Issue.md` 편집 시 **`* depends:` 토큰 문법**(F5-7)·**산문 절 길이 초과**(규칙9, Issue342), 그리고 `_doc_work/{plan,report}/*.md` 편집 시 **규칙2 산출물 필드 결손**(Issue411 — 이슈도 frontmatter 도 그 파일을 안 가리키면 경고). 나머지 조항(섹션 이동·완료 순서·`(!)` 마커 진입 조건·`trigger` 기재)은 **집행 수단 없음** — 사람·Claude 의 준수에 의존한다
> 📚 **분류: 사실** — `Issue.md` 섹션·필드 **포맷 규약**. issue-map 등 소비처가 이 형식을 전제

> 📖 **상세는 조건부 로드** (Issue361) — `depends` 토큰 문법·`(!)` 마커 진입조건과 fix 게이트·`trigger`/`status` 필드·산문 절 길이 상한은 [`issue-detail.md`](../_doc_arch/rules-ondemand/issue-detail.md) 로 분리했다.

# 규칙

- 규칙0 (프로세스): 작업 시작 시 `🚧 진행중` 섹션, 완료 시 `✅ 완료` 섹션으로 이동합니다. **`✅ 완료` 섹션 내 삽입 위치는 헤더 바로 아래(최상단)** — 완료 시각 역순(newest first) 유지. 이슈 번호 오름차순으로 섹션 끝에 append 금지 (이슈 번호 ≠ 완료 순서).
- 규칙1 (작성 언어): 이슈 제목, 목적, 상세 내용 및 결과 설명(Walkthrough)은 모두 **한국어**로 작성합니다. (기술 용어 제외)
- 규칙2 (이슈 포맷): 이슈 번호는 붙여쓰기(Issue1)하며, `* 목적`, `* 상세`, `* 구현 명세`(로직/검증 포함) 구조를 준수합니다. plan/task 파일이 존재하면 `* plan:`, `* task:` 경로 필드를 `* 목적:` 바로 아래에 명시합니다. (경로는 Issue.md 기준 상대경로). 선행 이슈가 있으면 `* depends:` 필드를 동일 위치에 명시합니다:
    - **같은 prj 내 선행**: `* depends: Issue<M>[, Issue<M2>]` (prj 접두 없음). 후행 이슈가 선행 이슈 완료 후에야 착수 가능함을 표기. 선행 이슈 종결 시 `issue-closer-g`가 이 필드를 스캔하여 "후행 진행 가능" 알림을 띄움.
    - **다른 prj 간 선행**: `* depends: prj<N>#Issue<M>[, prj<N2>#Issue<M2>]` (prj 접두 필수). `/fpm-do --auto-deps`가 이 필드를 파싱하여 선행 prj 작업을 자동 위임·대기 후 본 이슈 진행을 가능하게 합니다.
    - **혼합 표기**: 같은 prj·다른 prj 선행이 공존하면 한 `* depends:` 줄에 쉼표로 나열 (ex: `* depends: Issue3, prj16#Issue42`). prj 접두 유무로 같은 prj/다른 prj 를 구분.
- 규칙3 (커밋 정책): 완료된 이슈는 반드시 커밋 해시를 기록해야 합니다. 다수 커밋은 쉼표로 구분(hash1, hash2).
- 규칙4 (정리): 이슈 등록 시 `이슈후보` 섹션의 중복 항목은 삭제.
- 규칙5 (이슈후보): `🌱 이슈후보` 섹션은 번호 없이 `1. 항목명` 리스트로만 작성. 이슈 번호는 `📕📙📗` 우선순위 섹션으로 이동할 때 HWM 기반으로 발급.
- 규칙6 (서브 이슈): 복잡한 기능은 서브 이슈로 분리합니다. 서브 이슈는 `_`로 구분(Issue1_2)하고 부모 이슈 바로 아래 배치합니다. 서브 이슈 완료 시 '완료' 표시만 하고 부모 이슈가 종결될 때 함께 이동합니다.
- 규칙7 (서브 이슈 동기화): 서브 이슈는 항상 메인 이슈 하위 개요에 위치해야 합니다. (활성/완료 상태 무관)

## 포맷 예시 (규칙2 — plan/task 필드 위치)

```markdown
## Issue5: {제목} (등록: YYYY-MM-DD)
* 목적: ...
* plan: `_doc_work/plan/{주제}_plan.md`
* task: `_doc_work/plan/{주제}_task.md`
* 상세:
    - ...
```

* 경로는 **백틱 표기**가 규약입니다 — `issue-map` 등 소비처가 이 형식을 파싱하므로 markdown 링크로 바꾸지 마십시오([`language-rules.md`](language-rules.md) 경로 표기 규칙의 명시 예외)
* 산출물 **경로 자체**(`plan/` 아래 `_task.md` 등)는 [`../_doc_arch/rules-ondemand/nptir-rules.md`](../_doc_arch/rules-ondemand/nptir-rules.md) 가 소유합니다

# Issue.md 기본 섹션

```
Issue Management, 🤔 결정사항, 🌱 이슈후보, 🚧 진행중, 📕 중요, 📙 일반, 📗 선택, ✅ 완료, ⏸️ 보류, 🚫 취소, 📜 참고
```

> 프로젝트별로 완료 섹션명이 다를 수 있음 (ex: `🏁 완료-해결순`). 프로젝트 rules에서 오버라이드.

# 📋 예제 (SSOT)

> 양식·예제는 `___pm/data/template/Issue.md`가 원본 (Single Source of Truth).
> 이슈 작성·수정 시 해당 템플릿을 Read하여 최신 양식을 따를 것.
