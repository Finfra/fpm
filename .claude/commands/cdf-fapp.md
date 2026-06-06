---
name: cdf-fapp
description: "fApp 프로젝트 tmux pane 관리 + 상태 인식 CMD 라우팅. cdf 스킬로 pane 생성 후 IDLE/CLAUDE/BUSY 상태별로 CMD를 전달함."
date: 2026-03-30
---

인자: $ARGUMENTS

# Phase 1: fApp 인덱스 변환 + CMD 분리

`data/fapp.txt`를 읽어 fApp 목록을 로드한 뒤, `$ARGUMENTS`를 `---` 기준으로 분리함.

```bash
# --- 기준으로 PANE_ARGS와 CMD 분리
if echo "$ARGUMENTS" | /usr/bin/grep -qE '(^|[ ])---[ ]|^---$'; then
  PANE_ARGS=$(echo "$ARGUMENTS" | /usr/bin/sed 's/[[:space:]]*---[[:space:]].*//' | /usr/bin/sed 's/^---$//')
  CMD=$(echo "$ARGUMENTS" | /usr/bin/sed 's/.*---[[:space:]]*//')
else
  PANE_ARGS="$ARGUMENTS"
  CMD=""
fi

# fApp 목록 로드
FAPP_NUMS=($(cat ~/git/___pm/data/fapp.txt 2>/dev/null || cat ~/_git/___pm/data/fapp.txt))
FAPP_COUNT=${#FAPP_NUMS[@]}

# 숫자 토큰을 1-based fApp 인덱스로 변환, 나머지 토큰은 유지
NEW_ARGS=""
for token in ${=PANE_ARGS}; do
  if echo "$token" | /usr/bin/grep -qE '^[0-9]+$' && [ "$token" -ge 1 ] && [ "$token" -le "$FAPP_COUNT" ]; then
    NEW_ARGS="$NEW_ARGS ${FAPP_NUMS[$token]}"
  else
    NEW_ARGS="$NEW_ARGS $token"
  fi
done

# 인자 없으면 전체 fApp 프로젝트
if [ -z "$(echo $NEW_ARGS | /usr/bin/tr -d ' ')" ]; then
  NEW_ARGS="${FAPP_NUMS[*]}"
fi

NEW_ARGS=$(echo "$NEW_ARGS" | /usr/bin/sed 's/^ //')
echo "변환: $NEW_ARGS"
echo "CMD: ${CMD:-없음}"
```

변환 예시 (fapp.txt = 11 12 13 14 15 16):
* (없음) → `11 12 13 14 15 16`
* `1 2 --- ls` → PANE_ARGS: `1 2`, CMD: `ls` → NEW_ARGS: `11 12`
* `--- claude "/run"` → PANE_ARGS: (없음), NEW_ARGS: `11 12 13 14 15 16`, CMD: `claude "/run"`

# Phase 2: cdft 함수로 tmux pane 생성 → WIN_NAME 획득

`~/.zsh_functions`의 `cdft()` 함수를 직접 호출하여 pane 생성/매칭:

```bash
CDFT_OUTPUT=$(cdft :fapp $NEW_ARGS 2>&1)
echo "$CDFT_OUTPUT"
WIN_NAME=$(echo "$CDFT_OUTPUT" | /usr/bin/grep "WIN_NAME=" | /usr/bin/sed 's/WIN_NAME=//')

if [ -z "$WIN_NAME" ]; then
  echo "오류: WIN_NAME 획득 실패"
  echo "$CDFT_OUTPUT"
  exit 1
fi
echo "WIN_NAME: $WIN_NAME"
```

# Phase 3: 상태 분류

CMD가 없으면 Phase 3-4를 생략하고 종료.

CMD가 있으면 `pm:$WIN_NAME` 윈도우의 각 pane 상태를 분류:

```bash
TMUX=/opt/homebrew/bin/tmux
pane_count=$($TMUX list-panes -t "pm:$WIN_NAME" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')

detect_pane_state() {
  local target="$1"   # ex: "pm:fapp2.0"

  # MISSING
  $TMUX list-panes -t "$target" &>/dev/null || { echo "MISSING"; return; }

  # CLAUDE — claude 프로세스 확인
  local pane_pid=$($TMUX display-message -t "$target" -p '#{pane_pid}')
  local claude_cnt=$(pgrep -P "$pane_pid" -f "node.*claude\|claude.*node" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
  [ "$claude_cnt" -gt 0 ] && { echo "CLAUDE"; return; }

  # IDLE — 쉘 프롬프트 패턴 확인
  local last_line=$($TMUX capture-pane -t "$target" -p -l 3 2>/dev/null | tail -1)
  echo "$last_line" | /usr/bin/grep -qE '[$%#>] *$' && { echo "IDLE"; return; }

  echo "BUSY"
}

for ((i=0; i<pane_count; i++)); do
  target="pm:$WIN_NAME.$i"
  state=$(detect_pane_state "$target")
  echo "[$target] $state"
done
```

# Phase 4: CMD 라우팅

각 pane 상태에 따라 CMD를 전달:

```bash
route_cmd() {
  local target="$1"
  local state="$2"
  local cmd="$3"

  case "$state" in
    IDLE)
      # 쉘 프롬프트 → CMD 직접 실행
      $TMUX send-keys -t "$target" "$cmd" Enter
      echo "  → IDLE: 직접 실행"
      ;;
    CLAUDE)
      # Claude Code 실행 중 → 슬래시 커맨드 추출해서 입력
      # ex: 'claude "/run" --dangerously-skip-permissions' → '/run'
      local slash=$(echo "$cmd" | /usr/bin/grep -oE '"(/[^"]+)"' | /usr/bin/tr -d '"')
      if [ -n "$slash" ]; then
        $TMUX send-keys -t "$target" "$slash" Enter
        echo "  → CLAUDE: 슬래시 커맨드 전달 ($slash)"
      else
        $TMUX send-keys -t "$target" "$cmd" Enter
        echo "  → CLAUDE: 그대로 전달"
      fi
      ;;
    BUSY)
      echo "  → BUSY: 스킵 (다른 프로세스 실행 중)"
      ;;
    MISSING)
      echo "  → MISSING: pane 없음 (오류)"
      ;;
  esac
}

for ((i=0; i<pane_count; i++)); do
  target="pm:$WIN_NAME.$i"
  state=$(detect_pane_state "$target")
  echo "[$target] $state"
  route_cmd "$target" "$state" "$CMD"
  /bin/sleep 0.1
done
```

# Phase 5: 결과 보고

```bash
echo "---"
echo "완료: pm:$WIN_NAME (${pane_count}개 pane), CMD: ${CMD:-없음}"
/usr/bin/say "fApp ready"
```



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
