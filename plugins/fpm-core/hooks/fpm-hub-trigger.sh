#!/bin/bash
# fpm-hub-trigger.sh — UserPromptSubmit hook
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/hub-mode-arch.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 프롬프트에 a모드 render 트리거 `..show` (Issue133, 구 `..hub` deprecated alias) 감지 시:
#   1. .hub-mode-active-<md5(cwd)[:8]> 플래그 touch (Q&A intercept 활성화, Issue283 cwd 스코프)
#   2. HTML 렌더링 + 기본 브라우저 표시 + 후속 질문 form 처리 지시문 주입
# `..hub stop` 또는 `..hub off` 감지 시 플래그 해제 (단방향 모드 복귀 — 토글은 `..hub` 유지)
# Issue133: render 트리거만 `..hub`→`..show` rename. 우산 토글(`..hub on|off|start|stop`)·
#   c모드(`..hub dash`)는 `..hub` 보존 (우산명 충돌 해소가 목적).
#
# Issue83: `..show` 마커가 없어도 cwd 가 ___pm 등록 프로젝트면 hub 기본 on (자동 모드).
#   비프로젝트(/tmp 등)는 기본 off. per-cwd 상태는 ~/.claude/.hub-state/<hash> (on|off).
#
# Issue86: `/hub on|off` · `..hub on|off` — 폴더별 자동 모드 명시 토글.
#   상태 파일만 전환, render-blocking 미발동 (bare `..show` 와 구분).
#
# 출력 경로 결정 (Issue21):
#   - hook 입력 JSON의 cwd에서 _doc_work/ 존재 확인 (Issue289)
#   - 활성 htm/ → legacy z_htm/ → htm/ 신규 순으로 채택, 없으면 /tmp/ fallback

input=$(cat)
# Issue283: cwd 스코프 플래그. cwd 파싱 후 `.hub-mode-active-<hash>` 로 재할당됨(아래).
#   전역 단일 파일 시절엔 hub on 세션 플래그를 off 세션 hook 이 주워 b모드 form 이 누수됨.
FLAG_FILE="$HOME/.claude/.hub-mode-active-none"
# Issue83: 프로젝트 폴더 hub 기본 on — per-cwd 상태 파일로 override
STATE_DIR="$HOME/.claude/.hub-state"
# Issue105: 시스템 단위 마스터 OFF 플래그 (모든 프로젝트 자동 모드 차단)
SYSTEM_OFF_FLAG="$HOME/.claude/.hub-system-off"

# hook 입력 JSON 에서 cwd / prompt / session_id 파싱.
# Issue305_3: 종전에는 필드마다 python3 를 띄워 3회 × ~20ms 를 고정 지출했다.
#   1회 호출로 세 값을 **쉘 인용된 대입문**으로 받아 eval 한다(shlex.quote → 작은따옴표
#   포장이라 프롬프트에 개행·따옴표·`$`·백틱이 있어도 안전). NUL 구분자 방식은 불가 —
#   bash command substitution 이 NUL 을 버린다(실측).
# F2-1: 파싱 단일 지점(jq 기반, hooks/hook-input.sh). 디스패처가 미리 파싱했으면 비용 0.
# shellcheck source=/dev/null
. "$HOME/.claude/hooks/hook-input.sh"
hook_input_parse "$input"
_hookjson_cwd="$HOOK_CWD"
_hookjson_prompt="$HOOK_PROMPT"
_hookjson_session_id="$HOOK_SESSION_ID"
cwd="${_hookjson_cwd-}"
prompt="${_hookjson_prompt-}"

# ── 프롬프트 트리거 선행 게이트 (F2-7, 2026.07.31) ──────────────────────
# 이 hook 은 `..show`·`..hub on`·`..text` 같은 트리거를 찾느라 프롬프트를 **13~15회**
# grep 한다. 매번 `printf | grep` 2프로세스라 no-op 경로에서만 ~40ms 를 지출했다.
# 그런데 그 패턴들이 찾는 선행 토큰은 셋뿐이다: `..` · `/` · `sleep`.
# 셋 중 아무것도 없으면 **어떤 패턴도 매칭될 수 없으므로** grep 을 통째로 건너뛴다.
#
# ⚠️ 게이트 문자를 좁히지 말 것 —
#   · `/` 필수: 739행이 `^/<커맨드>` (임의 슬래시 커맨드)를 본다
#   · `sleep` 필수: 64행 패턴의 `(\.\.|/)?sleep[[:space:]]+off` 는 **접두 없이도** 매칭된다
#   새 트리거를 추가하면서 선행 문자가 늘면 여기도 같이 늘려야 한다. 안 그러면 그 트리거는
#   조용히 죽는다(게이트에서 걸러져 grep 까지 도달하지 못함).
case "$prompt" in
  *".."*|*"/"*|*[Ss][Ll][Ee][Ee][Pp]*) _HUB_TRIG_MAYBE=1 ;;
  *)                                   _HUB_TRIG_MAYBE=0 ;;
esac

