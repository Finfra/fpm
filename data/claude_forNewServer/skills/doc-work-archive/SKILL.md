---
title: doc-work-archive
description: "nPTiR의 _doc_work/{plan,tasks,report,htm} 하위에 누적된 파일을 z_done/ 으로 이동하고 영향받는 참조를 자동 갱신하는 글로벌 스킬. plan/task/report 는 Issue.md ✅ 완료 기준, htm 은 age+keep-N 기준으로 선별 아카이브함."
date: 2026-07-19
---

> ⚠️ **글로벌 SCAR 변경 가드** (Issue46)
>
> 본 스킬은 모든 프로젝트가 공유. 즉흥 수정 금지.
>
> * cwd ≠ `~/.claude/` → 즉시 수정 금지, `~/.claude/Issue.md` 이슈 등록 후 별도 세션에서 처리
> * 절차: `~/.claude/rules/global-scar-change-rules.md`

# doc-work-archive

nPTiR 산출물(plan/task/report)과 hub 렌더 산출물(htm)이 `_doc_work/` 하위에 누적되면 탐색 비용이 증가함. 대상 파일을 `_doc_work/z_done/` 로 이동하고 영향받는 모든 참조를 자동 갱신함.

## 대상 종류 (kind)

| kind | 출처 | 선별 기준 | 이동 경로 |
| :--- | :--- | :--- | :--- |
| `plan` / `task` / `report` | `Issue.md` 의 `* plan:`/`* task:`/`* report:` 필드 | ✅ 완료 섹션의 이슈 | `z_done/{plan,report}/` (task 는 `z_done/plan/`) |
| `htm` (Issue289) | `_doc_work/htm/` 디렉토리 스캔 | **mtime age + keep-N** (아래 2.7단계) | `z_done/htm/` |

htm 은 특정 이슈에 매달린 산출물이 아니라서 "이슈 ✅ 완료" 신호를 쓸 수 없음. 그래서 시간·개수 기준으로 따로 판정함. 설계 SSOT: `~/_git/___pm/_doc_arch/htm-lifecycle-design.md`

## 트리거

다음 표현이 감지되면 본 스킬을 발동함:

- "doc-work-archive", "/doc-work-archive"
- "_doc_work 정리", "plan/task/report 아카이브", "htm 정리"
- "완료된 이슈 산출물 정리"

## 입력 조건

- 필수: nPTiR 루트(가장 가까운 `Issue.md` 보유 디렉토리) 탐지 가능해야 함
- 선택 인자:
    - 특정 이슈 번호 지정 (ex: `Issue2,Issue3`) — 미지정 시 ✅ 완료 섹션 전체
    - `--kind=htm` / `--kind=doc` — 한 종류만 처리 (미지정 시 양쪽 모두)
    - `--age=N` / `--keep=N` — htm 판정 임계 override (기본 age 7일 · keep 20개)

## 종료 조건

- 완료된 이슈의 산출물이 `_doc_work/z_done/` 하위로 전부 이동됨
- 판정 기준을 넘긴 htm 이 `_doc_work/z_done/htm/` 로 이동됨
- `Issue.md`의 `* plan:`/`* task:`/`* report:` 경로가 신규 위치로 갱신됨
- 이동된 파일의 frontmatter `plan:`/`task:` 상호 참조가 신규 위치로 갱신됨
- **이동된 모든 경로에 대한 repo 전역 참조가 갱신되고, 사후 grep 결과가 0건임** (5-3)
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
- `HOLD_CONFIG`: `$NPTIR_ROOT/data/doc_work_archive.md` (존재 시 프로젝트 hold 정책 로드 — 2.5단계)

### 2단계: 완료 이슈 파싱

`$NPTIR_ROOT/Issue.md`에서 `✅ 완료` 섹션 블록을 추출하고, 각 이슈 항목에서 다음 패턴을 수집:

```
## Issue{N}: ... ✅
* plan: `_doc_work/plan/{name}_plan.md`      ← 있을 때만
* task: `_doc_work/plan/{name}_task.md`      ← 있을 때만 (legacy `tasks/` 경로도 읽음)
* report: `_doc_work/report/{name}_issue{N}_report.md`  ← 있을 때만
```

수집 항목: `(issue_number, kind, src_path)` 튜플 목록. 각 `src_path`에 대해 실제 파일 존재 여부 확인.

**필터**:
- 이미 `_doc_work/z_done/` 하위 경로 → 스킵 (재아카이브 금지)
- 파일 부재 → 경고 목록에 기록, 이동 대상에서 제외
- 프로젝트 hold 대상 (2.5단계 판정) → 스킵 (아카이브 제외, 보류 목록에 기록 + 경고)

### 2.5단계: 프로젝트 hold 정책 로드·적용 (Issue149)

