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
        진입 시 `sweep`(완료 감지)을 **선행**한다.
    sweep    [--dry-run]
        완료 감지(Issue438 ④): 배분 워커가 `checkout` + 그 봇의 `fbot_session` job 이
        done(배분 생성 이후) 이면 배분 완료 → job status=done 갱신 + **묶음 1회** 통지
        (aoa-mq `--alert --from-bot fbot-taskmgr`). watch 는 이 스윕을 **선행** 실행한다 —
        완료한 워커도 퇴근 상태라 순서를 바꾸면 정상 완료가 거짓 에스컬레이션이 된다.
    status
        이번 달 배분 수·상한·활성 배분 목록 + **취소 집계**(이번 달 건수·최근 5건
        사유). 취소는 `done` 과 합산하지 않는다 — 성과가 아니다(Issue446).

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

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
DEFAULT_AOA_DIR = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa")

# issue-map 이미터 (s3 확장 ① — 파서 재사용, htm 스크레이핑 금지)
ISSUE_MAP_PY = os.path.join(
    os.path.expanduser("~"), ".claude", "skills", "issue-map", "build_issue_map.py"
)

# prj 해소 resolver (prj3#Issue479) — 계약 §기존 규약 접점 "projects map".
#   ⚠️ 파일 값 = projects 디렉토리 **절대경로 그 자체**다. 추가 `/projects` join 금지
#      (fpm MCP `_base_dir()` 와 동일 구현 — 개인 경로 하드코딩 폴백도 금지).
PM_BASE_FILE = os.path.join(os.path.expanduser("~"), ".info", "__pmBasePath.txt")

# HR 게이트 (스폰 판정 단일 SSOT — 판정 로직 중복 구현 금지)
TASKMGR_ID = "fbot-taskmgr"
HR_GATE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-hr-gate.py")

# aoa-mq 등록 helper (직접 큐 파일 Write 금지 — helper 경유만)
MQ_ENQUEUE_SH = os.path.join(
    os.path.expanduser("~"), ".claude", "mcp", "aoa-mq", "aoa-mq-enqueue.sh"
)

BOT_ID = "fbot-taskmgr"  # 기록 귀속 주체 (F4 — 전역 1개, 계약 §조직 개체 스코프)

# policy.yml 필수 키 2종 (s3 편입분 — 수요측 가드) — 로드 실패 시 fail-loud
POLICY_KEYS = ("fbot_dispatch_monthly_limit", "fbot_dispatch_concurrent_limit")

DISPATCH_NS = "fbot:dispatch"  # registry.kv 배분 원장 네임스페이스 (HR ns=fbot:budget 과 분리)
JOB_KIND = "fbot_dispatch"     # registry.job 배분 기록 kind
SESSION_JOB_KIND = "fbot_session"  # 퇴근 훅(fbot-checkout.sh)이 남기는 세션 기록 kind
# 통지 워터마크 — 배분에 매이지 않은 봇 세션 완료를 어디까지 알렸는지(Issue438 ④ 명세 정합).
#   배분 완료는 job status 전이가 곧 중복 방지지만, 세션 완료는 그 보장이 없어 워터마크가 필요하다.
NOTIFY_NS = "fbot:notify"
NOTIFY_SESSION_KEY = "session_watermark"

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


def pm_projects_dir():
    """projects/ 디렉토리 절대경로. 부재·빈 값은 None (fpm MCP `_base_dir()` 동형)."""
    if not os.path.isfile(PM_BASE_FILE):
        return None
    with open(PM_BASE_FILE, encoding="utf-8") as fh:
        raw = fh.read().strip()
    return os.path.expanduser(os.path.expandvars(raw)) if raw else None


