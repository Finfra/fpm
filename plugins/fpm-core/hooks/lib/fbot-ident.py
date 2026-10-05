#!/usr/bin/env python3
"""fbot-ident.py — 봇 신원 대조 판정 단일 지점 (prj3#Issue832)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 파일은 모든 프로젝트가 공유. cwd ≠ ~/.claude 면
  즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT: ~/.claude/_doc_arch/fbot-manager.md
  «§응답» · 절차: ~/.claude/rules/global-scar-change-rules.md

`--by` 는 누구나 쓰는 문자열이다. 봇 몸체는 스폰 때 `FBOT_ID` 를 받고, `/fbot-bind` 결속 세션은 세션 슬롯
`sid-<SID>.id` 를 받는다(Issue960) — **호출 세션이 `--by` 본인인가**는 `caller_bot`(FBOT_ID → 슬롯) == --by 로 판정된다.
둘이 다르면 거부. 하청 슬롯은 보지 않는다(주 세션과 구별 불가). 이 대조가 소비처마다 복제돼 있었고(manual-review `mark`·`submit`·전결,
fbot-lead 총괄 확인) 인박스 `staffing`·`reply` 에는 빠져 있었다(Issue757 codex-arch-checker) — 한 곳에 모은다.

두 형태:
  ① `impersonation_error(by, what)` — **엄격**: 호출 세션이 반드시 `--by` 봇이어야 한다(FBOT_ID 없음 = 거부).
     봇만 할 수 있는 행위(작성 표지·상신·전결·차용 기록)에 쓴다
  ② `bot_caller_error(by, what)` — **봇 세션에만**: `FBOT_ID` 가 있으면 ① 과 같고, 없으면(사람·비봇 세션) 통과.
     사람 세션도 쓰는 경로(인박스 응답·인력 요청)에 쓴다 — 사람 경로는 종전 그대로 둔다
반환은 거부 사유 문자열 또는 None. 예외를 던지지 않는다 — 소비처의 오류 형식(die·Reject·{"ok":False})이 제각각이다.
"""
import os
import re


def handoff_dir(env=None):
    """세션 슬롯 디렉토리 — 주입구 FBOT_HANDOFF_DIR 은 테스트 전용, 운영 기본 `~/.claude/.fbot-handoff`."""
    env = env if env is not None else os.environ
    return env.get("FBOT_HANDOFF_DIR") or os.path.join(os.path.expanduser("~"), ".claude", ".fbot-handoff")


def sid_marker_path(session_id, form="", bot_id="", env=None):
    """세션 id → bot_id 마커 경로의 단일 계산 지점 (prj3#Issue960). form="agent" 는 하청 슬롯."""
    base = handoff_dir(env)
    if form == "agent":
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", bot_id or "anon")
        return os.path.join(base, f"sid-{session_id}.agent-{safe}.id")
    return os.path.join(base, f"sid-{session_id}.id")


def session_slot_bot(env=None):
    """`/fbot-bind` 결속 세션의 봇 id — 세션 슬롯 `sid-<SID>.id` 내용, 없으면 빈 문자열.
    하청 슬롯(`.agent-*.id`)은 보지 않는다 — 같은 sid 의 주 세션과 Agent 를 구별할 수 없다."""
    env = env if env is not None else os.environ
    sid = (env.get("CLAUDE_CODE_SESSION_ID") or "").strip()
    if not sid:
        return ""
    try:
        with open(sid_marker_path(sid, env=env), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def caller_bot(env=None):
    """호출 세션의 봇 id — `FBOT_ID`(스폰 몸체), 없으면 결속 세션 슬롯. 둘 다 없으면 빈 문자열."""
    env = env if env is not None else os.environ
    return (env.get("FBOT_ID") or "").strip() or session_slot_bot(env)


def _conflict(env=None):
    """FBOT_ID 와 세션 슬롯이 둘 다 있고 다르면 사유 — 스폰 몸체가 남의 결속 sid 로 도는 경우."""
    env = env if env is not None else os.environ
    fid = (env.get("FBOT_ID") or "").strip()
    slot = session_slot_bot(env) if fid else ""
    if fid and slot and fid != slot:
        return f"FBOT_ID={fid!r} 와 세션 결속 슬롯({slot!r})이 다르다 — 신원 불명"
    return None


def impersonation_error(by, what="호출", env=None):
    """엄격 대조 — 호출 세션(FBOT_ID·결속 슬롯)이 `--by` 본인이 아니면 사유."""
    conflict = _conflict(env)
    if conflict:
        return f"{what} 거부 — {conflict}"
    fid = caller_bot(env)
    if fid != (by or "").strip():
        return f"{what} 호출 세션이 --by 본인이 아니다 (FBOT_ID={fid!r}, --by={by!r}) — 사칭 금지"
    return None


def bot_caller_error(by, what="호출", env=None):
    """봇 세션에만 대조 — 비봇(사람) 세션은 None(종전 동작)."""
    if not caller_bot(env):
        return None
    return impersonation_error(by, what, env)