일부 산출물은 완료 이슈에 속하더라도 후속 작업이 "안정화 후 착수" 예정이라 `z_done` 이동을 일시 보류해야 함. 프로젝트가 `data/doc_work_archive.md` 로 보류 대상을 선언하면 본 스킬이 이를 존중하여 graceful skip 함.

#### 설정 파일

- 경로: `$NPTIR_ROOT/data/doc_work_archive.md` (없으면 본 단계 전체 no-op — 무변경, 전체 항목 정상 진행)
- 형식: frontmatter yaml `hold:` 리스트. 각 항목 `path`(필수, `NPTIR_ROOT` 기준 상대) / `until`(필수, `YYYY-MM-DD`) / `reason`(선택)

```yaml
---
name: doc_work_archive
description: doc-work-archive 보류(hold) 정책 — z_done 이동 제외 대상
date: 2026-06-14
hold:
  - path: _doc_work/plan/glossary_task.md
    until: 2026-07-13
    reason: prj2 Issue2/T6 안정화 후 착수
---
```

> `.yml` 이 아닌 `.md` 인 이유: `~/_doc` 볼트 rename 훅이 비-`.md` 신규 파일을 `.md` 로 개명하므로, frontmatter 에 데이터를 둠.

#### 판정 규칙

각 이동 대상 항목의 `src_path`(NPTIR_ROOT 기준 상대)에 대해:

1. hold 설정 파일 부재 → 전체 항목 정상 진행 (무변경)
2. `src_path` 가 어떤 `hold[].path` 와도 불일치 → 정상 진행
3. 일치 + `until` 가 오늘보다 **미래** → **skip** (이동 대상에서 제외 + 보류 목록 기록 + 경고)
4. 일치 + `until` 가 오늘 이하 (경과) → 정상 진행 (hold 자동 해제)

ISO `YYYY-MM-DD` 문자열은 사전순 비교가 날짜순과 일치하므로 bash `[[ "$UNTIL" > "$(date +%Y-%m-%d)" ]]` 로 미래 여부 판정.

**이중 안전**: 본 단계는 5-1 hard-abort(미완료 이슈 산출물 공유 시 중단)의 앞단 graceful 게이트임. hold 로 미리 제외된 산출물은 4·5단계에 도달하지 않음.

### 2.7단계: htm 산출물 선별 (Issue289)

`--kind=doc` 이 지정되지 않았고 `$DOC_WORK/htm/` 이 존재하면 수행. 없으면 no-op.

#### 판정 규칙

| 규칙 | 기본값 | 설명 |
| :--- | :--- | :--- |
| age | 7일 | mtime 이 N일보다 오래된 파일만 이동 대상 |
| keep-N | 20개 | mtime 최신 N개는 age 와 무관하게 활성 폴더에 유지 |
| hold | `data/doc_work_archive.md` | 2.5단계 hold 정책을 htm 에도 동일 적용 |

두 규칙은 **AND** 로 적용함 — "age 초과" **이면서** "최신 20개 밖"인 파일만 이동. 최근 작업 맥락을 보존하기 위함이며, 파일이 20개 이하면 아무리 오래돼도 이동하지 않음.

```bash
HTM_DIR="$DOC_WORK/htm"
AGE_DAYS="${AGE_DAYS:-7}"
KEEP_N="${KEEP_N:-20}"
# mtime 내림차순 정렬 → 상위 KEEP_N 제외 → 그 중 age 초과분만 대상
ls -t "$HTM_DIR"/*.htm "$HTM_DIR"/*.html 2>/dev/null | tail -n +$((KEEP_N + 1)) | while read -r f; do
  [ -f "$f" ] || continue
  if [ "$(find "$f" -mtime +"$AGE_DAYS" -print 2>/dev/null)" ]; then
    printf '%s\n' "$f"
  fi
done
```

동반 파일(`*.dash.json` / `*.dash.yaml` / `*.dash.yml`)이 있으면 **같은 stem 끼리 묶어 함께 이동**함. htm 만 옮기고 dash 데이터를 남기면 hub 의 dashboard 항목이 반쪽이 됨.

#### hub registry 와의 관계

이동해도 hub 링크는 죽지 않음 — 서버가 등록 경로 부재 시 `z_done/htm/<basename>` 을 재탐색해 200 을 주고 registry 를 새 경로로 갱신함(Issue289 P1, 축 2). 따라서 본 스킬은 registry 를 직접 건드리지 않음.

### 3단계: 이동 계획 생성 (dry-run)

각 수집 항목에 대한 이동 계획을 표 형태로 출력:

