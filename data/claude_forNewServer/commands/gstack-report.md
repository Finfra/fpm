---
name: gstack-report
description: gstack v1.12.1.0 /ship 완료 후 nPTiR report 자동 생성 + Issue.md 커밋 해시 갱신
date: 2026-04-24
---

# /gstack-report {이슈번호}

> **규칙 로드**: 실행 전 `~/.claude/_doc_arch/gstack-nptir-rules.md` 를 Read할 것.

gstack `/ship`·`/land-and-deploy` 완료 후 결과를 nPTiR report 파일로 구조화하여 저장하고 `Issue.md` 해당 이슈의 커밋 해시 필드를 자동 갱신함.

# 입력

* `{이슈번호}`: 정수 (ex: `5`) — Issue.md에 등록된 진행중 이슈 번호
* 인자 없으면 사용자에게 1회 질의

# 동작

## 1. 사전 확인

* nPTiR 루트 위치 확인: 가장 가까운 `Issue.md` 디렉토리
* `Issue.md`에서 `Issue{번호}` 항목 존재 확인 → 없으면 즉시 종료 + 사용자 보고
* 진행중 섹션에 있어야 함 (완료 섹션이면 경고)
* 동일 이슈 report 존재 시 덮어쓰기 금지 → 사용자 확인 후 진행

## 2. 메타데이터 수집

git 명령으로 자동 수집 (각 1회 실행, 실패 시 사용자 보고):

```bash
# 이슈 관련 커밋 해시 (메시지에 Issue{번호} 포함)
git log --oneline --grep="Issue{번호}" -20

# 변경 파일 목록
git diff --name-only {first-commit}^..HEAD

# PR URL (있을 경우)
gh pr list --state all --search "Issue{번호}" --json url,number,state --limit 5
```

## 3. report 파일 생성

**경로**: `{nPTiR루트}/_doc_work/report/{주제}_issue{번호}_report.md`

`{주제}`는 plan 파일명 또는 Issue.md 항목 제목에서 추출 (kebab-case 변환).

**frontmatter 템플릿**:

```yaml
---
name: {주제}_issue{번호}_report
description: Issue{번호} {제목} 해결 report
date: {오늘 날짜 YYYY-MM-DD}
issue: Issue{번호}
plan: _doc_work/plan/{주제}_plan.md
commits:
  - {hash1}
  - {hash2}
pr_url: {gh pr list URL, 없으면 생략}
deploy_url: {/land-and-deploy 출력 URL, 없으면 생략}
---
```

**본문 구조**:

```markdown
# 요약

{이슈 목적과 해결 결과 1-2 문단}

# 변경 내역

## 커밋

| 해시       | 메시지                          | 일시               |
| :--------- | :------------------------------ | :----------------- |
| {hash1}    | {커밋 메시지}                   | {YYYY-MM-DD HH:MM} |

## 파일

| 경로                     | 변경 유형 |
| :----------------------- | :-------- |
| {path/to/file.ext}       | M / A / D |

# 검증

## 빌드·테스트

{/ship 출력의 test/lint/typecheck 결과 요약}

## QA

{/qa 또는 /qa-only 결과 (있을 경우). 없으면 "수행되지 않음"}

## 보안

{/cso 또는 /review 결과 (있을 경우). 없으면 "수행되지 않음"}

# 배포

## PR

* URL: {pr_url}
* 상태: {open/merged/closed}

## Production

{/land-and-deploy 결과. canary 결과 포함 (있을 경우)}

# 후속

{follow-up TODO, 보류 항목 (있을 경우)}
```

## 4. Issue.md 갱신

해당 `Issue{번호}` 항목 헤더에 다음을 추가:

```markdown
## Issue{번호}: {제목} (등록: YYYY-MM-DD, 해결: {오늘 날짜}, commit: {hash1, hash2}) ✅
```

또한 항목 본문에 `* report:` 라인 추가 (`* plan:`, `* task:` 다음 줄):

```markdown
* report: `_doc_work/report/{주제}_issue{번호}_report.md`
```

**주의**: 이슈를 진행중 → 완료 섹션으로 이동하지 않음. 사용자가 명시적으로 `/issue-closer-g` 실행해야 이동.

## 5. gstack 출력 보존

`/ship` 출력에는 다음 정보가 포함됨:

* features shipped count
* logical SLOC delta (raw LOC 아님)
* tier 2 prose 형식의 jargon 풀이

→ report 본문에 그대로 반영하고 요약·재포맷 시에도 jargon 풀이 라인 보존.

# 출력

* 생성 report 파일 경로
* Issue.md 변경 라인 수
* 다음 단계 안내: "이슈를 완료 처리하려면 `/issue-closer-g {번호}` 실행"

# 종료 조건

* report 파일 생성 완료
* Issue.md 갱신 완료 (해결 일시 + 커밋 해시 + report 링크)
* 사용자에게 결과 보고
* **자동으로 이슈 완료 이동·git push 진행 금지**

# 참조

* nPTiR 규칙: `~/.claude/rules/nptir-rules.md`
* gstack ↔ nPTiR 연동: `~/.claude/_doc_arch/gstack-nptir-rules.md`
* 이슈 종결 절차: `~/.claude/commands/issue-closer-g.md`

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* 동일 이슈 report 존재 시 덮어쓰기 금지 — 사용자 승인 후 진행
* 이슈 상태 변경(진행중→완료)은 본 커맨드에서 수행하지 않음 — `/issue-closer-g` 책임
* git 명령 실패 시 1회 재시도 후 사용자 보고
* PR/deploy URL이 없어도 진행 — frontmatter에서 해당 필드만 생략
