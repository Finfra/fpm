#!/usr/bin/env python3
"""fbot 팀장핀봇(lead) 판정 코어 (Issue436_3 s3 — 단계 3·4·5·6).

계약: ~/.claude/_doc_arch/fbot-arch.md §조직(팀장핀봇 임무·수요측 가드) ·
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
    dispatch (--issue ID | --topic TEXT) --role ROLE [--cwd DIR] [--bot-id ID] [--dry-run]
        배분 **요청**: ① 수요측 가드 판정(월 배분 상한·동시 배분 상한 — 단일 지점)
        ② 통과 시 HR 게이트 `hire` 호출로 워커 봇 채용까지(스폰 집행은 fpm-do/Agent
        몫 — 여기서는 채용+배분 기록. 게이트 없는 스폰 경로 금지)
        ③ bot_id=fbot-lead 귀속으로 registry.job 에 배분 기록(kind=fbot_dispatch).
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
        (aoa-mq `--alert --from-bot fbot-lead`). watch 는 이 스윕을 **선행** 실행한다 —
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
TASKMGR_ID = "fbot-lead"
HR_GATE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-hr-gate.py")

# aoa-mq 등록 helper (직접 큐 파일 Write 금지 — helper 경유만)
MQ_ENQUEUE_SH = os.path.join(
    os.path.expanduser("~"), ".claude", "mcp", "aoa-mq", "aoa-mq-enqueue.sh"
)

BOT_ID = "fbot-lead"  # 배분자 **기본값** (F4). prj3#Issue538 로 prj별 PM 이 생기면서

# prj3#Issue608 — 배분 계층. 총괄이 직접 부릴 수 있는 상대(= 관리자)다.
#   워커 role 을 열거하지 않는 이유: 직능은 발굴로 계속 늘어난다(Issue566 배포핀봇 등).
#   **관리자 목록만 고정**하면 새 직능이 생겨도 규칙이 자동으로 맞는다.
MANAGER_ROLES = ("lead", "hr", "scout", "chief")
#   배분자가 여럿이 됐다 — `dispatch --by` 로 지정하지 않으면 이 전역 봇이 배분자다.
#   ⚠️ 예산·상한 원장 키는 **전역 합산 그대로**다(아래 dispatch 주석 참조).

# policy.yml 필수 키 2종 (s3 편입분 — 수요측 가드) — 로드 실패 시 fail-loud
POLICY_KEYS = ("fbot_dispatch_monthly_limit", "fbot_dispatch_concurrent_limit")
# prj3#Issue613 — 배분자별 상한은 **선택 키**다. 부재 시 3 으로 돈다(fail-soft) —
#   필수로 두면 policy 미갱신 머신에서 배분이 통째로 막힌다.

DISPATCH_NS = "fbot:dispatch"  # registry.kv 배분 원장 네임스페이스 (HR ns=fbot:budget 과 분리)
JOB_KIND = "fbot_dispatch"     # registry.job 배분 기록 kind
# prj3#Issue612 — 분업 우회 기록. **배분과 kind 를 섞지 않는다**: 섞으면 우회가 배분 실적으로
#   잡혀 조직 판정(부하·결원)이 정확히 반대로 읽는다(취소를 완료와 분리한 것과 같은 이유).
SOLO_JOB_KIND = "fbot_solo"
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
    # prj3#Issue626 — **정책 수치의 정본은 prj3** 다. 데이터(registry.db·learn.db)는 용량 때문에
    #   prj5 에 남지만(zshenv 명시 결정) 수치는 prj3 소관이다. 폴백 순서가 핵심이다:
    #   ⓐ `aoa_dir()` 에 있으면 그것 — **테스트가 픽스처에 쓴 policy 를 계속 읽는다**
    #   ⓑ 없으면 prj3. 운영에서는 prj5 사본을 걷었으므로 여기로 온다
    #   순서를 뒤집으면 테스트가 운영 policy 를 읽어 픽스처가 무력해진다.
    path = os.path.join(aoa_dir(), "policy.yml")
    if not os.path.exists(path):
        _p3 = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa", "policy.yml")
        if os.path.exists(_p3):
            path = _p3
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
        print(f"[fbot-lead] ⚠️ prj resolver 없음({PM_BASE_FILE}) — prj 미기록으로 진행",
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
    """미종결 fbot_dispatch job 전체 (open=진행, blocked=사람 ACK 대기, logged=사후 기록).

    ⚠️ 동시 상한(WIP) 판정은 호출측이 `status=="open"` 만 필터한다 — blocked 는
    사람 판단 대기라 WIP 슬롯을 점유하지 않는 것이 의도(s3 QA 발견 ② 명문화).

    prj3#Issue514 (2026-09-03) — **`logged` 를 미종결로 확정하고 여기 편입한다.**
      `logged` 는 `fbot-state.py dispatch-record` 가 남기는 **사후 기록**이다(이슈 번호 없는
      크로스 프로젝트 작업 등, `lead dispatch` 를 쓸 수 없는 경로). 종전에는 이 술어에
      없어서 **어떤 자동 경로로도 닫히지 않았다** — `status` 에 안 보이고(`active_dispatches: []`)
      `sweep` 도 감지하지 못해(`detected: 0`) 사람이 손으로 정리해야 했다.
      실측 2026-09-03: 나래의 리서치봇 2기가 정상 완료·퇴근했는데 배분 2건이 `logged` 로 잔류.

      🔴 **WIP 는 여전히 점유하지 않는다.** `logged` 는 *이미 일어난 일* 의 기록이지 슬롯
      예약이 아니다(`dispatch-record` 가 상한 판정을 두지 않는 것과 같은 이유). 호출측
      필터가 `=="open"` 이므로 편입해도 동시 상한은 불변이다 — 보이게만 만든다.
    """
    rows = con.execute(
        "SELECT * FROM job WHERE kind = ? AND status IN ('open','blocked','logged')"
        " ORDER BY created_at",
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
    신설 이전에 총괄핀봇이 직접 UPDATE 로 화해한 건의 `swept_at`. 둘 다 없으면 생성
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


def _state_mod():
    """fbot-state.py 의 record_event/notify_hub_event 재사용 (prj3#Issue575). 부재·실패는 조용히 None."""
    try:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-state.py")
        spec = importlib.util.spec_from_file_location("fbot_state", path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _ev(con, bot, etype, detail="", ref=""):
    m = _state_mod()
    if m:
        try:
            m.record_event(con, bot, etype, detail, ref)
        except Exception:
            pass


def _ev_notify(bot, etype, ref=""):
    m = _state_mod()
    if m:
        try:
            m.notify_hub_event(bot, etype, ref)
        except Exception:
            pass


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── 수요측 가드 (판정 단일 지점 — dispatch·dry-run 공용) ────────────────────

def judge_demand_guard(con, pol, actor: str = "") -> dict:
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

    # prj3#Issue613 — ⓒ **유령은 슬롯을 먹지 않는다.** 워커가 대장에 없으면 `sweep` 이
    #   영원히 못 닫아 슬롯을 무기한 점유한다(실측: `fbot-taskmgr-claude` 배분이 4일 점유).
    #   상한은 *지금 도는 몸체* 를 세려는 것이지 닫히지 않는 기록을 세려는 것이 아니다.
    known = {r[0] for r in con.execute("SELECT bot_id FROM bot")}
    ghosts = [j for j in active
              if (j.get("payload") or {}).get("worker_bot_id") not in known]
    active = [j for j in active if j not in ghosts]

    # prj3#Issue613 — ⓐ **축을 가른다.** 종전에는 상위→하위와 하위→더하위가 같은 전역
    #   카운터를 써서, *내가 일을 받았다는 사실이 내가 일을 내려보낼 슬롯을 먹었다*.
    #   Issue612 가 배분을 **의무**로 만든 뒤 이 충돌이 상시화됐다(팀장이 qa 에 배분하려는
    #   순간 거부 — 규칙이 요구하는 행동을 게이트가 막는다). 폭주 가드의 취지는
    #   *"동시에 몇 개의 몸체가 도는가"* 이므로 **배분자별 상한 + 전역 상한** 2단이면 취지가 산다.
    by = (pol.get("fbot_dispatch_actor_limit") or 3)
    actor = actor or ""
    mine = [j for j in active if (j.get("payload") or {}).get("by") == actor] if actor else []
    if actor and len(mine) >= by:
        raise Reject(2, f"배분자 동시 상한 도달 — {actor} 의 활성 배분 {len(mine)}건 ≥ 상한 {by}건. "
                        f"자기 배분을 먼저 sweep/cancel 하거나 상한(fbot_dispatch_actor_limit)을 조정한다")
    if len(active) >= c_limit:
        raise Reject(2, f"동시 배분 상한 도달 — 활성 배분 {len(active)}건 ≥ 상한 {c_limit}건"
                        + (f" (유령 {len(ghosts)}건은 제외했다)" if ghosts else ""))
    return {"month": month, "spent": spent, "monthly_limit": m_limit,
            "active": len(active), "concurrent_limit": c_limit,
            "actor": actor, "actor_active": len(mine), "actor_limit": by,
            "ghosts_excluded": len(ghosts)}


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
    즉 lead 로 배분된 작업만 완료가 통지된다. 그런데 봇을 fpm-do 로 **직접 위임**하면
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
            _ev(con, c.get("worker_bot_id") or BOT_ID, "done", f"완료 판정: {(c.get('issue') or '')[:80]}", c.get("job_id") or "")   # prj3#Issue575
            con.execute(
                "UPDATE job SET status = 'done', blocked_since = NULL, result = ?"
                # prj3#Issue514 — `logged`(사후 기록분)도 완료로 닫는다. 종결 경로가 없어
                #   영구 잔류하던 것이 이 술어의 누락이었다.
                " WHERE id = ? AND status IN ('open','blocked','logged')",
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
    msg = "[fbot-lead] " + " / ".join(parts)
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

    왜 필요한가 (2026-08-26 실측 — 총괄핀봇 처분건):
      `detect_completions()` 는 reap(lease 만료 강제 퇴근)된 워커를 완료로 보지 않는다.
      세션 done 기록이 없으니 보수적으로 남기는 것이 **옳다**(오판 금지 — 그 주석 참조).
      빠져 있던 것은 그 다음이다: 배분이 **다른 주체가 일을 끝내버려 무의미해진** 경우
      종결할 경로가 없어 `open`/`blocked` 로 영구 잔류한다. `open` 은 동시 상한(WIP)을
      포화시켜 **신규 배분을 전면 차단**한다 — 실측에서 3/3 포화로 조직이 멈춰 있었다.
      경로가 없으니 총괄핀봇이 registry.db 를 직접 UPDATE 했다. 그 우회를 없애는 것이 본 명령이다.

    ⚠️ 완료(`sweep`)와 취소(`cancel`)는 **다른 사건**이다. 취소는 워커가 일을 했다고 주장하지
      않으며, status 를 `done` 이 아니라 `cancelled` 로 둔다 — `done` 에 섞으면 `/fbot` 의
      "오늘 완료 N건" 집계가 오염된다(취소가 성과로 잡힌다).
    ⚠️ `--reason` 필수 — 근거 없는 원장 정리를 금지한다. 누가·왜 지웠는지 남지 않는 취소는
      나중에 "이 배분은 왜 사라졌나" 를 되짚을 수 없다.
    ⚠️ mq 통지 없음 — 취소는 사람·총괄이 **알고서 명시 호출**하는 사건이라 되알림이 노이즈다
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
            _ev(con, args.by or BOT_ID, "cancel", f"{r.get('id','')}: {args.reason or ''}"[:120], r.get("id",""))   # prj3#Issue575
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


def _spawn_commands(worker: str, ident: str, cwd: str, prj):
    """dispatch 응답의 `next_step` — 워커 몸체를 띄우는 두 형태 (prj3#Issue554).

    * fpm-do: prj 매핑이 있을 때. `FBOT_ID` 가 출근 훅을 켜고 `FBOT_TASK` 가 current_task 를 채운다
      (fpm-do 가 tmux 새 창에 env 를 실어 보낸다 — Issue438·462).
    * Agent: pane 이 없는 형태. `name=<worker>` 로 띄우면 fbot-agent-bind.sh(PreToolUse) 가 결속한다.
    """
    task = (ident or "").replace("'", "'\\''")[:120]
    out = {"agent": f"Agent(name='{worker}', prompt='{task} — cwd {cwd}')"}
    if prj is not None:
        out["fpm_do"] = f"FBOT_ID={worker} FBOT_TASK='{task}' fpm-do {prj} '{task}'"
        out["run"] = "fpm_do"
    else:
        out["run"] = "agent"
    return out


def cmd_dispatch(args) -> int:
    """배분 요청 — ① 수요측 가드 ② HR 게이트 hire(채용) ③ 배분 기록(F4).

    스폰 **집행**은 fpm-do/Agent 몫이다 — 여기서는 채용과 기록까지만.
    착수 가능 판정은 pending(issue-map)이 재료다 — 배분 요청은 그 판정을 재현하지 않는다.
    """
    # Issue526 — 식별자 축을 넓힌다. 단일 `--issue` 가 없는 작업(크로스 프로젝트 조사 등)이
    #   정규 경로를 못 써서 `dispatch-record` 로 우회하던 것이 `logged` 의 발생 원인이었다.
    #   ⚠️ payload 키는 `issue` 그대로 둔다 — status/sweep/queue 등 소비처 9곳이 전부
    #   `payload.get("issue")` 를 읽는다. 키를 바꾸면 그 전부가 조용히 빈 값을 보게 된다.
    #   구분이 필요하면 `ident_kind` 를 본다.
    ident = (args.issue or getattr(args, "topic", None) or "").strip()
    if not ident:
        raise Reject(2, "배분 식별자가 없다 — --issue 또는 --topic 중 하나는 필수다")
    ident_kind = "issue" if args.issue else "topic"

    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    workflow = load_workflow(cwd)
    # prj 해소 (prj3#Issue479) — cwd 는 workflow 만 해소하고 prj 는 버려지고 있었다. 그 결과
    #   전 봇이 prj=NULL 로 등록되어 "어느 prj 담당인가" 를 물을 수 없었다(2026-08-31 실측 13/13).
    prj = resolve_prj(cwd)
    pol = load_policy()
    _actor = getattr(args, "by", None) or BOT_ID   # prj3#Issue613 — 배분자별 축
    con = connect()
    try:
        guard = judge_demand_guard(con, pol, _actor)  # ① 통과 못 하면 Reject → exit 1
    finally:
        con.close()

    # prj3#Issue538: 배분자 실재 확인. `job.owner_id` 가 `bot(bot_id)` FK 라 없는 봇이면
    #   INSERT 가 실패한다. **dry-run 보다 앞**에 둔다 — dry-run 의 계약이 "가드 판정까지"
    #   이고 배분자 실재는 가드의 일부다. 뒤에 두면 dry-run 이 없는 배분자를 허가한다.
    #   ⚠️ sqlite3.Connection 의 `with` 는 트랜잭션 컨텍스트일 뿐 커넥션을 닫지 않는다.
    dispatcher = getattr(args, "by", None) or BOT_ID
    _c = connect()
    try:
        _drow = _c.execute("SELECT role FROM bot WHERE bot_id=?", (dispatcher,)).fetchone()
        if not _drow:
            raise Reject(1, f"배분자가 대장에 없다: {dispatcher} (채용이 먼저다)")
        # prj3#Issue608 — **계층 건너뛰기 금지** (사용자 지적 2026-09-09):
        #   *"회장이나 사장이 말단 사원에게 일을 시키는 꼴이다. 전체 구조를 아는 관리자가 시켜야 한다."*
        #   총괄(chief)은 **매니저에게만** 배분한다. 워커에게 직행하면
        #     ① PM 이 모르는 작업이 그 prj 에서 돌고 ② 같은 자원에 두 지시가 겹치며
        #     ③ PM 의 부하 판단(추가 채용 필요 여부)이 어긋난다 — HR·발굴 오작동과 같은 경로다.
        #   PM → 워커는 정상이다(그것이 PM 의 임무). 과잉 제약을 피해 **exec 의 워커 직행만** 막는다.
        _drole = (_drow[0] or "") if not isinstance(_drow, dict) else (_drow["role"] or "")
        if _drole == "chief" and (args.role or "") not in MANAGER_ROLES:
            raise Reject(1,
                f"총괄은 워커에게 직접 배분하지 않는다 (대상 role={args.role}). "
                f"전체 구조를 아는 PM(팀장핀봇)을 거친다 — "
                f"① fbot-org.py resolve --prj <N> 로 PM 확인 "
                f"② PM 이 없으면 인사핀봇에 staffing 요청 "
                f"③ --role lead --bot-id <PM> 로 배분하고 PM 이 워커에게 다시 배분한다")
    finally:
        _c.close()

    if args.dry_run:
        emit({"ok": True, "action": "dispatch", "mode": "dry-run", "verdict": "허가",
              "dispatched_by": dispatcher,
              "issue": ident, "ident_kind": ident_kind, "role": args.role,
              "workflow": workflow, "prj": prj, "guard": guard})
        return 0

    # ② HR 게이트 경유 배치 — 게이트 없는 스폰 경로 금지 (계약 §호출 경계)
    # slug 는 구분자를 **삭제하지 않고 치환**한다 (prj3#Issue515 ⓒ) — 삭제하면
    #   `Issue436_3` → `fbot-research-issue4363` 이 되어 `Issue43_63` 과 같은 bot_id 로
    #   충돌한다. 치환하면 `issue436-3` / `issue43-63` 으로 갈라진다.
    #   ⚠️ 기존에 발급된 id 는 소급 변경하지 않는다(대장·원장 참조가 깨진다).
    #   `--topic` 도 같은 치환 규칙을 탄다 — 자유 문자열이라 공백·한글이 섞이지만
    #   `[^a-z0-9]+` 치환이 전부 `-` 로 접어 주고, 남는 게 없으면 uuid 로 떨어진다.
    # 배분자 실재 확인 — `job.owner_id` 가 `bot(bot_id)` FK 라 없는 봇이면 INSERT 가
    #   실패한다. 여기서 미리 fail-loud 하지 않으면 채용까지 끝낸 뒤 터진다.
    bot_id = args.bot_id or "fbot-{}-{}".format(
        args.role,
        re.sub(r"[^a-z0-9]+", "-", ident.lower()).strip("-") or uuid.uuid4().hex[:6]
    )
    # prj3#Issue554 — **이미 등록된 개체**(prj PM·상비봇)에 배분하면 채용이 아니라 **재기동(wake)** 이다.
    #   종전엔 무조건 hire 라 "중복 bot_id" 로 거부됐다(2026-09-06 실측: 중역 → PM 배분이 이 자리에서
    #   막혀 체인이 원장에 남을 수 없었다). `checkout` 은 cold 다(계약 §상태 기계 ⓓ) — 배분 도착이 곧
    #   wake 트리거이고, 집행체는 hire 의 형제 `wake`(상주 상한만 판정·예산 무차감)다.
    _c = connect()
    try:
        existing = _c.execute("SELECT role, career FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
    finally:
        _c.close()
    if existing:
        if existing["role"] != args.role:
            raise Reject(1, f"배분 대상 {bot_id} 의 role 은 {existing['role']} — --role {args.role} 과 다르다")
        gate = subprocess.run([sys.executable, HR_GATE_PY, "wake", "--bot", bot_id],
                              capture_output=True, text=True)
        if gate.returncode != 0:
            raise FbotError(
                f"HR 게이트 재기동 거부·실패(exit {gate.returncode}) — 배분 중단: "
                f"{(gate.stderr or gate.stdout).strip()}"
            )
        placement = "wake"
    else:
        hire_cmd = [sys.executable, HR_GATE_PY, "hire",
                    "--bot-id", bot_id, "--role", args.role,
                    "--title", f"{ident} 담당 {args.role} 워커",
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
        placement = "hire"

    # ③ 배분 기록 — bot_id=fbot-lead 귀속(F4) + 원장 증분(BEGIN IMMEDIATE 재검증)
    now = int(time.time())
    job_id = f"fbotdisp-{now}-{uuid.uuid4().hex[:8]}"
    # 계약 §레지스트리 스키마: "어느 prj 일을 했나" 는 **작업 기록**이 답한다 — bot.prj(주 담당)와
    #   축이 다르므로 배분 원장에도 남긴다(겸임은 기록 레벨에서 표현된다).
    payload = {"issue": ident, "ident_kind": ident_kind, "role": args.role,
               "worker_bot_id": bot_id, "cwd": cwd, "workflow": workflow, "prj": prj}
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
        # prj3#Issue538: `owner` 는 **배분자**다. 전역 하나로 고정하면 prj PM 이 배분해도
        #   원장에는 전역 봇이 시킨 것으로 남아 **총괄→PM→워커 체인이 원리적으로
        #   기록될 수 없다**(실측: dispatch 1건이 전부 taskmgr owner).
        # ⚠️ 예산·상한 원장 키(DISPATCH_NS)는 위에서 **BOT_ID 로 전역 합산**한다 —
        #   배분자별로 갈리면 PM 을 늘리는 것만으로 3중 폭주 가드를 우회할 수 있다.
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (job_id, "fbot", JOB_KIND, "open", json.dumps(payload, ensure_ascii=False),
             dispatcher, now),
        )
        _ev(con, dispatcher, "dispatch", f"→ {bot_id}: {ident[:80]}", job_id)     # prj3#Issue575
        _ev(con, bot_id, "assigned", f"← {dispatcher}: {ident[:80]}", job_id)
        con.execute("COMMIT")
        _ev_notify(dispatcher, "dispatch", job_id)
        spent_after = dispatched_this_month(con, month)
    finally:
        con.close()

    # prj3#Issue538: 조직 부활 — **깨우는 것은 시간이 아니라 일이다.**
    #   집행 지점을 배분 1곳에 둔다. 조직도 렌더나 hub 요청이 부활시키면 관측이 상태를
    #   바꾸는 것이라 원장이 거짓말을 시작한다. 실패해도 배분을 막지 않는다(fail-soft) —
    #   조직 기능은 표시 계층이고 배분은 작업 계층이다.
    woke = None
    if prj is not None:
        try:
            import importlib.util as _il
            _op = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-org.py")
            if os.path.exists(_op):
                _sp = _il.spec_from_file_location("fbot_org", _op)
                _m = _il.module_from_spec(_sp); _sp.loader.exec_module(_m)
                _r = _m.wake(prj, reason=f"배분 {job_id}")
                woke = bool(_r.get("changed"))
        except Exception as _e:
            log(f"org wake(prj={prj}) skipped: {_e}") if "log" in dir() else None

    emit({
        "ok": True, "action": "dispatch", "verdict": "허가",
        "issue": args.issue, "role": args.role, "worker_bot_id": bot_id,
        "dispatched_by": dispatcher, "placement": placement,
        "job_id": job_id, "workflow": workflow, "org_woke": woke,
        "ledger": {"ns": DISPATCH_NS, "month": month, "spent": spent_after,
                   "limit": pol["fbot_dispatch_monthly_limit"]},
        "next": "스폰 집행은 fpm-do/Agent 몫 — 본 기록은 채용+배분까지 (계약 §호출 경계)",
        # prj3#Issue554 — 집행 명령을 응답에 싣는다. 매뉴얼이 명령을 복제하면 낡는다;
        #   배분자는 이 값을 **그대로 실행**한다. 실행하지 않으면 워커는 출근 0회로 reap 된다
        #   (2026-09-06 실측: 배분 2건 전부 reaped, session_id NULL).
        "next_step": _spawn_commands(bot_id, ident, cwd, prj),
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
                msg = (f"[fbot-lead] 배분 적체 에스컬레이션 — job {job['id']} "
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
                    msg = (f"[fbot-lead] 미배분 적체 에스컬레이션 — {data['root']} "
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


def cmd_close(args) -> int:
    """**외부 증적으로 확정된 완료**를 원장에 반영한다 (prj3#Issue514, prj3#Issue495 예외의 경로화).

    왜 필요한가 — `sweep` 의 완료 판정은 원장 안의 증거(`fbot_session` done + 워커 `checkout`)
      를 요구한다. 그것이 옳다: 원장 밖 주장으로 완료를 찍으면 원장이 거짓말을 하기 시작한다.
      그런데 **증거가 원장에서 사라지는 경로가 실재**한다 —
        ⓐ prj3#Issue495: Agent 형태 봇이 퇴근 훅을 못 받아 세션 기록을 아예 못 남긴 경우
        ⓑ prj3#Issue514: 워커를 **해고**하면서 그 봇 행·세션 기록이 함께 지워진 경우(2026-09-03 실측)
      두 경우 모두 일은 **끝났고** 커밋·리포트라는 외부 증적이 있는데, `sweep` 은 영원히 못 닫고
      `cancel` 은 완료를 "무의미해짐" 으로 적어 거짓이 된다.

    🔴 prj3#Issue495 는 이 상황에서 **직접 UPDATE 를 1회 집행**하고 이렇게 적었다 —
      *"같은 상황이 재발하면 예외가 아니라 경로 부재의 신호로 읽는다."* 재발했다(prj3#Issue514).
      그래서 예외를 반복하는 대신 **경로를 만든다**. 이것이 그 경로다.

    ⚠️ `--evidence` 필수 — 원장 밖 증거를 원장 안에 **박아 둔다**(커밋 해시·리포트 경로·이슈).
      증적 없는 close 는 `sweep` 의 판정 규율을 우회하는 뒷문이 될 뿐이다.
    ⚠️ `verdict` 는 `completed_external` 로 `sweep` 의 `completed` 와 **구분**한다 — 나중에
      *"이 완료는 무엇이 보증했나"* 를 물을 수 있어야 한다.
    ⚠️ mq 통지 없음 — `cancel` 과 같은 이유다(사람이 알고서 명시 호출하는 사건).
    """
    con = connect()
    try:
        targets = [j for j in active_dispatches(con)
                   if (args.job_id and j["id"] == args.job_id)
                   or (args.issue and j["payload"].get("issue") == args.issue)
                   or (args.worker and j["payload"].get("worker_bot_id") == args.worker)]
        if not targets:
            key = args.job_id or args.issue or args.worker
            raise FbotError(f"종결 대상 없음: {key} — 미종결(open/blocked/logged) 배분이 아니다")
        rows = [{"job_id": j["id"], "issue": j["payload"].get("issue"),
                 "role": j["payload"].get("role"),
                 "worker_bot_id": j["payload"].get("worker_bot_id"),
                 "from_status": j["status"]} for j in targets]
        if args.dry_run:
            emit({"ok": True, "action": "close", "mode": "dry-run",
                  "count": len(rows), "targets": rows, "evidence": args.evidence})
            return 0
        now = int(time.time())
        con.execute("BEGIN IMMEDIATE")
        applied = []
        for r in rows:
            _ev(con, args.by or BOT_ID, "close", f"{r.get('id','')}: {args.evidence or ''}"[:120], r.get("id",""))   # prj3#Issue575
            cur = con.execute(
                "UPDATE job SET status = 'done', blocked_since = NULL, result = ?"
                " WHERE id = ? AND status = ?",
                (json.dumps({"verdict": "completed_external",
                             "evidence": args.evidence, "reason": args.reason,
                             "detected_by": "manual:%s" % args.by,
                             "from_status": r["from_status"], "closed_at": now},
                            ensure_ascii=False),
                 r["job_id"], r["from_status"]),
            )
            if cur.rowcount == 1:
                applied.append(r)
        con.execute("COMMIT")
    finally:
        con.close()
    skipped = [r for r in rows if r not in applied]
    emit({"ok": True, "action": "close", "mode": "apply", "verdict": "completed_external",
          "evidence": args.evidence, "closed": applied,
          "skipped_raced": skipped, "count": len(applied)})
    return 0


def cmd_solo(args) -> int:
    """분업 우회 기록 — 팀장이 **직접 수행하는 사유**를 원장에 남긴다 (prj3#Issue612).

    왜 필요한가:
      Issue612 는 *"직능 자리가 있으면 배분 의무"* 를 확정하고 [`fbot-writeguard.sh`](fbot-writeguard.sh)
      로 집행한다. 그런데 **모든 직접 수행이 위반은 아니다** — 자리 없는 일(조직 선언에 없는 직능),
      워커를 띄우는 비용이 작업보다 큰 한 줄 수정, 배분 자체를 성립시키기 위한 선행 작업이 있다.
      우회로가 없으면 가드가 팀장의 손을 통째로 묶고, 묶인 가드는 곧 꺼진다(prj1#Issue480 실패형).

    ⚠️ **우회는 무료가 아니다 — 사유가 원장에 남는다.** 그래서 감사에서 *"이 팀장은 배분 0건에
      우회 12건"* 이 보인다. 가드가 막는 것은 직접 수행이 아니라 **말없는 직접 수행**이다.
    ⚠️ 배분(`fbot_dispatch`)과 **kind 를 분리**한다. 같은 kind 로 섞으면 우회가 배분 실적으로
      잡혀 조직 판정(HR 부하·발굴 필요)이 정확히 반대로 읽는다 — 취소를 완료와 분리한 것과 같은 이유.
    ⚠️ 예산(`kv fbot:dispatch`)은 차감하지 않는다. 우회는 워커를 띄우지 않으므로 스폰 비용이 없다.
    """
    by = getattr(args, "by", None) or os.environ.get("FBOT_ID", "") or BOT_ID
    reason = (args.reason or "").strip()
    if len(reason) < 8:
        raise Reject(2, "우회 사유가 너무 짧다(8자 이상) — 감사에서 읽히지 않는 사유는 사유가 아니다")
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    prj = resolve_prj(cwd)
    con = connect()
    try:
        row = con.execute("SELECT role FROM bot WHERE bot_id=?", (by,)).fetchone()
        if not row:
            raise Reject(1, f"우회 주체가 대장에 없다: {by} (결속·채용이 먼저다)")
        role = row["role"] if not isinstance(row, tuple) else row[0]
        now = int(time.time())
        job_id = f"fbotsolo-{now}-{uuid.uuid4().hex[:8]}"
        payload = {"reason": reason, "scope": (args.scope or "").strip(),
                   "role": role, "cwd": cwd, "prj": prj}
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (job_id, "fbot", SOLO_JOB_KIND, "logged",
             json.dumps(payload, ensure_ascii=False), by, now),
        )
        _ev(con, by, "solo", f"{(args.scope or '')[:40]}: {reason[:80]}", job_id)
        con.execute("COMMIT")
    finally:
        con.close()
    emit({"ok": True, "action": "solo", "job_id": job_id, "by": by, "role": role,
          "reason": reason, "scope": payload["scope"], "prj": prj, "cwd": cwd,
          "note": "이 세션의 직접 수정이 허용된다 (fbot-writeguard.sh 는 결속 이후 기록만 센다)"})
    return 0


def solo_records(con: sqlite3.Connection) -> list:
    """우회 기록 조회 — 감사용(status 가 배분·취소와 **나란히** 보여준다)."""
    rows = con.execute(
        "SELECT id, owner, payload, created_at FROM job WHERE kind = ? ORDER BY created_at",
        (SOLO_JOB_KIND,),
    ).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        out.append({"id": r["id"], "owner": r["owner"], "payload": payload,
                    "created_at": r["created_at"]})
    return out


def cmd_status(args) -> int:
    """이번 달 배분 수·상한·활성 배분 목록 + 취소 집계(Issue446 — 완료와 분리)."""
    pol = load_policy()
    month = month_key()
    con = connect()
    try:
        spent = dispatched_this_month(con, month)
        actives = active_dispatches(con)
        cancels = cancelled_dispatches(con)
        solos = solo_records(con)
    finally:
        con.close()
    month_solos = [s for s in solos if month_key(s["created_at"]) == month]
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
        # prj3#Issue612 — 분업 우회 감사축. 배분과 **나란히** 보여야 비율이 읽힌다:
        #   배분 0 · 우회 12 는 조항이 지켜지지 않는다는 신호이고, 그것을 보는 자리가 여기다.
        "solo": {
            "total": len(solos), "month": len(month_solos),
            "by_bot": {b: len([s for s in month_solos if s["owner"] == b])
                       for b in sorted({s["owner"] for s in month_solos})},
            "recent": [
                {"job_id": s["id"], "by": s["owner"],
                 "reason": s["payload"].get("reason"), "scope": s["payload"].get("scope"),
                 "prj": s["payload"].get("prj"), "created_at": s["created_at"]}
                for s in solos[-5:][::-1]
            ],
        },
    })
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fbot-lead.py",
        description="fbot 팀장핀봇 판정 코어 (Issue436_3 s3) — 계약 fbot-arch.md §조직·§워크플로우 어댑터",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pending", help="펜딩 큐 뷰 — issue-map --json 파생(startable/blocked)")
    sp.add_argument("--cwd", default=os.getcwd(), help="대상 프로젝트 루트(기본 현재 디렉토리)")
    sp.set_defaults(func=cmd_pending)

    sp = sub.add_parser("dispatch", help="배분 요청 — 수요측 가드 → HR hire → 배분 기록")
    # Issue526 — 둘 중 하나는 필수(cmd_dispatch 가 검증). required=True 를 풀되
    #   argparse 상호배타 그룹은 쓰지 않는다 — 둘 다 준 경우 --issue 우선이 자연스럽고,
    #   그룹으로 막으면 스크립트가 두 값을 모두 넘기던 기존 호출이 깨진다.
    sp.add_argument("--issue", default=None, help="이슈 ID (ex: Issue12)")
    sp.add_argument("--topic", default=None,
                    help="이슈 없는 배분의 주제 (ex: '크로스 prj 시급도 조사'). --issue 와 둘 중 하나 필수")
    sp.add_argument("--role", required=True, help="워커 role (카탈로그 등재값 — HR 게이트가 검증)")
    sp.add_argument("--cwd", default=os.getcwd(), help="대상 프로젝트 루트(기본 현재 디렉토리)")
    sp.add_argument("--bot-id", default=None, help="워커 bot_id 지정(생략 시 fbot-{role}-{issue} 자동)")
    sp.add_argument("--dry-run", action="store_true", help="가드 판정까지만 — 채용·기록 없음")
    sp.add_argument("--by", default=BOT_ID,
                   help="배분자 bot_id (기본: 전역 팀장핀봇). prj PM 이 자기 이름으로 "
                        "배분하려면 지정 — 그래야 조직도에 총괄→PM→워커 체인이 그려진다")
    sp.set_defaults(func=cmd_dispatch)

    sp = sub.add_parser("watch", help="진행 감시 — 적체 2종 → 재시도 → 에스컬레이션(mq alert)")
    sp.add_argument("--cwd", default=None, help="지정 시 미배분 startable 적체(A)도 판정")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("sweep", help="완료 감지 — 워커 퇴근+세션 done 배분을 done 처리 + 묶음 통지 1회")
    sp.add_argument("--dry-run", action="store_true", help="감지까지만 — 갱신·통지 없음")
    sp.set_defaults(func=cmd_sweep)

    sp = sub.add_parser("close", help="외부 증적으로 확정된 완료를 원장에 반영(prj3#Issue514 — sweep 이 못 닫는 건)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 지정")
    g.add_argument("--issue", default=None, help="이슈 ID 로 지정")
    g.add_argument("--worker", default=None, help="워커 bot_id 로 지정")
    sp.add_argument("--evidence", required=True,
                    help="원장 밖 증적(필수) — 커밋 해시·리포트 경로·이슈 번호")
    sp.add_argument("--reason", default="", help="보충 설명(선택)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "human"), help="종결 주체(기본 $FBOT_ID)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 갱신 없음")
    sp.set_defaults(func=cmd_close)

    sp = sub.add_parser("cancel", help="배분 취소 — 무의미해진 배분을 사유와 함께 명시 종결(완료 아님)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 지정")
    g.add_argument("--issue", default=None, help="이슈 ID 로 지정 (ex: Issue329 — 동일 이슈 전건)")
    sp.add_argument("--reason", required=True, help="취소 사유(필수) — 근거 없는 원장 정리 금지")
    sp.add_argument("--verdict", default="cancelled_obsolete", help="판정 코드(기본 cancelled_obsolete)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "human"), help="취소 주체 bot_id(기본 $FBOT_ID)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 갱신 없음")
    sp.set_defaults(func=cmd_cancel)

    sp = sub.add_parser("solo", help="분업 우회 기록 — 자리 없는 일·긴급 건을 직접 수행하는 사유를 원장에 남긴다")
    sp.add_argument("--reason", required=True,
                    help="직접 수행 사유(필수·8자 이상) — 감사에서 읽히는 문장으로")
    sp.add_argument("--scope", default="", help="대상 요지(선택 — 어떤 작업을 직접 했는가)")
    sp.add_argument("--cwd", default=os.getcwd(), help="대상 프로젝트 루트(기본 현재 디렉토리)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "") or BOT_ID,
                    help="우회 주체 bot_id(기본 $FBOT_ID)")
    sp.set_defaults(func=cmd_solo)

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
