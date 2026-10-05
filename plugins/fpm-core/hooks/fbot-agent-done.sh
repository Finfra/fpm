#!/usr/bin/env bash
# fbot-agent-done.sh — PostToolUse(`Agent`) + SubagentStop 배선, Issue495 · Issue693_1
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: ① PostToolUse(`Agent`) — 핀봇 스폰이 **포그라운드로 끝났을 때** 퇴근.
#         백그라운드 스폰(`async_launched`)이면 퇴근하지 않고 agentId→봇 마커만 남긴다.
#       ② SubagentStop — 그 마커가 있는 서브에이전트가 **실제로 끝났을 때** 퇴근.
# no-op: ① 핀봇 스폰이 아니면 jq 전에 bash 문자열 비교로 exit 0 · ② 마커가 없으면
#        bash 정규식 + `[ -f ]` 로 exit 0 — 둘 다 fork 0회 (규칙3).
#
# ── 🔧 Issue693_1 — PostToolUse 는 «일이 끝났다» 가 아니었다 (2026-09-26 실측) ─────
#   Agent 는 기본이 **백그라운드**다. 그때 PostToolUse 는 스폰 **직후** 발화하고
#   `tool_response` 는 `{"isAsync":true,"status":"async_launched","agentId":…}` 이다.
#   이 훅은 그 순간을 퇴근으로 읽어 **방금 출근한 봇을 같은 초에 퇴근**시켰다 —
#   agent-bind.log 실측: `bind ok` · `checkin` · `agent-done ok` 가 전부 같은 초
#   (prj42#Issue415 의 planner·advisor·qa, prj7 advisor-2 전건). 그 뒤 워커가 한참 일하는데
#   원장은 checkout 이라 ① sweep 이 퇴근 기록을 완료로 읽어 **거짓 완료 통지** ② hub 활성
#   명단 누락 ③ heartbeat 는 `state != checkout` 만 갱신하므로 **lease 도 안 올라갔다**.
#   증상이 «heartbeat 미갱신» 으로 보였지만 heartbeat 는 무죄였다 — 퇴근이 너무 일렀다.
#   끝나는 순간은 SubagentStop 이 안다(`agent_id` 제공). PostToolUse 의 `agentId` 와 이어
#   붙이는 마커가 `agent-<agentId>.bot` 이다.
#
# ── 왜 필요한가 (Issue495 실측 2026-08-31) ────────────────────────────────────
#   Agent 형태 봇의 **수명주기가 반쪽이었다.**
#
#     세션 형태 : SessionStart(출근) → heartbeat(유지) → Stop/SessionEnd(퇴근+작업기록)
#     Agent 형태: PreToolUse(출근·결속) → PostToolUse `*`(유지) → ✗ **없음**
#
#   퇴근 기록을 남기는 [`fbot-checkout.sh`](fbot-checkout.sh) 는 `FBOT_ID` env 가 있을
#   때만 발화하는데, Agent 는 env 가 부모 프로세스 것이라 FBOT_ID 가 **구조적으로 없다**
#   (같은 사실이 fbot-heartbeat.sh Issue442/448 주석에 이미 적혀 있다). 그래서 Agent
#   형태 봇은 `fbot_session` 작업 기록을 **영원히 남기지 못했다.**
#
#   그 결과가 조직 정지였다. 완료 판정(`fbot-lead.py detect_completions`)이 바로 그
#   작업 기록을 요구하므로 배분이 `open` 으로 영구 잔류하고 → 조직도에 "유실 배분"
#   경보가 영구 노출되고 → 팀장핀봇의 WIP 슬롯(상한 3)이 영구 점유돼 **새 배분이 전부
#   거절**됐다. 2026-08-31 실측: ig-maker 3건이 슬롯 3칸을 다 먹어 concurrent 3/3.
#
#   이 훅은 그 빠진 한 칸을 메운다. Agent 가 끝나는 순간이 곧 그 봇의 퇴근이다.
#
# ⚠️ **판정을 분기시키지 않는 것이 요점이다.** "Agent 형태면 퇴근만으로 완료로 친다" 는
#   우회도 가능했지만, 그러면 완료 판정이 형태별로 둘이 되고 한쪽이 반드시 낡는다.
#   대신 Agent 형태에도 **같은 증거**(`fbot_session` job)를 남기게 해서 판정은 하나로 둔다.
#
# ⚠️ 실패해도 아무것도 막지 않는다 — PostToolUse 라 이미 도구는 끝났고, 모든 단계가
#   fail-soft 다. 흔적은 bind 훅과 같은 로그 파일에 남긴다.
#
# 출력 없음 — 컨텍스트 주입 훅이 아니다. 배선: PostToolUse(`Agent`) **동기**(Issue693_1 — 마커가
#   SubagentStop 보다 먼저 서야 한다) · SubagentStop `async`.

