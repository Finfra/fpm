#!/usr/bin/env bash
# fbot-writeguard.sh — 매니저의 **월권**(Issue607)과 팀장의 **직접 수행**(Issue612 → prj3#Issue757)을 함께 막는다
#
# 축이 둘이다 — 강도는 prj3#Issue757 C 로 같아졌다:
#   ① 권한 축(chief·hr·scout) — 남의 prj 산출물 수정 **무조건 deny**
#   ② 분업 축(lead)           — 팀장은 일을 하지 않는다(회의·모색·지시·수령·전달). **무조건 deny**.
#                               예외는 사람 승인(사람 세션의 `solo-approve`)을 받은 `solo` 의 창 안 하나다.
#                               종전 통과 조건 3종(자리 0 · 6시간 창 배분 · 사유 기록)은 걷었다 — 그 셋이
#                               팀장 직접 수행 141건의 통로였다(Issue757 실측)
# 발동: 결속 마커(세션 슬롯·하청 슬롯·FBOT_ID) 있는 세션 + **실행 주체**가 매니저·팀장
#       + 도구가 Edit/Write/NotebookEdit/MultiEdit/Bash + 대상이 관할 예외 밖 → permissionDecision=deny
# no-op: 마커 부재(일반 세션 — 프로세스 0회) · 워커(실작업이 임무) · 예외 경로 · 재료 부재
#        · 살아 있는 하청 슬롯 2건 이상(병렬 — 실행 주체 불명, prj3#Issue631)
#
# ⚠️ **Bash 판정은 명령 문자열 기반이다**(두 축 공통 한계). 리다이렉트·`sed -i`·힙독 `open(w)`
#   (Issue617)과 파일 동사 `rm`·`mv`·`cp`·`mkdir`·`touch`·`ln`·`trash`·`unlink`·`find -delete|-exec`·
#   `git commit|add|mv|rm|clean|stash|reset --hard`, 파이썬 삭제·이동 API(prj3#Issue757 C)를 본다.
#   변수로 명령을 조립하거나(`$CMD x`)·`eval`·스크립트 파일을 거치면 보이지 않는다 — 이 가드는
#   우회 불가능한 봉쇄가 아니라 **기본 경로에서 조항을 상기시키는 장치**다. 봉쇄는 사후 감사(nodelegate)가 맡는다
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

_input="$(< /dev/stdin)"   # prj3#Issue845 — cat fork 제거
# 세션 id 는 env 가 정본이다(Claude Code 가 넣는다). 다만 env 가 비는 경로(테스트 하네스 등)를 위해
#   payload 의 session_id 로 폴백한다 — 폴백이 없으면 가드가 조용히 통과해 버린다.
_SID="${CLAUDE_CODE_SESSION_ID:-}"
if [ -z "$_SID" ]; then
  _SID="$(printf '%s' "$_input" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
fi
[ -n "$_SID" ] || exit 0
# 마커 디렉토리. 주입구 `FBOT_HANDOFF_DIR` 은 **테스트 전용**이다 — 운영에선 설정하지 않는다
#   (fbot-state.py `sid_marker_path` 와 같은 이름·같은 기본값). 없으면 회귀가 **운영 마커
#   디렉토리**에 파일을 남기고 운영 하청 슬롯을 읽는다 — FBOT_ORG_DIR 이 조직 선언에서 이미
#   겪은 문제와 같다(Issue612 qa 검토: hermetic 하지 않다).
_HDIR="${FBOT_HANDOFF_DIR:-$HOME/.claude/.fbot-handoff}"
_MARK="$_HDIR/sid-$_SID.id"
# 하청 슬롯(prj3#Issue616 이 세션 슬롯과 갈라 놓은 두 번째 슬롯)의 prefix
_APAT="$_HDIR/sid-$_SID.agent-"
# ← 게이트. 일반 세션(FBOT_ID 없음 · 마커 없음 · 하청 슬롯 없음)은 여기서 끝이다(외부 프로세스 0회).
#   ⚠️ **마커 단독 게이트는 틀렸다** (Issue612 qa 검토 + 실측 2026-09-10): 팀장이 규칙대로
#   `Agent(name='fbot-…')` 으로 워커를 띄우면 하청 lifecycle 이 **부모 세션의 마커를 덮어쓰고
#   끝날 때 지운다**(agent-bind → state bind → agent-done). 즉 **규칙을 지킨 배분이 그 세션의
#   가드를 통째로 끄는** 역설이 성립했다. 실측: 마커 소멸 + 부모 봇이 checkout 으로 전이.
#   (prj3#Issue616 이 슬롯을 가른 뒤로 부모 마커는 그 자리에 남는다 — 위 역설 자체는 해소됐다.)
#   ⚠️ **두 조건만으로도 아직 모자란다** (prj3#Issue631): 부모가 결속되지 않은 세션에서 핀봇을
#   `Agent` 로 띄우면 **하청 슬롯만** 생기므로 게이트가 통째로 꺼진다. 세 번째 조건을 더한다.
#   비용은 glob 1회(fork 0)이고, **앞의 두 builtin 판정이 다 실패할 때만** 돈다(규칙3 — 싼 판정부터).
if [ ! -f "$_MARK" ] && [ -z "${FBOT_ID:-}" ]; then
  _agate=0
  for _f in "$_APAT"*.id; do [ -f "$_f" ] && { _agate=1; break; }; done
  [ "$_agate" = "1" ] || exit 0
