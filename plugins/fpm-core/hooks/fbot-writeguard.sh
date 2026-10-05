#!/usr/bin/env bash
# fbot-writeguard.sh — 매니저의 **월권**(Issue607)과 팀장의 **분업 회피**(Issue612)를 함께 막는다
#
# 축이 둘이고 강도가 다르다:
#   ① 권한 축(chief·hr·scout) — 남의 prj 산출물 수정 **무조건 deny**
#   ② 분업 축(lead)           — 자기 prj 수정 권한은 있으나, **직능 자리가 있으면 배분 의무**.
#                               자리 없음 · 이 세션의 배분 1건 · 사유 기록 중 하나면 통과(조건부 deny)
# 발동: 결속 마커 있는 세션 + 그 봇이 매니저·팀장 + 도구가 Edit/Write/NotebookEdit
#       + 대상 경로가 관할 예외 밖  → permissionDecision=deny
# no-op: 마커 부재(일반 세션 — 프로세스 0회) · 워커(실작업이 임무) · 예외 경로 · 재료 부재
#
# ⚠️ **Bash 쓰기는 막지 않는다**(두 축 공통 한계). PreToolUse 가 보는 것은 Edit/Write 계열뿐이라
#   `sed -i`·heredoc 은 그대로 통과한다. 이 가드는 우회 불가능한 봉쇄가 아니라 **기본 경로에서
#   조항을 상기시키는 장치**다 — 봉쇄를 원하면 판정을 커밋 시점(사후 감사)으로 옮겨야 한다 🚧
# ⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude 면 Issue.md 등록 후)
#
# 왜 차단인가 (사용자 지시 2026-09-09):
#   *"총괄핀봇이 들여다볼 수는 있으나 해당 프로젝트의 수정 작업은 팀장핀봇을 통해야 한다."*
#   없으면 ① 같은 파일을 두 주체가 고쳐 충돌 ② HR핀봇 오작동 ③ 필요한 핀봇 리크루팅 실패.
#   Issue605 의 환기(advisory)는 보고도 무시하면 그만이었다 — 실측에서 조항을 읽고도 직접 고쳤다.
#
# 🔑 **읽기는 막지 않는다.** 매니저는 들여다봐야 판단한다. 막는 것은 쓰기뿐이다.
#   선례: prj3 의 글로벌 SCAR 가드(*"cwd ≠ ~/.claude → 즉시 수정 금지, 이슈 등록 후 별도 세션"*).
#   **남의 영역은 그 영역 담당을 통한다** 는 같은 원리를 핀봇 조직 전체로 넓힌 것이다.
#
# fail-open: 판정 재료(마커·DB·경로)가 없으면 **허용**한다. 가드가 일반 세션의 편집을 막으면
#   그 피해가 훨씬 크다 — 차단은 재료가 다 갖춰져 확실할 때만.
set -uo pipefail

_input="$(cat)"
# 세션 id 는 env 가 정본이다(Claude Code 가 넣는다). 다만 env 가 비는 경로(테스트 하네스 등)를 위해
#   payload 의 session_id 로 폴백한다 — 폴백이 없으면 가드가 조용히 통과해 버린다.
_SID="${CLAUDE_CODE_SESSION_ID:-}"
if [ -z "$_SID" ]; then
  _SID="$(printf '%s' "$_input" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
fi
[ -n "$_SID" ] || exit 0
_MARK="$HOME/.claude/.fbot-handoff/sid-$_SID.id"
# ← 게이트. 일반 세션(FBOT_ID 없음 · 마커 없음)은 여기서 끝이다(외부 프로세스 0회).
#   ⚠️ **마커 단독 게이트는 틀렸다** (Issue612 qa 검토 + 실측 2026-09-10): 팀장이 규칙대로
#   `Agent(name='fbot-…')` 으로 워커를 띄우면 하청 lifecycle 이 **부모 세션의 마커를 덮어쓰고
#   끝날 때 지운다**(agent-bind → state bind → agent-done). 즉 **규칙을 지킨 배분이 그 세션의
#   가드를 통째로 끄는** 역설이 성립했다. 실측: 마커 소멸 + 부모 봇이 checkout 으로 전이.
[ -f "$_MARK" ] || [ -n "${FBOT_ID:-}" ] || exit 0
# 파싱 단일 지점 — 디스패처 경유가 아니므로 jq 1회(hook-input.sh 와 같은 필드명)
if [ "${HOOK_INPUT_PARSED:-0}" = "1" ]; then
  _tool="${HOOK_TOOL:-}"; _file="${HOOK_FILE:-}"
