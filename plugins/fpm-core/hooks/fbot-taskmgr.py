#!/usr/bin/env python3
"""fbot 작업핀봇(taskmgr) 판정 코어 (Issue436_3 s3 — 단계 3·4·5·6).

계약: ~/.claude/_doc_arch/fbot-arch.md §조직(작업핀봇 임무·수요측 가드) ·
      §워크플로우 어댑터(nPTiR/칸반 — 코어 중립) · §호출 경계(스폰=HR 게이트 경유,
      `[컨펌]` 응답 승인은 사람 전용) · §작업 기록(F4 — 봇 전용 작업 대장 금지).
      어댑터 설정 위치는 s3 확정(2026-08-24): 프로젝트 `.claude/fbot.yml`
      `workflow: nptir|kanban` (파일·키 부재 = nptir). 계약 참조만 하며 재결정하지 않는다.

CLI
    pending  [--cwd DIR]
        issue-map `--json` 소비 → 펜딩 큐 뷰(startable/blocked 분류) 출력.
        펜딩 큐 = Issue.md·issue-map 의 **파생 뷰**다 — 별도 작업 대장 파일을 만들지
        않는다(F4). `--json` 부재·실패 시 fail-loud(빈 목록으로 오독 금지).
        칸반 어댑터면 pull 안내 + WIP 잔여(= 수요측 동시 상한 그대로)를 함께 표시 —
        판정 코어는 어댑터 중립, 표시만 갈린다.
    dispatch --issue ID --role ROLE [--cwd DIR] [--bot-id ID] [--dry-run]
        배분 **요청**: ① 수요측 가드 판정(월 배분 상한·동시 배분 상한 — 단일 지점)
        ② 통과 시 HR 게이트 `hire` 호출로 워커 봇 채용까지(스폰 집행은 fpm-do/Agent
        몫 — 여기서는 채용+배분 기록. 게이트 없는 스폰 경로 금지)
        ③ bot_id=fbot-taskmgr 귀속으로 registry.job 에 배분 기록(kind=fbot_dispatch).
        착수 가능 판정은 pending(issue-map) 소관 — 여기서 재판정하지 않는다.
    watch    [--cwd DIR]
        진행 감시: 배분 기록 vs bot.state·lease_expires 대조 → 적체 2종 판정
        (A: 미배분 startable 적체 — --cwd 지정 시만, issue-map 필요 /
         B: 배분 후 진행 신호 없음 — bot 부재·퇴근·lease 만료)
        → 재시도 카운트(상한 RETRY_LIMIT — opus 룰 §2) → 초과 시 에스컬레이션:
        aoa-mq enqueue helper `--alert` 호출(직접 큐 파일 Write 금지).
    status
        이번 달 배분 수·상한·활성 배분 목록.

설계 원칙 (fbot-state.py·fbot-hr-gate.py 승계)
* 표준 라이브러리만 사용(무의존). policy.yml·fbot.yml 은 평탄 키라 정규식으로 읽는다.
* fail-loud: issue-map 부재·policy 키 부재·미정의 어댑터 값 전부 명시 에러 + exit != 0.
* 상한 수치는 aoa policy.yml `fbot_dispatch_*` 2키가 SSOT — 하드코딩 금지.
* 배분 원장: registry.kv ns=`fbot:dispatch` key=YYYY-MM — HR 예산 원장(ns=fbot:budget)과
  같은 패턴. 신규 월 키 생성이 곧 리셋(리셋 잡 없음). 증분은 BEGIN IMMEDIATE 재검증.
* ⚠️ mq `[컨펌]` 응답 승인 호출 절대 금지 — 봇은 enqueue·리마인드·snooze **제안까지만**
  (`[컨펌]` 처리는 사람 전용 — 계약 §호출 경계). 본 코드에 해당 호출 경로가 없다.
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
import uuid

DEFAULT_AOA_DIR = os.path.join(os.path.expanduser("~"), "_git", "___common", "data", "aoa")

# issue-map 이미터 (s3 확장 ① — 파서 재사용, htm 스크레이핑 금지)
ISSUE_MAP_PY = os.path.join(
    os.path.expanduser("~"), ".claude", "skills", "issue-map", "build_issue_map.py"
)

# HR 게이트 (스폰 판정 단일 SSOT — 판정 로직 중복 구현 금지)
TASKMGR_ID = "fbot-taskmgr"
HR_GATE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-hr-gate.py")

# aoa-mq 등록 helper (직접 큐 파일 Write 금지 — helper 경유만)
MQ_ENQUEUE_SH = os.path.join(
    os.path.expanduser("~"), "_git", "___common", ".claude", "agents", "aoa-mq-enqueue.sh"
)

BOT_ID = "fbot-taskmgr"  # 기록 귀속 주체 (F4 — 전역 1개, 계약 §조직 개체 스코프)

# policy.yml 필수 키 2종 (s3 편입분 — 수요측 가드) — 로드 실패 시 fail-loud
POLICY_KEYS = ("fbot_dispatch_monthly_limit", "fbot_dispatch_concurrent_limit")

DISPATCH_NS = "fbot:dispatch"  # registry.kv 배분 원장 네임스페이스 (HR ns=fbot:budget 과 분리)
JOB_KIND = "fbot_dispatch"     # registry.job 배분 기록 kind

# 재시도 상한 — opus-4-8-execution-rules §2 (2회 연속 실패 시 보고·대기). 정책 수치가
# 아니라 실행 규칙 상수라 policy.yml 에 넣지 않는다.
RETRY_LIMIT = 2

# 워크플로우 어댑터 허용값 (계약 §워크플로우 어댑터 — 표준 2종)
ADAPTERS = ("nptir", "kanban")

CIRCLED = {1: "①", 2: "②"}


class FbotError(Exception):
    """fail-loud 용 — 인프라·입력 오류. stderr + exit 2."""


class Reject(Exception):
    """수요측 가드 거부 — 판정 번호 + 사유. exit 1."""

    def __init__(self, n: int, reason: str):
        self.n = n
        self.reason = reason
        super().__init__(f"수요측 판정 {CIRCLED[n]} 거부: {reason}")


# ── 경로·정책·어댑터 ────────────────────────────────────────────────────────

def aoa_dir() -> str:
    return os.environ.get("AOA_MEMORY_DIR") or DEFAULT_AOA_DIR


def registry_path() -> str:
    p = os.path.join(aoa_dir(), "registry.db")
    if not os.path.exists(p):
        raise FbotError(f"레지스트리 DB 없음: {p} (AOA_MEMORY_DIR 확인)")
    return p


def load_policy() -> dict:
    """aoa policy.yml 의 fbot_dispatch_* 2키 로드. 파일·키 부재 = fail-loud (기본값 폴백 금지)."""
    path = os.path.join(aoa_dir(), "policy.yml")
    if not os.path.exists(path):
        raise FbotError(f"policy 로드 실패 — 파일 없음: {path}")
    pol = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^(fbot_[a-z_]+):\s*(\d+)", line)
            if m:
                pol[m.group(1)] = int(m.group(2))
    missing = [k for k in POLICY_KEYS if k not in pol]
    if missing:
        raise FbotError(f"policy 로드 실패 — {path} 에 키 부재: {', '.join(missing)}")
    bad = [k for k in POLICY_KEYS if pol[k] <= 0]
    if bad:
        raise FbotError(f"policy 값 불량(양수 아님): {', '.join(f'{k}={pol[k]}' for k in bad)}")
    return pol


def load_workflow(cwd: str) -> str:
    """프로젝트 `.claude/fbot.yml` 의 `workflow:` 키 (s3 확정 — per-prj 선택값).

    파일·키 부재 = 기본 nptir. 미정의 값은 fail-loud — 어댑터 오독으로 흐름이
    갈라지는 것을 막는다(silent 기본값 강등 금지).
    """
    path = os.path.join(cwd, ".claude", "fbot.yml")
    if not os.path.exists(path):
        return "nptir"
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^workflow:\s*(\S+)", line)
            if m:
                val = m.group(1)
                if val not in ADAPTERS:
                    raise FbotError(
                        f"미정의 워크플로우 어댑터: {val!r} ({path}) — 허용값 {', '.join(ADAPTERS)}"
                    )
                return val
    return "nptir"


# ── issue-map 소비 (판정 재료 — 재판정 금지) ────────────────────────────────

def load_issue_map(cwd: str) -> dict:
    """issue-map `--json` 실행·파싱. 부재·실패는 전부 fail-loud — 빈 목록으로 오독 금지.

    판정(startable/blocked_by)은 issue-map 소유다 — 여기서는 소비만 한다.
    """
    if not os.path.exists(ISSUE_MAP_PY):
        raise FbotError(f"issue-map 스크립트 없음: {ISSUE_MAP_PY}")
    proc = subprocess.run(
        [sys.executable, ISSUE_MAP_PY, "--json"],
        cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FbotError(
            f"issue-map --json 실패(exit {proc.returncode}) — 판정불가, 빈 큐로 오독 금지: "
            f"{(proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout).strip() else '출력 없음'}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise FbotError(f"issue-map --json 출력 파싱 실패 — 판정불가: {e}")
    for key in ("root", "issues"):
        if key not in data:
            raise FbotError(f"issue-map --json 스키마 위반 — {key!r} 필드 부재")
    return data


TERMINAL_RE = re.compile(r"완료|취소")  # 종결 섹션은 펜딩 뷰에서 제외 (뷰 필터일 뿐 판정 아님)


def classify(issues: list) -> tuple[list, list]:
    """펜딩 이슈를 startable/blocked 로 분류 — issue-map 의 startable 판정을 그대로 쓴다."""
    startable, blocked = [], []
    for it in issues:
        if TERMINAL_RE.search(str(it.get("section", ""))) or TERMINAL_RE.search(str(it.get("state", ""))):
            continue
        (startable if it.get("startable") else blocked).append(it)
    return startable, blocked


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


def dispatched_this_month(con: sqlite3.Connection, month: str) -> int:
    row = con.execute(
        "SELECT value FROM kv WHERE ns = ? AND key = ?", (DISPATCH_NS, month)
    ).fetchone()
    return int(row["value"]) if row is not None else 0


def active_dispatches(con: sqlite3.Connection) -> list:
    """미종결 fbot_dispatch job 전체 (open=진행, blocked=에스컬레이션 후 사람 ACK 대기).

    ⚠️ 동시 상한(WIP) 판정은 호출측이 `status=="open"` 만 필터한다 — blocked 는
    사람 판단 대기라 WIP 슬롯을 점유하지 않는 것이 의도(s3 QA 발견 ② 명문화).
    """
    rows = con.execute(
        "SELECT * FROM job WHERE kind = ? AND status IN ('open','blocked') ORDER BY created_at",
        (JOB_KIND,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        except json.JSONDecodeError:
            d["payload"] = {"raw": d["payload"]}
        out.append(d)
    return out


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── 수요측 가드 (판정 단일 지점 — dispatch·dry-run 공용) ────────────────────

def judge_demand_guard(con, pol) -> dict:
    """수요측 폭주 가드 2종. HR 공급측 가드(세션 수)와 2중 차단 — 계약 §조직.

    ① 월 배분 상한 — 원장 registry.kv ns=fbot:dispatch key=YYYY-MM
    ② 동시 배분 상한 — 활성(open) fbot_dispatch job 수
    """
    month = month_key()
    m_limit = pol["fbot_dispatch_monthly_limit"]
    spent = dispatched_this_month(con, month)
    if spent >= m_limit:
        raise Reject(1, f"월 배분 상한 도달 — {month} 배분 {spent}건 ≥ 상한 {m_limit}건")
    c_limit = pol["fbot_dispatch_concurrent_limit"]
    active = [j for j in active_dispatches(con) if j["status"] == "open"]
    if len(active) >= c_limit:
        raise Reject(2, f"동시 배분 상한 도달 — 활성 배분 {len(active)}건 ≥ 상한 {c_limit}건")
    return {"month": month, "spent": spent, "monthly_limit": m_limit,
            "active": len(active), "concurrent_limit": c_limit}


# ── 에스컬레이션 (mq enqueue helper 경유 — 제안까지만, 사람 응답 대기) ──────

def escalate(message: str) -> str:
    """aoa-mq 에 alert 등록. 직접 큐 파일 Write 금지 — helper 경유만.

    여기서 끝이다 — 등록된 건의 후속 처리(`[컨펌]` 포함)는 사람 몫이다.
    """
    if not os.path.exists(MQ_ENQUEUE_SH):
        raise FbotError(f"aoa-mq enqueue helper 없음: {MQ_ENQUEUE_SH}")
    proc = subprocess.run(
        # from_bot 전용 필드 사용 (s4 표준 — source 는 helper 기본값 유지, 봇 귀속은 from_bot)
        [MQ_ENQUEUE_SH, "--message", message, "--alert", "--source", BOT_ID, "--from-bot", BOT_ID],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FbotError(
            f"에스컬레이션 enqueue 실패(exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc.stdout.strip()


# ── 서브커맨드 ──────────────────────────────────────────────────────────────

def cmd_pending(args) -> int:
    """펜딩 큐 뷰 — Issue.md·issue-map 파생 뷰(F4: 별도 작업 대장 파일 생성 금지)."""
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    if not os.path.isdir(cwd):
        raise FbotError(f"디렉토리 아님: {cwd}")
    workflow = load_workflow(cwd)
    data = load_issue_map(cwd)
    startable, blocked = classify(data["issues"])

    print(f"# 펜딩 큐 — {data['root']} (어댑터: {workflow} · 생성: {data.get('generated', '?')})")
    if workflow == "kanban":
        pol = load_policy()
        con = connect()
        try:
            active = [j for j in active_dispatches(con) if j["status"] == "open"]
        finally:
            con.close()
        wip_limit = pol["fbot_dispatch_concurrent_limit"]  # WIP 제한 = 수요측 상한 그대로 (계약)
        print(f"  [kanban·pull] 워커가 아래 착수 가능 목록에서 스스로 인출한다 — "
              f"WIP 잔여 {max(wip_limit - len(active), 0)}/{wip_limit} (활성 배분 {len(active)}건)")
    print(f"\n## 착수 가능 (startable) — {len(startable)}건")
    for it in startable:
        print(f"  * {it['id']}: {it.get('title', '')} [{it.get('section', '?')}]")
    if not startable:
        print("  (없음)")
    print(f"\n## 차단 (blocked) — {len(blocked)}건")
    for it in blocked:
        by = ", ".join(it.get("blocked_by") or []) or "사유 미상"
        print(f"  * {it['id']}: {it.get('title', '')} [{it.get('section', '?')}] ← 차단: {by}")
    if not blocked:
        print("  (없음)")
    return 0


def cmd_dispatch(args) -> int:
    """배분 요청 — ① 수요측 가드 ② HR 게이트 hire(채용) ③ 배분 기록(F4).

    스폰 **집행**은 fpm-do/Agent 몫이다 — 여기서는 채용과 기록까지만.
    착수 가능 판정은 pending(issue-map)이 재료다 — 배분 요청은 그 판정을 재현하지 않는다.
    """
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    workflow = load_workflow(cwd)
    pol = load_policy()
    con = connect()
    try:
        guard = judge_demand_guard(con, pol)  # ① 통과 못 하면 Reject → exit 1
    finally:
        con.close()

    if args.dry_run:
        emit({"ok": True, "action": "dispatch", "mode": "dry-run", "verdict": "허가",
              "issue": args.issue, "role": args.role, "workflow": workflow, "guard": guard})
        return 0

    # ② HR 게이트 경유 채용 — 게이트 없는 스폰 경로 금지 (계약 §호출 경계)
    bot_id = args.bot_id or "fbot-{}-{}".format(
        args.role, re.sub(r"[^a-z0-9-]", "", args.issue.lower()) or uuid.uuid4().hex[:6]
    )
    hire = subprocess.run(
        [sys.executable, HR_GATE_PY, "hire",
         "--bot-id", bot_id, "--role", args.role,
         "--title", f"{args.issue} 담당 {args.role} 워커",
         # 체인 기록 필수 — parent 는 깊이 판정(④)의 데이터 원천 (계약 F1 parent_bot_id)
         "--parent", TASKMGR_ID],
        capture_output=True, text=True,
    )
    if hire.returncode != 0:
        raise FbotError(
            f"HR 게이트 채용 거부·실패(exit {hire.returncode}) — 배분 중단: "
            f"{(hire.stderr or hire.stdout).strip()}"
        )

    # ③ 배분 기록 — bot_id=fbot-taskmgr 귀속(F4) + 원장 증분(BEGIN IMMEDIATE 재검증)
    now = int(time.time())
    job_id = f"fbotdisp-{now}-{uuid.uuid4().hex[:8]}"
    payload = {"issue": args.issue, "role": args.role, "worker_bot_id": bot_id,
               "cwd": cwd, "workflow": workflow}
    con = connect()
    try:
        # 명시 롤백 없이 구성한다 — 상한 재검증 실패는 쓰기 전에 빈 COMMIT 으로 빠지고,
        # 쓰기 도중 예외는 close 시 미커밋 트랜잭션이 자동 폐기된다(원자성 유지).
        con.execute("BEGIN IMMEDIATE")
        month = month_key()
        spent = dispatched_this_month(con, month)
        if spent >= pol["fbot_dispatch_monthly_limit"]:
            con.execute("COMMIT")  # 아직 아무것도 안 썼다 — 빈 커밋으로 락만 해제
            raise Reject(1, f"월 배분 상한 도달(기록 시점 재검증) — {month} {spent}건")
        con.execute(
            "INSERT INTO kv (ns, key, value, expires_at, updated_at, updated_by)"
            " VALUES (?,?,?,NULL,?,?)"
            " ON CONFLICT(ns, key) DO UPDATE SET"
            "   value = CAST(CAST(value AS INT) + 1 AS TEXT), updated_at = excluded.updated_at",
            (DISPATCH_NS, month, "1", now, BOT_ID),
        )
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (job_id, "fbot", JOB_KIND, "open", json.dumps(payload, ensure_ascii=False),
             BOT_ID, now),
        )
        con.execute("COMMIT")
        spent_after = dispatched_this_month(con, month)
    finally:
        con.close()

    emit({
        "ok": True, "action": "dispatch", "verdict": "허가",
        "issue": args.issue, "role": args.role, "worker_bot_id": bot_id,
        "job_id": job_id, "workflow": workflow,
        "ledger": {"ns": DISPATCH_NS, "month": month, "spent": spent_after,
                   "limit": pol["fbot_dispatch_monthly_limit"]},
        "next": "스폰 집행은 fpm-do/Agent 몫 — 본 기록은 채용+배분까지 (계약 §호출 경계)",
    })
    return 0


def cmd_watch(args) -> int:
    """진행 감시 — 적체 2종 판정 → 재시도 카운트(상한 RETRY_LIMIT) → 초과 시 에스컬레이션."""
    pol = load_policy()
    now = int(time.time())
    stalls, retried, escalated = [], [], []

    con = connect()
    try:
        # ── 적체 B: 배분 후 진행 신호 없음 (bot 부재·퇴근·lease 만료) ──
        for job in [j for j in active_dispatches(con) if j["status"] == "open"]:
            wid = job["payload"].get("worker_bot_id")
            bot = con.execute("SELECT * FROM bot WHERE bot_id = ?", (wid,)).fetchone() if wid else None
            if bot is None:
                reason = f"워커 봇 레코드 부재: {wid}"
            elif bot["state"] == "checkout":
                reason = f"워커 봇 퇴근 상태(작업 미완): {wid}"
            elif bot["lease_expires"] is not None and bot["lease_expires"] < now:
                reason = f"워커 봇 lease 만료({now - bot['lease_expires']}초 경과): {wid}"
            else:
                continue  # 진행 신호 정상
            attempts = (job["attempts"] or 0) + 1
            if attempts > RETRY_LIMIT:
                # 재시도 상한 초과 → 에스컬레이션(1회) + blocked 전환(반복 alert 방지)
                msg = (f"[fbot-taskmgr] 배분 적체 에스컬레이션 — job {job['id']} "
                       f"(이슈 {job['payload'].get('issue', '?')}): {reason}. "
                       f"재시도 {RETRY_LIMIT}회 초과 — 사람 판단 필요")
                enq = escalate(msg)
                con.execute(
                    "UPDATE job SET status = 'blocked', blocked_since = ?, attempts = ? WHERE id = ?",
                    (now, attempts, job["id"]),
                )
                escalated.append({"job_id": job["id"], "reason": reason, "enqueued": enq})
            else:
                con.execute("UPDATE job SET attempts = ? WHERE id = ?", (attempts, job["id"]))
                retried.append({"job_id": job["id"], "reason": reason,
                                "attempts": attempts, "limit": RETRY_LIMIT})
            stalls.append({"kind": "no_progress", "job_id": job["id"], "reason": reason})

        # ── 적체 A: 미배분 startable 적체 (--cwd 지정 시만 — issue-map 필요) ──
        idle_pending = None
        if args.cwd is not None:
            cwd = os.path.abspath(os.path.expanduser(args.cwd))
            data = load_issue_map(cwd)  # 부재·실패 시 fail-loud
            startable, _ = classify(data["issues"])
            dispatched_ids = {j["payload"].get("issue")
                              for j in active_dispatches(con)}
            idle_pending = []
            for it in startable:
                if it["id"] in dispatched_ids:
                    con.execute("DELETE FROM kv WHERE ns = ? AND key = ?",
                                (DISPATCH_NS, f"idle:{data['root']}:{it['id']}"))
                    continue
                key = f"idle:{data['root']}:{it['id']}"
                row = con.execute("SELECT value FROM kv WHERE ns = ? AND key = ?",
                                  (DISPATCH_NS, key)).fetchone()
                seen = (int(row["value"]) if row else 0) + 1
                con.execute(
                    "INSERT INTO kv (ns, key, value, expires_at, updated_at, updated_by)"
                    " VALUES (?,?,?,NULL,?,?)"
                    " ON CONFLICT(ns, key) DO UPDATE SET value = excluded.value,"
                    " updated_at = excluded.updated_at",
                    (DISPATCH_NS, key, str(seen), now, BOT_ID),
                )
                item = {"issue": it["id"], "watch_count": seen, "limit": RETRY_LIMIT}
                if seen == RETRY_LIMIT + 1:  # 상한 초과 첫 관측에서만 1회 alert
                    msg = (f"[fbot-taskmgr] 미배분 적체 에스컬레이션 — {data['root']} "
                           f"이슈 {it['id']} 이(가) 착수 가능 상태로 감시 {seen}회 연속 미배분. "
                           f"배분 또는 보류 판단 필요")
                    item["enqueued"] = escalate(msg)
                    escalated.append({"issue": it["id"], "reason": "미배분 적체",
                                      "enqueued": item["enqueued"]})
                idle_pending.append(item)
                stalls.append({"kind": "undispatched", "issue": it["id"], "seen": seen})
        else:
            idle_note = "미배분 적체 판정 생략 — --cwd 미지정(issue-map 대상 프로젝트 없음)"
    finally:
        con.close()

    out = {"ok": True, "action": "watch", "now": now,
           "stall_count": len(stalls), "stalls": stalls,
           "retried": retried, "escalated": escalated}
    if args.cwd is not None:
        out["undispatched_startable"] = idle_pending
    else:
        out["note"] = idle_note
    emit(out)
    return 0


def cmd_status(args) -> int:
    """이번 달 배분 수·상한·활성 배분 목록."""
    pol = load_policy()
    month = month_key()
    con = connect()
    try:
        spent = dispatched_this_month(con, month)
        actives = active_dispatches(con)
    finally:
        con.close()
    emit({
        "ok": True, "action": "status", "month": month,
        "dispatch": {"ns": DISPATCH_NS, "spent": spent,
                     "limit": pol["fbot_dispatch_monthly_limit"],
                     "remaining": max(pol["fbot_dispatch_monthly_limit"] - spent, 0)},
        "concurrent": {"active": len([j for j in actives if j["status"] == "open"]),
                       "limit": pol["fbot_dispatch_concurrent_limit"]},
        "active_dispatches": [
            {"job_id": j["id"], "status": j["status"], "attempts": j["attempts"],
             "issue": j["payload"].get("issue"), "role": j["payload"].get("role"),
             "worker_bot_id": j["payload"].get("worker_bot_id"),
             "created_at": j["created_at"], "blocked_since": j["blocked_since"]}
            for j in actives
        ],
    })
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fbot-taskmgr.py",
        description="fbot 작업핀봇 판정 코어 (Issue436_3 s3) — 계약 fbot-arch.md §조직·§워크플로우 어댑터",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pending", help="펜딩 큐 뷰 — issue-map --json 파생(startable/blocked)")
    sp.add_argument("--cwd", default=os.getcwd(), help="대상 프로젝트 루트(기본 현재 디렉토리)")
    sp.set_defaults(func=cmd_pending)

    sp = sub.add_parser("dispatch", help="배분 요청 — 수요측 가드 → HR hire → 배분 기록")
    sp.add_argument("--issue", required=True, help="이슈 ID (ex: Issue12)")
    sp.add_argument("--role", required=True, help="워커 role (카탈로그 등재값 — HR 게이트가 검증)")
    sp.add_argument("--cwd", default=os.getcwd(), help="대상 프로젝트 루트(기본 현재 디렉토리)")
    sp.add_argument("--bot-id", default=None, help="워커 bot_id 지정(생략 시 fbot-{role}-{issue} 자동)")
    sp.add_argument("--dry-run", action="store_true", help="가드 판정까지만 — 채용·기록 없음")
    sp.set_defaults(func=cmd_dispatch)

    sp = sub.add_parser("watch", help="진행 감시 — 적체 2종 → 재시도 → 에스컬레이션(mq alert)")
    sp.add_argument("--cwd", default=None, help="지정 시 미배분 startable 적체(A)도 판정")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("status", help="이번 달 배분 수·상한·활성 배분 목록")
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
