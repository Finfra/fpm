---
name: dev-g
description: "모든 프로젝트에서 사용 가능한 이슈 기반 개발 주기 통합 패턴"
---

# 개발 주기 글로벌 패턴

모든 프로젝트에서 **일관된 이슈 기반 개발 주기**를 구축하기 위한 글로벌 스킬입니다.

## 필수 전제

> **어떠한 코드 작업 전에도 반드시 `Issue.md`에 이슈를 생성하고 `# 🚧 진행중` 상태로 등록해야 합니다.**
> 이슈 생성 없이 코드를 수정하는 것은 엄격히 금지됩니다.

## 사용법

- `/dev` — 자동 모드 (Issue.md 우선순위 기반)
- `/dev [N]` — 이슈후보 N번 즉시 등록 및 진행

## 실행 로직

### Case A: 인자가 있는 경우 (후보 번호 N)

1. `Issue.md`의 `# 🌱 이슈후보` 섹션에서 N번 항목 식별
2. **nPTiR 파일 확인**: `_doc_work/plan/`, `_doc_work/tasks/`에서 이 이슈후보와 관련된 파일 탐색
    - 있으면: 이슈 등록 시 자동 연결 (`/issue-reg` 3-1 단계)
    - 없으면: **생성하지 않음** — plan/task는 사용자가 명시적으로 요청할 때만 생성
3. `/issue-reg`로 이슈 등록 (진행중 상태로 전환, plan/task 파일 자동 연결)
4. `/issue-fix`로 해결 진행

### Case B: 인자가 없는 경우 (자동 모드)

1. 사용자 요청 분석 후 적합한 이슈 발급 (`/issue-reg`)
2. 이슈 내용 확인 후 `/issue-fix` 진행

## 완료 프로토콜 (CRITICAL)

아래 순서를 반드시 엄수해야 함:

1. **코드 커밋**: `git commit -m "Fix: IssueXXX ..."`
2. **해시 확보**: `git log -1 --format="%h"`
3. **이슈 종결**: `/issue-closer` 실행 (Issue.md 종결 처리 + 해시 기록)
4. **문서 커밋**: `git commit` (메시지: `Docs: Close IssueXXX`)
5. **완료 알림**: 프로젝트별 알림 방식 실행 (로컬 스킬에서 정의)

## 의존 커맨드

| 커맨드          | 역할                           |
| --------------- | ------------------------------ |
| `/issue-reg`    | 이슈 등록 (HWM -> ID -> 파일) |
| `/issue-fix`    | 이슈 해결 (구현 + 검증)       |
| `/issue-closer` | 이슈 종결 (해시 + 완료 이동)  |

## 로컬 프로젝트별 커스터마이징

### 3레이어 참조 구조

```
로컬 dev.md → dev-m (macOS) 또는 dev-w (웹) → dev-g (글로벌)
```

- **dev-m**: macOS 앱 특화 (Xcode 빌드/테스트, 코드 서명, UI 캡처, 앱 배포)
- **dev-w**: 웹 개발 특화 (프레임워크 빌드, 린트/테스트, 번들 최적화, 배포)

각 프로젝트는 로컬 `.claude/skills/dev.md`에서:

1. **도메인 스킬 참조** (해당하는 경우):
    - macOS 앱: `~/.claude/skills/dev-m/SKILL.md` (Xcode 빌드, 코드 서명, UI 캡처)
    - 웹 프로젝트: `~/.claude/skills/dev-w/SKILL.md` (프레임워크, 린트, 배포)
    - 기타: 직접 dev-g 참조
2. **프로젝트 특화 내용 추가**:
    - 이슈후보 참조 파일 경로 (ex: `_doc/WORK.md`)
    - 완료 알림 방식 (ex: `say 'Complished'`)
    - 추가 검증 단계 (ex: UI 캡처, QA 테스트)
    - 빌드/배포 연동

### 로컬 스킬 구성 예시

