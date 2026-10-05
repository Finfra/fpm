#!/usr/bin/env python3
"""fbot-manual-review.py — 매뉴얼 개정 루프 (Issue436_3 s5 단계 4~7).

계약: ~/.claude/_doc_arch/fbot-arch.md §매뉴얼 체계(F5)·§작업 기록(F4)·ⓒ 판정(매뉴얼 정본=파일,
      DB=파생 조회층)·미해결 표 s5 확정행(개정 루프 = s0 worker tick 편입·주 1회·산출은 draft 까지).
      여기서 계약을 재결정하지 않는다 — 참조만 한다.

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

서브커맨드
  review  [--role R] [--dry-run]  개정 근거 추출 → 근거 있는 role 만 `{role}.md.draft` 생성
  propose                          생성된 draft 를 mq `[컨펌]` 으로 등록(사람 전결 요청)
  apply   --role R                 ACK 확인 후에만 draft → 정본 반영 + 이력 append + draft 삭제
  reject  --role R --reason "..."  draft 폐기 + 사유를 job 원장에 기록
  index   [--force]                매뉴얼 파일 → learn.db 파생 색인(mtime 기반 재색인)

왜 `.md.draft` 인가 (promote-instinct.py 선례 재사용)
  확장자가 `.md` 가 아니면 매뉴얼 로더(s1 출근 주입)가 집지 않는다 — 별도 플래그 없이 **비활성**이
  성립한다. 정본 반영은 사람이 승인한 뒤 `apply` 한 번이다.

하드 가드 (자동 수정 금지의 실체)
  * `review` 경로가 부를 수 있는 쓰기 함수는 `write_draft()` 하나뿐이고, 그 함수는 경로가
    `.md.draft` 로 끝나지 않으면 예외를 던진다. 정본 경로를 넘길 방법이 코드에 없다.
  * 정본을 쓰는 함수 `write_canonical()` 은 **mq ACK 레코드**를 인자로 요구하고, 없거나
    acked 가 아니면 예외다. `apply` 만 이 함수를 부른다.
  * ACK 는 **읽기 조회**만 한다 — 이 스크립트는 ack 를 발행하지 않는다(봇 auto-ack 금지, 계약).
"""

import argparse
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

# ── 경로 ─────────────────────────────────────────────────────────────────────

HOME = os.path.expanduser("~")
MANUAL_DIR = os.environ.get("FBOT_MANUAL_DIR") or os.path.join(HOME, ".claude", "data", "fbot", "manuals")
# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
AOA_DIR = os.environ.get("AOA_MEMORY_DIR") or os.path.join(HOME, ".claude", "data", "aoa")
REGISTRY_DB = os.path.join(AOA_DIR, "registry.db")
LEARN_DB = os.path.join(AOA_DIR, "learn.db")
MQ_DIR = os.environ.get("AOA_MQ_DIR") or os.path.join(HOME, ".claude", "data", "aoa", "mq")
MQ_ENQUEUE = os.path.join(HOME, ".claude", "mcp", "aoa-mq", "aoa-mq-enqueue.sh")

DRAFT_SUFFIX = ".md.draft"
AUTO_MARK = "<!-- fbot-manual-review:auto -->"   # 기계 생성 절 표식 (apply 시 이 절만 걷어낸다)
CONFIRM_MARK = "fbot 매뉴얼 개정안"               # mq `[컨펌]` 본문 매칭 토큰

# 파생 색인 네임스페이스 — 실제 instinct 와 **project_id 부터** 갈라 둔다(오염 금지).
INDEX_PROJECT_ID = "fbot-manual"
INDEX_SCOPE = "fbot/manual"
INDEX_ORIGIN = "fbot-manual-index"

# ── 판정 임계 (prj3#Issue503 — policy 이전) ────────────────────────────────
# 수치 SSOT 는 aoa policy.yml `fbot_review_*` 키. 아래 값은 **키 부재 시 폴백**(제품
# 중립 기본 — 미설치 머신 계약)이며, 있으면 policy 가 이긴다. 소수 키가 섞여 있어
# 정수 전용 파서를 쓰지 않고 float 허용 정규식으로 읽는다(판정 단일 지점 유지).
import re as _re

def _review_policy():
    # prj3#Issue626 — **정책 수치의 정본은 prj3** 다. 데이터(registry.db·learn.db)는 용량 때문에
    #   prj5 에 남지만(zshenv 명시 결정) 수치는 prj3 소관이다. 폴백 순서가 핵심이다:
    #   ⓐ `aoa_dir()` 에 있으면 그것 — **테스트가 픽스처에 쓴 policy 를 계속 읽는다**
    #   ⓑ 없으면 prj3. 운영에서는 prj5 사본을 걷었으므로 여기로 온다
    #   순서를 뒤집으면 테스트가 운영 policy 를 읽어 픽스처가 무력해진다.
    path = os.path.join(AOA_DIR, "policy.yml")
    if not os.path.exists(path):
        _p3 = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa", "policy.yml")
        if os.path.exists(_p3):
            path = _p3
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = _re.match(r"^(fbot_review_[a-z_]+):\s*([0-9.]+)", line)
            if m:
                v = m.group(2)
                out[m.group(1)] = float(v) if "." in v else int(v)
    return out

