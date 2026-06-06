---
title: "FAPP-CAPTURE-MA: ma에서 fApp 프로젝트 일괄 /capture 순차 실행"
description: "ma에서 fApp 프로젝트 일괄 /capture 순차 실행 커맨드"
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

## Step 3: ma에서 각 프로젝트 /capture 순차 실행

**주의: tmux 병렬 세션을 사용하면 캡처 프로세스가 충돌함. 반드시 순차 실행할 것.**

fApp 목록 로드:

```bash
FAPP_FILE="$HOME/_git/___pm/data/fapp.txt"
NUMS=($(cat "$FAPP_FILE"))
base_dir="$HOME/_git/___pm/projects"

CAPTURE_LIST=""
for num in "${NUMS[@]}"; do
  path=$(eval echo $(cat "${base_dir}/${num}"))
  app=$(basename "$path")
  CAPTURE_LIST="${CAPTURE_LIST}\n- ${app} (경로: ${path})"
done
echo -e "capture 대상:${CAPTURE_LIST}"
```

`sma` 에이전트에 위임하여 ma에서 각 프로젝트를 **순차적으로** capture.

sma 에이전트에 전달할 내용:
* capture 대상 프로젝트 목록 (위에서 확인한 목록)
* 각 프로젝트에 대해 순차 실행: `cd ${path} && claude "/capture" --dangerously-skip-permissions`
* **반드시 하나씩 순차 실행** (병렬 금지 — 캡처 프로세스 충돌 방지)
* 프로젝트별 capture 결과 보고

## Step 4: 완료 보고

```bash
say "fApp capture on ma complete"
```

결과를 사용자에게 보고.

# 주의사항

* fApp 목록은 `data/fapp.txt`에서 읽음 (프로젝트 추가/제거 시 이 파일만 수정)
* **절대 tmux 병렬 세션으로 실행하지 말 것** — 캡처 프로세스 충돌 발생
* 반드시 순차 실행
* Step 1 → Step 2 → Step 3 → Step 4 순차 실행
* ma 작업은 `sma` 에이전트 위임으로 통일 (직접 SSH 금지)
* 각 프로젝트에 `/capture` 커맨드가 정의되어 있어야 함
* ma에서도 동일 경로 구조 가정
* 경로의 `~`는 `eval echo`로 확장



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