def resolve_prj(cwd: str, base=None):
    """cwd → 등록 prj 번호. **최장 prefix 일치**(hub `_resolve_project_root` 와 동일 정책).

    왜 fail-loud 가 아닌가 — `prj` 는 주 담당을 가리키는 **메타 필드**이고, 미등록 경로에서의
    배분은 정당하다(s3 실증이 `/tmp/fbot-s3/demo-prj` 에서 돈다). 해소 실패로 배분 자체를
    막으면 가용성 손실이 더 크다. 대신 **조용히 넘어가지 않는다** — resolver 부재는 stderr
    경고를 낸다(설정 사고와 정상적인 미등록을 구분하기 위함).

    ⚠️ **한계**: `bot.prj` 가 INT 라 `42a` 같은 **비숫자 prj 는 담을 수 없다.** 그런 경로는
       상위 숫자 프로젝트로 귀속된다(실측: `42a`=Projects_deck 은 `42`=m2slide 의 하위라
       42 로 잡힌다). 정확한 귀속이 필요해지면 스키마 축 확장이 선행 조건이다.
    """
    if base is None:
        base = pm_projects_dir()
    if not base or not os.path.isdir(base):
        print(f"[fbot-taskmgr] ⚠️ prj resolver 없음({PM_BASE_FILE}) — prj 미기록으로 진행",
              file=sys.stderr)
        return None

    target = os.path.realpath(os.path.expanduser(cwd))
    best_num, best_len = None, -1
    for name in os.listdir(base):
        if not name.isdigit():
            continue  # `42a`·README 등 — INT 컬럼에 못 담는다(위 한계 주석)
        entry = os.path.join(base, name)
        if not os.path.isfile(entry):
            continue
        with open(entry, encoding="utf-8") as fh:
            raw = fh.read().strip()
        if not raw:
            continue
        root = os.path.realpath(os.path.expanduser(raw))
        # 경계 검사 — 순수 문자열 prefix 로 보면 `…/m2slide-other` 가 `…/m2slide` 에 걸린다
        if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
            if len(root) > best_len:
                best_num, best_len = int(name), len(root)
    return best_num


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


