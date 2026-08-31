#!/usr/bin/env python3
"""fbot 인사핀봇(HR) 게이트 (Issue436_3 s2 — T2).

계약: ~/.claude/_doc_arch/fbot-arch.md §호출 경계(F3) — 판정 5종·게이트 CLI 계약.
      미해결 표 s2 확정(2026-08-24): helper 스크립트 형태, MCP tool 승격은 수요 실증 후.
      계약 참조만 하며 여기서 재결정하지 않는다.

CLI (계약 그대로)
    hire  --bot-id --role --title [--parent] [--prj] [--career probation]
          판정 5종 계약 순서 — ① 레지스트리 조회(중복 bot_id 거부 + role 카탈로그 검증)
          ② policy 판정(값 로드 실패 시 fail-loud) ③ 예산(상한 도달 시 거부 — 차감은
          전 판정 통과 확정 후 원자적) ④ 스폰 깊이(parent 체인 역추적 ≤ limit)
          ⑤ 동시 상주(state != checkout 봇 수 < limit).
          전부 통과 → fbot-state.py register 호출로 채용 완료 + 허가 JSON.
    check --parent <bot_id|-> [--kind delegate]
          일반 위임(비봇 — 채용 아님): ④ 깊이 + ⑤ 동시 상주만. 등록·차감 없음.
    status
          이번 달 예산 소진·동시 상주 수·limit 출력.

설계 원칙 (fbot-state.py 승계)
* 표준 라이브러리만 사용(무의존). policy.yml·catalog.yml 은 평탄 키라 정규식으로 읽는다.
* fail-loud: 거부는 `판정 ③ 거부: <사유>` 형식(판정 번호+사유) + exit 1. silent fail 금지.
* 예산 차감은 BEGIN IMMEDIATE 안에서 상한 재검증 후 증분(다중 프로세스 동시 hire 경쟁 대비).
* 예산 원장: registry.kv ns=`fbot:budget` key=YYYY-MM — 신규 월 키 생성이 곧 리셋(리셋 잡 없음).
* 상한 수치는 aoa policy.yml `fbot_*` 3키가 SSOT — 하드코딩 금지.
* `AOA_MEMORY_DIR` env 존중(fbot-state.py 와 동일 방식).
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
DEFAULT_AOA_DIR = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa")

# role 카탈로그 SSOT — fbot-icon 스킬 소유 (fbot-arch.md §조직 role 등록 절차 ⑤단계).
#   env 는 테스트 픽스처 주입용(fbot-recruit.py 와 동일 규약).
CATALOG_PATH = os.environ.get("FBOT_CATALOG") or os.path.join(
    os.path.expanduser("~"), ".claude", "data", "fbot", "icons", "catalog.yml")

# policy.yml 필수 키 3종 (T1 편입분) — 로드 실패 시 판정 ② fail-loud
POLICY_KEYS = ("fbot_spawn_depth_limit", "fbot_concurrent_limit", "fbot_spawn_budget_monthly")

# 수명주기 판정 키 (prj3#Issue481) — 배치(hire) 판정과 **축이 다르므로 따로 로드**한다.
#   같은 튜플에 넣으면 키 하나가 없을 때 배치까지 죽는다(가용성 축 분리).
LIFECYCLE_KEYS = ("fbot_promote_job_min", "fbot_promote_fail_pct_max",
                  "fbot_idle_archive_days", "fbot_unused_archive_days")

# 봇 귀속 job kind — `job` 테이블은 봇 전용이 아니다. aoa-memory 배치(`consolidation`,
#   owner=`jm4/12345`)가 수백 건 섞여 있어, kind 로 거르지 않으면 승격 판정이 통째로 오염된다.
FBOT_JOB_KINDS = ("fbot_session", "fbot_dispatch", "fbot_report")

# 상비 role — 값의 SSOT 는 fbot-state.py CORE_ROLES 다(여기는 후보 스캔용 사본).
#   ⚠️ 값을 바꿀 일이 생기면 그쪽을 먼저 고친다. 판정 자체는 기록 계층이 최종 방어한다.
CORE_ROLES = ("exec", "recruit", "hr", "taskmgr")

BUDGET_NS = "fbot:budget"  # registry.kv 예산 원장 네임스페이스 (registry budget/budget_monthly 재사용 금지 — 계약 T2)

CIRCLED = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤"}

STATE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-state.py")
# 아이콘 생성기 — fbot-icon 스킬 소유(카탈로그와 같은 SSOT). 색·도형·경로 규약을 여기서
#   복제하지 않고 `gen --json` 으로 **물어본다**(fbot-arch §F1 판정 단일 지점).
ICON_GEN = os.path.join(os.path.expanduser("~"), ".claude", "skills", "fbot-icon",
                        "scripts", "fbot-icon-gen.py")


class FbotError(Exception):
    """fail-loud 용 — 판정 이전 단계의 인프라·입력 오류."""


class Reject(Exception):
    """게이트 거부 — 판정 번호 + 사유. exit 1."""

    def __init__(self, n: int, reason: str):
        self.n = n
        self.reason = reason
        super().__init__(f"판정 {CIRCLED[n]} 거부: {reason}")


# ── 경로·정책·카탈로그 ──────────────────────────────────────────────────────

def aoa_dir() -> str:
    return os.environ.get("AOA_MEMORY_DIR") or DEFAULT_AOA_DIR


def registry_path() -> str:
    p = os.path.join(aoa_dir(), "registry.db")
    if not os.path.exists(p):
        raise FbotError(f"레지스트리 DB 없음: {p} (AOA_MEMORY_DIR 확인)")
    return p


def load_policy(keys=POLICY_KEYS) -> dict:
    """aoa policy.yml 의 fbot_* 키 로드. 파일·키 부재 = 판정 ② fail-loud (기본값 폴백 금지).

    `keys` 로 검증 대상을 갈아끼운다 — 배치(POLICY_KEYS)와 수명주기(LIFECYCLE_KEYS)는
    축이 달라, 한쪽 키 부재가 다른 쪽 기능을 죽이면 안 된다.
    """
    path = os.path.join(aoa_dir(), "policy.yml")
    if not os.path.exists(path):
        raise Reject(2, f"policy 로드 실패 — 파일 없음: {path}")
    pol = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^(fbot_[a-z_]+):\s*(\d+)", line)
            if m:
                pol[m.group(1)] = int(m.group(2))
    missing = [k for k in keys if k not in pol]
    if missing:
        raise Reject(2, f"policy 로드 실패 — {path} 에 키 부재: {', '.join(missing)}")
    bad = [k for k in keys if pol[k] <= 0]
    if bad:
        raise Reject(2, f"policy 값 불량(양수 아님): {', '.join(f'{k}={pol[k]}' for k in bad)}")
    return pol


# ── 수명주기 판정 (prj3#Issue481) ────────────────────────────────────────────

def bot_job_stats(con: sqlite3.Connection, bot_id: str) -> dict:
    """봇 귀속 job 통계 — 완료·실패 건수와 마지막 활동 시각.

    ⚠️ `cancelled` 는 완료에도 실패에도 넣지 않는다. 계약 §배분 상태가 *"취소는 성과가
       아니다"* 로 done 과 분리했듯, 워커가 일했다고 주장하지 않는 사건이라 실패율의
       분모에도 들어가면 안 된다 — 넣으면 취소가 많은 봇이 무능한 봇으로 오판된다.
    """
    ph = ",".join("?" * len(FBOT_JOB_KINDS))
    row = con.execute(
        f"SELECT SUM(status = 'done') AS done, SUM(status = 'failed') AS failed,"
        f" COUNT(*) AS total, MAX(created_at) AS last_at"
        f" FROM job WHERE owner = ? AND kind IN ({ph})",
        (bot_id, *FBOT_JOB_KINDS),
    ).fetchone()
    done = row["done"] or 0
    failed = row["failed"] or 0
    judged = done + failed
    return {
        "done": done, "failed": failed, "total": row["total"] or 0,
        "last_at": row["last_at"],
        "fail_pct": round(failed * 100 / judged, 1) if judged else 0.0,
    }


def judge_promote(stats: dict, pol: dict) -> tuple:
    """승격 요건 판정 (s2 확정: job N건 + 실패율 <M%). 사람 승인은 호출자 몫."""
    reasons = []
    if stats["done"] < pol["fbot_promote_job_min"]:
        reasons.append(f"완료 {stats['done']}건 < 요건 {pol['fbot_promote_job_min']}건")
    if stats["fail_pct"] >= pol["fbot_promote_fail_pct_max"]:
        reasons.append(f"실패율 {stats['fail_pct']}% ≥ 상한 {pol['fbot_promote_fail_pct_max']}%")
    return (not reasons), reasons


def judge_archive(bot: sqlite3.Row, stats: dict, pol: dict, now: int) -> tuple:
    """유휴 판정 2축 — ⓐ 마지막 job 이후 유휴 ⓑ 배치 후 무활동 조기회수.

    ⓑ 가 없으면 **한 번도 일하지 않은 봇은 판정 자체가 성립하지 않는다** — "마지막 job"
    이 없기 때문이다. 실측(2026-08-31)에서 13봇 중 8봇이 그 상태였다.
    """
    if stats["last_at"]:
        days = (now - stats["last_at"]) // 86400
        limit = pol["fbot_idle_archive_days"]
        return (days >= limit), f"마지막 활동 {days}일 전 (임계 {limit}일)", days
    days = (now - bot["created_at"]) // 86400
    limit = pol["fbot_unused_archive_days"]
    return (days >= limit), f"배치 {days}일 경과·활동 0건 (조기회수 임계 {limit}일)", days


def load_catalog() -> dict:
    """role 카탈로그 로드 — {role: base_color}. 카탈로그 부재는 fail-loud (판정 ① 의 전제).

    `status=archived` 인 role 은 **로드 자체에서 뺀다** (prj3#Issue480 직능 아카이브) —
    판정 ① 이 "미등재" 와 동일하게 거부하게 되어, 아카이브 검사 지점이 따로 늘지 않는다.
    부활(revive)은 status 제거 1줄이므로 이 함수는 상태를 캐시하지 않는다.
    """
    if not os.path.exists(CATALOG_PATH):
        raise FbotError(f"role 카탈로그 없음: {CATALOG_PATH} — fbot-icon 스킬로 초기화하라")
    roles = {}
    with open(CATALOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^([a-z][a-z0-9_-]*):\s*shape=\S+\s+base=(#[0-9A-Fa-f]{6})", line)
            if m and "status=archived" not in line:
                roles[m.group(1)] = m.group(2)
    if not roles:
        raise FbotError(f"role 카탈로그 파싱 결과 0건: {CATALOG_PATH} — 형식 확인")
    return roles


# ── DB ──────────────────────────────────────────────────────────────────────

def connect() -> sqlite3.Connection:
    con = sqlite3.connect(registry_path(), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def month_key(now: float | None = None) -> str:
    return time.strftime("%Y-%m", time.localtime(now if now is not None else time.time()))


def budget_spent(con: sqlite3.Connection, month: str) -> int:
    row = con.execute(
        "SELECT value FROM kv WHERE ns = ? AND key = ?", (BUDGET_NS, month)
    ).fetchone()
    return int(row["value"]) if row is not None else 0


def chain_depth(con: sqlite3.Connection, parent_id: str | None, limit: int) -> tuple[int, list]:
    """신규 스폰의 깊이 = parent 체인 길이 + 1. 부모 없음(root) = 1.

    체인 역추적은 limit+2 스텝에서 중단(순환 방어 — 초과분은 어차피 거부).
    미등록 parent 는 fail-loud — 유령 부모를 조상으로 인정하지 않는다.
    """
    chain = []
    cur = parent_id
    while cur is not None:
        row = con.execute(
            "SELECT bot_id, parent_bot_id FROM bot WHERE bot_id = ?", (cur,)
        ).fetchone()
        if row is None:
            raise FbotError(f"미등록 parent 봇: {cur} — 체인 역추적 불가")
        if cur in chain:
            raise FbotError(f"parent 체인 순환 감지: {' → '.join(chain + [cur])}")
        chain.append(cur)
        if len(chain) > limit + 1:  # 이미 상한 초과 확정 — 더 걸을 이유 없음
            break
        cur = row["parent_bot_id"]
    return len(chain) + 1, chain


def active_count(con: sqlite3.Connection) -> int:
    """동시 상주 = state != checkout 인 봇 수 (계약 판정 ⑤)."""
    return con.execute("SELECT COUNT(*) AS c FROM bot WHERE state != 'checkout'").fetchone()["c"]


def ensure_bot_icon(bot_id: str, role: str) -> tuple:
    """채용 시 개체 아이콘을 생성하고 (상대경로, 개체색) 을 돌려준다.

    왜 채용 경로에 있는가 — 아이콘·색은 레지스트리 레코드의 필드이고, 그 레코드를 만드는
    유일한 지점이 채용이다(prj3#Issue438 실측: 이 배선이 없어 13봇 중 12봇의 icon 이 NULL
    이었고, color 에는 role 기본색이 들어가 같은 role 봇이 전부 동색이었다).

    실패는 fail-soft — 아이콘은 **표시 품질**이지 채용 판정 요소가 아니다. 다만 조용히
    넘기지 않고 (None, None) 을 돌려 호출부가 경고를 기록하게 한다.
    """
    if not os.path.exists(ICON_GEN):
        return (None, None)
    try:
        proc = subprocess.run(
            [sys.executable, ICON_GEN, "gen", "--role", role, "--bot-id", bot_id, "--json"],
            capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return (None, None)
        d = json.loads(proc.stdout)
        return (d.get("rel_path"), d.get("color"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return (None, None)


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── 판정 ④⑤ 공통 (hire·check 공용 — 판정 로직 중복 구현 금지) ──────────────

def judge_depth(con, parent_id, pol) -> int:
    limit = pol["fbot_spawn_depth_limit"]
    depth, chain = chain_depth(con, parent_id, limit)
    if depth > limit:
        raise Reject(4, f"스폰 깊이 초과 — 깊이 {depth} > 상한 {limit} (체인: {' → '.join(reversed(chain))} → 신규)")
    return depth


def judge_concurrent(con, pol) -> int:
    limit = pol["fbot_concurrent_limit"]
    n = active_count(con)
    if n >= limit:
        raise Reject(5, f"동시 상주 초과 — 활성(state != checkout) 봇 {n}개 ≥ 상한 {limit}")
    return n


# ── 서브커맨드 ──────────────────────────────────────────────────────────────

def cmd_hire(args) -> int:
    """채용 — 판정 5종 계약 순서. 전부 통과 → 예산 원자 차감 → fbot-state.py register."""
    con = connect()
    try:
        # ① 레지스트리 조회 — 중복 bot_id 거부 + role 카탈로그 검증
        dup = con.execute("SELECT bot_id FROM bot WHERE bot_id = ?", (args.bot_id,)).fetchone()
        if dup is not None:
            raise Reject(1, f"중복 bot_id: {args.bot_id} — 이미 레지스트리에 등록된 봇")
        catalog = load_catalog()
        if args.role not in catalog:
            raise Reject(1, f"미등재 role: {args.role!r} — 카탈로그 허용값 {', '.join(sorted(catalog))} (등록은 fbot-icon 스킬 ⑤단계 절차)")

        # ② policy 판정 — 값 로드 실패 시 fail-loud
        pol = load_policy()

        # ③ 예산 — 상한 도달 시 거부 (차감은 ④⑤ 통과 확정 후 원자적)
        month = month_key()
        budget_limit = pol["fbot_spawn_budget_monthly"]
        spent = budget_spent(con, month)
        if spent >= budget_limit:
            raise Reject(3, f"월 스폰 예산 소진 — {month} 사용 {spent}건 ≥ 상한 {budget_limit}건")

        # ④ 스폰 깊이 — parent_bot_id 체인 역추적 ≤ limit
        depth = judge_depth(con, args.parent, pol)

        # ⑤ 동시 상주 — state != checkout 봇 수 < limit
        actives = judge_concurrent(con, pol)

        # ── 전 판정 통과 → 예산 차감 (BEGIN IMMEDIATE 재검증 — 동시 hire 경쟁 대비) ──
        now = int(time.time())
        con.execute("BEGIN IMMEDIATE")
        try:
            spent = budget_spent(con, month)
            if spent >= budget_limit:
                raise Reject(3, f"월 스폰 예산 소진(차감 시점 재검증) — {month} 사용 {spent}건 ≥ 상한 {budget_limit}건")
            con.execute(
                "INSERT INTO kv (ns, key, value, expires_at, updated_at, updated_by)"
                " VALUES (?,?,?,NULL,?,'fbot-hr-gate')"
                " ON CONFLICT(ns, key) DO UPDATE SET"
                "   value = CAST(CAST(value AS INT) + 1 AS TEXT), updated_at = excluded.updated_at",
                (BUDGET_NS, month, "1", now),
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        spent_after = budget_spent(con, month)
    finally:
        con.close()

    # ── 채용 완료 = fbot-state.py register 호출 (등록 로직 중복 구현 금지) ──
    # 아이콘·개체색은 생성기에 물어본다. 계약은 "종류별 동형 도형 + **개체별** 색"이므로
    #   role 기본색은 생성기가 실패했을 때의 최후 폴백일 뿐이다.
    icon_rel, icon_color = ensure_bot_icon(args.bot_id, args.role)
    reg_cmd = [
        sys.executable, STATE_PY, "register",
        "--bot-id", args.bot_id, "--role", args.role, "--title", args.title,
        "--career", args.career,
        "--color", args.color or icon_color or load_catalog()[args.role],
    ]
    if args.parent:
        reg_cmd += ["--parent", args.parent]
    if args.prj is not None:
        reg_cmd += ["--prj", str(args.prj)]
    if args.icon or icon_rel:
        reg_cmd += ["--icon", args.icon or icon_rel]
    if getattr(args, "tmux_target", None):
        reg_cmd += ["--tmux-target", args.tmux_target]
    if getattr(args, "session_id", None):
        reg_cmd += ["--session-id", args.session_id]
    proc = subprocess.run(reg_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # register 실패 → 차감분 환불 후 fail-loud (예산 유령 차감 금지)
        con = connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "UPDATE kv SET value = CAST(MAX(CAST(value AS INT) - 1, 0) AS TEXT), updated_at = ?"
                " WHERE ns = ? AND key = ?",
                (int(time.time()), BUDGET_NS, month_key()),
            )
            con.execute("COMMIT")
        finally:
            con.close()
        raise FbotError(
            f"판정 5종 통과했으나 register 실패(예산 환불 완료): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    bot = json.loads(proc.stdout).get("bot", {})

    out = {
        "ok": True, "action": "hire", "verdict": "허가",
        "bot_id": args.bot_id, "role": args.role, "depth": depth,
        "active_before": actives,
        "budget": {"ns": BUDGET_NS, "month": month, "spent": spent_after, "limit": budget_limit},
        "bot": bot,
    }
    if not icon_rel:
        # 아이콘 생성 실패는 채용을 막지 않지만 조용히 넘기지도 않는다 — hub 카드가
        #   색 dot 으로만 뜨는 이유를 나중에 추적할 수 있어야 한다.
        out["warning"] = ("아이콘 생성 실패 — 개체 아이콘 없이 등록됨"
                          f" (생성기: {ICON_GEN}). hub 는 role 아이콘·색 dot 으로 폴백한다")
    emit(out)
    return 0


def move_career(bot_id: str, to: str, reason: str) -> None:
    """기록은 state.py 가 한다 — `hire`→`register` 와 동일한 판정/기록 분리.

    상비 role 보호·전이 규칙은 그쪽 계층이 소유하므로, 게이트가 판정을 통과시켜도
    기록 계층이 거부하면 그대로 실패한다(이중 방어).
    """
    r = subprocess.run(
        [sys.executable, STATE_PY, "career", "--bot-id", bot_id, "--to", to, "--reason", reason],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise Reject(2, f"career 전이 실패({bot_id} → {to}): {(r.stderr or r.stdout).strip()}")


def lifecycle_candidates(con, pol, now, mode):
    """수명주기 후보 스캔 — 상비봇과 이미 해고된 봇은 대상에서 뺀다.

    ⚠️ 상비 판정은 **role + parent 없음**이다. role 만 보면 `fbot-exec-issue331`
       (role=exec, parent=fbot-taskmgr) 같은 이슈 워커까지 영구 보호되어, 정작 정리
       대상인 워커가 상비봇 행세를 하며 남는다(2026-08-31 실측으로 좁힌 조건).
       최종 방어는 기록 계층(fbot-state.py `is_core_bot`)이 한 번 더 한다 — 여기는
       후보에서 빼는 것이고 거기는 전이 자체를 막는 것이라 역할이 다르다.
    """
    out = []
    for bot in con.execute("SELECT * FROM bot ORDER BY created_at").fetchall():
        if bot["role"] in CORE_ROLES and bot["parent_bot_id"] is None:
            continue  # 계약 §조직 — 상비봇 영구 제외
        if bot["career"] == "terminated":
            continue
        stats = bot_job_stats(con, bot["bot_id"])
        if mode == "promote":
            if bot["career"] != "probation":
                continue
            ok, why = judge_promote(stats, pol)
            if ok:
                out.append({"bot_id": bot["bot_id"], "title": bot["title"], "role": bot["role"],
                            "career": bot["career"], "stats": stats, "verdict": "승격 가능"})
            continue
        if mode == "archive":
            if bot["career"] == "leave":
                continue
            hit, why, days = judge_archive(bot, stats, pol, now)
            if hit:
                out.append({"bot_id": bot["bot_id"], "title": bot["title"], "role": bot["role"],
                            "career": bot["career"], "idle_days": days, "reason": why,
                            "stats": stats})
            continue
        if mode == "fire":
            # 해고 후보는 **휴직자 중에서만** 나온다 — 되돌릴 수 있는 단계를 반드시 거친다
            if bot["career"] != "leave":
                continue
            hit, why, days = judge_archive(bot, stats, pol, now)
            if hit:
                out.append({"bot_id": bot["bot_id"], "title": bot["title"], "role": bot["role"],
                            "career": bot["career"], "idle_days": days, "reason": why,
                            "stats": stats})
    return out


def cmd_wake(args) -> int:
    """`hire` 의 형제 (prj3#Issue498 ⓐ) — 있는 개체를 깨운다.

    hire=없는 개체를 만든다(카탈로그+예산+등록) / wake=있는 개체의 세션을 다시 띄운다.
    새 개체가 아니므로 예산 차감 없음 — 판정은 **동시 상주 상한 하나**다(폭주 가드는 유지).
    세션 기동 집행은 dispatch 와 같은 계약으로 **호출자(fpm-do/Agent) 몫** — 여기는 판정과
    복귀 기록까지. `checkout` 은 부재가 아니라 cold(대기)다 — 계약 §상태 기계 ⓓ.
    """
    pol = load_policy()
    con = connect()
    try:
        row = con.execute("SELECT * FROM bot WHERE bot_id = ?", (args.bot,)).fetchone()
        if row is None:
            raise Reject(1, f"미등록 봇: {args.bot} — 없는 개체는 wake 가 아니라 hire 다")
        if row["career"] == "terminated":
            raise Reject(1, f"해고된 봇: {args.bot} — 종결 상태는 깨우지 않는다(재채용은 hire)")
        if row["state"] != "checkout":
            raise Reject(1, f"이미 활동 중: {args.bot} (state={row['state']}) — wake 불요, SendMessage 로 직접")
        judge_concurrent(con, pol)   # ⑤ 동시 상주 상한 — hire 와 같은 판정 재사용
    finally:
        con.close()
    # career 휴직이면 복귀(계약 §career 전이: 재출근=자동 복귀·승인 불요) — 기록은 state.py 경유
    revived = False
    if row["career"] == "leave":
        r = subprocess.run([sys.executable, STATE_PY, "career", "--bot-id", args.bot,
                            "--to", "active", "--reason", "wake 재출근 자동 복귀 (Issue498)"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Reject(2, f"휴직 복귀 실패: {(r.stderr or r.stdout).strip()}")
        revived = True
    emit({"ok": True, "action": "wake", "verdict": "허가", "bot_id": args.bot,
          "career_revived": revived,
          "next": "세션 기동은 호출자 몫(fpm-do/Agent — dispatch 와 동일 계약). "
                  "기동되면 SessionStart 훅이 checkin 을 기록한다"})
    return 0


def cmd_promote(args) -> int:
    """승격 판정 — 기본은 후보 목록만. `--apply --bot-id` 가 사람 승인 1회를 대신한다."""
    pol = load_policy(LIFECYCLE_KEYS)
    now = int(time.time())
    con = connect()
    try:
        cands = lifecycle_candidates(con, pol, now, "promote")
    finally:
        con.close()
    if not args.apply:
        emit({"ok": True, "action": "promote", "mode": "판정만", "count": len(cands),
              "candidates": cands,
              "next": "집행은 --apply --bot-id ID (자동 승격 금지 — s2 확정 '사람 승인 1회')"})
        return 0
    if not args.bot_id:
        raise Reject(2, "--apply 는 --bot-id 를 함께 요구한다 — 일괄 승격은 승인 게이트를 무력화한다")
    if args.bot_id not in [c["bot_id"] for c in cands]:
        raise Reject(1, f"승격 요건 미충족·대상 아님: {args.bot_id}")
    move_career(args.bot_id, "active", args.reason or "승격 요건 충족(사람 승인)")
    emit({"ok": True, "action": "promote", "mode": "집행", "bot_id": args.bot_id})
    return 0


def cmd_archive(args) -> int:
    """유휴 개체 아카이브(휴직). 되돌리기가 값싸므로 `--apply` 는 일괄 집행을 허용한다."""
    pol = load_policy(LIFECYCLE_KEYS)
    now = int(time.time())
    con = connect()
    try:
        cands = lifecycle_candidates(con, pol, now, "archive")
    finally:
        con.close()
    if not args.apply:
        emit({"ok": True, "action": "archive", "mode": "dry-run", "count": len(cands),
              "candidates": cands, "next": "집행은 --apply (휴직은 복귀 1회로 되돌아온다)"})
        return 0
    moved = []
    for c in cands:
        if args.bot_id and c["bot_id"] != args.bot_id:
            continue
        move_career(c["bot_id"], "leave", c["reason"])
        moved.append(c["bot_id"])
    emit({"ok": True, "action": "archive", "mode": "집행", "count": len(moved), "moved": moved})
    return 0


def cmd_fire(args) -> int:
    """해고 — **제안이 기본**이고 집행은 개체 단위 명시 + 사유 필수.

    휴직자만 후보가 된다(§수명주기: leave → terminated 만 허용). 되돌릴 수 없는 전이라
    일괄 집행 경로를 두지 않는다 — 그것이 이 커맨드와 archive 의 유일한 설계 차이다.
    """
    pol = load_policy(LIFECYCLE_KEYS)
    now = int(time.time())
    con = connect()
    try:
        cands = lifecycle_candidates(con, pol, now, "fire")
    finally:
        con.close()
    if not args.apply:
        emit({"ok": True, "action": "fire", "mode": "제안", "count": len(cands),
              "candidates": cands,
              "next": "집행은 --apply --bot-id ID --reason '사유' (되돌릴 수 없다 — 사람 승인 필수)"})
        return 0
    if not args.bot_id or not args.reason:
        raise Reject(2, "--apply 는 --bot-id 와 --reason 을 함께 요구한다 (비가역 전이)")
    if args.bot_id not in [c["bot_id"] for c in cands]:
        raise Reject(1, f"해고 후보 아님: {args.bot_id} — 휴직 상태 + 유휴 임계 경과만 대상이다")
    move_career(args.bot_id, "terminated", args.reason)
    emit({"ok": True, "action": "fire", "mode": "집행", "bot_id": args.bot_id,
          "reason": args.reason, "note": "기록은 영속 — homunculus 학습 원천 유지(계약 §수명주기)"})
    return 0


def cmd_check(args) -> int:
    """일반 위임(비봇) 게이트 — 판정 ④ 깊이 + ⑤ 동시 상주만. 등록·차감 없음."""
    parent = None if args.parent == "-" else args.parent
    pol = load_policy()  # check 도 policy 로드 실패는 fail-loud (판정 ②와 동일 기준)
    con = connect()
    try:
        depth = judge_depth(con, parent, pol)
        # --depth: 레지스트리 밖 체인(fpm-do 일반 위임 PM_DO_DEPTH)의 깊이 신고값.
        # 레지스트리 역추적과 max 취합 — 어느 축이든 상한을 넘으면 거부 (판정 ④ 단일 지점).
        if args.depth is not None:
            limit = pol["fbot_spawn_depth_limit"]
            if args.depth > limit:
                raise Reject(4, f"스폰 깊이 초과 — 신고 깊이 {args.depth} > 상한 {limit} (fpm-do 체인)")
            depth = max(depth, args.depth)
        actives = judge_concurrent(con, pol)
    finally:
        con.close()
    emit({
        "ok": True, "action": "check", "verdict": "허가", "kind": args.kind,
        "parent": parent, "depth": depth, "depth_limit": pol["fbot_spawn_depth_limit"],
        "active": actives, "concurrent_limit": pol["fbot_concurrent_limit"],
    })
    return 0


def cmd_status(args) -> int:
    """이번 달 예산 소진·동시 상주 수·limit 출력."""
    pol = load_policy()
    month = month_key()
    con = connect()
    try:
        spent = budget_spent(con, month)
        actives = active_count(con)
    finally:
        con.close()
    emit({
        "ok": True, "action": "status", "month": month,
        "budget": {"ns": BUDGET_NS, "spent": spent, "limit": pol["fbot_spawn_budget_monthly"],
                   "remaining": max(pol["fbot_spawn_budget_monthly"] - spent, 0)},
        "concurrent": {"active": actives, "limit": pol["fbot_concurrent_limit"]},
        "depth_limit": pol["fbot_spawn_depth_limit"],
    })
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fbot-hr-gate.py",
        description="fbot 인사핀봇(HR) 게이트 (Issue436_3 s2) — 계약 fbot-arch.md §호출 경계(F3)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("hire", help="채용 — 판정 5종 통과 시 register 까지 수행")
    sp.add_argument("--bot-id", required=True)
    sp.add_argument("--role", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--parent", default=None, help="스폰 부모 bot_id(상비 봇·사람 기동은 생략)")
    sp.add_argument("--prj", type=int, default=None, help="주 담당 prj 번호(전역봇은 생략)")
    sp.add_argument("--career", default="probation", help="기본 probation (채용 = 수습 시작)")
    sp.add_argument("--icon", default=None)
    sp.add_argument("--color", default=None, help="생략 시 role 카탈로그 base 색")
    # Issue448 ② — 스폰 시점에 실행 형태를 알면 결속을 함께 기록한다.
    #   ⚠️ 모르면 넘기지 않는다(NULL). Agent 형태는 pane 이 없고, tmux 위임도 창을
    #   나중에 만들면 hire 시점엔 미상이다 — 그 경우 출근 훅이 채운다.
    sp.add_argument("--tmux-target", default=None, help="tmux 'session:window.pane' (모르면 생략)")
    sp.add_argument("--session-id", default=None, help="claude 세션 id (모르면 생략)")
    sp.set_defaults(func=cmd_hire)

    sp = sub.add_parser("check", help="일반 위임(비봇) — 깊이·동시 상주만, 등록·차감 없음")
    sp.add_argument("--parent", required=True, help="부모 bot_id, 루트(부모 없음)는 '-'")
    sp.add_argument("--kind", default="delegate")
    sp.add_argument("--depth", type=int, default=None, help="레지스트리 밖 체인 깊이 신고값(fpm-do PM_DO_DEPTH) — 역추적과 max 취합")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("wake", help="퇴근(cold) 봇 재기동 판정 — hire 의 형제, 상주 상한만 확인 (Issue498)")
    sp.add_argument("--bot", required=True)
    sp.set_defaults(func=cmd_wake)

    for name, helptext, fn in (
        ("promote", "승격 판정 — 기본 후보 목록, --apply --bot-id 로 집행(사람 승인 1회)", cmd_promote),
        ("archive", "유휴 개체 아카이브(휴직) — 기본 dry-run, --apply 로 집행", cmd_archive),
        ("fire", "해고 제안 — 휴직자만 후보. --apply 는 --bot-id+--reason 필수(비가역)", cmd_fire),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--apply", action="store_true", help="판정만 하지 않고 집행")
        sp.add_argument("--bot-id", default=None)
        sp.add_argument("--reason", default=None, help="전이 사유(감사 기록용)")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("status", help="이번 달 예산 소진·동시 상주·limit")
    sp.set_defaults(func=cmd_status)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Reject as e:
        print(str(e), file=sys.stderr)
        return 1
    except FbotError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    except sqlite3.Error as e:
        print(f"❌ DB 오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