_RP = _review_policy()
MIN_EVENTS = _RP.get("fbot_review_min_events", 3)          # role 당 최소 표본. 미만이면 "판정 보류"
BLOCK_RATE_MIN = _RP.get("fbot_review_block_rate_min", 0.30)   # blocked/failed 비율
RETRY_RATE_MIN = _RP.get("fbot_review_retry_rate_min", 0.30)   # attempts >= 2 비율
IDLE_RATE_MIN = _RP.get("fbot_review_idle_rate_min", 0.50)     # 출근했는데 current_task 가 빈 세션 비율
MISMATCH_MIN = _RP.get("fbot_review_mismatch_min", 1)      # strict role 인데 hash 증적 없이 done 건수
OBS_FAIL_MIN = _RP.get("fbot_review_obs_fail_min", 3)      # 실패 키워드 동반 observation 건수
# 매뉴얼 크기 상한 (prj3#Issue601) — 계약 §F5 의 900자. **파일 전체** 기준이다:
#   fbot-checkin.sh 가 `cat "$MANUAL_DIR/$role.md"` 로 통째로 주입하므로 frontmatter 도
#   매 출근 비용에 그대로 실린다(실측). 본문만 재면 `revisions:` 가 길어질수록 과소평가된다.
MANUAL_MAX_CHARS = _RP.get("fbot_manual_max_chars", 900)

HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
OBS_FAIL_RE = re.compile(r"실패|오류|에러|반송|재시도|blocked|failed", re.I)
ACK_OK = ("confirmed", "acked_done")   # dismissed = 승인 아님(반려·무시) → 정본 반영 거부


class FbotError(Exception):
    """fail-loud 용 — 메시지를 stderr 에 내고 exit != 0."""


def die(msg):
    raise FbotError(msg)


def today():
    return datetime.now().strftime("%Y.%m.%d")


def _ts(epoch):
    """epoch → 사람이 읽는 시각. 0/None 은 '미기록'(기준선 부재와 0시를 구분한다)."""
    if not epoch:
        return "미기록"
    return datetime.fromtimestamp(int(epoch)).strftime("%Y.%m.%d %H:%M")


def connect(db):
    if not os.path.exists(db):
        die("DB 없음: %s (AOA_MEMORY_DIR 확인)" % db)
    c = sqlite3.connect(db, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=10000")
    return c


# ── 파일 I/O (쓰기 경로는 이 둘뿐이다) ───────────────────────────────────────

def _atomic_write(path, text):
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_draft(path, text):
    """draft 전용 쓰기. `.md.draft` 가 아니면 **예외** — review 경로의 유일한 쓰기 함수다."""
    if not path.endswith(DRAFT_SUFFIX):
        die("하드 가드 위반: draft 이외 경로 쓰기 시도 — %s" % path)
    _atomic_write(path, text)


def write_canonical(path, text, ack):
    """정본 쓰기. mq ACK 레코드가 없으면 **예외** — apply 만 부른다."""
    if not isinstance(ack, dict) or not ack.get("acked"):
        die("하드 가드 위반: ACK 레코드 없이 정본 쓰기 시도 — %s" % path)
    if not path.endswith(".md"):
        die("하드 가드 위반: 정본 경로가 아님 — %s" % path)
    # prj3#Issue601 — 상한 초과를 **악화시키는** 쓰기만 막는다.
    #   무조건 거부로 두면 이미 초과한 4종(chief·lead·crosscheck·consult)의 개정이
    #   영구 불가가 되어, 정작 줄이는 개정까지 함께 막힌다. 줄어드는 방향은 통과시킨다.
    n = len(text)
    if n > MANUAL_MAX_CHARS:
        cur = len(read_text(path)) if os.path.exists(path) else 0
        if n > max(cur, MANUAL_MAX_CHARS):
            die("매뉴얼 상한 초과 악화: %s — %d자 (상한 %d · 현재 %d). "
                "매 출근 주입 비용이라 늘리는 개정은 막는다. 줄이는 개정은 통과한다."
                % (path, n, MANUAL_MAX_CHARS, cur))
    _atomic_write(path, text)


def manual_path(role):
    return os.path.join(MANUAL_DIR, "%s.md" % role)


def draft_path(role):
    return os.path.join(MANUAL_DIR, "%s%s" % (role, DRAFT_SUFFIX))


def all_roles():
    if not os.path.isdir(MANUAL_DIR):
        die("매뉴얼 디렉토리 없음: %s" % MANUAL_DIR)
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(MANUAL_DIR, "*.md")))


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def parse_frontmatter(text):
    """`---` 로 감싼 평탄 frontmatter → (dict, 본문시작offset). PyYAML 무의존."""
    if not text.startswith("---\n"):
        return {}, 0
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, 0
    fm = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm, end + 5


