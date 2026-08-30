#!/usr/bin/env python3
"""fbot-exec-report.py — 중역핀봇 보고 파이프라인 (Issue436_3 s6 보고 계열).

계약: ~/.claude/_doc_arch/fbot-arch.md §조직(중역핀봇 — daily report·온디맨드 현황) ·
      §hub 주입(보고 폴백 사다리 3단, 각 단 전환 fail-loud) ·
      §범용 배포 요건(Discord/openclaw = 옵션 플러그 · 외부 발신은 sanitize 계열 필터 경유) ·
      §Discord 발신 경로 확정행(2026-08-25 실측) · §작업 기록(F4 — 봇 전용 대장 금지).
      계약은 참조만 하며 여기서 재결정하지 않는다.

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

서브커맨드
  daily [--dry-run] [--target ID] [--cwd DIR] [--no-record]
      일일 보고 조립·발신. ① 재료 수집(registry.db 봇 현황·상태별 수·채용/배분 원장 +
      aoa-mq digest + job 원장 요약) ② sanitize 필터 ③ 폴백 사다리 발신
      ④ bot_id=fbot-exec 귀속 job 기록(kind=fbot_report)
  now   [--dry-run] [--target ID] [--cwd DIR] [--no-record]
      온디맨드 현황 스냅샷. daily 보다 간략 — 지금 상태만(원장 breakdown·큐 상세 없음)

폴백 사다리 3단 (계약)
  ① Discord(openclaw message send --channel discord --account clawm4)
  ② hub 렌더 — `<cwd>/_doc_work/htm/` 에 파일 생성. **hub OFF·수면 중이면 건너뜀**
  ③ 파일 보고 단독 — ~/.claude/data/fbot/reports/YYYY-MM-DD.md (최후 단, 항상 성립)
  각 단 전환은 fail-loud: stderr 1줄 + router.log(JSONL) + 폴백 보고문 안 "폴백 사유" 절.
  무음 스킵 금지 — openclaw 부재·gateway 미기동·발신 실패 전부 사유를 남기고 내려간다.

sanitize 가드 (새 외부 출구 — Discord)
  3단 + 발신 직전 assert.
    A. 이슈 제목 축약 — `Issue<N>: <제목 전문>` → `Issue<N>(요약…)` (비공개 정보 유출 차단)
    B. 리터럴 치환 — prj1 `scripts/fpm-sanitize.sh` **호출**(재구현 아님). publishable-policy.yml
       의 sanitize[] 쌍(개인 경로·계정·호스트·사설 프로젝트명)을 그대로 적용. 부재 시 경고 후 C 만.
    C. 구조 패턴 — `/Users/<user>`→`$HOME` · 이메일 · 토큰(sk-/ghp_/xox)·32자+ hex → 치환
    D. **발신 직전 assert** — 위 패턴 잔존 검사. 1건이라도 걸리면 발신 중단(fail-loud, exit 3).
       assert 는 sanitize 안이 아니라 **발신 경계**에 있다 — 필터를 우회해 들어온 텍스트도 막는다.

테스트 훅 (검증 전용 — 운영 경로 아님)
  FBOT_REPORT_TEST_MATERIAL : sanitize **전**에 본문에 덧붙임 → 필터가 지우는지 확인용
  FBOT_REPORT_TEST_INJECT   : sanitize **후**에 덧붙임 → 발신 직전 assert 가 막는지 확인용
  FBOT_REPORT_OPENCLAW      : openclaw 실행 파일 경로 강제(빈 값 = 부재로 취급, 폴백 시험)

설계 원칙 (fbot-state.py·fbot-taskmgr.py·fbot-manual-review.py 승계)
  * 표준 라이브러리만 사용(무의존). policy.yml 은 평탄 키라 정규식으로 읽는다.
  * 판정 단일 지점 재사용 — hub on/off = hooks/hub-scope.sh `hub_effective`,
    수면 = hooks/sleep-state.sh `sleep_is_active`, 리터럴 치환 = prj1 fpm-sanitize.sh.
    어느 것도 여기서 재구현하지 않는다.
  * aoa-mq digest 는 **큐 사본 샌드박스**에서 호출한다(AOA_MQ_DIR) — 타 repo 산출물
    (Aoa-mq-list.md) 을 건드리지 않으면서 생성기 포맷을 그대로 쓴다.
  * 실발신은 외부 노출이다 — `--dry-run` 은 openclaw `--dry-run` 으로 그대로 전달된다.
"""

