---
name: dev
title: dev
description: "이슈 기반 개발 주기 (___pm 특화 진입 → dev-g 위임)"
date: 2026-06-03
---

> 글로벌 `dev-g` 스킬이 개발 주기 공통 로직(Case A/B, 비대화 자동 진행, 자동 결정 기록)을 정의합니다. 본 로컬 `/dev` 커맨드는 ___pm 프로젝트 특화 컨텍스트를 적용한 뒤 `dev-g` 에 위임합니다.
> 하위 호출(`/issue-reg`, `/issue-fix`, `/issue-closer`)은 ___pm 로컬 커맨드를 우선 사용합니다 (각자 다시 `-g` 위임).

**역할**: `Issue.md` 우선순위 기반 이슈 개발 주기를 **비대화 자동 진행**합니다 (등록 → 구현 → 검증 → 종결).

# 사용법

- `/dev` — 자동 모드 (`Issue.md` 우선순위 최상위 이슈 자동 선택)
- `/dev [N]` — 이슈후보 N번 즉시 등록 및 진행

# ___pm 특화 컨텍스트

위임 전 다음 프로젝트 특화 사항을 적용합니다:

- **헬퍼 로드**: `source ~/.bin/issue-helper.sh` (HWM·날짜 함수)
- **하위 커맨드**: 로컬 `/issue-reg`, `/issue-fix`, `/issue-closer` 사용 (suffix 없는 ___pm 로컬 — 각자 `-g` 위임)
- **Issue.md SSOT**: 프로젝트 루트 `Issue.md`
- **PM 저장소 특성**: `projects/` 인덱스·`Projects.md`·`Harness.md`·`README.md` 는 상호 동기화 대상 — 한쪽 변경 시 나머지 정합성 점검
- **graphify**: 코드/구조 질의는 `graphify query/path/explain` 우선 (`.claude/rules/graphify-rules.md`)

# 위임

위 특화 컨텍스트 적용 후 글로벌 `dev-g` 스킬 워크플로우를 그대로 따릅니다:

- **Case A** (인자 N): 이슈후보 N 등록 → `# 🚧 진행중` 이동 → 구현 → 검증 → 종결
- **Case B** (인자 없음): `Issue.md` 우선순위(📕 > 📙 > 📗) 최상위 이슈 자동 선택 → 진행 → 종결
- **비대화 자동 진행**: 흐름 중 `AskUserQuestion`·사용자 확인 금지. 모호 시 보수적 자동 결정 + 최종 응답에 1줄 기록
- **예외**: 파일 삭제·`git push`·외부 시스템 변경·결제는 그대로 승인 요구 (`rules/opus-4-7-execution-rules.md § 5`)

상세 로직 SSOT: `~/.claude/skills/dev-g/SKILL.md`

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