# _hub_pmatch [-i] <정규식> — 프롬프트 매칭. 게이트 미통과 시 프로세스 0으로 즉시 실패.
_hub_pmatch() {
  local _ci=0
  if [ "${1:-}" = "-i" ]; then _ci=1; shift; fi
  [ "$_HUB_TRIG_MAYBE" = 1 ] || return 1
  # ⚠️ 아래 두 줄은 **실제 grep 이어야 한다**. 일괄 치환 시 이 안까지 바뀌면 자기 자신을
  #   호출해 무한 재귀에 빠진다(F2-7 1차 시도에서 실제로 발생 — 발동 경로가 25s 타임아웃).
  if [ "$_ci" = 1 ]; then
    printf '%s' "$prompt" | grep -qiE "$1"
  else
    printf '%s' "$prompt" | grep -qE "$1"
  fi
}

# 수면 모드 가드 (Issue278 / Issue281) — 활성 + 명시 hub 트리거 부재 시 자동 렌더 억제.
#   sleep-mode-trigger.sh 가 규칙을 주입하고, 여기서는 자동 hub 렌더 지시를 방출하지 않게 한다
#   (단일 책임 분리). 사용자가 `..show`/`..ask`/`..board`/`..hub`/`..sleep off` 를 명시하면 존중.
#   Issue281: 판정을 hooks/sleep-state.sh 로 단일화(전역 OR per-cwd) + config `rules.suppress_hub` 존중.
SLEEP_SUPPRESS_HUB=0
if [ -f "$HOME/.claude/hooks/sleep-state.sh" ]; then
  # shellcheck source=/dev/null
  . "$HOME/.claude/hooks/sleep-state.sh"
  if sleep_is_active "$cwd" && sleep_rule_on suppress_hub; then
    SLEEP_SUPPRESS_HUB=1
  fi
elif [ -f "$HOME/.claude/.sleep-mode-active" ]; then
  SLEEP_SUPPRESS_HUB=1
fi
if [ "$SLEEP_SUPPRESS_HUB" = "1" ]; then
  if ! _hub_pmatch -i '(^|[[:space:]])(\.\.show|/show|\.\.ask|/ask|\.\.board|\.\.dashboard|/dashboard|\.\.hub|/hub|(\.\.|/)?sleep[[:space:]]+off)([[:space:]]|$)'; then
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## 😴 수면 모드 — 자동 hub 렌더 억제 (Issue278)\n\n수면 모드 중 자동 HTML 렌더/브라우저 open 금지. **평문 채팅으로 진행** — HTML 미작성·브라우저 미open. 함께 온 요청은 수면 규칙(권장형 자율 진행)대로 정상 수행. 명시 렌더가 필요하면 사용자가 `..show` 를 직접 입력. 해제는 `sleep off`."
  }
}
JSON
    exit 0
  fi
fi

# `..hub list` · `/hub list` — 등록 프로젝트 hub on/off 상태 일괄 조회(조회 전용, 토글 아님).
#   hub 웹 UI Project List 팝업을 열지 않고 채팅에서 바로 확인하기 위함.
#   server.py _load_projects_list()/_htm_state() 판정 로직을 python으로 복제.
if _hub_pmatch -i '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+list([[:space:]]|$)'; then
  python3 <<'PYEOF'
import hashlib, json, os

home = os.path.expanduser("~")
system_off = os.path.exists(os.path.join(home, ".claude", ".hub-system-off"))
state_dir = os.path.join(home, ".claude", ".hub-state")
projects_md = os.path.join(home, "_git", "___pm", "Projects.md")

rows = []
try:
    with open(projects_md, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 5:
                continue
            try:
                pid = int(cells[0])
            except ValueError:
                continue  # 헤더·구분선 행 skip
            name = cells[1]
            emoji = cells[6] if len(cells) > 6 else ""
            path = cells[4].strip("`").strip() if len(cells) > 4 else ""
            rows.append((pid, name, emoji, path))
except FileNotFoundError:
    pass

def state_of(path):
    if system_off:
        return "\U0001F534 off(시스템)"
    abs_path = os.path.expanduser(path).rstrip("/")
    if not abs_path:
        return "\U0001F7E2 on"
    h = hashlib.md5(abs_path.encode("utf-8")).hexdigest()[:8]
    content = None
    try:
        for fn in os.listdir(state_dir):
            if fn == h or fn.startswith(h + "__"):
                with open(os.path.join(state_dir, fn), encoding="utf-8") as sf:
                    content = sf.read().strip()
                break
    except (FileNotFoundError, OSError):
        pass
    return "\U0001F534 off" if content == "off" else "\U0001F7E2 on"

lines = ["| 번호 | 프로젝트 | hub |", "| :--- | :--- | :--- |"]
for pid, name, emoji, path in sorted(rows):
    label = f"{emoji} {name}".strip()
    lines.append(f"| {pid} | {label} | {state_of(path)} |")
table = "\n".join(lines)

ctx = (
    "## hub 프로젝트 on/off 목록 — `..hub list`\n\n"
    "hub 웹 Project List 팝업 없이 채팅에서 바로 확인. 아래 표를 그대로 응답 (재계산·재조회 금지):\n\n"
    f"{table}\n\n"
    "### 본 turn 처리\n"
    "- 조회 전용 — 렌더·폼·워크플로우 진입 금지. 위 표만 출력.\n"
    "- 개별 토글: `..hub on|off` (이 폴더) / `..hub on|off all` (시스템)"
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}, ensure_ascii=False))
PYEOF
  exit 0
