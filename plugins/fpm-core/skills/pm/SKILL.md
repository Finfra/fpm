---
title: pm
description: 프로젝트 관리 스킬 (생성·삭제·업데이트·조회). pm-new, pm-del, pm-update, pm-query 커맨드의 공통 로직.
date: 2026-04-11
---

# 개요

프로젝트 관리(생성·삭제·업데이트·조회)를 위한 공통 스킬.
각 커맨드(`pm-new`, `pm-del`, `pm-update`, `pm-query`)가 action wrapper로 이 스킬을 호출함.

> 이 스킬은 `___pm` 프로젝트 로컬 스킬. `___pm` 컨텍스트에서 실행됨.

# SSOT 참조

| 항목           | 원본 (SSOT)                               | 용도                         |
| :------------- | :---------------------------------------- | :--------------------------- |
| `Issue.md`     | `___pm/data/template/Issue.md`            | 이슈 템플릿                 |
| 번호 대역 규칙 | `___pm/Projects.md` > `## 번호 대역 규칙` | 프로젝트 번호 할당 기준     |
| 템플릿 파일    | `___pm/data/template/`                    | 프로젝트 초기화 템플릿      |

# 프로젝트 타입

| 타입 | 파라미터값 | 도메인 서픽스 | Domain 레이어            |
| :--- | :--------- | :------------ | :----------------------- |
| 1    | `general`  | (없음)        | (없음) — dev-g 직접 참조 |
| 2    | `web`      | w             | `-w` (dev-w, issue-w 등) |
| 3    | `mac`      | m             | `-m` (dev-m, issue-m 등) |

# 번호 대역 규칙

> SSOT: `Projects.md` > `## 번호 대역 규칙` — 실행 시 Read하여 최신 정보 사용할 것.

# 핵심 파일 경로

```
___pm/
├── projects/              # 번호 파일 (각 파일에 경로 한 줄)
├── Projects.md            # 프로젝트 테이블 + 번호 대역 + setting Script
├── Harness.md             # SCAR 관리
├── _doc_work/
│   └── pm_history/        # 실행 이력 (실행당 파일 1개)
└── data/template/         # 프로젝트 초기화 템플릿
    ├── gitignore
    ├── Harness.md
    ├── Issue.md
    ├── noteForHuman.md
    ├── PROMPTS.md
    └── vscode.json
```

# 타입별 폴백 기본값 (Harness.md global layer)

수집 실패 시 아래를 사용:

## general
```
Skills: dev-g, issue-g, capture-g
Commands: /issue-reg-g, /issue-fix-g, /issue-closer-g
```

## web
```
Skills: dev-g, dev-w, issue-g, issue-w, capture-g, capture-w
Commands: /issue-reg-w, /issue-fix-w, /issue-closer-w
```

## mac
```
Skills: dev-g, dev-m, issue-g, issue-m, capture-g, capture-m, deploy-m, version-manager-m
Commands: /issue-reg-m, /issue-fix-m, /issue-closer-m
```

**필수 초기화**:

* **VERSION 파일**: 신규 mac 프로젝트 생성 시 git root에 `VERSION` 파일을 생성하고 `0.0.1` 기록. `~/.claude/rules/version-manager-rules.md` SSOT 원칙 준수 — xcodeproj/Info.plist/Formula.rb는 이 파일을 참조
* **기존 fApp 보강**: `pm-update` 실행 시 VERSION 파일이 없으면 현재 `MARKETING_VERSION` 또는 `0.0.1` 값으로 생성

# .gitignore 케이스 무결성 검증 (필수)

`.gitignore` 템플릿(`data/template/gitignore`)에 적힌 폴더 패턴은 실제 생성 폴더명과 **대소문자 완전 일치**해야 함. macOS HFS+ 기본은 case-insensitive지만 APFS·Linux·git 인덱스는 case-sensitive — 한쪽이 다르면 `.gitignore` 매칭이 조용히 실패함.

## pm-new 실행 시

`.gitignore` 복사 후 다음 검증을 수행하고 불일치 발견 시 즉시 수정:

