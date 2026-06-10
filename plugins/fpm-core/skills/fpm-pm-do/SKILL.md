---
title: fpm-pm-do
description: 다른 프로젝트(prj)로 명령을 위임하고 완료 시까지 동기 블로킹 후 결과(commit hash)를 회수함. 의존성(`* depends:`) 메타가 선언된 이슈는 선행 prj 작업을 자동 위임·대기 후 본 작업 진행
date: 2026-05-16
---

# 개요

`pm-do <prj번호> "<명령>"` — 호출한 prj에서 다른 prj로 명령을 위임함. 대상 prj의 Issue.md `✅ 완료` 섹션에 해당 이슈 hash가 출현할 때까지 동기 대기 후 hash를 회수함.

핵심 시나리오:
* prj1.IssueN이 prj2.IssueM 선행 필요 → `pm-do 2 "이슈M 해결"` 호출 → prj2 완료까지 블로킹 → 완료 hash 반환 → prj1.N 본 작업 진행
* 이슈 frontmatter 또는 항목에 `* depends: prj<N>#Issue<M>` 선언 시 `/pm-do --auto-deps`로 자동 해결

# 인자

| 형태                            | 설명                                                                            |
| :------------------------------ | :------------------------------------------------------------------------------ |
| `pm-do <번호> "<명령>"`         | 단일 위임. ex: `pm-do 15 "이슈3 해결"`                                          |
| `pm-do --auto-deps`             | 호출 컨텍스트의 현재 이슈 `* depends:` 파싱 후 미완료 dep 순차 위임             |
| `pm-do --auto-deps <IssueN>`    | 명시한 이슈의 `* depends:` 처리                                                 |
| `pm-do --no-wait <번호> "<명령>"` | 위임만 하고 즉시 리턴 (블로킹 생략). 본 이슈는 수동 재개                       |
| `pm-do --status <번호>`         | 대상 prj 윈도우 capture만 출력                                                  |

# Projects.md lookup

```bash
PM_BASE="$HOME/_git/___pm/projects"
PRJ_NUM="$1"
PRJ_PATH_RAW=$(/bin/cat "${PM_BASE}/${PRJ_NUM}" 2>/dev/null)
[ -z "$PRJ_PATH_RAW" ] && echo "ERROR: prj ${PRJ_NUM} not in ${PM_BASE}" && exit 1
PRJ_PATH=$(echo "$PRJ_PATH_RAW" | /usr/bin/sed "s|^~|$HOME|")
[ ! -d "$PRJ_PATH" ] && echo "ERROR: ${PRJ_PATH} dir missing" && exit 1
```

# 도메인 자동 판정

```bash
PROJECTS_MD="$HOME/_git/___pm/Projects.md"
DOMAIN=$(/usr/bin/grep -E "^\| +${PRJ_NUM} +\|" "$PROJECTS_MD" | /usr/bin/awk -F'|' '{print $4}' | /usr/bin/tr -d ' ')
case "$DOMAIN" in
  m)      SUFFIX="-m" ;;
  w)      SUFFIX="-w" ;;
  *)      SUFFIX="-g" ;;
esac
```

명령 변환 규칙:
* `이슈N 해결` / `Issue N 해결` / `Issue N fix` → `/issue-fix${SUFFIX} N`
* `이슈N 등록` → `/issue-reg${SUFFIX} ...`
* 슬래시 명령(`/...`)으로 시작 → 그대로 전달
* 그 외 자연어 → 그대로 전달 (Claude가 해석)

# 의존성 사전 해결

호출자가 `--auto-deps` 모드면:

```bash
CALLER_ISSUE_MD="${PWD}/Issue.md"
[ ! -f "$CALLER_ISSUE_MD" ] && echo "ERROR: caller Issue.md missing" && exit 1

CURRENT_ISSUE="${2:-$(detect_current_issue)}"  # 인자 또는 진행중 첫 이슈

DEPS=$(/usr/bin/awk -v iss="$CURRENT_ISSUE" '
  $0 ~ "^## "iss":" {flag=1; next}
  flag && /^## / {flag=0}
  flag && /^\* depends:/ {print; flag=0}
' "$CALLER_ISSUE_MD" | /usr/bin/sed 's/^\* depends:[[:space:]]*//')

# DEPS = "prj15#Issue3, prj25#Issue7"
echo "$DEPS" | /usr/bin/tr ',' '\n' | while IFS= read -r dep; do
  dep=$(echo "$dep" | /usr/bin/sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  [ -z "$dep" ] && continue
  DEP_PRJ=$(echo "$dep" | /usr/bin/sed -E 's/^prj([0-9]+)#.*/\1/')
  DEP_ISS=$(echo "$dep" | /usr/bin/sed -E 's/.*#Issue([0-9]+)$/\1/')
  # 이미 완료인지 검사
  if dep_completed "$DEP_PRJ" "$DEP_ISS"; then
    echo "[skip] $dep already ✅"
    continue
  fi
  # depth 증가 + 재귀 위임 (DFS)
  : ${PM_DO_DEPTH:=0}
  if [ "$PM_DO_DEPTH" -ge "${PM_DO_DEPTH_LIMIT:-3}" ]; then
    echo "ERROR: depth limit (${PM_DO_DEPTH_LIMIT:-3}) reached at $dep" && exit 1
  fi
  PM_DO_DEPTH=$((PM_DO_DEPTH+1)) pm-do "$DEP_PRJ" "이슈${DEP_ISS} 해결" || exit 1
done
```

`dep_completed`:
```bash
dep_completed() {
  local prj="$1" iss="$2"
  local path_raw=$(/bin/cat "${PM_BASE}/${prj}" 2>/dev/null)
  local path=$(echo "$path_raw" | /usr/bin/sed "s|^~|$HOME|")
  [ ! -f "${path}/Issue.md" ] && return 1
  /usr/bin/awk '/^# ✅ 완료/{flag=1} flag && /^## /{print}' "${path}/Issue.md" \
    | /usr/bin/grep -qE "^## Issue${iss}:.*✅"
}
```

# tmux 위임 (cdf 재사용)

```bash
# Step 1: pm 세션에 prj 윈도우 확보 (cdf 호출)
WIN_NAME=$(cdft "${PRJ_NUM}" 2>&1 | /usr/bin/grep -oE 'WIN_NAME=[^[:space:]]+' | /usr/bin/sed 's/WIN_NAME=//')
[ -z "$WIN_NAME" ] && echo "ERROR: cdf failed" && exit 1

TMUX=/opt/homebrew/bin/tmux
TARGET="pm:${WIN_NAME}.0"

# Step 2: pane 상태 확인
PANE_PID=$($TMUX display-message -t "$TARGET" -p '#{pane_pid}' 2>/dev/null)
CLAUDE_CNT=$(pgrep -P "$PANE_PID" -f "node.*claude\|claude.*node" 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')

# Step 3: Claude 미가동이면 띄움
if [ "$CLAUDE_CNT" -eq 0 ]; then
  $TMUX send-keys -t "$TARGET" "claude --dangerously-skip-permissions" Enter
  /bin/sleep 5  # Claude 부팅 대기
fi

# Step 4: 명령 변환 후 전달
RESOLVED_CMD=$(resolve_cmd "$CMD_RAW" "$SUFFIX")
$TMUX send-keys -t "$TARGET" "$RESOLVED_CMD" Enter
echo "[delegated] pm:${WIN_NAME}.0 ← ${RESOLVED_CMD}"
```

`resolve_cmd`:
```bash
resolve_cmd() {
  local cmd="$1" suffix="$2"
  if echo "$cmd" | /usr/bin/grep -qE '^/'; then
    echo "$cmd"; return
  fi
  local issnum=$(echo "$cmd" | /usr/bin/grep -oE '(이슈|Issue)[[:space:]]*[0-9]+' | /usr/bin/grep -oE '[0-9]+' | head -1)
  if [ -n "$issnum" ] && echo "$cmd" | /usr/bin/grep -qE '(해결|fix|close|종결)'; then
    echo "/issue-fix${suffix} ${issnum}"; return
  fi
  if [ -n "$issnum" ] && echo "$cmd" | /usr/bin/grep -qE '(등록|reg|register)'; then
    echo "/issue-reg${suffix}"; return
  fi
  echo "$cmd"
}
```