fi

. "$HOME/.claude/hooks/lib/hub-context.sh"
hub_ctx_identity

# Issue163: `..text`/`..txt`/`/text`/`/txt` — 단발(이번 turn 한정) render-off 트리거.
#   state/flag 파일 무변경 (영속 토글 `..hub stop`/`off` 와 구분). 본 turn 자동 hub 렌더만 suppress.
#   자동 모드 분기(IS_PROJECT)·`..show` 렌더 분기보다 먼저 평가 — 렌더 진입 차단이 목적.
#   `..te?xt|/te?xt` 로 text/txt 4종 동시 커버. `..hub` 토글류(on/off/start/stop 접미 필요)와 비충돌.
# prj3#Issue199: bare `..text` (요청 텍스트 없이 마커만) 은 "재실행" 이 아니라 "직전 결과를 text 로 표시".
#   사유: `..show`/`..ask` 렌더가 브라우저에 안 떠서 사용자가 `..text` 로 확인할 때, 기존 문구는
#   "작업 정상 수행" → Claude 가 직전 작업을 재실행 → 멱등성 없는 세션에서 이중 실행 부작용.
#   토큰 제거 후 잔여 텍스트 유무로 bare vs `..text <요청>` 분기.
if _hub_pmatch -i '(^|[[:space:]])(\.\.te?xt|/te?xt)([[:space:]]|$)'; then
  rm -f "$FLAG_FILE"  # 자동 모드가 켰을 수 있는 이번 turn 렌더 플래그 해제 (state 파일 불변)
  # 마커 토큰 제거 후 잔여(공백 제외) 유무 판정
  _text_rest=$(printf '%s' "$prompt" | sed -E 's#(\.\.te?xt|/te?xt)# #g' | tr -d '[:space:]')
  if [ -z "$_text_rest" ]; then
    # bare `..text` — 직전 결과 재표시 (재실행 금지)
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 단발 render-off — bare `..text` (직전 결과 재표시, prj3#Issue199)\n\n요청 텍스트 없는 단독 `..text` = **'직전 turn 결과를 평문으로 다시 보여줘'** 의미 (재실행 아님). `..show`/`..ask` 렌더가 브라우저에 안 떴을 때 결과 확인용.\n\n**⚠️ 작업 재실행 금지.** 멱등성 없는 세션 이중 실행 방지 — 이미 수행된 작업(슬래시 커맨드·dev 사이클·커밋·설치 등)을 다시 실행하지 말 것. 대화 맥락의 **직전 응답 결과만 평문 채팅으로 요약·표시**. HTML 미작성·브라우저 미open. state/flag 무변경 → 다음 turn 자동 hub 모드 복귀.\n\n직전 결과가 대화 맥락에 없으면(세션 경계 등) 그 사실을 알리고 재실행 여부를 사용자에게 확인."
  }
}
JSON
  else
    # `..text <요청>` — 함께 온 요청은 정상 수행 + 평문 응답 (기존 동작)
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 단발 render-off — `..text <요청>` (Issue163)\n\n이번 turn 한정 자동 hub 렌더 skip. **평문 채팅으로 응답** — HTML 문서 미작성·브라우저 미open. 함께 온 요청(슬래시 커맨드·dev 사이클·커밋 등)은 정상 수행. state/flag 파일 무변경 → 다음 turn 자동 hub 모드 복귀.\n\n영속 끄기는 `..hub stop`(이 폴더만) / `..hub off`(시스템 전체)."
  }
}
JSON
  fi
  exit 0
fi

# Issue200: 토글 스코프 통일 (Issue105 재정의)
#   * 토글 verb = on/off. 스코프 기본=프로젝트(현재 cwd), `all` 접미=시스템 전체.
#     - `..hub on|off`   · `/hub on|off`      → 프로젝트 단위 (STATE_FILE on/off)
#     - `..hub on|off all` · `/hub on|off all` → 시스템 단위 (SYSTEM_OFF_FLAG)
#   * 서버 lifecycle = start/stop/restart/status/disable/enable (slash 커맨드 전용).
#     hook 은 `/hub start|stop` 을 더 이상 가로채지 않음 → slash 커맨드가 서버 제어.
#   * `..hub start|stop` 은 프로젝트 on/off 의 deprecated alias (하위호환, `..hub` 전용).
#   * bare `..show <요청>` (구 `..hub`) 은 별도 분기 (render-only trigger, 아래)

# 토글 — `..hub on|off [all]` · `/hub on|off [all]`
#   매처 순서 주의: bare `on`/`off` 정규식이 `on all` 도 매칭하므로 `all` 변형을 먼저 평가.
HTM_ONOFF=""   # on | off
HTM_SCOPE=""   # system | project
if _hub_pmatch -i '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+on[[:space:]]+all([[:space:]]|$)'; then
  HTM_ONOFF="on"; HTM_SCOPE="system"
elif _hub_pmatch -i '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+off[[:space:]]+all([[:space:]]|$)'; then
  HTM_ONOFF="off"; HTM_SCOPE="system"
elif _hub_pmatch -i '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+on([[:space:]]|$)'; then
  HTM_ONOFF="on"; HTM_SCOPE="project"
