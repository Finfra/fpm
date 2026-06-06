---
name: fapp-parallel
description: "data/fapp.txt에서 fApp 프로젝트 목록을 읽어 팀을 구성하고, 커맨드를 병렬로 실행한 뒤 통합 리포트를 생성하며 팀을 자동 정리합니다."
date: 2026-04-18
---

`data/fapp.txt`에서 fApp 프로젝트 번호 목록을 읽어 팀을 구성하고, 동일한 작업(커맨드)을 **병렬로 실행**하는 에이전트입니다.

# 빠른 시작

## 기본 사용법
```bash
/fapp-parallel "실행할 커맨드"
```

## 실제 예시
```
/fapp-parallel "/issue"
/fapp-parallel "/issue-fix"
/fapp-parallel "/issue-reg"
/fapp-parallel "/issue-closer"
/fapp-parallel "/capture"
/fapp-parallel "/dev "Factory Reset" 통일"
```

# 사용 가능한 커맨드 카탈로그

이 에이전트가 팀원에게 위임할 수 있는 커맨드 분류.

## 프로젝트-로컬 커맨드 (팀원이 각자 프로젝트에서 실행)

각 팀원이 자신의 프로젝트 디렉토리에서 직접 실행하는 커맨드.
이 에이전트의 **주 사용 대상**.

| 커맨드           | 설명                                         | 비고                |
| :--------------- | :------------------------------------------- | :------------------ |
| `/issue`         | 이슈 상태 분석 → 자동 라우팅 (등록/해결)     | 디스패처            |
| `/issue-reg`     | 이슈 등록 (ID 발급, HWM 갱신)                | issue-manager 스킬  |
| `/issue-fix`     | 이슈 해결 (구현→검증→closer 호출)            | issue-closer 연쇄   |
| `/issue-closer`  | 이슈 종결 (해시 기록, 완료 이동)             | issue-manager 스킬  |
| `/capture`       | 프로젝트별 캡처 (각 프로젝트에 정의)         | 프로젝트 로컬 커맨드 |
| `/build`         | 프로젝트별 빌드 (각 프로젝트에 정의)         | 프로젝트 로컬 커맨드 |
| `/run`           | 프로젝트별 실행 (각 프로젝트에 정의)         | 프로젝트 로컬 커맨드 |
| 임의 프롬프트    | `/dev "..."`처럼 자유 형식 작업 지시          |                     |

## ___pm 일괄 관리 커맨드 (이 에이전트와 병렬 관계)

아래 커맨드는 `___pm` 프로젝트에서 **이 에이전트 대신** 직접 실행하는 일괄 관리 커맨드.
이 에이전트가 위임할 대상이 **아님** — 역할이 중복됨.

| 커맨드              | 설명                                  | 실행 방식             |
| :------------------ | :------------------------------------ | :-------------------- |
| `/fapp-build`       | 일괄 빌드 (tmux via `/cdf-fapp`)     | tmux 병렬             |
| `/fapp-run`         | 일괄 실행 (tmux via `/cdf-fapp`)     | tmux 병렬             |
| `/fapp-kill`        | 일괄 프로세스 종료 (via `/cdf-fapp`) | tmux 병렬             |
| `/fapp-push`        | 일괄 push (via `/cdf-fapp`)          | tmux 병렬             |
| `/fapp-pull`        | 일괄 pull (직접 git)                 | 순차                  |
| `/fapp-capture`     | 일괄 캡처 (**순차 전용**)            | 순차 (충돌 방지)      |
| `/fapp-restart`     | kill → run 순차                      | 순차                  |
| `/cdf-fapp`         | fApp tmux 세션 생성                  | tmux                  |
| `/fapp-*-ma`        | ma 리모트 실행 (sma 경유)           | SSH                   |

# 워크플로우 (자동 실행)

## Step 0: fApp 목록 읽기 및 커맨드 분류