set -uo pipefail

# ── GC 모드 (Issue751_5) — tick 이 `fbot-agent-done.sh --gc` 로 부른다 ─────────────────
#   SubagentStop 이 끝내 안 온 백그라운드 스폰의 `agent-<id>.bot` 마커를 치우는 경로가 없었다
#   (실측: fbot-qa-issue99 마커가 하루 넘게 잔존). ⓪-b 보류가 생기면서 «재개 없이 끝난 보류»
#   도 여기로 온다. 마커를 쓰고 지우는 곳이 이 파일이라 GC 도 여기 둔다(소유 단일 지점).
#   1시간 안 된 마커는 보지 않는다(스폰·보류 진행 중일 수 있다). 제거 조건:
#     빈 마커 · 24시간 초과(상태 무관) · 봇이 이미 `checkout`(SubagentStop 이 와도 할 일 없음) · 미등록 봇
#   ⚠️ 원장은 건드리지 않는다 — 봇 강제 퇴근은 reap(lease)의 몫이다. 조회가 **실패**(DB 잠금 등)하면
#      상태를 모르는 것이지 미등록이 아니다 → 유지한다.
if [ "${1:-}" = "--gc" ]; then
  _HDIR="${FBOT_HANDOFF_DIR:-$HOME/.claude/.fbot-handoff}"
  [ -d "$_HDIR" ] || exit 0
  _SP="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/fbot-state.py"
  _LOG="$HOME/.claude/.fbot-handoff/agent-bind.log"
  _rm=0; _kept=0
  while IFS= read -r _m; do
    [ -n "$_m" ] || continue
    _b=""; IFS= read -r _b < "$_m" || true
    _why=""
    if [ -z "$_b" ]; then
      _why="빈 마커"
    elif [ -n "$(find "$_m" -mmin +1440 2>/dev/null)" ]; then
      _why="24시간 초과"
    elif [ -f "$_SP" ]; then
      _out=$(python3 "$_SP" get --bot-id "$_b" 2>&1)
      case "$_out" in
        *'미등록 봇'*) _why="미등록 봇" ;;
        *'"state": "checkout"'*) _why="이미 퇴근" ;;
      esac
    fi
    if [ -n "$_why" ]; then
      rm -f "$_m" && _rm=$((_rm + 1))
      printf '%s agent-done gc marker=%s bot=%s (%s)\n' "$(date +%Y-%m-%dT%H:%M:%S)" \
        "${_m##*/}" "${_b:-?}" "$_why" >> "$_LOG" 2>/dev/null
    else
      _kept=$((_kept + 1))
    fi
  done < <(find "$_HDIR" -maxdepth 1 -name 'agent-*.bot' -mmin +60 2>/dev/null)
  echo "agent 마커 GC — 제거 ${_rm} · 유지 ${_kept} (1시간 미만은 제외)"
  exit 0
fi

input=$(cat)

_HDIR="${FBOT_HANDOFF_DIR:-$HOME/.claude/.fbot-handoff}"
_DEFERRED_BOT=""

