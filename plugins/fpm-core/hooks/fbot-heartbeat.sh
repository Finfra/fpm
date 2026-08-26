#!/usr/bin/env bash
# fbot-heartbeat.sh — UserPromptSubmit 자식 + PostToolUse(`*`) 직접 배선, Issue436_3·Issue442
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: 자기 봇을 식별할 수 있고 직전 heartbeat 로부터 FBOT_HEARTBEAT_SEC(기본 60초)가
#       지났을 때만. lease 를 갱신해 크래시한 봇이 "작업중"으로 영원히 남지 않게 한다
#       (계약 fbot-arch.md §상태 기계 — lease 만료 시 강제 퇴근의 데이터 원천).
# no-op: 봇 식별 실패(= 일반 세션) → 첫 블록에서 즉시 exit 0(fork 0회) · 봇이어도 간격
#        미도래면 date 1회로 종료.
#
# ⚠️ Issue442 — **UserPromptSubmit 만으로는 구조적으로 부족하다.** 위임 세션은
#   `claude -p '<프롬프트>'` 비대화 1-shot 이라 UserPromptSubmit 이 딱 한 번 발화한다.
#   그 뒤 5분(lease TTL)이 지나면 **작업 중인 봇이 예외 없이 reap 된다** — 판정이
#   "세션이 살아 있는가" 가 아니라 "프롬프트가 들어왔는가" 를 보고 있었다.
#   reap 은 작업을 멈추지 않지만 워커가 완료 기록을 못 남겨 sweep 이 완료를 영영
#   감지하지 못한다(2026-08-25 적체 6건의 뿌리). 그래서 **PostToolUse(`*`)** 에 함께
#   배선한다 — 도구를 쓰는 한 갱신되고, 진짜 크래시(창 kill)는 도구 호출이 멈추므로
#   여전히 TTL 내에 reap 된다.
#   비용: `*` matcher 는 이미 존재하므로 bash 진입은 **이미 지불 중**이다. 증분은
#   mtime 스로틀된 python3 호출뿐이며 배선은 `async` 라 차단 예산에 안 잡힌다.
#
# ⚠️ Issue442/448 — **Agent(서브에이전트) 형태 봇은 FBOT_ID 가 없다.** 실측: PostToolUse 는
#   Agent 세션에서도 정상 발화하지만(2026-08-26 probe 확증) env 는 부모 프로세스 것이라
#   FBOT_ID 가 전파되지 않는다. 그래서 세션 id 마커(`.fbot-handoff/sid-<sid>.id`)로
#   폴백한다 — 마커는 `fbot-state.py bind` 가 쓰고, 그 bind 는 Issue449 부터
#   [`fbot-agent-bind.sh`](fbot-agent-bind.sh)(PreToolUse `Agent`)가 **자동**으로 부른다.
#   폴백 판정은 fork 0회다(문자열 비교 + `[ -f ]`). 마커 **내용은 읽지 않는다** — 아래 참조.
#
# ⚠️ 이 훅은 **매 턴 차단 경로**(UserPromptSubmit)에 있다. 예산 여유가 가장 적은 자리다
#   (hook-budget.tsv: 200ms 상한, 실측 145~170ms). 그래서 두 겹으로 막는다:
#     ① env 문자열 비교 — 비봇 세션 비용 사실상 0
#     ② mtime 스로틀 — 봇이어도 python3(≈40ms) 기동은 간격당 1회뿐
#   lease TTL(출발값 300초, 계약 🚧)의 1/5 주기라 만료 전에 충분히 갱신된다.
#
# 출력 없음 — 컨텍스트 주입 훅이 아니다. 상태 전이도 하지 않는다(heartbeat 전용).

set -uo pipefail

# ── 봇 식별 (규칙3 무비용 가드 — 여기서 fork 를 쓰지 않는다) ────────────────────
#   ① env FBOT_ID (tmux `-p` 위임 경로 — fpm-do 가 주입) → 봇 1개 지정
#   ② 세션 id 마커 존재 (Agent 형태 — env 가 없다) → **세션 단위 갱신**
#
# ⚠️ Issue449 — 종전엔 마커 **내용**을 읽어 그 봇 하나를 갱신했다. 그런데 Agent 의
#   session_id 는 메인 세션과 같다(실측: 서로 다른 agent_id 4개가 같은 session_id 보고).
#   즉 한 세션에 봇이 여럿 결속될 수 있고, 마커는 마지막 1건만 담는다 — 마커 내용을 믿으면
#   메인 세션의 도구 호출이 엉뚱한 봇의 lease 를 갱신하고, 정작 그 봇은 reap 된다.
#   그래서 **내용을 읽지 않고** session_id 를 그대로 넘긴다. "누구인가" 는 DB 가 답한다.
_SID="${CLAUDE_CODE_SESSION_ID:-}"
if [ -n "${FBOT_ID:-}" ]; then
  _TARGET_FLAG="--bot-id"; _TARGET_VAL="$FBOT_ID"; _STAMP_KEY="$FBOT_ID"
else
  [ -n "$_SID" ] || exit 0
  [ -f "$HOME/.claude/.fbot-handoff/sid-$_SID.id" ] || exit 0
  _TARGET_FLAG="--session-id"; _TARGET_VAL="$_SID"; _STAMP_KEY="sid-$_SID"
fi

STATE_PY="$HOME/.claude/hooks/fbot-state.py"
[ -f "$STATE_PY" ] || exit 0             # 상태 헬퍼 부재 = 배관 미완 → 조용히 no-op

STAMP_DIR="$HOME/.claude/.fbot-handoff"
STAMP="$STAMP_DIR/$_STAMP_KEY.hb"
INTERVAL="${FBOT_HEARTBEAT_SEC:-60}"

# 스로틀: 스탬프가 INTERVAL 초 이내면 아무 것도 하지 않는다(자기 상태 파일 — 규칙8 예외)
if [ -f "$STAMP" ]; then
  now=${EPOCHSECONDS:-$(date +%s)}
  # ⚠️ stat 은 쓰지 않는다 — BSD(`-f %m`)와 GNU(`-c %Y`)의 플래그가 반대라, 폴백 체인을
  #   엮으면 실패한 쪽이 stdout 에 부분 출력을 남겨 값이 오염된다(실측: gnubin stat 이
  #   PATH 앞이면 "File: ..." 가 섞여 산술 오류). `date -r` 은 양쪽에서 같은 뜻이다.
  mt=$(date -r "$STAMP" +%s 2>/dev/null || echo 0)
  [ $(( now - mt )) -lt "$INTERVAL" ] && exit 0
fi

mkdir -p "$STAMP_DIR" 2>/dev/null && : > "$STAMP"
python3 "$STATE_PY" heartbeat "$_TARGET_FLAG" "$_TARGET_VAL" >/dev/null 2>&1 || true
exit 0
