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
import contextlib
import glob
import io
import json
import os
import re
import subprocess
import shutil
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
# prj3#Issue551 — career 를 두 축으로 가른다. career 컬럼은 **호환용 사영**(소비처 95지점)으로
#   남기고 두 축에서 항상 같이 쓴다(write-through). 읽기 정본은 grade·employment.
#   career = employment if employment in (leave, terminated) else grade   ← suspended 는 career 에
#   대응값이 없어 grade 로 보인다(제재는 employment 축에서만 보인다 — 조직도·HR 은 그쪽을 본다).
GRADES = ("probation", "active")
EMPLOYMENTS = ("employed", "suspended", "leave", "terminated")
EMPLOYMENT_LABEL = {"employed": "재직", "suspended": "정직", "leave": "휴직", "terminated": "해고"}
EMPLOYMENT_TRANSITIONS = {
    "employed": {"suspended", "leave"},
    "suspended": {"employed", "leave"},        # 정직은 되돌릴 수 있다 — 해고 앞의 되돌릴 수 있는 단계
    "leave": {"employed", "terminated"},        # 해고는 휴직 경유 필수(기존 규약 유지)
    "terminated": set(),
}


def split_career(career: str):
    """career(호환 사영) → (grade, employment) 기본 매핑 — 마이그레이션·백필 전용."""
    if career in ("leave", "terminated"):
        return ("active", career)      # 등급 정보가 없으면 정식으로 본다(수습 휴직은 grade 보존 컬럼이 답한다)
    return (career or "probation", "employed")


def project_career(grade: str, employment: str) -> str:
    return employment if employment in ("leave", "terminated") else (grade or "probation")


CAREER_TRANSITIONS = {
    "probation": {"active", "leave"},
    "active": {"leave"},
    "leave": {"active", "terminated"},
    "terminated": set(),
}

# 상비 role (계약 §조직 4종) — 상비봇 판정의 **필요조건**. 본 파일이 이 값의 SSOT 다.
#   ⚠️ role 만으로는 부족하다 — `is_core_bot()` 이 `parent_bot_id IS NULL` 까지 본다.
#      `fbot-chief-issue331`(role=chief, parent=fbot-lead)은 이슈 워커이지 총괄이 아니다.
#   ⚠️ 이 가드는 **기록 계층**에 둔다. "이 봇은 해고 불가" 는 상황 판정이 아니라 불변
#      제약이므로, 판정 계층(HR 게이트)을 우회한 어떤 경로로 와도 막혀야 한다.
CORE_ROLES = ("chief", "scout", "hr", "lead")

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
    ("last_active_at", "INT"), # 마지막 활동 epoch — heartbeat·transition·set-task 가 갱신 (prj3#Issue569, 관제 UI 경과 시간)
    ("grade", "TEXT"),         # 등급 축 probation|active (prj3#Issue551) — career 에서 분리
    ("employment", "TEXT"),    # 재직 축 employed|suspended|leave|terminated (prj3#Issue551)
    ("current_issue", "TEXT"),    # prj3#Issue739 M1-4 — `set-task --issue` 구조 필드(NULL = 미지정). 담당 판정 원천 아님
    ("current_task_ref", "TEXT"), # prj3#Issue739 M1-4 — `set-task --task-ref <경로#앵커>` · 미종결 배분 payload.task_ref 로 전사
    ("seat_id", "TEXT"),       # 조직도 자리 결속 (Issue538) — `{dept}-{role}-{n}` 형식.
                               #   NULL 은 **미배치**이지 오류가 아니다. 자리(선언)와 개체(대장)를
                               #   가르는 것이 조직도 전환의 핵심이라, 개체가 자리 없이 존재할 수
                               #   있다. 조직도는 NULL 인 봇을 `미배치` 구역에 렌더한다(계약 4).
                               #   ⚠️ 기록 귀속은 여전히 bot_id 다 — job 레코드에 넣지 않는다.
)

# `job.owner` → `owner_kind`/`owner_id` 유도 규칙 **SSOT** (Issue516).
#   트리거 2개·백필이 전부 이 두 식을 쓴다. 갈라지는 순간 원장이 거짓이 되므로 복제 금지.
#   `{t}` 에는 트리거면 `NEW`, 백필이면 `job` 이 들어간다.
#   prj3#Issue863_2 — `sel%`(선택 기록 sel_event)는 owner 가 없는 비봇 기록이라 `none`. 이 분기가 없으면 lock 으로 오표기된다.
JOB_OWNER_KIND_EXPR = ("CASE WHEN {t}.kind LIKE 'fbot%' THEN 'bot' "
                       "WHEN {t}.kind LIKE 'sel%' THEN 'none' ELSE 'lock' END")
JOB_OWNER_ID_EXPR = "CASE WHEN {t}.kind LIKE 'fbot%' THEN {t}.owner ELSE NULL END"

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
# reap 이 **이슈 미완료** 배분에 다는 사망 표지 (prj3#Issue788_2) — `reaped`(terminal)로 굳히면 재배분 경로가 없다.
#   회수(fbot-lead `_reclaim_action`)가 쓰는 `blocked(worker_died)` 와 같은 상태다(소비처 한 벌).
DISPATCH_DIED_BY = "worker_died"
_LEAD_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-lead.py")
_LEAD_MOD = None

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


def human_session_rejection(env=None) -> str:
    """사람 세션 전용 명령의 공통 판정 — 거부 사유, 사람이면 빈 문자열.

    Issue830 — ``solo-approve`` 와 권한 경계 매뉴얼 ``apply`` 가 같은 경계를 쓴다.
    ``FBOT_ID`` 뿐 아니라 세션 결속·살아 있는 하청 슬롯도 봇 실행 주체이므로 거부한다.
    """
    env = os.environ if env is None else env
    if env.get("FBOT_ID"):
        return "사람 세션 전용이다 — 봇(FBOT_ID=%s)은 승인할 수 없다" % env["FBOT_ID"]
    sid = env.get("CLAUDE_CODE_SESSION_ID", "")
    if not sid:
        return ""
    ident = _ident_mod()
    base = ident.handoff_dir(env)
    if ident.session_slot_bot(env) or os.path.exists(ident.sid_marker_path(sid, env=env)):
        return "이 세션은 봇에 결속돼 있다"
    bots = []
    for path in glob.glob(os.path.join(base, "sid-%s.agent-*.id" % sid)):
        try:
            bot_id = open(path, encoding="utf-8").read().strip()
        except OSError:
            continue
        if bot_id:
            bots.append(bot_id)
    if not bots:
        return ""
    con = sqlite3.connect(registry_path())
    try:
        live = [row[0] for row in con.execute(
            "SELECT bot_id FROM bot WHERE bot_id IN (%s) AND state <> 'checkout'"
            % ",".join("?" for _ in bots), bots).fetchall()]
    finally:
        con.close()
    if live:
        return "이 세션에 살아 있는 하청 봇(%s)이 있다 — 하청이 끝난 뒤 다시" % ", ".join(live)
    return ""


def idle_ttl_secs() -> int:
    """수신대기(waiting_input) 봇의 reap 유예 — policy `idle_ttl_secs`, 부재 시 7200 (prj3#Issue554).

    유휴(사용자 입력 대기)는 사망이 아니다. lease 는 hook 이벤트에서만 갱신되므로 사용자를
    기다리는 결속 세션은 5분이면 lease 가 끝난다 — 그 순간 타 세션이 `dead` 로 축출했다
    (2026-09-06 실측). 그렇다고 무한 유예하면 크래시한 세션이 영영 남는다. 두 시간 뒤엔 퇴근이다."""
    path = _policy_path()     # lease_ttl_secs 와 같은 해석 (prj3#Issue626 폴백 포함)
    if not os.path.exists(path):
        return 7200
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^idle_ttl_secs:\s*(\d+)", line)
            if m:
                return int(m.group(1))
    return 7200


def _policy_path() -> str:
    """policy.yml 해소 — prj3#Issue626.

    **정책 수치의 정본은 prj3** 다. 데이터(registry.db·learn.db)는 용량 때문에 prj5 에
    남지만(zshenv 명시 결정) 수치는 prj3 소관이다. 폴백 **순서가 핵심**이다:
      ⓐ `aoa_dir()` 에 있으면 그것 — 테스트가 픽스처에 쓴 policy 를 계속 읽는다
      ⓑ 없으면 prj3 — 운영에서는 prj5 사본을 걷었으므로 여기로 온다
    뒤집으면 테스트가 운영 policy 를 읽어 픽스처가 무력해진다.
    """
    path = os.path.join(aoa_dir(), "policy.yml")
    if os.path.exists(path):
        return path
    # ⓒ prj3#Issue696 — 그것도 없으면 배포 기본값 policy_org.yml
    for _name in ("policy.yml", "policy_org.yml"):
        p3 = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa", _name)
        if os.path.exists(p3):
            return p3
    return path


def lease_ttl_secs() -> int:
    """lease TTL 은 aoa policy.yml 의 lease_ttl_secs 가 SSOT — 하드코딩 금지.

    policy.yml 은 평탄(top-level) 키 구조라 정규식 한 줄로 충분하다. PyYAML 의존을 만들지 않는다.
    """
    path = _policy_path()
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


# ── 이벤트 원장 (prj3#Issue575) ────────────────────────────────────────────────
# 상태 컬럼은 *지금* 만 말한다. 알림·실시간·타임라인은 *언제 바뀌었나* 를 요구하므로 전이 지점이
# `job.kind='fbot_event'` 한 행을 남긴다(F4 — 모든 기록은 원장, bot_id 귀속; 별도 테이블 금지).
# hub 에는 best-effort 로 알린다 — hub 가 죽어도 봇은 산다(0.3초 타임아웃, 실패 무시).
HUB_EVENT_URL = os.environ.get("FBOT_HUB_EVENT_URL") or "http://127.0.0.1:9876/fbot-event"


def body_stamp(env=None) -> dict:
    """관리 행위 기록에 싣는 **몸체 도장** (prj3#Issue757 T15 ⑥) — «어느 몸체가 시켰나» 가 원장에 남는다.
    env 세션(`CLAUDE_CODE_SESSION_ID`)·흐름(`FBOT_FLOW`)이 있을 때만 키를 싣는다(없으면 종전 형태)."""
    env = os.environ if env is None else env
    out = {}
    if env.get("CLAUDE_CODE_SESSION_ID"):
        out["by_session"] = env["CLAUDE_CODE_SESSION_ID"]
    if env.get("FBOT_FLOW"):
        out["by_flow"] = env["FBOT_FLOW"]
    return out


def record_event(con: sqlite3.Connection, bot_id: str, etype: str, detail: str = "", ref: str = "") -> str:
    """전이 1건 → `fbot_event` 1행 (같은 커넥션·같은 트랜잭션). 반환 id. 실패는 조용히 "" — 기록이 본 작업을 막지 않는다."""
    now = int(time.time())
    eid = f"fbotev-{now}-{uuid.uuid4().hex[:8]}"
    try:
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts, owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (eid, "fbot", "fbot_event", "done",
             json.dumps({"type": etype, "detail": (detail or "")[:300], "ref": ref or "", **body_stamp()},
                        ensure_ascii=False),
             bot_id, now))
    except sqlite3.Error:
        return ""
    return eid


def notify_hub_event(bot_id: str, etype: str, ref: str = "") -> None:
    """hub SSE 발행 — best-effort. 원장 커밋 **뒤** 에 부른다(커밋 전에 알리면 보드가 빈 원장을 읽는다)."""
    if os.environ.get("FBOT_HUB_EVENT_URL") == "off":
        return
    try:
        import urllib.request
        body = json.dumps({"bot": bot_id, "type": etype, "ref": ref}).encode("utf-8")
        req = urllib.request.Request(HUB_EVENT_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=0.3).read()
    except Exception:
        pass


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
    # prj3#Issue551 — 두 축 백필: career 만 있는 행을 (grade, employment) 로 채운다(멱등)
    for row in con.execute("SELECT bot_id, career FROM bot WHERE grade IS NULL OR employment IS NULL").fetchall():
        g, e = split_career(row[1] or "")
        con.execute("UPDATE bot SET grade = COALESCE(grade, ?), employment = COALESCE(employment, ?)"
                    " WHERE bot_id = ?", (g, e, row[0]))
    _ensure_job_owner_split(con)
    _ensure_job_owner_fk(con)      # Issue527 — 축이 갈린 뒤에야 걸 수 있다. 순서 고정


def _ensure_job_owner_split(con: sqlite3.Connection) -> None:
    """`job.owner` 다형성 해소 (Issue516) — 멱등. FK 를 걸 수 있는 형태로 축을 가른다.

    같은 컬럼에 두 종류가 섞여 있어 FK 를 걸 수 없었다 — 봇 소유(``fbot-<id>``)와
    락 소유(``<host>/<PID>``). 2026-09-03 실측: lock 492건(전부 ``kind='consolidation'``)
    · bot 30건(전부 ``kind='fbot_*'``)으로 **교집합이 0** 이고 ``kind`` 가 종류를 100%
    결정한다. 즉 새 값을 만드는 게 아니라 **드러내는** 작업이다.

    🔑 **이중 쓰기를 코드에 넣지 않고 트리거로 유도한다.** 소비처가 17파일·42지점이라
    쓰기 지점마다 두 컬럼을 채우게 하면 **한 곳만 빠뜨려도 NULL 이 남고**, 그 상태에서
    FK 나 fencing 을 걸면 조용히 통과한다. 트리거는 빠뜨릴 자리가 없다.

    안전 근거 3가지 (착수 전 실측):
      * **fencing 무손상** — ``WHERE id=? AND owner=?`` (worker.py:545·662)는 ``owner``
        컬럼을 **그대로 두므로** 영향이 없다. 새 컬럼은 읽기 축일 뿐이다
      * **위치기반 INSERT 없음** — 모든 ``INSERT INTO job`` 이 명시 컬럼형이고,
        ``SELECT *`` 2곳(lead)은 ``sqlite3.Row`` → ``dict(r)`` 키 접근이다
      * **판정원 오염 없음** — hr-gate 는 이미 ``kind IN (...)`` 로 거른다
    """
    have = {r[1] for r in con.execute("PRAGMA table_info(job)").fetchall()}
    for name in ("owner_kind", "owner_id"):
        if name not in have:
            con.execute(f"ALTER TABLE job ADD COLUMN {name} TEXT")

    _create_job_owner_triggers(con)
    _backfill_job_owner(con)


def _backfill_job_owner(con: sqlite3.Connection) -> None:
    """백필 — 미채움(NULL)과 **유도식이 바뀌어 어긋난 행**을 다시 유도한다(멱등 · 어긋난 행만 쓴다).

    미채움이 남으면 FK·감사가 그 행을 조용히 통과시킨다(Issue516 기존 522행). 유도식에 분기가 늘면(prj3#Issue863_2 `sel%` → none)
    이미 lock 으로 채워진 행도 고쳐야 원장이 한 식을 따른다 — 별도 일회성 UPDATE 를 두지 않고 이 백필이 맡는다."""
    con.execute(f"""
        UPDATE job SET owner_kind = {JOB_OWNER_KIND_EXPR.format(t='job')},
                       owner_id   = {JOB_OWNER_ID_EXPR.format(t='job')}
         WHERE owner_kind IS NULL OR owner_kind IS NOT ({JOB_OWNER_KIND_EXPR.format(t='job')})""")


def _create_job_owner_triggers(con: sqlite3.Connection) -> None:
    """`owner` → `owner_kind`/`owner_id` 유도 트리거 2개를 (재)생성한다 — 멱등.

    ⚠️ **`job` 테이블을 재작성하면 트리거도 함께 사라진다**(SQLite 는 DROP TABLE 시 그
    테이블의 트리거를 같이 지운다). Issue527 의 FK 선언이 재작성이므로, 생성 지점을
    함수로 뽑아 두 경로(Issue516 컬럼 분리 · Issue527 FK 재작성)가 **같은 DDL** 을 쓴다.
    복붙으로 두 벌을 두면 한쪽만 고쳐져 유도식이 갈리는 순간 원장이 거짓말을 시작한다.

    트리거는 AFTER INSERT / owner·kind 가 바뀌는 AFTER UPDATE 2개다. 재귀는 SQLite 기본
    ``recursive_triggers=OFF`` 로 차단되지만 그 설정에 기대지 않고, UPDATE 트리거를
    ``OF owner, kind`` 로 좁혀 자기 UPDATE(owner_kind/owner_id)를 안 탄다.
    """
    # prj3#Issue876 — 연결마다 도는 (재)생성이라 DROP·CREATE 사이에 다른 프로세스가 끼면 «trigger already exists»(rc=2)
    #   로 터졌다 — 동시 출근의 bind 가 이걸로 죽으면 fail-soft 가 삼켜 둘 다 출근한다. 한 트랜잭션으로 묶는다
    #   (이미 트랜잭션 안 — Issue527 재작성 경로 — 이면 호출자 것에 합류)
    own = not con.in_transaction
    if own:
        con.execute("BEGIN IMMEDIATE")
    try:
        _recreate_job_owner_triggers(con)
    except Exception:
        if own:
            con.execute("ROLLBACK")
        raise
    if own:
        con.execute("COMMIT")


def _recreate_job_owner_triggers(con: sqlite3.Connection) -> None:
    con.execute("DROP TRIGGER IF EXISTS job_owner_split_ins")
    con.execute(f"""
        CREATE TRIGGER job_owner_split_ins AFTER INSERT ON job BEGIN
          UPDATE job SET owner_kind = {JOB_OWNER_KIND_EXPR.format(t='NEW')},
                         owner_id   = {JOB_OWNER_ID_EXPR.format(t='NEW')}
           WHERE id = NEW.id;
        END""")
    con.execute("DROP TRIGGER IF EXISTS job_owner_split_upd")
    con.execute(f"""
        CREATE TRIGGER job_owner_split_upd AFTER UPDATE OF owner, kind ON job BEGIN
          UPDATE job SET owner_kind = {JOB_OWNER_KIND_EXPR.format(t='NEW')},
                         owner_id   = {JOB_OWNER_ID_EXPR.format(t='NEW')}
           WHERE id = NEW.id;
        END""")


