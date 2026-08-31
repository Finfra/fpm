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
import uuid

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

CAREER_LABEL = {
    "probation": "수습", "active": "정식", "leave": "휴직", "terminated": "해고",
}

# career 전이표 (prj3#Issue481) — 계약 §수명주기 "career 전이" 표 그대로.
#   probation → active   : 승격(job 10건·실패율<20%·사람 승인 1회 — 판정은 HR 게이트)
#   probation → leave    : 수습도 휴직 대상이다. 승격 요건을 못 채운 봇이 오히려 유휴일
#                          확률이 높아, active 를 선행 조건으로 묶으면 정작 정리해야 할
#                          개체가 영구 잔류한다
#   active    → leave    : 아카이브
#   leave     → active   : 재출근 복귀 (매뉴얼·레코드가 잔존하므로 재채용이 아니다)
#   leave     → terminated: 해고. **휴직 경유가 필수**다 — 되돌릴 수 없는 전이 앞에
#                          되돌릴 수 있는 단계를 반드시 하나 두어, 사람 승인 게이트가
#                          건너뛰어지지 않게 한다
#   terminated → (없음)  : 종료 상태. 기록은 영속이나 상태는 되돌리지 않는다
CAREER_TRANSITIONS = {
    "probation": {"active", "leave"},
    "active": {"leave"},
    "leave": {"active", "terminated"},
    "terminated": set(),
}

# 상비 role (계약 §조직 4종) — 상비봇 판정의 **필요조건**. 본 파일이 이 값의 SSOT 다.
#   ⚠️ role 만으로는 부족하다 — `is_core_bot()` 이 `parent_bot_id IS NULL` 까지 본다.
#      `fbot-exec-issue331`(role=exec, parent=fbot-taskmgr)은 이슈 워커이지 중역이 아니다.
#   ⚠️ 이 가드는 **기록 계층**에 둔다. "이 봇은 해고 불가" 는 상황 판정이 아니라 불변
#      제약이므로, 판정 계층(HR 게이트)을 우회한 어떤 경로로 와도 막혀야 한다.
CORE_ROLES = ("exec", "recruit", "hr", "taskmgr")

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

# 결속 컬럼 (Issue448) — "이 pane·이 세션의 봇은 누구인가" 의 데이터 원천.
#   ⚠️ NULL 은 "미등록" 이 아니라 **"pane 기반 판정 불가"** 다. Agent(서브에이전트) 실행
#   형태는 pane 이 원래 없다. 이 구분이 무너지면 소비처(fpm-do 게이트)가 fail-open 에서
#   fail-wrong 으로 바뀐다 — Issue445 명세 ⚠️ 항 참조.
#   last_task 는 Issue441 — 출근 시 current_task 를 비우되 "직전에 뭘 했나" 는 남긴다.
BIND_COLUMNS = (
    ("tmux_target", "TEXT"),   # 'session:window.pane' — tmux 실행 형태에서만 채워진다
    ("session_id", "TEXT"),    # claude 세션 id — Agent 형태 포함 모든 실행 형태에서 취득 가능
    ("last_task", "TEXT"),     # 퇴근 시 current_task 를 옮겨 담는다(Issue441)
    ("form", "TEXT"),          # 실행 형태 'session'|'agent' — NULL 은 미판정(Issue495)
)

# ── 실행 형태 (Issue495) ────────────────────────────────────────────────────
#   왜 축이 필요한가 — 같은 "봇" 이라도 **수명주기 훅이 다르다**. 세션 형태는
#   SessionStart→heartbeat→Stop 3단이 다 있지만, Agent 형태는 부모 세션 안에서 돌아
#   `FBOT_ID` env 가 구조적으로 없다(fbot-heartbeat.sh Issue442/448 주석 참조).
#   그 차이를 기록해 두지 않으면 진단이 "왜 이 봇만 기록이 없나" 를 매번 다시 캔다.
#
#   ⚠️ **완료 판정을 이 축으로 분기시키지 않는다.** 분기는 판정을 둘로 쪼개 한쪽만
#   낡게 만든다. 대신 Agent 형태에도 퇴근 훅(fbot-agent-done.sh)을 주어 **같은 증거**
#   (`fbot_session` job)를 남기게 했다 — 형태가 달라도 판정은 하나다.
FORMS = ("session", "agent")

