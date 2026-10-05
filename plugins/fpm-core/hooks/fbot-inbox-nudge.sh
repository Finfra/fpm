#!/usr/bin/env bash
# fbot-inbox-nudge.sh — 결속 중인 매니저에게 미처리 요청 환기 (dispatch-userpromptsubmit.sh 의 자식), prj3#Issue552
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj1#Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#   설계 SSOT: ~/.claude/_doc_arch/fbot-manager.md "§소비 3경로"
#
# 발동: 이 세션에 결속된 봇 중 **매니저**(exec·taskmgr·hr) 앞으로 `open` 요청이 있을 때,
#   다음 턴 경계에 1블록 주입. 매니저가 `reply --status accepted|rejected|done` 하면 그친다.
#   + 핀봇 질문(prj3#Issue749): 이 세션이 **의뢰 세션**인 질문(`q-<sid>`) 또는 공용 질문(`q-any`)이
#   있으면 결속 여부와 무관하게 1블록 — AskUserQuestion 으로 묻고 `reply` 로 답하라는 지시.
# no-op: 결속 마커(`.fbot-handoff/sid-<sid>.id`)·질문 마커(`q-<sid>`·`q-any`) 모두 부재 → 첫 블록 exit 0, fork 0회.
#   마커가 있어도 헬퍼 부재·매니저 아님·요청 0건이면 무출력 exit 0. pm-do `-p` 몸체에는 질문을 싣지 않는다
#   (물을 사람이 없다 — 그 몸체의 질문은 거꾸로 이쪽으로 중계되는 쪽이다).
#
# 왜 (Issue552 원 문제):
#   결속된 총괄핀봇이 **다른 프로젝트의 요청을 무시**했다 — 요청이 오려면 결속해야 했고
#   결속은 배타라 두 번째가 거부됐다. fbot-inbox.py 가 적재 쪽을 풀었지만, 결속돼 작업 중인
#   매니저는 스스로 인박스를 열 계기가 없다. 세션은 자기 프롬프트만 본다. 그래서
#   **다음 턴 경계**에 실어 보낸다 — 비-Claude 프로세스의 통지를 세션에 넣는 유일한 합법 경로다
#   (session-delegation "완료 통지 → UserPromptSubmit 주입" 선례, prj5#Issue64).
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
# ← 무비용 게이트. 이 앞에 프로세스 0. 질문 마커 디렉토리는 fbot-inbox.py `_handoff_dir` 와 **같은 해석**:
#   FBOT_HANDOFF_DIR(테스트 주입구) > FBOT_REGISTRY_DB 를 갈아끼운 실행이면 그 원장 옆 > 운영 결속 마커 디렉토리.
#   파라미터 확장뿐이라 fork 0 — 격리 원장 테스트가 운영 마커에 반응하지 않는다
_QD="${FBOT_HANDOFF_DIR:-${FBOT_REGISTRY_DB:+${FBOT_REGISTRY_DB%/*}/.fbot-questions}}"
_QD="${_QD:-$HOME/.claude/.fbot-handoff}"
_BOUND=0; _ASK=0
[ -f "$HOME/.claude/.fbot-handoff/sid-$_SID.id" ] && _BOUND=1
if [ "${FPM_SESSION_ORIGIN:-}" != "pm-do" ] && { [ -f "$_QD/q-$_SID" ] || [ -f "$_QD/q-any" ]; }; then _ASK=1; fi
[ "$_BOUND$_ASK" = "00" ] && exit 0

_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
INBOX_PY="$_HOOKS_SELF/fbot-inbox.py"
[ -f "$INBOX_PY" ] || exit 0              # 헬퍼 부재 = 배관 미완 → 조용히 no-op

