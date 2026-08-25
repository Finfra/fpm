#!/usr/bin/env python3
"""fbot 상태 기계·lease helper (Issue436_3 s1 — 작업 항목 3).

계약: ~/.claude/_doc_arch/fbot-arch.md §상태 기계(5상태)·§레지스트리 스키마(F1)·§봇 수명주기.
      계약 참조만 하며 여기서 재결정하지 않는다.

저장 값 매핑 (계약 2026-08-24 확정 — 표시는 한글, 저장·질의는 영문):
    출근중 checkin · 작업중 working · 수신대기 waiting_input · 완료대기 waiting_child · 퇴근 checkout

설계 원칙
* 표준 라이브러리만 사용한다(무의존). PyYAML 도 쓰지 않는다 — policy.yml 은 평탄 키라 정규식으로 읽는다.
* fail-loud: 미등록 봇·전이표에 없는 전이·미정의 상태값은 전부 명시 에러 + exit != 0.
* 쓰기는 BEGIN IMMEDIATE + busy_timeout(store.py 방식) — 다중 프로세스 동시 접근이 전제다.
* TTL 하드코딩 금지 — aoa policy.yml 의 lease_ttl_secs 가 SSOT.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time

# ── 계약 상수 ────────────────────────────────────────────────────────────────

# 5상태 저장 값 (계약 §상태 기계 저장 값 매핑)
STATES = ("checkin", "working", "waiting_input", "waiting_child", "checkout")

# 상태 → 한글 호칭 (표시 전용)
STATE_LABEL = {
    "checkin": "출근중",
    "working": "작업중",
    "waiting_input": "수신대기",
    "waiting_child": "완료대기",
    "checkout": "퇴근",
}

# 경력 축 (계약 §봇 수명주기 — career 필드가 SSOT)
CAREERS = ("probation", "active", "leave", "terminated")

# 전이표 — 계약 §상태 기계의 진입·이탈 조건을 그대로 옮긴 것.
#   checkin  → working   : 매뉴얼+봇별 상태 로드 완료
#   working  → waiting_* : 입력 필요 / 하위 위임
#   waiting_*→ working   : 입력 도착 / 하위 완료 통지
#   * → checkout         : 작업 완료·세션 종료(Stop 훅)·lease 만료 강제
#                          (세션 종료·lease 만료는 어느 상태에서든 발생하므로 전 상태에서 허용)
#   checkout → checkin   : 다음 출근(SessionStart 훅). 퇴근에서 작업중으로 직행은 금지 —
#                          매뉴얼·봇별 상태 로드를 건너뛰기 때문이다.
TRANSITIONS = {
    "checkin": {"working", "checkout"},
    "working": {"waiting_input", "waiting_child", "checkout"},
    "waiting_input": {"working", "checkout"},
    "waiting_child": {"working", "checkout"},
    "checkout": {"checkin"},
}

# 전이 사유 (에러 메시지·감사 로그용)
TRANSITION_REASON = {
    ("checkin", "working"): "매뉴얼+봇별 상태 로드 완료",
    ("working", "waiting_input"): "사용자/타 봇 입력 필요",
    ("working", "waiting_child"): "하위 봇 위임",
    ("waiting_input", "working"): "입력 도착",
    ("waiting_child", "working"): "하위 완료 통지",
    ("checkout", "checkin"): "다음 출근(세션 기동)",
}

DEFAULT_AOA_DIR = os.path.join(os.path.expanduser("~"), "_git", "___common", "data", "aoa")
DEFAULT_LEASE_TTL = 300  # policy.yml 부재 시에만 쓰는 최후 폴백. 정상 경로는 policy 를 읽는다.


class FbotError(Exception):
    """fail-loud 용 — 메시지를 그대로 stderr 에 내고 exit != 0."""


# ── 경로·정책 ────────────────────────────────────────────────────────────────

def aoa_dir() -> str:
    """AOA_MEMORY_DIR env 를 존중한다(s0 래퍼 fbot-tick.sh 와 동일 방식)."""
    return os.environ.get("AOA_MEMORY_DIR") or DEFAULT_AOA_DIR


def registry_path() -> str:
    p = os.path.join(aoa_dir(), "registry.db")
    if not os.path.exists(p):
        raise FbotError(f"레지스트리 DB 없음: {p} (AOA_MEMORY_DIR 확인)")
    return p


def lease_ttl_secs() -> int:
    """lease TTL 은 aoa policy.yml 의 lease_ttl_secs 가 SSOT — 하드코딩 금지.

    policy.yml 은 평탄(top-level) 키 구조라 정규식 한 줄로 충분하다. PyYAML 의존을 만들지 않는다.
    """
    path = os.path.join(aoa_dir(), "policy.yml")
    if not os.path.exists(path):
        return DEFAULT_LEASE_TTL
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^lease_ttl_secs:\s*(\d+)", line)
            if m:
                return int(m.group(1))
    return DEFAULT_LEASE_TTL


# ── DB ──────────────────────────────────────────────────────────────────────

def connect() -> sqlite3.Connection:
    """WAL + busy_timeout 커넥션 (store.py 방식 승계 — 다중 프로세스 동시 접근 전제)."""
    con = sqlite3.connect(registry_path(), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def fetch_bot(con: sqlite3.Connection, bot_id: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM bot WHERE bot_id = ?", (bot_id,)).fetchone()
    if row is None:
        raise FbotError(f"미등록 봇: {bot_id} — register 로 먼저 등록하라")
    return row


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["state_label"] = STATE_LABEL.get(d.get("state"), "?")
    return d


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── 검증 ────────────────────────────────────────────────────────────────────

def validate_state(state: str) -> str:
    if state not in STATES:
        raise FbotError(
            f"미정의 상태값: {state!r} — 허용값 {', '.join(STATES)}"
        )
    return state


def validate_career(career: str) -> str:
    if career not in CAREERS:
        raise FbotError(
            f"미정의 career 값: {career!r} — 허용값 {', '.join(CAREERS)}"
        )
    return career


def validate_transition(cur: str, to: str) -> None:
    """계약 전이표에 없는 전이는 거부한다(fail-loud)."""
    validate_state(to)
    if cur not in TRANSITIONS:
        raise FbotError(f"레코드의 현재 상태값이 계약 밖: {cur!r}")
    if to == cur:
        raise FbotError(
            f"동일 상태 전이 금지: {STATE_LABEL[cur]}({cur}) → {STATE_LABEL[to]}({to}) "
            "— 상태를 바꾸지 않는 호출은 heartbeat 를 쓰라"
        )
    if to not in TRANSITIONS[cur]:
        allowed = ", ".join(sorted(TRANSITIONS[cur])) or "(없음 — 종료 상태)"
        raise FbotError(
            f"불법 전이 거부: {STATE_LABEL[cur]}({cur}) → {STATE_LABEL[to]}({to}). "
            f"{STATE_LABEL[cur]} 에서 허용된 전이: {allowed}"
        )


# ── 서브커맨드 ──────────────────────────────────────────────────────────────

def cmd_register(args) -> int:
    """봇 레코드 생성. 멱등이 아니다 — 이미 있으면 갱신하지 않고 명시 실패한다."""
    validate_career(args.career)
    now = int(time.time())
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        dup = con.execute("SELECT bot_id FROM bot WHERE bot_id = ?", (args.bot_id,)).fetchone()
        if dup is not None:
            con.execute("ROLLBACK")
            raise FbotError(
                f"이미 등록된 봇: {args.bot_id} — register 는 갱신하지 않는다(명시 실패)"
            )
        con.execute(
            "INSERT INTO bot (bot_id, title, role, state, career, icon, color, prj,"
            " current_task, parent_bot_id, lease_expires, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                args.bot_id, args.title, args.role,
                "checkin",                       # 신규 봇은 출근중으로 시작한다(계약 진입 조건)
                args.career, args.icon, args.color, args.prj,
                None, args.parent,
                now + lease_ttl_secs(),
                now,
            ),
        )
        con.execute("COMMIT")
        emit({"ok": True, "action": "register", "bot": row_to_dict(fetch_bot(con, args.bot_id))})
    finally:
        con.close()
    return 0


def cmd_transition(args) -> int:
    """전이 규칙 검증 후 상태 변경. 성공 시 lease 를 함께 갱신한다."""
    to = validate_state(args.to)
    ttl = lease_ttl_secs()
    now = int(time.time())
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            row = fetch_bot(con, args.bot_id)
            cur = row["state"]
            validate_transition(cur, to)
            con.execute(
                "UPDATE bot SET state = ?, lease_expires = ? WHERE bot_id = ?",
                (to, now + ttl, args.bot_id),
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({
            "ok": True, "action": "transition",
            "from": cur, "from_label": STATE_LABEL[cur],
            "to": to, "to_label": STATE_LABEL[to],
            "reason": TRANSITION_REASON.get((cur, to), "세션 종료·lease 만료 등"),
            "lease_expires": now + ttl, "lease_ttl_secs": ttl,
            "bot": row_to_dict(fetch_bot(con, args.bot_id)),
        })
    finally:
        con.close()
    return 0


def cmd_heartbeat(args) -> int:
    """lease_expires = now + TTL 갱신. TTL 은 policy.yml 이 SSOT."""
    ttl = lease_ttl_secs()
    now = int(time.time())
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            row = fetch_bot(con, args.bot_id)
            if row["state"] == "checkout":
                raise FbotError(
                    f"퇴근한 봇에는 heartbeat 를 걸 수 없다: {args.bot_id} "
                    "— transition --to checkin 으로 재출근이 먼저다"
                )
            con.execute(
                "UPDATE bot SET lease_expires = ? WHERE bot_id = ?", (now + ttl, args.bot_id)
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({
            "ok": True, "action": "heartbeat", "bot_id": args.bot_id,
            "now": now, "lease_ttl_secs": ttl, "lease_expires": now + ttl,
        })
    finally:
        con.close()
    return 0


def cmd_reap(args) -> int:
    """lease 만료 봇 스캔 → 강제 퇴근. 기본 dry-run, --apply 로 실제 적용.

    계약 §상태 기계: 크래시한 봇이 "작업중"으로 영원히 남지 않게 lease 만료 시 강제 퇴근한다.
    회수 경로는 s1 plan 확정대로 maint(s0 상주 스케줄러)가 본 서브커맨드를 부른다.
    """
    now = int(time.time())
    con = connect()
    try:
        rows = con.execute(
            "SELECT * FROM bot WHERE state != 'checkout'"
            " AND lease_expires IS NOT NULL AND lease_expires < ?"
            " ORDER BY lease_expires",
            (now,),
        ).fetchall()
        expired = [row_to_dict(r) for r in rows]
        for e in expired:
            e["overdue_secs"] = now - int(e["lease_expires"])

        reaped = []
        if args.apply and expired:
            con.execute("BEGIN IMMEDIATE")
            try:
                for e in expired:
                    # 강제 퇴근은 전 상태에서 허용되는 전이다(계약 §상태 기계 퇴근 진입 조건)
                    validate_transition(e["state"], "checkout")
                    con.execute(
                        "UPDATE bot SET state = 'checkout' WHERE bot_id = ?", (e["bot_id"],)
                    )
                    reaped.append(e["bot_id"])
            except Exception:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")

        emit({
            "ok": True, "action": "reap",
            "mode": "apply" if args.apply else "dry-run",
            "now": now, "lease_ttl_secs": lease_ttl_secs(),
            "expired_count": len(expired),
            "expired": expired,
            "reaped": reaped,
        })
    finally:
        con.close()
    return 0


def cmd_get(args) -> int:
    con = connect()
    try:
        emit({"ok": True, "action": "get", "bot": row_to_dict(fetch_bot(con, args.bot_id))})
    finally:
        con.close()
    return 0


def cmd_list(args) -> int:
    where, params = [], []
    if args.state:
        where.append("state = ?")
        params.append(validate_state(args.state))
    if args.role:
        where.append("role = ?")
        params.append(args.role)
    sql = "SELECT * FROM bot"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at"
    con = connect()
    try:
        rows = [row_to_dict(r) for r in con.execute(sql, params).fetchall()]
        emit({"ok": True, "action": "list", "count": len(rows), "bots": rows})
    finally:
        con.close()
    return 0


def cmd_set_task(args) -> int:
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            fetch_bot(con, args.bot_id)  # 미등록이면 fail-loud
            con.execute(
                "UPDATE bot SET current_task = ? WHERE bot_id = ?", (args.task, args.bot_id)
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({"ok": True, "action": "set-task", "bot": row_to_dict(fetch_bot(con, args.bot_id))})
    finally:
        con.close()
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fbot-state.py",
        description="fbot 상태 기계·lease helper (Issue436_3 s1) — 계약 fbot-arch.md §상태 기계",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("register", help="봇 레코드 생성(이미 있으면 명시 실패)")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--role", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--prj", type=int, default=None, help="주 담당 prj 번호(전역봇은 생략)")
    sp.add_argument("--parent", default=None, help="스폰 부모 bot_id(상비 봇·사람 기동은 생략)")
    sp.add_argument("--career", default="probation", help=f"{'|'.join(CAREERS)} (기본 probation)")
    sp.add_argument("--icon", default=None)
    sp.add_argument("--color", default=None)
    sp.set_defaults(func=cmd_register)

    sp = sub.add_parser("transition", help="전이 규칙 검증 후 상태 변경(+lease 갱신)")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--to", required=True, help=f"{'|'.join(STATES)}")
    sp.set_defaults(func=cmd_transition)

    sp = sub.add_parser("heartbeat", help="lease_expires = now + TTL 갱신")
    sp.add_argument("--bot-id", required=True)
    sp.set_defaults(func=cmd_heartbeat)

    sp = sub.add_parser("reap", help="lease 만료 봇 스캔 → 강제 퇴근(기본 dry-run)")
    sp.add_argument("--apply", action="store_true", help="실제 퇴근 처리")
    sp.set_defaults(func=cmd_reap)

    sp = sub.add_parser("get", help="봇 1건 조회(JSON)")
    sp.add_argument("--bot-id", required=True)
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("list", help="봇 목록 조회(JSON)")
    sp.add_argument("--state", default=None)
    sp.add_argument("--role", default=None)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("set-task", help="current_task 갱신")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--task", required=True)
    sp.set_defaults(func=cmd_set_task)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FbotError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except sqlite3.Error as e:
        print(f"❌ DB 오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
