#!/usr/bin/env bash
# fbot-agent-done.sh — PostToolUse(`Agent`) 배선, Issue495
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: Agent 도구 호출이 **끝난 직후**, 그 스폰이 핀봇 스폰이었을 때만.
# no-op: 핀봇 스폰이 아니면 jq 를 부르기 전에 bash 문자열 비교로 즉시 exit 0 (규칙3).
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
# 출력 없음 — 컨텍스트 주입 훅이 아니다. 배선은 `async`.

set -uo pipefail

input=$(cat)

# ── ① 무비용 가드: 페이로드에 `fbot-` 이 없으면 핀봇 스폰이 아니다 (fork 0회) ──────
case "$input" in
  *fbot-*) ;;
  *) exit 0 ;;
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
[ -n "$cands" ] || exit 0

LOG="$HOME/.claude/.fbot-handoff/agent-bind.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

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
  break
done <<< "$cands"

exit 0
