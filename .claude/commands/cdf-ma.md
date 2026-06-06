---
title: "CDF-MA: ma에서 cdf 원격 실행"
description: "sma 에이전트를 통해 ma에서 cdf 스킬을 실행하는 커맨드"
date: 2026-03-28
---

인자: $ARGUMENTS

`sma` 에이전트를 사용하여 ma에서 `/cdf` 스킬과 동일한 tmux 작업을 수행.

# 실행

`$ARGUMENTS`를 파싱하여 `sma` 에이전트에 다음 작업을 위임:

* `list` / `kill` → ma의 pm 세션 조회/삭제
* 프로젝트 번호 지정 → ma에서 tmux pm 세션 윈도우/pane 생성
* `--- CMD` → ma의 해당 pane에 명령 전달

## sma 에이전트 위임 시 전달할 정보

* 프로젝트 경로: `~/_git/___pm/projects/N` 파일 내용 (로컬에서 읽어서 전달)
* tmux 경로: `/opt/homebrew/bin/tmux`
* 시스템 명령 full path: `/bin/cat`, `/bin/sleep`, `/usr/bin/grep`, `/usr/bin/wc`, `/usr/bin/tr`, `/usr/bin/sed`, `/usr/bin/say`
* cdf 스킬의 동작 규칙:
    - pane 단위 매칭 (기존 pane 경로 일치 시 재사용)
    - 활성 윈도우 우선 탐색
    - sync-panes 윈도우에서 개별 전달 시 일시 해제/복원
    - column-major 배치 (2열)
    - PREFIX 기반 auto-numbering

# 주의사항

* ma에 tmux pm 세션이 생성됨 (로컬이 아님)
* 사전 조건: SSH 키 인증
* 접속: ma에서 `tmux attach -t pm`



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
