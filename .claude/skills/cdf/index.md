---
title: cdf
description: "pm tmux 세션의 window/pane을 생성·관리함. @N 윈도우 인덱스, :NAME 윈도우 이름, projects/ 번호로 pane 구성. 완료 후 WIN_NAME 출력."
date: 2026-04-18
---

# CDF Skill

인자: $ARGUMENTS

## cdft 우선 호출 규칙

`~/.zsh_functions`에 `cdft()` 함수가 존재함. **query 모드를 제외한 모든 모드**(setup, send, list, kill, capture)는 `cdft`를 bash에서 직접 실행하여 처리할 것.

```bash
# query 모드 판별
if echo "$ARGUMENTS" | /usr/bin/grep -qE '(^|[[:space:]]): .'; then
  # query 모드 → 아래 스킬 로직 실행
  :
else
  # cdft 직접 실행 (빠르고 안정적)
  cdft $ARGUMENTS
  # 여기서 종료 — 아래 로직 실행 불필요
fi
```

query 모드가 아니면 cdft 실행 후 종료. **아래 절차는 query 모드에서만 실행함.**

---

아래 절차를 **순서대로 bash 명령으로 직접 실행**할 것. 설명만 하지 말고 실행해야 함.

## Step 1: ARGUMENTS 파싱

**입력:** `$ARGUMENTS`

### 특수 키워드 즉시 처리

| 조건                      | 처리                                 |
| ------------------------- | ------------------------------------ |
| 비어있음 또는 `list`      | list 모드 실행 후 종료               |
| `kill` [WIN_NAME]         | kill 모드 실행 후 종료               |
| `kill` N N ...            | 윈도우 인덱스 N들을 삭제             |
| `capture` [N] ([:NAME])   | capture 모드: 각 pane 상태+출력 수집 |

### 파싱 (순서대로)

**1. `@N` 윈도우 번호 추출**

```bash
TMUX=/opt/homebrew/bin/tmux
if echo "$ARGUMENTS" | /usr/bin/grep -qE '@[0-9]+'; then
  WIN_NUM=$(echo "$ARGUMENTS" | /usr/bin/grep -oE '@[0-9]+' | /usr/bin/tr -d '@')
  ARGS_W=$(echo "$ARGUMENTS" | /usr/bin/sed 's/@[0-9]*//g' | /usr/bin/sed 's/  */ /g;s/^ //;s/ $//')
  TARGET_WIN=$($TMUX display-message -t "pm:$WIN_NUM" -p '#W' 2>/dev/null)
  [ -z "$TARGET_WIN" ] && TARGET_WIN="win-$WIN_NUM" && WIN_CREATE_IDX="$WIN_NUM"
else
  WIN_NUM=""
  ARGS_W="$ARGUMENTS"
  TARGET_WIN=""
fi
```

**2. `:NAME` 윈도우 이름 추출**

```bash
if echo "$ARGS_W" | /usr/bin/grep -qE ':[A-Za-z][A-Za-z0-9_-]*'; then
  TARGET_WIN=$(echo "$ARGS_W" | /usr/bin/grep -oE ':[A-Za-z][A-Za-z0-9_-]*' | /usr/bin/sed 's/^://')
  ARGS_W=$(echo "$ARGS_W" | /usr/bin/sed 's/:[A-Za-z][A-Za-z0-9_-]*//g' | /usr/bin/sed 's/  */ /g;s/^ //;s/ $//')
fi
```

**2.3. `: prompt` 자연어 쿼리 감지**

`: ` (콜론+공백) 패턴을 감지. `:NAME`(공백없음)과 충돌 없음.

```bash
if echo "$ARGS_W" | /usr/bin/grep -qE '(^|[[:space:]]): .'; then
  QUERY=$(echo "$ARGS_W" | /usr/bin/sed 's/.*: //')
  ARGS_W=$(echo "$ARGS_W" | /usr/bin/sed 's/[[:space:]]*: .*//' | /usr/bin/sed 's/  */ /g;s/^ //;s/ $//')
  QUERY_MODE=1
else
  QUERY=""
  QUERY_MODE=0
fi
```

**2.5. `capture` 키워드 감지**

```bash
if echo "$ARGS_W" | /usr/bin/grep -qE '(^|[[:space:]])capture([[:space:]]|$)'; then
  CAPTURE_N=$(echo "$ARGS_W" | /usr/bin/grep -oE 'capture[[:space:]]+[0-9]+' | /usr/bin/grep -oE '[0-9]+$')
  CAPTURE_N="${CAPTURE_N:-50}"
  ARGS_W=$(echo "$ARGS_W" | /usr/bin/sed 's/capture[[:space:]]*[0-9]*//' | /usr/bin/sed 's/  */ /g;s/^ //;s/ $//')
  CAPTURE_MODE=1
else
  CAPTURE_N=50
  CAPTURE_MODE=0
fi
```