# ── ⓪ SubagentStop — 백그라운드로 미뤄 둔 퇴근을 여기서 집행한다 (Issue693_1) ──────
#   모든 서브에이전트 종료에 발화하므로 가드가 싸야 한다: 정규식 1회 + `[ -f ]` (fork 0회).
case "$input" in
  *'"hook_event_name":"SubagentStop"'*|*'"hook_event_name": "SubagentStop"'*)
    [[ "$input" =~ \"agent_id\"[[:space:]]*:[[:space:]]*\"([A-Za-z0-9_-]+)\" ]] || exit 0
    _AID="${BASH_REMATCH[1]}"; _AMARK="$_HDIR/agent-$_AID.bot"
    [ -f "$_AMARK" ] || exit 0          # 핀봇이 아니거나 포그라운드로 이미 퇴근한 스폰
    IFS= read -r _DEFERRED_BOT < "$_AMARK" || true
    [ -n "$_DEFERRED_BOT" ] || { rm -f "$_AMARK" 2>/dev/null; exit 0; }
    # ── ⓪-b 자식 백그라운드 작업이 남았으면 아직 끝이 아니다 (Issue751_6) ─────────
    #   SubagentStop 은 «턴이 끝났다» 다. 봇이 Bash `run_in_background`·Monitor 를 걸고
    #   알림을 기다리며 턴을 닫아도 발화한다 — 그때 퇴근시키면 **작업 중 퇴근**이고,
    #   알림으로 재개해 진짜 끝날 땐 마커가 이미 없어 퇴근 기록이 안 남는다(Issue753 X3 실측).
    #   subagent 기록에서 «시작 결과는 있는데 종결 알림(<task-notification> completed·failed·
    #   killed·stopped)·TaskStop 이 없는» 작업을 센다. 있으면 마커를 두고 나간다 — 재개 뒤의
    #   SubagentStop 이 다시 판정한다. 기록을 못 찾거나 파싱이 깨지면 종전대로 퇴근한다
    #   (판정 불능을 보류로 읽으면 영구 보류가 된다). 끝내 재개가 없으면 reap 이 회수한다.
    #   ⚠️ 시작 판정은 **해당 도구의 tool_result 첫머리**만 본다 — 포그라운드 grep 출력·본문 인용이
    #      같은 문구를 담아도 대기 작업으로 세지 않는다(오탐 = 영구 보류).
    #   판정은 lib/session-end.py `pending_background` 단일 지점이다(prj3#Issue951 — `-p` 몸체 Stop 가드·퇴근 분류와
    #   같은 함수). 하청 기록은 전체를 읽는다(tail_bytes=0 — 종전과 같다). lib 를 못 읽으면 빈 값 → 종전대로 퇴근.
    _PENDING=$(printf '%s' "$input" | FBOT_SESSION_END_LIB="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/lib/session-end.py" python3 -c '
import importlib.util, json, os, sys
d = json.load(sys.stdin)
aid = d.get("agent_id") or ""
tp = d.get("transcript_path") or ""
cands = [d.get("agent_transcript_path") or ""]
if tp:
    if os.path.basename(tp) == "agent-%s.jsonl" % aid:
        cands.append(tp)
    cands.append(os.path.join(tp[:-6] if tp.endswith(".jsonl") else tp, "subagents", "agent-%s.jsonl" % aid))
p = next((c for c in cands if c and os.path.isfile(c)), None)
if not p:
    sys.exit(0)
spec = importlib.util.spec_from_file_location("session_end", os.environ["FBOT_SESSION_END_LIB"])
se = importlib.util.module_from_spec(spec)
spec.loader.exec_module(se)
print(" ".join(t["id"] for t in se.pending_background(p, tail_bytes=0)))
' 2>/dev/null) || _PENDING=""
    if [ -n "$_PENDING" ]; then
      mkdir -p "$HOME/.claude/.fbot-handoff" 2>/dev/null
      printf '%s agent-done hold bot=%s agent=%s (백그라운드 작업 대기: %s — 재개 뒤 SubagentStop 에서 퇴근)\n' \
        "$(date +%Y-%m-%dT%H:%M:%S)" "$_DEFERRED_BOT" "$_AID" "$_PENDING" \
        >> "$HOME/.claude/.fbot-handoff/agent-bind.log"
      exit 0
    fi
    rm -f "$_AMARK" 2>/dev/null
    ;;
  *)
    # ── ① 무비용 가드: 페이로드에 `fbot-` 이 없으면 핀봇 스폰이 아니다 (fork 0회) ──
    case "$input" in
      *fbot-*) ;;
      *) exit 0 ;;
    esac
    ;;
esac

# 형제 hook 경로 (Issue460) — 소비자는 SCAR 를 **플러그인**으로 받으므로 `~/.claude/hooks`
#   가 존재하지 않는다. 자기 위치가 곧 형제들의 위치다.
_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
STATE_PY="$_HOOKS_SELF/fbot-state.py"
[ -f "$STATE_PY" ] || exit 0             # 상태 헬퍼 부재 = 배관 미완 → 조용히 no-op

command -v jq >/dev/null 2>&1 || exit 0  # jq 부재는 fail-soft

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
#   ⚠️ fbot-state.py 와 **같은 env** 여야 한다. 갈라지면 상태와 기록이 조용히 어긋난다.
DB="${AOA_MEMORY_DIR:-$HOME/.claude/data/aoa}/registry.db"

sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)

