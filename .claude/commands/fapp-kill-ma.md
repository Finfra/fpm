---
title: "FAPP-KILL-MA: ma에서 fApp 프로세스 일괄 종료"
description: "ma에서 fApp 프로세스 일괄 종료 커맨드"
date: 2026-03-28
---

인자: $ARGUMENTS

# 실행 지시

아래 절차를 **순서대로** 실행할 것. 설명만 하지 말고 실행해야 함.

## Step 1: fApp 목록 로드

```bash
FAPP_FILE="$HOME/_git/___pm/data/fapp.txt"
NUMS=($(cat "$FAPP_FILE"))
base_dir="$HOME/_git/___pm/projects"

KILL_LIST=""
for num in "${NUMS[@]}"; do
  path=$(eval echo $(cat "${base_dir}/${num}"))
  app=$(basename "$path")
  KILL_LIST="${KILL_LIST}\n- ${app} (경로: ${path})"
done
echo -e "종료 대상:${KILL_LIST}"
```

## Step 2: sma 에이전트로 ma에서 프로세스 종료

`sma` 에이전트에 위임하여 ma에서 각 fApp 프로세스를 종료.

sma 에이전트에 전달할 내용:
* 종료 대상 앱 목록 (Step 1에서 확인한 목록)
* 각 앱에 대해 `pkill -f "MacOS/${app_name}"` 실행
* 종료 결과(성공/미실행) 앱별로 보고

## Step 3: 완료 보고

```bash
say "fApp kill on ma complete"
```

결과를 사용자에게 보고.

# 주의사항

* fApp 목록은 `data/fapp.txt`에서 읽음 (프로젝트 추가/제거 시 이 파일만 수정)
* 반드시 `pkill -f "MacOS/${app_name}"` 패턴을 사용하여 해당 앱만 정확히 종료
* ma 작업은 `sma` 에이전트 위임으로 통일 (직접 SSH 금지)
* 경로의 `~`는 `eval echo`로 확장



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
