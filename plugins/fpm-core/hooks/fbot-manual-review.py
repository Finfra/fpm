#!/usr/bin/env python3
"""fbot-manual-review.py — 매뉴얼 개정 루프 (Issue436_3 s5 단계 4~7).

계약: ~/.claude/_doc_arch/fbot-arch.md §매뉴얼 체계(F5)·§작업 기록(F4)·ⓒ 판정(매뉴얼 정본=파일,
      DB=파생 조회층)·미해결 표 s5 확정행(개정 루프 = s0 worker tick 편입·주 1회·산출은 draft 까지).
      여기서 계약을 재결정하지 않는다 — 참조만 한다.

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

서브커맨드
  review  [--role R] [--dry-run]  개정 근거 추출 → 근거 있는 role 만 `{role}.md.draft` 생성
  propose                          생성된 draft 를 **본사 팀장 인박스**로 — 매뉴얼핀봇 본문 배분 요청(prj3#Issue757 T12).
                                   권한 경계 role 도 같다(본문 선행 — prj3#Issue757_1). mq 직행 없음
  mark    --role R --by <매뉴얼핀봇>  본문을 고친 뒤 작성 표지(본문 해시)
  submit  --role R --by <본사 팀장>   표지 있는 draft 를 총괄 인박스로 상신 — 일반 role 은 C 결정 요청,
                                   권한 경계 role 은 «사람에게 올리라» 요청(H `방침`)
          [--decline --reason "..."]  배분하지 않기로 한 draft 의 **반려 상신** — 작성 표지 불요(prj3#Issue946).
                                   형식은 같은 `role: X.` 결정 요청이라 총괄 `reject --by` 가 그대로 근거를 찾는다.
                                   `--reason` 은 `--decline` 전용 — 일반 상신에 붙으면 거부
  needs-human --role R [--by <총괄>]  권한 경계 draft 를 mq `[컨펌] [H:방침]` 으로 사람에게 — 총괄(표지·상신 필수) 또는
                                   결속 없는 사람 세션 직접(`--by` 없음·표지 불요, prj3#Issue773·954). 반영은 사람 ACK 뒤 `apply`
  apply   --role R [--by B --reason "..."]  승인 확인 후에만 draft → 정본 반영 + 이력 append + draft 삭제
                                   승인 = 총괄(role=chief) `--by` 전결(일반 role) **또는** mq ACK(권한 경계 role)
  reject  --role R --reason "..." [--by B] [--return]  반려 — 결정 기록·요청 종결 공유, 모드 둘(prj3#Issue946·948):
                                   삭제(기본) draft 폐기 + origin_seen 갱신 · 반송(`--return`) draft 보존·작성 표지 제거·
                                   사유 머리 첨부·origin_seen 불변 → 본사 팀장 재배분 요청(적재 실패 시 exit 2).
                                   `--by` 없음은 결속 없는 사람 세션만(Issue830 판정 — FBOT_ID·결속·하청 슬롯 거부)
  index   [--force]                매뉴얼 파일 → learn.db 파생 색인(mtime 기반 재색인)
  inject  --role R | --file P      출근 주입본 출력 — frontmatter `revisions:` 제외(prj3#Issue767, 상한도 이 값)

왜 `.md.draft` 인가 (promote-instinct.py 선례 재사용)
  확장자가 `.md` 가 아니면 매뉴얼 로더(s1 출근 주입)가 집지 않는다 — 별도 플래그 없이 **비활성**이
  성립한다. 정본 반영은 사람이 승인한 뒤 `apply` 한 번이다.

하드 가드 (자동 수정 금지의 실체)
  * `review` 경로가 부를 수 있는 쓰기 함수는 `write_draft()` 하나뿐이고, 그 함수는 경로가
    `.md.draft` 로 끝나지 않으면 예외를 던진다. 정본 경로를 넘길 방법이 코드에 없다.
  * 정본을 쓰는 함수 `write_canonical()` 은 **mq ACK 레코드**를 인자로 요구하고, 없거나
    acked 가 아니면 예외다. `apply` 만 이 함수를 부른다.
  * ACK 는 **읽기 조회**만 한다 — 이 스크립트는 ack 를 발행하지 않는다(봇 auto-ack 금지, 계약).
  * prj3#Issue756 — 매뉴얼 개정은 결정 권한 **C 등급**(총괄 전결)이다(`_doc_arch/decision-authority.md`).
    과거 사람 승인 10건이 전부 승인·반려 0 이었다 — 사람 게이트가 도장이었다. 하드 가드는 그대로 두고
    **승인 주체만** 바꾼다: `apply --by` 는 레지스트리 role=chief 개체만 통과하고, 그 결정을
    `fbot_event`(type=decision) 로 남긴 뒤에야 승인 레코드가 생긴다 — 기록 없는 반영 경로는 없다.
"""

import argparse
import glob
import hashlib
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
INBOX_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-inbox.py")
CHIEF_ROLE = "chief"   # prj3#Issue756 — 매뉴얼 개정(C 등급) 전결자
LEAD_ROLE = "lead"     # prj3#Issue757 T12 — 본사 팀장(prj 없음)이 매뉴얼핀봇에 본문 작성을 배분하고 총괄에 상신한다
MANUAL_ROLE = "manual" # prj3#Issue757 T12 — 개정 **본문**을 쓰는 손. 총괄은 일을 하지 않으므로 결정만 한다
# 작성 표지 — 매뉴얼핀봇이 `mark` 로 남긴다. sha 는 표지를 뺀 draft 의 내용 해시: 표지 뒤에 누가 고치면 어긋난다
AUTHOR_RE = re.compile(r"^<!-- fbot-manual-review:author=(\S+) sha=([0-9a-f]{16}) -->\n?", re.M)
# 권한 경계를 정하는 매뉴얼 — 총괄 전결(C) 대상이 아니다. 이 매뉴얼의 «경계·금지» 가 곧 권한표의 집행
#   문구라, C 로 고치면 봇이 자기 권한을 넓힌다(권한표 변경 = H `방침`). 사람 mq ACK 경로만 남긴다.
AUTHORITY_ROLES = ("chief", "lead", "hr", "scout")

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
# prj3#Issue850 — homunculus **귀속** 관찰(레코드 `fbot_id`, Issue757_3 표지). 비귀속 obs 와 달리 단독 트리거.
HOBS_MIN_EVENTS = _RP.get("fbot_review_hobs_min_events", 20)           # role 당 귀속 관찰 최소 표본
HOBS_ERROR_RATE_MIN = _RP.get("fbot_review_hobs_error_rate_min", 0.30)  # 귀속 관찰 중 오류 비율 임계
# prj3#Issue943 — 원장 4신호 집계 창(일). 0 이면 일수 창을 끈다(role 기준선만 — 기준선도 없으면 전 기간). 음수는
#   `_review_policy` 파서(`[0-9.]+`)가 읽지 않아 기본 14 가 된다. 창 시작 = max(지금 − N일, role 기준선 — 최근 apply·reject).
#   전 기간 누적이면 이미 고친 배선 결함(prj3#Issue759 이전 공란 세션)이 매주 개정 신호로 되살아난다
WINDOW_DAYS = int(_RP.get("fbot_review_window_days", 14))
# 매뉴얼 크기 상한 (prj3#Issue601) — 계약 §F5 의 900자. **출근 주입본** 기준이다(prj3#Issue767):
#   주입본 = 파일 − frontmatter `revisions:` (`injected_text`). 종전엔 출근 훅이 파일을 통째 `cat` 해
#   «파일 전체» 로 쟀고, apply 마다 이력 ~100자가 붙어 다음 개정이 상한에 막혔다(Issue765 우회).
#   이력은 매 출근에 필요 없다 — 파일에는 남기고(사람·git 용) 주입과 상한에서만 뺀다.
MANUAL_MAX_CHARS = _RP.get("fbot_manual_max_chars", 900)
# prj3#Issue856_1 — draft «관련 학습» 참고 절 상한(정리 산출 소비 경로, homunculus-registry.md)
LEARN_REF_LIMIT = _RP.get("fbot_review_learn_ref_limit", 5)
LEARN_REF_ORIGINS = ("session-observation", "consolidation")   # fbot-manual-index 는 자기 색인 → 순환이라 제외

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
    check_cap(path, text)
    _atomic_write(path, text)


def check_cap(path, text):
    """prj3#Issue601 — 상한 초과를 **악화시키는** 쓰기만 막는다.

    무조건 거부로 두면 이미 초과한 4종(chief·lead·crosscheck·consult)의 개정이
    영구 불가가 되어, 정작 줄이는 개정까지 함께 막힌다. 줄어드는 방향은 통과시킨다.
    분리 이유(prj3#Issue756): 전결 기록 **전에** 같은 판정을 돌려, 쓰기가 실패할 반영을 기록하지 않는다.
    prj3#Issue767 — 새 글·현재 글 모두 **주입본**(`injected_text`)으로 잰다. 이력 append 는 상한을 먹지 않는다."""
    n = len(injected_text(text))
    if n > MANUAL_MAX_CHARS:
        cur = len(injected_text(read_text(path))) if os.path.exists(path) else 0
        if n > max(cur, MANUAL_MAX_CHARS):
            die("매뉴얼 상한 초과 악화: %s — %d자 (상한 %d · 현재 %d). "
                "매 출근 주입 비용이라 늘리는 개정은 막는다. 줄이는 개정은 통과한다."
                % (path, n, MANUAL_MAX_CHARS, cur))


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