# ── ② bot_id 후보 추출 — bind 훅과 **같은 규칙**이어야 한다 ────────────────────
#   출근시킨 자리와 퇴근시키는 자리가 다른 봇을 고르면 그 자체가 오귀속이다.
#   1순위: tool_input.name · 2순위: 프롬프트 본문의 첫 `fbot-…` 토큰.
#
# 🔴 프롬프트 scan 폐기 (Issue589, 2026-09-09) — 근거 전문은 fbot-agent-bind.sh ② 주석.
#   ⚠️ **두 훅을 반드시 함께 고친다.** 한쪽만 고치면 출근은 막히고 퇴근은 발화하는
#   최악 상태가 된다 — 결속된 적 없는 봇에 허위 done 기록이 쌓이고 checkout 된다.
#   추출식은 두 파일이 **바이트 단위로 같아야 한다**(md5 대조로 검증).
cands=$(printf '%s' "$input" | jq -r '
    [ (.tool_input.name // "") ]
    | map(select(type == "string" and startswith("fbot-"))) | unique | .[]
  ' 2>/dev/null)
# Issue693_1 — SubagentStop 경로는 tool_input 이 없다. 봇은 ⓪ 의 마커가 이미 알려 줬다.
[ -n "$_DEFERRED_BOT" ] && cands="$_DEFERRED_BOT"
[ -n "$cands" ] || exit 0

LOG="$HOME/.claude/.fbot-handoff/agent-bind.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

# ── ②-b 백그라운드 스폰이면 퇴근을 미룬다 (Issue693_1) ─────────────────────────
#   `async_launched` = 방금 **떠났다**는 뜻이지 끝났다는 뜻이 아니다. agentId→봇 마커만
#   남기고 나간다 — 퇴근은 ⓪ SubagentStop 이 집행한다.
#   agentId 가 없으면 이어 붙일 수 없다. 그래도 지금 퇴근시키지 않는다 — 거짓 퇴근보다
#   reap(lease 만료, 마지막 방벽)이 늦게라도 정직하다. 로그에 `defer-untracked` 로 남긴다.
if [ -z "$_DEFERRED_BOT" ]; then
  _resp=$(printf '%s' "$input" | jq -r '
      (.tool_response | objects | "\(.status // "")\t\(.agentId // "")") // empty
    ' 2>/dev/null)
  _rstatus="${_resp%%$'\t'*}"; _aid=""
  [ "$_resp" != "$_rstatus" ] && _aid="${_resp#*$'\t'}"
  if [ "$_rstatus" = "async_launched" ]; then
    # ⚠️ 경합 (codex 2차 리뷰 medium) — SubagentStop 이 마커보다 먼저 오면 퇴근이 유실된다.
    #   그래서 ① 이 배선은 **동기**다(settings.json — 도구 결과가 돌아가기 전에 마커가 선다)
    #   ② 마커를 python 조회 **앞**에서 쓴다(첫 후보 = bind 와 같은 «첫 1건»). 미등록 봇이면
    #   SubagentStop 쪽 ③ 루프의 `get` 이 걸러 내므로 마커가 잘못돼도 원장은 안 건드린다.
    #   남는 창은 bash·jq 기동 수십 ms 뿐이고, 에이전트는 첫 모델 호출에만 초 단위가 든다.
    while IFS= read -r cand; do
      [ -n "$cand" ] || continue
      if [[ "$_aid" =~ ^[A-Za-z0-9_-]+$ ]]; then
        mkdir -p "$_HDIR" 2>/dev/null
        printf '%s\n' "$cand" > "$_HDIR/agent-$_aid.bot"
        printf '%s agent-done defer bot=%s agent=%s (백그라운드 — SubagentStop 에서 퇴근)\n' \
          "$(date +%Y-%m-%dT%H:%M:%S)" "$cand" "$_aid" >> "$LOG"
      else
        printf '%s agent-done defer-untracked bot=%s (agentId 없음 — reap 이 회수)\n' \
          "$(date +%Y-%m-%dT%H:%M:%S)" "$cand" >> "$LOG"
      fi
      break
    done <<< "$cands"
    exit 0
  fi
fi

# ── ③ 실재하는 첫 1건만 퇴근 처리 ──────────────────────────────────────────────
#   한 스폰은 한 봇이다 — bind 와 같은 "첫 1건" 규칙.
while IFS= read -r cand; do
  [ -n "$cand" ] || continue
  python3 "$STATE_PY" get --bot-id "$cand" >/dev/null 2>&1 || continue

  # ── 작업 기록 append (F4) — checkout.sh 와 **동일한 형태**여야 한다.
  #   완료 판정이 이 레코드를 읽으므로 모양이 다르면 판정이 못 알아본다.
  if [ -f "$DB" ]; then
    FBOT_DB="$DB" FBOT_BOT="$cand" FBOT_SID="$sid" FBOT_CWD="$cwd" python3 - <<'PY' || true
import json, os, sqlite3, time, uuid

db, bot = os.environ["FBOT_DB"], os.environ["FBOT_BOT"]
sid, cwd = os.environ.get("FBOT_SID") or None, os.environ.get("FBOT_CWD") or None
now = int(time.time())
try:
    cx = sqlite3.connect(db, timeout=3)
    cx.execute("PRAGMA busy_timeout=3000")
    with cx:
        # 중복 방지 — 한 봇이 Agent 로 여러 번 불릴 수 있고, 그때마다 기록이 쌓이면
        #   "작업 N건" 이 부풀어 승격 판정(fbot_promote_job_min)이 오염된다.
        #   같은 봇의 마지막 퇴근 기록 이후 상태 변화가 없으면 다시 쓰지 않는다.
        row = cx.execute(
            "SELECT state FROM bot WHERE bot_id=?", (bot,)).fetchone()
        if row is not None and row[0] != "checkout":
            cur = cx.execute(
                "SELECT current_task FROM bot WHERE bot_id=?", (bot,)).fetchone()
            cx.execute(
                "INSERT INTO job(id,store,kind,status,payload,result,attempts,owner,"
                "lease_until,blocked_since,created_at) VALUES(?,NULL,?,?,?,NULL,0,?,NULL,NULL,?)",
                ("fbotjob-%d-%s" % (now, uuid.uuid4().hex[:8]), "fbot_session", "done",
                 json.dumps({"bot_id": bot, "cwd": cwd, "session_id": sid,
                             "current_task": cur[0] if cur else None,
                             "checkout_at": now,
                             # 어느 경로로 남은 기록인지 — 진단이 형태를 되묻지 않게.
                             "source": "agent-done"}, ensure_ascii=False), bot, now))
    cx.close()
except Exception:
    pass   # fail-soft — 기록 실패가 후속 전이를 막지 않는다
PY
  fi

  # ── 상태 전이는 단일 지점 경유(규칙5).
  #   ⚠️ 이미 `checkout` 이면 전이가 **정상 거부**된다(lease 만료 reap 이 먼저 찍은 경우).
  #      오류가 아니라 예상된 경로다 — 로그만 남긴다.
  if python3 "$STATE_PY" transition --bot-id "$cand" --to checkout >/dev/null 2>&1; then
    printf '%s agent-done ok bot=%s sid=%s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$cand" "$sid" >> "$LOG"
  else
    printf '%s agent-done skip bot=%s (이미 퇴근했거나 전이 불가)\n' \
      "$(date +%Y-%m-%dT%H:%M:%S)" "$cand" >> "$LOG"
  fi

  # ── ④ 자기 하청 슬롯 수거 (prj3#Issue631) ────────────────────────────────────
  #   prj3#Issue616 이 마커를 둘로 가르면서 하청은 `sid-<SID>.agent-<bot>.id` 를 따로 쓰는데,
  #   **지우는 쪽이 없었다** — `drop_sid_marker()` 의 `agent-*` glob 수거는 evict/reap
  #   경로에서만 돈다. 그래서 정상 종료한 하청의 슬롯이 그대로 남는다(실측 누수).
  #   남은 슬롯은 단순한 쓰레기가 아니다: [`fbot-writeguard.sh`](fbot-writeguard.sh) 가
  #   *"하청 슬롯이 있으면 지금 하청이 돌고 있다"* 로 읽어 **부모의 판정을 하청 role 로
  #   완화**시킨다(가드 무력화). 그쪽은 원장 `state<>'checkout'` 으로 2차 방어하지만,
  #   그 방어가 성립하려면 **정상 종료분은 여기서 거둬야** 한다 — 방어를 하나만 두지 않는다.
  #   ⚠️ 전이 성공 여부와 무관하게 지운다. 이 훅이 발화한 시점에 그 Agent 는 이미 끝났고,
  #      "전이 실패(이미 checkout)" 는 슬롯이 더더욱 쓸모없다는 뜻이다.
  #   ⚠️ 파일명 정규화는 fbot-state.py `sid_marker_path()` 와 **같은 규칙**이어야 한다
  #      (`[^A-Za-z0-9_.-]` → `_`). 갈라지면 지우는 경로와 쓰는 경로가 어긋나 누수가 남는다.
  #   fail-soft — 삭제 실패가 아무것도 막지 않는다(마커는 캐시다).
  if [ -n "$sid" ]; then
    _HDIR="${FBOT_HANDOFF_DIR:-$HOME/.claude/.fbot-handoff}"
    _SAFE="${cand//[^A-Za-z0-9_.-]/_}"
    rm -f "$_HDIR/sid-$sid.agent-$_SAFE.id" 2>/dev/null || true
  fi
  break
done <<< "$cands"

exit 0