```bash
FAPP_FILE="$HOME/_git/___pm/data/fapp.txt"
NUMS=($(cat "$FAPP_FILE"))
base_dir="$HOME/_git/___pm/projects"

# 각 번호의 프로젝트 경로와 이름 해석
declare -a PATHS APPS
for num in "${NUMS[@]}"; do
  path=$(eval echo $(cat "${base_dir}/${num}"))
  PATHS+=("$path")
  APPS+=("$(basename "$path")")
done
```

입력된 커맨드를 분석하여 실행 방식 결정:
* **프로젝트-로컬 커맨드** (`/issue*`, `/capture`, `/build`, `/run`, 임의 프롬프트) → 팀 병렬 실행
* **___pm 일괄 커맨드** (`/fapp-*`) → 에러: "이 커맨드는 /fapp-parallel이 아닌 ___pm에서 직접 실행하세요"

## Step 1: 팀 생성

팀 이름 자동 생성 (예: `fapp-parallel-20260325-153042`)

## Step 2: 에이전트 배치 (프로젝트별)

`data/fapp.txt`에서 읽은 번호 각각에 대해 `{프로젝트명}-agent` 생성:
* 각 에이전트의 working directory를 해당 프로젝트 경로로 설정
* 주어진 커맨드 실행
* 완료 후 결과 메시지 전송

### 에이전트 프롬프트 구성

각 팀원에게 전달하는 프롬프트에 포함할 내용:
1. 프로젝트 경로 (`cd {path}`)
2. 실행할 커맨드 (사용자 입력 그대로)
3. 결과 보고 형식:
    - 실행 상태 (성공/실패/경고)
    - 커밋 해시 (있을 경우)
    - 변경 파일 수
    - 주요 변경 내용 요약

### 이슈 관련 커맨드 실행 시 유의사항

`/issue*` 커맨드 실행 시 각 팀원에게 다음을 안내:
* 이슈 파일은 각 프로젝트의 `Issue.md`에서 관리
* `.claude/rules/issue-rules.md` 규칙 준수 (각 프로젝트에 있을 경우)
* `/issue` 디스패처는 상태 분석 → `/issue-reg` 또는 `/issue-fix` 자동 라우팅
* `/issue-fix` 완료 시 `/issue-closer`가 자동 호출됨

## Step 3: 결과 수집

각 팀원으로부터 완료 메시지 수신 (실행 상태, 커밋 해시, 변경 파일 수)

## Step 4: 통합 리포트 생성

`~/Desktop/fapp-parallel-report-{timestamp}.md` 생성 (템플릿: `data/fapp-report-template.md`)

## Step 5: 팀 자동 정리

모든 팀원 `shutdown_request` → `shutdown_approved` → `TeamDelete`

## Step 6: 리포트 오픈

# 입력 파라미터

| 파라미터  | 설명                            | 예시     |
| :-------- | :------------------------------ | :------- |
| `command` | 모든 프로젝트에서 실행할 커맨드 | `/issue` |

# 자동 처리 항목

* 팀 생성 (`TeamCreate`)
* 에이전트 배치 (`Agent` 도구)
* 팀원 커맨드 전송 (`SendMessage`)
* 팀원 종료 요청 (`shutdown_request`)
* 리포트 생성 및 오픈 (`open` 명령)
* 팀 정리 (`TeamDelete`)

# 주의사항

* fApp 목록은 `data/fapp.txt`에서 읽음 (프로젝트 추가/제거 시 이 파일만 수정)
* 각 번호에 대응하는 경로는 `projects/{번호}` 파일에서 읽음
* 각 프로젝트 경로가 존재해야 하며, git 권한 필요
* 팀원이 `shutdown_approved` 미전송 시 팀 삭제 실패 → 수동 확인 필요
* `/fapp-capture`는 순차 전용 — 이 에이전트로 `/capture`를 병렬 실행하면 충돌 가능. 개별 프로젝트의 `/capture`를 실행할 때는 주의 필요
* `/fapp-*` 일괄 커맨드는 이 에이전트의 역할과 중복되므로 위임 불가

# 관련 파일

* 리포트 템플릿: `data/fapp-report-template.md`
* 프로젝트 참조: `data/fapp-projects.md`
* 아키텍처 문서: `_doc_arch/Harness/Harness.md`



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 agent 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
