#!/usr/bin/env python3
"""fbot-registry-audit.py — fbot 레지스트리(registry.db) 정합성 검사기 (prj3#Issue515).

배경 (계약: `_doc_arch/fbot-arch.md` §정합성 계약)
    `bot`(대장)과 `job`(원장)은 **FK 로 묶여 있지 않다**. 참조 무결성을 DB 가 지켜
    주지 않으므로, 한쪽(bot)을 지우는 순간 다른 쪽(job·kv)이 조용히 거짓말을 시작한다
    — hub 조직도의 "유령 행"이 그 증상이다. 본 스크립트가 그 거짓말을 **주기적으로
    소리내어** 검출하는 유일한 수단이다.

검사 항목 (ⓐ~ⓔ — Issue515 실측 축)
    ⓐ fk_declaration    FK 선언·`PRAGMA foreign_keys` 상태            (severity: warn — 구조적 기지 결손)
    ⓑ owner_polymorphism `job.owner` 다형(`fbot-*` vs `<host>/<pid>`) (severity: warn — ⓐ 의 직접 원인)
    ⓒ bot_id_slug       bot_id 생성 slug 규칙(언더스코어 소실·충돌)   (severity: error 시 실제 충돌 발생)
    ⓓ budget_schema     `budget`/`budget_monthly` vs kv `fbot:budget` (severity: info — 축 분리는 설계)
    ⓔ orphans           대장에 없는 봇을 가리키는 job·kv 고아         (severity: error)
    ⓖ bot_refs          bot→bot 참조(parent_bot_id)가 대장 밖을 가리킴  (severity: error)

rc 규약 (fail-loud)
    0 = error 없음 · 1 = error 있음 · 2 = 실행 실패(DB 없음·인자 오류 등)
    `--strict` 는 warn 도 error 로 승격한다(구조적 결손까지 게이트하고 싶을 때).

⚠️ 안전 규약
    * `--dry-run` 이 **기본값**이다. 쓰기는 `--fix` 를 명시할 때만 일어난다.
    * `--fix` 는 **ⓔ 고아만** 지운다. 스키마 변경(DROP/ALTER)은 어떤 경우에도 하지 않는다.
    * `--fix` 는 쓰기 전에 **DB 사본 + 삭제 대상 전문 JSON** 을 남긴다. 실패 시 롤백 경로를 출력한다.
    * `job.owner` 는 다형이다 — `fbot-` 접두가 **아닌** owner(`jm4/12345` 락 소유자 466건)를
      봇 고아로 세면 466건 오탐이 난다. 판정은 반드시 `fbot-` 접두로 한다.
    * 가상 정체 화이트리스트는 **비어 있다**(Issue528). 예외를 두면 그 예외가 곧 갈림의
      은신처가 된다 — `fbot-exec` 가 그랬다. 기록 귀속은 대장의 개체 id 로만 한다.
    * 최근(<`--min-age-hours`, 기본 24h) 레코드는 **살아 있는 작업일 수 있으므로 보호**한다.
      `fpm-do` 직접 위임(status=logged)은 배분 기록만 남고 대장 등재가 뒤따르지 않아
      정상적으로도 일시적 고아로 보인다.

사용
    python3 ~/.claude/hooks/fbot-registry-audit.py                 # 검사만(dry-run)
    python3 ~/.claude/hooks/fbot-registry-audit.py --strict        # 구조적 결손까지 rc=1
    python3 ~/.claude/hooks/fbot-registry-audit.py --fix           # 고아 정리(백업 후)
    python3 ~/.claude/hooks/fbot-registry-audit.py --fix --min-age-hours 72
    python3 ~/.claude/hooks/fbot-registry-audit.py --quiet | jq .checks.orphans
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time

# ── 경로 ────────────────────────────────────────────────────────────────────
# fbot-hr-gate.py·fbot-state.py 와 동일 규약: AOA_MEMORY_DIR env 우선.
DEFAULT_AOA_DIR = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa")
# env 미설정(launchd·cron 등 PATH/env 가 얇은 컨텍스트)에서 기본 경로가 비어 있을 때만
# 살펴보는 정본 후보. 조용히 갈아타지 않고 db_path_source 로 어디를 썼는지 보고한다.
FALLBACK_AOA_DIRS = [os.path.join(os.path.expanduser("~"), "_git", "___common", "data", "aoa")]

# ── 정책 상수 ───────────────────────────────────────────────────────────────
# 대장에 없어도 고아가 아닌 "가상 정체". 코드에 하드코딩된 논리적 발신자 id 였다.
#
# ⚠️ Issue528 로 **비웠다.** 유일한 입주자 `fbot-exec` 는 fbot-chief-report.py 의
#    `BOT_ID` 상수였는데, 그것은 **직능(role) id 이지 개체가 아니었다** — 계약
#    (`_doc_arch/fbot-arch.md` §조직 "명명된 개체")은 머신마다 개체명을 다르게 두라고
#    정한다(jm4 = fbot-chief-narae). 화이트리스트가 그 갈림을 **고아가 아니라고 덮어**
#    18건이 조용히 쌓이는 것을 허용했다. 지금은 코드가 대장에서 개체를 해소하므로
#    (resolve_bot_id) 보호할 가상 정체가 없다.
#
# 다시 채우기 전에: 그 id 가 **정말 개체가 아닌지**를 먼저 따져라. 개체라면 대장에
# 등재하는 것이 답이고, 화이트리스트는 검사기를 눈멀게 하는 쪽이다.
VIRTUAL_BOT_IDS: set[str] = set()

# prj3#Issue610 — **역사 별칭**: 이름 개편(2026-09-10) 전의 bot_id 다.
#   `bot`·`job.owner` 는 새 이름으로 옮겼지만 **`job.payload` 는 그때의 기록이라 그대로 두었다**
#   (사용자 지시 — 소급 치환은 이력을 거짓으로 만든다). payload 안의 구 id 를 고아로 세면
#   개편 이전 원장 전부가 "삭제 대상" 으로 잡힌다(실측 34건). 대장에 없는 것은 맞지만
#   **끊긴 참조가 아니라 개명된 참조**이므로 여기서 예외로 안다. 매핑 정본은 `_doc_arch/fbot-naming.md`.
HISTORICAL_BOT_IDS: set[str] = {
    "fbot-exec-narae", "fbot-taskmgr", "fbot-recruit",
} | {
    # prj 별 팀장핀봇 — 구 `fbot-taskmgr-<slug>`
    f"fbot-taskmgr-{slug}" for slug in (
        "pm", "obsidian", "claude", "social", "common", "architect", "fpm",
        "finfrahome", "fgooglesheet", "fsnippet", "fwarrange", "f-claude-plugins",
        "fsnippetcli", "fwarrangecli", "fsnippetwinv-basic", "videostudio",
        "m2slide", "fcapture", "jmdashboard",
    )
}

# 봇 귀속 kv 네임스페이스는 `fbot:fbot-<id>` 다. `fbot:budget`·`fbot:dispatch`·`fbot:notify`
# 는 서브시스템 원장이지 봇이 아니다 — 접두 2단(`fbot:fbot-`)으로 구분한다.
BOT_NS_PREFIX = "fbot:fbot-"

# 종결 상태. 진행 중인 잡은 나이와 무관하게 지우지 않는다.
TERMINAL_STATUS = {"done", "cancelled", "canceled", "failed", "logged"}

# payload 안에서 봇을 가리키는 키들.
PAYLOAD_BOT_KEYS = ("bot_id", "worker_bot_id", "parent_bot_id", "requester_bot_id", "from_bot_id")

# ⓒ slug 생성 지점 — 규칙이 바뀌면 여기도 같이 고친다(2원 구조).
SLUG_SOURCE = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "fbot-lead.py")
SLUG_BAD_RE = re.compile(r"""re\.sub\(\s*r?["']\[\^a-z0-9-\]["']\s*,\s*["']["']""")

DEFAULT_MIN_AGE_HOURS = 24


class AuditError(RuntimeError):
    """실행 자체가 불가능한 상황 (rc=2)."""


# ── 경로·연결 ───────────────────────────────────────────────────────────────

def resolve_db(explicit: str | None) -> tuple[str, str]:
    """(경로, 출처) 를 돌려준다. 없으면 fail-loud."""
    if explicit:
        if not os.path.exists(explicit):
            raise AuditError(f"레지스트리 DB 없음: {explicit} (--db 확인)")
        return explicit, "--db"
    env = os.environ.get("AOA_MEMORY_DIR")
    if env:
        p = os.path.join(env, "registry.db")
        if os.path.exists(p):
            return p, "AOA_MEMORY_DIR"
    p = os.path.join(DEFAULT_AOA_DIR, "registry.db")
    if os.path.exists(p):
        return p, "default"
    for d in FALLBACK_AOA_DIRS:
        cand = os.path.join(d, "registry.db")
        if os.path.exists(cand):
            return cand, "fallback"
    raise AuditError(
        "레지스트리 DB 를 찾지 못했다 — AOA_MEMORY_DIR 를 설정하거나 --db 로 지정하라. "
        f"(확인한 곳: {env or '-'}, {DEFAULT_AOA_DIR}, {', '.join(FALLBACK_AOA_DIRS)})"
    )


def connect(path: str, readonly: bool) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    else:
        con = sqlite3.connect(path, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    # Issue527 — FK 는 **연결마다** 켜야 강제된다(선언만으로는 집행되지 않는다).
    #   ⓐ 검사가 `PRAGMA foreign_keys` 를 보므로, 검사기 자신이 끄고 들어오면 선언이
    #   멀쩡해도 영원히 red 다. 다른 소비처(fbot-state·taskmgr·hr-gate·prj5 store.py)와
    #   같은 규약을 여기서도 지킨다.
    con.execute("PRAGMA foreign_keys=ON")
    return con


def known_bots(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT bot_id FROM bot")}


def parse_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


# ── ⓐ FK 선언 ───────────────────────────────────────────────────────────────

def check_fk(con: sqlite3.Connection) -> dict:
    pragma = con.execute("PRAGMA foreign_keys").fetchone()[0]
    declared = {}
    for t in ("job", "bot", "kv"):
        declared[t] = [dict(r) for r in con.execute(f"PRAGMA foreign_key_list({t})")]
    total = sum(len(v) for v in declared.values())
    ok = total > 0 and pragma == 1
    return {
        "id": "a_fk_declaration",
        "label": "FK 선언·강제 상태",
        "severity": "warn",
        "ok": ok,
        "pragma_foreign_keys": int(pragma),
        "declared_fk_count": total,
        "declared_fk_by_table": declared,
        "note": (
            "bot↔job 참조 무결성을 DB 가 지키지 않는다. 대장에서 봇을 지우면 원장이 "
            "조용히 거짓말을 시작한다 — 본 검사기가 유일한 방어선이다. "
            "FK 를 걸려면 ⓑ(owner 다형)를 먼저 풀어야 한다."
        ) if not ok else "",
    }


# ── ⓑ owner 다형 ────────────────────────────────────────────────────────────

def classify_owner(owner: str | None) -> str:
    if owner is None or owner == "":
        return "null"
    if owner.startswith("fbot-"):
        return "bot"
    if "/" in owner:
        return "lock"          # `<host>/<pid>` — 잡 리스 소유자
    return "unknown"


def check_owner_polymorphism(con: sqlite3.Connection) -> dict:
    """`job.owner` 다형성 — Issue516 해소 후에는 **분리 축(owner_id)** 을 본다.

    `owner` 는 fencing 술어(`WHERE id=? AND owner=?`)가 쓰므로 **의도적으로 혼재를
    유지**한다. 그것을 다형성 위반으로 보면 영원히 red 다. 축이 갈린 뒤의 질문은
    *"owner 가 섞여 있는가"* 가 아니라 *"FK 를 걸 대상 컬럼(owner_id)이 단일 종류이고
    빠짐없이 채워졌는가"* 다.
    """
    have = {r[1] for r in con.execute("PRAGMA table_info(job)").fetchall()}
    split = {"owner_kind", "owner_id"} <= have

    buckets: dict[str, int] = {}
    samples: dict[str, str] = {}
    for (owner,) in con.execute("SELECT owner FROM job"):
        k = classify_owner(owner)
        buckets[k] = buckets.get(k, 0) + 1
        samples.setdefault(k, owner if owner is not None else "")

    if split:
        # 분리 후 판정: ① owner_kind 미채움 0 ② owner_id 는 bot 종류만
        unfilled = con.execute("SELECT COUNT(*) FROM job WHERE owner_kind IS NULL").fetchone()[0]
        stray = con.execute(
            "SELECT COUNT(*) FROM job WHERE owner_id IS NOT NULL AND owner_id NOT LIKE 'fbot-%'"
        ).fetchone()[0]
        ok = (unfilled == 0 and stray == 0)
        return {
            "id": "b_owner_polymorphism",
            "label": "job.owner 다형성 (분리 축 기준)",
            "severity": "warn",
            "ok": ok,
            "split": True,
            "by_kind": buckets,
            "samples": samples,
            "owner_kind_unfilled": unfilled,
            "owner_id_stray": stray,
            "note": "" if ok else (
                f"분리 축이 불완전하다 — owner_kind 미채움 {unfilled}건 · "
                f"owner_id 이물 {stray}건. ensure_schema() 백필을 다시 태우라."
            ),
        }

    kinds = [k for k in buckets if k not in ("null",)]
    ok = len(kinds) <= 1
    return {
        "id": "b_owner_polymorphism",
        "label": "job.owner 다형성",
        "severity": "warn",
        "ok": ok,
        "split": False,
        "by_kind": buckets,
        "samples": samples,
        "note": (
            "한 컬럼에 봇 귀속(fbot-*)과 락 소유자(<host>/<pid>)가 섞여 있어 "
            "bot.bot_id 로의 FK 가 불가능하다. 해소하려면 owner_kind + owner_id 2컬럼 "
            "분리가 필요하다 — Issue516 의 ensure_schema() 마이그레이션을 태우라."
        ) if not ok else "",
    }


# ── ⓒ bot_id slug ───────────────────────────────────────────────────────────

def normalize_issue_token(issue: str) -> str:
    """현행 생성 규칙(fbot-lead.py) 재현 — 비[a-z0-9-] 를 **삭제**한다."""
    return re.sub(r"[^a-z0-9-]", "", issue.lower())


def check_slug(con: sqlite3.Connection) -> dict:
    # (1) 코드 점검 — 생성기가 아직 구분자를 삭제하는가
    code_buggy = None
    if os.path.exists(SLUG_SOURCE):
        try:
            src = open(SLUG_SOURCE, encoding="utf-8").read()
            code_buggy = bool(SLUG_BAD_RE.search(src))
        except OSError:
            code_buggy = None

    # (2) 데이터 점검 — 실제 발급된 id 중 정규화 후 충돌하는 쌍
    seen: dict[str, set[str]] = {}
    for (bid,) in con.execute("SELECT bot_id FROM bot"):
        seen.setdefault(re.sub(r"[^a-z0-9]", "", bid.lower()), set()).add(bid)
    for (payload,) in con.execute("SELECT payload FROM job"):
        p = parse_payload(payload)
        for k in PAYLOAD_BOT_KEYS:
            v = p.get(k)
            if isinstance(v, str) and v.startswith("fbot-"):
                seen.setdefault(re.sub(r"[^a-z0-9]", "", v.lower()), set()).add(v)
    collisions = {k: sorted(v) for k, v in seen.items() if len(v) > 1}

    # (3) 위험 증거 — 구분자를 잃은 흔적(원 이슈에 `_` 가 있었던 배분)
    lossy = []
    for jid, payload in con.execute("SELECT id, payload FROM job WHERE payload LIKE '%worker_bot_id%'"):
        p = parse_payload(payload)
        issue, wid = p.get("issue"), p.get("worker_bot_id")
        if isinstance(issue, str) and isinstance(wid, str) and "_" in issue:
            if normalize_issue_token(issue) in wid:
                lossy.append({"job_id": jid, "issue": issue, "bot_id": wid,
                              "safe_slug": re.sub(r"[^a-z0-9]+", "-", issue.lower()).strip("-")})

    ok = not collisions
    return {
        "id": "c_bot_id_slug",
        "label": "bot_id slug 생성 규칙",
        "severity": "error" if collisions else "warn",
        "ok": ok and not code_buggy,
        "generator": SLUG_SOURCE,
        "generator_drops_separator": code_buggy,
        "actual_collisions": collisions,
        "lossy_ids": lossy,
        "note": (
            "생성기가 `[^a-z0-9-]` 를 삭제해 `Issue436_3` → `fbot-research-issue4363` 가 된다. "
            "`Issue43_63` 과 같은 id 로 충돌할 수 있다. 최소 교정은 삭제 대신 치환: "
            "`re.sub(r\"[^a-z0-9]+\", \"-\", issue.lower())`. 기존 id 는 소급 변경하지 않는다."
        ) if (code_buggy or collisions) else "",
    }


# ── ⓓ budget 스키마 ────────────────────────────────────────────────────────

def check_budget(con: sqlite3.Connection) -> dict:
    def count(t):
        try:
            return con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            return None
    tbl_day, tbl_month = count("budget"), count("budget_monthly")
    kv_rows = [dict(r) for r in con.execute(
        "SELECT ns, key, value, updated_by FROM kv WHERE ns='fbot:budget' ORDER BY key")]
    return {
        "id": "d_budget_schema",
        "label": "예산 원장 이원",
        "severity": "info",
        "ok": True,   # 축 분리는 설계다 — 결손이 아니다
        "table_budget_rows": tbl_day,
        "table_budget_monthly_rows": tbl_month,
        "kv_fbot_budget": kv_rows,
        "note": (
            "`budget`/`budget_monthly` 는 aoa-memory 통합(consolidation)의 **LLM 토큰** 예산이고"
            "(mcp/aoa-memory/store.py record_budget, store='llm'), fbot 의 **월 스폰 건수** 예산은"
            " kv ns `fbot:budget` 이다(hooks/fbot-hr-gate.py:62 — 계약 T2 로 재사용 금지 명시). "
            "축이 다르므로 0행은 죽은 스키마가 아니라 '아직 LLM 통합이 돌지 않았다'는 뜻이다. "
            "DROP 도 승격도 오답 — 이름 충돌을 문서로 분리하는 것이 정답."
        ),
    }


# ── ⓔ 고아 ─────────────────────────────────────────────────────────────────

def scan_orphans(con: sqlite3.Connection, min_age_hours: float) -> dict:
    bots = known_bots(con)
    now = int(time.time())
    cutoff = now - int(min_age_hours * 3600)

    def alive(bid: str) -> bool:
        return bid in bots or bid in VIRTUAL_BOT_IDS or bid in HISTORICAL_BOT_IDS

    purge_jobs: dict[str, dict] = {}
    keep_jobs: dict[str, dict] = {}
    virtual_hits = 0

    for row in con.execute("SELECT id, kind, status, owner, payload, created_at FROM job"):
        jid, kind, status, owner, payload, created = (
            row["id"], row["kind"], row["status"], row["owner"], row["payload"], row["created_at"])
        refs: list[tuple[str, str]] = []
        if classify_owner(owner) == "bot" and owner not in bots:
            if owner in VIRTUAL_BOT_IDS or owner in HISTORICAL_BOT_IDS:
                virtual_hits += 1
            else:
                refs.append(("owner", owner))
        p = parse_payload(payload)
        for k in PAYLOAD_BOT_KEYS:
            v = p.get(k)
            if isinstance(v, str) and v.startswith("fbot-") and not alive(v):
                refs.append((k, v))
            elif isinstance(v, str) and v in VIRTUAL_BOT_IDS and v not in bots:
                virtual_hits += 1
        if not refs:
            continue
        created = int(created or 0)
        rec = {"job_id": jid, "kind": kind, "status": status, "owner": owner,
               "created_at": created,
               "created": time.strftime("%Y-%m-%d %H:%M", time.localtime(created)) if created else None,
               "dangling_refs": [{"field": f, "bot_id": b} for f, b in refs]}
        if status not in TERMINAL_STATUS:
            rec["protected_by"] = f"status={status} (비종결)"
            keep_jobs[jid] = rec
        elif created >= cutoff:
            rec["protected_by"] = f"최근 {min_age_hours}h 이내 — 살아 있는 작업일 수 있음"
            keep_jobs[jid] = rec
        else:
            purge_jobs[jid] = rec

    purge_kv, keep_kv = [], []
    for r in con.execute("SELECT ns, key, value, updated_at FROM kv WHERE ns LIKE 'fbot:fbot-%'"):
        bid = r["ns"][len("fbot:"):]
        if alive(bid):
            continue
        upd = int(r["updated_at"] or 0)
        rec = {"ns": r["ns"], "key": r["key"], "bot_id": bid, "updated_at": upd,
               "value": (r["value"] or "")[:200]}
        if upd and upd >= cutoff:
            rec["protected_by"] = f"최근 {min_age_hours}h 이내"
            keep_kv.append(rec)
        else:
            purge_kv.append(rec)

    return {
        "bots_known": sorted(bots),
        "virtual_whitelist": sorted(VIRTUAL_BOT_IDS),
        "virtual_ref_count": virtual_hits,
        "min_age_hours": min_age_hours,
        "cutoff_epoch": cutoff,
        "purge": {"jobs": list(purge_jobs.values()), "kv": purge_kv},
        "keep": {"jobs": list(keep_jobs.values()), "kv": keep_kv},
    }


def check_orphans(scan: dict) -> dict:
    n_pj, n_pk = len(scan["purge"]["jobs"]), len(scan["purge"]["kv"])
    n_kj, n_kk = len(scan["keep"]["jobs"]), len(scan["keep"]["kv"])
    return {
        "id": "e_orphans",
        "label": "대장에 없는 봇 참조(고아)",
        "severity": "error",
        "ok": (n_pj + n_pk) == 0,
        "purgeable_jobs": n_pj,
        "purgeable_kv_rows": n_pk,
        "protected_jobs": n_kj,
        "protected_kv_rows": n_kk,
        "virtual_ref_count": scan["virtual_ref_count"],
        "detail": {"purge": scan["purge"], "keep": scan["keep"]},
        "note": (
            (f"가상 정체({', '.join(sorted(VIRTUAL_BOT_IDS))}) 참조 "
             f"{scan['virtual_ref_count']}건은 고아가 아니다(코드 하드코딩 발신자 id). "
             if VIRTUAL_BOT_IDS else
             "가상 정체 화이트리스트는 비어 있다(Issue528) — 모든 봇 참조는 대장으로 판정한다. ")
            + "보호된 항목은 비종결이거나 최근 기록이라 살아 있는 작업일 수 있어 남긴다."
        ),
    }


# ── --fix ──────────────────────────────────────────────────────────────────

def backup_db(path: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = f"{path}.bak.audit-{stamp}"
    if os.path.exists(dst):
        raise AuditError(f"백업 대상이 이미 있다: {dst}")
    # 소스 연결의 VACUUM INTO 가 WAL 까지 반영한 일관 사본을 만든다(cp 는 -wal 을 놓친다).
    con = sqlite3.connect(path, timeout=10)
    try:
        con.execute("VACUUM INTO ?", (dst,))
    except sqlite3.Error:
        con.close()
        shutil.copy2(path, dst)     # 구버전 sqlite 폴백
        return dst
    con.close()
    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise AuditError(f"백업 생성 실패: {dst}")
    return dst


def apply_fix(path: str, scan: dict, backup: str) -> dict:
    """ⓔ 고아만 삭제한다. 스키마는 건드리지 않는다."""
    evidence = f"{backup}.deleted.json"
    with open(evidence, "w", encoding="utf-8") as f:
        json.dump({"deleted_at": int(time.time()), "db": path, "backup": backup,
                   "purge": scan["purge"]}, f, ensure_ascii=False, indent=2)

    job_ids = [r["job_id"] for r in scan["purge"]["jobs"]]
    kv_keys = [(r["ns"], r["key"]) for r in scan["purge"]["kv"]]
    con = connect(path, readonly=False)
    try:
        con.execute("BEGIN IMMEDIATE")
        before_bot = con.execute("SELECT COUNT(*) FROM bot").fetchone()[0]
        before_job = con.execute("SELECT COUNT(*) FROM job").fetchone()[0]
        before_kv = con.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
        for jid in job_ids:
            con.execute("DELETE FROM job WHERE id = ?", (jid,))
        for ns, key in kv_keys:
            con.execute("DELETE FROM kv WHERE ns = ? AND key = ?", (ns, key))
        after_bot = con.execute("SELECT COUNT(*) FROM bot").fetchone()[0]
        after_job = con.execute("SELECT COUNT(*) FROM job").fetchone()[0]
        after_kv = con.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
        # 불변식 — 대장은 절대 줄지 않는다. 어긋나면 커밋하지 않고 폐기한다.
        if after_bot != before_bot:
            con.execute("ROLLBACK")
            raise AuditError(f"불변식 위반: bot {before_bot}→{after_bot} — 롤백함")
        if before_job - after_job != len(job_ids) or before_kv - after_kv != len(kv_keys):
            con.execute("ROLLBACK")
            raise AuditError("불변식 위반: 삭제 건수 불일치 — 롤백함")
        con.execute("COMMIT")
    except AuditError:
        raise
    except sqlite3.Error as e:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise AuditError(f"삭제 실패({e}) — 롤백: cp '{backup}' '{path}'") from e
    finally:
        con.close()
    return {"deleted_jobs": len(job_ids), "deleted_kv_rows": len(kv_keys),
            "evidence": evidence,
            "counts": {"bot": [before_bot, after_bot], "job": [before_job, after_job],
                       "kv": [before_kv, after_kv]}}


# ── 실행 ───────────────────────────────────────────────────────────────────

# ── ⓕ 조직 선언 정합 (prj3#Issue538) ────────────────────────────────────────
#   하이브리드 SSOT(선언은 파일 · 상태는 DB)의 대가를 여기서 갚는다. 구조와 상태가
#   두 소스로 갈렸으므로, 둘이 어긋나는 3가지를 기계로 잡는다.

def _load_org_module():
    """`fbot-org.py` 는 하이픈 파일명이라 일반 import 가 안 된다. 로직 복제 대신 로드한다."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-org.py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("fbot_org", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def check_org(con: sqlite3.Connection) -> dict:
    org = _load_org_module()
    if org is None:
        return {"id": "f_org", "label": "조직 선언 정합", "severity": "warn", "ok": True,
                "unknown_role_seats": [], "orphan_seat_bindings": [], "stale_drops": [],
                "invalid_ext_fields": [], "unknown_engines": [],
                "same_engine_checks": [], "non_checker_targets": [],
                "skipped": "fbot-org.py 부재 또는 PyYAML 미설치 — 조직 기능 미도입 상태로 본다"}

    roles = org.catalog_roles()
    declared, declared_seats, bad_role, stale_drops, invalid_ext = {}, {}, [], [], []
    # prj3#Issue757 — 선언 목록 원천은 fbot-org `_declared_names`(사용자 폴더 ∪ 번들 폴백) 하나
    names = org._declared_names() if hasattr(org, "_declared_names") else (
        sorted(f[:-4] for f in os.listdir(org.ORG_DIR) if f.endswith(".yml")) if os.path.isdir(org.ORG_DIR) else [])
    for name in names:
        prj = None if name == "_hq" else (int(name) if name.isdigit() else None)
        if name != "_hq" and prj is None:
            continue                      # _template 등은 직접 해소 대상이 아니다
        got = org.resolve(prj)
        if not got.get("ok"):
            continue
        for st in got["seats"]:
            # 🔴 seat_id 가 아니라 **주소**(scope/seat_id)로 센다. 템플릿을 공유하므로
            #   `dev-architect-1` 이 여러 조직에 동시 존재한다 — id 로 키를 잡으면
            #   자리 93개가 12개로 뭉개지고, 그 상태의 고아 판정은 **다른 프로젝트의
            #   자리에 앉은 봇을 정상으로 통과시킨다**(2026-09-05 실측).
            declared[st.get("addr") or st["id"]] = name
            declared_seats[st.get("addr") or st["id"]] = st
            if roles and st.get("role") not in roles:
                bad_role.append({"org": name, "seat": st["id"], "role": st.get("role")})
        for d in got.get("stale_drops") or []:
            stale_drops.append({"org": name, "drop": d})
        for item in got.get("invalid") or []:
            invalid_ext.append(dict(item, org=name))

    unknown_engines = []
    for role, attrs in sorted(org.catalog_attrs().items()):
        for value in (attrs.get("engine") or "").split("|"):
            if value and value not in org.ENGINES:
                unknown_engines.append({"role": role, "value": value})

    same_engine, non_checker = [], []
    for addr, st in declared_seats.items():
        target = st.get("checked_by_addr")
        target_seat = declared_seats.get(target)
        if not target or target_seat is None:
            continue
        warning = {"org": declared.get(addr), "seat": st.get("id"), "target": target}
        if org.role_engines(st.get("role")) & org.role_engines(target_seat.get("role")):
            same_engine.append(warning)
        if not org.is_checker(target_seat.get("role")):
            non_checker.append(warning)

    orphan_seats = []
    cols = {r[1] for r in con.execute("PRAGMA table_info(bot)")}
    if "seat_id" in cols:
        for r in con.execute("SELECT bot_id, seat_id FROM bot WHERE seat_id IS NOT NULL"):
            if r["seat_id"] not in declared:
                orphan_seats.append({"bot_id": r["bot_id"], "seat_id": r["seat_id"]})

    ok = not (bad_role or orphan_seats or stale_drops or invalid_ext or unknown_engines)
    return {
        "id": "f_org", "label": "조직 선언 정합", "severity": "warn", "ok": ok,
        "declared_orgs": len(names), "declared_seats": len(declared),
        "unknown_role_seats": bad_role,       # ① 카탈로그 미등재 role 참조
        "orphan_seat_bindings": orphan_seats,  # ② 없는 자리를 가리키는 bot.seat_id
        "stale_drops": stale_drops,            # ③ 대상 없는 drop — 낡은 override
        "invalid_ext_fields": invalid_ext,
        "unknown_engines": unknown_engines,
        "same_engine_checks": same_engine,
        "non_checker_targets": non_checker,
        "note": ("" if ok else
                 "선언(파일)과 대장(DB)이 어긋났다. ①은 카탈로그에 없는 role 이라 HR 배치가 "
                 "불가능하고, ②는 조직도에서 고아가 되며, ③은 상위에서 이미 사라진 자리를 "
                 "지우려는 낡은 override 다. 선언 확장 무효값과 카탈로그 미지원 엔진도 "
                 "해소·선택 판정을 갈라놓는다."),
    }


def check_bot_refs(con: sqlite3.Connection) -> dict:
    """ⓖ `bot` 테이블 **내부 참조**가 대장을 벗어나지 않는지.

    ⓔ orphans 는 `job`·`kv` 가 대장 밖 봇을 가리키는 것을 잡지만, **`bot` 이 `bot` 을
    가리키는 축**(`parent_bot_id`)은 아무도 보지 않았다. 여기에는 FK 제약도 없어서
    ``PRAGMA foreign_key_check`` 도 침묵한다.

    실발생(prj3#Issue610, 2026-09-10): 이름 개편에서 `fbot-taskmgr` → `fbot-lead` 로
    개체 id 를 옮기면서 **자식 21건의 `parent_bot_id` 를 안 따라 옮겼다**. 회귀·조직
    정합·감사 전부 통과했는데 조직 트리의 부모 간선만 조용히 끊겨 있었다 — 지금
    그것을 잡는 자리다.
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info(bot)")}
    if "parent_bot_id" not in cols:
        return {"id": "g_bot_refs", "label": "봇 내부 참조", "severity": "error", "ok": True,
                "skipped": "parent_bot_id 컬럼 없음"}
    dangling = [{"bot_id": r["bot_id"], "parent_bot_id": r["parent_bot_id"]}
                for r in con.execute(
                    "SELECT bot_id, parent_bot_id FROM bot WHERE parent_bot_id IS NOT NULL "
                    "AND parent_bot_id NOT IN (SELECT bot_id FROM bot)")]
    self_ref = [r["bot_id"] for r in con.execute(
        "SELECT bot_id FROM bot WHERE parent_bot_id = bot_id")]
    ok = not (dangling or self_ref)
    return {
        "id": "g_bot_refs", "label": "봇 내부 참조", "severity": "error", "ok": ok,
        "dangling_parents": dangling,   # ① 대장에 없는 부모 — 조직 트리가 끊긴다
        "self_parents": self_ref,       # ② 자기 자신이 부모 — 트리 순회가 돌 수 있다
        "note": ("" if ok else
                 "parent_bot_id 가 대장 밖을 가리킨다. FK 제약이 없어 foreign_key_check 는 "
                 "통과하지만 조직 트리에서 그 봇들은 부모를 잃는다. 개체 id 를 rename 했다면 "
                 "자식의 parent_bot_id 도 함께 옮겼는지 확인할 것(prj3#Issue610 실발생)."),
    }


def audit(db_path: str, source: str, min_age_hours: float, do_fix: bool, strict: bool) -> tuple[dict, int]:
    con = connect(db_path, readonly=not do_fix)
    try:
        checks = [check_fk(con), check_owner_polymorphism(con), check_slug(con),
                  check_budget(con), check_org(con), check_bot_refs(con)]
        scan = scan_orphans(con, min_age_hours)
        checks.append(check_orphans(scan))
        totals = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("bot", "job", "kv")}
    finally:
        con.close()

    result = {
        "tool": "fbot-registry-audit",
        "issue": "prj3#Issue515",
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": db_path,
        "db_path_source": source,
        "mode": "fix" if do_fix else "dry-run",
        "strict": strict,
        "row_counts_before": totals,
        "checks": {c["id"]: c for c in checks},
    }

    fix_info = None
    if do_fix:
        n = len(scan["purge"]["jobs"]) + len(scan["purge"]["kv"])
        if n == 0:
            result["fix"] = {"skipped": "정리 대상 없음 — 백업도 만들지 않았다"}
        else:
            backup = backup_db(db_path)
            fix_info = apply_fix(db_path, scan, backup)
            fix_info["backup"] = backup
            fix_info["rollback"] = f"cp '{backup}' '{db_path}'"
            result["fix"] = fix_info
            # 재검사 — 정리 후 상태를 같은 실행에서 확정한다
            con = connect(db_path, readonly=True)
            try:
                rescan = scan_orphans(con, min_age_hours)
                result["checks"]["e_orphans"] = check_orphans(rescan)
                result["row_counts_after"] = {
                    t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("bot", "job", "kv")}
            finally:
                con.close()

    failed = [c["id"] for c in result["checks"].values()
              if not c["ok"] and (c["severity"] == "error" or (strict and c["severity"] == "warn"))]
    result["failed_checks"] = failed
    result["rc"] = 1 if failed else 0
    return result, result["rc"]


def summary_line(r: dict) -> str:
    e = r["checks"]["e_orphans"]
    b = r["checks"]["b_owner_polymorphism"]["by_kind"]
    fixed = r.get("fix", {})
    head = "✅ 정합성 OK" if r["rc"] == 0 else "❌ 정합성 위반"
    bits = [
        f"고아 job {e['purgeable_jobs']}·kv {e['purgeable_kv_rows']}",
        f"보호 job {e['protected_jobs']}·kv {e['protected_kv_rows']}",
        f"owner {b.get('bot', 0)}봇/{b.get('lock', 0)}락",
        f"FK {r['checks']['a_fk_declaration']['declared_fk_count']}건",
    ]
    if fixed.get("deleted_jobs") is not None:
        bits.append(f"삭제 job {fixed['deleted_jobs']}·kv {fixed['deleted_kv_rows']}")
    tail = f" · 실패: {', '.join(r['failed_checks'])}" if r["failed_checks"] else ""
    return f"{head} [{r['mode']}] — " + " · ".join(bits) + tail


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="fbot-registry-audit.py",
        description="fbot 레지스트리(bot·job·kv) 정합성 검사 — 기본은 읽기 전용 dry-run")
    ap.add_argument("--db", help="registry.db 경로(기본: AOA_MEMORY_DIR/registry.db)")
    ap.add_argument("--fix", action="store_true",
                    help="ⓔ 고아만 삭제한다(백업 필수·스키마 불변). 미지정 시 dry-run")
    ap.add_argument("--dry-run", action="store_true", help="명시적 dry-run(기본값)")
    ap.add_argument("--min-age-hours", type=float, default=DEFAULT_MIN_AGE_HOURS,
                    help=f"이보다 최근인 기록은 보호한다(기본 {DEFAULT_MIN_AGE_HOURS}h)")
    ap.add_argument("--strict", action="store_true", help="warn 도 rc=1 로 승격")
    ap.add_argument("--quiet", action="store_true", help="요약 줄 없이 JSON 만 출력")
    args = ap.parse_args(argv)

    if args.fix and args.dry_run:
        print("--fix 와 --dry-run 을 동시에 줄 수 없다.", file=sys.stderr)
        return 2
    try:
        db, src = resolve_db(args.db)
        result, rc = audit(db, src, args.min_age_hours, args.fix, args.strict)
    except AuditError as e:
        print(f"❌ 실행 실패 — {e}", file=sys.stderr)
        return 2
    except sqlite3.Error as e:
        print(f"❌ SQLite 오류 — {e}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(summary_line(result))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