elif _hub_pmatch -i '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+off([[:space:]]|$)'; then
  HTM_ONOFF="off"; HTM_SCOPE="project"
fi

# 시스템 스코프 (`all`) — SYSTEM_OFF_FLAG 제어
if [ "$HTM_SCOPE" = "system" ]; then
  if [ "$HTM_ONOFF" = "on" ]; then
    rm -f "$SYSTEM_OFF_FLAG"
    rm -f "$FLAG_FILE"  # 본 turn 은 토글 전용 — 렌더 미진입
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 시스템 ON — `..hub on all` (Issue200)\n\n시스템 단위 마스터 OFF 플래그 (`~/.claude/.hub-system-off`) 제거. 모든 프로젝트의 자동 hub 모드 재활성 (per-cwd `off` 기록 폴더는 여전히 off 유지).\n\n### 본 turn 처리\n- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: `hub 시스템 on (all).`\n- 프로젝트 단위 끄기: `..hub off` (이 폴더만) / 시스템 전체 끄기: `..hub off all`"
  }
}
JSON
  else
    touch "$SYSTEM_OFF_FLAG"
    rm -f "$FLAG_FILE"
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 시스템 OFF — `..hub off all` (Issue200)\n\n시스템 단위 마스터 OFF 플래그 (`~/.claude/.hub-system-off`) 생성. 모든 프로젝트 자동 hub 모드 차단 (per-cwd `on` 기록 폴더 포함). bare `..show <요청>` render-only 트리거는 여전히 동작.\n\n### 본 turn 처리\n- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: `hub 시스템 off (all).`\n- 재활성: `..hub on all`"
  }
}
JSON
  fi
  exit 0
fi

# 프로젝트 스코프 토글 — `..hub on|off` 와 deprecated alias `..hub start|stop` 은
#   같은 일(STATE_FILE 기록 + 안내)을 한다. 종전에는 같은 python 블록이 **4벌** 있었고
#   차이는 제목 꼬리표와 알림 한 줄뿐이었다 (Issue424_2) → 인자 2개로 접었다.
# ⚠️ 조사가 값에 따라 다르다 — `on` **으로** 기록 / `off` **로** 기록. 통일하면 문구가 바뀐다.
_hub_toggle_project() {   # <on|off> [alias명]
  mkdir -p "$STATE_DIR"
  printf '%s' "$1" > "$STATE_FILE"
  rm -f "$FLAG_FILE"   # 토글 전용 — 렌더 미진입. 다음 turn 부터 자동 모드가 상태 파일을 따른다
  PROJECT_LABEL="$PROJECT_LABEL" CWD_HASH="$CWD_HASH" HTM_VAL="$1" HTM_ALIAS="${2:-}" python3 <<'PYEOF'
import os, json
label = os.environ.get('PROJECT_LABEL', 'unknown')
h = os.environ.get('CWD_HASH', 'none')
val = os.environ.get('HTM_VAL', 'on')
alias = os.environ.get('HTM_ALIAS', '')
on = val == 'on'
josa = '으로' if on else '로'          # `on` 으로 / `off` 로 — 받침 차이
title_alias = f", `..hub {alias}` deprecated alias" if alias else ""
note = f" (알림: '..hub {alias}' 는 '..hub {val}' 으로 변경됨)" if alias else ""
body = ("다음 턴부터 자동 HTML 렌더 (trivial 응답은 Issue85 로 skip)." if on
        else "프로젝트 폴더라도 자동 렌더 안 함. AskUserQuestion 정상 동작 복귀.")
tail = ("- 끄려면 `..hub off` (이 폴더만) / 시스템 전체 끄기 `..hub off all`" if on
        else "- 다시 켜려면 `..hub on` (이 폴더만) / 시스템 전체 켜기 `..hub on all`")
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        f"## hub 프로젝트 {val.upper()} ({label} — Issue200{title_alias})\n\n"
        f"이 폴더의 자동 hub 모드를 `{val}` {josa} 기록 (`~/.claude/.hub-state/{h}__{label}`). "
        f"{body}\n\n"
        "### 본 turn 처리\n"
        "- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: "
        f"`hub 프로젝트 {val} ({label}).{note}`\n"
        f"{tail}"
    )
}}, ensure_ascii=False))
PYEOF
}

# 프로젝트 스코프 (기본) — per-cwd STATE_FILE 제어
if [ "$HTM_SCOPE" = "project" ]; then
  _hub_toggle_project "$HTM_ONOFF"
  exit 0
fi

# `..hub start|stop` — 프로젝트 on/off 의 deprecated alias (하위호환, `..hub` 전용).
#   `/hub start|stop` 은 여기서 매칭하지 않음 → slash 커맨드(서버 lifecycle)로 통과.
HTM_PROJ=""
_hub_alias=""
if _hub_pmatch -i '(^|[[:space:]])\.\.hub[[:space:]]+start([[:space:]]|$)'; then
  HTM_PROJ="on"; _hub_alias="start"
elif _hub_pmatch -i '(^|[[:space:]])\.\.hub[[:space:]]+stop([[:space:]]|$)'; then
  HTM_PROJ="off"; _hub_alias="stop"
fi
if [ -n "$HTM_PROJ" ]; then
  _hub_toggle_project "$HTM_PROJ" "$_hub_alias"
  exit 0
