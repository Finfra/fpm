#!/usr/bin/env bash
# fbot-chief-nudge.sh — 매니저가 **배분 없이 직접 일하는** 상태를 매 턴 환기 (prj3#Issue605)
#
# 발동: 결속 마커 있는 세션 + 그 봇이 지휘 계통(카탈로그 nonexec — chief·lead) + state=working
#       + current_task 있음 + **자기가 낸 열린 배분 0건**
# no-op: 마커 부재(일반 세션 — 프로세스 0회) · 헬퍼/DB/카탈로그 부재 · 지휘 계통 아님(인사·발굴·워커) · 열린 배분 있음
# ⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude 면 Issue.md 등록 후)
#
# 왜 필요한가 (Issue605 실측 2026-09-09):
#   exec 매뉴얼에 *"직접 실행하는 것은 등록·배분·보고뿐"* 조항이 **있고 그 세션에서 읽히기까지 했는데**
#   나래가 prj10 PM 을 두고 ego 검증을 직접 했다. 조항이 passive 라 지키는지가 요청 성격·재량에 달렸다.
#   배분이 원장에 없으면 그 작업은 보드·체인에서 통째로 사라진다 — 관제 체계에서 가장 큰 손실이다.
#
# 왜 차단이 아니라 환기인가:
#   관리직에게도 정당한 직접 행위가 있다(회의·모색·지시·수령·전달 — Issue757). "실작업인가" 는 판정 영역이라
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
# 지휘 계통(카탈로그 `nonexec` — 총괄·팀장)만 (prj3#Issue757). 인사·발굴은 판정 자체가 직능이라 «배분하라» 가
#   틀린 지시가 된다 — 종전 `chief|lead|hr` 하드코딩이 hr 에게 총괄 문구를 냈다. 판정 원천은 fbot-org.is_nonexec 와
#   같은 카탈로그 속성(session-inbox.sh 와 같은 방식 — 매 턴 경로라 python 을 띄우지 않는다)
_cat="${FBOT_CATALOG:-$HOME/.claude/data/fbot/icons/catalog.yml}"
[ -f "$_cat" ] || exit 0
grep -qE "^${_role}:.*[[:space:]]nonexec=true([[:space:]]|$)" "$_cat" || exit 0
[ "$_state" = "working" ] || exit 0
[ -n "$_task" ] || exit 0
[ "${_open:-0}" = "0" ] || exit 0                        # 배분이 하나라도 열려 있으면 정상

# 안내 문형은 **역할마다 다르다** (prj3#Issue612 → prj3#Issue757).
#   관리직(총괄·팀장)은 일을 하지 않는다 — 하는 것은 회의·모색·지시·수령·전달 다섯 가지뿐이다.
#   종전 문구의 *"…·조사까지"* 와 팀장 `solo` 후 직접 안내가 직접 수행을 허용하는 원인이었다(원인 ④).
if [ "$_role" = "lead" ]; then
  _hint='실작업이면 **배분한다** — 자리 안의 일은 그 직능에(검토→qa · 설계→architect · 구현→developer · 배포→release): `fbot-lead.py dispatch --by '"$_BOT"' --role <직능> --cwd <경로> --issue Issue<N>` → 응답의 next_step 실행 → `sweep`. 팀에 그 직능 자리가 없으면(자리 밖) **총괄에 인력 요청**(차용·생성), 카탈로그에도 없으면 발굴핀봇에 배분(`--role scout`). 직접 하지 않는다.'
else
  _hint='실작업이면 지금 **팀장에게** 배분한다: `fbot-lead.py dispatch --by '"$_BOT"' --role lead --cwd <경로> --topic "<요지>"` → 응답의 next_step 실행 → `sweep`. 팀장이 없거나 퇴근 중이어도 그대로 낸다(없으면 자동 채용, 퇴근 중이면 기상).'
fi
# prj3#Issue863_17 — «이 작업이 배분할 실작업인가 관리 행위인가» Jev shadow(기록만). hook 이 못 가르던 판정의 재료다.
#   같은 작업은 매 턴 다시 묻지 않는다 — 작업 문자열 해시를 캐시 키로(7일). 분리 기동이라 기다리지 않는다
_tkey="$(printf '%s' "$_task" | shasum 2>/dev/null | cut -c1-16)"
. "$HOME/.claude/hooks/lib/selection-shadow.sh" 2>/dev/null && sel_shadow hook.chief_real_work "$_task" yes "$_tkey"
printf '[핀봇 위임 환기 — %s] 현재 작업 "%s" 에 대해 **열린 배분이 0건**이다. 관리직이 하는 것은 회의·모색·지시·수령·전달뿐이다(Issue757) — 읽은 결과가 보고 본문(점검·조사 결과)이 되면 그것은 실작업이다. %s 배분 없이 끝내면 그 작업은 원장에 안 남아 보드·작업 체인에서 사라진다. 회의·모색(배분 판단을 위한 읽기) 중이라 배분이 아직이면 이 줄을 무시한다.\n' \
  "$_BOT" "${_task:0:60}" "$_hint"
exit 0
