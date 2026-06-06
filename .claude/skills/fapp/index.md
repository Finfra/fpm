---
title: fapp
description: "fApp 커맨드 공통 헬퍼 함수 모음 (data 읽기, tmux 세션 생성, 경로 매핑)"
date: 2026-04-18
---

# 용도

fApp 관련 커맨드(`/fapp-run`, `/fapp-kill`, `/fapp-pull` 등)에서 공통으로 사용하는 헬퍼 함수 제공.

# 공통 함수

```bash
# ========================================
# fapp_load_projects() - fapp.txt 읽기
# ========================================
# 출력: 프로젝트 번호 배열 (스페이스 구분)
# 사용 예: NUMS=($(fapp_load_projects))

fapp_load_projects() {
  local FAPP_FILE="$HOME/_git/___pm/data/fapp.txt"
  if [ ! -f "$FAPP_FILE" ]; then
    echo "Error: $FAPP_FILE not found" >&2
    return 1
  fi
  cat "$FAPP_FILE"
}

# ========================================
# fapp_get_path() - 프로젝트 번호 → 경로
# ========================================
# 인자: 프로젝트 번호 (예: 11, 12)
# 출력: 확장된 절대 경로
# 사용 예: path=$(fapp_get_path 11)

fapp_get_path() {
  local num="$1"
  local base_dir="$HOME/_git/___pm/projects"
  local raw=$(cat "${base_dir}/${num}" 2>/dev/null)
  if [ -z "$raw" ]; then
    echo "Error: project $num not found" >&2
    return 1
  fi
  eval echo "$raw"
}

# ========================================
# fapp_get_app_name() - 경로 → 앱이름
# ========================================
# 인자: 프로젝트 경로
# 출력: 앱 이름 (경로의 basename)
# 사용 예: app=$(fapp_get_app_name "$path")

fapp_get_app_name() {
  local path="$1"
  basename "$path"
}

# ========================================
# fapp_create_session() - tmux 세션 생성
# ========================================
# 인자: 윈도우명 (예: "fapp-run", "fapp-kill")
# 출력: 세션 생성 후 각 pane에서 프로젝트 디렉토리로 cd
# 사용: fapp_create_session "fapp-run" 후 tmux send-keys로 명령 전달
# 참고: /cdf-fapp 커맨드 위임

fapp_create_session() {
  local WIN_NAME="$1"
  if [ -z "$WIN_NAME" ]; then
    echo "Error: window name required" >&2
    return 1
  fi
  # cdf-fapp 커맨드 실행 (tmux 세션 생성)
  /cdf-fapp "$WIN_NAME"
}

# ========================================
# fapp_column_major_map() - pane 인덱스 매핑
# ========================================
# 용도: kill에서 사용 (column-major 매핑)
# 입력: 프로젝트 개수
# 출력: PANE_MAP 배열 설정 (전역)
# 사용 예:
#   fapp_column_major_map ${#NUMS[@]}
#   pane_idx=${PANE_MAP[$i]}

fapp_column_major_map() {
  local pane_count="$1"
  local cols=2
  local rows=$(( (pane_count + cols - 1) / cols ))

  # 전역 배열 설정 (호출 스크립트에서 ${PANE_MAP[$i]} 사용)
  PANE_MAP=()
  for ((i=0; i<pane_count; i++)); do
    local col=$((i / rows))
    local row=$((i % rows))
    PANE_MAP[$i]=$((row * cols + col))
  done
}

# ========================================
# fapp_wait_for_completion() - 프로세스 대기
# ========================================
# 인자: 윈도우명, pane 개수, 타임아웃(초)
# 용도: tmux pane에서 실행 중인 claude/node 프로세스 완료 대기
# 사용 예: fapp_wait_for_completion "fapp-run" 6 300

fapp_wait_for_completion() {
  local WIN_NAME="$1"
  local pane_count="$2"
  local timeout="${3:-600}"  # 기본값: 10분
  local elapsed=0
  local check_interval=10

  while [ $elapsed -lt $timeout ]; do
    local running=0
    for ((i=0; i<pane_count; i++)); do
      local cmd=$(tmux display-message -t qa:$WIN_NAME.$i -p '#{pane_current_command}' 2>/dev/null)
      if [ "$cmd" = "claude" ] || [ "$cmd" = "node" ]; then
        running=$((running + 1))
      fi
    done

    if [ "$running" -eq 0 ]; then
      return 0
    fi

    echo "실행 중: ${running}개 pane 대기... ($elapsed초/$timeout초)"
    sleep $check_interval
    elapsed=$((elapsed + check_interval))
  done

  echo "Warning: timeout after ${timeout}초" >&2
  return 1
}
```

# 사용 예

## 예시 1: run 커맨드
```bash
# 함수 로드
source ~/.claude/skills/fapp.sh

# 프로젝트 로드
NUMS=($(fapp_load_projects))
pane_count=${#NUMS[@]}

# tmux 세션 생성
fapp_create_session "fapp-run"

# 각 pane에서 /run 실행
for ((i=0; i<pane_count; i++)); do
  tmux send-keys -t qa:fapp-run.$i "claude \"/run\" --dangerously-skip-permissions" Enter
done

# 완료 대기
fapp_wait_for_completion "fapp-run" $pane_count
say "fApp run complete"
```

## 예시 2: kill 커맨드
```bash
# 함수 로드
source ~/.claude/skills/fapp.sh

# 프로젝트 로드
NUMS=($(fapp_load_projects))
pane_count=${#NUMS[@]}

# tmux 세션 생성
fapp_create_session "fapp-kill"

# column-major 매핑
fapp_column_major_map $pane_count

# 각 pane에서 kill 실행
for ((i=0; i<pane_count; i++)); do
  path=$(fapp_get_path "${NUMS[$i]}")
  app=$(fapp_get_app_name "$path")
  pane_idx=${PANE_MAP[$i]}

  if [ -f "${path}/.claude/commands/kill.md" ]; then
    tmux send-keys -t qa:fapp-kill.$pane_idx "claude \"/kill\" --dangerously-skip-permissions" Enter
  else
    tmux send-keys -t qa:fapp-kill.$pane_idx "osascript -e 'tell application \"${app}\" to quit' 2>/dev/null" Enter
  fi
done

# 완료 대기
fapp_wait_for_completion "fapp-kill" $pane_count 60
say "fApp kill complete"
```

# 주의사항

* 함수는 bash 스크립트로 제공되므로, 커맨드에서 `source` 또는 shell redirection으로 로드 필요
* 모든 경로는 `~` 자동 확장 (eval echo 포함)
* tmux 세션명 하드코딩: `qa:` (claudeCode 기본 세션)



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 skill 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