fi

# Issue24 Phase 7 / Issue37 / Issue41 / Issue126: `..hub dash` / `..dashboard` / `..board` — Mode C Live Dashboard agent 트리거
# Mode C 는 ___pm 서버(htm-server) 의 SSE 사용. hub Q&A 도 동일 서버 inbox 사용 (Issue45).
# Issue41 (2026-05-19): `..dashboard` alias 추가 — 자연어 매칭 강화
# Issue126 (2026-06-03): `..board <topic>` 신설 — c모드 단일 단어 트리거. `..hub dash`/`..dashboard` 는
#   하위호환 별칭으로 유지 (deprecation 예정, 즉시 제거 금지 — 기존 muscle memory 보호).
if _hub_pmatch '(^|[[:space:]])(\.\.hub[[:space:]]+dash|\.\.dashboard|\.\.board)([[:space:]]|$)'; then
  touch "$FLAG_FILE"
  SERVER_PORT="${HTM_SERVER_PORT:-9876}"
  health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://127.0.0.1:${SERVER_PORT}/healthz" 2>/dev/null)

  # topic 추출: "..hub dash <topic ...>" / "..dashboard <topic ...>" / "..board <topic ...>" 에서 트리거 다음 토큰들
  TOPIC=$(printf '%s' "$prompt" | sed -nE 's/.*(\.\.hub[[:space:]]+dash|\.\.dashboard|\.\.board)[[:space:]]+(.+)/\2/p' | head -1)
  # Issue131: --auto-kill 플래그 — 완료 alert 후 tmux window 자동 kill (기본 미설정 = 잔존, 로그 보존)
  AUTO_KILL=false
  if printf '%s' "$TOPIC" | grep -qE '(^|[[:space:]])--auto-kill([[:space:]]|$)'; then
    AUTO_KILL=true
    TOPIC=$(printf '%s' "$TOPIC" | sed -E 's/(^|[[:space:]])--auto-kill([[:space:]]|$)/ /g' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
  fi

  PROJECT_NAME="$PROJECT_NAME" \
    SERVER_PORT="$SERVER_PORT" \
    HEALTH="$health" \
    PROJECT_CWD="$cwd" \
    TOPIC="$TOPIC" \
    AUTO_KILL="$AUTO_KILL" \
    python3 <<'PYEOF'
import os, json
project_name = os.environ.get('PROJECT_NAME', 'unknown')
server_port = os.environ.get('SERVER_PORT', '9876')
health_ok = os.environ.get('HEALTH', '') == '200'
cwd = os.environ.get('PROJECT_CWD', '')
topic = os.environ.get('TOPIC', '').strip()
auto_kill = os.environ.get('AUTO_KILL', 'false') == 'true'

if not health_ok:
    context = (
        "## ⚠️ `..board` 트리거 — dashboard-server 미실행\n\n"
        f"Mode C(dashboard) agent 는 ___pm 서버 (port {server_port}, htm-server daemon) 필수. healthz 실패.\n\n"
        "### 즉시 조치\n"
        "1. 사용자에게 `/dashboard-server start` 안내 (Issue37 이후 명칭)\n"
        "2. 시작 후 다시 `..board <topic>` 입력 (별칭: `..hub dash` / `..dashboard`)\n\n"
        "본 turn 응답: agent 호출 금지. 채팅으로 서버 미실행 안내만."
    )
else:
    topic_clause = f"`{topic}`" if topic else "(사용자에게 topic 확인 필요)"
    context = (
        "## `..board` 트리거 감지 — Mode C Live Dashboard agent (Issue24 Phase 7, Issue126)\n\n"
        "(별칭: `..hub dash` / `..dashboard` — 하위호환 유지)\n\n"
        f"프로젝트 `{project_name}`. 본 turn 은 **dashboard agent 1회 호출 후 종료**. 다른 작업 금지.\n\n"
        "### 처리 절차 (필수)\n"
        f"1. **topic 확인**: 트리거에서 추출된 topic = {topic_clause}\n"
        "   - 비어있으면 사용자에게 topic 1회 질의 후 종료 (자동 추측 금지)\n"
        "2. **Agent 도구 호출**:\n"
        "   ```\n"
        "   Agent(\n"
        "     description='dashboard 시작',\n"
        "     subagent_type='dashboard',\n"
        "     prompt='topic=<TOPIC>; cwd=" + cwd + "; htm-server 활성. tmux pane 에서 runner 시작 + dashboard push. ~/.claude/agents/fpm-dashboard.md 절차 따를 것.'\n"
        "   )\n"
        "   ```\n"
        "3. agent 반환 결과를 채팅에 그대로 전달 (요약 + stable URL + pane 명령 + 핵심 데이터)\n\n"
        "### 4. 완료 폴러 기동 (Issue131 — finite 작업만)\n"
        "agent 반환 메타로 finite 판정:\n"
        "- worker_pid 설정 모니터링 / 큐 모드 → **finite** (status:done 도달) → 폴러 기동\n"
        "- 무한 heartbeat (worker_pid 미설정 순수 모니터링) → 폴러 **생략** (수동 stop 용도, alert 불필요)\n\n"
        "finite 면 turn 종료 전 `run_in_background: true` Bash 폴러 1개 기동 (DATA_FILE=agent 반환 dash.yaml 절대경로):\n"
        "```bash\n"
        "DATA_FILE='<dash.yaml 절대경로>'; TOPIC='<topic>'\n"
        "ETA_SEC=''   # agent ETA 추정 있으면 초 단위, 없으면 빈 값\n"
        "POLL=30; TIMEOUT=${ETA_SEC:+$((ETA_SEC*2))}; TIMEOUT=${TIMEOUT:-21600}   # 기본 6h (ETA 알면 ETA*2)\n"
        "START=$(date +%s)\n"
        "while :; do\n"
        "  st=$(yq -r '.status' \"$DATA_FILE\" 2>/dev/null)\n"
        "  case \"$st\" in\n"
        "    done) echo \"BOARD_DONE topic=$TOPIC\"; break;;\n"
        "    stopped|halted) echo \"BOARD_END topic=$TOPIC status=$st\"; break;;\n"
        "  esac\n"
        "  [ $(( $(date +%s) - START )) -ge \"$TIMEOUT\" ] && { echo \"BOARD_TIMEOUT topic=$TOPIC elapsed=$(( $(date +%s) - START ))s\"; break; }\n"
        "  sleep \"$POLL\"\n"
        "done\n"
        "```\n"
        "→ 폴러 exit 시 harness 가 본 세션 재호출. 폴 30s, 기본 만료 6h (SCAR 전역 스케줄링: crontab 금지·네이티브 폴링 허용).\n\n"
        "### 5. 완료 alert (폴러 exit 후 재호출 시)\n"
        "폴러 stdout 확인 후 채팅 alert:\n"
        "- `BOARD_DONE` → DATA_FILE `yq` read → ✅ `<topic>` 완료 · 소요시간 · 핵심 결과(checklist done 비율 / progress / 검증 통과) · 산출물 경로\n"
        "- `BOARD_END` (stopped/halted) → ⏹ 중단 alert (사유)\n"
        "- `BOARD_TIMEOUT` → ⏳ 폴러 만료 (ETA×2 또는 6h 경과, 여전히 running) → 폴러 재기동 여부 사용자 질의\n\n"
        + ("### 6. auto-kill (--auto-kill 지정됨)\n"
           "BOARD_DONE alert 후 tmux window 자동 종료: `cdft kill :<win_name>` (또는 `tmux kill-window -t pm:<win_name>`). 로그 유실 주의.\n\n"
           if auto_kill else
           "### 6. window 잔존 (기본 — --auto-kill 미지정)\n"
           "완료 후 tmux window 잔존 (로그 보존). alert 에 수동 kill 명령 안내: `cdft kill :<win_name>`.\n\n")
        + "### 채팅 응답 의무 (Issue24 Phase 8)\n"
        "- 한 줄 요약 (무엇을, 어디 pane 에)\n"
        "- stable URL 전체 (token 포함, 임의 제거 금지)\n"
        "- pane capture/kill 명령\n"
        "- 데이터 핵심 bullet 2~3개 (브라우저 못 봐도 채팅만으로 상태 파악 가능)\n"
        "- finite 면 폴러 기동 사실 명시 (\"완료 시 자동 alert\")\n\n"
        "### 구버전 (참고)\n"
        "Mode C skill (`~/.claude/skills/dashboard/`) 폐기됨. 본 turn 부터 agent 만 사용.\n"
    )

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
  exit 0
fi


# Issue126 (2026-06-03): `..ask <주제>` — b모드(양방향 Q&A 폼) 명시 진입점
# 기존 b모드는 트리거 단어 없이 AskUserQuestion intercept 로만 진입했으나, 이제 단일 단어
#   `..ask` 로 "나에게 물어봐" 모드를 직접 호출. 플래그 touch → 후속 AskUserQuestion 을
#   fpm-ask-intercept.sh 가 동일 form 자동 회수 경로로 처리 (인프라 재사용).
# 매칭: `..ask` 가 render 분기보다 먼저 평가되도록 bare `..show`/`..hub` 분기 위에 배치.
if _hub_pmatch -i '(^|[[:space:]])\.\.ask([[:space:]]|$)'; then
  # Issue283: `..ask` 는 1회성 진입 — state file 불변 (Issue178 이 `..show` 에 확립한 원칙 동일 적용).
  #   구 코드는 `printf 'on' > "$STATE_FILE"` 로 그 폴더 hub 를 영구 on 전환시켰음.
  touch "$FLAG_FILE"

  # topic 추출: "..ask <주제 ...>" 에서 트리거 다음 토큰들
  ASK_TOPIC=$(printf '%s' "$prompt" | sed -nE 's/.*\.\.ask[[:space:]]+(.+)/\1/p' | head -1)

  ASK_TOPIC="$ASK_TOPIC" \
    SERVER_PORT="${HTM_SERVER_PORT:-9876}" \
    python3 <<'PYEOF'
import os, json
topic = os.environ.get('ASK_TOPIC', '').strip()
server_port = os.environ.get('SERVER_PORT', '9876')
topic_clause = f"`{topic}`" if topic else "(트리거에 주제 없음 — 사용자 직전 맥락에서 결정 주제 도출)"

context = (
    "## `..ask` 트리거 감지 — b모드 (양방향 Q&A 폼 자동 회수, Issue126)\n\n"
    f"주제 = {topic_clause}\n\n"
    "`.hub-mode-active-<hash>` 플래그 활성화됨. 본 turn 은 **사용자에게 결정을 묻는 폼 1회 제시**가 목적 "
    "(\"나에게 물어봐\" 모드 — 응답 자체가 결정 회수 폼).\n\n"
    "### 처리 절차 (필수)\n"
    "1. 주제에 대해 사용자가 선택할 **2~4개 옵션**을 도출 (권장안은 첫 옵션 + label 끝 `(권장)`).\n"
    "   - 옵션 도출에 정보 제공·비교가 필요하면 먼저 간단한 본문 HTML(a모드 절차)로 옵션 설명·trade-off 렌더 후 폼 분리. trivial 하면 본문 생략하고 바로 폼.\n"
    "2. **`AskUserQuestion` 도구 호출** — `fpm-ask-intercept.sh` (PreToolUse hook)가 가로채 "
    "form HTML 생성·Firefox open·server inbox 자동 회수 지시를 주입함. 그 지시를 그대로 따를 것.\n"
    "   - 호출 예: `AskUserQuestion(questions=[{\"question\":\"...\",\"header\":\"...\",\"multiSelect\":false,"
    "\"options\":[{\"label\":\"A (권장)\",\"description\":\"...\"}, ...]}])`\n"
    "3. 텍스트 bullet 리스트로 선택지를 dump 하지 말 것 — 결정 요청은 반드시 `AskUserQuestion` 호출로 분리.\n\n"
    f"### 서버 전제\n"
    f"- ___pm htm-server (port {server_port}) 상시 운영 전제. 서버 down 시 intercept hook 이 fail-loud "
    "(`/dashboard-server start` 후 재시도 또는 `..hub stop` 안내).\n\n"
    "### 채팅 fallback 의무 (Issue60)\n"
    "- 폼 열림 안내 + 질문 텍스트 + 옵션 라벨/desc + 저장 경로 포함 (Firefox 부재 가정, 채팅만으로 답 가능).\n\n"
    "### 모드 관계\n"
    "- a모드(`..show`, 단방향 렌더) / b모드(`..ask`, 양방향 폼) / c모드(`..board`, dashboard) 3트리거 체계.\n"
    "- 토글은 hub 단위 공유: 끄기 `..hub stop` (이 폴더) / `..hub off` (시스템 전체)."
)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
  exit 0
fi


# B. Slash command + ..show(또는 구 ..hub) 끝 위치 → 경고 후 exit (사용자 위치 교정)
# 사유: `/dev 885 ..show` 형식은 slash command가 prompt 흡수 → hub additionalContext 무시됨
# Issue33: regex 강화 — `/단어<space|EOL>` 만 매칭. `/tmp/test2` 같은 file path 는 두 번째 `/` 로 인해 미매칭
if _hub_pmatch '^/[a-zA-Z][a-zA-Z0-9_-]*([[:space:]]|$)' && \
   _hub_pmatch '(\.\.show|\.\.hub)[[:space:]]*$'; then
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "⚠️ `..show`(렌더 트리거)를 slash command와 함께 쓸 때는 **맨 앞**에 두어야 작동. 예: `..show /dev 885`. 현재 prompt는 slash command가 흡수하여 hub 모드 미작동. 본 turn은 평소대로 처리. 다음 turn부터 위치 변경 권장."
  }
}
JSON
  exit 0
