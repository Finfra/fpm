#!/usr/bin/env bash
# fbot-checkin.sh — SessionStart hook 모듈 (matcher: 없음 · dispatch-sessionstart.sh 자식), Issue436_3
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: 스폰 시 기동 파라미터로 주입된 env **FBOT_ID 가 있을 때만** (계약 fbot-arch.md §출퇴근 훅 F2).
#       출근 절차 = state:checkin → 종류(role)별 매뉴얼 주입 → kv 복원(ns=fbot:{id}) → state:working.
# no-op: FBOT_ID 부재(= 일반 세션) → 첫 줄에서 즉시 exit 0. 레지스트리 역조회로 봇 여부를
#        추정하지 않는다(오인 판정 방지 — 계약 F2 명문).
#
# fail-soft (규칙4): DB·상태 헬퍼·매뉴얼이 없어도 조용히 건너뛴다. 출근이 안 되는 것보다
#   세션이 안 뜨는 것이 나쁘다. 데이터 유실 위험이 없는 경로라 loud 로 만들지 않는다.
#
# ⚠️ 상태 전이는 hooks/fbot-state.py 단일 지점을 경유한다(규칙5). 여기서 bot.state 를
#   직접 UPDATE 하지 않는다 — 판정이 두 곳으로 갈라지는 순간 상태가 어긋난다.
#   읽기(role·kv)는 sqlite3 직접 조회다. MCP 는 훅에서 호출할 수 없다(서버 왕복 = 예산 초과).

set -uo pipefail

[ -n "${FBOT_ID:-}" ] || exit 0          # ← 규칙3 무비용 가드. 이 앞에 어떤 프로세스도 두지 않는다

CLAUDE_DIR="$HOME/.claude"
# DB 경로 knob 은 fbot-state.py·fbot-tick.sh 와 **같은 env**(AOA_MEMORY_DIR)를 쓴다 —
#   훅과 헬퍼가 서로 다른 DB 를 보면 상태와 kv 가 조용히 갈라진다.
# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
DB="${AOA_MEMORY_DIR:-$HOME/.claude/data/aoa}/registry.db"
# 형제 hook 경로 (Issue460 — Issue451 과 같은 결함이 남아 있던 자리)
#   소비자는 SCAR 를 **플러그인**으로 받으므로 `~/.claude/hooks` 가 존재하지 않는다.
#   훅 자체는 플러그인 경로에서 정상 발화하는데(env·매뉴얼 주입까지 성공) 그 안에서
#   부르는 헬퍼만 `~/.claude/hooks` 를 가리켜 **조용히 실패**했다 — fg1 실측:
#   `SID`·`FBOT_ID` 는 정상 도착하는데 `bind`·`transition` 이 안 먹어 결속·전이가 0.
#   자기 위치가 곧 형제들의 위치다. 개발 머신(prj3)에서도 같은 값이 나온다.
_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
STATE_PY="$_HOOKS_SELF/fbot-state.py"
# 🚧 매뉴얼 경로 규약은 s5 확정 대기(fbot-arch.md 미해결 표). 그때까지 데이터 자산 규약
#    (`~/.claude/data/fbot/`)을 따르고, 파일이 없으면 조용히 건너뛴다.
MANUAL_DIR="${FBOT_MANUAL_DIR:-$CLAUDE_DIR/data/fbot/manuals}"

# 상태 헬퍼는 다른 워커가 소유한다. 부재 시 전이는 건너뛰되 매뉴얼·kv 주입은 계속한다.
fbot_state() { [ -f "$STATE_PY" ] || return 0; python3 "$STATE_PY" "$@" >/dev/null 2>&1 || true; }