else
  command -v jq >/dev/null 2>&1 || exit 0
  eval "$(printf '%s' "$_input" | jq -r '@sh "_tool=\(.tool_name // "") _file=\(.tool_input.file_path // "")"' 2>/dev/null)" || exit 0
fi
# prj3#Issue617 — **Bash 경유 쓰기가 가드를 통째로 비켜갔다**(총괄핀봇 자기 신고 2026-09-10).
#   `python3 - <<PY … open(p,"w") … PY` · `sed -i` · `> file` 은 Edit/Write 를 쓰지 않으므로
#   matcher 에 걸리지 않는다. 우회가 의도적일 필요도 없다 — 여러 파일을 한 번에 고칠 때
#   힙독은 자연스러운 선택이고, 그래서 **나쁜 의도 없이 매일 새는 구멍**이었다.
#   Bash 는 `file_path` 가 없다. 판정 재료는 명령 문자열뿐이라 두 단을 거친다:
#     ⓐ 쓰기 의도가 보이는가(동사·API) ⓑ 그 대상이 관할 예외인가(경로 문자열 등장)
#   판정 불가는 **통과**다 — 가드가 일반 작업을 막는 피해가 우회보다 크다(fail-open 유지).
case "$_tool" in
  Edit|Write|NotebookEdit|MultiEdit) ;;
  Bash)
    if [ "${HOOK_INPUT_PARSED:-0}" = "1" ]; then
      _cmd="${HOOK_CMD:-}"
    else
      _cmd="$(printf '%s' "$_input" | jq -r '.tool_input.command // ""' 2>/dev/null)"
    fi
    [ -n "$_cmd" ] || exit 0
    # ⓐ 쓰기 의도 — 리다이렉트는 `>/dev/null`·`2>&1` 을 걸러야 조회 명령이 걸리지 않는다
    _w=0
    case "$_cmd" in
      *"sed -i"*|*"tee "*|*"truncate "*) _w=1 ;;
      *'open('*'"w"'*|*"open("*"'w'"*|*".write("*|*"write_text("*|*"writelines("*) _w=1 ;;
      *"os.replace("*|*"shutil.copy"*|*"shutil.move"*|*"Path("*".write"*) _w=1 ;;
      *"git checkout -- "*|*"git restore "*|*"git apply"*) _w=1 ;;
    esac
    if [ "$_w" = "0" ]; then
      # 리다이렉트 — /dev/null·$TMPDIR·/tmp 로 가는 것은 산출물이 아니다
      _probe="$(printf '%s' "$_cmd" | sed -e 's#2>&1##g' -e 's#>&2##g' -e 's#>>*[[:space:]]*/dev/null##g' \
                                          -e "s#>>*[[:space:]]*\${TMPDIR:-/tmp}[^[:space:]]*##g" \
                                          -e 's#>>*[[:space:]]*/tmp/[^[:space:]]*##g' \
                                          -e 's#>>*[[:space:]]*/private/tmp/[^[:space:]]*##g')"
      case "$_probe" in *">"*) _w=1 ;; esac
    fi
    [ "$_w" = "1" ] || exit 0
    # ⓑ 관할 예외가 명령에 보이면 통과 — 매니저 직무(등록·보고·조직 선언)다
    case "$_cmd" in
      *"Issue.md"*|*"Issue_OLD.md"*|*"_doc_work/htm/"*|*"_doc_work/report/"*) exit 0 ;;
      *"data/fbot/org/"*|*".sleep-log/"*) exit 0 ;;
    esac
    _file="(Bash 명령)"
    ;;
  *) exit 0 ;;
esac
[ -n "$_file" ] || exit 0

