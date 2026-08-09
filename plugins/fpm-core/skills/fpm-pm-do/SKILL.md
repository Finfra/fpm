---
title: fpm-pm-do
description: 다른 프로젝트(prj)로 명령을 위임하고 완료 시까지 동기 블로킹 후 결과(commit hash)를 회수함. 의존성(`* depends:`) 메타가 선언된 이슈는 선행 prj 작업을 자동 위임·대기 후 본 작업 진행
date: 2026-05-16
---

# 진입 게이트 — 위임은 명시 opt-in (Issue286)

본 스킬은 **명시 위임 토큰**(`pm-do`·`/pm-do`·`prj<N>`·"N번 프로젝트")이 있을 때만 진입한다.

* bare 숫자로 시작하는 입력(`11 /dev`, `3 해결해줘`)은 **현재 프로젝트의 이슈 번호** → 본 스킬 호출 금지
* 양쪽으로 읽히면 `AskUserQuestion` 1회 확인. 수면 모드 규칙①(자율 진행) 적용 제외 — 타 prj 세션 기동은 현재 프로젝트 밖 부작용 = 크리티컬
* 상세: [`~/.claude/rules/input-interpretation-rules.md`](../../rules/input-interpretation-rules.md)

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
  # Issue371 축D — 괄호 주석 제거 후 트림. ⚠️ `${dep%%(*}` 금지: zsh 가 `(` 를 glob 으로
  #   읽어 `bad pattern` 으로 전건 실패한다(실측). sed 로 자른다.
  dep=$(echo "$dep" | /usr/bin/sed -E 's/\(.*//; s/^[[:space:]]*//; s/[[:space:]]*$//')
  [ -z "$dep" ] && continue

  # issue-g 규칙2 의 2형식. 서브이슈(Issue334_1) 포함.
  #   ⚠️ 종전 sed 치환 1발은 **매치 실패 시 원본을 반환**해 DEP_PRJ 에 문자열 전체가 들어갔다.
  #      같은 prj 형식(`Issue<M>`)·괄호 주석·타 prj 서브이슈가 전부 깨졌다(실측 2026-08-09).
  DEP_PRJ=""; DEP_ISS=""
  if echo "$dep" | /usr/bin/grep -qE '^prj[0-9]+#Issue[0-9]+(_[0-9]+)*$'; then
    DEP_PRJ=$(echo "$dep" | /usr/bin/sed -E 's/^prj([0-9]+)#Issue.*$/\1/')
    DEP_ISS=$(echo "$dep" | /usr/bin/sed -E 's/^prj[0-9]+#Issue(.*)$/\1/')
  elif echo "$dep" | /usr/bin/grep -qE '^Issue[0-9]+(_[0-9]+)*$'; then
    DEP_ISS=$(echo "$dep" | /usr/bin/sed -E 's/^Issue(.*)$/\1/')
  else
    # 조용히 건너뛰지 않는다 — 선행을 빠뜨린 채 "해결됨" 을 내면 그게 더 위험하다
    echo "ERROR: depends 항목 파싱 실패 — '${dep}' (형식: prj<N>#Issue<M> 또는 Issue<M>)" && exit 1
  fi

  # 같은 prj 선행은 **위임하지 않는다** — 같은 프로젝트이므로 이 세션의 작업이다
  if [ -z "$DEP_PRJ" ]; then
    if dep_completed_local "$PWD" "$DEP_ISS"; then
      echo "[skip] Issue${DEP_ISS} (같은 prj) already ✅"; continue
    fi
    echo "ERROR: 같은 prj 선행 Issue${DEP_ISS} 미완료 — 위임 대상이 아니므로 중단" && exit 1
  fi

  # 이미 완료인지 검사 (타 prj)
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
  /usr/bin/awk '/^# ✅ 완료/{flag=1} flag && /^#{2,3} /{print}' "${path}/Issue.md" \
    | /usr/bin/grep -qE "^#{2,3} Issue${iss}:.*✅"
}
```

`dep_completed_local` (같은 prj — 경로를 직접 받는다):
```bash
dep_completed_local() {
  local path="$1" iss="$2"
  /usr/bin/awk '/^# ✅ 완료/{flag=1;next} flag && /^# /{flag=0} flag' "${path}/Issue.md" 2>/dev/null \
    | /usr/bin/grep -qE "^#{2,3} Issue${iss}:.*✅"
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

# Step 3~4: 비대화 1-shot 실행 (Issue299 — pending 방지)
#   ⚠️ 대화형 TUI 로 띄운 뒤 send-keys 로 프롬프트를 넣으면, 첫 실행 안내
#      (Chrome 확장 등)·편집 승인 게이트에서 **아무 작업도 못 하고 멈춘다**.
#      실측: 2026-07-26 위임 세션이 Chrome 프롬프트에서 작업 0으로 대기.
#   → 프롬프트를 인자로 넘기는 **`-p`(print) 비대화 모드**를 기본으로 한다.
#   ⚠️ 사용자 쉘 별칭 `cc`(= claude --dangerously-skip-permissions)는
#      **대화형 쉘 전용**이라 스크립트·send-keys 문맥에서는 풀네임을 쓴다.
RESOLVED_CMD=$(resolve_cmd "$CMD_RAW" "$SUFFIX")
# Issue351 — 변환이 원본 지시를 버리는 것을 막는다(실측 2026-08-06: 금지 문구 포함 명령이
#   "/issue-fix-g 40" 으로 축약되며 제약 전부 소실). 변환이 실제로 일어났을 때만 원문을 꼬리에 보존.
#   ⚠️ 한 줄 유지 — send-keys 는 개행을 그대로 흘려 대상 zsh 파싱을 깨뜨린다.
#   기본 안전 지시(파괴적 작업 금지)는 프롬프트가 아니라 아래 env 를 읽는
#   hooks/pm-do-safety-context.sh 가 SessionStart 에서 주입한다 — 변환 경로와 무관하게 항상 남는다.
DELEGATE_PROMPT="$RESOLVED_CMD"
if [ "$RESOLVED_CMD" != "$CMD_RAW" ]; then
  DELEGATE_PROMPT="${RESOLVED_CMD} — [원본 지시 원문 — 제약이 있으면 위 커맨드보다 우선] ${CMD_RAW}"
fi
# Issue342 S3 — 기동자 신호. SessionStart 훅이 caps.launched_by 로 실어 hub 카드가
#   위임 세션을 사람이 띄운 세션과 구분한다. 실동작 코드 `~/.bin/pm-do` 와 같은 값이어야 한다.
#   Issue351 — 같은 env 를 pm-do-safety-context.sh 도 읽는다. 값을 바꾸면 안전 지시가 끊긴다.
CLAUDE_BIN="FPM_SESSION_ORIGIN=pm-do claude --dangerously-skip-permissions"

if [ "$CLAUDE_CNT" -gt 0 ]; then
  # 이미 대화형 Claude 가 그 pane 을 점유 중 → 프롬프트만 입력(기존 경로).
  # 이 경로는 게이트에 걸릴 수 있으므로 아래 "pending 징후" 확인이 필수.
  # ⚠️ Issue351 — 세션이 이미 떠 있어 SessionStart 훅이 다시 돌지 않는다 → 기본 안전 지시
  #   미주입. 원본 보존(DELEGATE_PROMPT)만이 방어선이다. 무인 위임은 아래 -p 경로를 쓸 것.
  $TMUX send-keys -t "$TARGET" "$DELEGATE_PROMPT" Enter
  echo "[delegated:interactive] pm:${WIN_NAME}.0 ← ${DELEGATE_PROMPT}"
else
  # pane 이 비어 있으면 비대화 1-shot 으로 실행 (기본 경로)
  # ⚠️ Issue335 — send-keys 가 보낸 문자열은 대상 zsh 가 **다시 파싱**한다.
  #   프롬프트에 < > | $ 백틱이 있으면 리다이렉션·파이프로 해석되어 명령이 조각나고
  #   claude 가 아예 안 뜨거나 잘린 프롬프트를 받는다(2026-07-28 실측: `zsh: no such file or directory: 성공`).
  #   반드시 zsh ${(qq)} 로 단일 인자화할 것. 메타문자 개별 이스케이프는 누락이 남으므로 금지.
  QUOTED_CMD=${(qq)DELEGATE_PROMPT}
  $TMUX send-keys -t "$TARGET" "${CLAUDE_BIN} -p ${QUOTED_CMD}" Enter
  echo "[delegated:print] pm:${WIN_NAME}.0 ← ${CLAUDE_BIN} -p ${QUOTED_CMD}"
fi
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

# 실행 모드 — `-p` 비대화가 기본 (Issue299·Issue300)

> 규칙 SSOT: [`rules/session-delegation-rules.md`](../../rules/session-delegation-rules.md). 실동작 코드는 **`~/.bin/pm-do`** 이며 본 문서와 동일 분기를 갖는다(둘 중 하나만 고치면 반쪽 — Issue300 실측).

| 모드 | 명령 | 언제 | 특징 |
| :--- | :--- | :--- | :--- |
| **비대화(기본)** | `FPM_SESSION_ORIGIN=pm-do claude --dangerously-skip-permissions -p '<프롬프트>'` | 위임·자동화 전부 | 게이트 없음. 끝나면 프로세스 종료 → 완료 판정이 명확 |
| 대화형(예외) | `FPM_SESSION_ORIGIN=pm-do claude --dangerously-skip-permissions` + send-keys | 사람이 중간 개입할 작업 | **첫 실행 안내·승인 게이트에서 멈춘다**. 사람이 붙어 있을 때만 |

* `FPM_SESSION_ORIGIN=pm-do` 는 **기동자 신호**다(Issue342 S3) — hub 카드가 위임 세션을 사람이 띄운 세션과 구분한다. 빠뜨려도 위임 자체는 동작하나 카드에서 출처가 미상이 된다. ⚠️ **Issue351 이후로는 안전 지시 주입의 열쇠이기도 하다** — 빠뜨리면 방어선이 사라진다(아래)

## 안전 지시는 어디서 오는가 (Issue351)

위임 세션은 `--dangerously-skip-permissions` 로 돌아 **도구 승인 게이트가 0** 이다. [`session-delegation-rules.md`](../../rules/session-delegation-rules.md) 는 *"프롬프트에 파괴적 작업 금지를 명시하라"* 고 요구했지만, `resolve_cmd` 변환이 그 문구를 통째로 버렸다(실측 2026-08-06 — 금지 문구 포함 명령이 `/issue-fix-g 40` 으로 축약). 그래서 방어선을 **두 겹**으로 나눴다.

| 겹 | 무엇 | 어디서 | 변환에 견디나 |
| :--- | :--- | :--- | :--- |
| **기본** | 파괴적 작업 금지 일반 지시(`rm -rf`·`git reset --hard`·외부 시스템 쓰기·프로젝트 밖 부작용) | [`hooks/pm-do-safety-context.sh`](../../hooks/pm-do-safety-context.sh) — `FPM_SESSION_ORIGIN=pm-do` 를 보고 SessionStart 에서 `additionalContext` 주입 | ✅ 프롬프트를 안 거치므로 무관 |
| **특화** | 이 작업 한정 제약(ex: *"rclone 실행 금지"*) | `DELEGATE_PROMPT` — 변환이 일어났을 때 원문을 꼬리에 보존 | ✅ 변환돼도 원문이 남음 |

* **왜 프롬프트에만 두지 않았나** — 변환 경로가 늘어날 때마다 방어선이 다시 샌다. 기동 신호(env)는 변환과 독립이다
* ⚠️ **대화형 경로는 기본 겹이 없다** — 세션이 이미 떠 있으면 SessionStart 가 다시 돌지 않는다. 특화 겹만 유효하므로 무인 위임에는 `-p` 를 쓴다
* 위임 세션이 두 겹을 모두 받으면 **더 구체적인 쪽(특화)이 우선**한다. 단 범위를 넓히는 방향으로는 해석하지 않는다

* 사용자 쉘에서 손으로 띄울 때는 별칭 `cc -p '<프롬프트>'` 가 동일하다. **별칭은 대화형 쉘 전용**이므로 스크립트·`send-keys`·cron 에서는 `claude --dangerously-skip-permissions -p` 풀네임을 쓴다
* `-p` 는 1-shot 이다. 다단계 대화가 필요하면 프롬프트에 절차를 전부 적거나 `--continue`/`--resume` 으로 이어붙인다
* **pending 징후**: `tmux capture-pane` 에 `Do you want`·`❯ 1. Yes`·`Enter to confirm` 이 보이면 게이트에 걸린 것이다. 위임이 진척 0 이면 이걸 먼저 확인한다

# 완료 폴링

동기·비동기 양쪽이 **단일 폴링 지점**(`poll_delegate`)을 쓴다. 결과는 `POLL_*` 전역으로 돌려준다.

```bash
# 반환 0=완료 · 3=타임아웃이지만 세션은 아직 작업 중 · 2=타임아웃+세션 종료
poll_delegate() {
  local prj_path="$1" iss_num="$2" target="$3"
  local max_iters=$((TIMEOUT / POLL_INTERVAL))
  local start_ts=$(/bin/date +%s) iter=0
  POLL_HASH=""; POLL_ELAPSED=0; POLL_ITERS=0
  while [ "$iter" -lt "$max_iters" ]; do
    if is_completed "$prj_path" "$iss_num"; then
      POLL_HASH=$(extract_hash "$prj_path" "$iss_num")
      POLL_ELAPSED=$(( $(/bin/date +%s) - start_ts )); POLL_ITERS=$iter
      return 0
    fi
    /bin/sleep "$POLL_INTERVAL"; iter=$((iter + 1))
  done
  POLL_ELAPSED=$(( $(/bin/date +%s) - start_ts )); POLL_ITERS=$iter
  pane_has_claude "$target" && return 3   # Issue371 축C
  return 2
}
```

## 축C — 타임아웃은 실패가 아니다 (Issue371)

종전엔 `TIMEOUT` 초과를 무조건 실패로 보고해서 **31분에 끝난 작업도 실패로 읽혔다**. 이제 `pane_has_claude` 로 위임 세션 생존을 확인해 갈라 본다:

| 반환 | 상황 | 보고 |
| :-: | :--- | :--- |
| 0 | `✅` 감지 | 완료 + hash + 소요시간 |
| **3** | 타임아웃 + **세션 생존** | *"진행 중 — 실패가 아니다"*. `PM_DO_TIMEOUT` 증액 또는 `--no-wait` 전환 안내 |
| 2 | 타임아웃 + 세션 종료 | 실패. `✅` 미기록 |

## 축A — `--no-wait` 완료 알림 (Issue371)

종전 `--no-wait` 는 던지고 끝이라 **완료를 아무도 알려주지 않았다.** 백그라운드 감시를 붙이고 결과를 호출자 수신함에 넣는다.

```bash
if [ "$wait_mode" != "wait" ]; then
  send_sh="$HOME/.claude/hooks/session-send.sh"
  [ -x "$send_sh" ] || { echo "[pm-do] WARN: ${send_sh} 없음 — 감시 없이 리턴"; return 0; }
  caller_pwd="$PWD"
  (
    poll_delegate "$prj_path" "$iss_num" "$target"; rc=$?
    case "$rc" in
      0) msg="✅ prj${prj_num}#Issue${iss_num} 완료 — hash ${POLL_HASH:-noHash} (${POLL_ELAPSED}s)" ;;
      3) msg="⏳ … ${TIMEOUT}s 경과했으나 위임 세션은 아직 작업 중. 실패가 아니다" ;;
      *) msg="⚠️ … ${TIMEOUT}s 타임아웃 + 세션 종료(✅ 미기록). 확인 필요" ;;
    esac
    "$send_sh" "$caller_pwd" "$msg" "pm-do"
  ) >/dev/null 2>&1 &
  echo "[pm-do] --no-wait — 즉시 리턴. 완료되면 다음 프롬프트에 알림이 뜬다"
  return 0
fi
```

* 배달은 [`hooks/session-inbox.sh`](../../hooks/session-inbox.sh) 가 호출자의 **다음 프롬프트**에 주입한다(pull). **새 hook 을 만들지 않는다**
* ⚠️ **push(`send-keys`)로 알리지 않는다** — 비tmux·IDE 세션에 닿지 않고, 상대가 입력 중이면 깨지고, 전달 여부를 알 수 없다
* ⚠️ `>/dev/null 2>&1 &` 로 fd 를 끊는다 — 안 끊으면 호출자(Claude Bash 도구 등)가 자식의 파이프를 기다려 **즉시 리턴이 무의미해진다**
* 실행 검증(2026-08-09): 발신 → 수신함 생성 → hook 주입 → `read/` 이동 전 단계 통과. 백그라운드 감시는 부모 스크립트 종료 후에도 생존 확인

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

# 사용자 승인 (Opus 4.8 실행 제약)

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

* **`~/.claude/_doc_arch/fpm-do-design.md` — 본 자산의 설계 SSOT (prj3 소유)**. 자산 3벌 동기화 경계(⚠️ prj1 plugin 배포판이 Issue351 미반영), 실행 10단계 실측, `--auto-deps` 파싱 결함. ⚠️ 본 SKILL 은 *실행 단계*, 설계 문서는 *왜·어디가 갈라졌나*를 담는다
* `~/.claude/_doc_arch/session-delegation-design.md` — 위임 아키텍처 전반(3계층 중복·결손·DB 도입 경계)
* **`~/.claude/rules/session-delegation-rules.md` — 세션 기동 표준 SSOT (Issue300)**. `-p` + `--dangerously-skip-permissions` 강제, 게이트를 사용자에게 넘기지 않기
* `~/.claude/rules/issue-g.md` 규칙2 `* depends:` 필드 정의 (Issue17)
* `~/_git/___pm/.claude/skills/cdf/index.md` — tmux pane 라우팅
* `~/_git/___pm/Projects.md` — 번호↔경로↔Domain SSOT
* `~/.bin/pm-do` — bash 호출용 래퍼 (비-Claude 컨텍스트)

# Opus 4.8 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-8-execution-rules.md`](~/.claude/rules/opus-4-8-execution-rules.md) 참조. 이 skill 특화:

* 재귀 위임 depth 상한: 3 (무한 루프 방지)
* 폴링 횟수 상한: `TIMEOUT / POLL_INTERVAL` (기본 30회)
* 사용자 승인 필수: 첫 위임 직전 1회 + `--auto-deps` 다건 시 일괄 1회
* 파괴적 동작 없음 — kill·rm·force-push 미사용
