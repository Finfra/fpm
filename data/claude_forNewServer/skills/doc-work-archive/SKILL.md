---
title: doc-work-archive
description: nPTiR의 _doc_work/{plan,tasks,report} 하위에 누적된 파일을 z_done/ 으로 이동하고 영향받는 참조를 자동 갱신하는 글로벌 스킬. Issue.md의 ✅ 완료 섹션을 기준으로 완료된 이슈의 산출물만 선별 아카이브함.
date: 2026-04-19
---

# doc-work-archive

nPTiR 산출물(plan/task/report)이 `_doc_work/` 하위에 누적되면 탐색 비용이 증가함. 완료된 이슈의 산출물을 `_doc_work/z_done/` 로 이동하고 영향받는 모든 참조를 자동 갱신함.

## 트리거

다음 표현이 감지되면 본 스킬을 발동함:

- "doc-work-archive", "/doc-work-archive"
- "_doc_work 정리", "plan/task/report 아카이브"
- "완료된 이슈 산출물 정리"

## 입력 조건

- 필수: nPTiR 루트(가장 가까운 `Issue.md` 보유 디렉토리) 탐지 가능해야 함
- 선택 인자: 특정 이슈 번호 지정 (ex: `Issue2,Issue3`) — 미지정 시 ✅ 완료 섹션 전체

## 종료 조건

- 완료된 이슈의 산출물이 `_doc_work/z_done/` 하위로 전부 이동됨
- `Issue.md`의 `* plan:`/`* task:`/`* report:` 경로가 신규 위치로 갱신됨
- 이동된 파일의 frontmatter `plan:`/`task:` 상호 참조가 신규 위치로 갱신됨
- 요약 보고 출력 후 종료

**자동으로 다음 단계 진행 금지** — 이슈 상태 변경(완료 이동), git commit 등은 별도 커맨드(`/issue-closer-g`, 수동 commit)로 처리.

## 워크플로우

### 1단계: nPTiR 루트 탐지

다음 순서로 1회씩 시도하고 첫 성공 시 확정. 전부 실패 시 사용자에게 경로 확인 요청.

1. 현재 작업 디렉토리에서 상위로 `Issue.md` 탐색 (`git rev-parse --show-toplevel` 경계까지)
2. 1단계 실패 시: CWD 또는 상위 3단계까지에서 `*.xcodeproj` 발견 → 그 부모 디렉토리(또는 형제 디렉토리 `prj25`, `prj26` 등)에서 `_doc_work/` 보유 폴더 탐색
3. 2단계 실패 시: 사용자에게 nPTiR 루트 경로 직접 입력 요청 후 중단

탐지 결과:
- `NPTIR_ROOT`: `Issue.md` 위치
- `DOC_WORK`: `$NPTIR_ROOT/_doc_work`

### 2단계: 완료 이슈 파싱

`$NPTIR_ROOT/Issue.md`에서 `✅ 완료` 섹션 블록을 추출하고, 각 이슈 항목에서 다음 패턴을 수집:

```
## Issue{N}: ... ✅
* plan: `_doc_work/plan/{name}_plan.md`      ← 있을 때만
* task: `_doc_work/tasks/{name}_task.md`     ← 있을 때만
* report: `_doc_work/report/{name}_issue{N}_report.md`  ← 있을 때만
```

수집 항목: `(issue_number, kind, src_path)` 튜플 목록. 각 `src_path`에 대해 실제 파일 존재 여부 확인.

**필터**:
- 이미 `_doc_work/z_done/` 하위 경로 → 스킵 (재아카이브 금지)
- 파일 부재 → 경고 목록에 기록, 이동 대상에서 제외

### 3단계: 이동 계획 생성 (dry-run)

각 수집 항목에 대한 이동 계획을 표 형태로 출력:

```
| Issue | Kind   | From                                                   | To                                                      |
| :---- | :----- | :----------------------------------------------------- | :------------------------------------------------------ |
| 1     | plan   | _doc_work/plan/info-files-activation_plan.md           | _doc_work/z_done/plan/info-files-activation_plan.md     |
| 1     | report | _doc_work/report/info-files-activation_issue1_report.md| _doc_work/z_done/report/info-files-activation_issue1_report.md |
| 2     | plan   | ...                                                    | ...                                                     |
```

추가 출력:
- 누락된 파일 경고 목록 (이슈에 참조되었으나 실제 없음)
- 갱신 대상 파일 목록:
    1. `Issue.md` (해당 이슈 항목의 `* plan:`/`* task:`/`* report:` 경로)
    2. 이동되는 task/report 파일의 frontmatter `plan:` 필드 (가리키는 plan도 이동되는 경우)

**사용자 승인 대기** — 승인 전까지 실제 파일 이동·수정 금지.

### 4단계: 파일 이동 실행

사용자 승인 수신 후:

1. 대상 디렉토리 생성 (존재 시 no-op):
    ```bash
    mkdir -p "$DOC_WORK/z_done/plan" "$DOC_WORK/z_done/tasks" "$DOC_WORK/z_done/report"
    ```

