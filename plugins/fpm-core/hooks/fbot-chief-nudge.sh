#!/usr/bin/env bash
# fbot-chief-nudge.sh — 매니저가 **배분 없이 직접 일하는** 상태를 매 턴 환기 (prj3#Issue605)
#
# 발동: 결속 마커 있는 세션 + 그 봇이 매니저(chief·lead·hr) + state=working
#       + current_task 있음 + **자기가 낸 열린 배분 0건**
# no-op: 마커 부재(일반 세션 — 프로세스 0회) · 헬퍼/DB 부재 · 매니저 아님 · 열린 배분 있음
# ⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude 면 Issue.md 등록 후)
#
# 왜 필요한가 (Issue605 실측 2026-09-09):
#   exec 매뉴얼에 *"직접 실행하는 것은 등록·배분·보고뿐"* 조항이 **있고 그 세션에서 읽히기까지 했는데**
#   나래가 prj10 PM 을 두고 ego 검증을 직접 했다. 조항이 passive 라 지키는지가 요청 성격·재량에 달렸다.
#   배분이 원장에 없으면 그 작업은 보드·체인에서 통째로 사라진다 — 관제 체계에서 가장 큰 손실이다.
#
# 왜 차단이 아니라 환기인가:
#   매니저에게도 정당한 직접 실행이 있다(조사·현황 확인·이슈 등록·보고). "실작업인가" 는 판정 영역이라
#   hook 이 가를 수 없다([hook-rules] 규칙9). 기계가 셀 수 있는 것(배분 0건)만 말하고 판단은 봇에 맡긴다.
set -uo pipefail

_SID="${CLAUDE_CODE_SESSION_ID:-}"
[ -n "$_SID" ] || exit 0
_MARK="$HOME/.claude/.fbot-handoff/sid-$_SID.id"
[ -f "$_MARK" ] || exit 0                      # ← 무비용 게이트. 일반 세션은 여기서 끝

_BOT="$(cat "$_MARK" 2>/dev/null)"; [ -n "$_BOT" ] || exit 0
_DB="${AOA_MEMORY_DIR:-$HOME/_git/___common/data/aoa}/registry.db"
[ -f "$_DB" ] || exit 0
command -v sqlite3 >/dev/null 2>&1 || exit 0

# 한 번의 질의로 판정 재료를 모은다 — role·state·task·열린 배분 수
_row="$(sqlite3 -separator '|' "$_DB" "
  SELECT b.role, b.state, COALESCE(b.current_task,''),
         (SELECT COUNT(*) FROM job j
           WHERE j.kind='fbot_dispatch' AND j.status IN ('open','blocked')
             AND j.owner='$_BOT')
    FROM bot b WHERE b.bot_id='$_BOT'" 2>/dev/null)"
[ -n "$_row" ] || exit 0

IFS='|' read -r _role _state _task _open <<< "$_row"
case "$_role" in chief|lead|hr) ;; *) exit 0 ;; esac   # 매니저만
[ "$_state" = "working" ] || exit 0
[ -n "$_task" ] || exit 0
[ "${_open:-0}" = "0" ] || exit 0                        # 배분이 하나라도 열려 있으면 정상

# 안내 문형은 **역할마다 다르다** (prj3#Issue612). 종전엔 하나뿐이라 팀장에게도
#   `--role lead --bot-id <PM>` 를 권했는데, 그것은 총괄이 PM 에게 내리는 문형이다.
#   팀장이 그대로 따라 하면 자기 자신에게 배분하는 꼴이고, 정작 필요한 워커 자리는 계속 빈다.
if [ "$_role" = "lead" ]; then
  _hint='실작업이면 **자리 있는 일은 내려보낸다**(검토→qa · 설계→architect · 배포→release): `fbot-lead.py dispatch --by '"$_BOT"' --role <qa|architect|release|…> --cwd <경로> --issue Issue<N>` → 응답의 next_step 실행 → `sweep`. 자리 없는 일·긴급 건이면 `fbot-lead.py solo --by '"$_BOT"' --reason "<사유>"` 로 원장에 남기고 직접 한다 — 쓰기 가드가 이 둘 중 하나를 요구한다.'
else
  _hint='실작업이면 지금 배분한다: `fbot-org.py resolve --prj <N>` → `fbot-lead.py dispatch --by '"$_BOT"' --role lead --bot-id <PM> --cwd <경로> --topic "<요지>"` → 응답의 next_step 실행 → `sweep`.'
fi
printf '[핀봇 위임 환기 — %s] 현재 작업 "%s" 에 대해 **열린 배분이 0건**이다. 매니저의 직접 실행은 등록·배분·보고·조사까지다 — %s 배분 없이 끝내면 그 작업은 원장에 안 남아 보드·작업 체인에서 사라진다. 조사·보고 중이라 배분이 불필요하면 이 줄을 무시한다.\n' \
  "$_BOT" "${_task:0:60}" "$_hint"
exit 0