```sh
# 템플릿이 명시한 프로젝트 폴더 패턴 (현행 표준)
EXPECTED_DIRS=(_doc_work _doc_arch .claude .vscode)

# 신규 프로젝트의 .gitignore에서 위 패턴이 정확한 케이스로 등장하는지 확인
for dir in "${EXPECTED_DIRS[@]}"; do
    grep -qx "$dir/\?" "$PROJECT_ROOT/.gitignore" || \
        echo "WARN: $dir 패턴이 .gitignore에 없거나 케이스 불일치"
done
```

## pm-update 실행 시 (마이그레이션)

기존 프로젝트의 `.gitignore`를 스캔하여 다음 알려진 오타를 자동 정정:

| 오타 패턴      | 정정 후         | 도입 시점                                           |
| :------------- | :-------------- | :-------------------------------------------------- |
| `_doc_Design`  | `_doc_arch`   | 템플릿 초기 커밋(305e543, 2026-04-15)에 포함된 오타 — 2026-05-08 정정 |

발견 시 사용자 컨펌 후 in-place 수정. history 파일 `# 변경 내역` 섹션에 기록.

# Harness.md global layer 자동 채움 절차

1. 동일 타입의 기존 프로젝트 탐색 (ex: 맥 → `~/_git/` 하위 fApp 프로젝트들)
2. 해당 프로젝트의 `Harness.md` 또는 `.claude/` 구조에서 global SCAR 목록 수집
3. 수집 불가 시 위 폴백 기본값 사용

채움 규칙:
* **global Layer > Skills**: General(`-g`) + 해당 Domain(`-m` 또는 `-w`) 스킬만 기재
* **global Layer > Commands**: 해당 도메인의 커맨드만 기재
* **global Layer > Agents, Rules**: 동일 타입 프로젝트에서 수집
* **local Layer**: 빈 상태로 생성

# vscode.json 컬러·이모지 선택 로직

1. `~/_git/` 하위 프로젝트들의 `.vscode/settings.json`에서 사용중인 `peacock.color` + 이모지 수집
2. 기존 사용 현황과 **타입별 컬러 톤** 참고하여 선택:
    - 일반: 중성/회색 계열
    - 웹: 파랑/청록 계열
    - 맥: 난색 계열
3. 이모지는 프로젝트 성격을 표현 (1~2개, 의미 있는 조합)
4. 기존 프로젝트와 중복 불가 (컬러 + 이모지 모두)

## window.title 포맷 (SSOT)

`.vscode/settings.json`의 `window.title`은 다음 단일 포맷으로 고정:

```jsonc
"window.title": "{이모지} ${rootName}${separator}${activeEditorShort}"
```

* `{이모지}`: `Projects.md` 이모지 컬럼 값 (1~2개). 템플릿 `data/template/vscode.json`의 `{{emoji}}` 토큰이 이 값으로 치환됨
* `${rootName}`·`${separator}`·`${activeEditorShort}`: VSCode 네이티브 변수 — `$` 유지, 치환 금지
* 참조 예: `~/_doc/.vscode/settings.json` (`🪨📝 ${rootName}...`)
* **주의**: 토큰은 `{{emoji}}` (mustache 스타일, `{{#color}}`와 일관). `${{emoji}}` 형태 금지 — 치환 후 `$` 가 잔존함

# 실행 이력 기록

모든 pm 커맨드(`pm-new`, `pm-del`, `pm-update`) 완료 후 `_doc_work/pm_history/` 폴더에 실행 단위 파일 생성.
`pm-query`는 조회 전용이므로 기록하지 않음.

> **상세 스키마는 `_doc_arch/Harness/plans/pm-skill-plan.md` 참조.** 본 문서는 요약만 기재.

## 파일명

```
{YYYY-MM-DD}-{id}-{action}-{번호}-{프로젝트명}.md
```

* `{id}`: 날짜별 일련번호. 매일 `1`부터 시작하며, 동일 날짜에 기존 파일이 있으면 최대 id + 1

## 필수 Frontmatter

```yaml
---
name: {파일명}
description: pm {action} - {프로젝트명} ({타입})
date: {YYYY-MM-DD}
action: {new|del|update}
project_id: {번호}
project_name: {프로젝트명}
type: {general|web|mac}
status: {success|partial|failed|cancelled}
---
```

## 본문 필수 섹션

모든 action 공통:

* `# 실행 정보` — 커맨드, 액션, 실행 시각, 사용자 컨펌, 결과
* `# 프로젝트` — 번호/이름/타입/Domain/경로
* `# 변경 내역` — action별 하위 섹션
* `# Git` — 커밋 해시 (해당되면)
* `# 비고` — 경고/예외/특이사항

## action별 하위 섹션 (변경 내역)

| action | 필수 하위 섹션                                              |
| :----- | :---------------------------------------------------------- |
| new    | 호출 형식(A/B), 추론 결과(B만), 생성된 파일, 생성된 폴더, 레지스트리 업데이트 |
| del    | 모드(backup/keep), 백업(backup만), 레지스트리 정리          |
| update | 실행 옵션, 사전 진단(Diff), 컨펌 결과, 추가됨/업데이트됨/스킵됨, 레지스트리 업데이트 |

> **금지**: 한 줄 요약만 적는 빈약한 형식. 변경 내역은 항상 항목별 리스트로 명시.

# ___pm/Harness.md 등록 절차

프로젝트 생성/변경 후, `___pm/Harness.md`에 SCAR 정보를 등록/업데이트함.

등록 내용:
```markdown
# {프로젝트명}
## main
* dev
* issue
    - /issue-reg-{suffix}
    - /issue-fix-{suffix}
    - /issue-closer-{suffix}
* capture
```

`{suffix}`는 타입별 도메인 서픽스 (일반→g, 웹→w, 맥→m).

# pm-new 자동 추론 (형식 B)

`/pm-new <대상>` (단일 인자) 호출 시 타입·번호 자동 할당:

## 타입 추론 (대상 폴더 내용)

| 우선순위 | 시그널                                              | 결과    |
| :------- | :-------------------------------------------------- | :------ |
| 1        | `*.xcodeproj`, `*.xcworkspace`, `Package.swift`     | `mac`   |
| 2        | `package.json`, `tsconfig.json`, `next.config.*`, `vite.config.*` | `web`   |
| 3        | (위 시그널 없음 또는 폴더 미존재)                   | `general` |

## 번호 자동 할당

1. `Projects.md` > `## 번호 대역 규칙`을 Read
2. 타입 → 대역 매핑 (대역표의 `타입` 컬럼은 `일반`/`맥` 2종만 구분):
    - `mac` → `맥` 대역 (현재 11~40)
    - `web` / `general` → `일반` 대역. 대역 `설명`과 프로젝트 성격을 맞춰 선택:
        + 외부/학습 웹앱 성격 → 최상단 `100~` 대역 우선
        + 내부 제작 웹·앱 → `60~79`
        + 외주 제작 → `80~99`
        + CLI → `51~59`
        + Video → `41~50`
        + 그 외 일반 → `0~10`(시스템) 등 남은 빈 번호
3. 매핑된 대역에서 비어 있는 가장 작은 번호 선택
4. 모든 대역이 가득 → 에러 + 사용자에게 대역 확장 요청

## 컨펌

추론 결과(`타입`/`번호`/`경로`)를 출력하고 **반드시 사용자 승인**. 거절 시 형식 A로 재시도 안내.

# 기존 프로젝트 흡수 (adopt) 모드

이미 개발 중인 프로젝트(자체 `.git`·`CLAUDE.md`·`Issue.md`·소스 보유)를 pm에 편입할 때 사용. `pm-new`의 무손상 변형 — 기존 파일·이력을 **절대 덮어쓰지 않고** 누락분만 보강함.

## 발동 조건

대상 폴더에 다음 중 하나라도 존재하면 adopt 모드로 전환 (template 신규 생성 금지):

* `.git/` (이미 git repo)
* `CLAUDE.md` / `Issue.md` / `README.md` (자체 문서 보유)
* 소스 디렉토리·파일 (빈 폴더가 아님)

## 멱등 처리 매트릭스