import argparse
import glob
import json
import urllib.request
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime

# ── 경로 ─────────────────────────────────────────────────────────────────────

HOME = os.path.expanduser("~")
# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
AOA_DIR = os.environ.get("AOA_MEMORY_DIR") or os.path.join(HOME, ".claude", "data", "aoa")
REGISTRY_DB = os.path.join(AOA_DIR, "registry.db")
POLICY_YML = os.path.join(AOA_DIR, "policy.yml")
MQ_DIR = os.environ.get("AOA_MQ_DIR") or os.path.join(AOA_DIR, "mq")
MQ_DIGEST_SH = os.path.join(HOME, ".claude", "mcp", "aoa-mq", "aoa-mq-digest.sh")
FPM_SANITIZE_SH = os.path.join(HOME, "_git", "___pm", "scripts", "fpm-sanitize.sh")
HUB_SCOPE_SH = os.path.join(HOME, ".claude", "hooks", "hub-scope.sh")
SLEEP_STATE_SH = os.path.join(HOME, ".claude", "hooks", "sleep-state.sh")

REPORT_DIR = os.environ.get("FBOT_REPORT_DIR") or os.path.join(HOME, ".claude", "data", "fbot", "reports")
ROUTER_LOG = os.path.join(REPORT_DIR, "router.log")
FALLBACK_HTM_DIR = os.path.join(HOME, ".claude", "_doc_work", "htm")

# ── 상수 (계약 고정값) ────────────────────────────────────────────────────────

BOT_ID = "fbot-exec"            # 기록 귀속 주체 (F4 — 계약 §조직: 중역핀봇 전역 1개)
JOB_KIND = "fbot_report"        # registry.job 보고 기록 kind
JOB_STORE = "fbot"
DISCORD_CHANNEL = "discord"
DISCORD_ACCOUNT = "clawm4"      # 계약 §Discord 발신 경로 확정행(2026-08-25 실측)
POLICY_TARGET_KEY = "fbot_report_discord_target"

ISSUE_SUMMARY_LEN = 24          # 이슈 제목 축약 길이 — 번호 + 한 줄 요약만 내보낸다
JOB_RECENT_SECS = 24 * 3600     # job 원장 요약 창

ROLE_KO = {
    "exec": "중역", "hr": "인사", "taskmgr": "작업", "design": "설계",
    "planner": "기획자", "qa": "QA", "research": "리서치",
}
STATE_KO = {
    "checkin": "출근중", "working": "작업중", "waiting_input": "수신대기",
    "waiting_child": "완료대기", "checkout": "퇴근",
}
STATE_BADGE = {
    "checkin": "🔵", "working": "🟢", "waiting_input": "🟡",
    "waiting_child": "🟡", "checkout": "⚪",
}
ACTIVE_STATES = ("checkin", "working", "waiting_input", "waiting_child")


class FbotError(Exception):
    """fail-loud — 인프라·입력 오류. stderr + exit 2."""


class SanitizeError(Exception):
    """발신 직전 assert 실패 — 발신 중단. stderr + exit 3."""


# ── sanitize ─────────────────────────────────────────────────────────────────

# A. 이슈 제목 축약: `Issue436_3: 제목 전문…` → `Issue436_3(제목 전문… 앞 24자)`
ISSUE_TITLE_RE = re.compile(r"(Issue\d+(?:_\d+)*)\s*[::]\s*([^\n|]+)")