# ── 관측 수집 (registry.job — bot_id 귀속 기록이 원천, 계약 F4) ────────────────

def role_of_bot_id(bot_id, botmap):
    if not bot_id:
        return None
    if bot_id in botmap:
        return botmap[bot_id]
    m = re.match(r"^fbot-([a-z0-9]+)", bot_id)   # 레코드가 지워진 봇도 이름 규약으로 귀속
    return m.group(1) if m else None


def collect_job_stats():
    """registry.job 의 fbot_* 기록을 role 별로 집계한다. 여기서 판정하지 않는다 — 세기만 한다."""
    c = connect(REGISTRY_DB)
    botmap = {r["bot_id"]: r["role"] for r in c.execute("SELECT bot_id, role FROM bot")}
    stats = {}

    def slot(role):
        return stats.setdefault(role, dict(
            dispatch_total=0, dispatch_blocked=0, dispatch_retry=0, dispatch_done=0,
            done_no_hash=0, session_total=0, session_idle=0))

    rows = c.execute(
        "SELECT kind, status, payload, result, attempts, owner FROM job "
        "WHERE kind IN ('fbot_dispatch','fbot_session')").fetchall()
    for r in rows:
        try:
            p = json.loads(r["payload"] or "{}")
        except Exception:
            p = {}
        if r["kind"] == "fbot_dispatch":
            role = p.get("role") or role_of_bot_id(p.get("worker_bot_id"), botmap)
            if not role:
                continue
            s = slot(role)
            s["dispatch_total"] += 1
            if (r["status"] or "") in ("blocked", "failed"):
                s["dispatch_blocked"] += 1
            if (r["attempts"] or 0) >= 2:
                s["dispatch_retry"] += 1
            if (r["status"] or "") == "done":
                s["dispatch_done"] += 1
                if not HASH_RE.search(r["result"] or ""):
                    s["done_no_hash"] += 1
        else:  # fbot_session
            role = role_of_bot_id(p.get("bot_id") or r["owner"], botmap)
            if not role:
                continue
            s = slot(role)
            s["session_total"] += 1
            if not (p.get("current_task") or "").strip():
                s["session_idle"] += 1
    c.close()
    return stats


def collect_obs_stats(roles):
    """learn.db observation 이 있으면 함께 본다 — 없으면 조용히 0 (색인 부재는 실패가 아니다)."""
    out = {r: 0 for r in roles}
    if not os.path.exists(LEARN_DB):
        return out
    try:
        c = connect(LEARN_DB)
        rows = c.execute("SELECT body FROM observation WHERE body LIKE '%fbot-%'").fetchall()
        c.close()
    except Exception as e:
        print("⚠️ observation 조회 생략: %s" % e, file=sys.stderr)
        return out
    for r in rows:
        body = r["body"] or ""
        if not OBS_FAIL_RE.search(body):
            continue
        for role in roles:
            if ("fbot-%s" % role) in body:
                out[role] += 1
    return out


# ── 판정 ─────────────────────────────────────────────────────────────────────

# drift 판정이 불가능했던 사유 — review 요약이 마지막에 이것을 낸다(침묵 금지)
DRIFT_UNAVAILABLE = []


def _recruit_mod():
    """fbot-scout.py 를 모듈로 로드한다 — origin 해소 로직의 **단일 지점**.

    prj3#Issue589 — 경로 해소(`agent:` → `~/.claude/agents/N.md`)를 여기에 복제하면
    카탈로그 문법이 바뀔 때 한쪽만 고쳐져 조용히 어긋난다. 카탈로그를 소유한 쪽에서 빌린다.
    """
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-scout.py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("_fbot_recruit_for_review", path)
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None


def origin_drift(role):
    """(origin, seen, cur) — 원본 내용 해시가 기준선과 다르면 drift. 아니면 None.

    🔴 **기준선은 `origin_seen` 이지 매뉴얼 mtime 이 아니다.** 매뉴얼 mtime 을 쓰면
      `reject` 가 그것을 갱신하지 않아(draft 만 지운다) 월요일 tick 이 **매주 같은 draft·
      같은 `[컨펌]` 을 재생성**한다 — prj3#Issue518 이 경계한 폭주 그대로다. 감쇠하는
      비율 신호(blocked_rate 등)와 달리 mtime 비교는 스스로 줄어들지 않기 때문이다.
    """
    r = _recruit_mod()
    if r is None:
        DRIFT_UNAVAILABLE.append("fbot-scout.py 로드 실패")
        return None
    try:
        roles = r.parse_catalog()
    except Exception as e:
        # fail-soft 는 유지하되 **침묵하지 않는다** (prj3#Issue589 자체 검토 m4) —
        #   카탈로그가 파손되면 drift 가 전 role 에서 사라지는데, 그것이 조용하면
        #   운영자는 "신호 없음 = 최신"으로 읽는다. touch_origin_seen 은 이미 경고를
        #   내므로 대칭을 맞춘다.
        DRIFT_UNAVAILABLE.append("카탈로그 읽기 실패: %s" % e)
        return None                     # 카탈로그 부재는 fail-soft — 다른 신호를 죽이지 않는다
    f = roles.get(role) or {}
    origin = f.get("origin")
    if not origin or origin == "native":
        return None                     # 원본이 없으면 drift 라는 개념이 성립하지 않는다
    cur = r.origin_digest(origin)
    if cur is None:
        return None                     # web: 출처 — 로컬에 원본이 없어 판정 불가(계약 §A)
    seen = f.get("origin_seen") or ""
    # 미기입(미대조)도 drift 다 — *"아직 아무도 원본과 대조하지 않았다"* 는 사실이
    #   침묵으로 사라지면 안 된다. apply·reject 가 대조 시점에 기준선을 잡는다.
    return (origin, seen, cur) if cur != seen else None