| 항목                    | 존재 시                                              | 부재 시                          |
| :---------------------- | :-------------------------------------------------- | :------------------------------- |
| `git init`              | **스킵** (기존 repo 유지)                           | 실행                             |
| `.gitignore`            | diff 후 nPTiR 누락 패턴만 추가 (덮어쓰기 금지)      | 템플릿 복사                      |
| `CLAUDE.md`             | **보존**. 글로벌 참조(`~/.claude/CLAUDE.md`) 한 줄 없으면 상단에만 추가 | 템플릿 생성 |
| `Issue.md`              | **보존** (커스텀 이슈 트래커 가능성)                | 템플릿 생성                      |
| `noteForHuman.md`       | 보존                                                | 템플릿 생성                      |
| `PROMPTS.md`            | 보존                                                | 템플릿 생성                      |
| `Harness.md`            | 보존                                                | 템플릿 + global layer 자동 채움  |
| `_doc_work/{plan,tasks,report,z_done}`, `_doc_arch` | 없는 서브폴더만 생성   | 전체 생성                        |
| `.vscode/settings.json` | **peacock 동기화** (아래 절차)                      | 템플릿 컬러·이모지 자동 선택     |
| initial commit          | **스킵**. 변경분만 별도 커밋(사용자 컨펌)           | initial commit                   |

* nPTiR 산출물·로컬 문서가 `.gitignore` 정책상 ignore 대상이면 `.gitkeep` 불필요 — 폴더만 생성

## .vscode/settings.json peacock 동기화 (필수 — 누락 빈발 지점)

adopt 시 `.vscode/settings.json` peacock 색과 `Projects.md` peacock.color가 **불일치**하면 조용히 깨짐. 다음 순서로 reconcile:

1. 대상 `.vscode/settings.json`에서 `"peacock.color"` 읽기
2. 분기:
    - **기존 색 존재 + 사용자가 신규 색 미지정** → 기존 색을 `Projects.md`에 채택 (vscode → pm). 개발자가 쓰던 색 존중
    - **사용자가 신규 색 지정** → `Projects.md` 색을 `.vscode/settings.json`에 반영 (pm → vscode). `peacock.color` + `workbench.colorCustomizations` surface 색군 + `window.title` 이모지 라인 모두 일관 갱신
    - **양쪽 부재** → 템플릿 컬러·이모지 자동 선택 (기존 `# vscode.json 컬러·이모지 선택 로직`)
3. 채택 색은 기존 프로젝트와 **중복 불가** (peacock-sync diff로 검증)
4. `window.title` 없거나 포맷 불일치면 `# window.title 포맷 (SSOT)` 기준으로 추가·정정
5. 완료 후 `/peacock-sync`(인자 없음)로 전체 일치 여부 dry-run 검증

## 종료 조건

누락분 보강 완료 + projects/{번호}·Projects.md 등록 + peacock 양방향 일치 확인 + history 기록. 기존 파일 변경 0건이면 commit 생략.

# pm-del 모드

| 모드     | 폴더 처리        | 레지스트리 정리 | 용도                                  |
| :------- | :--------------- | :-------------- | :------------------------------------ |
| `backup` | `~/_git/z_backup/`로 mv | O        | 기본. 폐기·중단 프로젝트 백업         |
| `done`   | `~/_git/z_done/`로 mv   | O        | 정상 완료된 프로젝트 보관             |
| `keep`   | 그대로 유지      | O               | 관리 체계에서만 빼고 소스는 보존      |

* 셋 다 사용자 컨펌 필수
* mv 대상 디렉토리(`z_backup/`, `z_done/`)는 없으면 자동 생성
* 동일 이름 충돌 시 `_{YYYYMMDD}_{N}` 서픽스 부여
* history 파일 frontmatter `mode` 필드:
    - `backup` → `# 변경 내역 > ## 백업` 섹션
    - `done`   → `# 변경 내역 > ## 완료 이동` 섹션
    - `keep`   → `# 변경 내역 > ## 폴더 보존` 섹션

# Action 라우팅

이 스킬은 action 파라미터에 따라 동작이 분기됨:

| action   | 동작                   | 상세 계획 문서                |
| :------- | :--------------------- | :---------------------------- |
| `new`    | 프로젝트 생성          | `pm-new-command-plan.md`      |
| `del`    | 프로젝트 제거 (백업)   | `pm-del-command-plan.md`      |
| `update` | 프로젝트 갱신          | `pm-update-command-plan.md`   |
| `query`  | 프로젝트 조회          | `pm-query-command-plan.md`    |

각 action의 상세 절차는 해당 커맨드 파일에서 정의됨.



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 skill 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