fi

# `..show`(구 `..hub` deprecated) 마커 감지: 공백 경계 또는 줄 끝
# Issue45 (2026-05-19): ___pm 상시 운영 전제. form 자동 회수 단일 경로 (paste-back 제거).
# 본문 HTML 은 file:// 직접 open. Q&A 만 intercept hook 이 ___pm htm-server inbox 로 자동 회수.
hub_ctx_surface

# Issue133: a모드 render 트리거 `..hub` → `..show` rename. `..show`/`/show` = primary,
#   `..hub`(bare) = 한시적 deprecated alias. 토글(`..hub on|off|start|stop`)·c모드(`..hub dash`)는
#   위 분기에서 이미 처리·exit 됨 — 여기 도달한 `..hub` 는 render-intent 뿐 (보존 아님).
# 서버 down 시 intercept hook fail-loud 안내.
HUB_RENDER_TRIGGER=""
if _hub_pmatch '(^|[[:space:]])(\.\.show|/show)([[:space:]]|$)'; then
  HUB_RENDER_TRIGGER="show"
elif _hub_pmatch '(^|[[:space:]])\.\.hub([[:space:]]|$)'; then
  HUB_RENDER_TRIGGER="hub-deprecated"
fi

# prj3#Issue-unreg: 미등록 폴더 렌더 게이트. unregistered_render=text(기본) 이면
#   미등록 폴더(IS_PROJECT=0)에서 렌더가 발동할 상황(명시 ..show OR state-file/EFFECTIVE=on)에
#   htm 을 만들지 않고 평문으로 응답 (사용자가 본 "invisible /tmp htm" 재발 차단).
#   `unregistered_render: hub` 로 바꾸면 이 게이트를 통과 → 위 /tmp 안전망(file:// open)으로 표시.
#   등록 프로젝트(IS_PROJECT=1)는 무관 — 게이트 미적용.
if [ "$IS_PROJECT" = "0" ] && [ "$UNREG_RENDER" != "hub" ] \
   && { [ -n "$HUB_RENDER_TRIGGER" ] || [ "$EFFECTIVE" = "on" ]; }; then
  rm -f "$FLAG_FILE"
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 렌더 skip — 미등록 폴더 (unregistered_render: text)\n\n현재 cwd 는 ___pm 등록 프로젝트가 아님(`Projects.md` 범위 밖). 미등록 폴더 기본 정책이 `text` 라 자동/`..show` hub 렌더를 발동하지 않음.\n\n**평문 채팅으로 응답** — HTML 문서 미작성·브라우저 미open. 요청된 작업(슬래시 커맨드·dev·커밋 등)은 정상 수행. state/flag 무변경.\n\n이 폴더에서도 hub 로 보고 싶으면: `hub_setting.yml` 고급 탭 `unregistered_render: hub` 로 변경(미등록 폴더는 /tmp 렌더 후 file:// 로 표시) 또는 이 폴더를 `Projects.md` 에 등록."
  }
}
JSON
  exit 0