def evaluate(role, st, obs_fail, completion, drift=None, oversize=None):
    """관측 → 개정 근거 신호. **데이터로 관측 가능한 것만** 신호로 삼는다."""
    sig = []
    dt, se = st["dispatch_total"], st["session_total"]

    if dt >= MIN_EVENTS:
        rate = st["dispatch_blocked"] / dt
        if rate >= BLOCK_RATE_MIN:
            sig.append((
                "blocked_rate",
                "배분 %d건 중 blocked/failed %d건 (%.0f%% ≥ 임계 %.0f%%)"
                % (dt, st["dispatch_blocked"], rate * 100, BLOCK_RATE_MIN * 100),
                "「경계·금지」 절에 착수 전제 확인 항목(선행 이슈·cwd·권한)을 명시하고, "
                "전제 미충족 시 즉시 반송하는 절차를 「작업 절차」에 추가할 것을 제안한다."))
        rate = st["dispatch_retry"] / dt
        if rate >= RETRY_RATE_MIN:
            sig.append((
                "retry_rate",
                "배분 %d건 중 재시도(attempts≥2) %d건 (%.0f%% ≥ 임계 %.0f%%)"
                % (dt, st["dispatch_retry"], rate * 100, RETRY_RATE_MIN * 100),
                "재시도가 반복되는 지점을 「작업 절차」에 1회 실패 시 보고·에스컬레이션 규칙으로 "
                "명문화할 것을 제안한다(무한 재시도 금지)."))

    if completion == "strict" and st["dispatch_done"] >= MIN_EVENTS and st["done_no_hash"] >= MISMATCH_MIN:
        sig.append((
            "completion_mismatch",
            "완료 판정 유형 strict 인데 done %d건 중 hash 증적 없는 건 %d건"
            % (st["dispatch_done"], st["done_no_hash"]),
            "「완료 판정」 절의 증적 요건(✅+commit hash)을 실제 기록 형식과 일치시키거나, "
            "role 의 완료 판정 유형을 재검토할 것을 제안한다."))

    if se >= MIN_EVENTS:
        rate = st["session_idle"] / se
        if rate >= IDLE_RATE_MIN:
            sig.append((
                "idle_session_rate",
                "출근 %d건 중 current_task 공란 %d건 (%.0f%% ≥ 임계 %.0f%%)"
                % (se, st["session_idle"], rate * 100, IDLE_RATE_MIN * 100),
                "출근 직후 current_task 를 기록하도록 「작업 절차」에 첫 단계를 추가할 것을 "
                "제안한다(기록 없는 작업은 개선 루프에서 보이지 않는다 — 계약 F4)."))

    # 🔴 obs 의 교차 확인 재료는 **원장 파생 4신호뿐**이다 — 여기서 스냅샷을 뜬다.
    #   prj3#Issue589 자체 검토에서 잡은 결함: drift 를 `sig` 에 얹은 뒤 obs 게이트가
    #   `if ... and sig:` 를 보면 **drift 가 obs 의 잠금을 풀어버린다**. 그런데 둘은
    #   무관하다 — *"원본 파일이 바뀌었다"* 가 *"트랜스크립트에 실패가 언급됐다"* 를
    #   정당화하지 못한다. prj3#Issue522 가 세운 교차 확인의 뜻은 **원장 근거**였다.
    #   실측: igmaker 는 drift 도입 전 신호 0건이었는데 도입 후 obs 51건이 함께 붙었다.
    ledger_sig = list(sig)

    # prj3#Issue589 — origin_drift 는 **단독 트리거**다. obs 와 정반대 성격이라 다르게 다룬다:
    #   obs 는 트랜스크립트 전문 매칭이라 오탐이 섞이고 bot_id 귀속이 원리적으로 불가능한데,
    #   drift 는 **role 축의 결정론적 사실**(파일 mtime 비교)이라 귀속이 애초에 필요 없고
    #   오탐 여지가 없다. 기준선(`origin_seen`)이 apply·reject 양쪽에서 갱신되므로
    #   "봤는데 안 고치기로 했다" 가 표현돼 재발 폭주도 막힌다.
    # prj3#Issue601 — 크기 초과도 **단독 트리거**다. origin_drift 와 같은 성격
    #   (role 축의 결정론적 사실 · bot_id 귀속 불요 · 오탐 여지 0)이며, 원장 신호가
    #   0건이어도 비용은 매 출근 발생하므로 표본을 기다릴 이유가 없다.
    #   ⚠️ 단, obs 의 교차 확인 재료로는 **쓰지 않는다** — ledger_sig 스냅샷 뒤에 붙인다.
    if oversize:
        n, limit = oversize
        sig.append((
            "manual_oversize",
            "매뉴얼이 상한을 넘는다 — %d자 (상한 %d · 초과 %+d). "
            "fbot-checkin.sh 가 파일을 통째로 주입하므로 매 출근 비용이다"
            % (n, limit, n - limit),
            "절을 줄이거나 상세를 설계 문서로 옮길 것을 제안한다. 5절 구조(임무·작업 절차·"
            "워크플로우 어댑터·경계/금지·완료 판정)는 유지하고 각 절의 산문을 압축한다."))

    if drift:
        origin, seen, cur = drift
        sig.append((
            "origin_drift",
            "승격 원본이 기준선과 다르다 — origin=%s · origin_seen=%s · 원본 현재 %s"
            % (origin, seen or "미대조", cur),
            "원본이 바뀌었다. 「작업 절차」가 인용한 원본 절차와 현재 원본을 대조해 "
            "달라진 부분을 반영할 것을 제안한다. 반영하지 않기로 하면 `reject` 로 "
            "기준선만 갱신한다(다음 주 재발 방지)."))

    # prj3#Issue522 (2026-09-03) — obs 는 **단독 트리거가 될 수 없다.**
    #   learn.db observation 은 세션 트랜스크립트(`tool_complete` 이벤트)라 *"봇이 실패했다"* 와
    #   *"실패를 조사했다"* 를 구분하지 못한다. 실측: prj3#Issue517 리포트를 쓰는 동안 taskmgr 85건이
    #   "실패 언급"으로 쌓였고 그 표본 상위 3건이 전부 조사자의 Bash stdout 이었다.
    #   더 근본적으로 observation 에는 **bot_id 컬럼이 없다** — 계약 F4 가 요구하는 귀속이
    #   원리적으로 불가능한 데이터다. 위 4종은 전부 registry.job 파생이라 귀속이 성립한다.
    #   그래서 정보는 남기되(근거 표), **판정 권한은 주지 않는다**.
    if obs_fail >= OBS_FAIL_MIN and ledger_sig:
        sig.append((
            "obs_failure_mentions",
            "learn.db observation 중 본 role 봇을 실패 문맥으로 언급 %d건 (≥ 임계 %d) "
            "— ⚠️ 참고값: 트랜스크립트 전문 매칭이라 조사·논의도 함께 집계된다(prj3#Issue522)"
            % (obs_fail, OBS_FAIL_MIN),
            "반복 언급된 실패 문맥을 「경계·금지」 절의 금지 항목으로 승격할 것을 제안한다. "
            "⚠️ 이 신호만으로 개정하지 말 것 — 위 원장 신호와 교차 확인이 전제다."))
    return sig


