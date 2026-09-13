#!/usr/bin/env bash
# fbot-inbox-nudge.sh — 결속 중인 매니저에게 미처리 요청 환기 (dispatch-userpromptsubmit.sh 의 자식), prj3#Issue552
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj1#Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#   설계 SSOT: ~/.claude/_doc_arch/fbot-manager-design.md "§소비 3경로"
#
# 발동: 이 세션에 결속된 봇 중 **매니저**(exec·taskmgr·hr) 앞으로 `open` 요청이 있을 때,
#   다음 턴 경계에 1블록 주입. 매니저가 `reply --status accepted|rejected|done` 하면 그친다.
# no-op: 결속 마커(`.fbot-handoff/sid-<sid>.id`) 부재(= 일반 세션) → 첫 블록 exit 0, fork 0회.
#   마커가 있어도 헬퍼 부재·매니저 아님·요청 0건이면 무출력 exit 0.
#
# 왜 (Issue552 원 문제):
#   결속된 총괄핀봇이 **다른 프로젝트의 요청을 무시**했다 — 요청이 오려면 결속해야 했고
#   결속은 배타라 두 번째가 거부됐다. fbot-inbox.py 가 적재 쪽을 풀었지만, 결속돼 작업 중인
#   매니저는 스스로 인박스를 열 계기가 없다. 세션은 자기 프롬프트만 본다. 그래서
#   **다음 턴 경계**에 실어 보낸다 — 비-Claude 프로세스의 통지를 세션에 넣는 유일한 합법 경로다
#   (session-delegation-design "완료 통지 → UserPromptSubmit 주입" 선례, prj5#Issue64).
#
# 무비용 원칙 (hook-rules 규칙3):
#   ① 게이트는 fbot-heartbeat.sh 와 같은 마커 파일 `[ -f ]` — 파일 존재만 본다. 내용(bot_id)은
#      권위가 아니라 읽지 않는다(Issue449: 마지막 1건만 담김). "누가 이 세션에 있나" 는 DB 가 답한다.
#   ② 마커가 있는 세션(= 봇 세션)만 python3 1회. 병렬 자식이라 heartbeat 와 같은 예산 안에 든다.
#   ③ 주입은 `open` 요청만 — 받음(accepted)이 곧 ACK 라 별도 읽음 표시·스로틀이 필요 없다.
#
# 규칙8 (독립성): 다른 자식의 산출물을 읽지 않는다. DB 와 마커 파일만 본다.

_SID="${CLAUDE_CODE_SESSION_ID:-}"
[ -n "$_SID" ] || exit 0
[ -f "$HOME/.claude/.fbot-handoff/sid-$_SID.id" ] || exit 0     # ← 무비용 게이트. 이 앞에 프로세스 0

_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
INBOX_PY="$_HOOKS_SELF/fbot-inbox.py"
[ -f "$INBOX_PY" ] || exit 0              # 헬퍼 부재 = 배관 미완 → 조용히 no-op

# 한 번의 python3 로 조회+조립까지 끝낸다 — jq 로 다시 풀면 프로세스가 하나 더 든다
MSG="$(python3 - "$INBOX_PY" "$_SID" <<'PY' 2>/dev/null
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fbot_inbox", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.pending(session_id=sys.argv[2])
items = r.get("items") or []
if not items:
    sys.exit(0)
who = ",".join(r.get("managers") or [])
lines = [f"[핀봇 인박스 — {who}] 미처리 요청 {len(items)}건. 결속·현재 작업과 무관하게 **매니저로서 판단**한다 — 받을지(accepted)·거절할지(rejected)·바로 끝낼지(done)를 `python3 ~/.claude/hooks/fbot-inbox.py reply --id <id> --status <s> --body '<응답>'` 로 답한다. 직접 하지 말고 부하에게 배분할 일이면 `fbot-lead.py dispatch --by {who}` 로 넘긴다. 답하기 전까지 매 턴 다시 뜬다."]
for it in items:
    src = it.get("from") or it.get("from_session") or "?"
    prj = f" prj{it['prj']}" if it.get("prj") else ""
    lines.append(f"- `{it['id']}` ← {src}{prj} [{it.get('kind') or 'ask'}]: {(it.get('body') or '').strip()[:200]}")
print("\n".join(lines))
PY
)"
[ -n "$MSG" ] || exit 0
MSG="$MSG" jq -n --arg ev UserPromptSubmit \
  '{hookSpecificOutput: {hookEventName: $ev, additionalContext: env.MSG}}' 2>/dev/null \
  || printf '%s\n' "$MSG"
exit 0