fi

hub_ctx_live_preopen

if [ -n "$HUB_RENDER_TRIGGER" ]; then
  # 플래그 활성화 — 후속 AskUserQuestion 을 form 으로 가로채기 위함
  touch "$FLAG_FILE"
  # Issue178: `..show` = 그 턴만 1회성 렌더. STATE_FILE 미변경 (off 면 off 유지).
  #   과거 Issue83 은 여기서 `printf 'on' > "$STATE_FILE"` 로 영구 on 덮어썼으나
  #   "off 기본 + ..show 1회성" 모델과 충돌 → 제거. 자동 모드 재개는 STATE_FILE/IS_PROJECT default 가 결정.

  # --new flag 제거 (호환성 위해 prompt 에서 인식만, 동작 변화 없음)
  PROJECT_NAME="$PROJECT_NAME" \
    PROJECT_COLOR="$PROJECT_COLOR" \
    PROJECT_CWD="$cwd" \
    SID="$SID" \
    SID_FULL="$SID_FULL" \
    OUT_DIR="$OUT_DIR" \
    HTM_OPEN_CMD="$HTM_OPEN_CMD" \
    HUB_RENDER_TRIGGER="$HUB_RENDER_TRIGGER" \
    RENDER_TARGET="$RENDER_TARGET" \
    HUB_OPEN_SKIP="$HUB_OPEN_SKIP" \
    RENDER_HOST="$RENDER_HOST" \
    RENDER_PORT="$RENDER_PORT" \
    HUB_LINK_TARGET="$HUB_LINK_TARGET" \
    ZED_DOWNGRADED="$ZED_DOWNGRADED" \
    HUB_DOWN_DOWNGRADED="$HUB_DOWN_DOWNGRADED" \
    LIVE_OPENED="$LIVE_OPENED" \
    LIVE_URL="$LIVE_URL" \
    LIVE_DISPLAY="$LIVE_DISPLAY" \
    python3 "$HOME/.claude/hooks/lib/hub-instruction.py" show
  exit 0
