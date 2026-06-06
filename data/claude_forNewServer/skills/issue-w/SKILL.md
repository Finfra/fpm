---
name: issue-w
title: "Web Domain Issue Management Skill"
description: "웹 개발 프로젝트 특화 이슈 관리 (issue-g 기반)"
date: 2026-03-29
---

> **⚠️ 필수**: 이 스킬을 사용하기 전에 반드시 `~/.claude/skills/issue-g.md`를 먼저 읽으십시오.
> - Issue.md 구조, HWM, 이슈 형식, 서브이슈, 워크플로우 → 모두 **issue-g에서 정의**
> - 이 문서는 **웹 개발 특화 확장 내용만** 제공합니다.

---

# 웹 개발 이슈 카테고리 가이드

웹 개발 과정에서 발생하는 이슈들을 다음과 같이 분류합니다.

| 카테고리     | 설명                                    | 예시                                  |
| ------------ | --------------------------------------- | ------------------------------------- |
| **Frontend** | UI/UX, 컴포넌트, 스타일, 렌더링         | 반응형 레이아웃, 폼 유효성 검사        |
| **Backend**  | 서버 로직, 비즈니스 계층, 데이터 처리   | REST API 구현, 인증 미들웨어           |
| **Infra**    | 배포, CI/CD, 환경 설정, 컨테이너        | Docker 설정, GitHub Actions           |
| **DB**       | 데이터베이스, 마이그레이션, 쿼리 최적화 | 스키마 변경, 인덱스 최적화             |
| **Security** | 인증/인가, 취약점, CORS, XSS 방어       | JWT 갱신 로직, 입력값 검증             |
| **Perf**     | 성능, 로딩 속도, 번들 최적화            | 이미지 최적화, 코드 스플리팅           |

---

# 웹 프로젝트 이슈 형식 확장

## 배포/인프라 이슈

```markdown
## Issue[번호]: [제목] (등록: YYYY-MM-DD)
* 목적: ...
* 상세:
    - 환경: dev / staging / prod
    - 증상: ...
    - 영향 범위: ...
```

## API 이슈

```markdown
## Issue[번호]: API [엔드포인트] [문제] (등록: YYYY-MM-DD)
* 목적: ...
* 상세:
    - Endpoint: METHOD /api/v1/...
    - 증상: ...
    - 재현 방법: ...
```

---

# 로컬 프로젝트 구성

웹 프로젝트의 로컬 `issue.md` 스킬에서:

## 1. issue-w 참조 명시

```markdown
> **기반**: 이 스킬은 `~/.claude/skills/issue-w.md` (웹 개발 특화)를 기반으로 합니다.
> `issue-w` → `issue-g` 순서로 글로벌 패턴을 상속합니다.
```

## 2. 프로젝트별 추가 규칙

- 프레임워크 특화 (React, Vue, Next.js, SvelteKit 등)
- 패키지 매니저 규칙 (npm / yarn / pnpm)
- 배포 환경 (Vercel, AWS, GCP, Cloudflare 등)
- 로컬 서브스킬 경로 정의

---

# 참고

- **완전한 표준**: `~/.claude/skills/issue-g.md` ← **항상 먼저 읽으세요**
- **웹 특화**: 이 문서 (issue-w)
- **macOS 앱 특화**: `~/.claude/skills/issue-m.md`
- **로컬 구현**: `<project>/.claude/skills/issue.md`

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../../rules/opus-4-7-execution-rules.md) 참조 (종료 조건·재시도·루프 상한·리터럴 해석·사용자 승인 지점).

이 스킬 특화 제약:
* 각 워크플로우 단계는 명시된 종료 조건 충족 시에만 다음 단계로 진행
* 외부 명령 실패 시 기본 재시도 1회, 실패 지속 시 사용자에게 원인 보고
* 파일·git·외부 시스템 변경은 dry-run 또는 승인 절차 포함
* 애매 표현("시도해봐", "필요 시", "가능하면") 금지 — 조건문으로 해석