# C. 구조 패턴 (치환) — 순서 고정. 경로가 먼저여야 경로 안 이메일 오탐이 없다.
STRUCTURAL_SUBS = [
    (re.compile(r"/Users/[A-Za-z0-9._-]+"), "$HOME"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"), "<redacted-token>"),
    (re.compile(r"\bghp_[A-Za-z0-9]{10,}"), "<redacted-token>"),
    (re.compile(r"\bxox[A-Za-z]-?[A-Za-z0-9\-]{6,}"), "<redacted-token>"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<redacted-email>"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "<redacted-hex>"),
]

# D. 발신 직전 assert (잔존 검사) — 치환 목록과 같은 축. 1건이라도 걸리면 발신 중단.
RESIDUAL_CHECKS = [
    ("절대경로(/Users/…)", re.compile(r"/Users/[A-Za-z0-9._-]+")),
    ("토큰(sk-)", re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}")),
    ("토큰(ghp_)", re.compile(r"\bghp_[A-Za-z0-9]{10,}")),
    ("토큰(xox)", re.compile(r"\bxox[A-Za-z]-?[A-Za-z0-9\-]{6,}")),
    ("이메일", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("32자+ hex", re.compile(r"\b[0-9a-fA-F]{32,}\b")),
]


def _collapse_issue_titles(text: str) -> str:
    def rep(m):
        num, title = m.group(1), m.group(2).strip()
        if len(title) > ISSUE_SUMMARY_LEN:
            title = title[:ISSUE_SUMMARY_LEN] + "…"
        return f"{num}({title})"
    return ISSUE_TITLE_RE.sub(rep, text)


def _fpm_literal_stage(text: str, warnings: list) -> str:
    """prj1 fpm-sanitize.sh 호출 — 리터럴 치환쌍 재사용(재구현 금지).

    스크립트는 트리 대상 in-place 치환이므로 임시 트리에 본문을 놓고 돌린다.
    부재·실패는 fail-loud 경고를 남기고 구조 패턴 단계로만 진행한다(조용한 통과 금지).
    """
    if not os.path.exists(FPM_SANITIZE_SH):
        warnings.append(f"sanitize B단계 생략 — prj1 fpm-sanitize.sh 없음({FPM_SANITIZE_SH})")
        return text
    with tempfile.TemporaryDirectory(prefix="fbot-sanitize-") as td:
        fp = os.path.join(td, "body.md")
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(text)
        proc = subprocess.run([FPM_SANITIZE_SH, td], capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()
            warnings.append(
                "sanitize B단계 실패(exit %d) — 구조 패턴만 적용: %s"
                % (proc.returncode, tail[-1] if tail else "출력 없음")
            )
            return text
        with open(fp, encoding="utf-8") as fh:
            return fh.read()


def sanitize_text(text: str, warnings: list | None = None) -> str:
    """A→B→C 3단 필터. 발신 직전 assert(D)는 별도 — assert_clean() 가 경계에서 본다."""
    warnings = warnings if warnings is not None else []
    out = _collapse_issue_titles(text)
    out = _fpm_literal_stage(out, warnings)
    for pat, repl in STRUCTURAL_SUBS:
        out = pat.sub(repl, out)
    return out


def assert_clean(text: str) -> None:
    """발신 직전 잔존 검사. 걸리면 SanitizeError — 발신하지 않는다(fail-loud)."""
    hits = []
    for name, pat in RESIDUAL_CHECKS:
        found = pat.findall(text)
        if found:
            hits.append(f"{name} {len(found)}건")
    if hits:
        raise SanitizeError(
            "발신 중단 — sanitize 잔존 검사 실패: " + " · ".join(hits)
            + " (필터 우회 경로 의심 — 본문 조립부를 점검할 것)"
        )


# ── policy / DB ──────────────────────────────────────────────────────────────

def load_report_target() -> str:
    """aoa policy.yml 의 fbot_report_discord_target. 파일·키 부재·공백 = 빈 문자열(→ 폴백)."""
    if not os.path.exists(POLICY_YML):
        return ""
    pat = re.compile(r"^%s:\s*(.*)$" % re.escape(POLICY_TARGET_KEY))
    with open(POLICY_YML, encoding="utf-8") as fh:
        for line in fh:
            m = pat.match(line)
            if not m:
                continue
            val = m.group(1)
            val = re.sub(r"\s+#.*$", "", val).strip().strip("\"'")
            return val
    return ""


def connect() -> sqlite3.Connection:
    if not os.path.exists(REGISTRY_DB):
        raise FbotError(f"레지스트리 DB 없음: {REGISTRY_DB} (AOA_MEMORY_DIR 확인)")
    con = sqlite3.connect(REGISTRY_DB, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def month_key(now: float | None = None) -> str:
    return time.strftime("%Y-%m", time.localtime(now if now is not None else time.time()))


def kv_int(con, ns: str, key: str) -> int:
    row = con.execute("SELECT value FROM kv WHERE ns = ? AND key = ?", (ns, key)).fetchone()
    try:
        return int(row["value"]) if row is not None else 0
    except (TypeError, ValueError):
        return 0


def collect_registry(con) -> dict:
    """봇 현황·상태별 수·채용/배분 건수·job 원장 요약 (재료 ①③)."""
    bots = [dict(r) for r in con.execute(
        "SELECT bot_id, title, role, state, current_task, prj, lease_expires FROM bot"
        " ORDER BY role, bot_id").fetchall()]
    by_state = {}
    for b in bots:
        by_state[b["state"]] = by_state.get(b["state"], 0) + 1
    month = month_key()
    active_dispatch = con.execute(
        "SELECT COUNT(*) c FROM job WHERE kind='fbot_dispatch' AND status IN ('open','blocked')"
    ).fetchone()["c"]
    since = int(time.time()) - JOB_RECENT_SECS
    recent = [dict(r) for r in con.execute(
        "SELECT kind, status, COUNT(*) c FROM job WHERE created_at >= ?"
        " GROUP BY kind, status ORDER BY c DESC", (since,)).fetchall()]
    totals = [dict(r) for r in con.execute(
        "SELECT kind, COUNT(*) c FROM job GROUP BY kind ORDER BY c DESC").fetchall()]
    return {
        "bots": bots,
        "by_state": by_state,
        "active": sum(by_state.get(s, 0) for s in ACTIVE_STATES),
        "month": month,
        "hired": kv_int(con, "fbot:budget", month),
        "dispatched": kv_int(con, "fbot:dispatch", month),
        "active_dispatch": active_dispatch,
        "job_recent": recent,
        "job_totals": totals,
    }


# ── aoa-mq digest (재료 ②) ───────────────────────────────────────────────────

MQ_COUNT_RE = re.compile(r"미종결\s*(\d+)\s*건")
MQ_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")


def collect_mq(warnings: list) -> dict:
    """digest 스크립트가 있으면 **큐 사본 샌드박스**에서 호출(타 repo 산출물 불변).

    부재·실패 시 큐 JSON 직접 집계로 내려가되 사유를 warnings 에 남긴다(무음 금지).
    """
    queue = os.path.join(MQ_DIR, "queue")
    if not os.path.isdir(queue):
        warnings.append(f"aoa-mq 큐 디렉토리 없음 — 대기 큐 재료 생략: {queue}")
        return {"source": "none", "pending": 0, "due": 0, "items": []}

    if os.path.exists(MQ_DIGEST_SH):
        with tempfile.TemporaryDirectory(prefix="fbot-mq-") as td:
            try:
                shutil.copytree(queue, os.path.join(td, "queue"))
                env = dict(os.environ, AOA_MQ_DIR=td)
                proc = subprocess.run([MQ_DIGEST_SH], capture_output=True, text=True, env=env)
                listmd = os.path.join(td, "Aoa-mq-list.md")
                if proc.returncode == 0 and os.path.exists(listmd):
                    with open(listmd, encoding="utf-8") as fh:
                        text = fh.read()
                    m = MQ_COUNT_RE.search(text)
                    pending = int(m.group(1)) if m else 0
                    items, due = [], 0
                    for line in text.splitlines():
                        rm = MQ_ROW_RE.match(line)
                        if not rm or rm.group(1).startswith((":", "상태")):
                            continue
                        when, msg, src, mid = (g.strip() for g in rm.groups())
                        if "due" in when:
                            due += 1
                        items.append({"when": when, "summary": msg, "id": mid})
                    return {"source": "digest", "pending": pending, "due": due, "items": items}
                tail = (proc.stderr or proc.stdout).strip().splitlines()
                warnings.append(
                    "aoa-mq digest 호출 실패(exit %d) — 큐 직접 집계로 대체: %s"
                    % (proc.returncode, tail[-1] if tail else "출력 없음")
                )
            except OSError as e:
                warnings.append(f"aoa-mq digest 샌드박스 준비 실패 — 큐 직접 집계로 대체: {e}")
    else:
        warnings.append(f"aoa-mq digest 스크립트 없음 — 큐 직접 집계로 대체: {MQ_DIGEST_SH}")

    items, due = [], 0
    for fp in sorted(glob.glob(os.path.join(queue, "*.json"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            warnings.append(f"큐 파일 파싱 실패 — 집계 제외: {os.path.basename(fp)} ({e})")
            continue
        if d.get("acked"):
            continue
        status = str(d.get("status", ""))
        if status == "due":
            due += 1
        msg = re.sub(r"\s+", " ", str(d.get("message", "")))[:80]
        items.append({"when": f"{d.get('due_ts', '?')} {status}", "summary": msg,
                      "id": str(d.get("id", "?"))})
    return {"source": "queue", "pending": len(items), "due": due, "items": items}


# ── 본문 조립 ────────────────────────────────────────────────────────────────

def _bot_row(b: dict) -> str:
    badge = STATE_BADGE.get(b["state"], "⚫")
    role = ROLE_KO.get(b["role"], b["role"])
    title = b["title"] or b["bot_id"]
    task = (b["current_task"] or "—").strip() or "—"
    return f"| {title} | {role} | {badge} {STATE_KO.get(b['state'], b['state'])} | {task} |"


def hub_links() -> list:
    """prj1#Issue427: 보고 말미에 붙일 hub 링크 — **hub 에 물어서** 만든다.

    이 링크가 이 체인의 존재 이유다. Discord 알림을 외부망(셀룰러)에서 받았을 때
    눌러서 넘어갈 대상이 없으면, 알림은 "무슨 일이 있었다" 만 알리고 끝난다.

    ⚠️ 주소를 하드코딩하지 않는다(Issue425) — `/healthz` 의 `advertise_url` 을 쓴다.
       그 값이 없으면(= 사용자가 외부 공유를 켜지 않았거나 루프백 전용 머신)
       **링크를 만들지 않는다.** localhost 로 때우면 폰에서 열리지 않는 링크가 가고,
       받는 쪽은 그것이 죽은 링크인지 hub 가 꺼진 것인지 구분할 수 없다.
    """
    port = os.environ.get("HTM_SERVER_PORT", "9876")
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz", timeout=3) as r:
            base = (json.loads(r.read().decode("utf-8")) or {}).get("advertise_url")
    except Exception:
        return []
    if not base:
        return []
    return ["", "---", "", f"* 예약 큐 열기 → {base}/mq", f"* hub 열기 → {base}/hub"]


def build_daily(reg: dict, mq: dict, warnings: list) -> str:
    now = datetime.now()
    lines = [f"# 중역핀봇 일일 보고 — {now:%Y-%m-%d} ({now:%H:%M})", ""]
    lines += [f"## 봇 현황 — 총 {len(reg['bots'])} · 활성 {reg['active']}", ""]
    if reg["bots"]:
        lines += ["| 호칭 | 종류 | 상태 | 현재 작업 |", "| :--- | :--- | :--- | :--- |"]
        lines += [_bot_row(b) for b in reg["bots"]]
    else:
        lines.append("* 등재 봇 없음")
    lines.append("")
    by_state = " · ".join(f"{STATE_KO.get(k, k)} {v}" for k, v in sorted(reg["by_state"].items()))
    lines.append("* 상태별: " + (by_state or "—"))
    lines += ["", f"## 인사·배분 — {reg['month']}", "",
              f"* 채용(스폰) {reg['hired']}건 · 배분 {reg['dispatched']}건 · 활성 배분 {reg['active_dispatch']}건"]
    lines += ["", "## 작업 원장 (최근 24시간)", ""]
    if reg["job_recent"]:
        lines += [f"* {r['kind']} / {r['status']} — {r['c']}건" for r in reg["job_recent"]]
    else:
        lines.append("* 최근 24시간 신규 job 없음")
    lines.append("* 누적: " + (" · ".join(f"{r['kind']} {r['c']}" for r in reg["job_totals"]) or "—"))
    lines += ["", f"## 대기 큐 (aoa-mq · 출처 {mq['source']})", "",
              f"* 미종결 {mq['pending']}건 (기한 도래 {mq['due']}건)"]
    for it in mq["items"][:3]:
        lines.append(f"    - {it['when']} — {it['summary']}")
    if len(mq["items"]) > 3:
        lines.append(f"    - … 외 {len(mq['items']) - 3}건")
    if warnings:
        lines += ["", "## 수집 경고 (fail-loud)", ""] + [f"* {w}" for w in warnings]
    extra = os.environ.get("FBOT_REPORT_TEST_MATERIAL")
    if extra:
        lines += ["", "## 테스트 재료 (FBOT_REPORT_TEST_MATERIAL)", "", extra]
    return "\n".join(lines) + "\n"


def build_now(reg: dict, mq: dict, warnings: list) -> str:
    now = datetime.now()
    lines = [f"# 중역핀봇 현황 — {now:%Y-%m-%d %H:%M}", ""]
    lines.append("* 봇 %d (활성 %d / 퇴근 %d) · 활성 배분 %d · 대기 큐 %d(도래 %d)" % (
        len(reg["bots"]), reg["active"], reg["by_state"].get("checkout", 0),
        reg["active_dispatch"], mq["pending"], mq["due"]))
    active = [b for b in reg["bots"] if b["state"] in ACTIVE_STATES]
    if active:
        lines += ["", "| 호칭 | 상태 | 현재 작업 |", "| :--- | :--- | :--- |"]
        for b in active:
            badge = STATE_BADGE.get(b["state"], "⚫")
            lines.append("| %s | %s %s | %s |" % (
                b["title"] or b["bot_id"], badge, STATE_KO.get(b["state"], b["state"]),
                (b["current_task"] or "—").strip() or "—"))
    else:
        lines.append("* 활성 봇 없음 (전원 퇴근)")
    if warnings:
        lines.append("* ⚠️ " + " / ".join(warnings))
    extra = os.environ.get("FBOT_REPORT_TEST_MATERIAL")
    if extra:
        lines.append("* 테스트 재료: " + extra)
    return "\n".join(lines) + "\n"


# ── 폴백 사다리 ──────────────────────────────────────────────────────────────

def _sh_func(script: str, call: str) -> str:
    """판정 단일 지점(bash 헬퍼) 호출 — 재구현 금지."""
    proc = subprocess.run(["bash", "-c", f'. "{script}" >/dev/null 2>&1; {call}'],
                          capture_output=True, text=True)
    return (proc.stdout or "").strip()


def hub_is_on(cwd: str) -> bool:
    if not os.path.exists(HUB_SCOPE_SH):
        return False
    return _sh_func(HUB_SCOPE_SH, f'hub_effective "{cwd}"') == "on"


def sleep_is_active(cwd: str) -> bool:
    if not os.path.exists(SLEEP_STATE_SH):
        return False
    proc = subprocess.run(
        ["bash", "-c", f'. "{SLEEP_STATE_SH}" >/dev/null 2>&1; sleep_is_active "{cwd}"'],
        capture_output=True, text=True)
    return proc.returncode == 0


def openclaw_bin() -> str:
    """openclaw 실행 파일 탐지.

    prj3#Issue475: `shutil.which` 만으로는 부족하다 — **설치돼 있어도 못 찾는다.**
      fg1 실측: openclaw 가 nvm 아래(`~/.nvm/versions/node/<ver>/bin/openclaw`)에
      설치돼 gateway 까지 돌고 있는데, nvm 은 셸 초기화 스크립트가 PATH 에 넣어 주는
      구조라 **로그인 셸에서조차 안 잡혔다**. hook·cron 은 그 초기화를 거치지 않으므로
      which 는 영원히 None 이고, rung1(Discord)은 한 번도 쓰이지 못한 채 파일로만
      떨어진다 — "미설치" 와 구분되지 않는 조용한 실패였다.
      (jm4 는 homebrew 설치라 PATH 에 있어 이 함정이 드러나지 않았다.)
    """
    forced = os.environ.get("FBOT_REPORT_OPENCLAW")
    if forced is not None:            # 빈 문자열 = 의도적 부재(폴백 시험)
        return forced if forced and os.path.exists(forced) else ""
    found = shutil.which("openclaw")
    if found:
        return found
    # 셸 초기화에 의존하는 설치 경로들. 최신 node 버전 우선(역순 정렬).
    cands = sorted(glob.glob(os.path.expanduser(
        "~/.nvm/versions/node/*/bin/openclaw")), reverse=True)
    cands += ["/opt/homebrew/bin/openclaw", "/usr/local/bin/openclaw",
              os.path.expanduser("~/.local/bin/openclaw")]
    for c in cands:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ""


def log_transition(entry: dict) -> None:
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(ROUTER_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def fallback_streak_days() -> int:
    """마지막 ① 성공 이후 경과 일수 — 폴백 장기화를 보고문에 병기(plan 리스크 완화)."""
    if not os.path.exists(ROUTER_LOG):
        return 0
    last = None
    try:
        with open(ROUTER_LOG, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("rung") == 1 and not e.get("dry_run"):
                    last = e.get("ts")
    except OSError:
        return 0
    if not last:
        return -1                      # ① 성공 이력 자체가 없음
    try:
        return (datetime.now() - datetime.fromisoformat(last)).days
    except ValueError:
        return 0


def send_discord(body: str, target: str, dry_run: bool) -> tuple[bool, str]:
    binp = openclaw_bin()
    if not binp:
        return False, "openclaw 미탐지(PATH·FBOT_REPORT_OPENCLAW) — Discord 단 불가"
    if not target:
        return False, (f"발신 대상 미설정 — aoa policy.yml `{POLICY_TARGET_KEY}` 공백이고 "
                       "--target 도 없음")
    assert_clean(body)                 # ⚠️ 발신 경계 assert — 여기를 통과해야만 나간다
    cmd = [binp, "message", "send", "--channel", DISCORD_CHANNEL,
           "--account", DISCORD_ACCOUNT, "--target", target, "--message", body, "--json"]
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return False, ("openclaw 발신 실패(exit %d): %s"
                       % (proc.returncode, tail[-1] if tail else "출력 없음"))
    return True, (proc.stdout or "").strip()[:400]


def hub_available(cwd: str) -> tuple[bool, str]:
    """② 단 가용성 판정만 — 쓰기 없음. 사유 절을 붙인 최종 본문을 **한 번만** 쓰기 위해 분리."""
    if sleep_is_active(cwd):
        return False, "수면 모드 활성 — hub 렌더 단 건너뜀(계약 §hub 주입)"
    if not hub_is_on(cwd):
        return False, f"hub OFF(effective) — hub 렌더 단 건너뜀 (cwd={cwd})"
    return True, ""


def render_hub(body: str, cwd: str, mode: str) -> tuple[bool, str]:
    out_dir = os.path.join(cwd, "_doc_work", "htm")
    if not os.path.isdir(out_dir):
        out_dir = FALLBACK_HTM_DIR
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"hub_htm_{ts}_a_fbot-{mode}-report.md")
    fm = ("---\n"
          f"name: fbot-{mode}-report\n"
          f"description: \"중역핀봇 {mode} 보고 — Discord 단 불가로 hub 렌더 폴백\"\n"
          f"date: {datetime.now():%Y.%m.%d}\n"
          "---\n\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(fm + body)
    return True, path


def write_file_report(body: str) -> tuple[bool, str]:
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{datetime.now():%Y-%m-%d}.md")
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as fh:
        if new:
            fh.write("---\n"
                     f"name: fbot-report-{datetime.now():%Y.%m.%d}\n"
                     "description: \"중역핀봇 보고 — 파일 보고 단독(폴백 사다리 3단)\"\n"
                     f"date: {datetime.now():%Y.%m.%d}\n"
                     "---\n\n")
        else:
            fh.write("\n---\n\n")
        fh.write(body)
    return True, path


def route(body: str, *, mode: str, target: str, dry_run: bool, cwd: str) -> dict:
    """폴백 사다리 3단. 각 단 전환은 fail-loud — stderr + router.log + 보고문 사유 절."""
    transitions = []

    ok, info = send_discord(body, target, dry_run)
    if ok:
        result = {"rung": 1, "channel": "discord", "detail": info, "transitions": transitions}
    else:
        transitions.append({"rung": 1, "reason": info})
        print(f"🚨 폴백 ①→② (Discord 단 불가): {info}", file=sys.stderr)

        streak = fallback_streak_days()
        streak_txt = ("① 성공 이력 없음" if streak < 0 else f"마지막 Discord 발신 이후 {streak}일")
        notice_src = ["", "---", "", "## 폴백 사유 (fail-loud)", ""]
        notice_src += [f"* ① Discord — {t['reason']}" for t in transitions]

        ok2, why2 = hub_available(cwd)
        if not ok2:
            transitions.append({"rung": 2, "reason": why2})
            print(f"🚨 폴백 ②→③ (hub 렌더 단 불가): {why2}", file=sys.stderr)
            notice_src.append(f"* ② hub 렌더 — {why2}")
        notice_src.append(f"* 폴백 지속: {streak_txt}")
        notice = sanitize_text("\n".join(notice_src) + "\n")
        full = body + notice          # 폴백 산출물은 사유 절을 **본문 안에** 달고 나간다
        assert_clean(full)            # ⚠️ 폴백 산출물도 같은 경계 assert 를 지난다

        # 산출 쓰기는 단 1회 — 가용성 판정과 분리해 중복 파일 생성을 막는다
        if ok2:
            _, info2 = render_hub(full, cwd, mode)
            result = {"rung": 2, "channel": "hub", "detail": info2, "transitions": transitions}
        else:
            _, info3 = write_file_report(full)
            result = {"rung": 3, "channel": "file", "detail": info3, "transitions": transitions}

    log_transition({
        "ts": datetime.now().isoformat(timespec="seconds"), "mode": mode,
        "rung": result["rung"], "channel": result["channel"], "dry_run": dry_run,
        "transitions": transitions, "detail": result["detail"],
    })
    return result


# ── 작업 기록 (F4) ───────────────────────────────────────────────────────────

def record_job(con, *, mode: str, result: dict, dry_run: bool, target_set: bool, body: str) -> str:
    now = int(time.time())
    job_id = f"fbotrep-{now}-{os.urandom(4).hex()}"
    payload = {"mode": mode, "dry_run": dry_run, "target_set": target_set,
               "bytes": len(body.encode("utf-8"))}
    res = {"rung": result["rung"], "channel": result["channel"],
           "detail": result["detail"][:200],
           "transitions": [t["reason"][:120] for t in result["transitions"]]}
    con.execute(
        "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
        " owner, lease_until, blocked_since, created_at) VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?)",
        (job_id, JOB_STORE, JOB_KIND, "done", json.dumps(payload, ensure_ascii=False),
         json.dumps(res, ensure_ascii=False), 1, BOT_ID, now))
    return job_id


# ── 커맨드 ───────────────────────────────────────────────────────────────────

def _run(mode: str, args) -> int:
    cwd = os.path.abspath(args.cwd or os.getcwd())
    warnings: list = []
    con = connect()
    try:
        reg = collect_registry(con)
        mq = collect_mq(warnings)
        raw = build_daily(reg, mq, warnings) if mode == "daily" else build_now(reg, mq, warnings)
        body = sanitize_text(raw, warnings)
        # prj1#Issue427: hub 링크는 **sanitize 뒤에** 붙인다 (사용자 판정: 링크만 예외).
        #   sanitize 는 개인 호스트명을 host.tailnet.ts.net 으로 마스킹하는데, 그러면
        #   **눌러도 열리지 않는 주소**가 되어 링크의 존재 이유가 사라진다. 이 보고는
        #   본인 DM·Agent 채널로만 가고, tailnet 주소는 tailscale 로그인 없이는 접근
        #   자체가 불가하므로 실주소를 낸다. 본문의 다른 개인 경로·계정·사설 프로젝트명은
        #   그대로 마스킹된다 — 예외는 이 링크 줄에 한정된다.
        #   경계 assert(assert_clean)는 절대경로·토큰·이메일만 보므로 정상 통과한다.
        body = body.rstrip("\n") + "\n" + "\n".join(hub_links()) + "\n"

        inject = os.environ.get("FBOT_REPORT_TEST_INJECT")
        if inject:                     # 필터 우회 시나리오 — 경계 assert 가 잡아야 한다
            body += "\n" + inject + "\n"

        target = args.target or load_report_target()
        result = route(body, mode=mode, target=target, dry_run=args.dry_run, cwd=cwd)

        job_id = None
        if not args.no_record:
            job_id = record_job(con, mode=mode, result=result, dry_run=args.dry_run,
                                target_set=bool(target), body=body)
    finally:
        con.close()

    print(body)
    print(json.dumps({
        "ok": True, "mode": mode, "rung": result["rung"], "channel": result["channel"],
        "dry_run": args.dry_run, "target_set": bool(target),
        "transitions": result["transitions"], "detail": result["detail"],
        "job_id": job_id, "bot_id": BOT_ID, "kind": JOB_KIND,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_daily(args) -> int:
    return _run("daily", args)


def cmd_now(args) -> int:
    return _run("now", args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fbot-exec-report.py",
        description="중역핀봇 보고 — daily/온디맨드 조립 → sanitize → 폴백 사다리 3단 발신")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, helptxt in (
        ("daily", cmd_daily, "일일 보고 — registry+mq digest+job 원장 조합 후 발신"),
        ("now", cmd_now, "온디맨드 현황 — 지금 상태 스냅샷(daily 보다 간략)"),
    ):
        sp = sub.add_parser(name, help=helptxt)
        sp.add_argument("--dry-run", action="store_true",
                        help="openclaw --dry-run 으로 전달 — 실발신 0")
        sp.add_argument("--target", help=f"Discord 대상 id (미지정 시 policy {POLICY_TARGET_KEY})")
        sp.add_argument("--cwd", help="hub 스코프 판정·htm 출력 기준 디렉토리 (기본 현재 디렉토리)")
        sp.add_argument("--no-record", action="store_true", help="job 기록 생략(검증용)")
        sp.set_defaults(func=fn)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SanitizeError as e:
        # QA 발견 ② — assert 는 log_transition 이전이라 그대로 두면 "보고 완전 소실"이
        # 로그에 흔적조차 없다. 본문은 남기지 않고(유출 방지) 사실만 기록한다.
        print(f"🚨 {e}", file=sys.stderr)
        try:
            log_transition({"ts": int(time.time()), "event": "sanitize_abort",
                            "reason": str(e), "sent": False, "body_logged": False})
        except Exception:
            pass          # 로깅 실패가 차단을 무르게 하지 않는다
        return 3
    except FbotError as e:
        print(f"🚨 {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