def injected_text(text):
    """출근 주입본 — frontmatter 의 `revisions:` 블록만 뺀 글 (prj3#Issue767). **판정 단일 지점**이다:
    출근 훅(`fbot-checkin.sh` → `inject`)·상한(`check_cap`)·review 의 oversize 가 모두 이 함수를 읽는다.
    둘로 갈리면 Issue601 처럼 «훅이 무엇을 싣나» 와 «상한이 무엇을 재나» 가 다시 어긋난다.
    블록 = `revisions:` 줄 + 뒤따르는 들여쓴 줄·`-` 줄·빈 줄. 그 밖은 바이트 그대로 둔다."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    out, skip = [], False
    for ln in text[4:end].split("\n"):
        if re.match(r"^revisions:", ln):
            skip = True
            continue
        if skip and (ln[:1] in (" ", "\t", "-") or not ln.strip()):
            continue
        skip = False
        out.append(ln)
    return "---\n" + "\n".join(out) + text[end:]


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


LEDGER_BASELINE_DECISIONS = ("applied", "rejected")   # 결정이 끝난 것만 — 반송·표지·상신은 기준선이 아니다


def ledger_baselines(c):
    """role → 최근 apply·reject 시각(epoch) — 원장 집계 창의 role 기준선 (prj3#Issue943).

    `origin_seen` 을 apply·reject 가 올리는 것과 같은 뜻이다: *"봤고, 정했다"* 이전 기록은 그 결정에 이미 반영됐다.
    반송(returned)은 결정이 끝나지 않았으므로 옮기지 않는다(draft 가 남아 다시 올라온다 — prj3#Issue948)."""
    marks = ",".join("?" * len(LEDGER_BASELINE_DECISIONS))
    out = {}
    for r in c.execute("SELECT json_extract(payload,'$.role') AS role, MAX(COALESCE(created_at,0)) AS ts FROM job "
                       "WHERE kind='fbot_manual_review' AND json_extract(payload,'$.decision') IN (%s) "
                       "GROUP BY json_extract(payload,'$.role')" % marks, LEDGER_BASELINE_DECISIONS):
        if r["role"]:
            out[r["role"]] = int(r["ts"] or 0)
    return out


def window_since(role, baselines, now):
    """집계 시작 시각 — max(지금 − WINDOW_DAYS 일, role 기준선). **창 판정 단일 지점**(집계·draft 표·요약이 같이 읽는다)."""
    floor = now - WINDOW_DAYS * 86400 if WINDOW_DAYS > 0 else 0
    return max(floor, baselines.get(role, 0))


def _obs_window(now):
    """관찰 신호 집계 창 재료 — (now, 전역 하한, role 기준선). 원장 집계와 같은 `window_since` 로 role 별 시작을 정한다
    (prj3#Issue954 — 창 판정 단일 지점). registry 를 못 읽으면 기준선 없이 일수 창만(stderr 1줄 — 조용히 넓히지 않는다)."""
    now = int(now or time.time())
    floor = now - WINDOW_DAYS * 86400 if WINDOW_DAYS > 0 else 0
    base = {}
    try:
        if os.path.exists(REGISTRY_DB):
            c = connect(REGISTRY_DB)
            base = ledger_baselines(c)
            c.close()
    except Exception as e:
        print("⚠️ role 기준선 조회 생략(일수 창만): %s" % e, file=sys.stderr)
    return now, floor, base


def collect_job_stats(roles=None, now=None):
    """registry.job 의 fbot_* 기록을 role 별로 집계한다. 여기서 판정하지 않는다 — 세기만 한다.

    prj3#Issue943 — **창 안 기록만** 센다(`window_since`). MIN_EVENTS 판정도 창 안 건수로 된다. `since` 는 role 별
    집계 시작 시각(draft 근거 표가 싣는다). `roles` 를 주면 기록이 0건인 role 도 슬롯(과 `since`)을 갖는다."""
    now = int(now or time.time())
    c = connect(REGISTRY_DB)
    botmap = {r["bot_id"]: r["role"] for r in c.execute("SELECT bot_id, role FROM bot")}
    base = ledger_baselines(c)
    stats = {}

    def slot(role):
        return stats.setdefault(role, dict(
            dispatch_total=0, dispatch_blocked=0, dispatch_retry=0, dispatch_done=0,
            done_no_hash=0, session_total=0, session_idle=0, since=window_since(role, base, now)))

    for role in roles or ():
        slot(role)
    floor = now - WINDOW_DAYS * 86400 if WINDOW_DAYS > 0 else 0
    rows = c.execute(
        "SELECT kind, status, payload, result, attempts, owner, COALESCE(created_at,0) AS ts FROM job "
        "WHERE kind IN ('fbot_dispatch','fbot_session') AND COALESCE(created_at,0) >= ?", (floor,)).fetchall()
    # prj3#Issue929 — blocked(unconfirmed) 는 «워커가 퇴근했는데 산출 증적이 없다» 는 sweep 판정이지 수행 막힘이 아니다.
    #   blocked_rate(매뉴얼 개정 신호)에 넣으면 보고 없이 끝낸 조회·검토 배분이 «그 role 매뉴얼이 막힌다» 로 읽힌다.
    #   어휘는 fbot-state `UNCONFIRMED` 정본(fbot-inbox·fbot-lead 와 같은 값)
    unconfirmed = _state("blocked_rate 집계(«완료 미확인» 제외)").UNCONFIRMED
    for r in rows:
        try:
            p = json.loads(r["payload"] or "{}")
        except Exception:
            p = {}
        if r["kind"] == "fbot_dispatch":
            role = p.get("role") or role_of_bot_id(p.get("worker_bot_id"), botmap)
            if not role or r["ts"] < window_since(role, base, now):
                continue
            s = slot(role)
            s["dispatch_total"] += 1
            if (r["status"] or "") in ("blocked", "failed") and not (
                    r["status"] == "blocked" and p.get("blocked_by") == unconfirmed):
                s["dispatch_blocked"] += 1
            if (r["attempts"] or 0) >= 2:
                s["dispatch_retry"] += 1
            if (r["status"] or "") == "done":
                s["dispatch_done"] += 1
                if not HASH_RE.search(r["result"] or ""):
                    s["done_no_hash"] += 1
        else:  # fbot_session
            role = role_of_bot_id(p.get("bot_id") or r["owner"], botmap)
            if not role or r["ts"] < window_since(role, base, now):
                continue
            s = slot(role)
            s["session_total"] += 1
            if not (p.get("current_task") or "").strip():
                s["session_idle"] += 1
    c.close()
    return stats


def collect_obs_stats(roles, now=None):
    """learn.db observation 이 있으면 함께 본다 — 없으면 조용히 0 (색인 부재는 실패가 아니다).

    prj3#Issue954 — 원장 신호와 **같은 창**(`window_since`)만 센다. 시각 컬럼은 `observed_at`(epoch 초 — 미상 NULL 은
    구간 밖). 조회 실패는 stderr 로 알린다(컬럼명이 틀려도 운영에서 조용히 0 이 되던 함정)."""
    out = {r: 0 for r in roles}
    if not os.path.exists(LEARN_DB):
        return out
    now, floor, base = _obs_window(now)
    try:
        c = connect(LEARN_DB)
        rows = c.execute("SELECT body, observed_at AS ts FROM observation WHERE body LIKE '%fbot-%' "
                         "AND observed_at >= ?", (floor,)).fetchall()
        c.close()
    except Exception as e:
        print("⚠️ observation 조회 생략: %s" % e, file=sys.stderr)
        return out
    shadow_items = []
    for r in rows:
        body = r["body"] or ""
        if not OBS_FAIL_RE.search(body):
            continue
        hit = False
        for role in roles:
            if r["ts"] >= window_since(role, base, now) and bot_id_mentioned(body, role):
                out[role] += 1
                hit = True
        if hit:
            shadow_items.append({"text": body[:600],
                                 "cache_key": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]})
    _obs_failure_shadow(shadow_items)
    return out


def _obs_failure_shadow(items):
    """prj3#Issue863_17 — 정규식이 «실패» 로 센 비귀속 obs 를 Jev 로 다시 본다(shadow — 집계는 정규식 그대로).
    «조사 ≠ 실패»(Issue850 `_hobs_is_error` 가 귀속 경로에서만 고친 문제)를 비귀속 경로에서 재는 재료다.
    배치 1건·본문 해시 캐시(같은 obs 는 다시 묻지 않는다)·분리 기동. 마스킹·절단은 selection 이 한다."""
    if not items:
        return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_mr_selection", os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "selection.py"))
        sel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sel)
        sel.spawn_shadow_batch("obs.failure", items, static="yes")
    except Exception as e:
        print("⚠️ obs Jev shadow 생략: %s" % e, file=sys.stderr)


def _hobs_is_error(rec):
    """도구 응답의 **오류 표지**만 오류로 본다 — stderr 비공백 · interrupted · is_error.

    stdout 의 «실패»·«오류» 문구는 세지 않는다 — 봇이 테스트를 돌려 «3 failed» 를 읽은 것은 봇의 실패가
    아니라 봇의 일이다(prj3#Issue522 가 비귀속 obs 에서 겪은 «조사 ≠ 실패» 를 귀속 신호에서도 지킨다)."""
    out = rec.get("output")
    if isinstance(out, str):
        try:
            out = json.loads(out)
        except ValueError:
            return False
    if not isinstance(out, dict):
        return False
    if out.get("is_error") is True or out.get("interrupted") is True:
        return True
    return bool((out.get("stderr") or "").strip())


def collect_hobs_stats(roles, now=None):
    """homunculus 귀속 관찰 — learn.db observation 중 `fbot_id` 표지 레코드를 role 별로 센다 (prj3#Issue850).

    귀속 = 레코드 `fbot_id` → registry bot.role → 없으면 이름 규약(`fbot-<role>-…`). **언급은 귀속이 아니다** —
    비봇 세션이 fbot-lead 를 조사한 레코드는 어느 role 에도 들지 않는다. 그래서 이 신호는 Issue522 의
    자기참조 오염이 원리적으로 없고, 계약 F4(bot_id 귀속)를 만족해 단독 트리거가 된다.
    없으면 조용히 0 (색인 부재는 실패가 아니다).

    prj3#Issue954 — 원장 신호와 **같은 창**만 센다(`window_since`: 전역 하한 + role 기준선). reject 가 이 신호의
    기준선을 옮기지 못하면 단독 트리거 `homunculus_error_rate` 가 같은 레코드로 다음 주 재발화한다."""
    out = {r: {"total": 0, "error": 0, "bots": 0} for r in roles}
    if not os.path.exists(LEARN_DB):
        return out
    now, floor, base = _obs_window(now)
    botmap = {}
    try:
        if os.path.exists(REGISTRY_DB):
            c = connect(REGISTRY_DB)
            botmap = {r["bot_id"]: r["role"] for r in c.execute("SELECT bot_id, role FROM bot")}
            c.close()
    except Exception as e:
        print("⚠️ registry bot 조회 생략(이름 규약 귀속만): %s" % e, file=sys.stderr)
    try:
        c = connect(LEARN_DB)
        rows = c.execute("SELECT body, observed_at AS ts FROM observation WHERE body LIKE '%\"fbot_id\"%' "
                         "AND observed_at >= ?", (floor,)).fetchall()
        c.close()
    except Exception as e:
        print("⚠️ 귀속 observation 조회 생략: %s" % e, file=sys.stderr)
        return out
    bots = {r: set() for r in roles}
    for r in rows:
        try:
            rec = json.loads(r["body"] or "")
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        fid = rec.get("fbot_id")
        role = role_of_bot_id(fid, botmap) if isinstance(fid, str) else None
        if role not in out or r["ts"] < window_since(role, base, now):
            continue
        out[role]["total"] += 1
        bots[role].add(fid)
        if _hobs_is_error(rec):
            out[role]["error"] += 1
    for role in roles:
        out[role]["bots"] = len(bots[role])
    return out


