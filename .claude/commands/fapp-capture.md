---
name: fapp-capture
description: "fApp 프로젝트 일괄 /capture 순차 실행 커맨드"
date: 2026-03-31
---

인자: `[앱인덱스...] [--- 캡처ID]`

# 인자 파싱

`---` 기준으로 앱 인덱스(좌측)와 캡처 ID(우측)를 분리함.

| 입력                     | 앱 대상          | 캡처 ID |
| :----------------------- | :--------------- | :------ |
| (없음)                   | 전체 (1~6)       | all     |
| `1 2`                    | fApp 1, 2번      | all     |
| `1 2 3 --- 1`            | fApp 1, 2, 3번   | 1       |
| `--- 1`                  | 전체 (1~6)       | 1       |

## 파싱 로직

```bash
source ~/.bin/fapp-helper.sh
FAPP_NUMS=($(fapp_load_projects))
FAPP_COUNT=${#FAPP_NUMS[@]}

RAW_ARGS="$ARGUMENTS"

# --- 기준 분리
if echo "$RAW_ARGS" | /usr/bin/grep -qE '(^|[ ])---[ ]|^---$'; then
  APP_ARGS=$(echo "$RAW_ARGS" | /usr/bin/sed 's/[[:space:]]*---[[:space:]].*//' | /usr/bin/sed 's/^---$//')
  CAPTURE_ID=$(echo "$RAW_ARGS" | /usr/bin/sed 's/.*---[[:space:]]*//')
else
  APP_ARGS="$RAW_ARGS"
  CAPTURE_ID="all"
fi

# 앱 인덱스 → 프로젝트 번호 변환 (1-based)
if [ -z "$(echo $APP_ARGS | /usr/bin/tr -d ' ')" ]; then
  TARGET_NUMS=("${FAPP_NUMS[@]}")
else
  TARGET_NUMS=()
  for idx in $APP_ARGS; do
    if [ "$idx" -ge 1 ] && [ "$idx" -le "$FAPP_COUNT" ]; then
      TARGET_NUMS+=("${FAPP_NUMS[$((idx-1))]}")
    fi
  done
fi

# 캡처 커맨드 구성
if [ "$CAPTURE_ID" = "all" ] || [ -z "$CAPTURE_ID" ]; then
  CAPTURE_CMD="/capture"
else
  CAPTURE_CMD="/capture $CAPTURE_ID"
fi
```

# 실행 지시

fapp-serial 서브에이전트를 사용하여 **순차 실행**함.
(캡처는 화면 충돌 방지를 위해 병렬 실행 불가)

Agent 도구를 호출:
* `subagent_type`: `fapp-serial`
* 프롬프트에 포함할 내용:
    - 대상 프로젝트 번호 목록: `TARGET_NUMS` (파싱 결과)
    - 실행할 커맨드: `CAPTURE_CMD` (파싱 결과)
    - 순차 실행 강조: "반드시 한 프로젝트 완료 후 다음 프로젝트 진행"

프롬프트 예시:
```
다음 fApp 프로젝트에 `{CAPTURE_CMD}` 커맨드를 순차적으로 실행하세요.
대상 프로젝트 번호: {TARGET_NUMS}
반드시 한 프로젝트가 완료된 후 다음 프로젝트를 진행하세요.
```

# 주의사항
* fApp 목록은 `data/fapp.txt`에서 읽음
* **순차 실행 필수** (tmux 병렬 캡처 시 화면 충돌 유발)
* 앱 인덱스는 1-based (fapp.txt 순서 기준: 1=fBanner, 2=fBoard, ...)
* 캡처 ID는 각 프로젝트 capture 스킬에서 정의한 ID



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
