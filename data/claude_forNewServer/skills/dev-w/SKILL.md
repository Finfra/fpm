---
name: dev-w
description: "웹 개발 프로젝트 특화 개발 주기 (dev-g 기반)"
---

> **필수**: 이 스킬을 사용하기 전에 반드시 `~/.claude/skills/dev-g/SKILL.md`를 먼저 읽으십시오.
> - 개발 주기 패턴(Case A/B), 완료 프로토콜, 의존 커맨드 → 모두 **dev-g에서 정의**
> - 이 문서는 **웹 개발 특화 확장 내용만** 제공합니다.

---

# 웹 프로젝트 빌드 및 검증

## 빌드 단계

`/issue-fix` 구현 완료 후, 코드 커밋 전에 다음을 수행:

1. **린트 검사**
   ```bash
   npm run lint   # 또는 yarn lint, pnpm lint
   ```
2. **타입 체크** (TypeScript 프로젝트):
   ```bash
   npx tsc --noEmit
   ```
3. **빌드 확인**:
   ```bash
   npm run build
   ```

## 테스트 단계

| 단계           | 명령                       | 설명                        |
| -------------- | -------------------------- | --------------------------- |
| Unit Test      | `npm run test`             | Jest / Vitest 등            |
| E2E Test       | `npx playwright test`     | Playwright / Cypress        |
| 브라우저 확인  | 로컬 서버 실행 후 수동 확인 | 크로스 브라우저 검증        |

## 로컬 서버 검증

웹 프로젝트는 UI 변경 이슈 해결 시 **로컬 서버 기반 검증**을 권장:

1. `npm run dev` (또는 프로젝트별 dev 명령)로 로컬 서버 실행
2. 변경 사항 브라우저에서 확인
3. 반응형 레이아웃 검증 (필요시)

---

# 웹 프로젝트 완료 프로토콜 확장

dev-g의 완료 프로토콜에 다음 단계를 **코드 커밋 전에** 추가:

1. 린트 통과 확인
2. 타입 체크 통과 (TypeScript 프로젝트)
3. 빌드 성공 확인
4. 테스트 통과 확인

이후 dev-g 완료 프로토콜 (커밋 → 해시 확보 → 이슈 종결 → 문서 커밋 → 알림) 진행.

---

# 웹 개발 카테고리

| 카테고리     | 설명                                    | 빌드/테스트 영향          |
| ------------ | --------------------------------------- | ------------------------- |
| **Frontend** | UI/UX, 컴포넌트, 스타일, 렌더링         | 린트 + 브라우저 확인 필수 |
| **Backend**  | 서버 로직, 비즈니스 계층, 데이터 처리   | Unit Test 필수            |
| **Infra**    | 배포, CI/CD, 환경 설정, 컨테이너        | 빌드 검증 필수            |
| **DB**       | 데이터베이스, 마이그레이션, 쿼리 최적화 | 마이그레이션 테스트       |
| **Security** | 인증/인가, 취약점, CORS, XSS 방어       | 보안 테스트               |
| **Perf**     | 성능, 로딩 속도, 번들 최적화            | 번들 분석                 |

---

# 배포 환경별 고려사항

| 환경           | 빌드 명령 예시                   | 추가 확인                 |
| -------------- | -------------------------------- | ------------------------- |
| Vercel         | `vercel build`                   | Edge Function 동작        |
| Cloudflare     | `wrangler deploy --dry-run`      | Workers 호환성            |
| Docker         | `docker build -t app .`          | 이미지 크기, 헬스체크     |
| GitHub Actions | CI 파이프라인 확인               | 워크플로우 정상 실행      |

---

# 로컬 프로젝트 구성

웹 프로젝트의 로컬 `dev.md` 스킬에서:

## 1. dev-w 참조 명시

```markdown
> **기반**: 이 스킬은 `~/.claude/skills/dev-w/SKILL.md` (웹 개발 특화)를 기반으로 합니다.
> `dev-w` → `dev-g` 순서로 글로벌 패턴을 상속합니다.
```

## 2. 프로젝트별 추가 정의

- 프레임워크 (React, Vue, Next.js, SvelteKit 등)
- 패키지 매니저 (npm / yarn / pnpm)
- 배포 환경 (Vercel, AWS, GCP, Cloudflare 등)
- 완료 알림 방식
- 추가 검증 단계

---

# 참고

- **완전한 표준**: `~/.claude/skills/dev-g/SKILL.md` ← **항상 먼저 읽으세요**
- **웹 개발 특화**: 이 문서 (dev-w)
- **macOS 앱 특화**: `~/.claude/skills/dev-m/SKILL.md`
- **로컬 구현**: `<project>/.claude/skills/dev.md`

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../../rules/opus-4-7-execution-rules.md) 참조 (종료 조건·재시도·루프 상한·리터럴 해석·사용자 승인 지점).

이 스킬 특화 제약:
* 각 워크플로우 단계는 명시된 종료 조건 충족 시에만 다음 단계로 진행
* 외부 명령 실패 시 기본 재시도 1회, 실패 지속 시 사용자에게 원인 보고
* 파일·git·외부 시스템 변경은 dry-run 또는 승인 절차 포함
* 애매 표현("시도해봐", "필요 시", "가능하면") 금지 — 조건문으로 해석
