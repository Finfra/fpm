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

# ── 판정 임계 (근거 없는 개정 금지 — 표본 미달이면 아예 판정하지 않는다) ────────
MIN_EVENTS = 3          # role 당 최소 표본. 미만이면 "판정 보류"
BLOCK_RATE_MIN = 0.30   # blocked/failed 비율
RETRY_RATE_MIN = 0.30   # attempts >= 2 비율
IDLE_RATE_MIN = 0.50    # 출근했는데 current_task 가 빈 세션 비율
MISMATCH_MIN = 1        # 엄격형(strict) role 인데 hash 증적 없이 done 처리된 건수
OBS_FAIL_MIN = 3        # 실패 키워드를 동반한 observation 언급 건수

HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
OBS_FAIL_RE = re.compile(r"실패|오류|에러|반송|재시도|blocked|failed", re.I)
ACK_OK = ("confirmed", "acked_done")   # dismissed = 승인 아님(반려·무시) → 정본 반영 거부


class FbotError(Exception):
    """fail-loud 용 — 메시지를 stderr 에 내고 exit != 0."""


def die(msg):
    raise FbotError(msg)


def today():
    return datetime.now().strftime("%Y.%m.%d")


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

def evaluate(role, st, obs_fail, completion):
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

    if obs_fail >= OBS_FAIL_MIN:
        sig.append((
            "obs_failure_mentions",
            "learn.db observation 중 본 role 봇을 실패 문맥으로 언급 %d건 (≥ 임계 %d)"
            % (obs_fail, OBS_FAIL_MIN),
            "반복 언급된 실패 문맥을 「경계·금지」 절의 금지 항목으로 승격할 것을 제안한다."))
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
        sig = evaluate(role, st, obs.get(role, 0), fm.get("completion", ""))
        if not sig:
            skipped.append((role, st))
            continue
        if args.dry_run:
            made.append((role, sig, True))
            continue
        write_draft(draft_path(role), render_draft(role, text, sig, st, obs.get(role, 0)))
        made.append((role, sig, False))

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


def cmd_propose(args):
    drafts = list_drafts()
    if not drafts:
        print("draft 없음 — 먼저 `review` 를 실행한다. 등록할 컨펌이 없다.")
        return 0
    if not os.access(MQ_ENQUEUE, os.X_OK):
        die("mq helper 없음·실행 불가: %s (직접 큐 Write 금지 — helper 경유가 유일 경로)" % MQ_ENQUEUE)
    out = []
    for d in drafts:
        role = os.path.basename(d)[:-len(DRAFT_SUFFIX)]
        msg = ("[컨펌] %s — role: %s. 개정 초안 %s 를 정본에 반영할지 사람 전결 요청. "
               "승인 시 `~/.claude/hooks/fbot-manual-review.py apply --role %s`, "
               "반려 시 `reject --role %s --reason \"…\"`. 정본은 승인 전까지 무변경."
               % (CONFIRM_MARK, role, d, role, role))
        cmd = [MQ_ENQUEUE, "--message", msg, "--due", "+0d", "--from-bot", "fbot-taskmgr"]
        if args.dry_run:
            print("[dry-run] %s" % " ".join(cmd))
            continue
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            die("mq 등록 실패(role=%s): %s" % (role, (p.stderr or p.stdout).strip()))
        out.append((role, p.stdout.strip()))
    for role, res in out:
        print("* %s → %s" % (role, res))
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
               0, "fbot-taskmgr", None, None, now))
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
    print("✅ %s 정본 반영 (승인 %s · %s) · draft 삭제 · job 원장 %s" % (role, ack.get("id"), ack.get("ack_ts"), jid))
    return 0


def cmd_reject(args):
    role = args.role
    d = draft_path(role)
    if not os.path.exists(d):
        die("draft 없음: %s" % d)
    os.remove(d)
    jid = record_job(role, "rejected", args.reason)
    print("🚫 %s draft 폐기 · 사유 job 원장 기록 %s: %s" % (role, jid, args.reason))
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
