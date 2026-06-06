---
name: nptir-rules
description: nPTiR(needs/Plan/Task/issue/Report) 파일 위치·연결·트리거 상세 규칙
date: 2026-04-14
---

# 파일 위치 규칙

- nPTiR 루트: 현재 작업 컨텍스트에서 가장 가까운 `Issue.md`가 있는 디렉토리
- plan → `{nPTiR루트}/_doc_work/plan/{주제}_plan.md`
- task → `{nPTiR루트}/_doc_work/tasks/{주제}_task.md` ← **복수형 `tasks/` 고정**
- report → `{nPTiR루트}/_doc_work/report/{주제}_issue{번호}_report.md`
- Issue.md 없으면 → 사용자에게 위치 확인 후 생성
- 이슈 번호 미정 시 report 파일명: `{주제}_report.md` → 이슈 연결 후 rename
- **needs 산출물 규칙**: 탐색 결과는 plan 파일 내 `## Needs Exploration` 섹션으로 흡수. `_doc_work/needs/` 폴더 미사용. Issue.md 이슈 포맷에 `* needs:` 필드 추가 금지 (산출물 단일화). 상세: [`sp-nptir-rules.md`](sp-nptir-rules.md), [`commands/needs.md`](../commands/needs.md)
- **needs → `_doc_arch` 저장 규칙**: needs 탐색 결과 중 영속 설계 문서로 보존 가치가 있는 경우 `_doc_arch/{주제}.md`에 저장. 저장된 경우 해당 plan frontmatter에 `arch:` 필드 추가:
    ```yaml
    arch: _doc_arch/{주제}.md
    ```
    `_doc_arch` 파일이 없으면 `arch:` 필드 생략.

## ⚠️ 경로 표기 고정 (재발 방지)

| 올바름                | 잘못됨 (금지)           | 비고                                                 |
| :-------------------- | :---------------------- | :--------------------------------------------------- |
| `_doc_work/tasks/`    | ~~`_doc_work/task/`~~   | 단수 `task/`는 과거 오타. 2026-04-14 `33ad8eb`에서 교정 |
| `_doc_work/plan/`     | ~~`_doc_work/plans/`~~  | plan은 단수                                          |
| `_doc_work/report/`   | ~~`_doc_work/reports/`~~| report는 단수                                        |

- **기존 프로젝트에 단수 `_doc_work/task/` 디렉토리가 남아있으면 복수 `tasks/`로 마이그레이션**
- Glob/find로 단수 참조 확인: `find _doc_work -maxdepth 1 -name task -type d`
- 기존 문서에 "단수 task가 규칙"이라 적혀 있어도 따르지 말 것. 박제된 오정보일 가능성 높음

# 파일 연결 규칙 (양방향)

## plan/task frontmatter

```yaml
---
name: {주제}_plan
description: ...
date: YYYY-MM-DD
issue: TBD          # 이슈 등록 후 Issue{번호}로 업데이트
arch: _doc_arch/{주제}.md   # needs → _doc_arch 파일이 있을 때만 포함
---
```

task는 plan도 추가:

```yaml
issue: TBD
plan: _doc_work/plan/{주제}_plan.md
```

## Issue.md 이슈 항목

plan/task 파일이 있으면 `* 목적:` 바로 아래에 경로 필드 추가:

```markdown
## Issue5: {제목} (등록: YYYY-MM-DD)
* 목적: ...
* plan: `_doc_work/plan/{주제}_plan.md`
* task: `_doc_work/tasks/{주제}_task.md`
* 상세:
    - ...
```

## 연결 업데이트 절차

`/issue-reg-g` 3-1 단계에서 자동 처리:

1. `_doc_work/plan/`, `_doc_work/tasks/` Glob으로 관련 파일 탐색
2. 발견 시: Issue.md에 `* plan:`, `* task:` 경로 추가
3. 발견 시: 해당 파일 frontmatter `issue: TBD` → `issue: Issue{번호}` 업데이트

# 자연어 트리거 상세

| 트리거 표현                                                     | 동작                                                                                       |
| :-------------------------------------------------------------- | :----------------------------------------------------------------------------------------- |
| "계획 세워줘", "plan 만들어줘", "{주제} 계획", "이슈후보N 계획" | `{주제}_plan.md` 생성, frontmatter `issue: TBD`                                            |
| "태스크 만들어줘", "task 만들어줘", "계획 기반 태스크"          | 기존 `{주제}_plan.md` 확인 → `{주제}_task.md` 생성, frontmatter `issue: TBD` + `plan: ...` |
| "report 만들어줘", "결과 정리해줘" (이슈 번호 있음)             | `{주제}_issue{번호}_report.md` 생성                                                        |
| "report 만들어줘" (이슈 번호 없음)                              | `{주제}_report.md` 생성 → 이후 rename                                                      |

**명시적 요청 없이는 plan/task/report 자동 생성 금지** — 사용자가 요청할 때만 생성.

# 이슈 복잡도 triage

이슈 등록 시 복잡도를 판정하여 산출물 범위를 결정함. 상세 근거·사례: [`_doc_arch/nptir-triage-design.md`](../_doc_arch/nptir-triage-design.md)

## 판정 기준 (2단계 질문)

* **Q1**: 변경 파일 3개 이하 + 방법이 자명한가?
    - Yes → **단순**
    - No → Q2