def _ensure_job_owner_fk(con: sqlite3.Connection) -> None:
    """`job.owner_id` → `bot.bot_id` FK 선언 (Issue527) — 멱등.

    [[Issue516]] 이 다형성을 풀어 **FK 를 걸 수 있는 상태**를 만들었고, 여기가 실제 선언이다.
    선언이 없으면 대장에서 봇을 지우는 순간 원장이 조용히 거짓말을 시작한다 —
    ``fbot-registry-audit.py`` 가 유일한 방어선인 상태가 계속된다.

    ⚠️ **STRICT 테이블에 ``ALTER TABLE ADD CONSTRAINT`` 가 없다.** SQLite 는 FK 추가에
    **테이블 재작성**(새 테이블 → 복사 → 드롭 → rename)을 요구한다. Issue516 의 멱등
    ``ADD COLUMN`` 과 달리 비가역 구간이 생기므로 아래를 지킨다:

      * 재작성 구간은 ``PRAGMA foreign_keys=OFF`` — 켜진 채로 ``DROP TABLE`` 하면 다른
        테이블의 참조가 걸리거나 rename 이 FK 를 따라 재작성된다. 끝나면 원래 값으로 되돌린다
        (pragma 는 **트랜잭션 안에서 no-op** 이므로 반드시 BEGIN 밖에서 켜고 끈다)
      * 착수 전 고아 0 을 확인한다 — 고아가 있으면 FK 가 그 행을 거부해 **기록을 잃는다**
      * 복사 후 행수 대조 · ``PRAGMA foreign_key_check`` 를 트랜잭션 안에서 하고,
        어긋나면 COMMIT 하지 않는다
      * 인덱스·트리거를 재작성 안에서 되살린다(DROP TABLE 이 같이 지운다)

    ``ON DELETE`` 는 **RESTRICT** 다. ``SET NULL`` 은 봇을 지우면 그 봇의 작업 기록이
    주인 없는 행으로 남는다 — 지금 고치는 실패와 같은 모양이다. 봇을 지우려면 그 기록을
    먼저 처리하게 만드는 쪽이 맞다. ``owner_id`` 는 **NULL 허용**이다(락 소유 행 492건이 NULL).
    """
    if con.execute("PRAGMA foreign_key_list(job)").fetchall():
        return                                  # 이미 선언돼 있다 — 멱등 탈출

    orphan = con.execute(
        "SELECT COUNT(*) FROM job j LEFT JOIN bot b ON j.owner_id = b.bot_id"
        " WHERE j.owner_id IS NOT NULL AND b.bot_id IS NULL").fetchone()[0]
    if orphan:
        raise FbotError(
            f"job.owner_id 고아 {orphan}건 — FK 를 걸면 그 기록을 잃는다. "
            "`fbot-registry-audit.py` 로 먼저 정합을 맞춘 뒤 다시 연결하라 (Issue527/Issue528)")

    cols = ("id, store, kind, status, payload, result, attempts, owner,"
            " lease_until, blocked_since, created_at, owner_kind, owner_id")
    before = con.execute("SELECT COUNT(*) FROM job").fetchone()[0]
    fk_was = con.execute("PRAGMA foreign_keys").fetchone()[0]
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("""
            CREATE TABLE job_new(
              id TEXT PRIMARY KEY, store TEXT, kind TEXT, status TEXT,
              payload TEXT, result TEXT, attempts INT,
              owner TEXT, lease_until INT, blocked_since INT, created_at INT,
              owner_kind TEXT,
              owner_id TEXT REFERENCES bot(bot_id) ON DELETE RESTRICT ON UPDATE CASCADE
            ) STRICT""")
        con.execute(f"INSERT INTO job_new ({cols}) SELECT {cols} FROM job")
        copied = con.execute("SELECT COUNT(*) FROM job_new").fetchone()[0]
        if copied != before:
            con.execute("ROLLBACK")
            raise FbotError(f"job 재작성 중단 — 복사 행수 불일치 {before}→{copied} (롤백함)")
        con.execute("DROP TABLE job")
        con.execute("ALTER TABLE job_new RENAME TO job")
        # DROP TABLE 이 같이 지운 것들을 되살린다.
        con.execute("CREATE INDEX IF NOT EXISTS job_status_idx ON job(status, created_at)")
        _create_job_owner_triggers(con)
        bad = con.execute("PRAGMA foreign_key_check(job)").fetchall()
        if bad:
            con.execute("ROLLBACK")
            raise FbotError(f"job 재작성 중단 — FK 위반 {len(bad)}건 (롤백함)")
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        con.execute("PRAGMA foreign_keys=%s" % ("ON" if fk_was else "OFF"))


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

    role 만 보면 과보호가 된다 — `fbot-exec-issue331`(role=chief, parent=fbot-lead)은
    팀장핀봇이 배치한 **이슈 워커**이지 총괄핀봇이 아니다. 그런 개체까지 영구 보호하면
    정작 정리 대상인 워커가 상비봇 행세를 하며 남는다.

    상비봇은 조직 골격이라 누가 채용한 것이 아니다 — 그래서 `parent_bot_id IS NULL` 이
    구조적 표지가 된다(실측: 상비 3종만 parent 가 비어 있다).
    """
    # prj3#Issue609 — ⚠️ **PM(taskmgr)은 예외다.** PM 은 조직 골격이지만 *채용으로* 생기므로
    #   `parent_bot_id` 가 **있는 것이 정상**이다. parent 없음만 보면 prj PM 이 상비 보호 밖으로
    #   떨어져 유휴하다는 이유로 휴직당한다(2026-09-09 실측: prj13·40·42·57 PM 4명이 `leave`).
    #   PM 은 프로젝트 **필수 전제**다(사용자 지시) — 없으면 그 prj 는 작업 자체가 불가능하다(Issue608).
    #   PM 의 구조적 표지는 parent 가 아니라 **조직 자리**다: prj 에 배치되고 seat 에 앉아 있는가.
    #   이슈 워커는 조직 선언의 자리를 받지 않으므로 이 조건으로 사칭할 수 없다.
    #   prj3#Issue614 — 위 조건은 **prj 축만** 챙기고 본사 축을 떨어뜨렸다. 전역 팀장핀봇
    #     `fbot-lead`(자리 `hq/hq-lead-1`·prj NULL·parent NULL)가 `core=False` 로 나와
    #     hub 카드에 「해고 검토 요청」이 남았다(2026-09-10 실측). 그 봇은 `fbot-lead.py`
    #     의 **기본 배분자**(`BOT_ID`)라 해고되면 배분 기본값이 대장에서 사라진다.
    #   그래서 lead 의 상비 표지는 **자리에 앉아 있음 + (prj 소속 또는 채용된 적 없음)** 둘 중 하나다.
    #     ⓐ prj PM  — prj 배치 + seat (채용으로 생기므로 parent 가 있는 것이 정상)
    #     ⓑ 본사 전역 — parent 없음 + seat (조직 골격이라 누가 채용한 것이 아니다)
    #   어느 쪽도 아닌 lead(= 자리 없이 배치된 이슈 워커)는 상비가 아니다 — 사칭 경로가 닫힌다.
    if row["role"] == "lead":
        if not row["seat_id"]:
            return False
        return row["prj"] is not None or row["parent_bot_id"] is None
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
    # prj3#Issue551 — 두 축에 같이 쓴다. 등급 전이(probation→active)는 grade 만, 재직 전이는 employment 만
    #   움직이고 career 는 사영이다. 등급은 보존된다(수습 휴직 → 복귀해도 여전히 수습).
    has_axes = "grade" in row.keys() and "employment" in row.keys()   # 구 스키마 픽스처 호환
    g_cur = (row["grade"] if has_axes else None) or split_career(cur)[0]
    if to in GRADES:
        g_new, e_new = to, "employed"
    else:
        g_new, e_new = g_cur, to
    lease_sql = ", lease_expires = NULL" if to == "leave" else ""
    if has_axes:
        con.execute(f"UPDATE bot SET career = ?, grade = ?, employment = ?{lease_sql} WHERE bot_id = ?",
                    (project_career(g_new, e_new), g_new, e_new, bot_id))
    else:
        con.execute(f"UPDATE bot SET career = ?{lease_sql} WHERE bot_id = ?", (to, bot_id))
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
    # prj3#Issue796 — 초기 state 는 둘뿐이다. 기본 checkin(세션 기동이 곧 출근 — 계약 진입 조건) ·
    #   몸체 없는 채용(총괄 staffing 생성)은 checkout(cold). 세션 없는 checkin 은 거짓 상태라 HR wake 가
    #   «이미 활동 중» 으로 거절해 팀장의 첫 배분이 lease 만료까지 교착했다(2026-09-29 prj55 실측).
    init_state = getattr(args, "state", None) or "checkin"
    if init_state not in ("checkin", "checkout"):
        raise FbotError(f"register 초기 state 는 checkin|checkout 만: {init_state!r} — 중간 상태로 태어나지 않는다")
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
                init_state,                      # 기본 checkin(계약 진입 조건) · staffing 생성은 checkout (Issue796)
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


def _drop_own_sid_marker(session_id: str, bot_id: str) -> None:
    """수동 퇴근 전이가 그 세션의 마커를 회수한다 (prj3#Issue846).

    마커 회수는 SessionEnd 훅(`fbot-checkout.sh`)만 했다 — 세션 중간의 `transition --to checkout` 뒤에도
    마커가 남아 쓰기 가드·`human_session_rejection` 이 계속 «결속» 으로 보고 `.hb` 가 lease 를 갱신했다.
    판정 단일 지점은 **마커 하나** — 원장이 퇴근이면 마커도 없다(reap·evict 와 같은 `drop_sid_marker`).
    마커가 **다른 봇** 것이면(인계·타 결속) 건드리지 않는다.
    """
    if not session_id:
        return
    try:
        with open(sid_marker_path(session_id), encoding="utf-8") as fh:
            owner = fh.read().strip()
    except OSError:
        return  # 마커 없음 — 회수할 것이 없다
    if owner == bot_id:
        drop_sid_marker(session_id)


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
            # prj3#Issue757 T15 — 관리직 몸체 원장: 출근·퇴근은 **몸체 단위**다
            _sid = getattr(args, "session_id", None) or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
            if _sid and multibody_enabled() and _is_nonexec(row["role"], on_error=False):
                mine = [b for b in open_bodies(con, args.bot_id, now) if b["session_id"] == _sid]
                if to == "checkin" and cur != "checkout" and mine:
                    con.execute("COMMIT")
                    emit({"ok": True, "action": "transition", "joined": True, "from": cur, "to": cur,
                          "body": mine[0]["id"], "note": "이미 근무 중인 관리직에 몸체 합류 — 봇 상태는 몸체 집계(T15)"})
                    return 0
                # 몸체 단위 퇴근은 **이 세션이 이 봇의 몸체일 때만**(lease 무관 — 끊긴 몸체도 자기 몸체다).
                #   몸체 없는 세션(사람의 수동 퇴근 등)의 퇴근은 종전대로 봇 전체 퇴근 — 아래에서 몸체를 전부 닫는다
                own = [bid_ for bid_, _o in session_bodies(con, _sid) if _o == args.bot_id]
                if to == "checkout" and own:
                    for bid_ in own:
                        con.execute("UPDATE job SET status='closed', result=? WHERE id=?",
                                    (json.dumps({"closed_reason": "checkout", "at": now}), bid_))
                        record_event(con, args.bot_id, "body-close", f"퇴근 {_sid[:8]}", bid_)
                    if open_bodies(con, args.bot_id, now):
                        project_bot(con, args.bot_id, now)
                        con.execute("COMMIT")
                        _drop_own_sid_marker(_sid, args.bot_id)
                        emit({"ok": True, "action": "transition", "body_closed": _sid, "from": cur, "to": cur,
                              "note": "다른 몸체가 살아 있어 봇은 근무 유지 — 이 몸체만 닫았다(T15)"})
                        return 0
                if to == "checkout":
                    con.execute("UPDATE job SET status='closed', result=? WHERE kind=? AND owner=? AND status='open'",
                                (json.dumps({"closed_reason": "last-checkout" if own else "bot-checkout", "at": now}),
                                 BODY_KIND, args.bot_id))
            validate_transition(cur, to)
            con.execute(
                "UPDATE bot SET state = ?, lease_expires = ?, last_active_at = strftime('%s','now') WHERE bot_id = ?",
                (to, now + ttl, args.bot_id),
            )
            record_event(con, args.bot_id, f"state:{to}", f"{cur} → {to}")   # prj3#Issue575 — 전이 1건 = 이벤트 1행
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
        if to == "checkout":
            _drop_own_sid_marker(_sid, args.bot_id)
        notify_hub_event(args.bot_id, f"state:{to}")
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


def cmd_employment(args) -> int:
    """재직 축 전이 (prj3#Issue551) — employed ⇄ suspended ⇄ leave → terminated. 등급은 건드리지 않는다.

    `suspended`(정직)는 career 사영에 대응값이 없어 career 로는 보이지 않는다 — 제재는 이 축의 소비처
    (조직도 `team_alive`·HR 게이트)가 본다. 상비봇 보호·해고의 휴직 경유는 career 규약 그대로."""
    to = (args.to or "").strip()
    if to not in EMPLOYMENTS:
        raise FbotError(f"허용되지 않은 employment: {to} ({'|'.join(EMPLOYMENTS)})")
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            row = fetch_bot(con, args.bot_id)
            cur_e = (row["employment"] if "employment" in row.keys() else None) or split_career(row["career"])[1]
            cur_g = (row["grade"] if "grade" in row.keys() else None) or split_career(row["career"])[0]
            if is_core_bot(row) and to in ("leave", "terminated", "suspended"):
                raise FbotError(f"상비봇 보호: {args.bot_id} 는 {EMPLOYMENT_LABEL[to]} 대상이 아니다 (계약 §조직)")
            if to not in EMPLOYMENT_TRANSITIONS.get(cur_e, set()):
                raise FbotError(f"불법 전이 거부: {EMPLOYMENT_LABEL.get(cur_e, cur_e)} → {EMPLOYMENT_LABEL[to]}. "
                                f"허용: {', '.join(sorted(EMPLOYMENT_TRANSITIONS.get(cur_e, set())))}")
            lease_sql = ", lease_expires = NULL" if to in ("leave", "suspended") else ""
            con.execute(f"UPDATE bot SET employment = ?, career = ?{lease_sql} WHERE bot_id = ?",
                        (to, project_career(cur_g, to), args.bot_id))
            record_event(con, args.bot_id, f"employment:{to}", f"{cur_e} → {to} ({args.reason or '사유 미기재'})")   # prj3#Issue575
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        notify_hub_event(args.bot_id, f"employment:{to}")
        emit({"ok": True, "action": "employment", "from": cur_e, "to": to,
              "from_label": EMPLOYMENT_LABEL.get(cur_e, cur_e), "to_label": EMPLOYMENT_LABEL[to],
              "grade": cur_g, "reason": args.reason or "(사유 미기재)",
              "bot": row_to_dict(fetch_bot(con, args.bot_id))})
    finally:
        con.close()
    return 0


def cmd_heartbeat(args) -> int:
    """lease_expires = now + TTL 갱신. TTL 은 policy.yml 이 SSOT.

    대상 지정은 둘 중 하나다:

    * ``--bot-id``     — tmux 위임 경로. ``FBOT_ID`` env 로 자기 봇을 아는 형태.
    * ``--session-id`` — Agent 형태. **그 세션에 결속된 생존 봇 전부**를 갱신한다.
    * 둘 다 — 합집합(prj3#Issue693_1). 봇 세션이 백그라운드 Agent 봇을 거느린 경우다.

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
                targets = []
            if args.session_id:
                # 퇴근한 봇은 제외한다 — 세션에 결속 기록만 남은 과거 봇을 되살리지 않는다.
                # 🔧 prj3#Issue693_1 — `--bot-id` 와 **함께** 올 수 있다(합집합). 봇 세션(FBOT_ID)
                #   이 백그라운드로 띄운 Agent 봇은 같은 session_id 에 결속되는데, 종전에는
                #   `--bot-id` 가 있으면 세션 쪽을 안 봐서 그 하청들의 lease 가 한 번도 안 올랐다.
                targets += [
                    r["bot_id"] for r in con.execute(
                        "SELECT bot_id FROM bot WHERE session_id = ? AND state != 'checkout'",
                        (args.session_id,),
                    ).fetchall() if r["bot_id"] not in targets
                ]
            _bodied = set()
            if args.session_id and multibody_enabled():
                # prj3#Issue757 T15 — 관리직 몸체: 이 세션의 몸체 lease 를 올린다(bot.session_id 는 최근 몸체뿐이라
                #   이전 몸체 세션의 heartbeat 은 위 조회로 봇을 못 찾는다)
                for bid_, owner in session_bodies(con, args.session_id):
                    # prj3#Issue882 — 만료 몸체 되살림도 결속과 같은 입장 검사(`body_revive`) — 거부면 갱신하지 않는다
                    _b = sid_body(con, owner, args.session_id)
                    if _b and _b["id"] == bid_:
                        try:
                            body_revive(con, fetch_bot(con, owner), _b, now)
                        except FbotError:
                            continue
                    con.execute("UPDATE job SET lease_until=?, payload=json_set(payload,'$.state','working') WHERE id=?",
                                (now + ttl, bid_))
                    _bodied.add(owner)
                    if owner not in targets and fetch_bot(con, owner)["state"] != "checkout":
                        targets.append(owner)
            for bid in targets:
                # prj3#Issue554 — 입력이 도착했다. Stop 훅이 내린 waiting_input 은 여기서 올린다
                #   (전이표: waiting_input → working "입력 도착"). 다른 상태는 건드리지 않는다.
                con.execute(
                    "UPDATE bot SET lease_expires = ?, last_active_at = ?,"
                    " state = CASE WHEN state = 'waiting_input' THEN 'working' ELSE state END"
                    " WHERE bot_id = ?", (now + ttl, now, bid)
                )
            for owner in _bodied:
                project_bot(con, owner, now)
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


def cmd_idle(args) -> int:
    """턴 종료 — 이 세션에 결속된 working 봇을 `waiting_input` 으로 내린다 (prj3#Issue554).

    Stop 훅(fbot-idle.sh)이 부른다. lease 는 건드리지 않는다 — 생존 신호와 상태는 다른 축이다.
    `.hb` 스탬프를 지워 다음 프롬프트의 heartbeat 가 스로틀 없이 즉시 돌게 한다(그것이 복귀다)."""
    if not args.session_id:
        raise FbotError("--session-id 가 필요하다")
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            targets = [r["bot_id"] for r in con.execute(
                "SELECT bot_id FROM bot WHERE session_id = ? AND state = 'working'",
                (args.session_id,)).fetchall()]
            for bid in targets:
                con.execute("UPDATE bot SET state = 'waiting_input' WHERE bot_id = ?", (bid,))
            if multibody_enabled():
                # prj3#Issue757 T15 — 이 몸체만 대기로 — 다른 몸체가 일하면 봇은 working 으로 사영된다
                for bid_, owner in session_bodies(con, args.session_id):
                    con.execute("UPDATE job SET payload=json_set(payload,'$.state','waiting_input') WHERE id=?", (bid_,))
                    project_bot(con, owner)
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
    finally:
        con.close()
    hb = sid_marker_path(args.session_id).replace(".id", ".hb")
    try:
        os.remove(hb)
    except OSError:
        pass
    emit({"ok": True, "action": "idle", "session_id": args.session_id, "idled": targets})
    return 0


# prj3#Issue644 ①② — claim 신선도 상수.
#   GRACE 는 **스폰 직후 몸체가 아직 출근 전인 구간**이다. 이 구간에서 워커가 `checkout` 인
#   것은 정상이므로 생사를 보면 안 된다 — 보면 갓 건 잠금을 남이 즉시 뺏는다(Issue555 회귀).
#   ⚠️ 값은 **새로 정하지 않는다** — prj1 `server.py` 가 이미 `FBOT_SPAWN_GRACE_SECS`(600)로
#   *"배분 뒤 10분 안의 퇴근은 미종결이 아니라 **스폰 대기**"* 를 판정한다(Issue573).
#   따로 두면 300~600초 구간에서 **보드는 «스폰 대기», 원장은 «고아»** 로 갈린다 — 같은
#   질문(몸체가 아직 뜨는 중인가)에 두 답이 생기는 것이 이 이슈가 고치는 결함 그 자체다.
#   TTL 은 생사를 **끝내 모를 때만** 쓰는 나이 폴백이고, fpm-do 의 `PM_DO_TIMEOUT`(1800)과
#   맞춘다. 거기서 위임을 포기하는 시점이므로 그보다 이른 탈취는 살아 있는 위임을 친다.
CLAIM_GRACE_SECS = int(os.environ.get("FBOT_CLAIM_GRACE")
                       or os.environ.get("FBOT_SPAWN_GRACE_SECS") or 600)
CLAIM_TTL_SECS = int(os.environ.get("FBOT_CLAIM_TTL")
                     or os.environ.get("PM_DO_TIMEOUT") or 1800)


def claim_holder_verdict(con, pl, now=None, flow=None):
    """선점된 claim 이 **아직 유효한가**를 3단으로 판정한다 (prj3#Issue644 ①②).

    판정 대상은 집행자 세션이 아니라 **몸체(워커 봇)** 다. Issue555 가 막으려던 것은
    *"한 배분에 몸체가 둘"* 이므로, 물어야 할 것은 *"지금 그 몸체가 도는가"* 다.
    집행자가 살아 있어도 몸체가 끝났으면 재스폰은 중복이 아니다 — 거꾸로 잡으면
    실발생(2026-09-19)처럼 집행자만 살아서 고아 claim 이 영원히 남는다.

    🔴 **오판 방향은 «모르면 살아 있다»로 고정한다** (Issue633 에서 락에 쓴 원칙 그대로).
    반대로 틀리면 도는 몸체의 claim 을 뺏어 둘이 같은 배분을 실행한다.

    반환: (verdict, reason)
      fresh   — 유예 구간. 몸체가 부팅 중일 수 있다 → 존중
      alive   — 몸체가 살아 있다 → 존중
      stale   — 몸체가 끝났거나(퇴근) lease 가 만료됐다 → 재선점
      expired — 생사 판정 불가 + TTL 초과 → 재선점 (나이 폴백 ②)
      unknown — 생사 판정 불가 + TTL 이내 → **존중**(모르면 살아 있다)
    """
    now = now or int(time.time())
    try:
        spawned_at = int(pl.get("spawned_at") or 0)
    except (TypeError, ValueError):
        spawned_at = 0
    age = (now - spawned_at) if spawned_at > 0 else None

    # ① 유예 — 생사보다 **먼저** 본다. 순서가 뒤집히면 갓 건 잠금이 즉시 탈취된다
    if age is not None and age < CLAIM_GRACE_SECS:
        return "fresh", "유예 %ds 이내(몸체 부팅 중일 수 있다)" % CLAIM_GRACE_SECS

    # prj3#Issue757 T15 ④ — 흐름 단위 잠금이면 판정 대상은 **그 흐름의 몸체**다. 봇 행은 몸체들의 사영이라
    #   다른 흐름 몸체가 살아 있으면 «alive» 로 보여 닫힌 흐름의 고아 잠금이 영영 안 풀린다
    if flow:
        if any(b["flow"] == flow for b in open_bodies(con, pl.get("worker_bot_id") or "", now)):
            return "alive", "흐름 %s 의 몸체가 lease 유효" % flow
        return "stale", "흐름 %s 의 몸체 없음 — 이 흐름을 도는 세션이 없다" % flow

    row = None
    worker = pl.get("worker_bot_id")
    if worker:
        row = con.execute("SELECT state, lease_expires FROM bot WHERE bot_id = ?",
                          (worker,)).fetchone()
    if row is not None:
        state = row["state"]
        exp = row["lease_expires"]
        if state == "checkout":
            return "stale", "몸체 퇴근 — 이 배분을 도는 세션이 없다"
        if exp is None:
            # lease 가 없는 결속은 bind_occupancy_verdict 도 `unknown` 으로 본다. 같게 둔다
            return ("expired", "lease 없음 + TTL %ds 초과" % CLAIM_TTL_SECS) \
                if (age is not None and age > CLAIM_TTL_SECS) else \
                ("unknown", "lease 없음 — 생사 판정 불가(살아 있다고 본다)")
        if int(exp) <= now:
            return "stale", "lease 만료(%ds 경과) — 몸체가 죽었다" % (now - int(exp))
        return "alive", "몸체 %s 가 %s 로 lease 유효" % (worker, state)

    if age is not None and age > CLAIM_TTL_SECS:
        return "expired", "워커 기록 없음 + TTL %ds 초과" % CLAIM_TTL_SECS
    return "unknown", "워커 기록 없음 — 생사 판정 불가(살아 있다고 본다)"


def claim_flow(con, worker, flow=None):
    """스폰 잠금의 흐름 키 — 스위치 on · 대상이 관리직(fail-closed) · 키가 있을 때만(`--flow` > env `FBOT_FLOW`).
    그 밖은 None = 종전 워커 단위 (prj3#Issue757 T15 ④)."""
    flow = (flow or os.environ.get("FBOT_FLOW") or "").strip()
    if not flow or not multibody_enabled():
        return None
    r = con.execute("SELECT role FROM bot WHERE bot_id = ?", (worker,)).fetchone()
    return flow if r is not None and _is_nonexec(r["role"], on_error=False) else None


def _claim_open_rows(con, worker):
    """이 워커 앞으로 열린 배분을 **생성순**으로 전부 돌려준다.

    🔴 **claim 대상이 job 이 아니라 «워커» 인 것은 의도다** (prj3#Issue647 이 재판정해 유지).
    선점이 고르는 «가장 오래된 open 1건» 은 이 워커의 **결정적 mutex 슬롯**이다 — 모든
    호출자가 같은 행을 집기 때문에 배타가 성립한다. 행 선택을 호출자 입력(`--ident` 등)에
    맡기면 두 호출자가 서로 다른 행을 집어 **같은 워커의 몸체가 둘 뜬다**(Issue555 회귀).
    잠금이 지키는 실자원은 배분이 아니라 워커의 tmux 창 `pmdo<prj>-<bot-slug>` 하나뿐이다.

    해제가 «이 워커의 open 전부» 인 것도 같은 이유라 비대칭이 아니다 — 단위가 워커이므로
    몸체가 끝났다는 사실은 그 워커의 모든 잠금에 똑같이 적용된다.

    예외 하나(prj3#Issue757 T15 ④): 관리직 몸체 원장이 켜진 관리직은 흐름마다 몸체가 하나라 슬롯도
    **흐름**이다(`claim_flow`). 흐름 키는 배분 id·요청 id 로 정해져 호출자가 고르지 않으므로 mutex 는 성립한다.
    ⚠️ 창은 여전히 봇 하나 — fpm-do 가 흐름마다 창을 가르기 전까지 스위치를 켜지 않는다.
    """
    out = []
    for r in con.execute(
            "SELECT id, owner, payload FROM job WHERE kind = ? AND status = 'open'"
            " ORDER BY created_at", (DISPATCH_KIND,)).fetchall():
        try:
            pl = json.loads(r["payload"] or "{}")
        except (ValueError, TypeError):
            continue
        if pl.get("worker_bot_id") == worker:
            out.append((r["id"], r["owner"], pl))
    return out


def _row_ident(pl):
    """배분 행이 가리키는 일. 운영이 쓰는 키는 `issue` 다([fbot-lead.py](fbot-lead.py) `payload`).

    `ident` 는 회귀 하네스가 쓰는 옛 이름이라 **폴백으로만** 본다 — 둘 다 없으면 None.
    """
    v = pl.get("issue") or pl.get("ident")
    return v.strip() if isinstance(v, str) and v.strip() else None


def _lock_disclosure(pl, want, scope="worker"):
    """prj3#Issue647 — **어느 일을 잠갔는지 말한다.** 잠금의 단위는 바꾸지 않는다.

    호출자가 지목한 일(`want`)과 플래그가 박힌 행의 일(`lock_row_issue`)은 **갈릴 수 있고
    그것이 정상**이다. 잠금이 배타 제어하는 실자원은 배분이 아니라 **워커의 몸체**(tmux 창
    `pmdo<prj>-<bot-slug>` — [fpm-do](~/.bin/fpm-do))이기 때문이다. 종전에는 이 갈림이
    응답에 아예 없어, 호출자가 «내가 지목한 배분이 잠겼다» 고 오해할 수밖에 없었다.
    """
    row = _row_ident(pl)
    out = {"lock_scope": scope, "lock_row_issue": row}   # prj3#Issue757 T15 ④ — 관리직 흐름 잠금은 "flow"
    if want:
        out["requested_ident"] = want
        out["ident_match"] = (row == want)
    return out


def _clear_claim(pl, by, reason, now):
    """claim 을 비우되 **비운 사실을 남긴다**. 원장에서 잠금 이력이 사라지면 안 된다."""
    hist = pl.get("claim_history")
    if not isinstance(hist, list):
        hist = []
    hist.append({"spawned_by": pl.get("spawned_by"), "spawned_at": pl.get("spawned_at"),
                 "spawned_for": pl.get("spawned_for"),   # prj3#Issue647 — 무슨 일로 잡았던 잠금인가
                 "released_by": by, "released_at": now, "reason": reason})
    pl["claim_history"] = hist[-5:]     # 무한 성장 차단 — 최근 5건이면 진단에 충분하다
    pl.pop("spawned_by", None)
    pl.pop("spawned_at", None)
    pl.pop("spawned_for", None)
    return pl


def cmd_dispatch_claim(args) -> int:
    """스폰 집행자 잠금 (prj3#Issue555) — 이 워커의 `open` 배분 1건을 **선점**한다.

    같은 배분을 두 세션이 각자 승인을 들고 스폰하면 몸체가 둘이 뜬다(Issue554 e4 실측 —
    통지로만 회피). 잠금은 스폰 **앞**에 있어야 하므로 fpm-do 가 send-keys 직전에 부른다.
    rc 0 = 선점했거나 잠글 배분이 없음(자기 주도 위임) · **rc 3 = 이미 선점됨**(스폰 중단).
    선점 흔적은 `payload.spawned_by`·`spawned_at` — 원장 밖에 잠금 파일을 두지 않는다.

    🔴 **prj3#Issue644 ①②③ — 잠금에 해제 경로와 생사 판정이 생겼다.**
    종전에는 한 번 박힌 `spawned_by` 를 푸는 수단이 **하나도 없었다.** 몸체가 이슈를 닫지
    않고 끝나면(게이트 대기·중단·크래시) 배분은 `open` 인 채 잠금만 남아 그 워커를 향한
    이후 모든 스폰이 rc 3 으로 막혔다(2026-09-19 실측 — prj3 배분 3건 정지). 둘은 짝이다:
    `--release` 만 두면 크래시에서 또 고아가 되고, 생사 판정만 두면 정상 종료에서도
    유예·TTL 을 기다린다.
    """
    now = int(time.time())
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            flow = claim_flow(con, args.worker, getattr(args, "flow", None))
            scope = "flow" if flow else "worker"
            if getattr(args, "release", False):
                return _dispatch_release(con, args, now, flow)
            # prj3#Issue647 — 호출자가 «무엇을 스폰하려는가» 를 선언할 수 있다. 선언은
            #   **기록·공개 전용**이고 아래 행 선택에는 관여하지 않는다(그래야 mutex 가 산다).
            want = (getattr(args, "ident", None) or "").strip() or None
            rows = _claim_open_rows(con, args.worker)
            if flow:
                # prj3#Issue757 T15 ④ — 관리직 몸체는 흐름마다 하나라 mutex 슬롯도 흐름이다(흐름 키는 호출자가
                #   고르지 않는다 — 배분 id·요청 id 로 정해져 두 호출자가 같은 흐름이면 같은 행을 집는다)
                rows = [r for r in rows if r[0] == flow]
            if not rows:
                con.execute("COMMIT")
                out = {"ok": True, "action": "dispatch-claim", "claimed": False,
                       "reason": ("이 흐름의 open 배분 없음 — 잠글 대상이 없다(인박스 흐름 등)" if flow
                                  else "open 배분 없음 — 잠글 대상이 없다(자기 주도 위임)"),
                       "worker_bot_id": args.worker, "lock_scope": scope,
                       "lock_row_issue": None}
                if want:
                    out["requested_ident"] = want
                emit(out)
                return 0
            jid, owner, pl = rows[0]
            reclaimed_from = None
            if pl.get("spawned_by"):
                verdict, why = claim_holder_verdict(con, pl, now, flow=flow)
                if verdict in ("fresh", "alive", "unknown"):
                    con.execute("COMMIT")
                    out = {"ok": False, "action": "dispatch-claim", "claimed": False, "lock_scope": scope,
                           "reason": "이미 스폰됨 — 다른 집행자가 선점했다", "job_id": jid,
                           "spawned_by": pl["spawned_by"], "spawned_at": pl.get("spawned_at"),
                           # prj3#Issue647 — 막힌 호출자가 **무엇에 막혔는지** 알아야 한다.
                           #   보유자가 잠글 때 선언한 일이 `spawned_for` 다(없으면 미선언 호출).
                           "spawned_for": pl.get("spawned_for"),
                           "verdict": verdict, "verdict_reason": why,
                           "worker_bot_id": args.worker}
                    out.update(_lock_disclosure(pl, want, scope))
                    emit(out)
                    return 3
                # stale·expired — 고아 잠금이다. 뺏되 **뺏은 사실을 원장에 남긴다**
                reclaimed_from = {"spawned_by": pl.get("spawned_by"),
                                  "spawned_at": pl.get("spawned_at"),
                                  "spawned_for": pl.get("spawned_for"),
                                  "verdict": verdict, "reason": why}
                _clear_claim(pl, args.by or "", "reclaim/%s: %s" % (verdict, why), now)
            pl["spawned_by"] = args.by or ""
            pl["spawned_at"] = now
            # prj3#Issue647 — 플래그가 박힌 행과 실제로 스폰하는 일이 갈리므로, **의도를 행에
            #   적어 둔다**. 이것이 없으면 원장을 읽는 사람은 «가장 오래된 open» 행의 잠금을 보고
            #   «그 행의 이슈를 스폰했다» 고 읽는다 — 실제로 띄운 것은 다른 이슈인데도.
            if want:
                pl["spawned_for"] = want
            else:
                pl.pop("spawned_for", None)
            con.execute("UPDATE job SET payload = ? WHERE id = ?",
                        (json.dumps(pl, ensure_ascii=False), jid))
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        out = {"ok": True, "action": "dispatch-claim", "claimed": True, "job_id": jid, "lock_scope": scope,
               "owner": owner, "spawned_by": pl["spawned_by"], "worker_bot_id": args.worker}
        out.update(_lock_disclosure(pl, want, scope))
        if reclaimed_from:
            out["reclaimed_from"] = reclaimed_from
        emit(out)
        return 0
    finally:
        con.close()


def _dispatch_release(con, args, now, flow=None) -> int:
    """③ 해제 — 몸체가 끝났으니 이 워커의 잠금을 비운다 (prj3#Issue644).

    퇴근 훅([fbot-checkout.sh](fbot-checkout.sh))이 부른다. 짝이 없어서 생긴 이슈이므로
    **짝을 만드는 것이 본체**이고, 생사 판정(①)은 이 훅이 못 도는 경로(크래시·강제 종료)를
    받는 그물이다.

    ⚠️ **퇴근한 워커만 해제한다**(`--force` 로 우회). 늦게 끝난 옛 세션의 퇴근 훅이 방금
    걸린 새 잠금을 푸는 것을 막는다 — 그것을 허용하면 해제 경로가 Issue555 를 되살린다.
    """
    rows = _claim_open_rows(con, args.worker)
    row = con.execute("SELECT state FROM bot WHERE bot_id = ?", (args.worker,)).fetchone()
    state = row["state"] if row is not None else None
    if flow:
        # prj3#Issue757 T15 ④ — 흐름 해제는 **그 흐름의 몸체**로 판정한다. 봇은 다른 흐름 몸체로 근무 중일 수
        #   있다(그래도 이 흐름은 끝났다). 그 흐름 몸체가 아직 살아 있으면 늦은 퇴근 훅이므로 풀지 않는다
        rows = [r for r in rows if r[0] == flow]
        if any(b["flow"] == flow for b in open_bodies(con, args.worker, now)) and not getattr(args, "force", False):
            con.execute("COMMIT")
            emit({"ok": True, "action": "dispatch-claim", "released": [], "skipped": True, "lock_scope": "flow",
                  "reason": "흐름 %s 의 몸체가 아직 돈다. 해제하지 않는다" % flow, "worker_bot_id": args.worker})
            return 0
    elif not getattr(args, "force", False) and state is not None and state != "checkout":
        con.execute("COMMIT")
        emit({"ok": True, "action": "dispatch-claim", "released": [], "skipped": True,
              "reason": "워커가 %s — 몸체가 아직 돈다. 해제하지 않는다" % state,
              "worker_bot_id": args.worker})
        return 0
    released = []
    for jid, _owner, pl in rows:
        if not pl.get("spawned_by"):
            continue
        released.append({"job_id": jid, "spawned_by": pl.get("spawned_by"),
                         "spawned_at": pl.get("spawned_at"),
                         # prj3#Issue647 — 어느 행의 무슨 일이 풀렸는지 (행 ≠ 스폰한 일)
                         "issue": _row_ident(pl), "spawned_for": pl.get("spawned_for")})
        _clear_claim(pl, args.by or "", "release/checkout", now)
        con.execute("UPDATE job SET payload = ? WHERE id = ?",
                    (json.dumps(pl, ensure_ascii=False), jid))
    con.execute("COMMIT")
    emit({"ok": True, "action": "dispatch-claim", "released": released,
          "worker_bot_id": args.worker, "worker_state": state})
    return 0


def session_presence(tmux_target) -> str:
    """결속 세션의 **몸체**가 아직 있는가 — 3값 (prj3#Issue699_5).

    present — pane 이 있고 셸이 아닌 프로세스가 돈다 · absent — pane 이 없거나 죽었거나 셸로
    돌아왔다(Claude 종료) · unknown — tmux 실행 형태가 아니거나 tmux 를 못 부른다.
    ⚠️ `display-message -t` 는 **없는 타깃에도 rc 0** 으로 현재 pane 을 답한다(2026-09-26 실측) —
    존재 판정은 `list-panes` 로 한다. unknown 을 absent 로 읽지 않는다(VSCode 세션은 pane 이 없다).
    """
    t = (tmux_target or "").strip()
    if not t:
        return "unknown"
    tmux = shutil.which("tmux")
    if not tmux:
        return "unknown"
    win, _, idx = t.rpartition(".")
    if not win or not idx.isdigit():
        win, idx = t, "0"
    try:
        r = subprocess.run([tmux, "list-panes", "-t", win, "-F",
                            "#{pane_index}|#{pane_dead}|#{pane_current_command}"],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if r.returncode != 0:
        return "absent"
    for line in r.stdout.splitlines():
        i, dead, cmd = (line.split("|", 2) + ["", ""])[:3]
        if i == idx:
            return "absent" if dead == "1" or cmd in ("zsh", "bash", "sh", "fish", "-zsh", "-bash") else "present"
    return "absent"


def pane_human_active(tmux_target, now=None, window=None) -> bool:
    """사람이 **지금 이 pane 에서 입력 중**인가 — attach 중이고 그 pane 이 활성이며 최근 입력이 있다 (prj3#Issue859_3).

    판정 불가(tmux 없음·명령 실패·형식 이상)는 **False** 다 — 모른다고 막지 않는다(보류는 지연일 뿐이지만 모르는 채
    영구 보류하면 요청이 방치된다). `session_presence` 와 달리 «있다/없다» 가 아니라 «지금 사람이 쓰는가» 만 본다."""
    t = (tmux_target or "").strip()
    tmux = shutil.which("tmux") if t else None
    if not tmux:
        return False
    try:
        d = subprocess.run([tmux, "display-message", "-p", "-t", t, "#{session_attached} #{window_active} #{pane_active}"],
                           capture_output=True, text=True, timeout=3)
        c = subprocess.run([tmux, "list-clients", "-t", t, "-F", "#{client_activity}"],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return False
    if d.returncode != 0 or c.returncode != 0:
        return False
    parts = d.stdout.split()
    if len(parts) != 3 or not parts[0].isdigit() or int(parts[0]) < 1 or parts[1] != "1" or parts[2] != "1":
        return False
    acts = [int(x) for x in c.stdout.split() if x.isdigit()]
    if not acts:
        return False
    win = window if window is not None else typing_guard_secs()
    return (now or int(time.time())) - max(acts) <= win


def typing_guard_enabled() -> bool:
    return str(_policy_value("fbot_typing_guard", "on")).lower() not in ("off", "false", "0", "no")


def typing_guard_secs() -> int:
    try:
        return int(_policy_value("fbot_typing_guard_secs", 120))
    except (TypeError, ValueError):
        return 120


def typing_guard(con, row, now=None) -> str:
    """자동 기상을 **보류**해야 하는가 — 사유 문자열, 보류하지 않으면 빈 문자열 (prj3#Issue859_3, OpenRig typing-guard 차용).

    사람 세션 판정은 새로 만들지 않는다 — `/fbot-bind` 결속이 이미 남기는 표지를 쓴다: `bot.form == 'session'`
    (cmd_bind 가 사람 경로로 확정하는 값) 또는 몸체 원장의 흐름이 `session:`(사람 세션 몸체, body_bind 기본 흐름).
    배분 스폰 몸체(form 없음·흐름 = 요청·배분 id)는 사람이 쓰는 pane 이 아니므로 대상이 아니다.
    보류 대상은 **자동 주입(몸체 기상)** 뿐이다 — 요청은 인박스에 적재돼 있고 넛지 훅은 턴 경계 컨텍스트라 입력을 끊지 않는다."""
    if not typing_guard_enabled():
        return ""
    now = now or int(time.time())
    panes = []
    if (row["form"] if "form" in row.keys() else None) == "session" and row["tmux_target"]:
        panes.append(row["tmux_target"])
    for b in open_bodies(con, row["bot_id"], now):
        if str(b.get("flow") or "").startswith("session:") and b.get("pane"):
            panes.append(b["pane"])
    for p in dict.fromkeys(panes):
        if pane_human_active(p, now):
            return f"사람 세션 pane {p} 에서 입력 중 — 자동 기상 보류(요청은 인박스에 남는다)"
    return ""


def _lead_mod():
    """fbot-lead.py 적재 1회 — 이슈 완료 판정·재배분 명령을 복제하지 않고 빌려 쓴다(prj3#Issue788_2). 실패는 None."""
    global _LEAD_MOD
    if _LEAD_MOD is None:
        try:
            import importlib.util as _il
            _sp = _il.spec_from_file_location("fbot_lead_reap", _LEAD_PY)
            _lm = _il.module_from_spec(_sp); _sp.loader.exec_module(_lm)
            _LEAD_MOD = _lm
        except Exception:
            _LEAD_MOD = False
    return _LEAD_MOD or None


def _reap_dispatch_action(job_id, payload) -> tuple:
    """reap 대상 배분의 처분 — (`worker_died`, 재배분 명령) · (`reaped`, None) (prj3#Issue788_2).

    이슈 배분이고 그 이슈가 **미완료로 판정**되면 사망이다 — 일이 남았으니 다시 배분할 수 있어야 한다.
    완료 판정은 fbot-lead `issue_completed_in`(sweep·회수와 같은 규칙) 단일 지점이다.
    ⚠️ 완료(True)·판정 불가(None)·topic·적재 실패는 종전 `reaped` — 모르는 것을 사망으로 지어내지 않는다.
    """
    try:
        pl = json.loads(payload or "{}") or {}
    except (ValueError, TypeError):
        return DISPATCH_REAPED, None
    lead = _lead_mod() if pl.get("ident_kind") == "issue" else None
    if lead is None:
        return DISPATCH_REAPED, None
    try:
        verdict = lead.issue_completed_in(pl.get("cwd"), canon_issue(pl.get("issue") or ""))
    except Exception:
        return DISPATCH_REAPED, None
    if verdict is not False:
        return DISPATCH_REAPED, None
    try:   # 재배분 명령은 부가 정보다 — 못 만들어도 사망 판정은 선다
        sp = lead._spawn_commands(pl.get("worker_bot_id") or "", pl.get("issue") or "", pl.get("cwd") or "",
                                  pl.get("prj"), role=pl.get("role"), disp_id=job_id,
                                  model=pl.get("model_override"))   # prj3#Issue849
        respawn = sp.get(sp.get("run", "agent"))
    except Exception:
        respawn = None
    return DISPATCH_DIED_BY, respawn


def cmd_reap(args) -> int:
    """lease 만료 봇 스캔 → 강제 퇴근. 기본 dry-run, --apply 로 실제 적용.

    계약 §상태 기계: 크래시한 봇이 "작업중"으로 영원히 남지 않게 lease 만료 시 강제 퇴근한다.
    회수 경로는 s1 plan 확정대로 maint(s0 상주 스케줄러)가 본 서브커맨드를 부른다.

    **배분 원장 동반 종결 (Issue495 ⓒ)** — 봇만 퇴근시키고 원장을 두면 그 배분은 영원히
    `open` 이다. 완료 판정(`fbot-lead.py detect_completions`)은 퇴근한 봇의 **작업 기록**
    을 요구하는데, 강제 퇴근된 봇은 정의상 그 기록을 남길 기회가 없었기 때문이다. 그렇게
    남은 `open` 은 ① 조직도에 "유실 배분" 경보로 영구 노출되고 ② 팀장핀봇의 WIP 슬롯
    (실측 상한 3)을 영구 점유해 **조직 전체의 배분을 막는다**. 2026-08-31 실측이 정확히
    그것이었다 — Agent 형태 3건이 슬롯 3칸을 다 먹어 새 배분이 전부 거절됐다.

    ⚠️ 종결 status 는 `done` 이 아니라 `reaped` 다. 여기서 아는 것은 *"lease 가 만료됐다"*
    뿐이고 *"일이 끝났다"* 가 아니다. 완료로 적으면 원장이 거짓말을 한다. 정상 완료는
    퇴근 훅이 남긴 기록으로 sweep 이 `done` 을 찍는 것이 정규 경로이며, 이쪽은 그 경로가
    실패했을 때만 도는 **마지막 방벽**이다.

    🔧 prj3#Issue788_2 — **이슈 미완료 배분은 `reaped` 가 아니라 `blocked(worker_died)`** 다. lease 만료는 대개
      작업 도중 죽은 몸체다(퇴근 훅도 못 돈 kill). `reaped` 는 terminal 이라 남은 일을 다시 배분할 길이 없었다.
      회수(fbot-lead `_reclaim_action`)와 같은 상태로 두고 재배분 명령을 `payload.worker_died.respawn` 에 남긴다. 완료·판정 불가·
      topic 배분은 종전대로 `reaped`(`_reap_dispatch_action`).
    """
    now = int(time.time())
    con = connect()
    try:
        if args.apply:
            # prj3#Issue757 T15 — lease 만료 몸체는 닫는다(몸체 원장 위생). 봇 퇴근은 아래 봇 단위 판정 그대로.
            #   수신대기 몸체는 봇과 같은 idle 유예를 받는다(Issue554 — 유휴 ≠ 사망). 닫은 몸체 세션은
            #   봇 reap 과 같이 마커를 걷고 알린다(Issue549·675 — «퇴근 = 마커 소멸» 은 몸체 단위에서도 성립)
            _grace = idle_ttl_secs()
            _q = ("SELECT id, owner, payload, lease_until FROM job WHERE kind=? AND status='open'"
                  " AND lease_until IS NOT NULL AND lease_until <= ?")
            _p = [BODY_KIND, now]
            if getattr(args, "bot_id", None):
                _q += " AND owner=?"; _p.append(args.bot_id)
            dead = []
            for r in con.execute(_q, _p).fetchall():
                pl = json.loads(r["payload"] or "{}")
                if pl.get("state") == "waiting_input" and now < int(r["lease_until"]) + _grace:
                    continue
                dead.append((r["id"], r["owner"], pl.get("session_id") or ""))
            if dead:
                con.execute("BEGIN IMMEDIATE")
                closed_ = set()
                for jid, _o, _s in dead:
                    # prj3#Issue882 — 조회 뒤 되살아난 몸체는 닫지 않는다(트랜잭션 안 lease 재확인) · 실제로 닫은 행만 마커 걷기
                    cur_ = con.execute("UPDATE job SET status='closed', result=? WHERE id=? AND status='open'"
                                       " AND lease_until IS NOT NULL AND lease_until <= ?",
                                       (json.dumps({"closed_reason": "lease-expired", "at": now}), jid, now))
                    if cur_.rowcount:
                        closed_.add(jid)
                con.execute("COMMIT")
                for _j, owner, sid_ in dead:
                    if sid_ and _j in closed_:
                        drop_sid_marker(sid_)
                        write_evict_tombstone(sid_, owner, "", kind="reaped")
        rows = con.execute(
            "SELECT * FROM bot WHERE state != 'checkout'"
            " AND lease_expires IS NOT NULL AND lease_expires < ?"
            " ORDER BY lease_expires",
            (now,),
        ).fetchall()
        expired = [row_to_dict(r) for r in rows]
        # prj3#Issue554 — 수신대기 봇은 idle TTL 만큼 더 기다린다(유휴 ≠ 사망)
        idle_grace = idle_ttl_secs()
        # prj3#Issue734 — `--force`(반드시 --bot-id 동반): 깨우려는 호출자(HR wake)가 bind 판정으로
        #   `dead` 를 확정한 경우다. idle 유예는 **tick 일괄 회수**를 보수적으로 두는 장치라, 호출자가
        #   있으면 기다리지 않는다. lease 만료 조건(위 SELECT)은 그대로 — 살아 있는 lease 는 못 거둔다.
        force = bool(getattr(args, "force", False))
        if force and not getattr(args, "bot_id", None):
            raise FbotError("reap --force 는 --bot-id 를 함께 요구한다 — 일괄 강제 회수는 idle 유예를 무력화한다")
        #   prj3#Issue699_5 — 단 **몸체가 없으면** 유휴가 아니라 사망이다. 유예하면 그동안 HR wake 가
        #   «활동 중» 으로 거절해 교착한다(2026-09-26 실측). 판정 불가(unknown)는 종전대로 유예한다.
        expired = [e for e in expired
                   if force or not (e.get("state") == "waiting_input"
                           and now < int(e["lease_expires"]) + idle_grace
                           and session_presence(e.get("tmux_target")) != "absent")]
        if getattr(args, "bot_id", None):
            expired = [e for e in expired if e["bot_id"] == args.bot_id]
        for e in expired:
            e["overdue_secs"] = now - int(e["lease_expires"])

        # 각 만료 봇이 물고 있는 미종결 배분 — dry-run 에서도 보여야 판단이 된다.
        #   prj3#Issue788_2 — 배분별 처분(`dispatch_actions`)도 여기서 정한다. 판정이 Issue.md 를 읽고 재배분
        #   명령이 원장을 조회하므로 쓰기 트랜잭션(BEGIN IMMEDIATE) **밖**에서 끝낸다.
        respawns = {}
        for e in expired:
            mine = [r for r in con.execute(
                        "SELECT id, payload FROM job WHERE kind = ? AND status = 'open'",
                        (DISPATCH_KIND,),
                    ).fetchall()
                    if _dispatch_worker(r["payload"]) == e["bot_id"]]
            e["open_dispatches"] = [r["id"] for r in mine]
            e["dispatch_actions"] = {}
            for r in mine:
                act, respawn = _reap_dispatch_action(r["id"], r["payload"])
                e["dispatch_actions"][r["id"]] = act
                if act == DISPATCH_DIED_BY:
                    respawns[r["id"]] = respawn

        reaped, closed, died = [], [], []
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
                    # Issue549 — 마커도 함께 걷는다. 퇴근 훅(fbot-checkout.sh)은 이미
                    #   지우지만 reap 은 그 훅이 실패했을 때 도는 마지막 방벽이라,
                    #   여기서 빠지면 보완이 성립하지 않는다. 마커가 남으면 ①호칭 환기
                    #   훅이 "이미 결속" 으로 오판해 침묵하고 ②heartbeat 폴백이 퇴근한
                    #   봇의 lease 를 되살린다. 불변은 **"퇴근 = 마커 소멸"** 이다.
                    drop_sid_marker(e.get("session_id") or "")
                    # prj3#Issue757 T15 — 관리직 몸체가 남았으면(유예 중 몸체·강제 회수) 전부 닫고 그 세션들도 걷는다.
                    #   bot.session_id 는 최근 몸체 하나뿐이라 위 한 줄로는 나머지 몸체 세션의 마커가 남는다
                    for _r in con.execute("SELECT id, payload FROM job WHERE kind=? AND owner=? AND status='open'",
                                          (BODY_KIND, e["bot_id"])).fetchall():
                        con.execute("UPDATE job SET status='closed', result=? WHERE id=?",
                                    (json.dumps({"closed_reason": "reaped", "at": now}), _r["id"]))
                        _bs = json.loads(_r["payload"] or "{}").get("session_id") or ""
                        if _bs and _bs != (e.get("session_id") or ""):
                            drop_sid_marker(_bs)
                            write_evict_tombstone(_bs, e["bot_id"], "", kind="reaped")
                    # Issue675 — 마커를 걷었으면 **알려야 한다**. evict 는 Issue645 로
                    #   툼스톤을 세웠는데 reap 에는 같은 공백이 남아 있었다: 상태는
                    #   바꾸고(checkout) 마커는 걷으면서(Issue549) 통보만 없었다.
                    #   유휴로 lease 만 끊긴 **살아 있는 세션**(Issue554 가 지적한 경우)이
                    #   자기가 퇴근 처리된 줄 모르고 계속 그 봇으로 일한다 — 원장은 퇴근인데
                    #   세션은 근무 중이라 기록 귀속이 갈린다.
                    #   ⚠️ successor 는 **빈 값**이다. reap 은 아무도 안 받은 것이라
                    #      「후임에게 넘어갔다」가 아니다. 소비처가 kind 로 분기한다.
                    write_evict_tombstone(e.get("session_id") or "", e["bot_id"], "",
                                          kind="reaped")
                    for job_id in e["open_dispatches"]:
                        if e["dispatch_actions"].get(job_id) == DISPATCH_DIED_BY:
                            # prj3#Issue788_2 — 이슈가 미완료다. 종결하지 않고 재배분 대기로 둔다(WIP 미점유 —
                            #   동시 상한은 open 만 센다). 재배분 명령은 원장에 남긴다: reap 은 무인 주기라 받을 호출자가 없다
                            cur = con.execute(
                                "UPDATE job SET status = 'blocked', blocked_since = ?,"
                                " payload = json_set(payload, '$.blocked_by', ?, '$.worker_died', json(?))"
                                " WHERE id = ? AND status = 'open'",
                                (now, DISPATCH_DIED_BY,
                                 json.dumps({"by": "reap", "at": now, "from_status": "open",
                                             "reason": "워커 lease 만료로 강제 퇴근 — 이슈 미완료(재배분 대상)",
                                             "worker_bot_id": e["bot_id"], "overdue_secs": e["overdue_secs"],
                                             "respawn": respawns.get(job_id)}, ensure_ascii=False),
                                 job_id),
                            )
                            if cur.rowcount == 1:
                                record_event(con, e["bot_id"], "blocked",
                                             f"{job_id}: worker_died — reap(lease 만료, 이슈 미완료)", job_id)
                                died.append(job_id)
                            continue
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
            "dispatches_blocked": died,   # prj3#Issue788_2 — blocked(worker_died), 재배분 대기
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


def worker_dispatch(con, bot_id, hint=None, flow=None):
    """그 봇이 worker 인 미종결 배분 중 «지금 이 몸체의 일» — (고른 payload | None, 후보 payload 목록) (prj3#Issue759).

    출근 훅이 current_task 를 원장에서 적기 위한 판정 단일 지점이다. 고르는 순서:
      ① 몸체 흐름 `flow`(env `FBOT_FLOW` — 관리직은 흐름 = 받은 배분 id, prj3#Issue757 T15)가 후보면 그것
      ② `hint`(위임자가 준 FBOT_TASK)가 이슈 식별자를 품고 그 이슈의 후보가 정확히 1건이면 그것
      ③ 후보가 정확히 1건이면 그것 · 0건·못 가르는 2건+ 는 None(고르지 않는다 — `whois` 1:N 과 같은 원칙)
    후보 술어는 계보(`dispatch_lineage`)와 같은 `LINEAGE_LIVE` 다."""
    cands = []
    for jid, raw in con.execute("SELECT id, payload FROM job WHERE kind = ? AND status IN (" + LINEAGE_LIVE_SQL + ")"
                                " ORDER BY created_at, id", (DISPATCH_KIND,) + LINEAGE_LIVE).fetchall():
        try:
            pl = json.loads(raw or "{}")
        except (ValueError, TypeError):
            continue
        if pl.get("worker_bot_id") == bot_id:
            cands.append(dict(pl, _id=jid))
    if flow:
        hit = [c for c in cands if c["_id"] == flow]
        if hit:
            return hit[0], cands
    refs = _SM_ISSUE_RE.findall(hint or "") if hint else []
    if refs:
        hit = [c for c in cands if c.get("issue") and same_issue(canon_issue(c["issue"]), refs[0], c.get("prj"))]
        if len(hit) == 1:
            return hit[0], cands
    return (cands[0] if len(cands) == 1 else None), cands


def cmd_set_task(args) -> int:
    # prj3#Issue739 M1-4 — 구조 필드. 생략하면 NULL: current_task(사람용 문자열)와 **함께** 갱신해 낡은 이슈가 남지 않게
    issue = (getattr(args, "issue", None) or "").strip() or None
    ref = (getattr(args, "task_ref", None) or "").strip() or None
    task = (getattr(args, "task", None) or "").strip() or None
    from_disp = bool(getattr(args, "from_dispatch", False))
    if issue and not ISSUE_ID_RE.match(issue):
        raise FbotError(f"--issue {issue!r}: 이슈 식별자 형식이 아니다(Issue<N> · prj<N>#Issue<M>) — 원장 조인 키다")
    if not task and not from_disp:
        raise FbotError("--task 또는 --from-dispatch 중 하나는 필요하다")
    ref_given = ref is not None
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            fetch_bot(con, args.bot_id)  # 미등록이면 fail-loud
            if from_disp:
                # prj3#Issue759 — «무슨 일로 띄웠나» 는 배분 원장이 안다. 빈 칸만 원장 사실로 채운다(명시 인자가 이긴다)
                chosen, cands = worker_dispatch(con, args.bot_id, hint=task, flow=os.environ.get("FBOT_FLOW") or None)
                if chosen:
                    ident = canon_issue(chosen.get("issue") or "")
                    task = task or ident or None
                    if issue is None and ISSUE_ID_RE.match(ident):
                        issue = ident
                    if ref is None:
                        ref = (chosen.get("task_ref") or "").strip() or None
                elif cands and not task:
                    task = " · ".join(canon_issue(c.get("issue") or "") for c in cands if c.get("issue"))[:120] or None
            if not task:
                # 배분도 위임 요지도 없다 — 추측으로 채우지 않는다(낡은 값은 출근 전이가 이미 비웠다)
                con.execute("ROLLBACK")
                emit({"ok": True, "action": "set-task", "changed": False,
                      "reason": "미종결 배분도 --task 도 없다 — 기입하지 않음", "bot_id": args.bot_id})
                return 0
            con.execute(
                "UPDATE bot SET current_task = ?, current_issue = ?, current_task_ref = ?,"
                " last_active_at = strftime('%s','now') WHERE bot_id = ?", (task, issue, ref, args.bot_id)
            )
            if ref and ref_given:   # 원장에서 온 task_ref 는 이미 그 배분에 있다 — 다른 배분에 옮겨 적지 않는다
                # 그 봇의 미종결 배분에 task_ref 전사 — 진행률 해석(task 파일 [v]/전체)은 어댑터 몫(fbot-org §이슈 축 연동)
                for jid, raw in con.execute("SELECT id, payload FROM job WHERE kind = ? AND status IN (" + LINEAGE_LIVE_SQL + ")",
                                            (DISPATCH_KIND,) + LINEAGE_LIVE).fetchall():
                    try:
                        pl = json.loads(raw or "{}")
                    except (ValueError, TypeError):
                        continue
                    if pl.get("worker_bot_id") == args.bot_id and pl.get("task_ref") != ref:
                        pl["task_ref"] = ref
                        con.execute("UPDATE job SET payload = ? WHERE id = ?", (json.dumps(pl, ensure_ascii=False), jid))
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({"ok": True, "action": "set-task", "bot": row_to_dict(fetch_bot(con, args.bot_id))})
    finally:
        con.close()
    return 0


DECIDE_GRADES = ("C", "L")   # H 는 여기가 아니다 — mq `[컨펌] [H:<분류>]` 가 유일한 창구(prj3#Issue756)
# 등급별 결정 자격 — C 는 상비 총괄, L 은 매니저(팀장·총괄). 권한표 정본 `_doc_arch/decision-authority.md`
DECIDE_ROLES = {"C": ("chief",), "L": ("lead", "chief")}


def _ident_mod():
    """봇 신원 대조 판정 단일 지점(hooks/lib/fbot-ident.py, prj3#Issue832·839③) — `FBOT_ID == --by` 를 복제하지 않는다."""
    import importlib.util as _il
    _sp = _il.spec_from_file_location(
        "fbot_ident", os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "fbot-ident.py"))
    _m = _il.module_from_spec(_sp); _sp.loader.exec_module(_m)
    return _m


def cmd_decide(args) -> int:
    """C·L 전결 기록 — prj3#Issue756 (설계 SSOT `_doc_arch/decision-authority.md`).

    결정 권한 3등급 중 C(총괄)·L(팀장)은 사람에게 올리지 않고 **결정한다**. 그 대가가 기록이다:
    원장에 없는 전결은 daily «대신 결정한 것» 에 안 보여 사후 거부권이 무력해진다.
    `fbot_event` type=`decision` 1행 — detail 은 `[등급] 주제 → 결정`.
    """
    grade = (args.grade or "").strip().upper()
    if grade == "H":
        raise FbotError("H 등급은 전결 대상이 아니다 — mq `[컨펌] [H:<분류>]` 로 사람에게 올린다")
    if grade not in DECIDE_GRADES:
        raise FbotError(f"--grade 는 C|L 만 허용 (받음: {args.grade!r})")
    topic, decision = (args.topic or "").strip(), (args.decision or "").strip()
    if not topic or not decision:
        raise FbotError("--topic·--decision 은 비울 수 없다 — 무엇을 어떻게 정했는지가 기록의 전부다")
    # 사칭 차단 — `--by` 는 누구나 쓰는 문자열이다. 결정자 본인 세션(FBOT_ID)만 자기 이름으로 기록한다(엄격 — 사람 세션도 거부)
    err = _ident_mod().impersonation_error(args.by, "전결")
    if err:
        raise FbotError(err)
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            bot = fetch_bot(con, args.by)   # 미등록이면 fail-loud — 귀속 없는 결정 금지
            if bot["role"] not in DECIDE_ROLES[grade]:
                raise FbotError(f"{grade} 등급 결정 자격 없음 — {args.by} 은 role={bot['role']} "
                                f"(허용: {'·'.join(DECIDE_ROLES[grade])})")
            if bot["role"] == "chief" and not is_core_bot(bot):
                raise FbotError(f"{args.by} 은 상비 총괄이 아니다(parent 있음 — role=chief 이슈 워커)")
            if bot["career"] == "terminated" or (dict(bot).get("employment") or "") in ("terminated", "suspended"):
                raise FbotError(f"{args.by} 은 재직 상태가 아니다 — 결정 자격 없음")
            eid = record_event(con, args.by, "decision", f"[{grade}] {topic} → {decision}", args.ref or "")
            if not eid:
                raise FbotError("전결 기록 실패(fbot_event INSERT) — 기록 없는 결정은 결정이 아니다")
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
    finally:
        con.close()
    notify_hub_event(args.by, "decision", args.ref or "")
    emit({"ok": True, "action": "decide", "event_id": eid, "by": args.by, "grade": grade})
    return 0


def cmd_set_title(args) -> int:
    """표시 이름 변경 — prj3#Issue692. `bot_id` 는 원장·대장 참조 키라 바꾸지 않는다(그건 rename 이 아니라
    이관이다). 이름만 바꾸고 이력을 이벤트로 남긴다 — 누가 언제 무엇을 무엇으로 바꿨는지가 없으면
    보드에서 이름이 바뀐 봇을 다른 봇으로 오인한다."""
    title = (args.title or "").strip()
    if not title:
        raise FbotError("--title 이 비었다")
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            old = fetch_bot(con, args.bot_id)["title"]
            con.execute("UPDATE bot SET title = ? WHERE bot_id = ?", (title, args.bot_id))
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        try:
            record_event(con, args.bot_id, "set-title", f"{old} → {title}"[:80], args.reason or "")
        except Exception:
            pass                                  # 이벤트 기록 실패가 이름 변경을 되돌리지 않는다
        emit({"ok": True, "action": "set-title", "from": old, "bot": row_to_dict(fetch_bot(con, args.bot_id))})
    finally:
        con.close()
    return 0


def sid_marker_path(session_id: str, form: str = "", bot_id: str = "") -> str:
    """세션 id → bot_id 마커 파일 경로.

    heartbeat 훅의 **무비용 게이트**다 — "이 세션에 봇이 하나라도 결속돼 있는가" 를 파일
    존재만으로 답한다. DB 를 매 도구 호출마다 열 수는 없다(hook-rules 규칙3).

    ⚠️ Issue449 — 내용(bot_id)은 **권위가 아니다**. Agent 는 메인 세션의 session_id 를
    공유하므로 한 세션에 봇이 여럿 결속될 수 있고, 이 파일은 마지막 1건만 담는다.
    그래서 heartbeat 훅은 이 값을 쓰지 않고 `heartbeat --session-id` 로 넘긴다 —
    갱신 대상 판정은 DB 가 단일 지점이다. 내용은 진단용으로만 남긴다.
    """
    # 주입구 FBOT_HANDOFF_DIR 은 **테스트 전용**이다 — 운영에선 설정하지 않는다
    #   (hub-scope.sh 의 HUB_PROJECTS_DIR 선례). 이것이 없어서 2026-09-06 테스트가
    #   운영 마커 디렉토리에 `sid-fresh`·`sid-intruder` 를 남겼다. 훅(bash)은 이 값을
    #   읽지 않으므로 운영 경로는 양쪽이 하드코딩으로 일치한 채 유지된다.
    # prj3#Issue616 — Agent 하청은 **부모와 같은 session_id** 를 쓴다. 한 파일을 나눠 쓰면
    #   하청 bind 가 부모 마커를 덮고 done 이 그것을 지워, 살아 있는 부모 세션이 원장에서
    #   퇴근으로 뒤집힌다(실측 2026-09-10: checkin→working→checkout 2회 + 가드 무력화).
    #   Issue449 는 소비자마다 *"마커를 믿지 마라"* 로 우회했을 뿐 **원인은 남겼다** — 그래서
    #   Issue612 의 새 소비자(writeguard)가 같은 자리에서 다시 빠졌다. 슬롯 자체를 가른다.
    #   세션 슬롯(`sid-<SID>.id`)은 **오직 세션 결속**의 것이다. 훅(bash)이 읽는 경로가
    #   이것이므로, 하청이 무엇을 하든 부모의 마커는 그 자리에 남는다.
    return _ident_mod().sid_marker_path(session_id, form, bot_id)   # prj3#Issue960 — 경로 계산은 fbot-ident 한 곳


def write_sid_marker(session_id: str, bot_id: str, form: str = "") -> None:
    if not session_id:
        return
    path = sid_marker_path(session_id, form, bot_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(bot_id + "\n")
    except OSError:
        pass  # 마커는 캐시다 — 실패해도 DB 결속은 유효하다


def drop_sid_marker(session_id: str) -> None:
    """인계로 결속을 잃은 세션의 마커를 지운다 (Issue547).

    남겨 두면 heartbeat 훅이 **뺏긴 세션에서** lease 를 계속 갱신해, 원장은 새 세션을
    가리키는데 lease 는 옛 세션이 살리는 어긋남이 생긴다.
    """
    if not session_id:
        return
    paths = [sid_marker_path(session_id),
             sid_marker_path(session_id).replace(".id", ".hb")]
    # prj3#Issue616 — 하청 슬롯(`sid-<SID>.agent-*.id`)도 함께 거둔다. 세션이 결속을 잃으면
    #   그 아래 하청 슬롯은 주인 없는 파일이 된다(누수). glob 실패는 무시 — 캐시다.
    try:
        import glob as _glob
        paths += _glob.glob(sid_marker_path(session_id).replace(".id", ".agent-*.id"))
    except Exception:
        pass
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass  # 마커는 캐시다 — 없어도 DB 결속이 정본이다


def evict_tombstone_path(session_id: str, bot_id: str) -> str:
    """인계로 밀려난 세션 앞으로 남기는 **툼스톤** 경로 (Issue645).

    `drop_sid_marker` 가 *닫는 일* 이라면 이것은 *알리는 일* 이다. 둘은 다른 일이라 한쪽이
    다른 쪽을 대신하지 못한다 — 마커를 지우면 그 세션의 fbot 훅이 전부 침묵하므로
    (게이트가 곧 마커다) 인계 사실을 전할 경로가 **0개**가 된다.

    ⚠️ 한 세션이 봇 여럿에 결속될 수 있으므로(Agent 1:N) **봇별로 한 파일**이다. 세션당
    1파일에 누적하면 두 번째 인계가 첫 번째를 덮어 하나가 통째로 사라진다.
    ⚠️ 확장자는 `.id`·`.hb`·`.agent-*.id` 와 겹치지 않게 둔다 — `drop_sid_marker` 의 수거
    대상에 걸리면 알리기도 전에 지워진다.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", bot_id or "anon")
    base = os.path.dirname(sid_marker_path(session_id))
    return os.path.join(base, f"sid-{session_id}.evicted-{safe}.tomb")


def write_evict_tombstone(session_id: str, bot_id: str, successor: str,
                          kind: str = "evicted") -> None:
    """결속이 끊긴 세션이 **다음 프롬프트에서** 읽을 통보를 남긴다 (Issue645·Issue675).

    내용은 `KEY=value` 평문이다 — 읽는 쪽이 bash 훅이라 JSON 이면 파싱에 프로세스가 하나 더
    든다(hook-rules 규칙3: 게이트도 소비도 무비용이어야 한다).

    ⚠️ **`kind` 는 사유이지 장식이 아니다** (Issue675). 「인계」와 「퇴근」은 세션에
    요구하는 행동이 다르다 — 인계는 *재결속*(승계자가 가져갔다), 퇴근은 *재출근*(아무도
    안 받았고 lease 만 끊겼다)이다. 같은 문구를 쓰면 세션이 엉뚱한 행동을 한다.

    ⚠️ **파일명 패턴은 바꾸지 않는다.** `fbot-evict-nudge.sh` 의 게이트는 glob **1회**가
    전부고(무비용 원칙), 사유별로 파일명을 가르면 glob 이 사유 수만큼 는다. 분기는
    파일 *안* 에서 한다 — 어차피 읽는 파일이다.

      kind=evicted — 남이 가져갔다 (successor 있음) → 재결속
      kind=reaped  — lease 만료로 강제 퇴근됐다 (successor 없음) → 재출근
    """
    if not session_id:
        return
    path = evict_tombstone_path(session_id, bot_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"bot_id={bot_id}\n")
            fh.write(f"kind={kind or 'evicted'}\n")
            fh.write(f"successor={successor or ''}\n")
            now = int(time.time())
            fh.write(f"at={now}\n")
            # 사람이 읽는 시각은 **여기서** 만든다 — 읽는 쪽(bash)이 하면 `date -r`(BSD) 과
            #   `date -d @`(GNU) 로 갈리고 fork 가 하나 더 든다
            fh.write("at_human=" + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)) + "\n")
    except OSError:
        pass  # 통보 실패가 인계를 되돌리지는 않는다 — 결속은 이미 커밋됐다


def bind_occupancy_verdict(row, incoming_sid, now=None):
    """기존 세션 결속의 점유 상태를 **3값**으로 판정한다 (Issue547).

    🔴 부울로 만들지 않는 이유는 Issue445 와 같다 — "모른다" 를 표현할 수 없는 판정은
    참인 순간 판정을 통째로 건너뛰어 fail-open 이 된다. 그 실수를 pane 판정에서 이미
    두 번 했다(Issue419 미탐 · Issue439 오탐).

    반환: (verdict, 점유 세션 id)
      free    — 미점유이거나 **자기 자신의 재결속**. 그대로 진행
      released — 점유 세션이 이미 **퇴근**(`checkout`)했다. 점유자가 없다 — 인계 기록 없이 진행 (prj3#Issue749)
      dead    — lease 만료. 인계 가능
      idle    — lease 유효하나 점유 세션이 `waiting_input`(사용자 입력 대기). 인계 가능 (Issue554)
      alive   — lease 유효. 남이 쓰는 중이므로 거부
      unknown — 결속은 있는데 lease 가 없다. 판정 불가이므로 **사람에게 묻는다**
    """
    cur = (row["session_id"] or "") if "session_id" in row.keys() else ""
    if not cur or cur == incoming_sid:
        return "free", None
    # prj3#Issue749 — 퇴근은 몸체가 끝났다는 **기록된 사실**이다. checkout 전이는 lease 를 지우지 않아
    #   퇴근 직후(lease 5분 안) 같은 봇을 다시 띄우면 전 몸체가 «alive» 로 판정돼 결속이 거부됐다 —
    #   질문 답 재기동·퇴근 재기상 몸체가 결속 마커 없이 돌아 Stop 중계·넛지·하트비트가 침묵했다
    #   (2026-09-28 E2E 실측). 밀려난 세션이 아니므로 인계 기록·툼스톤도 남기지 않는다.
    if ("state" in row.keys()) and row["state"] == "checkout":
        return "released", cur
    exp = row["lease_expires"] if "lease_expires" in row.keys() else None
    if exp is None:
        return "unknown", cur
    if int(exp) <= (now or int(time.time())):
        return "dead", cur
    # prj3#Issue554 — 점유 세션이 사용자 입력을 기다리는 중이면 **idle** 이다. lease 는 살아
    #   있지만 그 세션은 지금 이 봇으로 일하고 있지 않다. 인계를 허용하되 `evicted_session`
    #   으로 사실을 남긴다 — 그 세션은 다음 프롬프트의 whois 에서 인계를 알고 인박스로 간다.
    st = row["state"] if "state" in row.keys() else None
    if st == "waiting_input":
        return "idle", cur
    return "alive", cur


_ORG_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-org.py")


def _is_nonexec(role, on_error=True) -> bool:
    """관리직(총괄·팀장) 판정 — 카탈로그 `nonexec` 단일 지점(fbot-org.is_nonexec, prj3#Issue757).
    매 호출 적재한다(FBOT_CATALOG 주입을 테스트가 바꾼다 — 결속은 드물어 비용이 없다).
    적재 실패 값은 호출처가 정한다 — 사람 결속 제한은 True(fail-open: 판정 재료가 없을 때 정상 결속을 막는
    피해가 더 크다) · 몸체 원장은 False(fail-closed: 종전 1:1 로 떨어져 워커가 다중 몸체로 새지 않는다)."""
    try:
        import importlib.util as _il
        _sp = _il.spec_from_file_location("fbot_org_nx", _ORG_PY)
        _om = _il.module_from_spec(_sp); _sp.loader.exec_module(_om)
        return bool(_om.is_nonexec(role))
    except Exception:
        return on_error


# ── 관리직 몸체 원장 (prj3#Issue757 T15 — 설계 fbot-arch §다중성 «몸체 원장 — T15-0») ──────────────────
#   관리직(총괄·팀장)은 지휘 흐름마다 몸체 1 — 봇 1 : 몸체 M. 워커는 종전 bot 행 1:1 그대로(산출물 귀속 F4).
#   스위치 `fbot_manager_multibody`(policy) 가 꺼져 있으면 관리직도 종전 1:1 판정이다 — 운영 문제 시 코드 되돌림 없이 끈다.
BODY_KIND = "fbot_body"
BODIES_MAX_DEFAULT = {"chief": 3, "lead": 2}      # 권장 출발값(plan 열린 질문 19) — policy 키가 우선


def _policy_value(key, default=None):
    """평탄 키 1개. 같은 키가 여러 번이면 **마지막 값** — YAML·fbot-lead/hr-gate 로더와 같은 규칙(덧붙인 값이 이긴다)."""
    path = _policy_path()
    if not os.path.exists(path):
        return default
    val = default
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^" + re.escape(key) + r":\s*([^#\s]+)", line)
            if m:
                val = m.group(1)
    return val


def multibody_enabled() -> bool:
    return str(_policy_value("fbot_manager_multibody", "false")).lower() in ("true", "1", "yes", "on")


def bodies_max(role) -> int:
    v = _policy_value(f"fbot_manager_bodies_max_{role}")
    try:
        return int(v) if v is not None else BODIES_MAX_DEFAULT.get(role, 1)
    except ValueError:
        return BODIES_MAX_DEFAULT.get(role, 1)


def open_bodies(con, bot_id, now=None):
    """살아 있는 몸체 — status open · lease 유효(만료분은 reap 전이라도 산 것으로 치지 않는다)."""
    now = now or int(time.time())
    out = []
    for r in con.execute("SELECT id, payload, lease_until FROM job WHERE kind=? AND owner=? AND status='open'",
                         (BODY_KIND, bot_id)).fetchall():
        if r["lease_until"] is not None and int(r["lease_until"]) <= now:
            continue
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            pl = {}
        out.append({"id": r["id"], "session_id": pl.get("session_id"), "flow": pl.get("flow"), "pane": pl.get("pane"),
                    "lease_until": r["lease_until"], "state": pl.get("state") or "working",
                    "started_at": int(pl.get("started_at") or 0)})
    return out


def session_bodies(con, sid):
    """이 세션의 open 몸체 — [(body_id, owner)]. heartbeat·idle·퇴근이 몸체 단위로 갱신할 대상."""
    return [(r["id"], r["owner"]) for r in con.execute(
        "SELECT id, owner FROM job WHERE kind=? AND status='open' AND json_extract(payload,'$.session_id')=?",
        (BODY_KIND, sid)).fetchall()]


def sid_body(con, bot_id, sid):
    """이 봇의 같은 sid open 몸체 — **lease 무관**(prj3#Issue882: 만료·reap 전 몸체도 내 몸체다). 없으면 None.
    반환 dict 는 `open_bodies` 와 같은 키 + `expired`(now 기준은 호출자가 `body_revive` 로 판정)."""
    for r in con.execute("SELECT id, payload, lease_until FROM job WHERE kind=? AND owner=? AND status='open'"
                         " ORDER BY lease_until DESC", (BODY_KIND, bot_id)).fetchall():
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            pl = {}
        if sid and pl.get("session_id") == sid:
            return {"id": r["id"], "session_id": sid, "flow": pl.get("flow"), "pane": pl.get("pane"),
                    "lease_until": r["lease_until"], "state": pl.get("state") or "working",
                    "started_at": int(pl.get("started_at") or 0)}
    return None


def body_revive(con, row, body, now):
    """같은 sid 몸체의 재결속·갱신 판정 — 결속(`body_join_verdict`·`body_bind`)과 heartbeat 가 **같은 헬퍼**(Issue882).
    반환 `"rebind"`(lease 유효 — 검사 없음, 이미 셈에 들어 있다) · `"rebind_expired"`(만료 되살림 — 입장 검사 통과).
    만료 몸체를 되살리는 것은 «새 입장» 이라 같은 흐름에 다른 살아 있는 몸체가 있거나 상한이면 FbotError(거부)."""
    if body["lease_until"] is None or int(body["lease_until"]) > now:
        return "rebind"
    body_admit(con, row, body["flow"], now)     # open_bodies 는 만료분을 빼므로 자기 자신은 셈에 안 든다
    return "rebind_expired"


def project_bot(con, bot_id, now=None):
    """봇 행 = 몸체들의 사영 (T15-0) — session_id 최근 몸체 · lease 최댓값 · 하나라도 working 이면 working.
    살아 있는 몸체가 없으면 손대지 않는다(퇴근·reap 은 각자의 경로가 한다). 출근 직후(checkin)·하위 대기는 보존."""
    bodies = open_bodies(con, bot_id, now)
    if not bodies:
        return None
    latest = max(bodies, key=lambda b: (b["started_at"], b["id"]))
    lease = max(int(b["lease_until"] or 0) for b in bodies)
    agg = "working" if any(b["state"] != "waiting_input" for b in bodies) else "waiting_input"
    con.execute("UPDATE bot SET session_id=?, lease_expires=?,"
                " state = CASE WHEN state IN ('working','waiting_input') THEN ? ELSE state END WHERE bot_id=?",
                (latest["session_id"], lease or None, agg, bot_id))
    return agg


def body_admit(con, row, flow, now, bodies=None):
    """새 몸체를 받을 수 있나 — 흐름 잠금·몸체 상한. 거부는 FbotError. 결속(`body_bind`)과 HR `wake`(몸체 추가)가
    같은 함수를 쓴다(prj3#Issue757 T15 ③ — 판정을 두 벌 두면 갈라진다)."""
    bodies = open_bodies(con, row["bot_id"], now) if bodies is None else bodies
    same = next((b for b in bodies if b["flow"] == flow), None)
    if same:
        raise FbotError(f"{row['bot_id']} 의 흐름 {flow} 은 이미 몸체({(same['session_id'] or '')[:8]})가 지휘 중이다 — "
                        "한 흐름에 몸체 둘은 금지(흐름 잠금, prj3#Issue757 T15)")
    cap = bodies_max(row["role"])
    if len(bodies) >= cap:
        raise FbotError(f"{row['bot_id']}({row['role']}) 몸체 상한 {cap} 에 닿았다 — 살아 있는 몸체 {len(bodies)}개. "
                        "새 흐름은 인박스에서 기다린다(prj3#Issue757 T15)")
    return bodies


FLOW_SOURCE_KINDS = ("fbot_request", "fbot_dispatch")   # 흐름을 여는 원장 — 인박스 기상(요청 id)·dispatch(배분 id)


def body_join_verdict(con, row, flow, pane=None, now=None, sid=None):
    """출근 훅 탈취 가드(prj3#Issue679)의 관리직 몸체 추가 예외 — prj3#Issue843. 반환 (admit, reason).

    가드는 bot 행의 단일 session_id 만 봐서 `FBOT_FLOW` 로 뜬 두 번째 흐름 몸체까지 탈취로 거부했다 — 스폰
    배선(HR `wake --flow`·dispatch 흐름 잠금)과 갈라진 한쪽. 통과는 전부 성립할 때만(fail-closed = 종전 거부):
    스위치 on · 관리직 · 흐름이 이 봇 앞으로 열린 open 요청·배분 · pane 이 기존 몸체 pane 과 다름 ·
    흐름 잠금·상한(`body_admit` — 결속과 같은 함수). 이미 몸체가 있는 흐름 = 자식 상속이라 거부가 유지된다.
    «기존 몸체 pane» = bot.tmux_target(최근 결속) + open 몸체 전부의 `payload.pane` — 훅 바깥 가드가 tmux_target
    과 같은 pane 은 이미 통과시키므로 tmux_target 만 보면 이 분기는 도달 불가다(QA ②). 자식 claude 는 부모 pane 을
    상속하므로 흐름이 달라도 몸체 pane 에서 뜬 세션은 새 흐름 몸체가 아니다.
    `sid` 가 이미 이 봇의 open 몸체면 재결속(rebind) — 흐름2 결속으로 bot.session_id·tmux_target 이 바뀐 뒤 흐름1
    몸체가 compact·resume(같은 sid)으로 출근 훅을 다시 타면 바깥 가드가 성립한다. 같은 sid 는 탈취일 수 없으므로
    흐름·pane 판정보다 먼저 허용한다(QA 재판정 회귀 — FBOT_FLOW 없이 선 `session:` 흐름 몸체도 같다)."""
    flow = (flow or "").strip()
    if not multibody_enabled():
        return False, "switch_off"
    if not _is_nonexec(row["role"], on_error=False):
        return False, "not_manager"
    now = now or int(time.time())
    bodies = open_bodies(con, row["bot_id"], now)
    mine = sid_body(con, row["bot_id"], sid) if sid else None
    if mine:                       # prj3#Issue882 — 만료·reap 전 같은 sid 도 내 몸체(입장 검사는 body_revive)
        try:
            return True, body_revive(con, row, mine, now)
        except FbotError as e:
            return False, str(e)
    if not flow:
        return False, "no_flow"
    # 흐름의 수신자 — 배분은 owner 가 **배분자**라 대상은 payload.worker_bot_id(원장 실측) · 요청은 owner 가 받는 봇
    #   (팀원 질문은 payload.to_lead). 이 봇이 내보낸 배분 id 는 이 봇의 흐름이 아니다
    src = con.execute("SELECT kind, status, owner, json_extract(payload,'$.to_lead') AS to_lead,"
                      " json_extract(payload,'$.worker_bot_id') AS worker FROM job WHERE id=?", (flow,)).fetchone()
    if src is None or src["kind"] not in FLOW_SOURCE_KINDS or src["status"] != "open":
        return False, "flow_not_opened"
    to = (src["worker"],) if src["kind"] == "fbot_dispatch" else (src["owner"], src["to_lead"])
    if row["bot_id"] not in to:
        return False, "flow_not_opened"
    if pane and pane in {row["tmux_target"] or ""} | {b["pane"] for b in bodies if b["pane"]}:
        return False, "same_pane"
    try:
        body_admit(con, row, flow, now, bodies)
    except FbotError as e:
        return False, str(e)
    return True, "new_flow_body"


def cmd_body_join(args) -> int:
    """출근 훅 전용 판정 — rc 0 = 몸체 추가로 결속 허용, rc 3 = 종전 거부 유지 (prj3#Issue843).

    `--session-id` 가 있으면 **판정과 몸체 기록이 한 트랜잭션**이다(BEGIN IMMEDIATE) — 판정만 하고 기록을 뒤따르는
    `bind` 에 맡기면 같은 흐름 두 세션이 동시에 판정을 통과하고, 진 쪽의 흐름 잠금 FbotError 는 훅의 fail-soft
    (`|| true`)가 삼켜 둘 다 출근했다(QA ① TOCTOU 재현 7/10). 이긴 쪽 몸체가 먼저 서므로 뒤따르는 `bind` 는 reuse.
    now 는 **한 번만** 구해 판정과 기록에 같이 넘긴다 — 따로 구하면 그 사이 초 경계에서 흐름1 몸체 lease 가 만료될 때
    판정 `rebind`(허용) 뒤 `body_bind` 가 자기 몸체를 못 찾고 flow "" 새 몸체·`body-open` 을 썼다(QA 3차 ③ 재현).
    `rebind` 인데 기록이 reuse 가 아니면 거부로 되돌린다(fail-closed — 재결속은 새 몸체를 만들지 않는다).
    `--session-id` 없으면 쓰기 없는 판정만(원장 조회용)."""
    flow = args.flow or os.environ.get("FBOT_FLOW")
    con = connect()
    body = None
    try:
        if args.session_id:
            con.execute("BEGIN IMMEDIATE")
        try:
            row = fetch_bot(con, args.bot_id)
            now = int(time.time())
            admit, reason = body_join_verdict(con, row, flow, args.pane, now=now, sid=args.session_id)
            if admit and args.session_id:
                body = body_bind(con, row, args.session_id, (flow or "").strip(), None, now, lease_ttl_secs(), args.pane)
                if reason in ("rebind", "rebind_expired") and body[0] != "reuse":
                    admit, reason, body = False, "rebind_not_reuse", None
        except Exception:
            if args.session_id:
                con.execute("ROLLBACK")
            raise
        if args.session_id:
            con.execute("COMMIT" if admit else "ROLLBACK")
        if args.session_id and reason.startswith("rebind"):
            # prj3#Issue905 — 재결속 계측. 거부(rebind_not_reuse)는 위에서 ROLLBACK 됐으니 트랜잭션 밖에서 남긴다
            record_event(con, args.bot_id, "rebind", f"{reason} · {args.session_id[:8]}", body[1] if body else "")
    finally:
        con.close()
    out = {"ok": True, "action": "body-join", "bot_id": args.bot_id, "admit": admit, "reason": reason}
    if body:
        out["body"] = {"action": body[0], "id": body[1]}
    emit(out)
    return 0 if admit else 3


def body_bind(con, row, sid, flow, form, now, ttl, pane=None):
    """관리직 몸체 결속 판정·기록 — 호출자의 트랜잭션 안. 반환 (action, body_id). 거부는 FbotError.
    같은 세션 = 재결속(reuse) · 같은 흐름의 다른 살아 있는 몸체 = 흐름 잠금 · open 몸체 수 ≥ 상한 = 거부.
    pane 은 몸체별로 남긴다 — 출근 가드의 «기존 몸체 pane» 비교 대상(prj3#Issue843 QA ②)."""
    mine = sid_body(con, row["bot_id"], sid)       # prj3#Issue882 — lease 만료·reap 전도 같은 몸체(새 행 금지)
    if mine:
        body_revive(con, row, mine, now)           # 만료 되살림이면 입장 검사 — 거부는 FbotError
        con.execute("UPDATE job SET lease_until=? WHERE id=?", (now + ttl, mine["id"]))
        if pane and not mine["pane"]:
            con.execute("UPDATE job SET payload=json_set(payload,'$.pane',?) WHERE id=?", (pane, mine["id"]))
        return "reuse", mine["id"]
    bodies = open_bodies(con, row["bot_id"], now)
    body_admit(con, row, flow, now, bodies)
    bid = f"fbotbody-{now}-{uuid.uuid4().hex[:8]}"
    con.execute("INSERT INTO job (id, store, kind, status, payload, result, attempts, owner, lease_until, blocked_since, created_at)"
                " VALUES (?,?,?,?,?,NULL,0,?,?,NULL,?)",
                (bid, "fbot", BODY_KIND, "open",
                 json.dumps({"session_id": sid, "flow": flow, "form": form, "started_at": now, "state": "working",
                             **({"pane": pane} if pane else {})}, ensure_ascii=False),
                 row["bot_id"], now + ttl, now))
    record_event(con, row["bot_id"], "body-open", f"{flow} · {sid[:8]}", bid)
    return "new", bid


def cmd_bind(args) -> int:
    """실행 형태(pane·세션)를 봇 레코드에 결속한다 (Issue448 ②).

    ⚠️ 값이 없으면 **NULL 을 유지**하고 오류를 내지 않는다. Agent(서브에이전트) 실행
    형태는 tmux pane 이 원래 없기 때문이다. NULL 은 "미등록" 이 아니라 "pane 기반
    판정 불가" 다 — 소비처는 이 둘을 반드시 구분해야 한다.

    🔴 **세션 결속은 선점을 판정한다 (Issue547).** 종전에는 기존 `session_id` 를 조건
    없이 덮어썼다. 상비 게이트 3종(exec·hr·recruit)은 `_hq.yml` 이 못박은 **전역 단일**
    개체라 복수화로 피할 수도 없다 — 두 세션이 같은 봇을 부르면 뒤에 온 쪽이 앞을
    조용히 끊고, 끊긴 세션은 자기가 여전히 그 봇인 줄 알고 계속 일한다.
    """
    form = validate_form(getattr(args, "form", None))
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            row = fetch_bot(con, args.bot_id)    # 미등록이면 fail-loud
            # prj3#Issue757 I ⓑ — *"인간의 지시를 받는 것은 총괄과 팀장 뿐"*. `--form session` 이면서
            #   `FBOT_ID` 가 그 봇이 아닌 결속은 **사람 세션이 봇의 몸체가 되는** 경로(`/fbot-bind`)다.
            #   워커 몸체는 배분 스폰(FBOT_ID 출근)·팀장의 `Agent(name=…)`(form=agent) 로만 선다.
            #   prj3#Issue820 — `--form` 생략도 판정 안이다. 출근 훅(form 없음·FBOT_ID=그 봇)만 스폰 경로로
            #   인정하고, 그 밖의 form 생략(FBOT_ID 부재·다른 봇)은 사람 경로로 **보수 판정**(session 과 같은 규칙).
            if (form in ("session", None) and os.environ.get("FBOT_ID", "") != args.bot_id
                    and not _is_nonexec(row["role"])):
                raise FbotError(
                    f"{args.bot_id}(role={row['role']}) 는 사람 세션이 결속하지 않는다 — 사람의 지시는 "
                    f"총괄·팀장이 받는다(Issue757). 요청은 그 팀장 인박스로 보낸다: "
                    f"python3 ~/.claude/hooks/fbot-inbox.py send --to {args.bot_id} --body '<요청>' "
                    f"(워커 수신은 그 팀장에게 돌려 적재된다)")
            evicted = None
            body = None
            if args.session_id and multibody_enabled() and _is_nonexec(row["role"], on_error=False):
                # prj3#Issue757 T15 — 관리직은 흐름마다 몸체 1. 종전 1:1 점유 판정 대신 몸체 원장이 판정한다
                flow = (getattr(args, "flow", None) or os.environ.get("FBOT_FLOW") or f"session:{args.session_id}")
                body = body_bind(con, row, args.session_id, flow, form, int(time.time()), lease_ttl_secs(),
                                 args.tmux_target or None)
            elif args.session_id:                # 지우는 것(빈 문자열)은 선점 대상이 아니다
                verdict, holder = bind_occupancy_verdict(row, args.session_id)
                if verdict in ("alive", "unknown") and not getattr(args, "takeover", False):
                    # ROLLBACK 은 바깥 except 가 한다 — 여기서 먼저 걷으면
                    #   "cannot rollback - no transaction is active" 로 원인이 가려진다
                    raise FbotError(
                        f"{args.bot_id} 는 이미 결속돼 있다 (점유 판정: {verdict}).\n"
                        f"  점유 세션: {holder}\n"
                        + ("  lease 가 유효하다 — 그 세션이 지금 이 봇으로 일하는 중이다.\n"
                           if verdict == "alive" else
                           "  lease 기록이 없어 생사를 판정할 수 없다.\n")
                        + f"  인계하려면: --takeover (⚠️ 점유 세션은 결속을 잃는다)"
                    )
                if verdict not in ("free", "released"):
                    evicted = holder
            sets, params = [], []
            if args.tmux_target is not None:
                sets.append("tmux_target = ?"); params.append(args.tmux_target or None)
            if args.session_id is not None:
                sets.append("session_id = ?"); params.append(args.session_id or None)
            if form is not None:
                # Issue495 — 결속 시점이 형태를 **확정**하는 자리다. PreToolUse(`Agent`)
                #   훅이 부르면 그 봇은 Agent 형태이고, 그 사실은 여기서만 알 수 있다.
                sets.append("form = ?"); params.append(form)
            if evicted:
                # prj3#Issue554 — 인계는 **몸이 바뀌는 것**이다. 전 세션이 남긴 `working`·current_task 를
                #   그대로 두면 새 세션의 출근 전이(checkin)가 "작업중 → 출근중 불법" 으로 거부되고
                #   (2026-09-06 실측 2회: e8e1a768·126fbcb0 모두 이 자리에서 막혀 출근 없이 진행),
                #   조직도에는 전 세션의 일이 지금 일로 남는다. 전 몸은 퇴근시키고 새 몸이 출근한다.
                sets.append("state = 'checkout'")
                sets.append("last_task = COALESCE(current_task, last_task)")
                sets.append("current_task = NULL")
            if sets:
                params.append(args.bot_id)
                con.execute(f"UPDATE bot SET {', '.join(sets)} WHERE bot_id = ?", params)
            if evicted:
                record_event(con, args.bot_id, "evict", f"세션 인계 {evicted[:8]} → {(args.session_id or '')[:8]}")   # prj3#Issue575
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        if evicted:
            drop_sid_marker(evicted)             # 뺏긴 세션이 lease 를 살리지 못하게
            # Issue645 — **닫는 일과 알리는 일은 다르다.** 위 한 줄은 lease 만 끊을 뿐이고,
            #   마커가 사라지는 순간 그 세션의 fbot 훅 4종이 전부 침묵한다(게이트가 마커다).
            #   밀려난 세션이 스스로 의심할 이유는 없으므로 인계 사실을 툼스톤으로 남긴다.
            write_evict_tombstone(evicted, args.bot_id, args.session_id or "")
            notify_hub_event(args.bot_id, "evict")
        if args.session_id:
            # form 을 넘겨 **하청은 자기 슬롯에** 쓴다(prj3#Issue616). 세션 슬롯 불변
            write_sid_marker(args.session_id, args.bot_id, getattr(args, "form", "") or "")
        out = {"ok": True, "action": "bind", "bot": row_to_dict(fetch_bot(con, args.bot_id))}
        if body:
            out["body"] = {"action": body[0], "id": body[1]}   # prj3#Issue757 T15
        if evicted:
            out["evicted_session"] = evicted     # 인계 사실은 숨기지 않는다
        emit(out)
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

DISPATCH_KIND = "fbot_dispatch"       # 조직도·팀장핀봇이 공용하는 배분 원장 kind
# 사후 기록 전용 status — `open` 을 쓰지 않는 근거는 cmd_dispatch_record 참조.
DISPATCH_LOGGED = "logged"


def norm_issue(text: str) -> str:
    """이슈 표기 정규화 — 중복 기록 판정에만 쓴다.

    같은 배분을 팀장핀봇은 ``Issue335`` 로, fpm-do 는 ``prj42#Issue335`` 로 부른다.
    문자열을 그대로 비교하면 같은 사건이 원장에 두 줄이 되어 "배분 2회" 라는 거짓말이 된다.
    """
    t = (text or "").strip().lower()
    if _BARE_ISSUE_RE.match(t):
        # prj3#Issue761 — `dispatch --issue 727`(맨 숫자)이 원장에 그대로 남았다. 여기서 `727` 과
        #   fpm-do 의 `prj3#Issue727` 을 다른 일로 보자 같은 일이 두 행(open·logged)이 됐다
        return "issue" + t
    m = re.findall(r"issue[_-]?(\d+(?:_\d+)*)", t)
    return "issue" + m[-1] if m else t


_BARE_ISSUE_RE = re.compile(r"^\d+(?:_\d+)*$")      # 맨 숫자 이슈 번호 — `727`·`7_2` (문장 전체가 번호일 때만)


def canon_issue(text: str) -> str:
    """이슈 식별자 **기록 형식** 정규화 (prj3#Issue761) — 맨 숫자 `727` → `Issue` 접두. 나머지는 그대로.

    원장 `payload.issue` 는 조인 키다 — sweep 의 완료 대조(`issue_completed_in` 은 `Issue<N>:` 헤더를 찾는다)·
    이슈맵 오버레이·중복 판정이 모두 `Issue<N>` 형식을 전제한다. 맨 숫자로 적힌 배분은 어느 것에도 안 걸려
    영구 잔류했다. 쓰는 자리(`fbot-lead dispatch`)와 읽는 자리(sweep 대조)가 같은 함수를 쓴다."""
    t = (text or "").strip()
    return "Issue" + t if _BARE_ISSUE_RE.match(t) else t


def _issue_prj(issue: str, prj=None):
    """이슈의 prj — **필드가 정본**, 표기 접두(`prj42#`)는 필드 없는 구형 기록의 보조."""
    if prj not in (None, ""):
        try:
            return int(prj)
        except (TypeError, ValueError):
            pass
    m = re.findall(r"prj(\d+)#", (issue or "").lower())
    return int(m[-1]) if m else None


def same_issue(a: str, b: str, prj_a=None, prj_b=None) -> bool:
    """두 이슈 표기가 같은 이슈인가 — ``norm_issue`` + **prj 접두 충돌 검사** (prj3#Issue699_6).

    ``Issue335`` ↔ ``prj42#Issue335`` 는 같다(접두 생략 허용). 그러나 ``prj3#Issue335`` ↔
    ``prj42#Issue335`` 는 번호만 같은 **다른 이슈**다 — norm_issue 만 쓰면 이 둘이 합쳐진다.
    fbot-lead 는 prj 를 ``payload.prj`` 필드로 따로 적는다(`issue=Issue5, prj=42`) — 필드를 먼저 본다.
    """
    if norm_issue(a) != norm_issue(b):
        return False
    pa, pb = _issue_prj(a, prj_a), _issue_prj(b, prj_b)
    return not (pa is not None and pb is not None and pa != pb)


ISSUE_ID_RE = re.compile(r"^(prj\d+#)?Issue\d+(_\d+)*$")   # 원장 조인 키 — 이슈맵·hub 가 이 형식으로 잇는다
LINEAGE_LIVE = ("open", "blocked", "logged", "deferred")      # 미종결 배분 술어 단일 지점 — fbot-lead `active_dispatches` 도 이것을 읽는다(prj3#Issue795)
LINEAGE_LIVE_SQL = ",".join("?" * len(LINEAGE_LIVE))           # `status IN (…)` 자리표시자 — 술어 길이가 바뀌어도 따라간다
# prj3#Issue929 — «완료 미확인» 어휘 단일 지점. fbot-inbox(defer 검증·통지 종결)·fbot-lead(sweep 판정)·
#   fbot-manual-review(blocked_rate 집계 제외)가 이것을 읽는다 — 세 곳에 리터럴을 두면 한쪽만 바뀌어 갈라진다
REPORT_STATUSES = ("done", "incomplete")   # 워커 보고(defer --status)의 명시 결과 — 마지막 명시가 done 이 아니면 미확인
UNCONFIRMED = "unconfirmed"                # 배분 `payload.blocked_by` 사유 = 인박스 통지 kind(`fbot_request.payload.kind`)


def dispatch_lineage(con, by, explicit=None, flow=None) -> dict:
    """배분 계보 판정 단일 지점 (prj3#Issue739 M1-2 — 설계 fbot-arch §작업 기록 «배분 계보·이슈 연결 필드»).

    `fbot-lead dispatch` 와 `dispatch-record` 가 같이 쓴다 — 정규 배분만 계보를 갖고 사후 기록이 고아로 남으면
    캐스케이드가 그 자리에서 다시 끊긴다. 반환 {parent_dispatch_id, root_dispatch_id, parent_ambiguous}.
    root 가 None 이면 호출자가 **자기 id** 로 채운다(부모 없음 = 자기가 root).
      ① `explicit`(`--parent-dispatch`) — 없는 배분이면 FbotError
      ② `flow`(env `FBOT_FLOW`)가 배분자가 worker 인 미종결 배분이면 그것 — prj3#Issue757 T15: 다중 몸체 관리직은
         흐름마다 받은 배분이 따로라 ③ 이 늘 모호해진다. 몸체가 쥔 흐름이 곧 부모다
      ③ 배분자가 worker 인 미종결 배분이 정확히 1건이면 그것 · 0건이면 root · 2건+ 이면 null + ambiguous(고르지 않는다)
    root 는 부모의 `root_dispatch_id`, 없으면(구 레코드 — 소급하지 않는다) 부모 id."""
    rows = {}
    for jid, status, raw in con.execute("SELECT id, status, payload FROM job WHERE kind = ?", (DISPATCH_KIND,)).fetchall():
        try:
            rows[jid] = (status, json.loads(raw or "{}"))
        except (ValueError, TypeError):
            continue

    def _root(pid):
        return rows[pid][1].get("root_dispatch_id") or pid

    if explicit:
        if explicit not in rows:
            raise FbotError(f"--parent-dispatch {explicit}: 원장에 없는 배분")
        return {"parent_dispatch_id": explicit, "root_dispatch_id": _root(explicit), "parent_ambiguous": False}
    live = [jid for jid, (st, pl) in rows.items() if st in LINEAGE_LIVE and pl.get("worker_bot_id") == by]
    if flow and flow in live:
        return {"parent_dispatch_id": flow, "root_dispatch_id": _root(flow), "parent_ambiguous": False}
    if len(live) == 1:
        return {"parent_dispatch_id": live[0], "root_dispatch_id": _root(live[0]), "parent_ambiguous": False}
    return {"parent_dispatch_id": None, "root_dispatch_id": None, "parent_ambiguous": len(live) > 1}


def lineage_fields(lin, job_id) -> dict:
    """payload 에 싣는 계보 필드 — root 가 없으면 자기 id, ambiguous 는 참일 때만 싣는다."""
    out = {"parent_dispatch_id": lin["parent_dispatch_id"], "root_dispatch_id": lin["root_dispatch_id"] or job_id}
    if lin.get("parent_ambiguous"):
        out["parent_ambiguous"] = True
    return out


def cmd_dispatch_record(args) -> int:
    """**이미 집행된** 배분을 원장에 사후 기록한다 (prj1#Issue445).

    왜 필요한가 — 배분 원장(``job.kind='fbot_dispatch'``)에 쓰는 주체가 팀장핀봇
    (`fbot-lead.py dispatch`) **하나뿐**이라, 조직이 가장 많이 쓰는 경로인 ``fpm-do``
    직접 위임이 원장을 통째로 비켜갔다. 실측(2026-08-31) 배분 엣지 11건이 전부
    팀장핀봇 소유였고 총괄핀봇은 **0건** — 조직도에서 총괄핀봇 밑이 채용 실선만으로
    그려진 것이 이 결손의 표면이다.

    🔴 **여기에 상한 판정을 두지 않는다.** 이 명령이 기록하는 것은 *일어날 일* 이 아니라
    *이미 일어난 일* 이다. 상한으로 거절하면 배분은 그대로 일어나고 **기록만 사라져**
    지금 고치려는 결손이 그대로 재발한다. 승인 게이트는 스폰 직전(HR 게이트)에 있고,
    판정 지점은 하나여야 한다.

    🔴 **status 는 ``open`` 이 아니라 ``logged``** 다. ``open`` 은 팀장핀봇의 **WIP 슬롯**
    (`fbot_dispatch_concurrent_limit`, 실측 3)을 점유하는 값이다. 사후 기록이 그 슬롯을
    먹으면 fpm-do 위임 3건만으로 팀장핀봇 배분이 통째로 막힌다 — 관측을 고치려다 조직을
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

        # prj3#Issue554 — 배분자가 **다른** open 배분이 이미 있으면 스폰은 그 배분의 **집행**이다.
        #   종전 dedupe 는 같은 owner 안에서만 봐서, 총괄이 `dispatch --by 나래` 로 PM 을 배분하고
        #   fpm-do 가 스폰하면 parent(전역 taskmgr) 명의의 두 번째 줄이 생겼다(2026-09-06 실측:
        #   `fbotdisp-…dd1c913a`). 조직도에 가짜 taskmgr→PM 엣지가 선다. 원장의 진짜 지시 관계는
        #   dispatch 가 이미 적었다 — 여기서는 적지 않는다.
        # prj3#Issue761 — `open` 만 보면 사람 판단 대기(`blocked`)·보류(`deferred`) 배분의 재기동과 다른 배분자의
        #   사후 기록(`logged`)에 두 번째 줄이 붙는다. 미종결 배분 전부가 «그 일» 이다. 찾으면 새 행 없이 결속한다.
        for r in con.execute(
                "SELECT id, owner, status, payload FROM job WHERE kind = ?"
                " AND status IN (" + LINEAGE_LIVE_SQL + ") ORDER BY created_at, id",
                (DISPATCH_KIND,) + LINEAGE_LIVE).fetchall():
            try:
                pl = json.loads(r["payload"] or "{}")
            except (ValueError, TypeError):
                continue
            # prj3#Issue699_6 — **다른 작업**이면 집행이 아니라 후속 배분이다. 워커만 보고 붙이면
            #   SendMessage 로 넘긴 후속이 앞 배분에 병합돼 원장에 1줄도 안 남는다(2026-09-26 실측:
            #   `fbotdisp-1790415000-46cca740`). 한쪽이라도 이슈가 없으면 같은 일로 본다(종전 동작).
            # prj3#Issue815 — topic 배분의 `issue` 는 주제 문장이지 이슈 키가 아니다. fpm-do 는 지휘 지시문에서 첫 번호를
            #   뽑아 넘기는데 `norm_issue` 는 주제의 마지막 번호를 잡아 대조가 늘 빗나갔다(그림자 행 `…b72d8bf0`). 이슈 없음으로 본다
            open_issue = "" if pl.get("ident_kind") == "topic" else (pl.get("issue") or "")
            if pl.get("worker_bot_id") == args.worker and (
                    not key or not open_issue or same_issue(open_issue, args.issue or "", pl.get("prj"), args.prj)):
                emit({"ok": True, "action": "dispatch-record", "recorded": False, "bound": True,
                      "reason": f"미종결 배분({r['status']})이 이미 있다 — 스폰은 그 배분의 집행이지 새 지시가 아니다",
                      "job_id": r["id"], "status": r["status"], "owner": r["owner"], "worker_bot_id": args.worker})
                return 0

        # 중복 기록 방지 — 팀장핀봇이 배분(open)하고 fpm-do 가 스폰하는 정상 경로에서
        #   같은 사건이 두 줄이 되면 안 된다. 원장은 작아서(실측 12행) 전건 스캔으로 족하다.
        for r in con.execute(
                "SELECT id, payload, status FROM job WHERE kind = ? AND owner = ?"
                " AND status != 'cancelled'", (DISPATCH_KIND, owner)).fetchall():
            try:
                pl = json.loads(r["payload"] or "{}")
            except (ValueError, TypeError):
                continue
            if pl.get("worker_bot_id") == args.worker and same_issue(pl.get("issue") or "", args.issue or "",
                                                               pl.get("prj"), args.prj):
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
        # prj3#Issue739 M1-2 — 사후 기록도 같은 계보 규칙
        payload.update(lineage_fields(dispatch_lineage(con, owner, getattr(args, "parent_dispatch", None),
                                                       os.environ.get("FBOT_FLOW") or None), job_id))
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



# ── SendMessage 위임 자동 기록 (prj3#Issue739 M1-3 — 설계 fbot-org §이슈 축 연동 결정 2) ────────────
#   판정 3조건(송신·수신·지시형)을 **모두** 충족할 때만 `dispatch-record --source sendmessage` 1건. 하나라도 판정 불가면
#   적지 않고 1줄 알림 — 원장 오염이 공백보다 비싸다. 입력 계약은 M1-1 실측(fbot-org 결정 2 «포그라운드 송신 식별»).
#   단 송신·수신 **양쪽 다 봇이 아니면** 알림도 없다(Issue806) — 비봇 세션 간 대화는 원장 대상이 아니다.
_SM_ISSUE_RE = re.compile(r"(?<![\w#])((?:prj\d+#)?Issue\d+(?:_\d+)*)")
_SM_TAG = "[지시]"


def _session_live_bots(con, sid):
    """세션에 결속된 살아 있는 봇 — bot.session_id + 관리직 몸체 원장(T15). 1:N 이면 호출자가 고르지 않는다."""
    if not sid:
        return []
    out = [r[0] for r in con.execute("SELECT bot_id FROM bot WHERE session_id = ? AND state != 'checkout'", (sid,)).fetchall()]
    for _b, owner in session_bodies(con, sid):
        if owner not in out:
            out.append(owner)
    return out


def _handoff_dir():
    """마커 폴더 — sid 마커와 같은 해소(FBOT_HANDOFF_DIR 은 테스트 주입구)."""
    return os.environ.get("FBOT_HANDOFF_DIR") or os.path.join(os.path.expanduser("~"), ".claude", ".fbot-handoff")


def _agent_marker_bot(aid):
    """에이전트 id → 봇 — 포그라운드 `agentfg-<id>.bot`(fbot-agent-map.sh) · 백그라운드 `agent-<id>.bot`(fbot-agent-done.sh)."""
    if not aid or not re.match(r"^[A-Za-z0-9_.-]+$", aid):
        return None
    for name in (f"agentfg-{aid}.bot", f"agent-{aid}.bot"):
        p = os.path.join(_handoff_dir(), name)
        try:
            with open(p, encoding="utf-8") as fh:
                v = fh.readline().strip()
            if v:
                return v
        except OSError:
            continue
    return None


def _registered(con, bid):
    return bool(bid) and con.execute("SELECT 1 FROM bot WHERE bot_id = ?", (bid,)).fetchone() is not None


def sendmessage_record(ev, env=None) -> dict:
    """PostToolUse(SendMessage) 훅 입력 → 판정 → 기록. 반환 {recorded, reason, notice?, sender, receiver, issue}."""
    env = os.environ if env is None else env
    ti = ev.get("tool_input") or {}
    tr = ev.get("tool_response") or {}
    msg = str(ti.get("message") or "")
    to = str(ti.get("to") or "")
    out = {"recorded": False, "sender": None, "receiver": None, "issue": None}
    if not (isinstance(tr, dict) and tr.get("success") is True):
        return dict(out, reason="전송 실패·응답 미상 — 기록하지 않는다")
    m = _SM_ISSUE_RE.search(msg)
    if not m and _SM_TAG not in msg:
        return dict(out, reason="지시형 아님(이슈 식별자·[지시] 없음)")
    issue = m.group(1) if m else ""
    out["issue"] = issue
    con = connect()
    try:
        # ① 송신 — agent_id 가 있으면 마커만(부모 세션의 FBOT_ID·결속은 부모 봇이라 쓰면 오귀속)
        #   s_nobot: 그 쪽에 봇 후보가 아예 없다(마커·결속·대장 0건). 봇 2개 결속처럼 «있는데 못 고름» 은 봇 있음(Issue806)
        why = ""
        s_nobot = False
        aid = ev.get("agent_id") or ""
        if aid:
            sender = _agent_marker_bot(aid)
            why = "" if sender else f"서브에이전트 {aid} 의 봇 마커 없음"
            s_nobot = not sender
        elif env.get("FBOT_ID"):
            sender = env["FBOT_ID"]
        else:
            live = _session_live_bots(con, ev.get("session_id") or "")
            sender = live[0] if len(live) == 1 else None
            why = "" if sender else ("세션 결속 봇 없음" if not live else f"세션에 봇 {len(live)}개 결속 — 고르지 않는다")
            s_nobot = not live
        if sender and not _registered(con, sender):
            sender, why, s_nobot = None, f"송신 {sender} 대장 밖", True
        # ② 수신
        rwhy = ""
        if to.startswith("uds:"):
            pid = os.path.basename(to[4:]).split(".")[0]
            sdir = (env.get("FBOT_CC_SESSIONS_DIR") or os.environ.get("FBOT_CC_SESSIONS_DIR")   # 테스트 주입구
                    or os.path.join(os.path.expanduser("~"), ".claude", "sessions"))
            try:
                with open(os.path.join(sdir, f"{pid}.json"), encoding="utf-8") as fh:
                    rsid = json.load(fh).get("sessionId") or ""
            except (OSError, ValueError):
                rsid = ""
            live = _session_live_bots(con, rsid)
            receiver = live[0] if len(live) == 1 else None
            rwhy = "" if receiver else f"소켓 {to} 세션의 결속 봇 {len(live)}개"
            r_nobot = not live
        elif _registered(con, to):
            receiver = to
            r_nobot = False
        else:
            receiver = _agent_marker_bot(to)
            rwhy = "" if receiver else f"수신 {to!r} 은 대장 bot_id·에이전트 마커가 아니다"
            r_nobot = not receiver
        out.update({"sender": sender, "receiver": receiver})
        if not sender or not receiver:
            reason = "; ".join(x for x in (why and f"송신 미상({why})", rwhy and f"수신 미상({rwhy})") if x)
            if s_nobot and r_nobot:
                # 양쪽 다 봇이 아니다 — 원장에 적을 것이 없으니 알림도 내지 않는다(Issue806: 비봇 세션 간 대화 오탐)
                return dict(out, reason=f"양쪽 비봇 — 조용히({reason})")
            return dict(out, reason=reason, notice=(
                f"[fbot] SendMessage 지시 미기록 — {reason}. 원장에 남기려면: python3 ~/.claude/hooks/fbot-state.py "
                f"dispatch-record --worker <수신 bot_id> --by <송신 bot_id> --issue {issue or '<Issue>'} --source sendmessage"))
        if sender == receiver:
            return dict(out, reason="자기 자신에게 보낸 메시지")
        # ③ 보고 방향 제외 — 수신자가 송신자에게 준 미종결 배분이 있으면 완료 통지·회신이다
        for raw, in con.execute("SELECT payload FROM job WHERE kind = ? AND owner = ? AND status IN (" + LINEAGE_LIVE_SQL + ")",
                                (DISPATCH_KIND, receiver) + LINEAGE_LIVE).fetchall():
            try:
                if json.loads(raw or "{}").get("worker_bot_id") == sender:
                    return dict(out, reason="보고 방향 — 수신자가 송신자에게 준 미종결 배분이 있다")
            except (ValueError, TypeError):
                continue
    finally:
        con.close()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_dispatch_record(argparse.Namespace(worker=receiver, by=sender, issue=issue, cwd=ev.get("cwd") or "",
                                               prj=None, source="sendmessage", parent_dispatch=None))
    try:
        dr = json.loads(buf.getvalue() or "{}")
    except ValueError:
        dr = {}
    return dict(out, recorded=bool(dr.get("recorded")), reason=dr.get("reason") or "기록",
                job_id=dr.get("job_id"))


def cmd_sendmessage_record(args) -> int:
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        emit({"ok": False, "recorded": False, "reason": "stdin JSON 아님"})
        return 0
    emit(dict(sendmessage_record(ev), ok=True, action="sendmessage-record"))
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
    sp.add_argument("--state", default=None, choices=("checkin", "checkout"),
                    help="초기 state — 기본 checkin(세션 기동=출근) · 몸체 없는 채용(총괄 staffing 생성)은 checkout (prj3#Issue796)")
    sp.set_defaults(func=cmd_register)

    sp = sub.add_parser("transition", help="전이 규칙 검증 후 상태 변경(+lease 갱신)")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--to", required=True, help=f"{'|'.join(STATES)}")
    sp.add_argument("--session-id", default=None,
                    help="관리직 몸체 원장의 몸체 세션(기본 env CLAUDE_CODE_SESSION_ID) — prj3#Issue757 T15")
    sp.set_defaults(func=cmd_transition)

    sp = sub.add_parser("career", help="career 전이(수습·정식·휴직·해고) — 규칙 검증만, 판정 없음")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--to", required=True, help=f"{'|'.join(CAREERS)}")
    sp.add_argument("--reason", default=None, help="전이 사유(감사 기록용)")
    sp.set_defaults(func=cmd_career)

    sp = sub.add_parser("employment", help="재직 축 전이 employed|suspended|leave|terminated (Issue551) — 등급 불변")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--to", required=True, help="|".join(EMPLOYMENTS))
    sp.add_argument("--reason", default=None)
    sp.set_defaults(func=cmd_employment)

    sp = sub.add_parser("heartbeat", help="lease_expires = now + TTL 갱신")
    sp.add_argument("--bot-id", default=None)
    sp.add_argument("--session-id", default=None,
                    help="그 세션에 결속된 생존 봇 전부를 갱신 — Agent 형태(Issue449)")
    sp.set_defaults(func=cmd_heartbeat)

    sp = sub.add_parser("dispatch-claim", help="스폰 집행자 잠금 — open 배분 선점 (rc 3 = 이미 선점, Issue555)")
    sp.add_argument("--worker", required=True)
    sp.add_argument("--by", default=os.environ.get("CLAUDE_CODE_SESSION_ID", "") or "fpm-do")
    # prj3#Issue647 — 호출자가 지목한 일. **잠글 행을 고르지 않는다**(고르게 하면 mutex 가 깨진다).
    #   하는 일은 둘뿐: 원장에 `spawned_for` 로 남기고, 응답에 `ident_match` 로 갈림을 알린다.
    sp.add_argument("--ident", default=None,
                    help="스폰하려는 일(Issue<N>·topic). 기록·공개 전용 — 잠금 단위는 워커 그대로")
    # prj3#Issue644 ③ — 잠금의 **짝**. 퇴근 훅이 몸체 종료를 알릴 유일한 경로다
    sp.add_argument("--release", action="store_true",
                    help="선점 해제 — 이 워커의 open 배분 잠금을 비운다 (퇴근 훅, Issue644 ③)")
    sp.add_argument("--force", action="store_true",
                    help="--release 와 함께: 워커가 퇴근 상태가 아니어도 해제(진단·수동 복구용)")
    sp.add_argument("--flow", default=None,
                    help="관리직 흐름 키(기본 env FBOT_FLOW) — 스위치 on·관리직이면 잠금 단위가 흐름(prj3#Issue757 T15 ④)")
    sp.set_defaults(func=cmd_dispatch_claim)

    sp = sub.add_parser("idle", help="턴 종료 — 세션의 working 봇을 waiting_input 으로 (Stop 훅, Issue554)")
    sp.add_argument("--session-id", required=True)
    sp.set_defaults(func=cmd_idle)

    sp = sub.add_parser("reap", help="lease 만료 봇 스캔 → 강제 퇴근(기본 dry-run)")
    sp.add_argument("--apply", action="store_true", help="실제 퇴근 처리")
    sp.add_argument("--bot-id", default=None, help="이 봇만 대상(HR wake 의 교착 해소용 — prj3#Issue699_5)")
    sp.add_argument("--force", action="store_true",
                    help="idle 유예 생략 — --bot-id 필수, lease 만료는 여전히 필요 (prj3#Issue734)")
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
    sp.add_argument("--takeover", action="store_true",
                    help="선점 무시하고 인계 — 점유 세션은 결속을 잃는다 (Issue547)")
    sp.add_argument("--flow", default=None,
                    help="관리직 지휘 흐름 키(배분·요청 id) — 몸체 원장 흐름 잠금. 기본 env FBOT_FLOW (prj3#Issue757 T15)")
    sp.set_defaults(func=cmd_bind)

    sp = sub.add_parser("body-join",
                        help="출근 가드의 관리직 몸체 추가 판정 — rc 0 허용 · rc 3 거부 유지 (prj3#Issue843)")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--flow", default=None, help="흐름 키. 기본 env FBOT_FLOW")
    sp.add_argument("--pane", default=None, help="지금 세션 pane 'session:window.pane'")
    sp.add_argument("--session-id", default=None,
                    help="주면 허용 시 몸체를 같은 트랜잭션에서 기록(판정·기록 원자 — QA ① TOCTOU). 없으면 조회만")
    sp.set_defaults(func=cmd_body_join)

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
    sp.add_argument("--parent-dispatch", default=None,
                    help="부모 배분 id — 생략 시 계보 자동 판정(prj3#Issue739 M1-2)")
    sp.set_defaults(func=cmd_dispatch_record)

    sp = sub.add_parser("sendmessage-record",
                        help="PostToolUse(SendMessage) 훅 입력(stdin) → 지시 판정 → dispatch-record (prj3#Issue739 M1-3)")
    sp.set_defaults(func=cmd_sendmessage_record)

    sp = sub.add_parser("set-task", help="current_task 갱신")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--task", default=None, help="사람용 요지. --from-dispatch 없으면 필수")
    sp.add_argument("--from-dispatch", action="store_true",
                    help="빈 칸을 그 봇의 미종결 배분(issue·topic·task_ref)에서 채운다 — 출근 훅용 (prj3#Issue759)")
    sp.add_argument("--issue", default=None, help="이슈 식별자 Issue<N>·prj<N>#Issue<M> — current_issue (prj3#Issue739 M1-4)")
    sp.add_argument("--task-ref", default=None, help="<repo 상대경로>[#앵커] — current_task_ref + 미종결 배분 payload.task_ref")
    sp.set_defaults(func=cmd_set_task)

    sp = sub.add_parser("decide", help="C·L 전결 기록 — fbot_event type=decision (Issue756)")
    sp.add_argument("--by", required=True, help="결정자 bot_id(대장 등재 필수)")
    sp.add_argument("--grade", required=True, help="C(총괄 전결)|L(팀장 전결) — H 는 mq [컨펌] [H:…]")
    sp.add_argument("--topic", required=True)
    sp.add_argument("--decision", required=True)
    sp.add_argument("--ref", default="", help="근거 — mq id·이슈·보고서 경로")
    sp.set_defaults(func=cmd_decide)

    sp = sub.add_parser("set-title", help="표시 이름 변경 — bot_id 불변 (Issue692)")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--reason", default="")
    sp.set_defaults(func=cmd_set_title)

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