# 한 번의 python3 로 조회+조립까지 끝낸다 — jq 로 다시 풀면 프로세스가 하나 더 든다
MSG="$(python3 - "$INBOX_PY" "$_SID" "$_BOUND" "$_ASK" <<'PY' 2>/dev/null
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fbot_inbox", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
blocks = []
if sys.argv[4] == "1":
    # prj3#Issue749 — 핀봇 질문: 이 세션이 사람에게 물어 답을 돌려준다(-p 몸체는 AskUserQuestion 이 없다)
    qs = m.questions_for(sys.argv[2]).get("items") or []
    if qs:
        ql = [f"[핀봇 질문 {len(qs)}건 — 사람 답 대기] 봇이 작업을 멈추고 기다린다. 각 질문을 **AskUserQuestion 으로 사용자에게 물은 뒤** "
              "`python3 ~/.claude/hooks/fbot-inbox.py reply --id <id> --status done --body '<사용자 답>'` 로 돌려준다 "
              "(답하지 않기로 하면 `--status rejected`). 답이 들어가면 묻던 봇이 답을 들고 자동 재기동된다. 추측으로 대신 답하지 않는다."]
        for q in qs:
            tag = " (공용 — 의뢰 세션 미상·장기 미응답)" if q.get("public") else ""
            prj = f" prj{q['prj']}" if q.get("prj") else ""
            ql.append(f"- `{q['id']}` ← {q.get('from') or '?'}{prj}{tag} · 작업 {(q.get('task') or '?')[:60]}: {(q.get('body') or '').strip()[:400]}")
            if q.get("options"):
                ql.append("  선택지: " + " | ".join(o[:60] for o in q["options"]))
            for f in (q.get("followups") or [])[-2:]:
                ql.append(f"  덧붙임: {(f or '')[:160]}")
        blocks.append("\n".join(ql))
r = m.pending(session_id=sys.argv[2]) if sys.argv[3] == "1" else {}
items = r.get("items") or []
if not items:
    if blocks:
        print("\n\n".join(blocks))
    sys.exit(0)
who = ",".join(r.get("managers") or [])
lines = [f"[핀봇 인박스 — {who}] 미처리 요청 {len(items)}건. 결속·현재 작업과 무관하게 **매니저로서 판단**한다 — 받을지(accepted)·거절할지(rejected)·바로 끝낼지(done)를 `python3 ~/.claude/hooks/fbot-inbox.py reply --id <id> --status <s> --body '<응답>'` 로 답한다. 직접 하지 말고 부하에게 배분할 일이면 `fbot-lead.py dispatch --by {who}` 로 넘긴다. 답하기 전까지 매 턴 다시 뜬다."]
for it in items:
    src = it.get("from") or it.get("from_session") or "?"
    prj = f" prj{it['prj']}" if it.get("prj") else ""
    lines.append(f"- `{it['id']}` ← {src}{prj} [{it.get('kind') or 'ask'}]: {(it.get('body') or '').strip()[:200]}")
if any(it.get("kind") == "question" for it in items):
    # prj3#Issue757 — 팀원 질문은 사람이 아니라 팀장이 받는다. 팀원은 작업을 멈추고 답을 기다린다
    # prj3#Issue831 ① — 팀장의 질문은 총괄이 받는다(사람 결정은 팀장 → 총괄 → 사람). 팀장이 올린 질문은 총괄에게 간다
    lines.append("[question] 은 **팀원 질문**이다(총괄에게는 팀장의 질문 — 묻는 봇 작업이 멈춰 있다). 정할 수 있으면(팀장 L·총괄 C) "
                 "`python3 ~/.claude/hooks/fbot-inbox.py reply --id <id> --status done --body '<답>' --by <나>` — 묻던 봇이 답을 들고 재기동된다. "
                 "위의 결정이 필요하면 그 질문을 **번호 목록 평문**으로 정리해 남기고 턴을 끝낸다 — 팀장이면 총괄에게, 총괄이면 의뢰한 사람에게 올라가고, 답이 오면 네가 재기동된다. 그때 이 질문에 답한다.")
blocks.append("\n".join(lines))
print("\n\n".join(blocks))
PY
)"
[ -n "$MSG" ] || exit 0
MSG="$MSG" jq -n --arg ev UserPromptSubmit \
  '{hookSpecificOutput: {hookEventName: $ev, additionalContext: env.MSG}}' 2>/dev/null \
  || printf '%s\n' "$MSG"
exit 0