```
| Issue | Kind   | From                                                   | To                                                      |
| :---- | :----- | :----------------------------------------------------- | :------------------------------------------------------ |
| 1     | plan   | _doc_work/z_done/plan/info-files-activation_plan.md           | _doc_work/z_done/plan/info-files-activation_plan.md     |
| 1     | report | _doc_work/z_done/report/info-files-activation_issue1_report.md| _doc_work/z_done/report/info-files-activation_issue1_report.md |
| 2     | plan   | ...                                                    | ...                                                     |
```

htm 은 이슈 컬럼 대신 판정 근거(age/순번)를 표시:

```
| Kind | Age  | Rank | From                                      | To                                             |
| :--- | :--- | :--- | :---------------------------------------- | :--------------------------------------------- |
| htm  | 34일 | 87   | _doc_work/htm/hub_htm_20260615_..._a_x.htm | _doc_work/z_done/htm/hub_htm_20260615_..._a_x.htm |
```

추가 출력:
- 누락된 파일 경고 목록 (이슈에 참조되었으나 실제 없음)
- hold 보류 목록 (프로젝트 hold 정책으로 아카이브 제외 — `path` / `until` / `reason`)
- htm 요약: `대상 N건 / 유지 M건 (keep-N=20, age=7일)`
- **갱신될 참조 N건** (5-3 사전 grep 결과, 파일별 집계) ← Issue289
- 갱신 대상 파일 목록:
    1. `Issue.md` (해당 이슈 항목의 `* plan:`/`* task:`/`* report:` 경로)
    2. 이동되는 task/report 파일의 frontmatter `plan:` 필드 (가리키는 plan도 이동되는 경우)
    3. 위 사전 grep 이 찾은 **모든 md/htm 본문 참조** (Issue289 — 기본 포함)

**사용자 승인 대기** — 승인 전까지 실제 파일 이동·수정 금지.

### 4단계: 파일 이동 실행

사용자 승인 수신 후:

1. 대상 디렉토리 생성 (존재 시 no-op):
    ```bash
    mkdir -p "$DOC_WORK/z_done/plan" "$DOC_WORK/z_done/report" "$DOC_WORK/z_done/htm"
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
- `` `_doc_work/plan/{x}_task.md` `` → `` `_doc_work/z_done/plan/{x}_task.md` ``
- (legacy) `` `_doc_work/tasks/{x}.md` `` → `` `_doc_work/z_done/plan/{x}.md` ``
- `` `_doc_work/report/{x}.md` `` → `` `_doc_work/z_done/report/{x}.md` ``

동일 경로가 Issue.md의 **다른 이슈 항목(미완료)** 에서 발견되면 오류로 판단하고 중단 (동일 산출물을 두 이슈가 공유하는 비정상 상태). 이 hard-abort 는 그대로 유지되는 이중 안전장치이며, 정상적으로 보류해야 하는 산출물은 2.5단계 hold 정책이 앞단에서 graceful skip 으로 미리 제외함.

#### 5-2. 이동된 파일의 frontmatter 상호 참조 갱신

task 파일의 frontmatter `plan:` 필드가 이동된 plan을 가리키면 경로 갱신:

```yaml
---
plan: _doc_work/plan/{x}_plan.md       ← 갱신 전
plan: _doc_work/z_done/plan/{x}_plan.md  ← 갱신 후
---
```

- plan만 이동되고 task는 미이동인 경우에도 task의 frontmatter 갱신 필요
- 본문(body) 경로 문자열도 5-3 에서 함께 갱신함 (Issue289 — 구 "frontmatter만 갱신" 조항 폐기)

#### 5-3. repo 전역 참조 재작성 (기본 동작 — Issue289)

**이 단계는 옵션이 아니라 기본이다.** 종전에는 "전체 스캔"을 사용자가 명시할 때만 수행하고 본문 링크는 갱신하지 않았는데, 그 결과 아카이브를 할수록 문서 간 링크가 죽었다. 이제 `~/.claude/_doc_arch/rules-ondemand/rename-reference-rules.md` 의 5단계 절차를 그대로 따른다.

| 단계 | 동작 | 비고 |
| :-: | :--- | :--- |
| 1 | **사전 grep** — 4단계 이동 **전에** 전체 대상 경로의 참조 위치를 수집 | 이동 후에는 원본 경로 문자열을 못 찾음. 반드시 이동 전 |
| 2 | 이동 실행 (4단계) | — |
| 3 | **참조 갱신** — 1에서 수집한 위치를 전부 신규 경로로 치환 | Issue.md · frontmatter · **md 본문 링크** 포함 |
| 4 | **사후 검증** — 옛 경로 grep 결과 **0건** 확인 | 0건이 아니면 실패로 보고, 남은 위치 목록 제시 |
| 5 | 이동 + 참조 갱신을 **단일 commit** 권고 | 분리 시 중간 상태가 broken |

사전 grep (1단계):

```bash
# 이동 대상 상대경로 목록(MOVE_LIST)을 기준으로 참조 위치 수집
grep -rn --include="*.md" --include="*.htm" --include="*.html" \
  -F -f "$MOVE_LIST" "$NPTIR_ROOT" \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=graphify-out \
  > "$REF_HITS"