**3. `---` 구분자 분리**

```bash
if echo "$ARGS_W" | /usr/bin/grep -qE '(^|[ ])---'; then
  BEFORE=$(echo "$ARGS_W" | /usr/bin/sed 's/[[:space:]]*---[[:space:]]*.*//')
  CMD=$(echo "$ARGS_W" | /usr/bin/sed 's/.*---[[:space:]]*//')
else
  BEFORE="$ARGS_W"
  CMD=""
fi
```

**4. 토큰 분류 (zsh word split 대응)**

```bash
PANES=()
for token in ${=BEFORE}; do
  if echo "$token" | /usr/bin/grep -qE '^[0-9]+$'; then
    PANES+=("$token")
  fi
done
```

**5. 모드 결정**

```bash
if [ "$QUERY_MODE" -eq 1 ]; then
  MODE="query"
  if [ -z "$TARGET_WIN" ]; then
    TARGET_WIN=$($TMUX display-message -t pm -p '#W' 2>/dev/null)  # 활성 윈도우
  fi
elif [ "$CAPTURE_MODE" -eq 1 ]; then
  MODE="capture"
  if [ -z "$TARGET_WIN" ]; then
    TARGET_WIN=$($TMUX display-message -t pm -p '#W' 2>/dev/null)  # 활성 윈도우
  fi
elif [ "${#PANES[@]}" -gt 0 ]; then
  MODE="setup"
  PREFIX="${TARGET_WIN:-pm}"
elif [ -n "$CMD" ]; then
  MODE="send"                                      # PANES 없고 CMD만 있으면 send
  if [ -z "$TARGET_WIN" ]; then
    TARGET_WIN=$($TMUX display-message -t pm -p '#W' 2>/dev/null)  # 활성 윈도우
  fi
else
  echo "오류: 프로젝트 번호 또는 명령을 지정해주세요"
  exit 1
fi
```

### 파싱 결과 예시

| 입력                   | TARGET_WIN        | PANES  | MODE    | CMD       | CAPTURE_N |
| ---------------------- | ----------------- | ------ | ------- | --------- | --------- |
| `1 2`                  | (없음→pm prefix)  | 1 2    | setup   |           |           |
| `1 2 :mywin`           | `mywin`           | 1 2    | setup   |           |           |
| `6 7 8 :fapp`          | `fapp`            | 6 7 8  | setup   |           |           |
| `1 2 @3`               | pm:3 윈도우 이름  | 1 2    | setup   |           |           |
| `@1 --- 뭐하나?`       | pm:1 윈도우 이름  | -      | send    | `뭐하나?` |           |
| `:mywin --- ls`        | `mywin`           | -      | send    | `ls`      |           |
| `--- ls`               | (활성 윈도우)     | -      | send    | `ls`      |           |
| `capture`              | (활성 윈도우)     | -      | capture |           | 50        |
| `:fapp capture`        | `fapp`            | -      | capture |           | 50        |
| `:fapp capture 30`     | `fapp`            | -      | capture |           | 30        |
| `@2 capture`           | pm:2 윈도우 이름  | -      | capture |           | 50        |
| `@0 : 뭐하고있나`     | pm:0 윈도우 이름  | -      | query   |           |           |
| `:fapp : 클로드실행해줘` | `fapp`          | -      | query   |           |           |
| `: ls 실행해줘`        | (활성 윈도우)     | -      | query   |           |           |

---

## Step 2: 모드별 실행

### query 모드

QUERY 자연어를 Claude가 해석하여 아래 세 가지 액션 중 하나를 결정하고 실행함.

**액션 분류 기준:**

| 의도           | 예시                                 | 액션   |
| -------------- | ------------------------------------ | ------ |
| 상태/현황 조회 | 뭐하고있나, 상태는, 어때, 확인해줘   | STATUS |
| 출력/결과 조회 | 결과는, 출력봐줘, 뭐나왔나           | OUTPUT |
| 명령 실행      | 클로드실행해줘, ls해줘, /run전달해줘 | SEND   |

**STATUS 액션** — pane 상태 + 최근 출력 수집:

