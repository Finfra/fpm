#!/usr/bin/env python3
"""aoa-memory 스토어 스키마 v2 — registry.db + learn.db (prj5 Issue68 · v2 = prj3#Issue436_3)

⚠️ 설계 SSOT: ~/_git/___common/_doc_arch/aoa-memory-design.md
   본 파일은 그 문서의 DDL 절을 **그대로 실행되는 정본**으로 옮긴 것이다.
   스키마를 바꾸려면 설계 문서를 먼저 고치고 여기가 따른다(§변경 이력 기준).

범위 (1순위 최소 구현 — Issue68 B-1):
  * registry.db — store(카탈로그) · kv(싱글톤 KV) · job(비동기 잡) · budget · budget_monthly
                  · bot(핀봇 레지스트리 — v2 신설, prj3 fbot-arch §레지스트리 스키마 F1)
  * learn.db    — observation(raw) · instinct · policy_candidate · _meta(watermark)
  * 스코프 밖: kb-m.db(2순위) · mq.db(3순위) · 잡 실행기 · GC/백업(maint) — 스키마만 서고
    실행 주체는 만들지 않는다(설계 TODO "worker 상주는 실증 후").

설계 승계 조항 (어기지 말 것):
  * `_meta` watermark 는 **스토어 DB 내부**에 둔다 — registry.kv 에 두면 ATTACH 교차
    쓰기가 비원자라 크래시 시 소화 반영과 watermark 기록이 갈라진다.
  * 모든 kv 읽기 경로는 `expires_at IS NULL OR expires_at > now` 필터 의무 —
    GC 는 lazy 라 만료 행이 며칠 남는 창이 정상 상태다.
  * 이전 값에 의존하는 갱신은 `SET x = x + :d` 상대 갱신으로만 (lost update 차단).
"""

import hashlib
import os
import sqlite3
import time

HOME = os.path.expanduser("~")
# 기본 경로 = **제품 중립** `~/.claude/data/aoa` (prj3#Issue436_3 s7 — Issue62 ① 개정).
# `AOA_MEMORY_DIR` 는 회귀 전용이 아니라 **정식 설정**이다 — 설치 환경이 데이터 위치를
# 실데이터를 건드리지 않고 격리 디렉토리에서 돌기 위한 유일한 용도다(운영 중 변경 금지).
AOA_DIR = os.environ.get("AOA_MEMORY_DIR") or os.path.join(HOME, ".claude", "data", "aoa")

REGISTRY_DB = os.path.join(AOA_DIR, "registry.db")
LEARN_DB = os.path.join(AOA_DIR, "learn.db")

# 코드 버전 — registry.store.min_supported_version 게이트의 비교 대상 (설계 §버전 가드)
#   ⚠️ **CODE_VERSION 과 SCHEMA_VERSION 은 축이 다르다 — 함께 올리지 말 것.**
#      `SCHEMA_VERSION` 은 "이 DDL 이 몇 판인가"(카탈로그·_meta 표기용),
#      `CODE_VERSION` 은 신규 스토어 생성 시 `min_supported_version` 으로 박히는
#      **참여 하한**이다. v2(bot 테이블 신설)는 **순수 추가**라 v1 코드가 그대로 돌아간다 —
#      여기서 하한을 2 로 올리면 새로 만들어지는 스토어가 아직 살아 있는 v1 참여자
#      (장수명 stdio 서버·worker)를 이유 없이 거부한다. 하한 상향은 **구 코드가
#      신 스키마를 오독·손상시킬 때만** 한다 (설계 §마이그레이션 절차).
CODE_VERSION = 1
SCHEMA_VERSION = 2

# --- DDL (설계 정본) ------------------------------------------------------

REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS store(
  name TEXT PRIMARY KEY, kind TEXT, path TEXT, owner_prj TEXT,
  schema_version INT, min_supported_version INT,
  last_indexed TEXT, health TEXT, note TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS kv(
  ns TEXT, key TEXT, value TEXT,
  expires_at INT, updated_at INT, updated_by TEXT,
  PRIMARY KEY(ns, key)
) STRICT;

CREATE TABLE IF NOT EXISTS job(
  id TEXT PRIMARY KEY, store TEXT, kind TEXT, status TEXT,
  payload TEXT, result TEXT, attempts INT,
  owner TEXT, lease_until INT, blocked_since INT, created_at INT
) STRICT;

CREATE TABLE IF NOT EXISTS budget(
  day TEXT, store TEXT, tokens INT, calls INT,
  PRIMARY KEY(day, store)
) STRICT;

CREATE TABLE IF NOT EXISTS budget_monthly(
  ym TEXT, store TEXT, tokens INT, calls INT,
  PRIMARY KEY(ym, store)
) STRICT;

-- ⑥ 핀봇 레지스트리 (v2 신설 — prj3#Issue436_3 s1)
--    계약 정본: ~/.claude/_doc_arch/fbot-arch.md §레지스트리 스키마(F1) · §봇 수명주기 · §상태 기계
--    state: checkin | working | waiting_input | waiting_child | checkout (표시는 한글, 저장은 영문)
--    career: probation | active | leave | terminated (경력 축 — 상태 기계와 직교)
--    prj: 주 담당 prj 번호(단수) — 전역봇은 NULL. "어느 prj 일을 했나" 는 job 원장이 답한다
--    parent_bot_id: 스폰 부모 — 인사핀봇 깊이 상한 판정의 데이터 원천. 상비 봇·사람 기동은 NULL
--    lease_expires: heartbeat 갱신 시각 + TTL. 만료분은 인사핀봇/maint 가 퇴근 처리
--    STRICT 는 타입만 강제한다 — state·career 값 검증은 서버 코드 책임(job.status 선례와 동일)
CREATE TABLE IF NOT EXISTS bot(
  bot_id TEXT PRIMARY KEY,
  title TEXT,
  role TEXT NOT NULL,
  state TEXT NOT NULL,
  career TEXT NOT NULL,
  icon TEXT,
  color TEXT,
  prj INT,
  current_task TEXT,
  parent_bot_id TEXT,
  lease_expires INT,
  created_at INT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS job_status_idx ON job(status, created_at);
"""

# learn.db — 1순위 적재 대상은 homunculus 다.
#   ⚠️ **파일이 정본, DB 가 파생**이다(Issue403 ⓒ 판정 · 정본 역전은 별도 판정).
#      그래서 모든 행이 `source_path` 를 갖는다 — 최악의 DB 손실에도 원천에서 재적재된다.
#   ⚠️ instinct.origin — 환원 산출물(consolidation 이 memory/ 로 되돌린 파일)을 구별하는 열.
#      이것이 없으면 환원본이 다음 consolidation 의 입력으로 재소화돼 요약의 요약이 증폭된다
#      (설계 §승격 경로 "산출물을 재소화하지 않는다" 를 파일 환원 경로까지 확장한 것 — Issue68 반증 ③).
LEARN_DDL = """
CREATE TABLE IF NOT EXISTS observation(
  id TEXT PRIMARY KEY,
  project_id TEXT, project_name TEXT, session_id TEXT,
  observed_at INT, body TEXT,
  source_path TEXT, ingested_at INT
) STRICT;

CREATE TABLE IF NOT EXISTS instinct(
  project_id TEXT, instinct_id TEXT,
  title TEXT, trigger TEXT, confidence REAL,
  domain TEXT, scope TEXT, origin TEXT, occurrences INT,
  body TEXT,
  source_path TEXT, source_mtime INT, ingested_at INT,
  PRIMARY KEY(project_id, instinct_id)
) STRICT;

CREATE TABLE IF NOT EXISTS policy_candidate(
  id TEXT PRIMARY KEY, project_id TEXT, instinct_id TEXT,
  status TEXT, payload TEXT, created_at INT
) STRICT;

CREATE TABLE IF NOT EXISTS _meta(
  key TEXT PRIMARY KEY, value TEXT, updated_at INT
) STRICT;

CREATE INDEX IF NOT EXISTS observation_aging_idx ON observation(observed_at);
"""

# FTS5 — `learn_search` 의 기본 엔진(BM25). 가상 테이블은 STRICT 를 못 붙인다.
#   외부 콘텐츠 연동 대신 upsert 코드가 동기화한다(최소 구현 — 트리거 3종을 세우지 않는다).
LEARN_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS instinct_fts USING fts5(
  project_id UNINDEXED, instinct_id UNINDEXED,
  title, trigger, body,
  tokenize = 'unicode61'
);
"""


def now() -> int:
    return int(time.time())


def _budget_keys() -> tuple:
    """예산 테이블의 (일별 키, 월별 키) — UTC 기준 (month_bucket 과 동일 축)."""
    import datetime
    d = datetime.datetime.fromtimestamp(now(), datetime.timezone.utc)
    return d.strftime("%Y-%m-%d"), d.strftime("%Y-%m")


def budget_month_spent(con: sqlite3.Connection, store: str) -> int:
    """이번 달(UTC) 해당 store 의 토큰 소진 누계. 기록이 없으면 0."""
    _, ym = _budget_keys()
    row = con.execute(
        "SELECT tokens FROM budget_monthly WHERE ym=? AND store=?", (ym, store)
    ).fetchone()
    return int(row["tokens"]) if row else 0


def record_budget(con: sqlite3.Connection, store: str, tokens: int, calls: int) -> None:
    """예산 소진을 기록한다 (원자적).

    `budget` (일별)과 `budget_monthly` (월별) 테이블에 토큰과 호출 수를 가산한다.
    """
    day, ym = _budget_keys()

    con.execute(
        "INSERT INTO budget(day, store, tokens, calls) VALUES(?,?,?,?) "
        "ON CONFLICT(day, store) DO UPDATE SET tokens=tokens+excluded.tokens, calls=calls+excluded.calls",
        (day, store, tokens, calls)
    )
    con.execute(
        "INSERT INTO budget_monthly(ym, store, tokens, calls) VALUES(?,?,?,?) "
        "ON CONFLICT(ym, store) DO UPDATE SET tokens=tokens+excluded.tokens, calls=calls+excluded.calls",
        (ym, store, tokens, calls)
    )


def observation_id(source_path: str, line: int) -> str:
    """관측 raw 의 **자연키** — `(원천 파일, 줄번호)` (Issue69 A-3).

    스키마와 짝이라 여기 둔다. 어댑터가 각자 키를 만들면 재실행 멱등이 깨진다 —
    부를 곳은 이 함수 하나다.

    ## 왜 내용 해시가 아닌가 (실측으로 뒤집힌 초안)

    첫 후보는 `(project_id, session, timestamp, event, tool, output)` 내용 해시였다.
    실측(2026-08-16 · 931파일 41,466행)에서 그 키로 **534건이 충돌**했는데,
    표본을 열어 보니 전부 *같은 파일 안의 서로 다른 줄* 이었다 — 같은 초에 같은 툴이
    같은 출력으로 두 번 끝난, **진짜로 두 번 일어난 관측**이다. 내용 해시를 키로 쓰면
    그 534건이 조용히 사라지고 빈도 집계가 그만큼 틀어진다.

    ## 줄번호가 안정적인 근거

    관측 파일은 **append-only** 다 — 활성 `observations.jsonl` 은 뒤에만 붙고,
    회전된 `observations.archive/processed-*.jsonl` 은 그 뒤로 불변이다. 따라서
    "N번째 줄"은 한 번 정해지면 변하지 않고, 같은 파일을 몇 번 다시 읽어도 같은 id 가 난다.

    경로는 **홈 상대**로 정규화한다 — 절대경로를 쓰면 머신·사용자가 바뀔 때 같은 줄이
    다른 id 를 받아 재적재가 중복된다. 홈 밖 경로는 절대경로 그대로 쓴다(정규화할 기준이 없다).
    """
    ap = os.path.abspath(source_path)
    rel = os.path.relpath(ap, HOME) if ap.startswith(HOME + os.sep) else ap
    return "obs_" + hashlib.sha1(("%s:%d" % (rel, line)).encode("utf-8")).hexdigest()[:20]


def get_meta(con: sqlite3.Connection, key: str, default: str = "0") -> str:
    row = con.execute("SELECT value FROM _meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    """⚠️ 커밋하지 않는다 — 호출자의 트랜잭션 안에서 쓰라는 뜻이다.

    watermark 는 소화 결과와 **같은 커밋**으로 올라가야 한다(설계 §영속 보증 3항 ·
    agy 검토 C-2). 여기서 commit 하면 그 원자성이 깨진다.
    """
    con.execute(
        "INSERT INTO _meta(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, str(value), now()),
    )


def connect(path: str) -> sqlite3.Connection:
    """WAL + busy_timeout 을 건 커넥션. 다중 프로세스 동시 접근이 전제다(설계 §실행 토폴로지)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def check_fts5(con: sqlite3.Connection) -> None:
    """FTS5 자기점검 — 부재면 fail-loud (설계 §MCP 도구 표면).

    조용히 LIKE 로 강등하지 않는다. 검색 품질이 말없이 달라지면 호출자가 결과를
    신뢰할 근거를 잃는다.
    """
    row = con.execute(
        "SELECT count(*) c FROM pragma_compile_options WHERE compile_options LIKE 'ENABLE_FTS5%'"
    ).fetchone()
    if not row or row["c"] == 0:
        raise RuntimeError(
            "SQLite FTS5 미탑재 — learn_search 를 세울 수 없다. "
            "python3 의 sqlite3 빌드를 FTS5 포함본으로 교체할 것"
        )


def init_stores() -> dict:
    """스토어 2종을 생성·등록한다. 멱등 — 여러 번 불러도 결과가 같다."""
    os.makedirs(AOA_DIR, exist_ok=True)
    created = {}

    with connect(LEARN_DB) as lc:
        check_fts5(lc)
        lc.executescript(LEARN_DDL)
        lc.executescript(LEARN_FTS_DDL)
        lc.execute(
            "INSERT INTO _meta(key, value, updated_at) VALUES('schema_version', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (str(SCHEMA_VERSION), now()),
        )
        # consolidated_until — raw 에이징의 성공 게이트. 미소화 상태는 0 이다.
        lc.execute(
            "INSERT OR IGNORE INTO _meta(key, value, updated_at) VALUES('consolidated_until', '0', ?)",
            (now(),),
        )
        lc.commit()
        created["learn"] = LEARN_DB

    with connect(REGISTRY_DB) as rc:
        rc.executescript(REGISTRY_DDL)
        for name, path, note in (
            ("registry", REGISTRY_DB, "싱글톤 KV + 카탈로그"),
            ("learn", LEARN_DB, "homunculus 관측·instinct·정책 후보 (파일 정본의 파생)"),
        ):
            rc.execute(
                "INSERT INTO store(name, kind, path, owner_prj, schema_version, "
                "min_supported_version, last_indexed, health, note) "
                "VALUES(?, 'managed', ?, 'prj5', ?, ?, NULL, 'ok', ?) "
                "ON CONFLICT(name) DO UPDATE SET path=excluded.path, "
                "schema_version=excluded.schema_version, note=excluded.note",
                (name, path, SCHEMA_VERSION, CODE_VERSION, note),
            )
        rc.commit()
        created["registry"] = REGISTRY_DB

    return created


def version_gate(con: sqlite3.Connection) -> None:
    """설계 §버전 가드 — 설치본이 스토어보다 낡았으면 도구 호출을 거부한다.

    stdio 서버는 장수명이라 검사를 initialize 가 아니라 **첫 도구 호출**에 건다.
    """
    row = con.execute(
        "SELECT max(min_supported_version) m FROM store WHERE kind='managed'"
    ).fetchone()
    need = (row["m"] if row and row["m"] is not None else 0)
    if need > CODE_VERSION:
        raise RuntimeError(
            "aoa-memory 코드 버전 %d < 요구 %d — 세션 재시작(설치본 갱신)이 필요하다"
            % (CODE_VERSION, need)
        )


if __name__ == "__main__":
    for k, v in init_stores().items():
        print("%-9s %s" % (k, v))
