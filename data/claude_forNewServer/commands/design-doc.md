---
name: design-doc
description: _doc_arch/ 영속적 설계 문서 생성·갱신 커맨드. 없으면 신규 작성, 있으면 섹션 단위 추가·갱신. _doc_arch/doc-design-rules.md 규칙 준수
date: 2026-04-19
---

# /design-doc

> **규칙 로드**: 실행 전 `~/.claude/_doc_arch/doc-design-rules.md` 를 Read할 것.

`_doc_arch/` 영속적 설계 SSOT 문서를 생성·갱신하는 커맨드. 규칙 SSOT는 [`~/.claude/_doc_arch/doc-design-rules.md`](../_doc_arch/doc-design-rules.md).

# 사용법

```
/design-doc {주제}                                  # 신규 생성 또는 섹션 append
/design-doc {주제} {섹션명}                          # 특정 섹션만 갱신
/design-doc --path {전체경로}                        # 경로 직접 지정
/design-doc --deprecate {주제}                       # z_old/ 로 이관
```

* `{주제}`: kebab-case 권장 (ex: `nptir-triage`, `folder-arch`, `harness`)
* `{섹션명}`: 선택. 지정 시 해당 `## 섹션명` 만 갱신
* `$ARGUMENTS`: 주제 + (선택) 추가 내용

# 동작

## 1. 사전 확인

1. nPTiR 루트 확인: 가장 가까운 `Issue.md` 디렉토리
2. `_doc_arch/` 폴더 존재 확인 — 없으면 생성 (사용자 확인 후)
3. 규칙 로드: [`_doc_arch/doc-design-rules.md`](../_doc_arch/doc-design-rules.md)의 파일 위치·명명·필수 섹션 규칙

## 2. 경로 결정

### 주제 → 파일 경로 매핑

| 주제 키워드          | 기본 경로                                          |
| :------------------- | :------------------------------------------------- |
| `harness`, `arch`    | `_doc_arch/Harness/{주제}.md`                    |
| `folder-*`           | `_doc_arch/folder_arch.md`                       |
| `*-usage`            | `_doc_arch/{주제}.md`                            |
| 그 외                | `_doc_arch/{주제}-design.md`                     |

`--path` 지정 시 이 매핑을 무시하고 직접 사용.

## 3. 분기 처리

### Case A: 신규 생성 (파일 없음)

1. 아래 템플릿으로 파일 생성
2. `# 관련 자료` 섹션에 후보 링크 자동 삽입:
   - 루트 `Harness.md` (존재 시)
   - 주제와 매칭되는 `rules/{주제}-rules.md` (Grep으로 탐색)
   - 주제와 매칭되는 `_doc_work/plan/{주제}_plan.md`
3. `/md-rule-apply {파일경로}` 실행하여 검증

### Case B: 기존 파일에 섹션 추가 (파일 있음, 섹션명 미지정)

1. `Read`로 기존 파일 확인
2. 추가할 섹션 내용 사용자에게 확인
3. `Edit`으로 말미에 `## {새 섹션}` 추가 (기존 섹션 무수정)
4. `# 변경 이력 기준` 섹션 바로 위에 삽입

### Case C: 특정 섹션 갱신 (파일 있음, 섹션명 지정)

1. `Read`로 기존 파일 확인
2. `## {섹션명}` 블록 존재 확인
3. `Edit`으로 해당 블록만 교체 (다른 섹션 무수정)
4. 존재하지 않는 섹션이면 Case B로 폴백

### Case D: 폐기 (`--deprecate`)

1. `_doc_arch/z_old/` 생성 확인
2. 파일을 `_doc_arch/z_old/{원래경로}`로 이동
3. 이동된 파일 상단에 폐기 주석 추가: `<!-- deprecated: {사유}, {YYYY-MM-DD} -->`
4. 영향받는 참조 링크 보고 (자동 수정 금지 — 사용자에게 수정 대상 목록 제시)

## 4. 템플릿 (신규 생성)