def render_draft(role, base_text, signals, st, obs_fail):
    lines = [base_text.rstrip("\n"), "", "## 개정 제안 (%s)" % today(), "", AUTO_MARK, "",
             "> 기계 생성 초안이다. **정본이 아니다** — 사람이 검토·편집한 뒤 승인 게이트를 "
             "통과해야 반영된다(`propose` → `[컨펌]` ACK → `apply`).", "",
             "### 관측 근거", "",
             "| 지표 | 값 |", "| :--- | :--- |",
             "| 배분(fbot_dispatch) | 총 %d · blocked/failed %d · 재시도 %d · done %d(hash 없음 %d) |"
             % (st["dispatch_total"], st["dispatch_blocked"], st["dispatch_retry"],
                st["dispatch_done"], st["done_no_hash"]),
             "| 출근(fbot_session) | 총 %d · current_task 공란 %d |" % (st["session_total"], st["session_idle"]),
             "| observation 실패 언급 | %d |" % obs_fail,
             "", "### 제안", ""]
    for i, (key, detail, proposal) in enumerate(signals, 1):
        lines.append("%d. **%s** — %s" % (i, key, detail))
        lines.append("    - %s" % proposal)
    lines.append("")
    return "\n".join(lines)


# ── review ───────────────────────────────────────────────────────────────────

