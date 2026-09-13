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
    ("seat_id", "TEXT"),       # 조직도 자리 결속 (Issue538) — `{dept}-{role}-{n}` 형식.
                               #   NULL 은 **미배치**이지 오류가 아니다. 자리(선언)와 개체(대장)를
                               #   가르는 것이 조직도 전환의 핵심이라, 개체가 자리 없이 존재할 수
                               #   있다. 조직도는 NULL 인 봇을 `미배치` 구역에 렌더한다(계약 4).
                               #   ⚠️ 기록 귀속은 여전히 bot_id 다 — job 레코드에 넣지 않는다.
)

# `job.owner` → `owner_kind`/`owner_id` 유도 규칙 **SSOT** (Issue516).
#   트리거 2개·백필이 전부 이 두 식을 쓴다. 갈라지는 순간 원장이 거짓이 되므로 복제 금지.
#   `{t}` 에는 트리거면 `NEW`, 백필이면 `job` 이 들어간다.
JOB_OWNER_KIND_EXPR = "CASE WHEN {t}.kind LIKE 'fbot%' THEN 'bot' ELSE 'lock' END"
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
    p3 = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa", "policy.yml")
    return p3 if os.path.exists(p3) else path


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


def record_event(con: sqlite3.Connection, bot_id: str, etype: str, detail: str = "", ref: str = "") -> str:
    """전이 1건 → `fbot_event` 1행 (같은 커넥션·같은 트랜잭션). 반환 id. 실패는 조용히 "" — 기록이 본 작업을 막지 않는다."""
    now = int(time.time())
    eid = f"fbotev-{now}-{uuid.uuid4().hex[:8]}"
    try:
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts, owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (eid, "fbot", "fbot_event", "done",
             json.dumps({"type": etype, "detail": (detail or "")[:300], "ref": ref or ""}, ensure_ascii=False),
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

    # 백필 — 기존 522행. 미채움(NULL)이 남으면 FK·감사가 그 행을 조용히 통과시킨다.
    con.execute(f"""
        UPDATE job SET owner_kind = {JOB_OWNER_KIND_EXPR.format(t='job')},
                       owner_id   = {JOB_OWNER_ID_EXPR.format(t='job')}
         WHERE owner_kind IS NULL""")


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
                # prj3#Issue554 — 입력이 도착했다. Stop 훅이 내린 waiting_input 은 여기서 올린다
                #   (전이표: waiting_input → working "입력 도착"). 다른 상태는 건드리지 않는다.
                con.execute(
                    "UPDATE bot SET lease_expires = ?, last_active_at = ?,"
                    " state = CASE WHEN state = 'waiting_input' THEN 'working' ELSE state END"
                    " WHERE bot_id = ?", (now + ttl, now, bid)
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


def cmd_dispatch_claim(args) -> int:
    """스폰 집행자 잠금 (prj3#Issue555) — 이 워커의 `open` 배분 1건을 **선점**한다.

    같은 배분을 두 세션이 각자 승인을 들고 스폰하면 몸체가 둘이 뜬다(Issue554 e4 실측 —
    통지로만 회피). 잠금은 스폰 **앞**에 있어야 하므로 fpm-do 가 send-keys 직전에 부른다.
    rc 0 = 선점했거나 잠글 배분이 없음(자기 주도 위임) · **rc 3 = 이미 선점됨**(스폰 중단).
    선점 흔적은 `payload.spawned_by`·`spawned_at` — 원장 밖에 잠금 파일을 두지 않는다."""
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            target = None
            for r in con.execute(
                    "SELECT id, owner, payload FROM job WHERE kind = ? AND status = 'open'"
                    " ORDER BY created_at", (DISPATCH_KIND,)).fetchall():
                try:
                    pl = json.loads(r["payload"] or "{}")
                except (ValueError, TypeError):
                    continue
                if pl.get("worker_bot_id") == args.worker:
                    target = (r["id"], r["owner"], pl)
                    break
            if not target:
                con.execute("COMMIT")
                emit({"ok": True, "action": "dispatch-claim", "claimed": False,
                      "reason": "open 배분 없음 — 잠글 대상이 없다(자기 주도 위임)",
                      "worker_bot_id": args.worker})
                return 0
            jid, owner, pl = target
            if pl.get("spawned_by"):
                con.execute("COMMIT")
                emit({"ok": False, "action": "dispatch-claim", "claimed": False,
                      "reason": "이미 스폰됨 — 다른 집행자가 선점했다", "job_id": jid,
                      "spawned_by": pl["spawned_by"], "spawned_at": pl.get("spawned_at"),
                      "worker_bot_id": args.worker})
                return 3
            pl["spawned_by"] = args.by or ""
            pl["spawned_at"] = int(time.time())
            con.execute("UPDATE job SET payload = ? WHERE id = ?",
                        (json.dumps(pl, ensure_ascii=False), jid))
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({"ok": True, "action": "dispatch-claim", "claimed": True, "job_id": jid,
              "owner": owner, "spawned_by": pl["spawned_by"], "worker_bot_id": args.worker})
        return 0
    finally:
        con.close()


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
        # prj3#Issue554 — 수신대기 봇은 idle TTL 만큼 더 기다린다(유휴 ≠ 사망)
        idle_grace = idle_ttl_secs()
        expired = [e for e in expired
                   if not (e.get("state") == "waiting_input"
                           and now < int(e["lease_expires"]) + idle_grace)]
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
                    # Issue549 — 마커도 함께 걷는다. 퇴근 훅(fbot-checkout.sh)은 이미
                    #   지우지만 reap 은 그 훅이 실패했을 때 도는 마지막 방벽이라,
                    #   여기서 빠지면 보완이 성립하지 않는다. 마커가 남으면 ①호칭 환기
                    #   훅이 "이미 결속" 으로 오판해 침묵하고 ②heartbeat 폴백이 퇴근한
                    #   봇의 lease 를 되살린다. 불변은 **"퇴근 = 마커 소멸"** 이다.
                    drop_sid_marker(e.get("session_id") or "")
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
                "UPDATE bot SET current_task = ?, last_active_at = strftime('%s','now') WHERE bot_id = ?", (args.task, args.bot_id)
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        emit({"ok": True, "action": "set-task", "bot": row_to_dict(fetch_bot(con, args.bot_id))})
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
    base = os.environ.get("FBOT_HANDOFF_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", ".fbot-handoff")
    # prj3#Issue616 — Agent 하청은 **부모와 같은 session_id** 를 쓴다. 한 파일을 나눠 쓰면
    #   하청 bind 가 부모 마커를 덮고 done 이 그것을 지워, 살아 있는 부모 세션이 원장에서
    #   퇴근으로 뒤집힌다(실측 2026-09-10: checkin→working→checkout 2회 + 가드 무력화).
    #   Issue449 는 소비자마다 *"마커를 믿지 마라"* 로 우회했을 뿐 **원인은 남겼다** — 그래서
    #   Issue612 의 새 소비자(writeguard)가 같은 자리에서 다시 빠졌다. 슬롯 자체를 가른다.
    #   세션 슬롯(`sid-<SID>.id`)은 **오직 세션 결속**의 것이다. 훅(bash)이 읽는 경로가
    #   이것이므로, 하청이 무엇을 하든 부모의 마커는 그 자리에 남는다.
    if form == "agent":
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", bot_id or "anon")
        return os.path.join(base, f"sid-{session_id}.agent-{safe}.id")
    return os.path.join(base, f"sid-{session_id}.id")


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


def bind_occupancy_verdict(row, incoming_sid, now=None):
    """기존 세션 결속의 점유 상태를 **3값**으로 판정한다 (Issue547).

    🔴 부울로 만들지 않는 이유는 Issue445 와 같다 — "모른다" 를 표현할 수 없는 판정은
    참인 순간 판정을 통째로 건너뛰어 fail-open 이 된다. 그 실수를 pane 판정에서 이미
    두 번 했다(Issue419 미탐 · Issue439 오탐).

    반환: (verdict, 점유 세션 id)
      free    — 미점유이거나 **자기 자신의 재결속**. 그대로 진행
      dead    — lease 만료. 인계 가능
      idle    — lease 유효하나 점유 세션이 `waiting_input`(사용자 입력 대기). 인계 가능 (Issue554)
      alive   — lease 유효. 남이 쓰는 중이므로 거부
      unknown — 결속은 있는데 lease 가 없다. 판정 불가이므로 **사람에게 묻는다**
    """
    cur = (row["session_id"] or "") if "session_id" in row.keys() else ""
    if not cur or cur == incoming_sid:
        return "free", None
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
            evicted = None
            if args.session_id:                  # 지우는 것(빈 문자열)은 선점 대상이 아니다
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
                if verdict != "free":
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
            notify_hub_event(args.bot_id, "evict")
        if args.session_id:
            # form 을 넘겨 **하청은 자기 슬롯에** 쓴다(prj3#Issue616). 세션 슬롯 불변
            write_sid_marker(args.session_id, args.bot_id, getattr(args, "form", "") or "")
        out = {"ok": True, "action": "bind", "bot": row_to_dict(fetch_bot(con, args.bot_id))}
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
    m = re.findall(r"issue[_-]?(\d+(?:_\d+)*)", t)
    return "issue" + m[-1] if m else t


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
        for r in con.execute(
                "SELECT id, owner, payload FROM job WHERE kind = ? AND status = 'open'",
                (DISPATCH_KIND,)).fetchall():
            try:
                pl = json.loads(r["payload"] or "{}")
            except (ValueError, TypeError):
                continue
            if pl.get("worker_bot_id") == args.worker:
                emit({"ok": True, "action": "dispatch-record", "recorded": False,
                      "reason": "open 배분이 이미 있다 — 스폰은 그 배분의 집행이지 새 지시가 아니다",
                      "job_id": r["id"], "owner": r["owner"], "worker_bot_id": args.worker})
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
    sp.set_defaults(func=cmd_dispatch_claim)

    sp = sub.add_parser("idle", help="턴 종료 — 세션의 working 봇을 waiting_input 으로 (Stop 훅, Issue554)")
    sp.add_argument("--session-id", required=True)
    sp.set_defaults(func=cmd_idle)

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
    sp.add_argument("--takeover", action="store_true",
                    help="선점 무시하고 인계 — 점유 세션은 결속을 잃는다 (Issue547)")
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
