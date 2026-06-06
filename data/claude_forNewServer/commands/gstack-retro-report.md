---
name: gstack-retro-report
description: gstack v1.12.1.0 /retro 출력을 nPTiR 주간 report 형식으로 저장 (features→commits→SLOC→raw LOC 순서)
date: 2026-04-24
---

# /gstack-retro-report

> **규칙 로드**: 실행 전 `~/.claude/_doc_arch/gstack-nptir-rules.md` 를 Read할 것.

gstack `/retro` 결과를 nPTiR 형식의 주간 report로 저장. v1.0.0 메트릭 우선순위(features → commits/PRs → SLOC → raw LOC) 준수.

# 입력

* 인자 없음 (현재 날짜 기준 주차 자동 계산)
* 옵션: `--week YYYY-Www` (특정 주차 지정, ex: `--week 2026-W16`)
* 옵션: `--force` (기존 report 덮어쓰기 허용)

# 동작

## 1. 사전 확인

* nPTiR 루트 위치 확인: 가장 가까운 `Issue.md` 디렉토리
* gstack 설치 확인: `test -d ~/.claude/skills/gstack` (없으면 즉시 종료 + 사용자 보고)
* `/retro` 결과 입력 방식:
    - 사용자가 `/retro` 출력을 미리 실행한 경우: 텍스트 직접 입력 받기
    - 또는 본 커맨드 내에서 `/retro` Skill 호출 후 결과 수신

## 2. 주차 계산

```bash
# 오늘 날짜 기준 ISO 주차 (YYYY-Www 형식)
date +%G-W%V
```

`--week` 옵션 사용 시 해당 값 사용.

## 3. report 파일 생성

**경로**: `{nPTiR루트}/_doc_work/report/retro_{YYYY}-W{WW}_report.md`

**중복 처리**:
* 파일 존재 + `--force` 없음 → 사용자에게 덮어쓰기 확인 1회 → 거부 시 종료
* 파일 존재 + `--force` 있음 → 즉시 덮어쓰기

**frontmatter 템플릿**:

```yaml
---
name: retro_{YYYY}-W{WW}_report
description: {YYYY}년 {WW}주차 엔지니어링 회고
date: {오늘 날짜 YYYY-MM-DD}
type: doc
week: {YYYY-Www}
period_start: {월요일 YYYY-MM-DD}
period_end: {일요일 YYYY-MM-DD}
---
```

**본문 구조** (v1.0.0 메트릭 우선순위 준수):

```markdown
# 요약

{한 문단 — 이번 주 핵심 성과 1-2 문장}

# Shipped

## Features

| 기능명           | 상태       | 관련 이슈   | PR/커밋     |
| :--------------- | :--------- | :---------- | :---------- |
| {feature name}   | shipped    | Issue{N}    | {PR# or hash} |

## Commits

* 총 커밋 수: **{N}**
* 주요 커밋:
    - {hash} {message}
    - ...

## PRs

* 총 PR: open {N} / merged {N} / closed {N}
* 머지된 PR:
    - #{num} {title}

# Code Volume (보조 지표)

## Logical SLOC

* 추가: **+{N}** (의미 있는 변경 라인)
* 삭제: **-{N}**
* 순증감: {+/-N}

## Raw LOC (컨텍스트)

* 추가: +{N} (생성 코드, 포맷 변경 포함)
* 삭제: -{N}

> **주의**: Raw LOC는 v1.0.0 정책상 **컨텍스트 지표**로만 활용. shipped features와 commits가 실질 성과 지표.

# Quality

## 테스트·CI

{/health 결과 (있을 경우) 또는 CI 통과율}

## 발견·해결 이슈

* 신규 등록: {N}
* 해결: {N}
* 진행중: {N}

# Insights

{gstack /retro의 패턴 분석·praise·growth area 섹션}

## Praise

{잘한 점}

## Growth Areas

{개선할 점}

# 다음 주 계획

{우선순위 항목 3-5개}
```

## 4. 메트릭 검증 체크

report 작성 후 다음 순서 확인:

1. `# Shipped` 섹션이 `# Code Volume` 섹션보다 위에 있는가?
2. `Logical SLOC`가 `Raw LOC`보다 위에 있는가?
3. Raw LOC에 "컨텍스트 지표" 주석이 있는가?

위반 시 자동 재정렬.

## 5. Issue.md 갱신 (선택)

다음 주 계획 항목 중 신규 작업이 있으면 `# 🌱 이슈후보` 섹션에 추가 제안 (사용자 승인 후 적용).

# 출력

* 생성 report 파일 경로
* 메트릭 요약 (features {N}, commits {N}, PRs {N})
* 다음 단계 안내: "이슈후보로 옮기려면 `/issue-reg-g {제목}` 실행"

# 종료 조건

* 주간 report 파일 생성 완료
* v1.0.0 메트릭 순서 검증 통과
* 사용자에게 결과 보고
* **자동으로 이슈 등록·다음 주 작업 진행 금지**

# 참조

* gstack `/retro` 스킬: `~/.claude/skills/gstack/retro/`
* gstack v1.0.0 CHANGELOG: `~/.claude/skills/gstack/CHANGELOG.md` (Smarter `/retro` metrics 섹션)
* nPTiR 규칙: `~/.claude/rules/nptir-rules.md`
* gstack ↔ nPTiR 연동: `~/.claude/_doc_arch/gstack-nptir-rules.md`

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* 동일 주차 report 존재 시 `--force` 없으면 덮어쓰기 금지 (사용자 승인 1회)
* `/retro` 결과를 임의로 요약·재해석 금지 — gstack 출력 그대로 보존
* 메트릭 순서(features → SLOC → raw LOC)를 임의 변경 금지