macOS 앱 프로젝트의 `<project>/.claude/skills/dev.md` 상단:
```markdown
> **기반**: 이 스킬은 `~/.claude/skills/dev-m/SKILL.md` (macOS 앱 특화)를 기반으로 합니다.
> `dev-m` → `dev-g` 순서로 글로벌 패턴을 상속합니다.
> - 개발 주기 패턴(Case A/B, 완료 프로토콜) → dev-g 정의
> - Xcode 빌드, 테스트, 코드 서명, UI 캡처 → dev-m 정의
> - 이 문서는 **이 프로젝트 특화 내용만** 추가 정의합니다.
```

웹 프로젝트의 `<project>/.claude/skills/dev.md` 상단:
```markdown
> **기반**: 이 스킬은 `~/.claude/skills/dev-w/SKILL.md` (웹 개발 특화)를 기반으로 합니다.
> `dev-w` → `dev-g` 순서로 글로벌 패턴을 상속합니다.
> - 개발 주기 패턴(Case A/B, 완료 프로토콜) → dev-g 정의
> - 프레임워크 빌드, 린트/테스트, 배포 → dev-w 정의
> - 이 문서는 **이 프로젝트 특화 내용만** 추가 정의합니다.
```

일반 프로젝트(dev-g 직접 참조)의 `<project>/.claude/skills/dev.md` 상단:
```markdown
> **기반**: 이 스킬은 `~/.claude/skills/dev-g/SKILL.md`를 기반으로 합니다.
> 개발 주기 패턴(Case A/B, 완료 프로토콜) → dev-g 정의
> 이 문서는 **이 프로젝트 특화 내용만** 추가 정의합니다.
```

## 설계 원칙

- **단순성**: 이슈 등록 -> 해결 -> 종결의 3단계 사이클
- **추적성**: 모든 작업에 이슈 ID와 커밋 해시 연결
- **확장성**: 프로젝트별 빌드/테스트/알림 커스터마이징 가능
- **일관성**: 글로벌 커맨드(`/issue-reg`, `/issue-fix`, `/issue-closer`) 재사용

## SP 자동화 경로 (선택)

task가 크거나 독립 서브태스크 다수일 때 superpowers 자동화 스킬을 호출할 수 있음. 기존 `/issue-reg` → `/issue-fix` → `/issue-closer` 흐름은 **변경 없음**이며, 본 경로는 `/issue-fix` 내부 구현 수단으로만 사용.

| 상황                                    | 권장 SP 스킬                              | 호출 조건                                    |
| :-------------------------------------- | :---------------------------------------- | :------------------------------------------- |
| plan 파일 기반 다단계 실행              | `superpowers:executing-plans`             | `_doc_work/plan/{주제}_plan.md` 존재 시      |
| 독립 서브태스크 다수 (상태 공유 없음)   | `superpowers:subagent-driven-development` | Claude Code 등 subagent 지원 환경            |
| 다중 버그·다중 도메인 동시 수정         | `superpowers:dispatching-parallel-agents` | 세부 가이드는 `/issue-fix-g` 병렬 섹션 참조  |

사용 원칙:

* SP 자동화 스킬 호출 **전**에 이슈가 이미 `# 🚧 진행중`에 등록되어 있어야 함 (필수 전제 준수)
* SP 출력의 jargon 풀이·체크포인트는 task 진행 기록에 보존 (요약 시에도 제거 금지)
* 종료 조건: SP 스킬 완료 → 기존 완료 프로토콜(커밋·해시·`/issue-closer`·알림) 순차 진행
* 상세 규칙: [`~/.claude/_doc_arch/sp-nptir-rules.md`](../../_doc_arch/sp-nptir-rules.md) 참조

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../../rules/opus-4-7-execution-rules.md) 참조 (종료 조건·재시도·루프 상한·리터럴 해석·사용자 승인 지점).

이 스킬 특화 제약:
* 각 워크플로우 단계는 명시된 종료 조건 충족 시에만 다음 단계로 진행
* 외부 명령 실패 시 기본 재시도 1회, 실패 지속 시 사용자에게 원인 보고
* 파일·git·외부 시스템 변경은 dry-run 또는 승인 절차 포함
* 애매 표현("시도해봐", "필요 시", "가능하면") 금지 — 조건문으로 해석