```bash
TMUX=/opt/homebrew/bin/tmux
WIN_NAME="$TARGET_WIN"
pane_count=$($TMUX list-panes -t "pm:$WIN_NAME" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
[ "$pane_count" -eq 0 ] && echo "오류: pm:$WIN_NAME 에 pane이 없음" && exit 1

detect_pane_state() {
  local target="$1"
  $TMUX list-panes -t "$target" &>/dev/null || { echo "MISSING"; return; }
  local pane_pid=$($TMUX display-message -t "$target" -p '#{pane_pid}' 2>/dev/null)
  local claude_cnt=$(pgrep -P "$pane_pid" -f "node.*claude|claude.*node" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
  [ "$claude_cnt" -gt 0 ] && { echo "CLAUDE"; return; }
  local last_line=$($TMUX capture-pane -t "$target" -p -l 3 2>/dev/null | tail -1)
  echo "$last_line" | /usr/bin/grep -qE '[$%#>] *$' && { echo "IDLE"; return; }
  echo "BUSY"
}

echo "=== pm:$WIN_NAME 상태 ==="
for pane_idx in $(seq 0 $((pane_count - 1))); do
  target="pm:$WIN_NAME.$pane_idx"
  pane_path=$($TMUX display-message -t "$target" -p '#{pane_current_path}' 2>/dev/null)
  state=$(detect_pane_state "$target")
  echo ""
  echo "--- pane $pane_idx [$state] ${pane_path##*/} ---"
  $TMUX capture-pane -t "$target" -p -l 10 2>/dev/null | /usr/bin/grep -v '^[[:space:]]*$' | tail -5
done
```

**OUTPUT 액션** — capture-pane 50줄 전체 출력 (capture 모드와 동일, 위임):

capture 모드 로직을 CAPTURE_N=50으로 그대로 실행.

**SEND 액션** — QUERY에서 실행할 CMD를 Claude가 추출하고 상태 인식 라우팅:

Claude가 QUERY에서 CMD를 추출 (ex: "클로드 실행해줘" → `claude --dangerously-skip-permissions`, "/run 전달해줘" → `/run`).

```bash
TMUX=/opt/homebrew/bin/tmux
WIN_NAME="$TARGET_WIN"
# [Claude가 추출한 CMD를 RESOLVED_CMD 변수에 설정]
pane_count=$($TMUX list-panes -t "pm:$WIN_NAME" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')

for pane_idx in $(seq 0 $((pane_count - 1))); do
  target="pm:$WIN_NAME.$pane_idx"
  state=$(detect_pane_state "$target")   # 위 STATUS 액션의 함수 재사용
  case "$state" in
    IDLE)
      $TMUX send-keys -t "$target" "$RESOLVED_CMD" Enter
      echo "  pane $pane_idx [IDLE] → 전달: $RESOLVED_CMD"
      ;;
    CLAUDE)
      slash=$(echo "$RESOLVED_CMD" | /usr/bin/grep -oE '"(/[^"]+)"' | /usr/bin/tr -d '"')
      send_cmd="${slash:-$RESOLVED_CMD}"
      $TMUX send-keys -t "$target" "$send_cmd" Enter
      echo "  pane $pane_idx [CLAUDE] → 전달: $send_cmd"
      ;;
    BUSY)   echo "  pane $pane_idx [BUSY] → 스킵" ;;
    MISSING) echo "  pane $pane_idx [MISSING] → 오류" ;;
  esac
  /bin/sleep 0.1
done
```

## capture 모드

각 pane의 상태(IDLE/CLAUDE/BUSY/MISSING)와 마지막 N줄 출력을 수집하여 보고함.

```bash
TMUX=/opt/homebrew/bin/tmux
WIN_NAME="$TARGET_WIN"
pane_count=$($TMUX list-panes -t "pm:$WIN_NAME" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
[ "$pane_count" -eq 0 ] && echo "오류: pm:$WIN_NAME 에 pane이 없음" && exit 1

detect_pane_state() {
  local target="$1"

  $TMUX list-panes -t "$target" &>/dev/null || { echo "MISSING"; return; }

  local pane_pid=$($TMUX display-message -t "$target" -p '#{pane_pid}' 2>/dev/null)
  local claude_cnt=$(pgrep -P "$pane_pid" -f "node.*claude\|claude.*node" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
  [ "$claude_cnt" -gt 0 ] && { echo "CLAUDE"; return; }

  local last_line=$($TMUX capture-pane -t "$target" -p -l 3 2>/dev/null | tail -1)
  echo "$last_line" | /usr/bin/grep -qE '[$%#>] *$' && { echo "IDLE"; return; }

  echo "BUSY"
}

echo "=== pm:$WIN_NAME capture (last ${CAPTURE_N} lines) ==="
for pane_idx in $(seq 0 $((pane_count - 1))); do
  target="pm:$WIN_NAME.$pane_idx"
  pane_path=$($TMUX display-message -t "$target" -p '#{pane_current_path}' 2>/dev/null)
  state=$(detect_pane_state "$target")
  echo ""
  echo "--- pane $pane_idx [$state] ${pane_path##*/} ---"
  $TMUX capture-pane -t "$target" -p -l "$CAPTURE_N" 2>/dev/null
done
echo ""
echo "=== 완료: ${pane_count}개 pane ==="
```