# reap 이 강제 종결한 배분의 status (Issue495 ⓒ).
#   `done`(완료 확인) 도 `cancelled`(무의미해져 접음) 도 아닌 **완료 여부 미상**이다.
#   소비처는 ('open','blocked') 밖을 전부 종결로 보므로 새 값이 안전하다.
#   (`DISPATCH_KIND` 는 배분 원장 절에서 정의한다 — 함수 실행 시점엔 이미 바인딩돼 있다.)
DISPATCH_REAPED = "reaped"

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
DEFAULT_AOA_DIR = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa")
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
    ensure_schema(con)
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    """결속 컬럼 마이그레이션 (Issue448) — 멱등.

    STRICT 테이블이라 임의 DDL 은 못 쓰지만 ``ALTER TABLE ... ADD COLUMN`` 은 허용된다
    (기본값 NULL · STRICT 허용 타입). 테이블 재작성이 아니므로 **기존 행이 그대로 보존**된다.
    prj5 소유 DDL 을 건드리지 않고 prj3 helper 가 스스로 보정하는 형태다.
    """
    have = {r[1] for r in con.execute("PRAGMA table_info(bot)").fetchall()}
    for name, typ in BIND_COLUMNS:
        if name not in have:
            con.execute(f"ALTER TABLE bot ADD COLUMN {name} {typ}")


def _dispatch_worker(payload) -> str:
    """배분 원장 payload 에서 워커 bot_id 를 꺼낸다 (Issue495).

    payload 는 JSON TEXT 이고 손상돼 있을 수 있다. 파싱 실패를 예외로 올리면 reap 전체가
    죽어 **정상 봇의 회수까지 막힌다** — 그 한 건만 대상에서 빠지는 것이 맞다.
    """
    try:
        return (json.loads(payload or "{}") or {}).get("worker_bot_id") or ""
    except (ValueError, TypeError):
        return ""


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


def validate_form(form):
    """실행 형태 검증 (Issue495). None 은 통과 — **미판정과 오값은 다르다.**

    기존 행은 전부 NULL 이고 그것이 정상이다(마이그레이션 시점엔 형태를 소급할 수 없다).
    오값만 거부해 새로 들어오는 값의 품질을 지킨다.
    """
    if form is None:
        return None
    if form not in FORMS:
        raise FbotError(
            f"미정의 form 값: {form!r} — 허용값 {', '.join(FORMS)}"
        )
    return form


def is_core_role(role: str) -> bool:
    """상비 role 계열 여부 (계약 §조직 4종). ⚠️ 이것만으로 상비봇을 판정하지 말 것 —
    `is_core_bot()` 을 쓴다. role 은 필요조건일 뿐이다."""
    return role in CORE_ROLES


def is_core_bot(row) -> bool:
    """상비봇 판정 = **상비 role + parent 없음** (2026-08-31 실측으로 좁힌 조건).

    role 만 보면 과보호가 된다 — `fbot-exec-issue331`(role=exec, parent=fbot-taskmgr)은
    작업핀봇이 배치한 **이슈 워커**이지 중역핀봇이 아니다. 그런 개체까지 영구 보호하면
    정작 정리 대상인 워커가 상비봇 행세를 하며 남는다.

    상비봇은 조직 골격이라 누가 채용한 것이 아니다 — 그래서 `parent_bot_id IS NULL` 이
    구조적 표지가 된다(실측: 상비 3종만 parent 가 비어 있다).
    """
    return is_core_role(row["role"]) and row["parent_bot_id"] is None


def validate_career_transition(cur: str, to: str) -> str:
    """career 전이 규칙 검증 (prj3#Issue481). 불법이면 허용 목록과 함께 fail-loud."""
    validate_career(cur)
    validate_career(to)
    if cur == to:
        raise FbotError(
            f"동일 career 전이 금지: {CAREER_LABEL[cur]}({cur}) — 상태 변화가 없다"
        )
    if to not in CAREER_TRANSITIONS[cur]:
        allowed = ", ".join(sorted(CAREER_TRANSITIONS[cur])) or "(없음 — 종료 상태)"
        raise FbotError(
            f"불법 career 전이 거부: {CAREER_LABEL[cur]}({cur}) → {CAREER_LABEL[to]}({to}). "
            f"{CAREER_LABEL[cur]} 에서 허용된 전이: {allowed}"
        )
    return to