```

사후 검증 (4단계):

```bash
LEFT=$(grep -rn --include="*.md" --include="*.htm" --include="*.html" \
  -F -f "$MOVE_LIST" "$NPTIR_ROOT" \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=graphify-out | wc -l)
[ "$LEFT" -eq 0 ] || echo "⚠️ 미갱신 참조 $LEFT 건 — 아래 목록 확인 필요"
```

**제외 디렉토리 주의**: `graphify-out/`(생성물)·`.git/`·`node_modules/` 는 갱신 대상이 아님. `graphify-out` 은 `graphify update .` 로 재생성되므로 직접 치환하면 안 됨.

**dry-run 표시 의무**: 3단계 dry-run 출력에 "갱신될 참조 N건"을 파일별로 함께 제시함. 참조 갱신 범위를 사용자가 승인 전에 알 수 있어야 함.

### 6단계: 요약 보고

```
이동 완료: {N}건
  - plan:   {n_plan}건
  - tasks:  {n_task}건
  - report: {n_report}건
  - htm:    {n_htm}건 (age>{age}일 & keep-{keep} 밖)

갱신 완료:
  - Issue.md: {k}개 경로
  - frontmatter 상호 참조: {m}개 파일
  - 본문 참조(repo 전역): {r}개 파일
  - 사후 검증 잔존 참조: {left}건  ← 0 이어야 정상

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

### legacy `tasks/`·`task/` 디렉토리 처리 (2026.07.31 전환)

**task 전용 폴더는 폐지됐다** — 신규 task 는 `_doc_work/plan/{주제}_task.md` 다(SSOT: [`_doc_arch/rules-ondemand/nptir-rules.md`](../../_doc_arch/rules-ondemand/nptir-rules.md) "task 폴더 폐지").

본 스킬은 Issue.md 가 참조하는 경로를 그대로 따르므로 전환기에는 두 형태가 섞인다:

| 참조 경로 | 처리 |
| :--- | :--- |
| `_doc_work/plan/{x}_task.md` (신규 규약) | `z_done/plan/` 으로 이동 |
| `_doc_work/tasks/{x}.md` (legacy 복수) | **`z_done/plan/` 으로 이동** — `z_done/tasks/` 를 새로 만들지 않는다 |
| `_doc_work/task/{x}.md` (과거 오타, 단수) | 위와 동일. 경고 1줄 출력 후 `z_done/plan/` |

* **이미 존재하는 `z_done/tasks/` 는 건드리지 않는다** — 당시 규약을 반영한 역사 기록. 소급 이동 대상 아님
* 이동 후 원본 `tasks/`·`task/` 디렉토리가 비면 **제거**하고 요약에 보고한다

### 재아카이브 방지

`_doc_work/z_done/` 하위 경로를 가리키는 이슈 항목은 이미 아카이브된 것. 본 스킬은 이런 항목을 자동 스킵하며 경고도 출력하지 않음.

## 헬퍼 스크립트 (선택)

반복 사용 시 `scripts/archive.sh` 추가 가능 (현 버전에는 미포함). 단일 실행 기준 본 스킬 본문의 절차로 충분함.

## Opus 4.8 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-8-execution-rules.md`](../../rules/opus-4-8-execution-rules.md) 참조.

본 스킬 특화:

- **사용자 승인 필수 지점**: 3단계 dry-run 출력 후 4단계 실행 전
- **재시도 정책**: `git mv`/`mv` 실패 시 재시도 0회, 즉시 중단 + 원인 보고
- **루프 상한**: 이동 대상 파일 50건 초과 시 분할 요청으로 전환 (50건씩 배치).
  단 htm 대량 정리(Issue289 초기 마이그레이션 등 수백~수천 건)는 예외 — 참조 갱신 없이
  단일 `git mv` 배치로 처리 가능하므로, htm 전용(`--kind=htm`) 실행에 한해 배치 상한을 두지 않음.
  대신 dry-run 요약에 총 건수를 명시하고 승인받는다.
- **사후 검증 미통과 시**: 5-3 4단계 grep 이 0건이 아니면 완료로 보고하지 않음. 잔존 위치를
  목록으로 제시하고 사용자 판단을 요청 (조용한 성공 보고 금지)
- **부분 실패 복구**: N건 중 k건 이동 후 실패하면 **이미 이동된 k건은 롤백하지 않음**. 사용자에게 현 상태 보고 + git status 확인 권고
- **읽기 전용 검사**: 1~3단계는 파일 시스템 변경 없음. 4~5단계만 변경 수행