## list 모드

```bash
TMUX=/opt/homebrew/bin/tmux
$TMUX list-windows -t pm -F '#I:#W (#F)' 2>/dev/null | /usr/bin/grep -v "^$" || echo "pm 세션 없음"
echo "---"
for win in $($TMUX list-windows -t pm -F '#W' 2>/dev/null); do
  echo "=== $win ==="
  $TMUX list-panes -t "pm:$win" -F '  pane #P: #{pane_current_path}' 2>/dev/null
done
```

## send 모드

`@N` 또는 `:NAME` 또는 빈값(활성 윈도우) + `--- CMD` 형태로 기존 윈도우의 모든 pane에 CMD 전달.

```bash
TMUX=/opt/homebrew/bin/tmux
WIN_NAME="$TARGET_WIN"
pane_count=$($TMUX list-panes -t "pm:$WIN_NAME" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
[ "$pane_count" -eq 0 ] && echo "오류: pm:$WIN_NAME 에 pane이 없음" && exit 1
sync=$($TMUX show-window-options -t "pm:$WIN_NAME" synchronize-panes 2>/dev/null | /usr/bin/grep -c "on")
if [ "$sync" -gt 0 ]; then
  $TMUX send-keys -t "pm:$WIN_NAME.0" "$CMD" Enter
  echo "pm:$WIN_NAME [sync] pane 0에만 전달: $CMD"
else
  for pane_idx in $(seq 0 $((pane_count - 1))); do
    $TMUX send-keys -t "pm:$WIN_NAME.$pane_idx" "$CMD" Enter
    /bin/sleep 0.1
  done
  echo "pm:$WIN_NAME 의 ${pane_count}개 pane에 전달: $CMD"
fi
```

## kill 모드

인자가 숫자면 윈도우 인덱스로 삭제, 문자면 윈도우 이름으로 삭제.
윈도우가 1개만 남으면 세션 전체 삭제.

```bash
TMUX=/opt/homebrew/bin/tmux
# kill 뒤의 인자들을 순회하며 삭제
for target in ${=KILL_ARGS}; do
  win_count=$($TMUX list-windows -t pm 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
  if [ "$win_count" -le 1 ]; then
    $TMUX kill-session -t pm 2>/dev/null && echo "pm 세션 전체 삭제됨"
    break
  fi
  $TMUX kill-window -t "pm:$target" 2>/dev/null && echo "pm:$target 삭제됨"
done
```

## setup 모드

**경로 해석:**
```bash
TMUX=/opt/homebrew/bin/tmux
base_dir="$HOME/_git/___pm/projects"
declare -a PROJ_PATHS
declare -a PROJ_APPS
idx=1
for num in "${PANES[@]}"; do
  content=$(/bin/cat "${base_dir}/${num}" 2>/dev/null)
  proj_path=$( echo "$content" | /usr/bin/sed "s|~|$HOME|g" )
  PROJ_PATHS[$idx]="$proj_path"
  PROJ_APPS[$idx]="${proj_path##*/}"
  idx=$((idx+1))
done
pane_count=${#PANES[@]}

# column-major PANE_MAP 계산
cols=2
rows=$(( (pane_count + cols - 1) / cols ))
declare -a PANE_MAP
for ((i=1; i<=pane_count; i++)); do
  col=$(( (i-1) / rows ))
  row=$(( (i-1) % rows ))
  PANE_MAP[$i]=$(( row * cols + col ))
done
```

**pm 세션 확인/생성:**
```bash
$TMUX has-session -t pm 2>/dev/null || $TMUX new-session -d -s pm -n "${PREFIX}1"
```

**pane 단위 매칭 — 기존 pane에서 프로젝트 경로 탐색:**

> **절대 kill-window / kill-session 금지** — 기존 window는 다른 세션이 작업 중일 수 있음.
> 먼저 모든 윈도우의 pane을 순회하며 요청된 프로젝트 경로와 일치하는 pane을 찾음.
> 전부 찾으면 → 해당 pane들 재사용.
> 일부/전부 없으면 → 새 윈도우 생성.