```markdown
---
name: {파일명_without_ext}
description: {1줄 요약}
date: {YYYY-MM-DD}
---

# 개요
{이 문서가 설계하는 대상·스코프 — 2~4문장}

# 관련 자료
* [상위 Harness 또는 folder_arch 링크]
* [관련 규칙 링크]
* [관련 plan 링크 — 있다면]

# {설계 본문 섹션들}
{호출 관계, 정책, 판정 기준, 사례 등 — 주제별로 필요 섹션 구성}

# 설계 결정 요약
* {핵심 결정 1}: {근거}
* {핵심 결정 2}: {근거}

# 변경 이력 기준
* 본 문서는 {YYYY-MM-DD} 작성. 이전 이력은 `git log -- {상대경로}` 참조
* {어떤 상황에 본 문서 직접 갱신 vs 상위 SSOT(Harness·규칙) 갱신을 우선할지 기준}
```

## 5. 검증 (모든 Case 공통)

1. `/md-rule-apply {파일경로}` 실행 — Frontmatter·Outline·Bullet·Table 검증
2. `# 관련 자료` 섹션 1개 이상 링크 확인 (고립 문서 방지)
3. SSOT 중복 확인: Grep으로 동일 내용이 `rules/`·루트 `Harness.md`·`_doc_work/plan/`에 있는지 탐색 → 발견 시 사용자 보고 + 참조 링크로 축약 제안

# 산출물

* 단일 파일: `_doc_arch/{주제}-design.md` 또는 매핑된 경로
* `/md-rule-apply` 검증 통과
* (Case B/C) 변경 요약 1줄 사용자 보고

# 규칙 연계

* 필수 참조: [`_doc_arch/doc-design-rules.md`](../_doc_arch/doc-design-rules.md)
    - 작성 시점 (언제 `_doc_arch/`에 둘지)
    - `_doc_arch/` vs `_doc_work/plan/` 분리 기준
    - SSOT 중복 방지 우선순위
    - 필수 섹션 목록
* 관련: [`rules/nptir-rules.md`](../rules/nptir-rules.md) — nPTiR 루트 위치 판정
* 관련: [`rules/md-rules.md`](../rules/md-rules.md) — 마크다운 포맷
* 관련: [`rules/naming-rules.md`](../rules/naming-rules.md) — 파일명 kebab-case

# 사용 예시

```bash
## 신규 triage 설계 문서 (Issue4 진행용)
/design-doc nptir-triage

## Harness에 새 섹션 추가
/design-doc harness "sync 도메인 호출 관계 추가"

## 기존 섹션 갱신
/design-doc folder-arch "타입 3"

## 경로 직접 지정
/design-doc --path _doc_arch/Harness/sp-integration.md

## 폐기
/design-doc --deprecate old-xxx-design
```

# 기존 커맨드와의 차이

| 커맨드           | 용도                                   | 저장 위치                        |
| :--------------- | :------------------------------------- | :------------------------------- |
| `/design-doc`    | 영속적 설계 SSOT                       | `_doc_arch/`                   |
| `/needs`, `/sp-plan`, `/gstack-plan` | 이슈별 실행 계획      | `_doc_work/plan/`                |
| `/gstack-report` | 이슈 완료 결과물                       | `_doc_work/report/`              |
| `/md-add`        | 범용 마크다운 생성                     | 경로 자유 (주로 docs/)           |

# 종료 조건

* 파일 생성·갱신 확인
* `/md-rule-apply` 검증 통과
* SSOT 중복 체크 완료 (발견 시 사용자 보고만, 자동 수정 금지)
* 사용자 확인 없이 `z_old/` 이동·파일 삭제 금지

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조. 본 커맨드 특화 제약:

* 기존 `_doc_arch/` 문서 **전체 재작성 금지** — 섹션 단위 Edit만 허용
* 폐기(`--deprecate`) 실행 시 사용자 승인 후 이동, 원본 삭제 금지
* 다이어그램(.mermaid/.excalidraw) 생성 시 dry-run으로 내용 먼저 제시, 승인 후 저장
* `/md-rule-apply` 실패 2회 시 사용자에게 원인 보고 + 중단
* SSOT 중복 발견 시 자동 병합·삭제 금지, 사용자 결정 대기

# 참조

* [`~/.claude/_doc_arch/doc-design-rules.md`](../_doc_arch/doc-design-rules.md) — `_doc_arch/` 운영 SSOT
* [`~/.claude/rules/nptir-rules.md`](../rules/nptir-rules.md) — nPTiR 상위 규칙
* [`~/.claude/rules/md-rules.md`](../rules/md-rules.md) — 마크다운 포맷
* [`~/.claude/commands/md-add.md`](md-add.md) — 범용 마크다운 생성
* [`~/.claude/commands/md-rule-apply.md`] — 마크다운 규칙 검증
