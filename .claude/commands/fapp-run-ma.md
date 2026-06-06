---
title: "FAPP-RUN-MA: ma에서 fApp 프로젝트 일괄 배포 및 실행"
description: "ma에서 fApp 프로젝트 일괄 배포 및 실행 커맨드"
date: 2026-03-28
---

인자: $ARGUMENTS

# 실행 지시

아래 절차를 **순서대로** 실행할 것. 각 Step의 커맨드가 완료된 후 다음으로 진행.

## Step 1: 로컬 deploy + push

`/fapp-push` 커맨드 실행:
```
/fapp-push
```

## Step 2: ma에서 pull

`/fapp-pull-ma` 커맨드 실행:
```
/fapp-pull-ma
```

## Step 3: ma에 tmux 세션 생성

`/cdf-fapp-ma` 커맨드 실행:
```
/cdf-fapp-ma
```

## Step 4: ma tmux 세션에서 /run 실행

`sma` 에이전트에 위임하여 ma의 pm tmux 세션 각 pane에서 `/run` 실행.

sma 에이전트에 전달할 내용:
* fApp 프로젝트 수 (data/fapp.txt 기준)
* ma의 pm tmux 세션 `fapp` 윈도우 각 pane에서 `claude "/run" --dangerously-skip-permissions` 실행
* tmux 경로: `/opt/homebrew/bin/tmux`
* 각 pane에 `tmux send-keys -t pm:fapp.{i} 'claude "/run" --dangerously-skip-permissions' Enter` 전달

## Step 5: 완료 보고

```bash
say "fApp run started on ma"
```

ma의 tmux 세션에서 각 프로젝트가 실행 중임을 사용자에게 보고.
실행 완료 확인은 ma에서 `tmux attach -t pm`으로 직접 확인.

# 주의사항

* fApp 목록은 `data/fapp.txt`에서 읽음 (프로젝트 추가/제거 시 이 파일만 수정)
* Step 1 → Step 2 → Step 3 → Step 4 순차 실행
* ma 작업은 `sma` 에이전트 위임으로 통일 (직접 SSH 금지)
* 각 프로젝트에 `/run` 커맨드가 정의되어 있어야 함



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