```bash
# 활성 윈도우를 먼저 탐색하여 우선 매칭
declare -a FOUND_TARGETS   # "pm:윈도우.pane" 형태로 매칭된 타겟 저장
FOUND_COUNT=0

for ((i=1; i<=pane_count; i++)); do
  FOUND_TARGETS[$i]=""
done

# 활성 윈도우 먼저, 나머지 윈도우 후순위로 정렬
ACTIVE_WIN=$($TMUX display-message -t pm -p '#W' 2>/dev/null)
WIN_ORDER="$ACTIVE_WIN"
for win in $($TMUX list-windows -t pm -F '#W' 2>/dev/null); do
  [ "$win" != "$ACTIVE_WIN" ] && WIN_ORDER="$WIN_ORDER $win"
done

for win in ${=WIN_ORDER}; do
  for pane_info in $($TMUX list-panes -t "pm:$win" -F '#P:#{pane_current_path}' 2>/dev/null); do
    pane_idx=${pane_info%%:*}
    pane_path=${pane_info#*:}
    for ((i=1; i<=pane_count; i++)); do
      if [ -z "${FOUND_TARGETS[$i]}" ] && [ "$pane_path" = "${PROJ_PATHS[$i]}" ]; then
        FOUND_TARGETS[$i]="pm:$win.$pane_idx"
        FOUND_COUNT=$((FOUND_COUNT + 1))
        break
      fi
    done
  done
done

echo "매칭: $FOUND_COUNT / $pane_count"
```

**분기: 전부 매칭 → 재사용 / 미매칭 → 신규 생성:**

```bash
if [ "$FOUND_COUNT" -eq "$pane_count" ]; then
  # === 재사용: 기존 pane 보고 ===
  echo "기존 pane 재사용:"
  for ((i=1; i<=pane_count; i++)); do
    echo "  ${FOUND_TARGETS[$i]} → ${PROJ_PATHS[$i]}"
  done

  # WIN_NAME 추출 (pm:fapp2.0 → fapp2)
  REUSE_WIN=$(echo "${FOUND_TARGETS[1]}" | /usr/bin/sed 's/pm://;s/\..*//')
  /usr/bin/say "session ready"
  echo "WIN_NAME=$REUSE_WIN"

else
  # === 신규 윈도우 생성 ===
  MAX_NUM=0
  for existing in $($TMUX list-windows -t pm -F '#W' 2>/dev/null | /usr/bin/grep "^${PREFIX}[0-9]*$"); do
    num=${existing#$PREFIX}
    [ -n "$num" ] && [ "$num" -gt "$MAX_NUM" ] && MAX_NUM=$num
  done
  WIN_NAME="${PREFIX}$((MAX_NUM + 1))"
  echo "새 window: $WIN_NAME"
  if [ -n "$WIN_CREATE_IDX" ]; then
    $TMUX new-window -a -t "pm:$WIN_CREATE_IDX" -n "$WIN_NAME" 2>/dev/null || \
    $TMUX new-window -a -t pm -n "$WIN_NAME" 2>/dev/null
  else
    $TMUX new-window -a -t pm -n "$WIN_NAME" 2>/dev/null
  fi

  # pane 생성
  for ((i=1; i<pane_count; i++)); do
    $TMUX split-window -t "pm:$WIN_NAME"
    $TMUX select-layout -t "pm:$WIN_NAME" tiled
  done

  # column-major cd 배정
  for ((i=1; i<=pane_count; i++)); do
    $TMUX send-keys -t "pm:$WIN_NAME.${PANE_MAP[$i]}" "cd '${PROJ_PATHS[$i]}'" Enter
    /bin/sleep 0.1
  done

  # 완료 보고 (신규)
  /bin/sleep 1
  $TMUX list-panes -t "pm:$WIN_NAME" -F '  pane #P: #{pane_current_path}'
  /usr/bin/say "session ready"
  echo "WIN_NAME=$WIN_NAME"
fi
```

---

# 주의사항

* tmux 경로: `TMUX=/opt/homebrew/bin/tmux`
* 시스템 명령 full path 사용: `/bin/cat`, `/bin/sleep`, `/usr/bin/say`, `/usr/bin/grep`, `/usr/bin/wc`, `/usr/bin/tr`, `/usr/bin/sed`
* `path` 변수명 사용 금지 (zsh `$PATH` 덮어씀)
* **zsh word split**: 변수를 for loop에서 분할할 때 반드시 `${=var}` 사용
* 배열 index 1부터 사용 (zsh 호환)
* 세션 attach 하지 않음
* **CMD 전송 없음**: CMD 라우팅은 cdf-fapp이 담당



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 skill 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