# 정체성 원천 우선순위: **$FBOT_ID(세션 불변) → 마커 내용**.
#   마커는 세션당 1개 파일에 **마지막 결속 1건만** 담는다(fbot-state.py `write_sid_marker`).
#   Agent 하청은 부모와 같은 session_id 를 쓰므로 그 파일을 워커 id 로 덮어쓴다 — 마커를 믿으면
#   부모 세션의 편집이 워커 role 로 판정되어 두 축이 동시에 no-op 이 된다(Issue449 가 heartbeat 에서
#   이미 겪은 실패의 재발). FBOT_ID 는 세션 기동 시 한 번 심기고 하청이 바꾸지 못한다.
_BOT="${FBOT_ID:-}"
[ -n "$_BOT" ] || _BOT="$(cat "$_MARK" 2>/dev/null)"
[ -n "$_BOT" ] || exit 0
_DB="${AOA_MEMORY_DIR:-$HOME/_git/___common/data/aoa}/registry.db"
[ -f "$_DB" ] || exit 0
command -v sqlite3 >/dev/null 2>&1 || exit 0
# SQL 문자열 삽입 전 홑따옴표 이스케이프 — bot_id 는 채용 경로가 늘수록 통제가 약해지는 값이다
_BOTQ="${_BOT//\'/\'\'}"
_row="$(sqlite3 "$_DB" "SELECT role || '|' || COALESCE(prj,'') FROM bot WHERE bot_id='$_BOTQ'" 2>/dev/null)"
_role="${_row%%|*}"; _prj="${_row#*|}"
# 축이 둘이다 (prj3#Issue612):
#   ① 권한 축 — 매니저(chief·hr·scout)는 **남의 prj** 산출물을 못 고친다. 무조건 deny.
#   ② 분업 축 — 팀장(lead)은 **자기 prj** 를 고칠 권한이 있으나, 그 일에 **직능 자리가 있으면
#      배분 의무**다. 조건부 deny — 자리 없는 일까지 막으면 팀장이 아무 일도 못 한다.
# 워커는 어느 축의 대상도 아니다 — 실작업이 임무다.
case "$_role" in chief|hr|scout) _axis=권한 ;; lead) _axis=분업 ;; *) exit 0 ;; esac