* **Q2**: 설계 결정이 후속 이슈에 영향을 주는가?
    - No → **중간**
    - Yes → **복잡**

## 단계별 산출물 정책

| 복잡도 | plan | task | report | 흐름                             |
| :----- | :--: | :--: | :----: | :------------------------------- |
| 단순   | ❌   | ❌   | ❌     | reg → fix → close 3단계만        |
| 중간   | ✅   | 선택 | 선택   | plan 필수, task/report는 가치 판단 |
| 복잡   | ✅   | ✅   | ✅     | 전체 사이클                      |

## report 생성 조건

report는 다음 중 하나에 해당할 때만 작성:
* 미래 작업자가 설계 결정 배경을 이해해야 함
* 완료 조건 검증 증거를 보존해야 함
* 사용자가 명시적으로 요청
* 복잡도 `복잡` 판정

## 적용 시점

* `issue-reg-g` 등록 시 — 단순 판정 시 plan/task 생성 제안 금지
* `issue-closer-g` 종결 시 — 단순/중간 이슈는 report 없이 종결 가능

# 프로젝트 루트 정리 규칙 (Root Cleanliness)

nPTiR 산출물(plan/task/report) 및 작업 부산물은 **절대 프로젝트 루트에 생성 금지**.
반드시 `_doc_work/{plan,tasks,report}/` 하위에 생성할 것.

## 루트 금지 패턴 (전체 프로젝트 공통)

| 금지 패턴 (루트)                       | 올바른 위치                          |
| :------------------------------------- | :----------------------------------- |
| `tasks.md`, `*_task.md`, `task_*.md`   | `_doc_work/tasks/`                   |
| `*_plan.md`, `plan_*.md`               | `_doc_work/plan/`                    |
| `*_report.md`, `report_*.md`           | `_doc_work/report/`                  |
| `verification_report_*.md`             | `_doc_work/report/`                  |
| `analyze_*.md`, `debug_*.md`           | `_doc_work/report/` 또는 `_doc_work/debug/` |
| 임시 테스트 스크립트(`run_*`, `test_*`) | 모듈 폴더 또는 `z_test/`             |
| `*.log`                                | `logs/`                              |

## 자동화 스킬 출력 경로 의무

`verify`, `test`, `tdd-runner`, `qa` 등 결과 보고서를 생성하는 스킬은
출력 경로를 **반드시 명시**할 것 (디폴트 `pwd`/루트 사용 금지):

```bash
## ❌ 금지
{cmd} > verification_report_$(date +%Y%m%d).md

## ✅ 권장
{cmd} > _doc_work/report/verification_report_$(date +%Y%m%d).md
{cmd} > logs/test/run_test_$(date +%Y%m%d-%H%M%S).log
```

## 신규 파일 생성 시 체크리스트

- [ ] 루트 화이트리스트(`README.md`, `CLAUDE.md`, `Issue.md`, 빌드/메타 파일 등)에 속하는가?
- [ ] 산출물(plan/task/report)이라면 `_doc_work/{plan,tasks,report}/`로 가는가?
- [ ] 로그라면 `logs/`로 가는가?
- [ ] 임시 스크립트라면 `z_test/` 또는 적절한 모듈 폴더에 가는가?

# nPTiR 초기화 조건

nPTiR 워크플로우를 시작하려면 아래 파일·폴더가 프로젝트 루트에 존재해야 함. 없을 경우 `/new-project` 또는 수동으로 생성.

## 필수 파일

| 파일 | 역할 |
| :--- | :--- |
| `Issue.md` | nPTiR 루트 식별자. 이슈 트래킹 SSOT |
| `CLAUDE.md` | Claude Code 지시사항 (글로벌 규칙 참조 포함) |
| `noteForHuman.md` | 사람이 읽는 프로젝트 메모 (AI 에이전트 미사용) |
| `PROMPTS.md` | 자주 쓰는 프롬프트 모음 |
| `Harness.md` | 프로젝트 로컬 스킬 목록 정의. 생성 시 [`~/_git/___pm/Harness.md`](../../_git/___pm/Harness.md)의 `# local` 섹션 패턴 참조 |

## 필수 폴더

| 폴더 | 역할 |
| :--- | :--- |
| `.claude/` | 프로젝트 전용 commands/rules/skills |
| `_doc_work/` | nPTiR 산출물 루트 (plan/tasks/report/z_done) |
| `_doc_arch/` | 영속 설계 문서 SSOT (needs → 설계 결정 보존) |

## `_doc_work/` 초기 서브폴더

```
_doc_work/
├── plan/       # Plan 산출물
├── tasks/      # Task 산출물
├── report/     # Report 산출물
└── z_done/     # 완료된 이슈 산출물 아카이브
```

## 초기화 체크리스트

- [ ] `Issue.md` 생성 (섹션: 이슈후보 / 진행중 / 우선순위 / 완료)
- [ ] `CLAUDE.md` 생성 (글로벌 `~/.claude/CLAUDE.md` 참조 한 줄 포함)
- [ ] `noteForHuman.md` 생성
- [ ] `PROMPTS.md` 생성
- [ ] `Harness.md` 생성
- [ ] `.claude/` 폴더 생성
- [ ] `_doc_work/plan/`, `_doc_work/tasks/`, `_doc_work/report/`, `_doc_work/z_done/` 생성
- [ ] `_doc_arch/` 폴더 생성