# --- 인격 탈취 차단 (prj3#Issue679) ------------------------------------------
# FBOT_ID 는 «스폰 시점 결속 신호» 라는 계약인데 **env 는 상속된다** — 봇 세션의 자식이
#   claude 를 띄우면 주입 지점(~/.bin/fpm-do)을 거치지 않고 같은 신호가 선다. 그 세션이
#   출근하면 **살아 있는 봇의 인격을 빼앗는다**(2026-09-23 실측: homunculus 관측기의 분석
#   세션이 fbot-lead-m2slide 를 결속해 팀장의 배분·기록이 중단).
# spawn 지점마다 env 를 끊는 것(fbot-env-scrub.sh)은 **열거**라 새 지점이 생기면 또 샌다.
#   여기가 마지막 한 칸이다 — 신호를 누가 보냈든 «이 봇은 이미 몸체가 있는가» 를 묻는다.
#
# 거부 조건 5개 동시 성립 (하나라도 아니면 통과 — fail-open):
#   ① 레코드에 세션이 결속돼 있고 ② 그게 지금 세션이 아니며 ③ 상태가 working 이고
#   ④ lease 가 아직 유효하며(= 그 몸체가 살아서 heartbeat 중) ⑤ 지금 pane 이 그 몸체의
#   pane 이 아니다.
# ⑤ 가 **오탐을 막는 자리**다 — 같은 창에서 /clear·resume 로 다시 뜬 정당한 재출근은
#   session_id 가 새로 발급돼 ②를 만족해 버린다. pane 이 같으면 «같은 자리에 다시 앉은
#   것» 이므로 통과시킨다. 반대로 탈취 세션은 pane 을 못 가진다(scrub 이 TMUX_PANE 을
#   끊고, 애초에 tmux 밖에서 뜨는 경우가 많다).
# (Issue959) ⑤ 는 pane 이 같아도 **자식 세션**(조상에 다른 claude)이면 성립 — `_is_child_session`.
# lease TTL 은 policy 의 lease_ttl_secs 가 SSOT — 여기서 시간을 하드코딩하지 않는다.
# prj3#Issue959 — ⑤ 의 구멍: **자식 세션은 부모의 `TMUX_PANE` 을 상속**해 «같은 자리에 다시 앉은 것» 으로 보인다.
#   워커가 실측용으로 `claude -p` 를 Bash 로 띄우면 pane 이 같아 가드를 통과해 봇 session_id 를 덮어썼다(거짓 done).
#   정당한 재출근(/clear·resume)은 **같은 프로세스·새 셸**이라 조상 체인에 claude 가 자기 하나뿐이고, 자식은
#   그 위에 부모 claude 가 하나 더 있다 — 조상 claude 가 둘 이상이면 자식이다. `FBOT_PS_BIN` 은 테스트용 주입점.
_is_child_session() {
  local p=$$ n=0 i pp comm
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
    read -r pp comm < <("${FBOT_PS_BIN:-ps}" -o ppid=,comm= -p "$p" 2>/dev/null) || break
    [ -z "$pp" ] && break
    [ "$(basename "$comm" 2>/dev/null)" = "claude" ] && n=$((n+1))
    p="$pp"; [ "$p" -le 1 ] 2>/dev/null && break
  done
  [ "$n" -ge 2 ]
}
_bind_reject=""
if [ -f "$DB" ]; then
  _esc() { printf '%s' "${1//\'/\'\'}"; }
  _idq="$(_esc "$FBOT_ID")"
  # ⚠️ 값을 한 줄에 **이어 붙이지 않는다** — sqlite3 CLI 는 `char(31)` 같은 제어문자를
  #   리터럴 `^_` 두 글자로 출력하고(2026-09-23 실측 `od -c`), 구분자가 원문에 섞여
  #   분리가 통째로 실패한다. `cat -v` 로 보면 진짜 0x1f 와 구별되지 않아 **오진하기 쉽다**.
  #   기본 구분자 `|` 도 tmux 세션 이름에 들어갈 수 있어 쓰지 않는다. 행 단위가 안전하다.
  _prev_sid=""; _prev_state=""; _prev_lease=0; _prev_pane=""
  {
    IFS= read -r _prev_sid   || true
    IFS= read -r _prev_state || true
    IFS= read -r _prev_lease || true
    IFS= read -r _prev_pane  || true
  } < <(sqlite3 -cmd ".timeout 2000" "$DB" \
          "SELECT COALESCE(session_id,'')  FROM bot WHERE bot_id='$_idq';
           SELECT COALESCE(state,'')       FROM bot WHERE bot_id='$_idq';
           SELECT COALESCE(lease_expires,0)FROM bot WHERE bot_id='$_idq';
           SELECT COALESCE(tmux_target,'') FROM bot WHERE bot_id='$_idq';" 2>/dev/null)

  if [ -n "$_prev_sid" ] || [ -n "$_prev_state" ]; then
    _now=$(date +%s)
    # ⑤ 지금 세션의 pane 을 bind 와 **같은 정규화**로 구한다(표기가 갈리면 비교가 빗나간다).
    _cur_pane=""
    if [ -n "${TMUX_PANE:-}" ] && command -v tmux >/dev/null 2>&1; then
      _cur_pane=$(tmux display-message -p -t "${TMUX_PANE}" '#{session_name}:#{window_name}.#{pane_index}' 2>/dev/null || true)
    fi
    if [ -n "$_prev_sid" ] \
       && [ -n "${CLAUDE_CODE_SESSION_ID:-}" ] \
       && [ "$_prev_sid" != "$CLAUDE_CODE_SESSION_ID" ] \
       && [ "$_prev_state" = "working" ] \
       && [ "${_prev_lease:-0}" -gt "$_now" ] 2>/dev/null \
       && { [ -z "$_cur_pane" ] || [ "$_cur_pane" != "$_prev_pane" ] || _is_child_session; }; then
      _bind_reject="1"
      # prj3#Issue843 — 관리직 다중 몸체: 인박스 기상·dispatch 가 `FBOT_FLOW` 로 띄운 **아직 몸체 없는 흐름**은
      #   탈취가 아니라 몸체 추가다. 판정은 fbot-state `body_join_verdict` 단일 지점(여기는 호출만) —
      #   이미 몸체가 있는 흐름(자식 상속)·스위치 off·헬퍼 실패는 전부 rc≠0 → 거부 유지(fail-closed).
      #   `--session-id` = 판정과 몸체 기록을 한 트랜잭션으로(동시 출근 TOCTOU 차단 — 뒤의 `bind` 는 fail-soft 라
      #   흐름 잠금 거부를 삼킨다). 허용되면 몸체는 이미 서 있고 아래 `bind` 는 reuse 다.
      #   `FBOT_FLOW` 가 없어도 부른다 — 이 sid 가 이미 open 몸체면 재결속(흐름2 결속 뒤 흐름1 몸체의 compact·resume.
      #   `session:` 흐름 몸체는 FBOT_FLOW 없이 섰다). 그 밖의 흐름 없음은 판정이 `no_flow` 로 거부한다.
      if [ -f "$STATE_PY" ] \
         && python3 "$STATE_PY" body-join --bot-id "$FBOT_ID" ${FBOT_FLOW:+--flow "$FBOT_FLOW"} \
              --session-id "$CLAUDE_CODE_SESSION_ID" ${_cur_pane:+--pane "$_cur_pane"} >/dev/null 2>&1; then
        _bind_reject=""
      fi
    fi
  fi
fi

# 거부 출력 — 사전 가드(탈취)와 bind 거부(prj3#Issue876 — 동시 출근 패자) 가 같은 경로를 쓴다.
#   $1 = 거부 사유 한 줄(bind 거부일 때 fbot-state 의 stderr), 비면 종전 탈취 문구
_emit_reject() {
  local why="${1:-}" ctx
  # 재발 추적용 기록 — 조용히 거부하면 «왜 봇이 안 떴나» 를 매번 다시 조사하게 된다.
  _rej_log="${FBOT_BIND_REJECT_LOG:-$CLAUDE_DIR/data/fbot/bind-reject.log}"
  mkdir -p "$(dirname "$_rej_log")" 2>/dev/null
  printf '%s\tbot=%s\tprev_sid=%s\tcur_sid=%s\tprev_pane=%s\tcur_pane=%s\tcwd=%s\treason=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FBOT_ID" "$_prev_sid" "${CLAUDE_CODE_SESSION_ID:-}" \
    "$_prev_pane" "${_cur_pane:-}" "$PWD" "${why//$'\n'/ }" >> "$_rej_log" 2>/dev/null
  ctx="[⚠️ 핀봇 결속 거부 — $FBOT_ID 는 이미 다른 세션이 몸체다 (prj3#Issue679)]

이 세션은 **핀봇이 아니다**. \`FBOT_ID\` 가 부모 프로세스에서 **상속**돼 들어왔을 뿐이거나(또는 같은 흐름에
먼저 출근한 세션이 있어), 그 봇은 지금 다른 세션(\`${_prev_sid:-동시 출근 선착}\`)이 몸체다 — 결속하면 인격을 빼앗는다.
매뉴얼·상태 전이·기록 귀속은 수행하지 않았다. 일반 세션으로 진행하라.
${why:+거부 사유: $why
}
봇으로 일해야 하는 세션이라면 스폰 경로(\`fpm-do\` · \`fbot-lead.py dispatch\`)를 거쳐라.
거부 기록: $_rej_log"
  CTX="$ctx" jq -n --arg ev SessionStart '{hookSpecificOutput:{hookEventName:$ev, additionalContext: env.CTX}}' 2>/dev/null || printf '%s\n' "$ctx"
  exit 0
}

[ -n "$_bind_reject" ] && _emit_reject

# --- 실행 형태 결속 (Issue448 ②) ---------------------------------------------
# tmux pane 과 세션 id 를 봇 레코드에 적어 둔다. "이 pane 의 claude 가 등록된 봇인가" 를
#   물을 수 있게 하는 데이터 원천이며 Issue445 의 3값 판정이 이것을 소비한다.
# ⚠️ 값이 없으면 **기록하지 않는다**(NULL 유지). Agent 서브에이전트는 pane 이 원래 없다 —
#   NULL 은 "미등록" 이 아니라 "pane 기반 판정 불가" 다. 이 구분이 무너지면 소비처가
#   fail-open 에서 fail-wrong 으로 바뀐다.
bind_args=()
if [ -n "${TMUX_PANE:-}" ] && command -v tmux >/dev/null 2>&1; then
  # TMUX_PANE 은 '%12' 형태의 pane id 다. 소비처(fpm-do)가 쓰는 'session:window.pane'
  #   표기로 정규화해 둔다 — 표기가 두 가지면 역조회가 조용히 빗나간다.
  tgt=$(tmux display-message -p -t "${TMUX_PANE}" '#{session_name}:#{window_name}.#{pane_index}' 2>/dev/null || true)
  [ -n "$tgt" ] && bind_args+=(--tmux-target "$tgt")
fi
[ -n "${CLAUDE_CODE_SESSION_ID:-}" ] && bind_args+=(--session-id "$CLAUDE_CODE_SESSION_ID")
# ⚠️ bash 3.2(macOS 기본) + `set -u` 에서 빈 배열 전개는 unbound 오류다 — `+` 확장으로 감싼다
# prj3#Issue876 — bind 의 **거부(rc=1, FbotError: 흐름 잠금·상한·점유)** 는 삼키지 않는다. 사전 가드는 이전 상태가
#   working+lease 유효일 때만 들어 idle·open 몸체 없음에서 같은 FBOT_FLOW 두 세션이 동시에 뜨면 가드를 거치지 않고,
#   진 쪽 body_bind 의 흐름 잠금 거부를 fail-soft 래퍼가 삼켜 **둘 다 출근 컨텍스트를 받았다**(5/5 재현).
#   rc=2(DB 오류)·python 부재는 종전 fail-soft. 미등록 봇(rc=1 이지만 거부가 아님)은 아래 «등록 여부 판정» 이 맡는다.
if [ -n "${bind_args[*]+x}" ] && [ -f "$STATE_PY" ]; then
  _bind_err=$(python3 "$STATE_PY" bind --bot-id "$FBOT_ID" "${bind_args[@]}" 2>&1 >/dev/null); _bind_rc=$?
  if [ "$_bind_rc" = 1 ] && [ -f "$DB" ] \
     && [ -n "$(sqlite3 -cmd ".timeout 2000" "$DB" "SELECT 1 FROM bot WHERE bot_id='$(_esc "$FBOT_ID")' LIMIT 1;" 2>/dev/null)" ]; then
    _emit_reject "${_bind_err:-bind 거부}"
  fi
fi

# ⚠️ Issue441 — 전이가 current_task 를 비운다(fbot-state.py: checkin/checkout 에서
#   last_task 로 옮기고 NULL). 출근 훅이 따로 지우지 않는 이유는 판정 단일 지점 원칙
#   (규칙5) 때문이다 — 상태와 함께 움직이는 필드는 상태 헬퍼가 소유한다.
fbot_state transition --bot-id "$FBOT_ID" --to checkin

# --- role 판정: 스폰 env 우선, 없으면 레지스트리 1회 조회 -------------------
sql_esc() { printf '%s' "${1//\'/\'\'}"; }        # SQL 문자열 리터럴 이스케이프
# ⚠️ `-readonly` 를 쓰지 않는다. registry.db 는 **WAL** 이라, 다른 접속이 없어 `-shm` 이
#   없는 순간에 readonly 로 열면 "unable to open database file (14)" 로 실패한다(실측).
#   그러면 매뉴얼·kv 복원이 조용히 빈 값이 된다 — 침묵 실패가 더 나쁘다. 대신 SELECT 만
#   쓰고 busy_timeout 으로 워커 쓰기와의 경합을 흡수한다.
q() { sqlite3 -cmd ".timeout 2000" "$DB" "$1" 2>/dev/null || true; }
ID_SQL="$(sql_esc "$FBOT_ID")"
role="${FBOT_ROLE:-}"
if [ -z "$role" ] && [ -f "$DB" ]; then
  role=$(q "SELECT role FROM bot WHERE bot_id='$ID_SQL';")
fi

# --- 매뉴얼 (부재 시 skip — 계약: "부재면 skip") ---------------------------
# prj3#Issue767 — 주입본 = 파일 − frontmatter `revisions:`. 이력은 매 출근에 필요 없고, 통째 `cat` 하면
#   apply 마다 ~100자씩 주입·상한을 먹었다. 판정 단일 지점은 fbot-manual-review.py `injected_text`
#   (상한도 같은 값으로 잰다) — 여기서 따로 자르지 않는다. 헬퍼 실패 시 통째 주입(fail-soft: 덜 싣는 것보다 낫다)
manual=""
if [ -n "$role" ] && [ -r "$MANUAL_DIR/$role.md" ]; then
  manual=$(python3 "$_HOOKS_SELF/fbot-manual-review.py" inject --file "$MANUAL_DIR/$role.md" 2>/dev/null) \
    || manual=$(cat "$MANUAL_DIR/$role.md" 2>/dev/null || true)
fi

# --- 봇별 상태 복원 (registry.kv ns=fbot:{id}) ------------------------------
# 만료된 키는 제외한다. -json 으로 뽑아 손실 없이 그대로 넘긴다(값에 개행이 있어도 안전).
kv=""
if [ -f "$DB" ]; then
  kv=$(sqlite3 -cmd ".timeout 2000" -json "$DB" \
    "SELECT key, value FROM kv WHERE ns='fbot:$ID_SQL'
       AND (expires_at IS NULL OR expires_at > strftime('%s','now')) ORDER BY key;" 2>/dev/null || true)
  [ "$kv" = "[]" ] && kv=""
fi

# --- 등록 여부 판정 (QA 발견 C — 유령 봇 위장 출근 차단) -----------------------
# 미등록 bot_id 에 정상 출근 컨텍스트를 주입하면 세션이 허위 상태("작업중")를 믿는다.
# fail-soft 는 유지하되(세션은 안 깨짐) 문구로 명확히 구분한다. 전이도 등록 시에만.
registered=""
[ -f "$DB" ] && registered=$(q "SELECT 1 FROM bot WHERE bot_id='$ID_SQL' LIMIT 1;")

if [ -z "$registered" ]; then
  ctx="[⚠️ 핀봇 출근 실패 — $FBOT_ID 는 레지스트리 **미등록**]

이 세션은 핀봇으로 등록되지 않았다 — 상태 전이·기록 귀속·매뉴얼 주입은 수행되지 않는다.
채용(등록)이 먼저다 — python3 ~/.claude/hooks/fbot-state.py register --bot-id $FBOT_ID --role {role} --title {호칭} (계약: _doc_arch/fbot-arch.md §호출 경계 — 미등록 role 채용 불가)"
  CTX="$ctx" jq -n --arg ev SessionStart '{hookSpecificOutput:{hookEventName:$ev, additionalContext: env.CTX}}' 2>/dev/null || printf '%s\n' "$ctx"
  exit 0
fi

fbot_state transition --bot-id "$FBOT_ID" --to working

# --- 현재 작업 기재 (Issue462) ----------------------------------------------
# 전이가 current_task 를 비운 **직후**에 채운다(순서 뒤집으면 방금 넣은 값이 지워진다).
# Issue441 은 낡은 값을 안 보여주는 데까지 갔으나 **채우는 주체를 만들지 않아** 실측에서
#   항상 NULL 이었다(2026-08-29 미르 실작업 — 일은 끝났는데 원장에 내용이 0).
# ⚠️ SessionStart 시점에는 프롬프트가 아직 훅에 오지 않으므로 "위임문에서 요지 추출"(Issue441 후보ⓑ)은
#   이 자리에서 원리적으로 불가능하다. 근거는 둘뿐이다 — env `FBOT_TASK`(위임자의 요지)와 **배분 원장**.
# prj3#Issue759 — 종전엔 FBOT_TASK 가 없으면 NULL 이었고 봇이 스스로 `set-task` 를 부르기를 기대했다.
#   매뉴얼 개정 루프가 그 공란을 «current_task 공란 100%» 신호로 읽어 role 마다 개정안을 냈다(qa 5/5).
#   «무슨 일로 띄웠나» 는 배분 payload(issue·topic·task_ref)가 이미 안다 → `--from-dispatch` 가 빈 칸만
#   원장 사실로 채운다(고르는 규칙은 fbot-state `worker_dispatch` 단일 지점 — 못 가르면 고르지 않는다).
#   둘 다 없으면 NULL 유지 — 추측으로 채우면 낡은 값보다 나쁜 거짓이 된다.
if [ -n "${FBOT_TASK:-}" ]; then
  fbot_state set-task --bot-id "$FBOT_ID" --task "$FBOT_TASK" --from-dispatch
else
  fbot_state set-task --bot-id "$FBOT_ID" --from-dispatch
fi

# --- 배분 지시 전문 (prj3#Issue931) -------------------------------------------
# 배분 지시(-p)가 기동 줄 바이트 예산(Issue786_1·824)으로 잘리면 몸체는 머리 + 조회 포인터(`fbot-lead.py topic <id>`)만
#   받는다. 포인터를 따르지 않는 몸체는 지시를 못 받는다 — haiku 몸체 «지시 미수신» defer · sonnet 몸체 산출 0 거짓 완료
#   (prj42 scout fbotdisp-1791106489-a06b18f6). 그 몸체 배분의 topic 전문(질문답 재개면 질문·답 원문까지)을 여기서 싣는다.
#   «이 몸체의 배분»·«잘렸나» 판정은 fbot-lead.py `checkin_brief` 단일 지점(worker_dispatch · prompt_cut — 기동과 같은 함수).
# fail-open(규칙4): 실패하면 출력을 통째로 버리고 종전 출근 컨텍스트로 간다 — 반쯤 찍힌 출력을 싣지 않는다.
brief=""
LEAD_PY="$_HOOKS_SELF/fbot-lead.py"
if [ -f "$LEAD_PY" ]; then
  brief="$(python3 "$LEAD_PY" checkin-brief --bot-id "$FBOT_ID" 2>/dev/null)" || brief=""
fi

# --- 컨텍스트 조립 ----------------------------------------------------------
# prj3#Issue931 — 절을 따로 만들어 마지막에 잇는다(순서 = 머리 · 배분 지시 전문 · 매뉴얼 · kv · 인박스). 상한과 부딪치면
#   뒤에서부터 뺀다(아래 «상한»). 전문 절이 없으면 결과는 종전과 같은 글이다.
ctx="[핀봇 출근 — $FBOT_ID${role:+ (role: $role)}]

이 세션은 핀봇 **$FBOT_ID** 의 런타임 몸체다. 상태: 작업중(working).
기록·책임은 세션이 아니라 봇 이름에 귀속된다(계약: _doc_arch/fbot-arch.md)."
[ -n "$brief" ] && ctx="$ctx

$brief"
sec_manual=""
[ -n "$manual" ] && sec_manual="## 작업 매뉴얼 ($role)

$manual"
sec_kv=""
[ -n "$kv" ] && sec_kv="## 복원된 봇별 상태 (registry.kv ns=\`fbot:$FBOT_ID\`)

\`\`\`json
$kv
\`\`\`"

# --- 매니저 인박스 (prj3#Issue552 — 소비 경로 ①출근) --------------------------
# 결속 없이 쌓인 요청(N:1)을 출근 시점에 한 번 보여준다. 매니저가 아니면 pending 이 빈
#   목록을 돌려주므로 role 분기를 여기 복제하지 않는다(판정 단일 지점 = fbot-inbox.py).
# 결속 중 도착분은 fbot-inbox-nudge.sh(UserPromptSubmit) 가, 미출근 방치분은 tick 이 맡는다.
INBOX_PY="$_HOOKS_SELF/fbot-inbox.py"
inbox=""
[ -f "$INBOX_PY" ] && inbox="$(python3 "$INBOX_PY" pending --bot-id "$FBOT_ID" 2>/dev/null \
  | python3 -c '
import json,sys
try: r=json.load(sys.stdin)
except Exception: sys.exit(0)
for it in r.get("items") or []:
    src=it.get("from") or it.get("from_session") or "?"
    prj=f" prj{it[\"prj\"]}" if it.get("prj") else ""
    print(f"- `{it[\"id\"]}` ← {src}{prj} [{it.get(\"kind\") or \"ask\"}]: {(it.get(\"body\") or \"\").strip()[:200]}")
' 2>/dev/null)"
sec_inbox=""
[ -n "$inbox" ] && sec_inbox="## 인박스 — 미처리 요청 (매니저 창구, 결속과 무관)

$inbox

받을지·거절할지·바로 끝낼지를 \`python3 ~/.claude/hooks/fbot-inbox.py reply --id <id> --status accepted|rejected|done --body '<응답>'\` 로 답한다. 부하에게 배분할 일이면 \`fbot-lead.py dispatch --by $FBOT_ID\`.
\`[question]\` 은 **팀원 질문**이다(prj3#Issue757 — 사람이 아니라 팀장이 받는다). L 로 정할 수 있으면 \`reply --id <id> --status done --body '<답>' --by $FBOT_ID\` — 팀원이 답을 들고 재기동된다. 위의 결정이 필요하면 그 질문을 번호 목록 평문으로 정리해 남기고 턴을 끝낸다 — 팀장이면 총괄에게, 총괄이면 의뢰한 사람에게 올라가고(prj3#Issue831) 답이 오면 재기동된다."

ctx_head="$ctx"
for _sec in "$sec_manual" "$sec_kv" "$sec_inbox"; do
  [ -n "$_sec" ] && ctx="$ctx

$_sec"
done

# --- 상한 (prj3#Issue931) ------------------------------------------------------
# Claude Code 는 훅 주입 문자열이 10,000자를 넘으면 파일 + 앞 2,000자 미리보기로 바꾼다 — 실은 전문이 다시 포인터가 된다.
#   출근 몫 상한 FBOT_CHECKIN_CTX_MAX(기본 8,000 — 형제 SessionStart 훅 몫을 남긴다). 전문 절이 있을 때만 잰다(종전 출근은
#   그대로). 넘치면 인박스 → kv → 매뉴얼 순으로 빼고 조회 안내를 남긴다 — topic 우선. 글자 수는 python 으로 잰다(bash
#   `${#var}` 는 로캘이 C 면 바이트를 센다). 실패하면 자르지 않은 글 그대로(fail-open).
if [ -n "$brief" ]; then
  _fit=$(HEAD="$ctx_head" S1="$sec_manual" S2="$sec_kv" S3="$sec_inbox" MAX="${FBOT_CHECKIN_CTX_MAX:-8000}" \
         BOT="$FBOT_ID" ROLE="$role" DBP="$DB" python3 -c '
import os
mx = int(os.environ.get("MAX") or 8000)
head = os.environ.get("HEAD", "")
secs = [os.environ.get(k, "") for k in ("S1", "S2", "S3")]
bot, role, dbp = os.environ.get("BOT", ""), os.environ.get("ROLE", ""), os.environ.get("DBP", "")
hint = ["작업 매뉴얼 — `python3 ~/.claude/hooks/fbot-manual-review.py inject --role %s`" % role,
        "복원된 kv — `sqlite3 %s \"SELECT key, value FROM kv WHERE ns=%s\"`" % (dbp, chr(39) + "fbot:" + bot + chr(39)),
        "인박스 — `python3 ~/.claude/hooks/fbot-inbox.py pending --bot-id %s`" % bot]
drop = []
def render():
    out = "\n\n".join([head] + [s for s in secs if s])
    if drop:
        out += ("\n\n> 출근 컨텍스트 상한 %d자 — 배분 지시 전문이 우선이라 아래 절을 생략했다(prj3#Issue931). 필요하면 조회:\n" % mx
                + "\n".join("> - " + hint[i] for i in drop))
    return out
for i in (2, 1, 0):
    if len(render()) <= mx:
        break
    if secs[i]:
        secs[i] = ""
        drop.append(i)
print(render()[:mx])
' 2>/dev/null) && [ -n "$_fit" ] && ctx="$_fit"
fi

out=$(CTX="$ctx" jq -n --arg ev SessionStart \
  '{hookSpecificOutput:{hookEventName:$ev, additionalContext:env.CTX}}' 2>/dev/null)
# jq 부재·인코딩 실패 시에도 출근 사실을 잃지 않는다(fail-soft — 평문도 컨텍스트로 읽힌다)
printf '%s\n' "${out:-$ctx}"
exit 0
