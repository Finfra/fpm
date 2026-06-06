---
name: gstack-plan
description: gstack v1.12.1.0 /office-hours·/autoplan 결과를 nPTiR plan 파일로 변환·저장하고 Issue.md 이슈후보 등록
date: 2026-04-24
---

# /gstack-plan {주제}

> **규칙 로드**: 실행 전 `~/.claude/_doc_arch/gstack-nptir-rules.md` 를 Read할 것.

gstack 계획 단계 스킬(`/office-hours`, `/autoplan`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/plan-devex-review`) 출력을 nPTiR plan 파일로 구조화하여 저장하고 Issue.md 이슈후보에 등록함.

# 입력

* `{주제}`: 영문 kebab-case 권장 (ex: `dark-mode-toggle`, `auth-rewrite`)
* 인자 없으면 사용자에게 주제 1회 질의

# 동작

## 1. 사전 확인

* nPTiR 루트 위치 확인: 가장 가까운 `Issue.md` 디렉토리
* 동일 주제 plan 존재 시 덮어쓰기 금지 → 사용자 확인 후 진행
* gstack 버전 확인: `cat ~/.claude/skills/gstack/VERSION` (현재 v1.12.1.0, jargon 풀이·outcome-framing 기본 활성)

## 2. plan 파일 생성

**경로**: `{nPTiR루트}/_doc_work/plan/{주제}_plan.md`

**frontmatter 템플릿**:

```yaml
---
name: {주제}_plan
description: {gstack 출력의 첫 문단 요약 1줄}
date: {오늘 날짜 YYYY-MM-DD}
issue: TBD
---
```

**본문 구조** (md-rules.md Outline 규칙 준수):

```markdown
# 배경

{gstack 스킬이 식별한 문제 정의}

# 목표

{핵심 결과 + 측정 가능 기준}

# 설계

{gstack 출력의 설계 섹션. jargon 풀이 라인 보존 — 절대 제거 금지}

# 단계별 계획

{Phase 1, 2, 3 ...}

# 위험 및 트레이드오프

{gstack /plan-ceo-review·/plan-eng-review가 식별한 위험}

# 검증 기준

{measurable success criteria}
```

## 3. 리뷰 결과 통합 (선택)

`/autoplan` 또는 개별 `/plan-*-review`를 사전 실행한 경우, 결과를 plan 본문에 다음 섹션으로 추가:

* `## CEO Review` — `/plan-ceo-review` 결과
* `## Eng Review` — `/plan-eng-review` 결과
* `## Design Review` — `/plan-design-review` 결과
* `## DevEx Review` — `/plan-devex-review` 결과

## 4. Issue.md 이슈후보 등록

`Issue.md`의 `# 🌱 이슈후보` 섹션에 다음 항목 추가:

```markdown
1. {gstack 출력 제목}
    - plan: `_doc_work/plan/{주제}_plan.md`
```

이후 `/issue-reg-g`로 이슈 번호 발급 시 자동으로 `* plan:` 필드 연결됨.

## 5. prose 정책 안내

plan 파일 끝에 **단 1회**(첫 사용 시) 다음 안내 추가:

```markdown
---

> **참고**: 본 plan은 gstack default explain 모드 출력을 보존함.
> 간결 모드 선호 시 `gstack-config set explain_level terse` 실행 후 재생성.
```

이미 `~/.gstack/explain-level-asked.flag`가 있으면 이 섹션 생략.

# 출력

* 생성 파일 경로
* Issue.md 변경 라인 수
* 다음 단계 안내: "`/issue-reg-g`로 이슈 번호 발급 후 `/gstack-report {번호}`로 완료 시 report 생성"

# 종료 조건

* plan 파일 생성 완료
* Issue.md 이슈후보 등록 완료
* 사용자에게 결과 보고
* **자동으로 다음 단계(이슈 등록·구현 등) 진행 금지**

# 참조

* nPTiR 규칙: `~/.claude/rules/nptir-rules.md`
* gstack ↔ nPTiR 연동: `~/.claude/_doc_arch/gstack-nptir-rules.md`
* md 규칙: `~/.claude/rules/md-rules.md`
* gstack v1.12.1.0 CHANGELOG: `~/.claude/skills/gstack/CHANGELOG.md`

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* 동일 주제 plan 존재 시 덮어쓰기 금지 — 사용자 승인 후 진행
* gstack 출력의 jargon 풀이는 plan 본문에 그대로 보존 (요약·삭제 금지)
* explain_level 안내는 첫 사용 시 1회만 노출
