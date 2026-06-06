---
title: issue
description: "PM 프로젝트의 이슈 관리 (issue-g 기반 + PM 특화)"
date: 2026-04-18
---

> **기반**: `~/.claude/skills/issue-g/SKILL.md`를 상속.
> Issue.md 구조, HWM, 이슈 형식, 헬퍼 함수, 워크플로우 → issue-g 정의.
> 이 문서는 **PM 프로젝트 특화 내용만** 정의함.

# PM 프로젝트 특화

## 파일 위치
* Issue.md: `~/_git/___pm/Issue.md`
* 규칙: `.claude/rules/issue-rules.md`

## 프로젝트 맥락
* **타겟**: MacOS App 관리 (fApp 11~16) + cdf 함수 시스템
* **범위**: 스크립트, 설정, 문서

## 자동 워크플로우 (인자 없이 실행 시)

`Issue.md`의 상태를 분석하여 자동으로 결정·실행:

| 우선순위 | 대상 섹션    | 조건        | 행동                                    |
| -------- | ------------ | ----------- | --------------------------------------- |
| 1        | 🌱 이슈후보 | 내용 있음   | `/issue-reg` 실행                       |
| 2        | 🚧 진행중   | 이슈 할당됨 | `/issue-fix` 실행                       |
| 3        | 📕 중요     | 이슈 있음   | 🚧 진행중으로 이동 → `/issue-fix` 실행 |
| 4        | 📙 일반     | 이슈 있음   | 🚧 진행중으로 이동 → `/issue-fix` 실행 |

## 로컬 커맨드
* `/issue-reg`: 이슈 등록 (분석 → ID 발급 → Issue.md 추가 → HWM 업데이트 → commit)
* `/issue-fix`: 이슈 해결 (분석 → 구현 → 검증 → `/issue-closer` 연결)
* `/issue-closer`: 이슈 종결 (커밋 생성 → ✅ 완료 이동 → 해시 기록)



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 skill 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
