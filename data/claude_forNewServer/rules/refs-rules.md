---
name: refs-rules
description: _doc_work/refs/ 참고 자료 폴더 운영 규칙 — 인덱스(_doc_work/refs.md) 동기화 의무 (글로벌)
date: 2026-04-26
---

# 목적

프로젝트에서 참조하는 자료(웹 스크랩, 정리노트, 외부 문서 발췌 등)를 `_doc_work/refs/`에 모으되, **루트 인덱스 `_doc_work/refs.md`에서 항상 전체 항목을 한눈에 추적**할 수 있도록 강제함. 자료가 흩어지거나 인덱스 누락이 발생하지 않게 함.

# 적용 범위

* 모든 프로젝트의 `_doc_work/refs/` 폴더 하위 파일·서브폴더 생성·이동·삭제·이름변경
* 인덱스 파일: 해당 프로젝트의 `_doc_work/refs.md` (SSOT)
* 본 폴더·인덱스가 없는 프로젝트는 사용자가 도입을 결정한 시점부터 적용

# 핵심 규칙

## 1. 인덱스 등록 의무

`_doc_work/refs/` 하위에 **파일이나 폴더를 생성하면 즉시** `_doc_work/refs.md`에 한 줄을 추가함.

* 등록 누락 상태로 작업 종료 금지
* 생성 직후 같은 응답 내에서 인덱스 갱신 (다음 턴으로 미루지 않음)

## 2. 등록 형식

```markdown
* {제목} : {프로젝트 루트 기준 상대경로}
```

* `{제목}`: 파일명에서 확장자 제거. 케밥케이스 또는 사람이 읽기 좋은 형태로 통일
* `{경로}`: 프로젝트 루트 기준 상대경로 (`_doc_work/refs/...`)
* 경로는 백틱 없이 적음 (Obsidian/IDE 클릭 호환성)

ex)

```markdown
* agentic-engineering : _doc_work/refs/agentic-engineering.md
* langgraph-tutorial : _doc_work/refs/langgraph-tutorial.md
```

## 3. 섹션 구조

`_doc_work/refs.md`는 출처 유형별로 H1 섹션을 분리함. 본문 H1 다수가 정상이므로 **md-rules의 Outline 단일 H1 규칙 적용 제외** (이슈 트래커형 파일).

| 섹션              | 용도                                                          |
| :---------------- | :------------------------------------------------------------ |
| `# obsidian docs` | `~/_doc` 볼트에서 가져온/링크된 자료 (글로벌 지식 자산)       |
| `# refs`          | 외부에서 직접 작성·수집한 일반 참고 자료 (웹 스크랩, 정리노트) |

신규 유형이 필요하면 H1 섹션을 추가하고, 프로젝트 특화 섹션은 해당 프로젝트 `_doc_arch/` 문서에 정의를 보충함.

## 4. 폴더 등록 규칙

`_doc_work/refs/` 하위에 서브폴더를 만들 경우:

* 서브폴더 자체를 한 줄로 등록: `* {폴더명}/ : _doc_work/refs/{폴더명}/`
* 서브폴더 내부 파일은 개별 등록 생략 가능 (단, 대표 파일은 등록 권장)
* 서브폴더 내부에 별도 인덱스(`README.md` 또는 `index.md`)를 두면 더 좋음

## 5. 이름 변경·이동·삭제

* 파일명·경로 변경 시 `_doc_work/refs.md` 항목도 동시 수정
* 삭제 시 인덱스 항목도 동시 제거
* 다른 폴더(`_doc_arch/`, `~/_doc/`)로 승격·이동 시 인덱스에서 제거 + 이동 위치를 주석으로 기록 권장

## 6. 파일 자체 규칙

`_doc_work/refs/` 내부 마크다운 파일은 글로벌 `md-rules`를 따름:

* Frontmatter 필수 (`name`, `description`, `date`)
* `name` = 파일명(확장자 제외)
* 단일 H1 금지 (Frontmatter `name`이 제목 역할)

# 자동화 후크 (선택)

향후 다음 자동화 도입 가능:

* pre-commit 훅: `_doc_work/refs/` 변경분과 `_doc_work/refs.md` diff 동시 변경 검증
* `/refs-sync` 슬래시 커맨드: 폴더 스캔 후 인덱스 자동 재생성

현재는 **수동 등록 의무** 단계.

# 위반 시 대응

* Claude가 `_doc_work/refs/`에 파일 생성 후 인덱스 갱신을 누락한 사실을 발견하면 즉시 갱신
* 사용자가 누락을 지적하면 즉시 수정 후 `learning_log.md`에 누락 사례 한 줄 기록 권장

# 참조

* 글로벌 md-rules: `~/.claude/rules/md-rules.md`
* nPTiR 폴더 구조: `~/.claude/rules/nptir-rules.md`