def cmd_review(args):
    roles = [args.role] if args.role else all_roles()
    for r in roles:
        if not os.path.exists(manual_path(r)):
            die("매뉴얼 없음: %s" % manual_path(r))
    stats = collect_job_stats()
    obs = collect_obs_stats(roles) if not args.no_obs else {r: 0 for r in roles}

    empty = dict(dispatch_total=0, dispatch_blocked=0, dispatch_retry=0, dispatch_done=0,
                 done_no_hash=0, session_total=0, session_idle=0)
    made, skipped = [], []
    for role in roles:
        st = stats.get(role, empty)
        text = read_text(manual_path(role))
        fm, _ = parse_frontmatter(text)
        n = len(text)
        sig = evaluate(role, st, obs.get(role, 0), fm.get("completion", ""),
                       drift=origin_drift(role),
                       oversize=(n, MANUAL_MAX_CHARS) if n > MANUAL_MAX_CHARS else None)
        if not sig:
            skipped.append((role, st))
            continue
        if args.dry_run:
            made.append((role, sig, True))
            continue
        write_draft(draft_path(role), render_draft(role, text, sig, st, obs.get(role, 0)))
        made.append((role, sig, False))

    if DRIFT_UNAVAILABLE:
        print("⚠️ origin_drift 판정 불가 — %s (신호 없음이 최신을 뜻하지 않는다)"
              % "; ".join(sorted(set(DRIFT_UNAVAILABLE))), file=sys.stderr)
    print("# fbot 매뉴얼 개정 후보 (%s)%s" % (today(), " [dry-run]" if args.dry_run else ""))
    print("* 대상 role %d종 · 매뉴얼 %s" % (len(roles), MANUAL_DIR))
    if not made:
        print("* **개정 근거 없음** — draft 를 만들지 않는다(빈 개정 금지).")
        for role, st in skipped:
            print("    - %s: 배분 %d(차단 %d·재시도 %d) · 출근 %d(공란 %d) → 임계 미달 또는 표본 부족(<%d)"
                  % (role, st["dispatch_total"], st["dispatch_blocked"], st["dispatch_retry"],
                     st["session_total"], st["session_idle"], MIN_EVENTS))
        return 0
    for role, sig, dry in made:
        print("* **%s** — 신호 %d건%s" % (role, len(sig), " (dry-run · 미생성)" if dry else " → %s" % draft_path(role)))
        for key, detail, _ in sig:
            print("    - %s: %s" % (key, detail))
    if skipped:
        print("* 근거 없음(draft 미생성): %s" % ", ".join(r for r, _ in skipped))
    if not args.dry_run:
        print("* 다음 단계: `fbot-manual-review.py propose` → `[컨펌]` ACK → `apply --role <R>`")
    return 0


# ── propose (mq `[컨펌]` 등록 — helper 경유. 큐 직접 Write 금지) ─────────────

def list_drafts():
    return sorted(glob.glob(os.path.join(MANUAL_DIR, "*" + DRAFT_SUFFIX)))


