---
name: needs
description: nPTiR n(Needs) 단계 입구 커맨드. 주제를 받아 신호 판정 후 superpowers:brainstorming(탐색) 또는 superpowers:writing-plans(직행)로 라우팅하여 plan 파일 생성
date: 2026-04-19
---

# /needs {주제}

> **규칙 로드**: 실행 전 `~/.claude/_doc_arch/sp-nptir-rules.md` 를 Read할 것.

nPTiR needs 단계 단일 입구. 주제 확실성에 따라 A경로(brainstorming) 또는 B경로(sp-plan)로 자동 라우팅하고 `_doc_work/plan/{주제}_plan.md` 단일 산출물을 생성함.

# 입력

* `{주제}`: 자유 기술 또는 영문 kebab-case (ex: "dark-mode 추가할지 고민", `auth-rewrite`)
* 인자 없으면 1회 질의

# 동작

## 1. 사전 확인

* nPTiR 루트 위치 확인: 가장 가까운 `Issue.md` 디렉토리
* 동일 주제 plan 존재 시 덮어쓰기 금지 → 사용자 확인
* 규칙 로드: [`~/.claude/_doc_arch/sp-nptir-rules.md`](../_doc_arch/sp-nptir-rules.md) 신호 판정 기준표

## 2. 신호 판정 (R1 라우팅)

| 구분       | 키워드·표현 예시                                    | 경로     |
| :--------- | :-------------------------------------------------- | :------- |
| 탐색 필요  | "어떻게 할지", "옵션", "뭐가 좋을까", "방안 모호"   | **A**    |
| 방향 명확  | "plan 만들어줘", "X로 구현", "계획만 쪼개줘"        | **B**    |
| 애매       | 위 둘 다 아님                                       | 1회 질문 |

**판정 실패 시**: 재시도 1회 → 실패 시 사용자에게 "A 탐색 / B 계획만" 명시 질문.

## 3. 경로별 실행

### A경로 — 탐색 후 계획

1. `superpowers:brainstorming` 호출 — 단일 대화 컨텍스트에서 요구사항·대안·트레이드오프 탐색
2. 탐색 요약을 plan 파일 `## Needs Exploration` 섹션으로 흡수
3. `superpowers:writing-plans` 호출 (선택, 사용자 동의 시) — 본문 구조화
4. plan 파일 저장

### B경로 — 계획 직행

1. `superpowers:writing-plans` 호출 — 주제 기반 plan 즉시 생성
2. plan 파일 저장
3. `## Needs Exploration` 섹션 생략 (탐색 단계 skip)

## 4. plan 파일 생성

**경로**: `{nPTiR루트}/_doc_work/plan/{주제}_plan.md`

**frontmatter**:

```yaml
---
name: {주제}_plan
description: {writing-plans 출력의 요약 1줄}
date: {오늘 YYYY-MM-DD}
issue: TBD
---
```

**본문 구조** (md-rules.md Outline 준수):

```markdown
# 배경 및 목표
## Needs Exploration        <-- A경로일 때만 작성
# 적용 범위
# 구현 순서
# 완료 조건
# 리스크 및 완화
# Opus 4.7 실행 제약
```

## 5. 후속 연결

plan 생성 완료 직후 사용자에게 1회 질의:

> "이슈로 등록할까요? (Y: /issue-reg-g 연쇄 / N: plan만 저장)"

* Yes → `/issue-reg-g` 연쇄 호출 (이슈 번호 발급 + plan frontmatter `issue:` 업데이트 + Issue.md 양방향 링크)
* No → plan frontmatter `issue: TBD` 유지, 종료

# 산출물

* **단일 파일**: `_doc_work/plan/{주제}_plan.md`
* `_doc_work/needs/` 폴더 **미사용** (needs 산출물은 plan 내부 흡수)
* brainstorming 대화 내용은 plan `## Needs Exploration`에 요약 (원문 저장 금지)

# /gstack-plan 과의 차이

| 항목            | /needs (+/sp-plan)                    | /gstack-plan                              |
| :-------------- | :------------------------------------ | :---------------------------------------- |
| 토큰 예산        | ~3k (경량)                           | ~20k (4종 리뷰 내장)                      |
| 리뷰 단계       | 없음 (필요 시 개별 호출)              | CEO·Eng·Design·DX 자동                    |
| 적합 시점       | 작업 복잡도 낮음·컨텍스트 여유 부족   | 대형 리뉴얼·다관점 리뷰 필요              |
| context overflow 위험 | 낮음                             | 있음 (50% 이상 사용 시 주의)              |

상세 선택 기준: [`_doc_arch/sp-nptir-rules.md`](../_doc_arch/sp-nptir-rules.md) "선택 기준표" 섹션 참조.

# 종료 조건

* plan 파일 생성 확인 (`ls _doc_work/plan/{주제}_plan.md` 성공)
* 후속 질의 응답 수령 (Y/N)
* Y 선택 시: Issue.md 이슈 등록 + 양방향 링크 확인 후 종료
* N 선택 시: plan 파일 저장 후 종료

추가 작업(task 생성·구현 시작) **자동 진행 금지**.

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조. 본 커맨드 특화 제약:

* 신호 판정 재시도 최대 1회, 이후 사용자 명시 선택 대기
* A경로의 brainstorming 대화 턴 상한 5회 (공통 규칙 준수)
* plan 파일 생성 실패 시 1회 재시도 → 실패 시 보고 + 중단
* Issue.md 자동 갱신은 `/issue-reg-g` 위임. 본 커맨드 단독 수정 금지

# 참조

* [`~/.claude/_doc_arch/sp-nptir-rules.md`](../_doc_arch/sp-nptir-rules.md) — superpowers × nPTiR 통합 규칙
* [`~/.claude/rules/nptir-rules.md`](../rules/nptir-rules.md) — nPTiR 상위 규칙
* [`~/.claude/commands/sp-plan.md`](sp-plan.md) — B경로 단축 커맨드
* [`~/.claude/commands/gstack-plan.md`](gstack-plan.md) — gstack 장황 경로 (대체 옵션)
* `~/.claude/plugins/cache/superpowers-marketplace/superpowers/5.0.7/skills/brainstorming/SKILL.md`
* `~/.claude/plugins/cache/superpowers-marketplace/superpowers/5.0.7/skills/writing-plans/SKILL.md`