# ── 관할 예외: 매니저가 직접 써도 되는 것 ──────────────────────────────
#   등록(Issue.md)·보고(_doc_work/htm·report)·조직 선언(data/fbot/org). 매뉴얼상 "등록·배분·보고" 범위다.
case "$_file" in
  */Issue.md|*/Issue_OLD.md)               exit 0 ;;
  */_doc_work/htm/*|*/_doc_work/report/*)  exit 0 ;;
  "$HOME"/.claude/data/fbot/org/*)         exit 0 ;;
  */.sleep-log/*)                          exit 0 ;;
esac

# ── ② 분업 축 (prj3#Issue612) — 팀장은 자리가 있으면 배분한다 ───────────────
#   판정 재료 3종: ⓐ 그 prj 조직 선언의 워커 자리 ⓑ 공석 여부 ⓒ 이 세션의 배분 이력.
#   ⓑ 는 **통과 사유가 아니다** — 공석은 배분을 막는 조건이 아니라 채용을 부르는 조건이고
#   (dispatch 가 HR 게이트로 hire 한다), 공석을 면제로 읽으면 *"자리가 비었으니 내가 한다 →
#   그래서 영영 안 채워진다"* 는 이슈가 겨냥한 악순환 그 자체가 된다.
if [ "$_axis" = "분업" ]; then
  [ -n "$_prj" ] || exit 0                      # prj 미해소 → 자리 판정 불가 → fail-open
  # 조직 선언 경로는 env 로 갈아끼운다 — 회귀가 **운영 데이터**를 읽으면 org/3.yml 에서 자리를
  #   하나 빼는 것만으로 테스트 결과가 바뀐다(qa 검토 지적: hermetic 하지 않다).
  _ORGDIR="${FBOT_ORG_DIR:-$HOME/.claude/data/fbot/org}"
  _ORG="$_ORGDIR/${_prj}.yml"
  [ -f "$_ORG" ] || exit 0                      # 조직 선언 없음 → 자리 없음과 같다 → 직접 수행
  _ext="$(sed -n 's/^extends:[[:space:]]*//p' "$_ORG" | head -1)"
  #   주석 줄은 센다고 자리가 되지 않는다 — `# role: qa` 같은 설명이 자리로 잡히면 오탐이 된다
  _seats="$(cat "$_ORG" ${_ext:+"$_ORGDIR/$_ext"} 2>/dev/null \
            | grep -v '^[[:space:]]*#' \
            | sed -n 's/.*role:[[:space:]]*\([a-z][a-z0-9_-]*\).*/\1/p' \
            | grep -v '^lead$' | sort -u | tr '\n' ' ')"
  [ -n "$_seats" ] || exit 0                    # ⓐ 워커 자리 0 → 팀장이 직접 한다
  # ⓒ **최근 배분·우회 이력.** 처음에는 "이 세션" 을 결속 마커 mtime 으로 잘랐으나, 그 마커는
  #   하청 lifecycle 이 덮어쓰고 지운다(위 게이트 주석) — 경계의 기준점 자체가 움직인다.
  #   그래서 세션 경계를 흉내내지 않고 **시간 창**으로 바꿨다. 조항이 겨냥한 것은
  #   *"지난주 배분으로 오늘의 직접 수정을 면제받는 것"* 이고, 창 하나로 그것은 그대로 막힌다.
  #   느슨해지는 지점은 명시한다 — 같은 창 안의 **다른 작업** 배분도 통과로 친다. 오탐(정상 작업
  #   차단)이 미탐보다 비싸다는 이 가드의 원칙에 맞춘 선택이다.
  _win="${FBOT_DISPATCH_WINDOW_SEC:-21600}"     # 기본 6시간 — 한 작업 세션의 대략적 길이
  case "$_win" in ''|*[!0-9]*) _win=21600 ;; esac
  _acts="$(sqlite3 "$_DB" "SELECT COUNT(*) FROM job WHERE owner='$_BOTQ' AND kind IN ('fbot_dispatch','fbot_solo') AND created_at >= strftime('%s','now') - $_win" 2>/dev/null)"
  [ "${_acts:-0}" = "0" ] || exit 0             # 배분했거나 사유를 남겼다 → 통과
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[핀봇 분업 규칙 — %s(팀장·prj%s)] 이 prj 에는 직능 자리가 있다: %s— **자리가 있는 일은 배분한다**(사용자 확정 2026-09-10: 검토→qa · 설계→architect · 배포→release). 대상: %s — 팀장이 직접 하면 워커가 채용되지 않고, 채용이 없으니 그 부서는 빈 자리로 남아 다음에도 팀장이 직접 하게 된다(조직도의 자리가 장식이 된다). ① 배분: python3 ~/.claude/hooks/fbot-lead.py dispatch --by %s --role <qa|architect|release|…> --cwd <prj 경로> --issue Issue<N> → 응답의 next_step 실행. ② 자리 없는 일·긴급 건이면 사유를 원장에 남기고 진행: python3 ~/.claude/hooks/fbot-lead.py solo --by %s --reason <왜 직접 하는가> (사유 없는 우회만 막는다 — 기록하면 통과하고 감사에서 fbot-lead.py status 의 solo 축으로 드러난다). 등록(Issue.md)·보고(_doc_work/{htm,report})·조직 선언은 지금도 자유다."}}\n' \
    "$_BOT" "$_prj" "$_seats" "$_file" "$_BOT" "$_BOT"
  exit 0
fi

# ── ① 권한 축 ────────────────────────────────────────────────────────────────
_pm_hint="fbot-org.py resolve --prj <N> 로 PM 을 찾아 fbot-lead.py dispatch --by ${_BOT} --role lead --bot-id <PM> --cwd <경로> --topic '<요지>' 로 배분하고, 응답의 next_step 을 실행한다."
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[핀봇 가드레일 — %s(%s)] 매니저는 prj 산출물을 직접 수정하지 않는다. 대상: %s — 읽기·조사는 자유지만 **쓰기는 그 prj 의 팀장핀봇(PM)을 통한다**(직접 고치면 같은 파일을 두 주체가 만져 충돌하고, 배분이 원장에 안 남아 HR·발굴 판정이 어긋난다). %s 매니저가 직접 써도 되는 것은 Issue.md 등록·_doc_work/{htm,report} 보고·data/fbot/org 조직 선언뿐이다."}}\n' \
  "$_BOT" "$_role" "$_file" "$_pm_hint"
exit 0