fi
# 파싱 단일 지점 — 디스패처 경유가 아니므로 jq 1회(hook-input.sh 와 같은 필드명)
if [ "${HOOK_INPUT_PARSED:-0}" = "1" ]; then
  _tool="${HOOK_TOOL:-}"; _file="${HOOK_FILE:-}"
else
  command -v jq >/dev/null 2>&1 || exit 0
  # NotebookEdit 은 `notebook_path` 다 — `file_path` 만 읽으면 판정에서 빠진다(codex 2차 N9)
  eval "$(printf '%s' "$_input" | jq -r '@sh "_tool=\(.tool_name // "") _file=\(.tool_input.file_path // .tool_input.notebook_path // "")"' 2>/dev/null)" || exit 0
fi
# prj3#Issue617 — **Bash 경유 쓰기가 가드를 통째로 비켜갔다**(총괄핀봇 자기 신고 2026-09-10).
#   `python3 - <<PY … open(p,"w") … PY` · `sed -i` · `> file` 은 Edit/Write 를 쓰지 않으므로
#   matcher 에 걸리지 않는다. 우회가 의도적일 필요도 없다 — 여러 파일을 한 번에 고칠 때
#   힙독은 자연스러운 선택이고, 그래서 **나쁜 의도 없이 매일 새는 구멍**이었다.
#   Bash 는 `file_path` 가 없다. 판정 재료는 명령 문자열뿐이라 **두 갈래**로 본다 (prj3#Issue757 C 재구성):
#     ⓐ 파이썬 쓰기 API(`open(…,"w")`·`shutil.rmtree(` …) — python 을 부르는 명령에서만 본다(grep 으로 API 이름을
#        찾는 조회를 막지 않게 — codex 2차 O5). 대상을 해석할 수 없어 `shcmd.py apiwrites` 가 **경로 리터럴 전부**가
#        임시·관할 예외일 때만 통과시킨다(문자열 어딘가의 `Issue.md` 로 제품 파일까지 면제하던 것 — 2차 N6)
#     ⓑ 셸 판정(리다이렉트·파일 동사·`sed -i`·`tee`·git·셸 `-c`·명령 치환·issue-tx) — 대상이 해석된다.
#        `shcmd.py mutates` 가 **대상마다** 관할 예외를 보고, 같은 명령 안의 임시 변수·`cd /tmp/…` 를 따라간다
#   python 기동은 역할이 매니저로 판정된 **뒤**다 — 워커의 `git status` 마다 fork 하지 않는다
#   판정 불가는 **통과**다 — 가드가 일반 작업을 막는 피해가 우회보다 크다(fail-open 유지).
# 관할 예외 — 매니저가 써도 되는 것. 파일 도구(`[[ =~ ]]`)와 Bash 대상(shcmd `--allow`)이 **이 한 정규식**을 쓴다
#   (ERE·python 공통 문법). 등록·보고·조직 선언·sleep 로그 + 산출물 아닌 세션 기록(auto-memory·그 동반 정보 파일)
#   폴더 자체도 예외다(`mkdir -p _doc_work/report` — codex 2차 O4). 대상은 shcmd 가 `./`·`~`·`..` 를 정규화한 뒤 본다
_ALLOW_RE='(^|/)Issue(_OLD)?\.md$|(^|/)_doc_work/(htm|report)(/|$)|(^|/)\.claude/data/fbot/org(/|$)|^data/fbot/org(/|$)|(^|/)\.sleep-log(/|$)|/\.claude/projects/[^/]+/memory(/|$)|/\.claude/(learning_log|knowledge_base)\.md$'
_wa=0; _wv=0; _appr=0; _cmd=""
case "$_tool" in
  Edit|Write|NotebookEdit|MultiEdit) ;;
  Bash)
    if [ "${HOOK_INPUT_PARSED:-0}" = "1" ]; then
      _cmd="${HOOK_CMD:-}"
    else
      _cmd="$(printf '%s' "$_input" | jq -r '.tool_input.command // ""' 2>/dev/null)"
    fi
    [ -n "$_cmd" ] || exit 0
    # ⓐ 파이썬 쓰기 API — python 호출이 있을 때만. `sys.stdout.write(` 는 출력이지 파일 쓰기가 아니다(2차 O8)
    case "$_cmd" in
      *python*)
        _pc="${_cmd//sys.stdout.write(/}"; _pc="${_pc//sys.stderr.write(/}"
        case "$_pc" in
          *'open('*'"w"'*|*"open("*"'w'"*|*'open('*'"wb"'*|*"open("*"'wb'"*) _wa=1 ;;
          *'open('*'"a"'*|*"open("*"'a'"*|*".write("*|*"write_text("*|*"writelines("*) _wa=1 ;;
          *"os.replace("*|*"shutil.copy"*|*"shutil.move"*|*"Path("*".write"*) _wa=1 ;;
          # 삭제·이동·생성 API — 실발생이 삭제였는데 쓰기 API 만 보고 있었다
          *"os.remove("*|*"os.unlink("*|*"os.removedirs("*|*"shutil.rmtree("*|*".unlink("*|*".rmdir("*) _wa=1 ;;
          *".rename("*|*"os.makedirs("*|*".mkdir("*|*".touch("*) _wa=1 ;;
        esac ;;
    esac
    # ⓑ 셸 판정 후보 — `[[ =~ ]]` 는 builtin(fork 0). 인용·역슬래시를 걷은 사본에서 동사 **단어**를 찾는다
    #   (`r\m`·`"r"m`·`'rm'` — 셸은 그것을 rm 으로 실행한다, 2차 N2)
    _vc="${_cmd//[\\\'\"]/}"
    _vre='(^|[^A-Za-z0-9_.-])(rm|rmdir|mv|cp|mkdir|touch|ln|trash|unlink|find|git|sed|tee|truncate|perl|patch|rsync|install|curl|wget|dd|bash|sh|zsh)([^A-Za-z0-9_.-]|$)'
    if [[ "$_cmd" == *">"* || "$_cmd" == *"issue-tx.py"* || "$_cmd" == *'$('* || "$_cmd" == *'`'* || "$_vc" =~ $_vre ]]; then _wv=1; fi
    # 사람 승인 기록(`fbot-lead.py solo-approve`)은 **사람 전용**이다 — 봇 세션이 부르면 승인이 아니다(prj3#Issue757 C).
    #   여기서는 후보만 표시한다 — 실제 호출인지(grep·로그 언급이 아닌지)는 역할 판정 뒤 shcmd 가 본다(2차 O1)
    case "$_vc" in *"solo-approve"*) _appr=1 ;; esac
    [ "$_wa$_wv$_appr" != "000" ] || exit 0
    _file="(Bash 명령)"
    ;;
  *) exit 0 ;;