_BOT_ID_MENTION_RES = {}


def bot_id_mentioned(body, role):
    """Issue834 — 실제 ``fbot-<role>[-…]`` id 경계만 찾고 ``*.py`` 파일명은 제외한다."""
    pat = _BOT_ID_MENTION_RES.get(role)
    if pat is None:
        pat = re.compile(r"(?<![A-Za-z0-9_.:-])fbot-%s(?:-[A-Za-z0-9_:-]+)*(?![A-Za-z0-9_:-])(?!\.py\b)"
                         % re.escape(role))
        _BOT_ID_MENTION_RES[role] = pat
    return pat.search(body or "") is not None


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


_STATE_MOD = None


def _state(what):
    """fbot-state 모듈(한 번만 적재) — 실패는 fail-loud(`what` = 그것으로 하려던 판정). 사본 폴백을 두지 않는다."""
    global _STATE_MOD
    if _STATE_MOD is None:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-state.py")
        spec = importlib.util.spec_from_file_location("_fbot_state_for_manual_review", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            _STATE_MOD = mod
        except Exception as e:
            die("fbot-state.py 적재 실패 — %s 불가: %s" % (what, e))
    return _STATE_MOD


def _human_session_rejection():
    """Issue830 — solo-approve 와 같은 fbot-state 사람 세션 판정을 재사용한다."""
    st = _state("사람 세션 판정")
    try:
        return st.human_session_rejection()
    except st.FbotError as e:
        die(str(e))


def _ident():
    """봇 신원 대조 판정 단일 지점(hooks/lib/fbot-ident.py, prj3#Issue832) — `FBOT_ID == --by` 를 복제하지 않는다."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_fbot_ident_review", os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "fbot-ident.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def role_kind(role):
    """카탈로그 `kind` — `tool`(도구 래핑) 또는 `bot`(기본, 봇이 수행하는 공정).

    🔑 **이 루프의 «신호 기대» 가 여기서 갈린다** (prj3#Issue636). 원장 4신호(배분·
      출근·done·observation)는 전부 *봇이 일한 흔적*이라, 도구로 재분류된 role 에서는
      0 인 것이 **정상**이다. 분기가 없으면 같은 0 이 «표본 부족(방치)» 으로 읽히고,
      운영자는 배선 결함을 계속 의심하게 된다 — 승격 3종이 전건 0 이던 기간이 그랬다.

    prj3#Issue943 — 도구 role 은 원장 4신호(와 봇 귀속 관찰)를 **판정하지 않는다**(`evaluate` `kind`).
      종전(prj3#Issue636)은 «분기하는 것은 0 을 읽는 방법이지 판정이 아니다» 로 신호를 살려 두었는데,
      draft 표가 «기대 신호는 origin_drift·manual_oversize 뿐» 이라 적은 채 crosscheck 에 원장 신호
      개정안이 반복됐다(자기모순). 봇 신호가 필요할 만큼 봇으로 일하면 `kind=bot` 으로 재분류한다
      (consult 선례 — `fbot-scout.py set-kind`).

    fail-soft — 카탈로그를 못 읽으면 `bot`(기본). 기본이 `tool` 이면 카탈로그 파손이
      전 role 의 원장 신호를 «정상» 으로 덮어버린다.
    """
    r = _recruit_mod()
    if r is None:
        return "bot"
    try:
        f = r.parse_catalog().get(role) or {}
    except Exception:
        return "bot"
    kind = f.get("kind") or "bot"
    return kind if kind in getattr(r, "KIND_VALUES", ("bot", "tool")) else "bot"


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


def evaluate(role, st, obs_fail, completion, drift=None, oversize=None, hobs=None, kind=None):
    """관측 → 개정 근거 신호. **데이터로 관측 가능한 것만** 신호로 삼는다.

    kind — 카탈로그 분류(None 이면 `role_kind`). `tool` 이면 role 축 결정론 신호 2종(`manual_oversize`·
      `origin_drift`)만 낸다 — 원장 4신호·귀속 관찰은 봇이 일한 흔적이라 판정하지 않는다(prj3#Issue943 ②).
      obs 는 원장 신호에 종속이라 함께 빠진다."""
    sig = []
    dt, se = st["dispatch_total"], st["session_total"]
    bot_signals = (kind if kind is not None else role_kind(role)) != "tool"
    if not bot_signals:
        dt = se = 0                     # 원장 4신호 전부 «표본 0» 으로 — 판정 분기를 한 곳에 둔다

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

    if (bot_signals and completion == "strict" and st["dispatch_done"] >= MIN_EVENTS
            and st["done_no_hash"] >= MISMATCH_MIN):
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

    # prj3#Issue850 — homunculus **귀속** 관찰은 단독 트리거다. 비귀속 obs(아래)와 다른 점은 하나 —
    #   레코드 `fbot_id` 로 role 귀속이 성립해 계약 F4 를 만족한다(Issue520 분리 근거의 해소). 오류는
    #   도구 응답 표지로만 세어 «조사 ≠ 실패» 를 지킨다(_hobs_is_error). ⚠️ obs 의 교차 재료로는
    #   **쓰지 않는다** — ledger_sig 스냅샷 뒤에 붙인다(Issue522·589 계약: 교차 확인은 원장 근거).
    #   prj3#Issue943 ② — 도구 role 은 귀속 관찰도 판정하지 않는다(봇이 일한 흔적 — 원장 4신호와 같은 축)
    if bot_signals and hobs and hobs.get("total", 0) >= HOBS_MIN_EVENTS:
        rate = hobs.get("error", 0) / hobs["total"]
        if rate >= HOBS_ERROR_RATE_MIN:
            sig.append((
                "homunculus_error_rate",
                "homunculus 귀속 관찰 %d건(봇 %d개) 중 도구 오류 %d건 (%.0f%% ≥ 임계 %.0f%%) — "
                "레코드 fbot_id 귀속(prj3#Issue757_3), 오류 = stderr·interrupted·is_error"
                % (hobs["total"], hobs.get("bots", 0), hobs["error"], rate * 100, HOBS_ERROR_RATE_MIN * 100),
                "오류가 반복되는 도구·명령 유형을 「작업 절차」의 사전 확인 항목으로 올리거나, "
                "「경계·금지」 절에 실패가 잦은 경로의 우회·보고 규칙을 명문화할 것을 제안한다."))

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


def learn_refs(role, title, signals):
    """learn.db instinct FTS 상위 N건 → (rows, q, err). 참고값이지 신호가 아니다 (prj3#Issue856_1).

    err 가 있으면 조회 불가 — 호출자가 draft 에 사유를 남긴다(침묵 금지)."""
    terms = []
    for t in [role, title] + [k for k, _, _ in (signals or [])]:
        t = (t or "").replace('"', " ").strip()
        if t and t not in terms:
            terms.append(t)
    q = " OR ".join('"%s"' % t for t in terms)
    if not os.path.exists(LEARN_DB):
        return [], q, "learn.db 없음"
    try:
        c = connect(LEARN_DB)
        marks = ",".join("?" * len(LEARN_REF_ORIGINS))
        rows = c.execute(
            "SELECT i.title, i.project_id, i.origin, i.source_path FROM instinct_fts f "
            "JOIN instinct i ON i.project_id=f.project_id AND i.instinct_id=f.instinct_id "
            "WHERE instinct_fts MATCH ? AND i.origin IN (%s) ORDER BY f.rank LIMIT ?" % marks,
            [q] + list(LEARN_REF_ORIGINS) + [int(LEARN_REF_LIMIT)]).fetchall()
        c.close()
        return [tuple(r) for r in rows], q, ""
    except Exception as e:
        return [], q, str(e)


def _learn_ref_lines(role, signals):
    try:
        fm, _ = parse_frontmatter(read_text(manual_path(role)))
        title = fm.get("title", "")
    except Exception:
        title = ""
    rows, q, err = learn_refs(role, title, signals)
    out = ["", "### 관련 학습 (참고값 — 신호 아님)", ""]
    if err:
        out.append("* 조회 불가 — %s" % err)
    elif not rows:
        out.append("* 매치 0건 — q=%s" % q)
    else:
        out.append("> learn.db instinct FTS 상위 %d건. 개정 판단의 **참고**일 뿐 신호 판정에 쓰이지 않는다 "
                   "(instinct 에는 fbot_id 귀속이 없다 — prj3#Issue850). `apply` 가 이 절째 걷어낸다." % len(rows))
        out.append("")
        for t, proj, origin, src in rows:
            out.append("* %s — %s · %s · `%s`" % (t, proj, origin, src))
    return out


def _window_label(since):
    """draft 근거 표·review 요약의 «집계 창» 문구 (prj3#Issue943)."""
    if not since:
        return "전 기간"
    return ("%s 이후 — 최근 %d일(policy `fbot_review_window_days`)과 role 기준선(최근 apply·reject) 중 늦은 쪽"
            % (_ts(since), WINDOW_DAYS))


def render_draft(role, base_text, signals, st, obs_fail, kind="bot", hobs=None):
    hobs = hobs or {"total": 0, "error": 0, "bots": 0}
    lines = [base_text.rstrip("\n"), "", "## 개정 제안 (%s)" % today(), "", AUTO_MARK, "",
             "> 기계 생성 초안이다. **정본이 아니다** — 매뉴얼핀봇이 본문을 고치고(`mark`) 승인 게이트를 "
             "통과해야 반영된다(총괄 결정 · 권한 경계 role 은 사람 `[컨펌]` ACK → `apply`).", "",
             "### 관측 근거", "",
             "| 지표 | 값 |", "| :--- | :--- |",
             # 도구 재분류 role 은 원장 0 이 정상이다 — 표에 그 선언이 없으면 읽는 사람이
             #   같은 0 을 «방치» 로 되읽는다(prj3#Issue636 ③ⓒ). prj3#Issue943 ② 부터 판정도 하지 않는다
             "| 분류 | 도구(`kind=tool`) — 원장 신호 0 은 **정상**이다(prj3#Issue636). 원장 4신호·귀속 관찰은 "
             "판정하지 않는다(prj3#Issue943) — 기대 신호는 `origin_drift`·`manual_oversize` 뿐 |" if kind == "tool" else
             "| 분류 | 공정 role(`kind=bot`) — 원장 4신호가 기대된다 |",
             "| 원장 집계 창(배분·출근) | %s · observation·귀속 관찰도 같은 창 |" % _window_label(st.get("since")),
             "| 배분(fbot_dispatch) | 총 %d · blocked/failed %d · 재시도 %d · done %d(hash 없음 %d) |"
             % (st["dispatch_total"], st["dispatch_blocked"], st["dispatch_retry"],
                st["dispatch_done"], st["done_no_hash"]),
             "| 출근(fbot_session) | 총 %d · current_task 공란 %d |" % (st["session_total"], st["session_idle"]),
             "| observation 실패 언급 | %d |" % obs_fail,
             "| homunculus 귀속 관찰 | %d건 · 봇 %d개 · 도구 오류 %d건 (fbot_id 귀속, prj3#Issue850) |"
             % (hobs.get("total", 0), hobs.get("bots", 0), hobs.get("error", 0)),
             "", "### 제안", ""]
    for i, (key, detail, proposal) in enumerate(signals, 1):
        lines.append("%d. **%s** — %s" % (i, key, detail))
        lines.append("    - %s" % proposal)
    lines.extend(_learn_ref_lines(role, signals))
    lines.append("")
    return "\n".join(lines)


# ── review ───────────────────────────────────────────────────────────────────

def _no_signal_reason(role, st):
    """신호 0 을 **무엇으로 읽어야 하는가** — 도구/공정에서 답이 갈린다 (prj3#Issue636 ③ⓒ).

    같은 «배분 0» 이 도구 role 에서는 설계대로이고 공정 role 에서는 표본 부족이다.
    한 문장으로 뭉뚱그리면 운영자가 둘을 구별할 방법이 없어, 정상인 0 을 배선 결함으로
    계속 의심하거나 반대로 방치된 0 을 정상으로 넘긴다.
    """
    if role_kind(role) == "tool":
        return ("**도구 재분류(`kind=tool`) — 원장 신호 0 은 정상**이다(prj3#Issue636). "
                "봇 경유는 조건부(동시 다발·장기 실행·2회 실패 에스컬레이션)이며 원장 4신호는 판정하지 않는다"
                "(prj3#Issue943) — 기대 신호는 `origin_drift`·`manual_oversize`")
    return "임계 미달 또는 표본 부족(<%d, 집계 창 안)" % MIN_EVENTS


def cmd_review(args):
    roles = [args.role] if args.role else all_roles()
    for r in roles:
        if not os.path.exists(manual_path(r)):
            die("매뉴얼 없음: %s" % manual_path(r))
    stats = collect_job_stats(roles)   # prj3#Issue943 — 창 안 기록만, role 마다 `since`
    obs = collect_obs_stats(roles) if not args.no_obs else {r: 0 for r in roles}
    # prj3#Issue850 — homunculus 귀속 관찰(학습 3단 «관찰» 티어의 산출을 매뉴얼 루프의 원천으로)
    hobs = collect_hobs_stats(roles) if not args.no_obs else {r: None for r in roles}

    empty = dict(dispatch_total=0, dispatch_blocked=0, dispatch_retry=0, dispatch_done=0,
                 done_no_hash=0, session_total=0, session_idle=0)
    made, skipped = [], []
    for role in roles:
        st = stats.get(role, empty)
        kind = role_kind(role)         # 분류 판정은 role 당 한 번 — 판정(evaluate)과 표(render_draft)가 같은 값을 본다
        text = read_text(manual_path(role))
        fm, _ = parse_frontmatter(text)
        n = len(injected_text(text))   # prj3#Issue767 — 상한은 주입본 기준(이력은 재지 않는다)
        sig = evaluate(role, st, obs.get(role, 0), fm.get("completion", ""),
                       drift=origin_drift(role),
                       oversize=(n, MANUAL_MAX_CHARS) if n > MANUAL_MAX_CHARS else None,
                       hobs=hobs.get(role), kind=kind)
        if not sig:
            skipped.append((role, st))
            continue
        if args.dry_run:
            made.append((role, sig, True))
            continue
        if draft_preserved(role):
            # prj3#Issue757 T12 — 매뉴얼핀봇이 쓴 draft 는 결정(apply/reject) 전까지 다시 만들지 않는다
            skipped.append((role, st))
            continue
        write_draft(draft_path(role),
                    render_draft(role, text, sig, st, obs.get(role, 0), kind,
                                 hobs=hobs.get(role)))
        made.append((role, sig, False))

    if DRIFT_UNAVAILABLE:
        print("⚠️ origin_drift 판정 불가 — %s (신호 없음이 최신을 뜻하지 않는다)"
              % "; ".join(sorted(set(DRIFT_UNAVAILABLE))), file=sys.stderr)
    print("# fbot 매뉴얼 개정 후보 (%s)%s" % (today(), " [dry-run]" if args.dry_run else ""))
    print("* 대상 role %d종 · 매뉴얼 %s" % (len(roles), MANUAL_DIR))
    print("* 원장 집계 창: 최근 %d일(policy `fbot_review_window_days`) · role 기준선(최근 apply·reject) 이후만 — "
          "도구(`kind=tool`)는 원장 4신호 미판정 (prj3#Issue943)" % WINDOW_DAYS)
    if not made:
        print("* **개정 근거 없음** — draft 를 만들지 않는다(빈 개정 금지).")
        for role, st in skipped:
            print("    - %s: 배분 %d(차단 %d·재시도 %d) · 출근 %d(공란 %d) → %s"
                  % (role, st["dispatch_total"], st["dispatch_blocked"], st["dispatch_retry"],
                     st["session_total"], st["session_idle"], _no_signal_reason(role, st)))
        return 0
    for role, sig, dry in made:
        print("* **%s** — 신호 %d건%s" % (role, len(sig), " (dry-run · 미생성)" if dry else " → %s" % draft_path(role)))
        for key, detail, _ in sig:
            print("    - %s: %s" % (key, detail))
    if skipped:
        print("* 근거 없음(draft 미생성): %s"
              % ", ".join("%s%s" % (r, "(도구)" if role_kind(r) == "tool" else "")
                          for r, _ in skipped))
    if not args.dry_run:
        print("* 다음 단계: `propose` → 본사 팀장이 매뉴얼핀봇 배분 → `mark` → `submit` → 총괄 `apply`/`reject`"
              " (권한 경계 role 은 총괄 `needs-human` → 사람 ACK → `apply`)")
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
    out, dup = [], []
    for d in drafts:
        role = os.path.basename(d)[:-len(DRAFT_SUFFIX)]
        # prj3#Issue518 — 주간 재등록 소음 차단. 인박스(1·2단계)와 mq([컨펌] 대기 — 권한 경계 role 의 3단계)를 다 본다
        already = pending_confirm(role) or pending_inbox(role)
        if already:
            dup.append((role, already))
            continue
        # prj3#Issue757 T12 — 총괄은 일을 하지 않는다. 1단계는 **본사 팀장**에게: 매뉴얼핀봇에 본문 작성을 배분하고,
        #   완료를 받으면 `submit` 으로 총괄에 결정을 올린다(2단계). 종전(Issue756)은 총괄이 본문을 고친 뒤 apply 했다.
        #   tick(headless)은 배분의 next_step 을 돌리지 못하므로 배분 자체는 본사 팀장이 한다(재점검 지적 8).
        # prj3#Issue757_1 — 권한 경계 role 도 같은 1단계를 탄다. 종전엔 여기서 곧바로 mq `[컨펌] [H:방침]` 이라 본문을
        #   쓸 손이 없었다(prj3#Issue773 은 작업자가 draft 를 직접 썼다). 바뀐 것은 본문 작성 주체뿐 — 최종 게이트는 사람 ACK
        h_note = ("권한 경계 매뉴얼 — 결정은 사람(H 방침): submit 은 총괄 인박스로 가고 총괄이 `needs-human` 으로 "
                  "mq `[컨펌] [H:방침]` 에 올린다(총괄 전결 불가). " if role in AUTHORITY_ROLES else "")
        msg = ("%s — role: %s. 본문 작성 배분 요청(prj3#Issue757): 매뉴얼핀봇에 배분 — "
               "`python3 ~/.claude/hooks/fbot-lead.py dispatch --by <나> --role %s --cwd ~/.claude "
               "--topic \"매뉴얼 개정 %s\"` → 응답 next_step 실행 → 완료 수령 후 "
               "`~/.claude/hooks/fbot-manual-review.py submit --role %s --by <나>` 로 총괄에 상신. %s초안 %s. "
               "여러 role 에 같은 신호면 매뉴얼이 아니라 배선 문제다 — 이슈 1건으로 올린다.%s"
               % (CONFIRM_MARK, role, MANUAL_ROLE, role, role, h_note, d,
                  "" if role in AUTHORITY_ROLES else
                  (" 배분하지 않기로 하면(오탐·배선 문제) `submit --role %s --by <나> --decline --reason \"…\"` 로 "
                   "총괄에 반려 상신한다(작성 표지 불요 — prj3#Issue946)." % role)))
        if args.dry_run:
            print("[dry-run] 본사 팀장 인박스 ← %s" % msg)
            continue
        out.append((role, send_request(hq_lead_bot(), role, msg)))
    for role, res in out:
        print("* %s → 본사 팀장 인박스 %s" % (role, res))
    for role, mid in dup:
        print("* %s → 스킵(미처리 요청 이미 있음: %s)" % (role, mid))
    return 0


def chief_bot():
    """결정 권한 C 등급의 결정자 — 레지스트리 role=chief 개체(해고 제외). 없으면 fail-loud."""
    c = connect(REGISTRY_DB)
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(bot)").fetchall()}
        cond = " AND COALESCE(employment,'') != 'terminated'" if "employment" in cols else ""
        # 상비 총괄 = role=chief + parent 없음 (fbot-state.is_core_bot 과 같은 판정) — role=chief 이슈 워커
        #   (fbot-exec-issue331 선례)가 이름순으로 앞서도 총괄로 오인하지 않는다
        row = c.execute("SELECT bot_id FROM bot WHERE role=? AND parent_bot_id IS NULL"
                        " AND career != 'terminated'%s ORDER BY bot_id LIMIT 1" % cond, (CHIEF_ROLE,)).fetchone()
    finally:
        c.close()
    if not row:
        die("총괄(role=%s) 개체 없음 — 매뉴얼 개정 전결자가 없다. 총괄을 채용한다(fbot-hr-gate.py hire --role chief)" % CHIEF_ROLE)
    return row[0]


def hq_lead_bot():
    """본사 팀장 — role=lead · prj 없음 · parent 없음 · 재직(prj3#Issue757 T12). 없으면 fail-loud."""
    c = connect(REGISTRY_DB)
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(bot)").fetchall()}
        cond = " AND COALESCE(employment,'') != 'terminated'" if "employment" in cols else ""
        row = c.execute("SELECT bot_id FROM bot WHERE role=? AND prj IS NULL AND parent_bot_id IS NULL"
                        " AND career != 'terminated'%s ORDER BY bot_id LIMIT 1" % cond, (LEAD_ROLE,)).fetchone()
    finally:
        c.close()
    if not row:
        die("본사 팀장(role=lead·prj 없음) 개체 없음 — 매뉴얼 개정 본문을 배분할 사람이 없다")
    return row[0]


def send_request(to, role, text, from_bot=""):
    """인박스 적재 — fbot-inbox 경유(직접 INSERT 금지: 기상·이벤트가 거기 있다). 반환 요청 id.
    from_bot 이 비면 **시스템 발신**(tick) — 세션도 비워 사람 발신으로 잘못 읽히지 않게 한다."""
    p = subprocess.run([sys.executable, INBOX_PY, "send", "--to", to, "--kind", "manual-review",
                        "--from-bot", from_bot, "--from-session", "", "--body", text],
                       capture_output=True, text=True)
    if p.returncode != 0:
        die("인박스 적재 실패(to=%s, role=%s): %s" % (to, role, (p.stderr or p.stdout).strip()[-300:]))
    try:
        return json.loads(p.stdout or "{}").get("id") or "?"
    except ValueError:
        return (p.stdout or "").strip()[-80:]


def open_requests(role, to=None):
    """미처리(open) 인박스의 같은 role 개정 요청 전부 — [(id, 수신자)] (생성 순). `to` 가 있으면 그 수신자 앞만.
    «미처리» 술어의 **단일 지점**이다 — `pending_inbox`(첫 건)와 반려의 요청 종결(prj3#Issue946)이 같이 읽는다."""
    c = connect(REGISTRY_DB)
    try:
        # result IS NULL — `reply --status accepted` 는 status 를 open 으로 둔다(ACK 일 뿐 — sweep 이 배분 완료 때 닫는다,
        #   fbot-inbox 의 다른 조회도 같은 술어). 이게 없으면 수락만 하고 아직 닫히지 않은 role 의 개정 루프가 영구히
        #   스킵된다. rejected·done 은 reply 가 status 도 닫으므로(prj3#Issue937) 이 술어에 기대지 않는다
        rows = c.execute("SELECT id, owner FROM job WHERE kind='fbot_request' AND status='open' AND result IS NULL"
                         " AND json_extract(payload,'$.kind')='manual-review'"
                         " AND json_extract(payload,'$.body') LIKE ?" + (" AND owner=?" if to else "")
                         + " ORDER BY created_at",
                         (("%%role: %s.%%" % role,) + ((to,) if to else ()))).fetchall()
    finally:
        c.close()
    return [(r[0], r[1]) for r in rows]


def pending_inbox(role, to=None):
    """미처리(open) 인박스에 같은 role 의 개정 요청이 있으면 그 id. `to` 가 있으면 그 수신자 앞만 본다
    (prj3#Issue757 T12 — 1단계 본사 팀장 앞 요청이 총괄 전결의 근거로 잘못 읽히지 않게). 없으면 두 단계 모두(중복 방지)."""
    rows = open_requests(role, to)
    return rows[0][0] if rows else None


def verify_decider(by, role, reason):
    """총괄 전결의 자격 — 전부 통과해야 결정 레코드를 만든다 (prj3#Issue756, 독립 검토 반영).

    ① 호출 세션이 결정자 본인(`FBOT_ID == by`) — `--by` 는 누구나 쓰는 문자열이다. 이 확인이 없으면
       어느 세션이든 총괄 이름 한 줄로 정본을 쓴다(사람 ACK 가 지키던 자리를 문자열이 대신하게 된다)
    ② 상비 총괄 — role=chief · parent 없음 · 해고·정직 아님 (`chief_bot()` 과 같은 판정)
    ③ 권한 경계 매뉴얼이 아님 — AUTHORITY_ROLES 는 H(`방침`)
    ④ 그 role 의 **미처리 개정 요청**이 인박스에 있음 — 요청 없는 전결은 근거가 없다
    반환: 닫을 요청 id."""
    if not (reason or "").strip():
        die("--by 전결에는 --reason 이 필요하다 — 무엇을 왜 정했는지가 사후 검토의 전부다")
    err = _ident().impersonation_error(by, "전결")
    if err:
        die(err + ". 사람은 `--by` 없이 mq ACK 경로로 반영한다")
    if role in AUTHORITY_ROLES:
        die("권한 경계 매뉴얼(%s)은 총괄 전결 대상이 아니다 — H(방침): 총괄은 `needs-human --role %s --by <나>` 로 "
            "mq `[컨펌] [H:방침]` 에 올리고, 사람 ACK 후 `apply` (봇이 자기 권한을 넓히지 못한다)" % (role, role))
    if chief_bot() != by:
        die("매뉴얼 개정 전결은 상비 총괄만 — %s 은 자격 없음(role·parent·재직 확인)" % by)
    rid = pending_inbox(role, to=by)
    if not rid:
        die("role=%s 의 미처리 결정 요청이 총괄 인박스에 없다 — 본사 팀장의 `submit` 이 전결의 근거다" % role)
    return rid


def close_request(rid, verdict, reason, by):
    """처리한 인박스 요청을 닫는다 — fbot-inbox `reply --status done` 경유(이벤트·SSE 가 거기 있다)."""
    p = subprocess.run([sys.executable, INBOX_PY, "reply", "--id", rid, "--status", "done",
                        "--by", by, "--body", ("%s: %s" % (verdict, reason))[:200]],
                       capture_output=True, text=True)
    if p.returncode != 0:
        print("⚠️ 인박스 요청 %s 닫기 실패 — 수동 `fbot-inbox.py reply --id %s --status done`: %s"
              % (rid, rid, (p.stderr or p.stdout).strip()[-200:]), file=sys.stderr)


def record_decision(by, role, verdict, reason):
    """C 등급 전결 기록 — `fbot_event` type=decision (fbot-state.py decide 와 같은 모양, prj3#Issue756).

    daily «대신 결정한 것» 이 이 행을 읽는다. ref=`manual:<role>` 로 매뉴얼 개정 결정을 식별한다.
    자격 판정은 `verify_decider` 가 먼저 한다 — 여기는 기록만."""
    c = connect(REGISTRY_DB)
    now = int(time.time())
    eid = "fbotev-%d-%s" % (now, os.urandom(4).hex())
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO job(id, store, kind, status, payload, result, attempts, owner, "
                  "lease_until, blocked_since, created_at) VALUES(?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
                  (eid, "fbot", "fbot_event", "done",
                   json.dumps({"type": "decision",
                               "detail": ("[C] 매뉴얼 개정 %s → %s: %s" % (role, verdict, reason))[:300],
                               "ref": "manual:%s" % role}, ensure_ascii=False), by, now))
        c.commit()
    finally:
        c.close()
    return eid, datetime.fromtimestamp(now).strftime("%Y-%m-%dT%H:%M:%S")


# ── ACK 조회 (읽기 전용 — 이 스크립트는 ack 를 발행하지 않는다) ───────────────

def find_ack(role, since=None):
    """queue_done 에서 해당 role 의 `[컨펌]` 승인 레코드를 **조회**한다. 없으면 None.

    since — ISO 시각(`YYYY-MM-DDTHH:MM:SS`). 주어지면 그 **이후** ACK 만 인정한다(Issue693_3)."""
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
        if since and (d.get("ack_ts") or "") < since:
            continue
        if hit is None or (d.get("ack_ts") or "") >= (hit.get("ack_ts") or ""):
            hit = d
    return hit


# ── job 원장 기록 (계약 F4 — 결정도 기록이다) ────────────────────────────────

def record_job(role, decision, detail, by=""):
    """개정 루프 행위 기록 — `decision` 은 marked·declined·raised·applied·rejected·returned.
    prj3#Issue946 — 실행 주체를 남긴다: `by`(봇)가 있으면 owner·payload.by 가 그 봇이다. 없으면(사람 세션·tick)
    종전 owner 값 그대로. applied·rejected 는 원장 집계 창의 role 기준선이다(`ledger_baselines`, prj3#Issue943)."""
    c = connect(REGISTRY_DB)
    now = int(time.time())
    jid = "fbotman-%d-%s" % (now, os.urandom(4).hex())
    payload = {"role": role, "decision": decision}
    if by:
        payload["by"] = by
    c.execute("BEGIN IMMEDIATE")
    c.execute("INSERT INTO job(id, store, kind, status, payload, result, attempts, owner, "
              "lease_until, blocked_since, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (jid, None, "fbot_manual_review", "done",
               json.dumps(payload, ensure_ascii=False),
               json.dumps({"detail": detail}, ensure_ascii=False),
               0, by or "fbot-lead", None, None, now))
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


def strip_author(text):
    """작성 표지 줄을 걷어낸다 — 정본에는 남기지 않는다."""
    return AUTHOR_RE.sub("", text)


# 반송 블록 (prj3#Issue948) — `reject --return` 이 draft 본문 머리에 붙이는 사유. 재배분된 매뉴얼핀봇이 draft 를 열자마자
#   읽고 «그 위에서» 고친다. 정본에는 남지 않는다(`canonical_body`). 재반송은 블록을 교체한다(누적하지 않는다)
RETURN_OPEN = "<!-- fbot-manual-review:returned"
RETURN_CLOSE = "<!-- /fbot-manual-review:returned -->"
RETURN_RE = re.compile(r"<!-- fbot-manual-review:returned[^\n]*-->\n.*?<!-- /fbot-manual-review:returned -->\n*", re.S)


def strip_return(text):
    """반송 블록을 걷어낸다."""
    return RETURN_RE.sub("", text)


def add_return_note(text, by, reason):
    """반송 블록을 본문 머리(frontmatter 바로 뒤)에 둔다 — 기존 블록은 교체. frontmatter 앞에 두면
    `apply` 의 `append_revision`(frontmatter 필수)이 깨지므로 본문 머리가 «draft 머리» 다."""
    base = strip_return(text)
    one = (reason or "").replace("\n", " ").replace("-->", "-- >").strip()
    block = ("%s by=%s at=%s -->\n"
             "> **반송**(%s · %s): %s\n"
             ">\n"
             "> draft 는 보존됐다 — 정본을 다시 복사하지 말고 **이 draft 위에서** 사유대로 고친 뒤 `mark` 한다. "
             "이 블록은 `apply` 가 걷어낸다(정본에 남지 않는다).\n"
             "%s\n\n" % (RETURN_OPEN, by or "-", today(), today(), by or "사람(비봇 세션)", one, RETURN_CLOSE))
    fm, body_start = parse_frontmatter(base)
    if fm:
        return base[:body_start] + block + base[body_start:]
    return block + base


def canonical_body(text):
    """draft → 정본 글 — 자동 제안 절·반송 블록·작성 표지를 걷어낸다. `apply` 의 사전 상한 판정과 실제 쓰기가
    **같은 함수**를 읽는다(둘이 갈리면 상한 판정한 글과 쓴 글이 달라진다)."""
    return strip_author(strip_return(strip_auto_section(text)))


def _draft_sha(text):
    return hashlib.sha256(strip_author(text).rstrip("\n").encode("utf-8")).hexdigest()[:16]


def draft_author(role):
    """draft 의 작성 표지 검증 — 매뉴얼핀봇(role=manual) 본인이 남겼고 그 뒤로 바뀌지 않았어야 한다. 아니면 die.
    총괄은 일을 하지 않는다(prj3#Issue757) — 표지 없는 draft 를 반영하면 총괄이 본문을 쓴 것과 같다."""
    text = read_text(draft_path(role))
    m = AUTHOR_RE.search(text)
    if not m:
        die("draft 에 매뉴얼핀봇 작성 표지가 없다(role=%s) — 본문은 매뉴얼핀봇이 쓰고 `mark` 로 표지를 남긴다" % role)
    if m.group(2) != _draft_sha(text):
        die("작성 표지 뒤에 draft 가 바뀌었다(role=%s) — 매뉴얼핀봇이 다시 `mark` 해야 한다" % role)
    c = connect(REGISTRY_DB)
    try:
        r = c.execute("SELECT role FROM bot WHERE bot_id=?", (m.group(1),)).fetchone()
    finally:
        c.close()
    if not r or r[0] != MANUAL_ROLE:
        die("작성 표지의 주체 %s 는 매뉴얼핀봇이 아니다" % m.group(1))
    return m.group(1)


def draft_preserved(role):
    """review 가 이 draft 를 덮지 말아야 하는가 — 작성 표지가 있거나(매뉴얼핀봇이 썼다) 반송 블록이 있으면
    (반송돼 재작성 대기 — prj3#Issue948. 표지는 반송이 지웠다) True."""
    d = draft_path(role)
    if not os.path.exists(d):
        return False
    t = read_text(d)
    return bool(AUTHOR_RE.search(t) or RETURN_RE.search(t))   # 블록 전체 일치 — 본문의 마커 인용은 보존 근거가 아니다


def cmd_mark(args):
    """매뉴얼핀봇의 작성 표지 (prj3#Issue757 T12) — 본문을 고친 뒤 부른다. 호출 세션 = 본인 · role=manual."""
    role, by = args.role, (args.by or "").strip()
    err = _ident().impersonation_error(by, "표지")
    if err:
        die(err)
    c = connect(REGISTRY_DB)
    try:
        r = c.execute("SELECT role FROM bot WHERE bot_id=?", (by,)).fetchone()
    finally:
        c.close()
    if not r or r[0] != MANUAL_ROLE:
        die("작성 표지는 매뉴얼핀봇(role=%s)만 남긴다 — %s" % (MANUAL_ROLE, by))
    d = draft_path(role)
    if not os.path.exists(d):
        die("draft 없음: %s" % d)
    base = strip_author(read_text(d)).rstrip("\n")
    write_draft(d, base + "\n\n<!-- fbot-manual-review:author=%s sha=%s -->\n" % (by, _draft_sha(base)))
    record_job(role, "marked", "by=%s" % by, by=by)
    print("✅ %s 작성 표지 — %s (본사 팀장에게 완료 보고 → submit)" % (role, by))
    return 0


def _submit_decline(role, by, reason):
    """본사 팀장의 **반려 상신** (prj3#Issue946) — 매뉴얼핀봇에 배분하지 않기로 한 draft 를 총괄 결정 요청으로 올린다.

    작성 표지를 요구하지 않는다 — 대상이 배분 전 자동 draft 다. 형식은 일반 상신과 같은 `role: X.` 결정 요청이라
    총괄 `reject --by` 가 `verify_decider` ④(총괄 앞 미처리 요청)를 **그대로** 통과한다(«요청 없는 전결 금지» 유지).
    `apply --by` 는 `draft_author` 가 계속 막는다 — 반려 상신이 표지 없는 본문의 반영 근거가 되지 않는다.
    권한 경계 role 은 총괄 전결 대상이 아니라 거부한다(H — 사람 결정)."""
    if not reason:
        die("submit --decline 에는 --reason 이 필요하다 — 왜 배분하지 않는지가 총괄 결정의 근거다")
    if role in AUTHORITY_ROLES:
        die("권한 경계 매뉴얼(%s)의 반려는 총괄 전결 대상이 아니다(H 방침) — 반려 상신 경로가 없다. 사람이 정한다: "
            "비봇 세션의 `reject --role %s --reason \"…\"`(필요하면 총괄 인박스로 사람 상신을 요청)" % (role, role))
    d = draft_path(role)
    if not os.path.exists(d):
        die("draft 없음: %s" % d)
    chief = chief_bot()
    if pending_inbox(role, to=chief):
        die("role=%s 의 결정 요청이 이미 총괄 인박스에 있다" % role)
    marked = bool(AUTHOR_RE.search(read_text(d)))
    msg = ("%s — role: %s. 반려 상신(C 등급 총괄 전결, prj3#Issue946) — 본사 팀장 %s 가 매뉴얼핀봇에 배분하지 "
           "않기로 했다: %s (초안 %s · 작성 표지 %s). 반려: `~/.claude/hooks/fbot-manual-review.py reject --role %s "
           "--by <총괄 bot_id> --reason \"…\"`(draft 삭제) · 방향은 맞고 고칠 것이 있으면 반송: `reject --role %s "
           "--by <총괄 bot_id> --return --reason \"…\"`(draft 보존 → 매뉴얼핀봇 재배분). 반영(`apply --by`)은 작성 "
           "표지 있는 draft 만 된다. 여러 role 에 같은 신호면 배선 이슈 1건이다. "
           "권한표: ~/.claude/_doc_arch/decision-authority.md"
           % (CONFIRM_MARK, role, by, reason, d, "있음" if marked else "없음", role, role))
    rid2 = send_request(chief, role, msg, from_bot=by)
    rid1 = pending_inbox(role, to=by)
    if rid1:
        close_request(rid1, "반려 상신", "총괄 결정 요청 %s: %s" % (rid2, reason), by)
    record_job(role, "declined", reason, by=by)
    print("✅ %s → 총괄 인박스 %s (반려 상신: %s)" % (role, rid2, reason))
    return 0


def cmd_submit(args):
    """본사 팀장의 상신 (prj3#Issue757 T12) — 매뉴얼핀봇이 쓴 draft 를 총괄에게 결정 요청으로 올린다.
    `--decline` 이면 반려 상신(`_submit_decline` — 작성 표지 불요, prj3#Issue946)."""
    role, by = args.role, (args.by or "").strip()
    err = _ident().impersonation_error(by, "상신")
    if err:
        die(err)
    if hq_lead_bot() != by:
        die("상신은 본사 팀장만 — %s 은 자격 없음" % by)
    if getattr(args, "decline", False):
        return _submit_decline(role, by, (getattr(args, "reason", None) or "").strip())
    if (getattr(args, "reason", None) or "").strip():
        # 조용히 버리면 «반려하려던» 호출이 표지 있는 draft 의 «반영 결정 요청» 으로 뒤집힌다 — 경고가 아니라 거부
        die("--reason 은 --decline(반려 상신) 전용이다 — 반려 상신이면 `--decline` 을 붙이고, 반영 상신이면 --reason 을 뺀다")
    author = draft_author(role)
    if pending_inbox(role, to=chief_bot()):
        die("role=%s 의 결정 요청이 이미 총괄 인박스에 있다" % role)
    d = draft_path(role)
    if role in AUTHORITY_ROLES:
        # prj3#Issue757_1 — 권한 경계 role 도 상신은 총괄에게(봇의 H 는 총괄이 상신한다 — decision-authority).
        #   다만 결정 요청이 아니라 «사람에게 올리라» 요청이다: 총괄 전결(`apply --by`)은 verify_decider 가 거부한다
        msg = ("%s — role: %s. 사람 결정 요청(H 방침 — 권한 경계 매뉴얼이라 총괄 전결 불가) — 매뉴얼핀봇 %s 가 "
               "본문을 썼다(초안 %s). 총괄은 `~/.claude/hooks/fbot-manual-review.py needs-human --role %s "
               "--by <총괄 bot_id>` 로 mq `[컨펌] [H:방침]` 에 올린다(결정 묶음에 섞지 말 것 — ACK 매칭 형식). "
               "사람 ACK 뒤 `apply --role %s` 로 반영된다. 본문 수정은 총괄 몫이 아니다. "
               "권한표: ~/.claude/_doc_arch/decision-authority.md"
               % (CONFIRM_MARK, role, author, d, role, role))
    else:
        msg = ("%s — role: %s. 결정 요청(C 등급 총괄 전결) — 매뉴얼핀봇 %s 가 본문을 썼다(초안 %s). "
               "반영: `~/.claude/hooks/fbot-manual-review.py apply --role %s --by <총괄 bot_id> --reason \"…\"` · "
               "반려: `reject --role %s --by <총괄 bot_id> --reason \"…\"`(draft 삭제) · 반송: `reject --role %s "
               "--by <총괄 bot_id> --return --reason \"…\"`(draft 보존 — 사유를 머리에 붙여 매뉴얼핀봇 재배분, prj3#Issue948). "
               "본문 수정은 총괄 몫이 아니다 — 고칠 것이 있으면 반송 사유에 적는다. "
               "권한표: ~/.claude/_doc_arch/decision-authority.md"
               % (CONFIRM_MARK, role, author, d, role, role, role))
    rid2 = send_request(chief_bot(), role, msg, from_bot=by)
    rid1 = pending_inbox(role, to=by)
    if rid1:
        close_request(rid1, "상신", "총괄 결정 요청 %s" % rid2, by)
    print("✅ %s → 총괄 인박스 %s (작성 %s)" % (role, rid2, author))
    return 0


def _mq_confirm(message, bot=""):
    """mq `[컨펌]` 등록 — helper **호출만**(큐 직접 Write 금지). 반환 mq id. `[H:분류]` 판정은 helper 게이트(exit 5)가 한다.
    bot 이 있으면 `source=<bot>@<cwd 이름>`·`--from-bot` — hub «사람 결정 대기»(prj1#Issue570)가 그 봇 카드에 싣는다
    (fbot-inbox `_mq_confirm` 과 같은 귀속 규약. 그 함수를 빌리지 않는 것은 subprocess 를 함수 안에서 import 해서 —
    이 모듈의 subprocess 대역이 닿지 않아 테스트가 실 mq 에 쓰게 된다)."""
    cmd = [MQ_ENQUEUE, "--message", message, "--due", "+0d"]
    if bot:
        cmd += ["--source", "%s@%s" % (bot, os.path.basename(os.getcwd()) or "fbot"), "--from-bot", bot]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        die("mq [컨펌] 등록 실패%s: %s" % (" — H 등급 게이트 거부" if p.returncode == 5 else "",
                                         (p.stderr or p.stdout).strip()[-300:]))
    m = re.search(r"enqueued:\s*(\S+?\.json)", p.stdout or "")
    return os.path.splitext(os.path.basename(m.group(1)))[0] if m else (p.stdout or "").strip()[-80:]


def cmd_needs_human(args):
    """권한 경계 매뉴얼 개정을 사람에게 올린다 — mq `[컨펌] [H:방침]` (prj3#Issue757_1).

    두 경로 · 최종 게이트는 둘 다 사람 ACK 다(`apply` 의 `find_ack` — draft 이후 승인만):
      ⓐ 총괄(`--by`) — 조직 경로. 매뉴얼핀봇 작성 표지 + 본사 팀장 상신(총괄 인박스 요청)이 근거. 올린 뒤 요청을 닫는다
      ⓑ 비봇 세션(`--by` 없음·결속 없는 세션) — 사람이 세션에 지시해 draft 를 쓴 경우(prj3#Issue773 선례). 표지 불요
    봇 세션(`FBOT_ID`·`/fbot-bind` 결속·하청 슬롯 — `reject` 와 같은 `_human_session_rejection`)의 `--by` 생략은 거부 — 봇의 H 는 총괄이 상신한다(decision-authority). 일반 role 은 C 라 거부."""
    role, by = args.role, (getattr(args, "by", None) or "").strip()
    fid = _ident().caller_bot()
    if role not in AUTHORITY_ROLES:
        die("role=%s 는 권한 경계 매뉴얼이 아니다 — C 등급: 총괄이 `apply`/`reject --by` 로 결정한다"
            "(C 를 사람에게 되묻지 않는다 — decision-authority)" % role)
    d = draft_path(role)
    if not os.path.exists(d):
        die("draft 없음: %s" % d)
    already = pending_confirm(role)
    if already:
        die("role=%s 의 [컨펌] 이 이미 대기 중이다: %s — 사람 ACK 를 기다린다" % (role, already))
    author, rid = None, None
    if by:
        err = _ident().impersonation_error(by, "사람 상신")
        if err:
            die(err)
        if chief_bot() != by:
            die("봇의 H 는 총괄이 상신한다 — %s 은 자격 없음(상비 총괄만)" % by)
        author = draft_author(role)             # 본문은 매뉴얼핀봇이 쓴 것이어야 한다(표지·해시)
        rid = pending_inbox(role, to=by)
        if not rid:
            die("role=%s 의 사람 결정 요청이 총괄 인박스에 없다 — 본사 팀장의 `submit` 이 근거다" % role)
    else:
        why = _human_session_rejection()   # prj3#Issue954 — FBOT_ID 만 보면 /fbot-bind 결속·하청 슬롯이 비봇으로 통과한다
        if why:
            die("%s — `--by` 없는 needs-human 은 결속 없는 사람 세션 전용이다. 봇의 H 는 총괄이 상신한다"
                "(본사 팀장 `submit` → 총괄 `needs-human --by`)" % why)
    who = ("매뉴얼핀봇 %s 가 본문을 썼다" % author) if author else "비봇 세션이 draft 를 직접 썼다(작성 표지 없음)"
    msg = ("[컨펌] [H:방침] %s — role: %s. 권한 경계 매뉴얼이라 사람 결정 — %s(초안 %s). "
           "승인 시 `~/.claude/hooks/fbot-manual-review.py apply --role %s`, "
           "반려 시 `reject --role %s --reason \"…\"`(고칠 것이 있으면 `--return` — draft 보존·매뉴얼핀봇 재배분). "
           "정본은 승인 전까지 무변경."
           % (CONFIRM_MARK, role, who, d, role, role))
    mid = _mq_confirm(msg, by)
    if rid:
        close_request(rid, "사람 상신", "mq %s" % mid, by)
    record_job(role, "raised", "mq=%s by=%s" % (mid, by or "비봇 세션"), by=by)
    print("✅ %s → mq [컨펌] [H:방침] %s (%s) — 사람 ACK 뒤 `apply --role %s`" % (role, mid, who, role))
    return 0


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
    # prj3#Issue693_3 — 승인은 **그 draft 이후**의 것이어야 한다. 종전에는 role 의 최신 ACK 만
    #   찾아서, draft 를 고쳐 쓴 뒤에도 **고치기 전 내용에 대한 옛 승인**으로 반영됐다
    #   (2026-09-26 실측: 9/22 ACK 가 남아 있어 9/26 압축본이 사람 검토 없이 통과할 수 있었다).
    #   draft mtime 이 곧 «승인 대상 내용» 의 시각이다.
    draft_ts = datetime.fromtimestamp(os.path.getmtime(d)).strftime("%Y-%m-%dT%H:%M:%S")
    by = (getattr(args, "by", None) or "").strip()
    rid = None
    if by:
        # prj3#Issue756 — 총괄 전결(C 등급). 자격 → 상한 사전 판정 → 기록 → 쓰기 순서다:
        #   기록을 쓰기보다 먼저 하면, 상한 초과로 쓰기가 실패해도 «반영» 결정이 daily 에 남는다.
        reason = (getattr(args, "reason", None) or "").strip()
        rid = verify_decider(by, role, reason)
        author = draft_author(role)             # prj3#Issue757 T12 — 본문은 매뉴얼핀봇이 쓴 것이어야 한다
        preview = append_revision(canonical_body(read_text(d)),
                                  {"date": today(), "mq": "-", "note": ("총괄 전결(%s): %s" % (by, reason))[:120]})
        check_cap(m, preview)
        eid, ts = record_decision(by, role, "반영", reason)
        ack = {"acked": True, "id": eid, "ack_ts": ts, "ack_note": "총괄 전결(%s): %s" % (by, reason)}
    else:
        # Issue830 — mq ACK 는 승인 주체를 증명하지 못한다. 권한 경계의 최종 apply 호출자는
        #   solo-approve 와 같은 판정에서 결속 없는 사람 세션임이 확인돼야 한다.
        if role in AUTHORITY_ROLES:
            why = _human_session_rejection()
            if why:
                die("%s — 권한 경계 매뉴얼 apply 는 결속 없는 사람 세션 전용이다" % why)
        ack = find_ack(role, since=draft_ts)
    if not ack:
        stale = find_ack(role)
        die("승인 미확인 — role=%s 의 `[컨펌]` ACK 레코드가 %s/queue_done 에 없다%s.\n"
            "   `propose` 로 등록한 뒤 **사람이** ACK 해야 반영된다(봇 auto-ack 금지). 정본 무변경."
            % (role, MQ_DIR,
               (" — ⚠️ 옛 승인 %s(%s)은 draft 수정(%s) **이전**이라 무효"
                % (stale.get("id"), stale.get("ack_ts"), draft_ts)) if stale else ""))
    new = canonical_body(read_text(d))          # prj3#Issue948 — 반송 블록도 정본에 남기지 않는다
    new = append_revision(new, {"date": today(), "mq": ack.get("id") or "?",
                                "note": (ack.get("ack_note") or "승인 반영").replace("\n", " ")[:120]})
    write_canonical(m, new, ack)
    os.remove(d)
    if rid:
        close_request(rid, "반영", ack.get("ack_note", ""), by)
    jid = record_job(role, "applied", "mq=%s ack_ts=%s" % (ack.get("id"), ack.get("ack_ts")), by=by)
    seen = touch_origin_seen(role)
    print("✅ %s 정본 반영 (승인 %s · %s) · draft 삭제 · job 원장 %s%s"
          % (role, ack.get("id"), ack.get("ack_ts"), jid,
             (" · origin_seen→%s" % seen) if seen else ""))
    return 0


def _send_redispatch(lead, role, reason, by, d):
    """반송 뒤 재배분 요청 — 본사 팀장 인박스 (prj3#Issue948). propose 와 같은 `role: X.` 형식이라 재작성 뒤
    `submit` 이 이 요청을 닫는다. 반환 `(상태, 값)` — 세 결과를 **구분**한다(호출자가 종료 코드를 가른다):
      ("sent", 새 요청 id) · ("open", 이미 열린 요청 id — 중복 방지로 재적재 없음, 정상) ·
      ("failed", 사유) — 반송(draft·결정 기록)은 이미 끝났으나 본사 팀장이 모른다: 부분 상태라 호출자가 비0 종료"""
    rid0 = pending_inbox(role, to=lead)
    if rid0:
        return ("open", rid0)
    msg = ("%s — role: %s. 반송 재배분 요청(prj3#Issue948) — %s 이 반송했다: %s. draft 는 보존됐다(%s · 머리에 "
           "반송 사유) — 정본을 다시 복사하지 말고 **이 draft 위에서** 사유대로 고친다. 매뉴얼핀봇 배분: "
           "`python3 ~/.claude/hooks/fbot-lead.py dispatch --by <나> --role %s --cwd ~/.claude --topic "
           "\"매뉴얼 반송 %s — draft 위에서 수정\"` → 완료 수령 후 `~/.claude/hooks/fbot-manual-review.py submit "
           "--role %s --by <나>` 로 다시 상신."
           % (CONFIRM_MARK, role, by or "사람(비봇 세션)", reason, d, MANUAL_ROLE, role, role))
    try:
        return ("sent", send_request(lead, role, msg, from_bot=by))
    except FbotError as e:
        return ("failed", str(e))


def cmd_reject(args):
    """반려 — 두 모드가 **입구 자격·결정 기록·요청 종결**을 공유한다 (prj3#Issue946 입구 · prj3#Issue948 동작).

    모드
      삭제(기본)  draft 폐기 + `origin_seen` 기준선 갱신 — *«봤고, 반영하지 않기로 했다»*(prj3#Issue518 재발 방지)
      반송(--return)  draft 보존 · 작성 표지만 제거 · 사유를 본문 머리에 첨부 · `origin_seen` 불변 — *«방향은 맞고 고칠
                  것이 있다»*. 본사 팀장 인박스에 재배분 요청(«draft 위에서»)을 올린다. 원장 기준선도 옮기지 않는다
                  (decision=returned — `ledger_baselines` 는 applied·rejected 만 본다, prj3#Issue943)
    입구
      `--by` 총괄 전결 — `verify_decider` 그대로(근거 = 총괄 앞 요청: 본사 팀장 `submit` 또는 `submit --decline`)
      `--by` 없음 — **결속 없는 사람 세션만**. 판정은 apply 사람 경로와 같은 `_human_session_rejection`(Issue830 —
                  `FBOT_ID`·`/fbot-bind` 결속 sid 마커·살아 있는 하청 슬롯): `--by` 없는 봇 반려는 결정 행·요청 종결·
                  실행 주체가 원장에서 빠진다(prj3#Issue946 재현). 사람 세션은 그 role 의 열린 요청을 모두 닫는다
    기록 순서 — 실패할 수 있는 계산(재배분 수신자·반송 본문)은 **결정 기록 전에** 끝낸다(«기록은 쓰기가 성공할 때만»)
    종료 코드 — 0 정상 · 2 반송은 끝났으나 재배분 요청 적재 실패(부분 상태 — stdout 에 수동 통지 안내)
    """
    role = args.role
    reason = (getattr(args, "reason", None) or "").strip()
    ret = bool(getattr(args, "return_", False))
    decision, verdict = ("returned", "반송") if ret else ("rejected", "반려")
    d = draft_path(role)
    if not os.path.exists(d):
        die("draft 없음: %s" % d)
    by = (getattr(args, "by", None) or "").strip()
    if ret and not reason:
        die("reject --return 에는 --reason 이 필요하다 — 반송 사유가 곧 재작성 지시다")
    if by:
        rids = [verify_decider(by, role, reason)]
    else:
        why = _human_session_rejection()
        if why:
            die("%s — `--by` 없는 반려·반송은 결속 없는 사람 세션 전용이다(결정 행·요청 종결·실행 주체가 원장에서 "
                "빠진다). 총괄은 `reject --role %s --by <나> --reason \"…\"`(근거 = 총괄 인박스 요청: 본사 팀장 "
                "`submit` 또는 `submit --decline` — prj3#Issue946)" % (why, role))
        rids = [rid for rid, _ in open_requests(role)]   # 사람 세션 — 이 결정으로 무의미해진 요청 전부
    lead = hq_lead_bot() if ret else None              # 반송은 재배분 수신자가 있어야 한다 — 쓰기 전에 fail-loud
    new_text = add_return_note(strip_author(read_text(d)), by, reason) if ret else None   # 기록 전에 계산
    if by:
        record_decision(by, role, verdict, reason)     # prj3#Issue756 — 반려·반송도 결정이다
    if ret:
        write_draft(d, new_text)
    else:
        os.remove(d)
    for rid in rids:
        close_request(rid, verdict, reason, by)
    sent = _send_redispatch(lead, role, reason, by, d) if ret else None
    jid = record_job(role, decision, reason, by=by)
    if ret:
        st, val = sent
        note = {"sent": "→ 본사 팀장 %s 인박스 %s" % (lead, val),
                "open": "이미 열린 요청 %s 유지(재적재 없음)" % val}.get(st, "적재 실패")
        print("↩️ %s 반송 — draft 보존(작성 표지 제거·사유 머리 첨부) · 재배분 요청 %s · job 원장 %s: %s · "
              "origin_seen 불변" % (role, note, jid, reason))
        if st == "failed":
            print("❌ 재배분 요청 적재 실패(role=%s): %s — 반송·결정 기록은 끝났다. 본사 팀장 %s 에게 직접 알린다: "
                  "`python3 ~/.claude/hooks/fbot-inbox.py send --to %s --kind manual-review --body \"role: %s. 반송 재배분 요청 — draft 위에서\"`"
                  % (role, val, lead, lead, role))
            return 2
        return 0
    seen = touch_origin_seen(role)
    print("🚫 %s draft 폐기 · 사유 job 원장 기록 %s: %s%s"
          % (role, jid, reason,
             (" · origin_seen→%s (재발 방지)" % seen) if seen else ""))
    return 0


# ── inject (출근 주입본 — prj3#Issue767) ──────────────────────────────────────

def cmd_inject(args):
    """출근 주입본을 stdout 으로 — `fbot-checkin.sh`·`/fbot-bind` 가 부른다. 읽기 전용(DB·쓰기 없음)."""
    p = args.file or manual_path(args.role or "")
    if not (args.file or args.role):
        die("inject: --role 또는 --file 필요")
    if not os.path.exists(p):
        die("매뉴얼 없음: %s" % p)
    sys.stdout.write(injected_text(read_text(p)))
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

    p = sub.add_parser("propose", help="draft 목록을 본사 팀장 인박스로 — 매뉴얼핀봇 본문 배분 요청")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_propose)

    p = sub.add_parser("mark", help="매뉴얼핀봇의 작성 표지 — 본문을 고친 뒤 (prj3#Issue757 T12)")
    p.add_argument("--role", required=True); p.add_argument("--by", required=True)
    p.set_defaults(fn=cmd_mark)

    p = sub.add_parser("submit", help="본사 팀장이 매뉴얼핀봇 draft 를 총괄 결정 요청으로 상신 (prj3#Issue757 T12) — "
                                      "--decline 이면 반려 상신")
    p.add_argument("--role", required=True); p.add_argument("--by", required=True)
    p.add_argument("--decline", action="store_true",
                   help="배분하지 않기로 한 draft 를 총괄에 반려 상신 — 작성 표지 불요, --reason 필수 (prj3#Issue946)")
    p.add_argument("--reason", default="", help="--decline 사유(필수) — --decline 없이 주면 거부")
    p.set_defaults(fn=cmd_submit)

    p = sub.add_parser("needs-human", help="권한 경계 draft 를 mq [컨펌] [H:방침] 으로 사람에게 — 총괄 --by 또는 결속 없는 사람 세션 (prj3#Issue757_1·954)")
    p.add_argument("--role", required=True)
    p.add_argument("--by", default="", help="총괄 bot_id — 조직 경로(표지·상신 필수). 비봇 세션은 생략")
    p.set_defaults(fn=cmd_needs_human)

    p = sub.add_parser("apply", help="승인 확인 후 draft → 정본 반영 (총괄 --by 전결 또는 mq ACK)")
    p.add_argument("--role", required=True)
    p.add_argument("--by", default="", help="총괄(role=chief) bot_id — C 등급 전결 (prj3#Issue756)")
    p.add_argument("--reason", default="", help="--by 전결 사유(필수)")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("reject", help="반려 — 기본 draft 삭제 · --return 이면 반송(draft 보존 → 매뉴얼핀봇 재배분)")
    p.add_argument("--role", required=True); p.add_argument("--reason", required=True)
    p.add_argument("--by", default="", help="총괄 bot_id — 반려를 C 결정으로 기록. 생략은 비봇 세션만(prj3#Issue946)")
    p.add_argument("--return", dest="return_", action="store_true",
                   help="반송 — draft 보존·작성 표지 제거·사유 머리 첨부·origin_seen 불변 → 본사 팀장 재배분 요청 "
                        "(prj3#Issue948). 재배분 요청 적재 실패 시 exit 2")
    p.set_defaults(fn=cmd_reject)

    p = sub.add_parser("inject", help="출근 주입본 출력 — frontmatter revisions: 제외 (prj3#Issue767)")
    p.add_argument("--role"); p.add_argument("--file")
    p.set_defaults(fn=cmd_inject)

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