def apply_career(con, bot_id: str, to: str) -> dict:
    """career 전이를 레코드에 반영한다 — **규칙 검증만, 판정 없음**.

    승격 요건(job 건수·실패율)·유휴 임계 판정은 HR 게이트 소관이다. 여기는 `register`
    가 `hire` 에 대해 갖는 관계와 동형인 기록 계층이다.

    휴직은 lease 를 해제한다 — 계약 §수명주기 *"비활성 보존 — 레코드 유지·lease 해제"*.
    lease 를 남기면 reap 스캔이 계속 그 봇을 후보로 잡아 휴직이 무의미해진다.
    """
    row = fetch_bot(con, bot_id)
    cur = row["career"]
    if is_core_bot(row) and to in ("leave", "terminated"):
        raise FbotError(
            f"상비봇 보호: {bot_id}(role={row['role']}, parent 없음) 는 {CAREER_LABEL[to]} 대상이 아니다 "
            f"— 조직 골격이라 비면 판정 주체가 사라진다 (계약 §조직). "
            f"상비 role: {', '.join(CORE_ROLES)}"
        )
    validate_career_transition(cur, to)
    if to == "leave":
        con.execute(
            "UPDATE bot SET career = ?, lease_expires = NULL WHERE bot_id = ?", (to, bot_id))
    else:
        con.execute("UPDATE bot SET career = ? WHERE bot_id = ?", (to, bot_id))
    return {"from": cur, "from_label": CAREER_LABEL[cur],
            "to": to, "to_label": CAREER_LABEL[to]}


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
    form = validate_form(getattr(args, "form", None))
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
            " current_task, parent_bot_id, lease_expires, created_at,"
            " tmux_target, session_id, form)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                args.bot_id, args.title, args.role,
                "checkin",                       # 신규 봇은 출근중으로 시작한다(계약 진입 조건)
                args.career, args.icon, args.color, args.prj,
                None, args.parent,
                now + lease_ttl_secs(),
                now,
                # Issue448 — 스폰 시점에 알 수 있으면 기록, 모르면 NULL(= 판정 불가).
                #   Agent 형태는 여기서 항상 NULL 이고 그것이 정상이다.
                args.tmux_target, args.session_id,
                # Issue495 — 등록 시점엔 대개 형태를 모른다(집행이 fpm-do 인지 Agent 인지는
                #   배분 뒤에 갈린다). 그래서 기본은 NULL 이고, 실제로 Agent 로 뜨면
                #   PreToolUse(`Agent`) 훅의 bind 가 그때 'agent' 로 확정한다.
                form,
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
            # Issue441 — 낡은 작업을 "현재 작업" 으로 보여주는 것만은 금지한다.
            #   퇴근에서 current_task 를 비우고 값은 last_task 로 옮긴다(후보 ⓒ).
            #   출근(checkin)에서도 한 번 더 비운다 — 퇴근 경로를 안 거친 봇(reap 등) 방어.
            if to == "checkout":
                con.execute(
                    "UPDATE bot SET last_task = COALESCE(current_task, last_task),"
                    " current_task = NULL WHERE bot_id = ?", (args.bot_id,))
            elif to == "checkin":
                con.execute(
                    "UPDATE bot SET last_task = COALESCE(current_task, last_task),"
                    " current_task = NULL WHERE bot_id = ?", (args.bot_id,))
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


def cmd_career(args) -> int:
    """career 전이 (prj3#Issue481) — 규칙 검증 후 반영. **판정은 하지 않는다.**

    승격 요건·유휴 임계 판정은 HR 게이트가 소유한다(`register`↔`hire` 와 동형 분리).
    사람이 직접 부르는 경로이기도 하므로 상비 role 보호는 여기서 건다.
    """
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            moved = apply_career(con, args.bot_id, validate_career(args.to))
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({
            "ok": True, "action": "career", **moved,
            "reason": args.reason or "(사유 미기재)",
            "bot": row_to_dict(fetch_bot(con, args.bot_id)),
        })
    finally:
        con.close()
    return 0