# 완료 폴링

```bash
POLL_INTERVAL="${PM_DO_POLL_INTERVAL:-60}"
TIMEOUT="${PM_DO_TIMEOUT:-1800}"
MAX_ITERS=$((TIMEOUT / POLL_INTERVAL))

iter=0
while [ "$iter" -lt "$MAX_ITERS" ]; do
  HASH=$(extract_completion_hash "$PRJ_PATH" "$ISS_NUM")
  if [ -n "$HASH" ]; then
    echo "[completed] prj${PRJ_NUM}#Issue${ISS_NUM} → ${HASH}"
    echo "$HASH"
    exit 0
  fi
  /bin/sleep "$POLL_INTERVAL"
  iter=$((iter+1))
done

# 타임아웃: capture로 상황 출력
echo "ERROR: timeout (${TIMEOUT}s) for prj${PRJ_NUM}#Issue${ISS_NUM}"
$TMUX capture-pane -t "$TARGET" -p -l 50
exit 2
```

`extract_completion_hash`:
```bash
extract_completion_hash() {
  local path="$1" iss="$2"
  /usr/bin/awk '/^# ✅ 완료/{flag=1; next} flag && /^# /{flag=0} flag' "${path}/Issue.md" \
    | /usr/bin/grep -E "^## Issue${iss}:.*✅" \
    | /usr/bin/grep -oE 'commit:[[:space:]]*[a-f0-9]+' \
    | /usr/bin/sed 's/commit:[[:space:]]*//' \
    | head -1
}
```

* hash 추출 패턴: `Issue<N>:.*commit: <hash>.*✅`
* hash 없이 ✅만 있으면 hash 자리에 `noHash` 반환 후 사용자 안내

# 사용자 승인 (Opus 4.7 실행 제약)

호출 직전 출력 후 컨펌:

```
[pm-do plan]
  대상 prj: 15 (~/_git/__all/fSnippet)
  도메인: m → /issue-fix-m
  명령: /issue-fix-m 3
  타임아웃: 1800s, 폴링: 60s
진행할까요? (y/N)
```

`--auto-deps`로 다건 위임 시 전체 계획을 일괄 출력 후 한 번에 컨펌.

# 환경 변수

| 변수                  | 기본값 | 설명                           |
| :-------------------- | :----- | :----------------------------- |
| `PM_DO_POLL_INTERVAL` | 60     | 폴링 간격 (초)                 |
| `PM_DO_TIMEOUT`       | 1800   | 타임아웃 (초, 30분)            |
| `PM_DO_DEPTH_LIMIT`   | 3      | 재귀 의존성 depth 상한         |
| `PM_DO_DEPTH`         | 0      | 내부 사용 (재귀 카운터)        |

# 보고 형식

성공:
```
[pm-do] prj15#Issue3 → completed
  hash: 7a8f3c2
  duration: 612s (10.2m)
  poll iters: 11
```

실패(타임아웃):
```
[pm-do] prj15#Issue3 → TIMEOUT
  elapsed: 1800s
  last pane capture (50 lines):
  ...
```

# 의존 룰·SCAR

* `~/.claude/rules/issue-g.md` 규칙2 `* depends:` 필드 정의 (Issue17)
* `~/_git/___pm/.claude/skills/cdf/index.md` — tmux pane 라우팅
* `~/_git/___pm/Projects.md` — 번호↔경로↔Domain SSOT
* `~/.bin/pm-do` — bash 호출용 래퍼 (비-Claude 컨텍스트)

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 skill 특화:

* 재귀 위임 depth 상한: 3 (무한 루프 방지)
* 폴링 횟수 상한: `TIMEOUT / POLL_INTERVAL` (기본 30회)
* 사용자 승인 필수: 첫 위임 직전 1회 + `--auto-deps` 다건 시 일괄 1회
* 파괴적 동작 없음 — kill·rm·force-push 미사용