fi

# Issue83: render 마커(`..show`/`..hub`) 없음 — 프로젝트 폴더는 hub 기본 on (per-cwd 상태 파일로 override)
# Issue105: 시스템 OFF 플래그가 최우선 — 존재 시 모든 프로젝트 자동 모드 차단
#   판정 우선순위: SYSTEM_OFF_FLAG > STATE_FILE > IS_PROJECT
#   (EFFECTIVE 는 prj3#Issue184 에서 render_target resolver 앞으로 이동 — 여기선 이미 계산됨. 재사용.)

if [ "$EFFECTIVE" = "on" ]; then
  # 플래그 활성화 — 후속 AskUserQuestion intercept + 선택지 자동 승격용
  touch "$FLAG_FILE"
  PROJECT_NAME="$PROJECT_NAME" \
    PROJECT_COLOR="$PROJECT_COLOR" \
    PROJECT_CWD="$cwd" \
    SID="$SID" \
    SID_FULL="$SID_FULL" \
    OUT_DIR="$OUT_DIR" \
    HTM_OPEN_CMD="$HTM_OPEN_CMD" \
    RENDER_TARGET="$RENDER_TARGET" \
    HUB_OPEN_SKIP="$HUB_OPEN_SKIP" \
    RENDER_HOST="$RENDER_HOST" \
    RENDER_PORT="$RENDER_PORT" \
    HUB_LINK_TARGET="$HUB_LINK_TARGET" \
    ZED_DOWNGRADED="$ZED_DOWNGRADED" \
    HUB_DOWN_DOWNGRADED="$HUB_DOWN_DOWNGRADED" \
    LIVE_OPENED="$LIVE_OPENED" \
    LIVE_URL="$LIVE_URL" \
    LIVE_DISPLAY="$LIVE_DISPLAY" \
    python3 "$HOME/.claude/hooks/lib/hub-instruction.py" auto
else
  # 비프로젝트 + 마커 없음, 또는 이 폴더 off 기록 → 플래그 비활성 (intercept 미동작)
  rm -f "$FLAG_FILE"
fi

exit 0