def cancelled_dispatches(con: sqlite3.Connection) -> list:
    """취소(cancelled) 배분 전체 — 종결분이라 `active_dispatches` 가 보지 않는 축이다.

    왜 별도 함수인가 (Issue446) — `cancel` 경로 신설로 `cancelled` 상태가 생겼으나 관측이
    따라오지 않아 원장에만 존재하고 어느 뷰에도 안 나왔다. ⚠️ **`done` 과 합산 금지** —
    분리한 이유가 "취소를 성과로 집계하지 않는 것" 이다(cmd_cancel 주석 참조).

    시각 키가 2종인 것은 이력 때문이다: `cancel` 명령이 쓰는 `cancelled_at` 과, 명령
    신설 이전에 중역핀봇이 직접 UPDATE 로 화해한 건의 `swept_at`. 둘 다 없으면 생성
    시각으로 떨어진다 — 시각 부재를 "취소 없음" 으로 읽지 않기 위한 폴백이다.
    주체 키도 같은 이유로 `cancelled_by`/`detected_by` 2종을 본다.
    """
    rows = con.execute(
        "SELECT * FROM job WHERE kind = ? AND status = 'cancelled' ORDER BY created_at",
        (JOB_KIND,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("payload", "result"):
            try:
                d[k] = json.loads(d[k]) if d[k] else {}
            except json.JSONDecodeError:
                d[k] = {"raw": d[k]}
        res = d["result"]
        d["cancelled_at"] = res.get("cancelled_at") or res.get("swept_at") or d["created_at"]
        d["cancelled_by"] = res.get("cancelled_by") or res.get("detected_by") or "unknown"
        out.append(d)
    out.sort(key=lambda d: d["cancelled_at"])
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


# ── mq alert 발신 (helper 경유 — 제안까지만, 사람 응답 대기) ────────────────

def mq_alert(message: str) -> str:
    """aoa-mq 에 alert 등록. 직접 큐 파일 Write 금지 — helper 경유만.

    에스컬레이션(watch)과 완료 통지(sweep)의 **공용 발신구**다. 여기서 끝이다 —
    등록된 건의 후속 처리(`[컨펌]` ACK 포함)는 사람 몫이다(계약 §호출 경계).
    ⚠️ 호출측은 **건당 1회가 아니라 묶음 1회**로 부른다 (Issue399 규약: 통지 1회·묶음).
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


# ── 완료 감지·통지 (Issue438 ④ — 상태 전이 시점 통지) ──────────────────────

def detect_completions(con: sqlite3.Connection) -> list:
    """미종결 배분 중 **완료된 것**을 골라낸다.

    판정(계약 Issue438 ④): 배분의 워커 봇이 `checkout` 이고, 그 봇 귀속
    `fbot_session` job(status=done — 퇴근 훅이 남긴다)이 **배분 생성 이후**에
    존재하면 배분 완료다.

    ⚠️ `created_at >= 배분 시각` 조건이 핵심이다 — 같은 bot_id 로 재배분한 경우
    직전 배분의 낡은 세션 기록이 새 배분을 완료로 오판하는 것을 막는다.
    ⚠️ reap(lease 만료 강제 퇴근)은 세션 기록을 남기지 않는다 — 즉 **퇴근 상태만으로는
    완료가 아니다**. 그 경우는 watch 의 적체 B 판정으로 남는다(오판 금지).
    """
    found = []
    for job in active_dispatches(con):
        wid = job["payload"].get("worker_bot_id")
        if not wid:
            continue
        bot = con.execute("SELECT state FROM bot WHERE bot_id = ?", (wid,)).fetchone()
        if bot is None or bot["state"] != "checkout":
            continue
        row = con.execute(
            "SELECT id, created_at FROM job"
            " WHERE kind = ? AND status = 'done' AND owner = ? AND created_at >= ?"
            " ORDER BY created_at DESC LIMIT 1",
            (SESSION_JOB_KIND, wid, job["created_at"]),
        ).fetchone()
        if row is None:
            continue
        found.append({
            "job_id": job["id"], "from_status": job["status"],
            "issue": job["payload"].get("issue"), "role": job["payload"].get("role"),
            "worker_bot_id": wid, "session_job_id": row["id"],
            "completed_at": row["created_at"],
        })
    return found


def session_watermark(con: sqlite3.Connection) -> int:
    """세션 완료 통지 워터마크. 부재 시 **오늘 자정**으로 출발한다.

    왜 0 이 아닌가 — 0 이면 첫 실행에서 과거 전체(누적 세션 기록)를 한꺼번에 알린다.
    왜 '지금'이 아닌가 — 그러면 오늘 이미 끝난 작업을 영영 못 알린다. 자정이 그 사이다.
    """
    row = con.execute("SELECT value FROM kv WHERE ns = ? AND key = ?",
                      (NOTIFY_NS, NOTIFY_SESSION_KEY)).fetchone()
    if row is not None:
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            pass
    return int(time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")))


def detect_session_completions(con: sqlite3.Connection, watermark: int) -> list:
    """**배분에 매이지 않은** 봇 세션 완료를 골라낸다 (Issue438 ④).

    왜 필요한가 (2026-08-26 실측) — `detect_completions()` 는 `active_dispatches` 만 돈다.
    즉 taskmgr 로 배분된 작업만 완료가 통지된다. 그런데 봇을 fpm-do 로 **직접 위임**하면
    배분 원장에 없으므로, 봇이 일을 끝내도 **아무도 알리지 않는다**. 나래의 prj61 검토가
    정확히 그랬고 사람이 폴링해서야 알았다 — Issue438 이 없애려던 상황 그 자체다.

    계약 ④ 는 "배분 완료·QA 판정 등 **상태 전이 시점**에 통지" 다. 판정의 기준은
    배분 원장이 아니라 **봇이 일을 마쳤는가** 여야 한다.

    중복 방지: 배분 완료는 job status 전이가 구조적 보장이 되지만, 세션 기록은 done 인 채로
    남으므로 워터마크로 막는다. 배분으로 이미 통지된 세션은 `session_job_id` 역참조로 뺀다.
    """
    rows = con.execute(
        "SELECT id, owner, created_at FROM job"
        " WHERE kind = ? AND status = 'done' AND created_at > ?"
        " ORDER BY created_at",
        (SESSION_JOB_KIND, watermark),
    ).fetchall()
    if not rows:
        return []
    claimed = {
        r["sid"] for r in con.execute(
            "SELECT json_extract(result, '$.session_job_id') AS sid FROM job"
            " WHERE kind = ? AND result IS NOT NULL", (JOB_KIND,)).fetchall()
        if r["sid"]
    }
    out = []
    for r in rows:
        if r["id"] in claimed:
            continue   # 배분 완료로 이미 통지된 세션 — 두 번 알리지 않는다
        bot = con.execute("SELECT title, current_task FROM bot WHERE bot_id = ?",
                          (r["owner"],)).fetchone()
        out.append({
            "session_job_id": r["id"], "bot_id": r["owner"],
            "title": (bot["title"] if bot else None) or r["owner"],
            "task": (bot["current_task"] if bot else None) or "",
            "completed_at": r["created_at"],
        })
    return out


def run_sweep(dry_run: bool = False) -> dict:
    """완료 감지 → job status=done 갱신 → **묶음 1회** 통지.

    통지 규약(Issue399 승계 · 계약 §호출 경계): 여러 건이 동시에 완료돼도 mq 등록은
    **1건**이다. 건당 발신은 소음이 되고, 소음이 되면 사람이 통지를 끄게 된다.
    이미 done 으로 넘긴 배분은 다음 sweep 의 후보 집합(open/blocked)에서 빠지므로
    재통지가 구조적으로 불가능하다 — 별도 중복 마커를 두지 않는 이유다.
    """
    now = int(time.time())
    con = connect()
    try:
        done = detect_completions(con)
        wm = session_watermark(con)
        sessions = detect_session_completions(con, wm)
        if dry_run or not (done or sessions):
            return {"detected": len(done), "completed": done,
                    "sessions_detected": len(sessions), "sessions": sessions,
                    "watermark": wm, "enqueued": None,
                    "mode": "dry-run" if dry_run else "apply"}
        con.execute("BEGIN IMMEDIATE")
        for c in done:
            con.execute(
                "UPDATE job SET status = 'done', blocked_since = NULL, result = ?"
                " WHERE id = ? AND status IN ('open','blocked')",
                (json.dumps({"verdict": "completed", "detected_by": BOT_ID,
                             "session_job_id": c["session_job_id"],
                             "from_status": c["from_status"], "swept_at": now},
                            ensure_ascii=False), c["job_id"]),
            )
        # 워터마크는 통지 **전** 같은 트랜잭션에서 전진시킨다. 통지가 실패하면 그 예외로
        #   sweep 이 끝나고, 워터마크만 앞서 있어 재통지는 없다 — 유실 대신 중복을 막는 선택이다.
        #   (통지 실패는 mq_alert 이 FbotError 로 시끄럽게 알리므로 조용히 사라지지 않는다.)
        if sessions:
            newest = max(x["completed_at"] for x in sessions)
            con.execute(
                "INSERT INTO kv (ns, key, value, expires_at, updated_at, updated_by)"
                " VALUES (?,?,?,NULL,?,?)"
                " ON CONFLICT(ns, key) DO UPDATE SET"
                "   value = excluded.value, updated_at = excluded.updated_at",
                (NOTIFY_NS, NOTIFY_SESSION_KEY, str(newest), now, BOT_ID),
            )
        con.execute("COMMIT")
    finally:
        con.close()

    # 통지는 커밋 **후** 1회 — 쓰기가 실패한 건을 완료로 알리지 않는다.
    #   배분 완료와 세션 완료를 **한 건으로 묶는다**(계약 ④ "묶음 발신"). 건당 발신은
    #   소음이 되고, 소음이 되면 사람이 통지를 끈다.
    parts = []
    if done:
        parts.append("배분 완료 {}건 — {}".format(len(done), " · ".join(
            f"{c['issue'] or '?'}({c['role'] or '?'}/{c['worker_bot_id']})"
            + ("[에스컬레이션 해소]" if c["from_status"] == "blocked" else "")
            for c in done)))
    if sessions:
        parts.append("봇 작업 완료 {}건 — {}".format(len(sessions), " · ".join(
            f"{x['title']}" + (f": {x['task'][:40]}" if x["task"] else "")
            for x in sessions)))
    msg = "[fbot-taskmgr] " + " / ".join(parts)
    enq = mq_alert(msg)   # 실패 시 FbotError — 조용히 삼키지 않는다(통지 유실 금지)
    return {"detected": len(done), "completed": done,
            "sessions_detected": len(sessions), "sessions": sessions,
            "watermark": wm, "enqueued": enq, "message": msg, "mode": "apply"}


def cmd_sweep(args) -> int:
    """완료 감지 스윕 — 상태 전이 시점 통지의 진입점(tick worker 주기 편입)."""
    out = run_sweep(dry_run=args.dry_run)
    emit({"ok": True, "action": "sweep", **out})
    return 0


def cmd_cancel(args) -> int:
    """배분 취소 — 완료가 아니라 **무의미해진 배분의 명시 종결**이다.

    왜 필요한가 (2026-08-26 실측 — 중역핀봇 처분건):
      `detect_completions()` 는 reap(lease 만료 강제 퇴근)된 워커를 완료로 보지 않는다.
      세션 done 기록이 없으니 보수적으로 남기는 것이 **옳다**(오판 금지 — 그 주석 참조).
      빠져 있던 것은 그 다음이다: 배분이 **다른 주체가 일을 끝내버려 무의미해진** 경우
      종결할 경로가 없어 `open`/`blocked` 로 영구 잔류한다. `open` 은 동시 상한(WIP)을
      포화시켜 **신규 배분을 전면 차단**한다 — 실측에서 3/3 포화로 조직이 멈춰 있었다.
      경로가 없으니 중역핀봇이 registry.db 를 직접 UPDATE 했다. 그 우회를 없애는 것이 본 명령이다.

    ⚠️ 완료(`sweep`)와 취소(`cancel`)는 **다른 사건**이다. 취소는 워커가 일을 했다고 주장하지
      않으며, status 를 `done` 이 아니라 `cancelled` 로 둔다 — `done` 에 섞으면 `/fbot` 의
      "오늘 완료 N건" 집계가 오염된다(취소가 성과로 잡힌다).
    ⚠️ `--reason` 필수 — 근거 없는 원장 정리를 금지한다. 누가·왜 지웠는지 남지 않는 취소는
      나중에 "이 배분은 왜 사라졌나" 를 되짚을 수 없다.
    ⚠️ mq 통지 없음 — 취소는 사람·중역이 **알고서 명시 호출**하는 사건이라 되알림이 노이즈다
      (sweep 의 통지는 무인 주기가 발견한 사건이라 성격이 다르다).
    """
    con = connect()
    try:
        targets = [j for j in active_dispatches(con)
                   if (args.job_id and j["id"] == args.job_id)
                   or (args.issue and j["payload"].get("issue") == args.issue)]
        if not targets:
            key = args.job_id or args.issue
            # Reject 는 **수요측 가드 판정 번호** 전용이다(①~⑤) — 취소 대상 부재는 그 축이 아니다.
            raise FbotError(f"취소 대상 없음: {key} — 미종결(open/blocked) 배분이 아니다")
        rows = [{"job_id": j["id"], "issue": j["payload"].get("issue"),
                 "role": j["payload"].get("role"), "worker_bot_id": j["payload"].get("worker_bot_id"),
                 "from_status": j["status"]} for j in targets]
        if args.dry_run:
            emit({"ok": True, "action": "cancel", "mode": "dry-run",
                  "count": len(rows), "targets": rows})
            return 0
        now = int(time.time())
        # BEGIN IMMEDIATE — 판정과 쓰기 사이에 sweep 이 같은 건을 done 으로 옮겼을 수 있다.
        con.execute("BEGIN IMMEDIATE")
        applied = []
        for r in rows:
            cur = con.execute(
                "UPDATE job SET status = 'cancelled', result = ? WHERE id = ? AND status = ?",
                (json.dumps({"verdict": args.verdict, "reason": args.reason,
                             "cancelled_by": args.by, "from_status": r["from_status"],
                             "cancelled_at": now}, ensure_ascii=False),
                 r["job_id"], r["from_status"]),
            )
            if cur.rowcount == 1:
                applied.append(r)
        con.execute("COMMIT")
    finally:
        con.close()
    skipped = [r for r in rows if r not in applied]
    emit({"ok": True, "action": "cancel", "mode": "apply", "verdict": args.verdict,
          "cancelled": applied, "skipped_raced": skipped, "count": len(applied)})
    return 0


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
    # prj 해소 (prj3#Issue479) — cwd 는 workflow 만 해소하고 prj 는 버려지고 있었다. 그 결과
    #   전 봇이 prj=NULL 로 등록되어 "어느 prj 담당인가" 를 물을 수 없었다(2026-08-31 실측 13/13).
    prj = resolve_prj(cwd)
    pol = load_policy()
    con = connect()
    try:
        guard = judge_demand_guard(con, pol)  # ① 통과 못 하면 Reject → exit 1
    finally:
        con.close()

    if args.dry_run:
        emit({"ok": True, "action": "dispatch", "mode": "dry-run", "verdict": "허가",
              "issue": args.issue, "role": args.role, "workflow": workflow,
              "prj": prj, "guard": guard})
        return 0

    # ② HR 게이트 경유 배치 — 게이트 없는 스폰 경로 금지 (계약 §호출 경계)
    bot_id = args.bot_id or "fbot-{}-{}".format(
        args.role, re.sub(r"[^a-z0-9-]", "", args.issue.lower()) or uuid.uuid4().hex[:6]
    )
    hire_cmd = [sys.executable, HR_GATE_PY, "hire",
                "--bot-id", bot_id, "--role", args.role,
                "--title", f"{args.issue} 담당 {args.role} 워커",
                # 체인 기록 필수 — parent 는 깊이 판정(④)의 데이터 원천 (계약 F1 parent_bot_id)
                "--parent", TASKMGR_ID]
    if prj is not None:
        # 미해소는 --prj 를 아예 넘기지 않는다 — 게이트가 "전역봇(NULL)" 로 해석한다
        hire_cmd += ["--prj", str(prj)]
    hire = subprocess.run(hire_cmd, capture_output=True, text=True)
    if hire.returncode != 0:
        raise FbotError(
            f"HR 게이트 채용 거부·실패(exit {hire.returncode}) — 배분 중단: "
            f"{(hire.stderr or hire.stdout).strip()}"
        )

    # ③ 배분 기록 — bot_id=fbot-taskmgr 귀속(F4) + 원장 증분(BEGIN IMMEDIATE 재검증)
    now = int(time.time())
    job_id = f"fbotdisp-{now}-{uuid.uuid4().hex[:8]}"
    # 계약 §레지스트리 스키마: "어느 prj 일을 했나" 는 **작업 기록**이 답한다 — bot.prj(주 담당)와
    #   축이 다르므로 배분 원장에도 남긴다(겸임은 기록 레벨에서 표현된다).
    payload = {"issue": args.issue, "role": args.role, "worker_bot_id": bot_id,
               "cwd": cwd, "workflow": workflow, "prj": prj}
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
    """진행 감시 — **완료 스윕 선행** → 적체 2종 판정 → 재시도 카운트 → 초과 시 에스컬레이션.

    ⚠️ 순서가 계약이다. 완료한 워커도 `checkout` 이라 적체 B 와 겉모습이 같다 —
    스윕을 뒤에 두면 정상 완료가 먼저 에스컬레이션되어 거짓 경보가 된다.
    """
    pol = load_policy()
    now = int(time.time())
    swept = run_sweep(dry_run=False)   # 선행 — 완료분은 done 으로 빠져 적체 판정 대상에서 제외
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
                reason = f"워커 봇 퇴근 상태(작업 미완): {wid} — 조치: fbot-hr-gate.py wake --bot {wid} (Issue498)"
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
                enq = mq_alert(msg)
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
                    item["enqueued"] = mq_alert(msg)
                    escalated.append({"issue": it["id"], "reason": "미배분 적체",
                                      "enqueued": item["enqueued"]})
                idle_pending.append(item)
                stalls.append({"kind": "undispatched", "issue": it["id"], "seen": seen})
        else:
            idle_note = "미배분 적체 판정 생략 — --cwd 미지정(issue-map 대상 프로젝트 없음)"
    finally:
        con.close()

    out = {"ok": True, "action": "watch", "now": now,
           "swept": {"detected": swept["detected"], "enqueued": swept["enqueued"]},
           "stall_count": len(stalls), "stalls": stalls,
           "retried": retried, "escalated": escalated}
    if args.cwd is not None:
        out["undispatched_startable"] = idle_pending
    else:
        out["note"] = idle_note
    emit(out)
    return 0


def cmd_status(args) -> int:
    """이번 달 배분 수·상한·활성 배분 목록 + 취소 집계(Issue446 — 완료와 분리)."""
    pol = load_policy()
    month = month_key()
    con = connect()
    try:
        spent = dispatched_this_month(con, month)
        actives = active_dispatches(con)
        cancels = cancelled_dispatches(con)
    finally:
        con.close()
    # 취소는 **별도 축**이다 — dispatch.spent(예산 차감분)에서 빼지도, done 에 더하지도
    #   않는다. 예산은 이미 쓴 것이고 성과는 아니다. 그 둘을 동시에 성립시키는 유일한
    #   표현이 "따로 세어 따로 보여주기" 다 (Issue446).
    month_cancels = [c for c in cancels if month_key(c["cancelled_at"]) == month]
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
        "cancelled": {
            "total": len(cancels), "month": len(month_cancels),
            # 사유는 `cancel --reason` 이 강제해 원장에 이미 있다 — 여기서 지어내지 않는다.
            "recent": [
                {"job_id": c["id"], "issue": c["payload"].get("issue"),
                 "role": c["payload"].get("role"),
                 "worker_bot_id": c["payload"].get("worker_bot_id"),
                 "verdict": c["result"].get("verdict"), "reason": c["result"].get("reason"),
                 "cancelled_by": c["cancelled_by"], "cancelled_at": c["cancelled_at"]}
                for c in cancels[-5:][::-1]
            ],
        },
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

    sp = sub.add_parser("sweep", help="완료 감지 — 워커 퇴근+세션 done 배분을 done 처리 + 묶음 통지 1회")
    sp.add_argument("--dry-run", action="store_true", help="감지까지만 — 갱신·통지 없음")
    sp.set_defaults(func=cmd_sweep)

    sp = sub.add_parser("cancel", help="배분 취소 — 무의미해진 배분을 사유와 함께 명시 종결(완료 아님)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 지정")
    g.add_argument("--issue", default=None, help="이슈 ID 로 지정 (ex: Issue329 — 동일 이슈 전건)")
    sp.add_argument("--reason", required=True, help="취소 사유(필수) — 근거 없는 원장 정리 금지")
    sp.add_argument("--verdict", default="cancelled_obsolete", help="판정 코드(기본 cancelled_obsolete)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "human"), help="취소 주체 bot_id(기본 $FBOT_ID)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 갱신 없음")
    sp.set_defaults(func=cmd_cancel)

    sp = sub.add_parser("status", help="이번 달 배분 수·상한·활성 배분 목록 + 취소 집계(완료와 분리)")
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