2. 각 항목에 대해 `git mv` 우선, git 추적 밖이면 `mv`:
    ```bash
    if git -C "$NPTIR_ROOT" ls-files --error-unmatch "$SRC_REL" >/dev/null 2>&1; then
      git -C "$NPTIR_ROOT" mv "$SRC_REL" "$DST_REL"
    else
      mv "$NPTIR_ROOT/$SRC_REL" "$NPTIR_ROOT/$DST_REL"
    fi
    ```

   `SRC_REL`/`DST_REL`은 `$NPTIR_ROOT` 기준 상대경로.

3. 이동 1건 실패 시: 즉시 중단하고 사용자에게 실패 원인 보고. 재시도 0회 (사용자 지시 시에만 재시도).

### 5단계: 참조 갱신

#### 5-1. Issue.md 경로 갱신

대상: 완료 섹션의 해당 이슈 항목.

변환 규칙 (역따옴표 포함 정확 치환):
- `` `_doc_work/plan/{x}.md` `` → `` `_doc_work/z_done/plan/{x}.md` ``
- `` `_doc_work/tasks/{x}.md` `` → `` `_doc_work/z_done/tasks/{x}.md` ``
- `` `_doc_work/report/{x}.md` `` → `` `_doc_work/z_done/report/{x}.md` ``

동일 경로가 Issue.md의 **다른 이슈 항목(미완료)** 에서 발견되면 오류로 판단하고 중단 (동일 산출물을 두 이슈가 공유하는 비정상 상태).

#### 5-2. 이동된 파일의 frontmatter 상호 참조 갱신

task 파일의 frontmatter `plan:` 필드가 이동된 plan을 가리키면 경로 갱신:

```yaml
---
plan: _doc_work/plan/{x}_plan.md       ← 갱신 전
plan: _doc_work/z_done/plan/{x}_plan.md  ← 갱신 후
---
```

- plan만 이동되고 task는 미이동인 경우에도 task의 frontmatter 갱신 필요
- 본문(body)에 있는 경로 문자열은 **갱신하지 않음** (frontmatter만 갱신). 본문 링크 갱신은 사용자 요청 시에만 수행.

#### 5-3. 추가 파일 스캔 (옵션)

사용자가 "전체 스캔" 옵션을 지정한 경우에만 수행:

```bash
grep -rln "_doc_work/plan/\|_doc_work/tasks/\|_doc_work/report/" \
  --include="*.md" "$NPTIR_ROOT"
```

발견 파일을 사용자에게 목록으로 제시하고 개별 승인 후 치환. 기본 동작에서는 수행 안 함 (범위 확장은 사용자 명시 요청 필요).

### 6단계: 요약 보고

```
이동 완료: {N}건
  - plan:   {n_plan}건
  - tasks:  {n_task}건
  - report: {n_report}건

갱신 완료:
  - Issue.md: {k}개 경로
  - frontmatter 상호 참조: {m}개 파일

경고: {w}건
  - {파일}: {사유}

다음 단계(수동):
  - git status 로 변경 확인
  - 필요 시 commit
```

## 주의 사항

### Mac 앱 프로젝트의 경우

`_doc_work/`가 프로젝트 루트가 아닌 Xcode 프로젝트 폴더(`prj25/_doc_work/`, `prj26/_doc_work/` 등) 내부에 위치할 수 있음. 이 경우:

- `Issue.md`는 프로젝트 최상위에 있음
- `Issue.md`의 경로 표기는 해당 `_doc_work`에 맞춘 **상대경로** (ex: `prj26/_doc_work/plan/foo_plan.md`)

탐지 순서에서 `*.xcodeproj` 기반 fallback이 이 케이스를 커버. 이동·갱신 시 상대경로 prefix를 보존함.

### 단수 `task/` 디렉토리 처리

과거 `_doc_work/task/` (단수) 오탈자가 남아있을 수 있음. 본 스킬은 Issue.md가 참조하는 경로를 그대로 따르므로:

- 단수 `task/` 참조 발견 시 경고 출력 후 사용자에게 선택 요청:
    1. 그대로 이동 (`z_done/task/`)
    2. 복수 `tasks/`로 마이그레이션 후 이동 (`z_done/tasks/`)

기본값 없음 — 사용자 명시 선택 필요.

### 재아카이브 방지

`_doc_work/z_done/` 하위 경로를 가리키는 이슈 항목은 이미 아카이브된 것. 본 스킬은 이런 항목을 자동 스킵하며 경고도 출력하지 않음.

## 헬퍼 스크립트 (선택)

반복 사용 시 `scripts/archive.sh` 추가 가능 (현 버전에는 미포함). 단일 실행 기준 본 스킬 본문의 절차로 충분함.

## Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../../rules/opus-4-7-execution-rules.md) 참조.

본 스킬 특화:

- **사용자 승인 필수 지점**: 3단계 dry-run 출력 후 4단계 실행 전
- **재시도 정책**: `git mv`/`mv` 실패 시 재시도 0회, 즉시 중단 + 원인 보고
- **루프 상한**: 이동 대상 파일 50건 초과 시 분할 요청으로 전환 (50건씩 배치)
- **부분 실패 복구**: N건 중 k건 이동 후 실패하면 **이미 이동된 k건은 롤백하지 않음**. 사용자에게 현 상태 보고 + git status 확인 권고
- **읽기 전용 검사**: 1~3단계는 파일 시스템 변경 없음. 4~5단계만 변경 수행
