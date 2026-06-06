---
title: CLAUDE.md
description: Claude Code가 이 저장소에서 작업할 때 참고하는 가이드
date: 2026-03-26
---

# 프로젝트 개요

프로젝트 관리(Project Management) 저장소. `~/_git/__all/` 하위 프로젝트들의 경로를 번호 인덱스로 관리하며, zsh 함수 `cdf`를 통해 빠르게 디렉토리 이동할 수 있게 해주는 시스템.

# 구조

* `projects/` - 번호 파일(0~57), 각 파일에 대상 디렉토리 경로가 한 줄로 저장됨 (전체 목록: `Projects.md`)
    - `0` → `~` (홈 디렉토리)
    - `1` → `~/_git/___pm` (이 저장소 자체)
    - `2` → `~/_doc` (옵시디언 볼트)
    - `3` → `~/.claude`
    - `11`~`16` → macOS App(fApp) 관리 대상 프로젝트 경로
    - `51`~`57` → CLI / 라이브러리
* `README.md` - 프로젝트 번호-경로 매핑 문서

# 프로젝트 도메인 매핑

* **SSOT**: `Projects.md`의 `Domain` 컬럼 (`g`, `w`, `m`, `g(cli)`, `g(Exe)`)
* **Harness 구조**: `Harness.md` 참조
* 프로젝트 번호로 작업 요청 시 `Projects.md`에서 Domain을 확인하고 해당 도메인의 글로벌 커맨드/스킬(`-g`, `-m`, `-w`)을 적용할 것

# cdf 함수군 (핵심 메커니즘)

`~/.zsh_functions`에 정의된 셸 함수. 공용 헬퍼 `_pm_manager()`가 `~/.info/__pmBasePath.txt`에서 베이스 경로(`projects/`)를 읽어 동작함.

| 함수   | 설명                                                   | 사용 예시                 |
| :----- | ------------------------------------------------------ | ------------------------- |
| `cdf`  | 터미널 디렉토리 이동 (복수 인덱스 시 iTerm2 수평 분할) | `cdf 10` / `cdf 11 12 13` |
| `cdff` | Finder에서 해당 경로 열기                              | `cdff 14`                 |
| `cdfc` | 해당 경로를 클립보드에 복사                            | `cdfc 2`                  |
| `cdfv` | VS Code로 해당 경로 열기 (복수 가능)                   | `cdfv 0 1 2 10`           |

* 인자 없이 실행 시 전체 프로젝트 목록 출력
* 인덱스 파일이 없으면 에러 반환

# Keyboard Maestro 연동

| 매크로                                  | 설명                                                                                 |
| :-------------------------------------- | ------------------------------------------------------------------------------------ |
| `iterm - input num for broadcast input` | iTerm2 패널 여러 개에 동시 입력 → `cdf` + 번호로 각 패널을 프로젝트 디렉토리로 이동 |

# Claude Code 커맨드 (`.claude/commands/`)

fApp(macOS 앱 11~16) 일괄 관리용 커맨드:

| 커맨드                               | 설명                                          |
| :----------------------------------- | --------------------------------------------- |
| `cdf-fapp-ma`                        | ma에서 fApp tmux 세션 생성                   |
| `fapp-build`                         | fApp 프로젝트 일괄 `/build` 실행              |
| `fapp-run` / `fapp-run-ma`           | fApp 프로젝트 일괄 실행 (로컬/ma)            |
| `fapp-kill` / `fapp-kill-ma`         | fApp 프로세스 일괄 종료 (로컬/ma)            |
| `fapp-pull` / `fapp-pull-ma`         | fApp 프로젝트 일괄 pull (로컬/ma)            |
| `fapp-push`                          | fApp 프로젝트 일괄 push                       |
| `fapp-capture` / `fapp-capture-ma`   | fApp 프로젝트 일괄 `/capture` 실행 (로컬/ma) |
| `fapp-restart`                       | fApp 프로세스 종료 후 재실행                   |
| `cdf`                                | tmux pm 세션 범용 관리 (window/pane 생성·명령전달) |
| `cdf-fapp`                           | fApp 기본값 설정 후 `/cdf` 위임                |

프로젝트 관리 커맨드 (글로벌 `~/.claude/commands/`):

| 커맨드                               | 설명                                          |
| :----------------------------------- | --------------------------------------------- |
| `pm-new`                             | 프로젝트 타입별 초기화 (일반/웹/맥)           |
| `pm-del`                             | 프로젝트 안전 제거 (백업 이동)                |
| `pm-update`                          | 기존 프로젝트 SCAR·템플릿·폴더 최신화        |
| `pm-query`                           | 프로젝트 조회·검색                            |
| `pm-do`                              | 다른 prj로 명령 위임 + 동기 블로킹 + 의존성(`* depends:`) 자동 해결 |

# Claude Code 스킬 (`.claude/skills/`)

| 스킬                    | 설명                                                                          |
| :---------------------- | :---------------------------------------------------------------------------- |
| `sync-ma`               | jm4 → ma 동기화 통합 스킬 (인자: `claude`/`pm`/`fapp`/`all`, 기본값: `all`) |
| `pm`                    | 프로젝트 관리 스킬 (pm-new, pm-del, pm-update, pm-query 공통 로직)            |

# Claude Code 에이전트 (`.claude/agents/`)

서브에이전트를 생성·관리하는 오케스트레이터:

| 에이전트              | 설명                                                        |
| :-------------------- | :---------------------------------------------------------- |
| `fapp-parallel`  | fApp 6개 프로젝트에 팀을 구성하여 커맨드를 병렬 실행·리포트 |

# 프로젝트 추가/변경

`projects/` 폴더에 번호 파일을 생성하고 경로를 한 줄로 기록. `README.md`도 함께 업데이트할 것.

## graphify

This project has a graphify knowledge graph at `graphify-out/`.

* 토큰 절감 규칙: `.claude/rules/graphify-rules.md` 필독 (1차 기준)
* 핵심: `GRAPH_REPORT.md` / `graph.json` / `graph.html` 직접 Read 금지. `GRAPH_REPORT.brief.md` 있으면 최우선. `wiki/index.md` → 필요한 커뮤니티 1~2개만 선별 Read (일괄 금지)
* 코드/아키텍처 질문은 `graphify query/path/explain` CLI 우선, 일반 grep 금지
* 파일 수정 후: `graphify update .` (AST-only, 무비용)
* 보조 커맨드: `/graphify-prune` (리포트 압축), `/gq <질문>` (query 래퍼)