def cmd_heartbeat(args) -> int:
    """lease_expires = now + TTL 갱신. TTL 은 policy.yml 이 SSOT.

    대상 지정은 둘 중 하나다:

    * ``--bot-id``     — tmux 위임 경로. ``FBOT_ID`` env 로 자기 봇을 아는 형태.
    * ``--session-id`` — Agent 형태. **그 세션에 결속된 생존 봇 전부**를 갱신한다.

    ⚠️ 왜 세션 단위로 "전부" 인가 (Issue449 실측) — Agent 의 ``session_id`` 는 메인 세션과
    **같다**. 즉 session→bot 은 원리적으로 1:N 이며, 하나를 고르는 순간 그것이 곧 오귀속이다.
    heartbeat 는 신원 귀속이 아니라 **생존 신호**이므로, 고르지 않고 결속된 집합 전체를
    갱신하는 것이 정직하다. 신원이 필요한 자리(``whois``)는 반대로 모호하면 ``unknown``
    을 낸다 — 같은 사실을 용도에 맞게 반대 방향으로 처리하는 것이다.
    """
    if not args.bot_id and not args.session_id:
        raise FbotError("--bot-id 또는 --session-id 중 하나는 필요하다")
    ttl = lease_ttl_secs()
    now = int(time.time())
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            if args.bot_id:
                row = fetch_bot(con, args.bot_id)
                if row["state"] == "checkout":
                    raise FbotError(
                        f"퇴근한 봇에는 heartbeat 를 걸 수 없다: {args.bot_id} "
                        "— transition --to checkin 으로 재출근이 먼저다"
                    )
                targets = [args.bot_id]
            else:
                # 퇴근한 봇은 제외한다 — 세션에 결속 기록만 남은 과거 봇을 되살리지 않는다.
                targets = [
                    r["bot_id"] for r in con.execute(
                        "SELECT bot_id FROM bot WHERE session_id = ? AND state != 'checkout'",
                        (args.session_id,),
                    ).fetchall()
                ]
            for bid in targets:
                con.execute(
                    "UPDATE bot SET lease_expires = ? WHERE bot_id = ?", (now + ttl, bid)
                )
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({
            "ok": True, "action": "heartbeat", "bot_id": args.bot_id,
            "session_id": args.session_id, "renewed": targets,
            "now": now, "lease_ttl_secs": ttl, "lease_expires": now + ttl,
        })
    finally:
        con.close()
    return 0