esac
[ -n "$_file" ] || exit 0

# ── prj3#Issue859_2 — 조직 선언(중앙 층)의 **권한 모드 완화** 편집은 봇 몸체에 deny ───────────────────────────
#   `data/fbot/org` 는 매니저 관할 예외(_ALLOW_RE)라 아래 판정이 통과시키지만, `permission_mode` 를 bypass 로 풀거나
#   floor 를 지우는 것은 «완화»다 — 점유자가 자기 권한을 스스로 풀면 권한 세탁이다. 완화는 사람 결정이라 역할(매니저·워커)과
#   무관하게 **예외보다 앞에서** 막는다. Edit·MultiEdit·Write 만 본다(Bash 는 이 가드 전체의 명령 문자열 한계를 따른다).
case "$_tool:$_file" in
  Edit:*data/fbot/org/*|MultiEdit:*data/fbot/org/*|Write:*data/fbot/org/*)
    if ! _why="$(printf '%s' "$_input" | python3 "$(dirname "${BASH_SOURCE[0]:-$0}")/lib/perm-relax-guard.py" 2>&1)"; then
      printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[핀봇 가드레일 — 권한 모드] %s. 조직 선언의 permission_mode 를 완화(bypass 지정·floor 소거)하는 편집은 봇 몸체가 할 수 없다 — 사람이 직접 고치거나 mq [컨펌] [H:보안] 으로 올린다."}}\n' "$_why"
      exit 0
    fi ;;
esac

# ── 정체성 해소 (prj3#Issue631) ───────────────────────────────────────────────
# 우선순위: **① 살아 있는 하청 슬롯 → ② $FBOT_ID(세션 불변) → ③ 세션 슬롯**.
#
# 이 가드가 답해야 하는 질문은 *"지금 이 도구를 쓰는 주체가 누구인가"* 다. 하청 슬롯
#   (`sid-<SID>.agent-<bot>.id`)은 **그 질문에만** 답하는 유일한 증거다 — 나머지 둘은 세션 단위라
#   subagent 가 도는 동안에도 **부모**를 가리킨다. 세션 슬롯은 prj3#Issue616 이후 오직 세션 결속의 것이다.
#
# ⚠️ **`$FBOT_ID` 를 무조건 앞에 두면 Issue631 이 그대로 재발한다.** 부모가 `fpm-do` 로 뜬 세션이면
#   그 env 가 **하청 Agent 의 훅에도 상속**되기 때문이다 — 실측 2026-09-18: 하청
#   `fbot-architect-issue631` 의 훅이 부모 `FBOT_ID=fbot-lead-claude` 를 그대로 봤다.
#   `FBOT_ID` 는 "하청이 못 바꾸는 값" 이지 "실행 주체" 가 아니다. 그 둘을 같은 것으로 읽은 것이
#   Issue631 의 원인이다.
#
# ⚠️ **옛 주석(*"FBOT_ID 우선 — 하청이 부모 정체성을 덮어쓰면 안 된다(Issue449)"*)은 축이 다른
#   이야기였다.** Issue449 가 막으려던 것은 heartbeat 의 **lease 갱신 대상** 혼동이다 — *"누구의
#   lease 를 살릴 것인가"* 의 답은 세션 소유자, 즉 **부모**가 맞다. 이 가드가 묻는 것은 **실행
#   주체**다 — *"누가 지금 쓰고 있는가"* 의 답은 **하청**이다. 같은 파일을 보고 답이 갈리는 것이
#   정상이며, 그래서 prj3#Issue616 이 슬롯 자체를 둘로 갈라 놓았다. **되돌리지 말 것** — 되돌리면
#   배분된 팀장핀봇이 부모의 chief 판정을 받아 자기 prj 산출물조차 못 고친다(prj3#Issue631 실발생).
#
# **병렬 하청 규칙 — 살아 있는 하청이 2건 이상이면 판정을 포기하고 통과시킨다(fail-open).**
#   누가 지금 쓰는지 알 수 없는데 하나를 고르면 그 자체가 **오귀속**이다: lead-B 가 쓰는 것을
#   lead-C 의 prj 조직 선언으로 판정해 엉뚱한 deny 를 낸다. `mtime 최신` 은 그 오귀속을 확률로
#   바꿀 뿐 없애지 못하고(배분 순서 ≠ 실행 순서), `전부 거부` 는 이 가드의 명시 원칙(26~27행
#   fail-open · **오탐이 미탐보다 비싸다**)과 정면으로 어긋난다. `가장 관대한 role` 과는 실무
#   조합 대부분에서 결과가 같다 — 후보 중 하나라도 워커면 어차피 통과이기 때문이다.
#
# **신선도 — 파일 존재를 믿지 않는다.** 하청 슬롯은 누수한다: `drop_sid_marker()` 의 `agent-*`
#   수거는 evict/reap 경로에만 있다. Issue631 과 함께 fbot-agent-done.sh 가 자기 슬롯을 거두게
#   고쳤으나 비정상 종료분은 남는다. 남은 슬롯이 **부모의 판정을 완화**하면 가드가 무력해지므로
#   원장의 `state <> 'checkout'` 으로 살아 있는지를 묻는다. 질의는 부모 후보까지 한 `IN` 에 묶어
#   **sqlite3 1회**로 끝낸다(규칙3).
#
# 🚧 **남는 한계**: 하청을 background 로 띄우면 부모도 같은 시각에 도구를 쓸 수 있다. 그때 부모의
#   쓰기가 하청 role 로 판정된다(미탐). PreToolUse 페이로드에 실행 주체를 가리키는 필드가 없어
#   훅 층에서는 원리적으로 구분 불가다 — 위 원칙에 맞춰 통과 쪽으로 둔다.
_AGENTS=$'\n'
for _f in "$_APAT"*.id; do
  [ -f "$_f" ] || continue
  _c=""; IFS= read -r _c < "$_f" 2>/dev/null
  [ -n "$_c" ] || continue
  _AGENTS="$_AGENTS$_c"$'\n'
done
_PARENT="${FBOT_ID:-}"
if [ -z "$_PARENT" ] && [ -f "$_MARK" ]; then IFS= read -r _PARENT < "$_MARK" 2>/dev/null; fi
_PARENT="${_PARENT:-}"
# SQL 문자열 삽입 전 홑따옴표 이스케이프 — bot_id 는 채용 경로가 늘수록 통제가 약해지는 값이다
_IN=""
_sqladd() { local _v="${1//\'/\'\'}"; _IN="$_IN${_IN:+,}'$_v'"; }
while IFS= read -r _c; do [ -n "$_c" ] && _sqladd "$_c"; done <<< "$_AGENTS"
[ -n "$_PARENT" ] && _sqladd "$_PARENT"
[ -n "$_IN" ] || exit 0
_DB="${AOA_MEMORY_DIR:-$HOME/_git/___common/data/aoa}/registry.db"
[ -f "$_DB" ] || exit 0
command -v sqlite3 >/dev/null 2>&1 || exit 0
# 질의가 실패하면(스키마 낡음·잠김) `_rows` 가 비고 아래에서 통째로 exit 0 한다 — 26~27행 fail-open.
_rows="$(sqlite3 "$_DB" "SELECT bot_id || '|' || role || '|' || COALESCE(prj,'') || '|' || COALESCE(state,'') FROM bot WHERE bot_id IN ($_IN)" 2>/dev/null)"
_live=0; _BOT=""; _role=""; _prj=""; _prow=""
while IFS= read -r _r; do
  [ -n "$_r" ] || continue
  _rb="${_r%%|*}"; _t="${_r#*|}"
  _rrole="${_t%%|*}"; _t="${_t#*|}"
  _rprj="${_t%%|*}"; _rstate="${_t#*|}"
  case "$_AGENTS" in
    *$'\n'"$_rb"$'\n'*)                       # 하청 후보 — 살아 있을 때만 센다
      [ "$_rstate" = "checkout" ] && continue
      _live=$((_live+1)); _BOT="$_rb"; _role="$_rrole"; _prj="$_rprj" ;;
    *) [ "$_rb" = "$_PARENT" ] && _prow="$_rb|$_rrole|$_rprj" ;;
  esac
done <<< "$_rows"
[ "$_live" -lt 2 ] || exit 0                  # 병렬 하청 → 실행 주체 불명 → fail-open
if [ "$_live" -eq 0 ]; then                   # 하청 없음(또는 전부 누수) → 부모 판정
  [ -n "$_prow" ] || exit 0
  _BOT="${_prow%%|*}"; _t="${_prow#*|}"; _role="${_t%%|*}"; _prj="${_t#*|}"
fi
_BOTQ="${_BOT//\'/\'\'}"
# ── 사람 승인 기록은 사람 전용 (prj3#Issue757 C) ─────────────────────────────
#   `fbot-lead.py solo-approve` 는 팀장 직접 수행의 **유일한 예외**를 여는 기록이다. 봇 세션이 부르면
#   자기 예외를 자기가 여는 꼴이다 — 워커 포함 **모든 결속 세션**에서 막는다(도구 쪽 검사와 이중).
if [ "$_appr" = "1" ] && [ -n "$_role" ] && command -v python3 >/dev/null 2>&1 \
   && printf '%s' "$_cmd" | python3 "$(dirname "$0")/lib/shcmd.py" approves; then
  _who="핀봇 세션"; [ "$_live" -ge 1 ] && _who="살아 있는 하청 봇이 있는 세션"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[핀봇 비실행 원칙 — %s(%s)] solo-approve 는 사람 세션 전용이다 — 이 명령은 %s 에서 실행돼 실행 주체가 봇으로 판정된다(prj3#Issue757). 봇이면: 평문으로 묻고 턴을 끝낸다 — 질문이 팀장·의뢰 세션(사람)으로 올라가고, 승인되면 id 가 답으로 온다. 사람 세션이면: 하청이 끝난 뒤 다시 실행한다."}}\n' "$_BOT" "$_role" "$_who"
  exit 0
fi
# 축이 둘이다 (prj3#Issue612 → prj3#Issue757 C):
#   ① 권한 축 — 매니저(chief·hr·scout)는 **남의 prj** 산출물을 못 고친다. 무조건 deny.
#   ② 분업 축 — 팀장(lead)은 일을 하지 않는다. 무조건 deny(예외: 사람 승인 solo) — 아래 절.
# 워커는 어느 축의 대상도 아니다 — 실작업이 임무다.
case "$_role" in chief|hr|scout) _axis=권한 ;; lead) _axis=분업 ;; *) exit 0 ;; esac

# ── 관할 예외 ────────────────────────────────────────────────────────────────
#   발굴핀봇의 매뉴얼 초안(`data/fbot/manuals/{role}.md.draft`)은 발굴 ② 단계의 **자기 산출물**이다(prj3#Issue757).
#   정본(`*.md`)은 열지 않는다 — 등재(register)·개정(apply) 경유다. 총괄·인사는 대상이 아니다.
_allow="$_ALLOW_RE"
[ "$_role" = "scout" ] && _allow="$_allow|/\.claude/data/fbot/manuals/[^/]+\.md\.draft$"
if [ "$_file" = "(Bash 명령)" ]; then
  command -v python3 >/dev/null 2>&1 || exit 0
  # ⓐ 파이썬 쓰기 API — 경로 리터럴이 전부 임시·관할 예외면 통과
  if [ "$_wa" = "1" ]; then
    printf '%s' "$_cmd" | python3 "$(dirname "$0")/lib/shcmd.py" apiwrites --allow "$_allow" || _wa=0
  fi
  # ⓑ 셸 판정 — 대상마다 임시 경로·관할 예외를 본다. 산출물에 닿지 않거나 판정 불가면 통과(fail-open)
  if [ "$_wa" = "0" ]; then
    [ "$_wv" = "1" ] || exit 0
    printf '%s' "$_cmd" | python3 "$(dirname "$0")/lib/shcmd.py" mutates --allow "$_allow" || exit 0
  fi
else
  # 파일 도구 — `..` 가 든 경로는 접두 비교로 예외를 줄 수 없다(`/tmp/../Users/x` — codex 리뷰 1차). 예외 판정 없이 아래로
  case "$_file" in
    */../*|*/..) ;;
    *)
      [[ "$_file" =~ $_allow ]] && exit 0
      #   산출물이 아닌 임시 경로(스크래치패드 포함) — `TMPDIR` 이 비었거나 루트면 쓰지 않는다(`/*` 전면 면제 방지)
      case "$_file" in /tmp/*|/private/tmp/*) exit 0 ;; esac
      _td="${TMPDIR:-}"; _td="${_td%/}"
      [ "${#_td}" -gt 1 ] && case "$_file" in "$_td"/*) exit 0 ;; esac
      ;;
  esac
fi

# ── ② 분업 축 (prj3#Issue612 → prj3#Issue757 C) — 팀장은 일을 하지 않는다 ─────────────
#   종전은 조건부였다: ⓐ 워커 자리 0 ⓑ 6시간 창 안의 배분 ⓒ `solo` 사유 — 하나면 통과. 그 셋이 곧
#   팀장 직접 수행의 통로였다(Issue757 실측 solo 141건 — 자리 없음 56). 구현 자리(`developer`)가 전 prj 에
#   선 뒤(순서 계약 B → A → C) 조건을 걷었다. 자리 밖의 일은 팀장이 하는 것이 아니라 총괄에 인력을
#   요청하는 일이다(인력 확보 사다리).
#   남는 예외는 **사람 승인 `solo`** 하나 — 사람 세션이 `fbot-lead.py solo-approve --bot <팀장>` 으로 원장에
#   승인을 남기고, 팀장이 `solo --approved-by <그 id>` 로 쓴다(그 봇 전용·1회용·24시간). 가드는 payload 의
#   `approved_by` 가 있는 solo 만 창 안 통과로 센다. mq confirmed 는 ACK 주체를 남기지 않아 사람의 승인임을
#   증명하지 못하고 `-p` 몸체는 mq 를 거치지 않으므로(Issue749) 승인 원천이 될 수 없다(codex 리뷰 1차 — 추가 확인분).
if [ "$_axis" = "분업" ]; then
  _win="${FBOT_DISPATCH_WINDOW_SEC:-21600}"     # 승인 solo 의 유효 창 — 기본 6시간(한 작업 세션)
  case "$_win" in ''|*[!0-9]*) _win=21600 ;; esac
  # `CASE json_valid` — 손상 payload 행 하나가 질의 전체를 깨 유효한 승인까지 거부하던 것을 막는다(codex 리뷰 1차).
  #   빈 문자열 id 는 승인이 아니다. 질의 자체가 실패하면(잠김·스키마) 판정 불가 → 통과(fail-open)
  _acts="$(sqlite3 "$_DB" "SELECT COUNT(*) FROM job WHERE owner='$_BOTQ' AND kind='fbot_solo' AND created_at >= strftime('%s','now') - $_win AND COALESCE(CASE WHEN json_valid(payload) THEN json_extract(payload,'\$.approved_by') END,'') <> ''" 2>/dev/null)" || exit 0
  [ "${_acts:-0}" = "0" ] || exit 0             # 사람이 승인한 직접 수행 → 통과
  _where="본사"; [ -n "$_prj" ] && _where="prj$_prj"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[핀봇 비실행 원칙 — %s(팀장·%s)] 팀장은 일을 직접 하지 않는다 — 허용은 회의·모색·지시·수령·전달이다(prj3#Issue757). 대상: %s. ① 자리 안의 일은 배분: python3 ~/.claude/hooks/fbot-lead.py dispatch --by %s --role <developer|qa|architect|planner|release|fileops|…> --cwd <prj 경로> --issue Issue<N> → 응답의 next_step 실행(구현은 developer). ② 자리 밖·카탈로그 밖의 일이면 총괄에게 인력 요청(차용·생성) — 그래도 없으면 발굴. ③ 등록(Issue.md)·보고(_doc_work/{htm,report})·조직 선언·임시 경로·issue-tx 커밋은 자유다."}}\n' \
    "$_BOT" "$_where" "$_file" "$_BOT"
  exit 0
fi

# ── ① 권한 축 ────────────────────────────────────────────────────────────────
_pm_hint="fbot-org.py resolve --prj <N> 로 PM 을 찾아 fbot-lead.py dispatch --by ${_BOT} --role lead --bot-id <PM> --cwd <경로> --topic '<요지>' 로 배분하고, 응답의 next_step 을 실행한다."
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[핀봇 가드레일 — %s(%s)] 매니저는 prj 산출물을 직접 수정하지 않는다. 대상: %s — 읽기·조사는 자유지만 **쓰기는 그 prj 의 팀장핀봇(PM)을 통한다**(직접 고치면 같은 파일을 두 주체가 만져 충돌하고, 배분이 원장에 안 남아 HR·발굴 판정이 어긋난다). %s 매니저가 직접 써도 되는 것은 Issue.md 등록·_doc_work/{htm,report} 보고·data/fbot/org 조직 선언뿐이다."}}\n' \
  "$_BOT" "$_role" "$_file" "$_pm_hint"
exit 0