def pending_confirm(role):
    """`queue/`(미종결)에 같은 role 의 `[컨펌]` 이 이미 있으면 그 id 를 돌려준다.

    prj3#Issue518 — `propose` 를 tick 에 편입하면서 필요해졌다. 개정 루프는 **주 1회**
    도는데 draft 는 사람이 `apply`/`reject` 할 때까지 남는다. 중복 방지가 없으면 미결
    draft 1건이 매주 새 `[컨펌]` 을 낳아 큐가 같은 요청으로 채워진다 — 그렇게 되면
    사람이 통지를 끄고, 통지를 끄면 이 루프의 존재 이유가 사라진다.

    매칭 규칙은 `find_ack()` 와 **같다**(`"role: %s." % role` — 마침표까지 봐서 접두
    충돌을 막는다). 두 곳이 다른 규칙을 쓰면 한쪽만 갱신돼 갈라진다.
    """
    q = os.path.join(MQ_DIR, "queue")
    if not os.path.isdir(q):
        return None
    for f in sorted(glob.glob(os.path.join(q, "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        msg = d.get("message") or ""
        if CONFIRM_MARK in msg and ("role: %s." % role) in msg:
            return d.get("id") or os.path.basename(f)
    return None


def cmd_propose(args):
    drafts = list_drafts()
    if not drafts:
        print("draft 없음 — 먼저 `review` 를 실행한다. 등록할 컨펌이 없다.")
        return 0
    if not os.access(MQ_ENQUEUE, os.X_OK):
        die("mq helper 없음·실행 불가: %s (직접 큐 Write 금지 — helper 경유가 유일 경로)" % MQ_ENQUEUE)
    out, dup = [], []
    for d in drafts:
        role = os.path.basename(d)[:-len(DRAFT_SUFFIX)]
        already = pending_confirm(role)          # prj3#Issue518 — 주간 재등록 소음 차단
        if already:
            dup.append((role, already))
            continue
        msg = ("[컨펌] %s — role: %s. 개정 초안 %s 를 정본에 반영할지 사람 전결 요청. "
               "승인 시 `~/.claude/hooks/fbot-manual-review.py apply --role %s`, "
               "반려 시 `reject --role %s --reason \"…\"`. 정본은 승인 전까지 무변경."
               % (CONFIRM_MARK, role, d, role, role))
        cmd = [MQ_ENQUEUE, "--message", msg, "--due", "+0d", "--from-bot", "fbot-lead"]
        if args.dry_run:
            print("[dry-run] %s" % " ".join(cmd))
            continue
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            die("mq 등록 실패(role=%s): %s" % (role, (p.stderr or p.stdout).strip()))
        out.append((role, p.stdout.strip()))
    for role, res in out:
        print("* %s → %s" % (role, res))
    for role, mid in dup:
        print("* %s → 스킵(미종결 컨펌 이미 있음: %s)" % (role, mid))
    if out:
        print("* ⚠️ ACK 는 사람이 한다 — 봇 auto-ack 금지(계약). 승인 확인 후 `apply --role <R>`.")
    return 0


# ── ACK 조회 (읽기 전용 — 이 스크립트는 ack 를 발행하지 않는다) ───────────────

def find_ack(role):
    """queue_done 에서 해당 role 의 `[컨펌]` 승인 레코드를 **조회**한다. 없으면 None."""
    done = os.path.join(MQ_DIR, "queue_done")
    if not os.path.isdir(done):
        return None
    hit = None
    for f in sorted(glob.glob(os.path.join(done, "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        msg = d.get("message") or ""
        if CONFIRM_MARK not in msg or ("role: %s." % role) not in msg:   # 마침표까지 = 접두 충돌 방지(QA F4)
            continue
        if not d.get("acked"):
            continue
        if (d.get("status") or "") not in ACK_OK:
            continue
        note = (d.get("ack_note") or "")
        if re.search(r"반려|거부|reject", note, re.I):
            continue
        if hit is None or (d.get("ack_ts") or "") >= (hit.get("ack_ts") or ""):
            hit = d
    return hit


# ── job 원장 기록 (계약 F4 — 결정도 기록이다) ────────────────────────────────

def record_job(role, decision, detail):
    c = connect(REGISTRY_DB)
    now = int(time.time())
    jid = "fbotman-%d-%s" % (now, os.urandom(4).hex())
    c.execute("BEGIN IMMEDIATE")
    c.execute("INSERT INTO job(id, store, kind, status, payload, result, attempts, owner, "
              "lease_until, blocked_since, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (jid, None, "fbot_manual_review", "done",
               json.dumps({"role": role, "decision": decision}, ensure_ascii=False),
               json.dumps({"detail": detail}, ensure_ascii=False),
               0, "fbot-lead", None, None, now))
    c.commit()
    c.close()
    return jid


# ── apply / reject ───────────────────────────────────────────────────────────

def strip_auto_section(text):
    """기계 생성 「개정 제안」 절만 걷어낸다. 사람이 지웠거나 고쳤으면 손대지 않는다."""
    if AUTO_MARK not in text:
        return text
    idx = text.rfind("\n## 개정 제안 (")
    if idx < 0:
        return text
    return text[:idx].rstrip("\n") + "\n"


def append_revision(text, entry):
    """frontmatter 에 개정 이력을 append. 본문은 건드리지 않는다."""
    fm, body_start = parse_frontmatter(text)
    if not fm:
        die("frontmatter 없음 — 개정 이력을 붙일 자리가 없다")
    head_end = text.find("\n---\n", 4)
    head = text[:head_end]
    body = text[head_end:]
    item = ("  - date: %s\n    mq: %s\n    note: %s" % (entry["date"], entry["mq"], entry["note"]))
    if re.search(r"^revisions:\s*$", head, re.M):
        head = head.rstrip("\n") + "\n" + item
    else:
        head = head.rstrip("\n") + "\nrevisions:\n" + item
    return head + body


def touch_origin_seen(role):
    """drift 기준선을 현재 원본 **내용 해시**로 올린다 — apply·reject **양쪽**이 부른다.

    🔴 reject 도 갱신한다. *"봤고, 반영하지 않기로 했다"* 역시 기준선이 움직여야 하는
      사건이다. 갱신하지 않으면 draft 를 지워도 다음 주 review 가 같은 신호를 다시
      내고 `[컨펌]` 이 매주 재생성된다(prj3#Issue518 폭주). 사람이 통지를 끄면 루프
      자체의 존재 이유가 사라진다.
    """
    r = _recruit_mod()
    if r is None:
        return None
    try:
        f = (r.parse_catalog().get(role) or {})
        origin = f.get("origin")
        if not origin or origin == "native":
            return None
        cur = r.origin_digest(origin)
        if cur is None:
            return None                 # web: 출처 — 올릴 기준선이 없다
        r.set_field(r.CATALOG_PATH, role, "origin_seen", cur)
        return cur
    except Exception as e:              # 기준선 갱신 실패가 본 명령을 되돌리지는 않는다
        print("⚠️ origin_seen 갱신 실패(%s): %s — 다음 review 에서 같은 신호가 재발한다"
              % (role, e), file=sys.stderr)
        return None


def cmd_apply(args):
    role = args.role
    d, m = draft_path(role), manual_path(role)
    if not os.path.exists(d):
        die("draft 없음: %s (먼저 `review`)" % d)
    if not os.path.exists(m):
        die("정본 없음: %s" % m)
    ack = find_ack(role)
    if not ack:
        die("승인 미확인 — role=%s 의 `[컨펌]` ACK 레코드가 %s/queue_done 에 없다.\n"
            "   `propose` 로 등록한 뒤 **사람이** ACK 해야 반영된다(봇 auto-ack 금지). 정본 무변경."
            % (role, MQ_DIR))
    new = strip_auto_section(read_text(d))
    new = append_revision(new, {"date": today(), "mq": ack.get("id") or "?",
                                "note": (ack.get("ack_note") or "승인 반영").replace("\n", " ")[:120]})
    write_canonical(m, new, ack)
    os.remove(d)
    jid = record_job(role, "applied", "mq=%s ack_ts=%s" % (ack.get("id"), ack.get("ack_ts")))
    seen = touch_origin_seen(role)
    print("✅ %s 정본 반영 (승인 %s · %s) · draft 삭제 · job 원장 %s%s"
          % (role, ack.get("id"), ack.get("ack_ts"), jid,
             (" · origin_seen→%s" % seen) if seen else ""))
    return 0


def cmd_reject(args):
    role = args.role
    d = draft_path(role)
    if not os.path.exists(d):
        die("draft 없음: %s" % d)
    os.remove(d)
    jid = record_job(role, "rejected", args.reason)
    seen = touch_origin_seen(role)
    print("🚫 %s draft 폐기 · 사유 job 원장 기록 %s: %s%s"
          % (role, jid, args.reason,
             (" · origin_seen→%s (재발 방지)" % seen) if seen else ""))
    return 0


# ── index (단계 4 — 파일 정본 → DB 파생 조회층) ───────────────────────────────

def cmd_index(args):
    if not os.path.exists(LEARN_DB):
        die("learn.db 없음: %s" % LEARN_DB)
    roles = [args.role] if args.role else all_roles()
    c = connect(LEARN_DB)
    now = int(time.time())
    rows = []
    c.execute("BEGIN IMMEDIATE")
    for role in roles:
        p = manual_path(role)
        mtime = int(os.path.getmtime(p))
        cur = c.execute("SELECT source_mtime FROM instinct WHERE project_id=? AND instinct_id=?",
                        (INDEX_PROJECT_ID, "manual-%s" % role)).fetchone()
        if cur and cur["source_mtime"] == mtime and not args.force:
            rows.append((role, "skip(최신)", mtime))
            continue
        text = read_text(p)
        fm, _ = parse_frontmatter(text)
        title = "fbot 매뉴얼: %s (%s)" % (fm.get("title") or role, role)
        trigger = "role=%s 출근 주입·개정 루프. 완료 판정 유형 %s" % (role, fm.get("completion") or "?")
        # 정본은 파일이다 — DB 는 파생이므로 파일 내용을 그대로 싣고 불일치 시 파일이 이긴다.
        c.execute(
            "INSERT INTO instinct(project_id, instinct_id, title, trigger, confidence, domain, "
            "scope, origin, occurrences, body, source_path, source_mtime, ingested_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(project_id, instinct_id) DO UPDATE SET "
            "title=excluded.title, trigger=excluded.trigger, domain=excluded.domain, "
            "scope=excluded.scope, origin=excluded.origin, body=excluded.body, "
            "source_path=excluded.source_path, source_mtime=excluded.source_mtime, "
            "ingested_at=excluded.ingested_at",
            (INDEX_PROJECT_ID, "manual-%s" % role, title, trigger, None, "fbot",
             INDEX_SCOPE, INDEX_ORIGIN, None, text, p, mtime, now))
        c.execute("DELETE FROM instinct_fts WHERE project_id=? AND instinct_id=?",
                  (INDEX_PROJECT_ID, "manual-%s" % role))
        c.execute("INSERT INTO instinct_fts(project_id, instinct_id, title, trigger, body) "
                  "VALUES(?,?,?,?,?)", (INDEX_PROJECT_ID, "manual-%s" % role, title, trigger, text))
        rows.append((role, "upsert", mtime))
    c.commit()
    c.close()
    print("# 매뉴얼 파생 색인 (project_id=%s · scope=%s · origin=%s)" % (INDEX_PROJECT_ID, INDEX_SCOPE, INDEX_ORIGIN))
    for role, act, mtime in rows:
        print("* %-10s %-12s mtime=%d" % (role, act, mtime))
    print("* 정본은 파일이다 — 불일치 시 파일 우선(재실행으로 DB 를 맞춘다).")
    return 0


# ── entry ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="fbot 매뉴얼 개정 루프 (Issue436_3 s5)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("review", help="개정 근거 추출 → 근거 있는 role 만 draft 생성")
    p.add_argument("--role"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-obs", action="store_true", help="learn.db observation 조회 생략")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("propose", help="draft 목록을 mq `[컨펌]` 으로 등록")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_propose)

    p = sub.add_parser("apply", help="승인(ACK) 확인 후 draft → 정본 반영")
    p.add_argument("--role", required=True); p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("reject", help="draft 폐기 + 사유 기록")
    p.add_argument("--role", required=True); p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_reject)

    p = sub.add_parser("index", help="매뉴얼 파일 → learn.db 파생 색인")
    p.add_argument("--role"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_index)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except FbotError as e:
        print("❌ %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