def cmd_reap(args) -> int:
    """lease 만료 봇 스캔 → 강제 퇴근. 기본 dry-run, --apply 로 실제 적용.

    계약 §상태 기계: 크래시한 봇이 "작업중"으로 영원히 남지 않게 lease 만료 시 강제 퇴근한다.
    회수 경로는 s1 plan 확정대로 maint(s0 상주 스케줄러)가 본 서브커맨드를 부른다.

    **배분 원장 동반 종결 (Issue495 ⓒ)** — 봇만 퇴근시키고 원장을 두면 그 배분은 영원히
    `open` 이다. 완료 판정(`fbot-taskmgr.py detect_completions`)은 퇴근한 봇의 **작업 기록**
    을 요구하는데, 강제 퇴근된 봇은 정의상 그 기록을 남길 기회가 없었기 때문이다. 그렇게
    남은 `open` 은 ① 조직도에 "유실 배분" 경보로 영구 노출되고 ② 작업핀봇의 WIP 슬롯
    (실측 상한 3)을 영구 점유해 **조직 전체의 배분을 막는다**. 2026-08-31 실측이 정확히
    그것이었다 — Agent 형태 3건이 슬롯 3칸을 다 먹어 새 배분이 전부 거절됐다.

    ⚠️ 종결 status 는 `done` 이 아니라 `reaped` 다. 여기서 아는 것은 *"lease 가 만료됐다"*
    뿐이고 *"일이 끝났다"* 가 아니다. 완료로 적으면 원장이 거짓말을 한다. 정상 완료는
    퇴근 훅이 남긴 기록으로 sweep 이 `done` 을 찍는 것이 정규 경로이며, 이쪽은 그 경로가
    실패했을 때만 도는 **마지막 방벽**이다.
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

        # 각 만료 봇이 물고 있는 미종결 배분 — dry-run 에서도 보여야 판단이 된다.
        for e in expired:
            e["open_dispatches"] = [
                r["id"] for r in con.execute(
                    "SELECT id, payload FROM job WHERE kind = ? AND status = 'open'",
                    (DISPATCH_KIND,),
                ).fetchall()
                if _dispatch_worker(r["payload"]) == e["bot_id"]
            ]

        reaped, closed = [], []
        if args.apply and expired:
            con.execute("BEGIN IMMEDIATE")
            try:
                for e in expired:
                    # 강제 퇴근은 전 상태에서 허용되는 전이다(계약 §상태 기계 퇴근 진입 조건)
                    validate_transition(e["state"], "checkout")
                    con.execute(
                        "UPDATE bot SET state = 'checkout',"
                        " last_task = COALESCE(current_task, last_task), current_task = NULL"
                        " WHERE bot_id = ?", (e["bot_id"],)
                    )
                    reaped.append(e["bot_id"])
                    for job_id in e["open_dispatches"]:
                        con.execute(
                            "UPDATE job SET status = ?, result = ?"
                            " WHERE id = ? AND status = 'open'",
                            (DISPATCH_REAPED,
                             json.dumps({"verdict": "reaped",
                                         "reason": "워커 lease 만료로 강제 퇴근 — 완료 여부 미상",
                                         "worker_bot_id": e["bot_id"],
                                         "overdue_secs": e["overdue_secs"],
                                         "reaped_at": now}, ensure_ascii=False),
                             job_id),
                        )
                        closed.append(job_id)
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
            "dispatches_closed": closed,
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


def sid_marker_path(session_id: str) -> str:
    """세션 id → bot_id 마커 파일 경로.

    heartbeat 훅의 **무비용 게이트**다 — "이 세션에 봇이 하나라도 결속돼 있는가" 를 파일
    존재만으로 답한다. DB 를 매 도구 호출마다 열 수는 없다(hook-rules 규칙3).

    ⚠️ Issue449 — 내용(bot_id)은 **권위가 아니다**. Agent 는 메인 세션의 session_id 를
    공유하므로 한 세션에 봇이 여럿 결속될 수 있고, 이 파일은 마지막 1건만 담는다.
    그래서 heartbeat 훅은 이 값을 쓰지 않고 `heartbeat --session-id` 로 넘긴다 —
    갱신 대상 판정은 DB 가 단일 지점이다. 내용은 진단용으로만 남긴다.
    """
    return os.path.join(
        os.path.expanduser("~"), ".claude", ".fbot-handoff", f"sid-{session_id}.id"
    )


def write_sid_marker(session_id: str, bot_id: str) -> None:
    if not session_id:
        return
    path = sid_marker_path(session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(bot_id + "\n")
    except OSError:
        pass  # 마커는 캐시다 — 실패해도 DB 결속은 유효하다


def cmd_bind(args) -> int:
    """실행 형태(pane·세션)를 봇 레코드에 결속한다 (Issue448 ②).

    ⚠️ 값이 없으면 **NULL 을 유지**하고 오류를 내지 않는다. Agent(서브에이전트) 실행
    형태는 tmux pane 이 원래 없기 때문이다. NULL 은 "미등록" 이 아니라 "pane 기반
    판정 불가" 다 — 소비처는 이 둘을 반드시 구분해야 한다.
    """
    form = validate_form(getattr(args, "form", None))
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            fetch_bot(con, args.bot_id)          # 미등록이면 fail-loud
            sets, params = [], []
            if args.tmux_target is not None:
                sets.append("tmux_target = ?"); params.append(args.tmux_target or None)
            if args.session_id is not None:
                sets.append("session_id = ?"); params.append(args.session_id or None)
            if form is not None:
                # Issue495 — 결속 시점이 형태를 **확정**하는 자리다. PreToolUse(`Agent`)
                #   훅이 부르면 그 봇은 Agent 형태이고, 그 사실은 여기서만 알 수 있다.
                sets.append("form = ?"); params.append(form)
            if sets:
                params.append(args.bot_id)
                con.execute(f"UPDATE bot SET {', '.join(sets)} WHERE bot_id = ?", params)
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        if args.session_id:
            write_sid_marker(args.session_id, args.bot_id)
        emit({"ok": True, "action": "bind", "bot": row_to_dict(fetch_bot(con, args.bot_id))})
    finally:
        con.close()
    return 0


def cmd_whois(args) -> int:
    """역조회 — "이 pane / 이 세션의 봇은 누구인가" (Issue448 ③).

    Issue445 의 3값 판정이 이것을 소비한다. 반환 verdict 는 **2값이 아니라 3값**이다:

    * ``bot``     — 결속된 등록 봇이 있고 퇴근 상태가 아니다
    * ``retired`` — 결속된 봇이 있으나 이미 퇴근했다
    * ``unknown`` — 결속 기록이 없다. **"봇이 아니다" 가 아니라 "모른다"** 이다.
                    Agent 형태 봇은 pane 이 없어 pane 조회로는 항상 unknown 이 된다.
    """
    if not args.pane and not args.session_id:
        raise FbotError("--pane 또는 --session-id 중 하나는 필요하다")
    con = connect()
    try:
        row = None
        if args.pane:
            row = con.execute(
                "SELECT * FROM bot WHERE tmux_target = ? ORDER BY created_at DESC LIMIT 1",
                (args.pane,),
            ).fetchone()
        if row is None and args.session_id:
            # ⚠️ Issue449 — session_id 는 **per-agent 키가 아니다**. Agent 는 메인 세션의
            #   session_id 를 그대로 쓰므로 한 세션에 봇이 여럿 결속될 수 있다. 종전 구현은
            #   `ORDER BY created_at DESC LIMIT 1` 로 **조용히 하나를 골랐다** — 그것이 오귀속이다.
            #   결속이 2건 이상이면 고르지 않고 `unknown`(= 게이트 경유)을 낸다. fail-closed.
            rows = con.execute(
                "SELECT * FROM bot WHERE session_id = ? AND state != 'checkout'"
                " ORDER BY created_at DESC",
                (args.session_id,),
            ).fetchall()
            if len(rows) > 1:
                emit({
                    "ok": True, "action": "whois", "verdict": "unknown", "bot": None,
                    "candidates": [r["bot_id"] for r in rows],
                    "note": "세션 중복 결속 — Agent 는 메인 세션 id 를 공유한다(Issue449). "
                            "세션만으로는 신원을 특정할 수 없어 고르지 않는다",
                })
                return 0
            if rows:
                row = rows[0]
            else:
                # 생존 봇이 없으면 퇴근분까지 본다 — 'retired' 를 낼 수 있어야 한다.
                row = con.execute(
                    "SELECT * FROM bot WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                    (args.session_id,),
                ).fetchone()
        if row is None:
            emit({
                "ok": True, "action": "whois", "verdict": "unknown", "bot": None,
                "note": "결속 기록 없음 — '봇이 아님' 이 아니라 'pane/세션 기반 판정 불가'",
            })
            return 0
        d = row_to_dict(row)
        emit({
            "ok": True, "action": "whois",
            "verdict": "retired" if d["state"] == "checkout" else "bot",
            "bot": d,
        })
    finally:
        con.close()
    return 0


# ── 배분 원장 사후 기록 (prj1#Issue445) ─────────────────────────────────────

DISPATCH_KIND = "fbot_dispatch"       # 조직도·작업핀봇이 공용하는 배분 원장 kind
# 사후 기록 전용 status — `open` 을 쓰지 않는 근거는 cmd_dispatch_record 참조.
DISPATCH_LOGGED = "logged"


def norm_issue(text: str) -> str:
    """이슈 표기 정규화 — 중복 기록 판정에만 쓴다.

    같은 배분을 작업핀봇은 ``Issue335`` 로, fpm-do 는 ``prj42#Issue335`` 로 부른다.
    문자열을 그대로 비교하면 같은 사건이 원장에 두 줄이 되어 "배분 2회" 라는 거짓말이 된다.
    """
    t = (text or "").strip().lower()
    m = re.findall(r"issue[_-]?(\d+(?:_\d+)*)", t)
    return "issue" + m[-1] if m else t


def cmd_dispatch_record(args) -> int:
    """**이미 집행된** 배분을 원장에 사후 기록한다 (prj1#Issue445).

    왜 필요한가 — 배분 원장(``job.kind='fbot_dispatch'``)에 쓰는 주체가 작업핀봇
    (`fbot-taskmgr.py dispatch`) **하나뿐**이라, 조직이 가장 많이 쓰는 경로인 ``fpm-do``
    직접 위임이 원장을 통째로 비켜갔다. 실측(2026-08-31) 배분 엣지 11건이 전부
    작업핀봇 소유였고 중역핀봇은 **0건** — 조직도에서 중역핀봇 밑이 채용 실선만으로
    그려진 것이 이 결손의 표면이다.

    🔴 **여기에 상한 판정을 두지 않는다.** 이 명령이 기록하는 것은 *일어날 일* 이 아니라
    *이미 일어난 일* 이다. 상한으로 거절하면 배분은 그대로 일어나고 **기록만 사라져**
    지금 고치려는 결손이 그대로 재발한다. 승인 게이트는 스폰 직전(HR 게이트)에 있고,
    판정 지점은 하나여야 한다.

    🔴 **status 는 ``open`` 이 아니라 ``logged``** 다. ``open`` 은 작업핀봇의 **WIP 슬롯**
    (`fbot_dispatch_concurrent_limit`, 실측 3)을 점유하는 값이다. 사후 기록이 그 슬롯을
    먹으면 fpm-do 위임 3건만으로 작업핀봇 배분이 통째로 막힌다 — 관측을 고치려다 조직을
    세우는 셈이다. ``logged`` 는 조직도(배분 엣지·원장 표)에는 그대로 보이면서 WIP·완료
    감지 질의(둘 다 ``open`` 필터)에는 걸리지 않는다.

    배분자(owner) 해소 순서 — ① ``--by`` 명시 ② 대상 봇의 ``parent_bot_id``(채용 사슬이
    곧 지시 계통이다) ③ 둘 다 없으면 **기록하지 않고 정상 종료**. ③ 은 루트 봇이 자기
    주도로 위임한 경우라 지시 관계 자체가 없다 — 오류가 아니다. 반면 지목된 봇이
    레지스트리에 없으면(대상·배분자 모두) fail-loud 다.
    """
    con = connect()
    try:
        worker = fetch_bot(con, args.worker)          # 미등록 대상이면 fail-loud
        owner = args.by or (worker["parent_bot_id"] or "")
        if not owner:
            # ⚠️ 이것은 **오류가 아니다.** 루트 봇(부모 없음)이 자기 주도로 위임한 경우이며,
            #   그때는 지시 관계 자체가 없다. 출발지 없는 배분 엣지는 조직도에서 거짓말이
            #   되므로 **기록하지 않는 것**이 정답이고, 정상 상태를 에러로 만들면 호출측
            #   (fpm-do)이 매 위임마다 무의미한 경고를 뱉는다.
            emit({"ok": True, "action": "dispatch-record", "recorded": False,
                  "reason": "배분자 미상 — 대상의 parent_bot_id 가 없고 --by 도 없다"
                            "(루트 봇의 자기 주도 위임 = 지시 관계 아님)",
                  "worker_bot_id": args.worker, "issue": args.issue or ""})
            return 0
        fetch_bot(con, owner)                          # 유령 배분자는 fail-loud
        key = norm_issue(args.issue or "")

        # 중복 기록 방지 — 작업핀봇이 배분(open)하고 fpm-do 가 스폰하는 정상 경로에서
        #   같은 사건이 두 줄이 되면 안 된다. 원장은 작아서(실측 12행) 전건 스캔으로 족하다.
        for r in con.execute(
                "SELECT id, payload, status FROM job WHERE kind = ? AND owner = ?"
                " AND status != 'cancelled'", (DISPATCH_KIND, owner)).fetchall():
            try:
                pl = json.loads(r["payload"] or "{}")
            except (ValueError, TypeError):
                continue
            if pl.get("worker_bot_id") == args.worker and norm_issue(pl.get("issue") or "") == key:
                emit({"ok": True, "action": "dispatch-record", "recorded": False,
                      "reason": "이미 원장에 있는 배분 — 중복 기록하지 않는다",
                      "job_id": r["id"], "status": r["status"],
                      "owner": owner, "worker_bot_id": args.worker, "issue": args.issue or ""})
                return 0

        now = int(time.time())
        job_id = f"fbotdisp-{now}-{uuid.uuid4().hex[:8]}"
        payload = {
            "issue": args.issue or "", "role": worker["role"] or "",
            "worker_bot_id": args.worker, "cwd": args.cwd or "",
            "prj": args.prj,
            # 어느 경로로 들어온 기록인지 — 원장 소비처가 사후 기록과 정규 배분을
            #   구분해야 할 때의 유일한 단서다.
            "source": args.source or "fpm-do",
        }
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute(
                "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
                " owner, lease_until, blocked_since, created_at)"
                " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
                (job_id, "fbot", DISPATCH_KIND, DISPATCH_LOGGED,
                 json.dumps(payload, ensure_ascii=False), owner, now),
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({"ok": True, "action": "dispatch-record", "recorded": True,
              "job_id": job_id, "status": DISPATCH_LOGGED,
              "owner": owner, "worker_bot_id": args.worker,
              "issue": args.issue or "", "payload": payload})
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
    sp.add_argument("--tmux-target", default=None, help="tmux 'session:window.pane' (없으면 NULL)")
    sp.add_argument("--session-id", default=None, help="claude 세션 id (없으면 NULL)")
    sp.add_argument("--form", default=None, choices=FORMS,
                    help="실행 형태 (없으면 NULL=미판정 — bind 시점에 확정된다)")
    sp.set_defaults(func=cmd_register)

    sp = sub.add_parser("transition", help="전이 규칙 검증 후 상태 변경(+lease 갱신)")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--to", required=True, help=f"{'|'.join(STATES)}")
    sp.set_defaults(func=cmd_transition)

    sp = sub.add_parser("career", help="career 전이(수습·정식·휴직·해고) — 규칙 검증만, 판정 없음")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--to", required=True, help=f"{'|'.join(CAREERS)}")
    sp.add_argument("--reason", default=None, help="전이 사유(감사 기록용)")
    sp.set_defaults(func=cmd_career)

    sp = sub.add_parser("heartbeat", help="lease_expires = now + TTL 갱신")
    sp.add_argument("--bot-id", default=None)
    sp.add_argument("--session-id", default=None,
                    help="그 세션에 결속된 생존 봇 전부를 갱신 — Agent 형태(Issue449)")
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

    sp = sub.add_parser("bind", help="실행 형태(pane·세션) 결속 기록 — Issue448")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--tmux-target", default=None, help="빈 문자열이면 NULL 로 지운다")
    sp.add_argument("--session-id", default=None, help="빈 문자열이면 NULL 로 지운다")
    sp.add_argument("--form", default=None, choices=FORMS,
                    help="실행 형태 확정 — Agent 훅이 'agent' 를 찍는다 (Issue495)")
    sp.set_defaults(func=cmd_bind)

    sp = sub.add_parser("whois", help="pane·세션 → 봇 역조회(3값 verdict) — Issue448")
    sp.add_argument("--pane", default=None, help="tmux 'session:window.pane'")
    sp.add_argument("--session-id", default=None)
    sp.set_defaults(func=cmd_whois)

    sp = sub.add_parser("dispatch-record",
                        help="이미 집행된 배분을 원장에 사후 기록 — prj1#Issue445 (상한 미판정)")
    sp.add_argument("--worker", required=True, help="배분 대상 bot_id(등록돼 있어야 한다)")
    sp.add_argument("--by", default=None,
                    help="배분자 bot_id. 생략 시 대상의 parent_bot_id 를 쓴다")
    sp.add_argument("--issue", default=None, help="이슈 표기(ex: prj42#Issue335)")
    sp.add_argument("--prj", type=int, default=None, help="배분된 일의 prj 번호")
    sp.add_argument("--cwd", default=None, help="배분 대상 작업 경로")
    sp.add_argument("--source", default="fpm-do", help="기록 유입 경로(기본 fpm-do)")
    sp.set_defaults(func=cmd_dispatch_record)

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
