#!/usr/bin/env python3
"""test-notify.py — aoa-memory 완료 통지(UPS 가속 B)·종결 job GC 정합 (prj3#Issue938)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

무엇을 지키나 — UserPromptSubmit 이 매 프롬프트 주입하는 «종결된 배치 잡» 통지가 **회수 대상만** 싣고,
job 테이블이 불어나지 않는다. 실측(2026-10-04) 결함 3종:
  ① 배치 잡이 아닌 행(fbot_event·sel_event·fbot_request …)까지 통지 — 24h 316회 주입
  ② job GC 정기 배선 없음 — 30일 경과 579건 잔존
  ③ 전달 표식(kv ns=notify) 30일 TTL 만료 뒤 재통지 — 576건
지키는 성질 —
  · 통지는 **구독 행**(kv ns=notify-want — `learn_index` 가 세션 요청 잡에 남긴다)이 있는 배치 kind 잡만 — 스케줄러가
    30분마다 만드는 consolidation·원장(`fbot_*`)·sel_event 는 구독이 없어 침묵
  · 구독 행은 **소비형**이다 — 전달하면 지운다. 전달 표식 TTL 이 없으니 TTL 만료 뒤 재통지가 구조적으로 불가
  · 통지 쿼리는 job 을 상태 인덱스로 훑지 않는다(구독 행 → job PK 조회)
  · GC 는 **배치 kind**(consolidation·index)의 종결 행만 지운다 — fbot 원장은 영구(fbot-arch §로깅 규약)·sel_event 는
    selection.py 의 롤업 뒤 삭제라 소유가 다르다. 진행 중 잡(pending·running·pending_batch)은 지우지 않는다
  · `gc` 의 job 부분은 관측 에이징 게이트(watermark·적격 0건 조기 반환) 뒤에 숨지 않는다
  · `gc --jobs` 는 관측(learn.db)을 건드리지 않는다 — 정기 tick 은 이것만 건다

격리: AOA_MEMORY_DIR 임시 폴더. 실 DB 는 열지 않는다.
실행: python3 mcp/aoa-memory/test-notify.py
"""
import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = tempfile.mkdtemp(prefix="aoa-notify-")
os.environ["AOA_MEMORY_DIR"] = os.path.join(ROOT, "aoa0")
sys.path.insert(0, HERE)
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name} {str(detail)[:300]}")


import store as S      # noqa: E402
import worker as W     # noqa: E402
import notify as N     # noqa: E402
import server as SV    # noqa: E402

DAY = 86400
POL = {"job_retention_days": 30, "observation_retention_days": 90}


def rc():
    c = sqlite3.connect(S.REGISTRY_DB)
    c.row_factory = sqlite3.Row
    return c


def reset():
    with rc() as c:
        c.execute("DELETE FROM job")
        c.execute("DELETE FROM kv")
        c.commit()
    bdir = os.path.join(S.AOA_DIR, "backup")
    shutil.rmtree(bdir, ignore_errors=True)


def job(jid, kind, status, age_days=0, store="learn", result=None, want=False, want_exp=None):
    """job 1행(+선택 구독 행). age_days 만큼 과거에 만들어진 것으로 적는다."""
    created = S.now() - int(age_days * DAY)
    with rc() as c:
        c.execute("INSERT INTO job(id, store, kind, status, payload, result, attempts, owner, "
                  "lease_until, blocked_since, created_at) VALUES(?,?,?,?,NULL,?,0,NULL,NULL,NULL,?)",
                  (jid, store, kind, status, result, created))
        if want:
            S.notify_subscribe(c, jid)
            if want_exp is not None:
                c.execute("UPDATE kv SET expires_at=? WHERE ns=? AND key=?", (want_exp, S.NOTIFY_WANT_NS, jid))
        c.commit()


def notify():
    """notify.main() 을 인프로세스로 1회 — (rc, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = N.main()
    return r, buf.getvalue()


def count(sql, *a):
    with rc() as c:
        return c.execute(sql, a).fetchone()[0]


def main():
    S.init_stores()

    print("\n[상수 — 통지·GC 가 같은 배치 kind 를 본다]")
    check("BATCH_JOB_KINDS = consolidation·index", tuple(S.BATCH_JOB_KINDS) == ("consolidation", "index"), S.BATCH_JOB_KINDS)
    check("구독 TTL ≥ job 보존 기간(정책 기본값) — 보존 중인 잡의 구독이 먼저 죽지 않는다",
          S.NOTIFY_WANT_TTL_SEC >= W.P.DEFAULTS["job_retention_days"] * DAY, S.NOTIFY_WANT_TTL_SEC)

    print("\n[① 비배치 잡은 통지하지 않는다]")
    reset()
    for i, (k, st) in enumerate([("fbot_event", "fbot"), ("sel_event", "selection"), ("fbot_request", "fbot"),
                                 ("fbot_session", "fbot"), ("fbot_dispatch", "fbot"), ("fbot_report", "fbot"),
                                 ("fbot_manual_review", "")]):
        job("j-%d" % i, k, "done", store=st)
    r, out = notify()
    check("fbot_event·sel_event 외 원장 kind 종결 → 통지 0", r == 0 and out == "", out)
    # 적대적 경우 — 누가 비배치 잡을 구독해도 kind 화이트리스트가 막는다
    with rc() as c:
        for i in range(7):
            S.notify_subscribe(c, "j-%d" % i)
        c.commit()
    r, out = notify()
    check("비배치 kind 에 구독 행이 있어도 통지 0 (kind 화이트리스트)", out == "", out)

    print("\n[② 세션이 요청한 배치 잡 — 종결 1회·재실행 0]")
    reset()
    txt = SV.t_learn_index({"kind": "consolidation"})
    jid = re.search(r"enqueue (job_[0-9a-f]+)", txt).group(1)
    check("learn_index 가 구독 행을 남긴다", count("SELECT count(*) FROM kv WHERE ns=? AND key=?", S.NOTIFY_WANT_NS, jid) == 1)
    with rc() as c:
        ttl = c.execute("SELECT expires_at - updated_at FROM kv WHERE ns=? AND key=?", (S.NOTIFY_WANT_NS, jid)).fetchone()[0]
    check("구독 행 TTL = NOTIFY_WANT_TTL_SEC", ttl == S.NOTIFY_WANT_TTL_SEC, ttl)
    r, out = notify()
    check("미종결(pending) 잡은 통지하지 않는다", out == "", out)
    with rc() as c:
        c.execute("UPDATE job SET status='running' WHERE id=?", (jid,)); c.commit()
        c.execute("UPDATE job SET status='pending_batch' WHERE id=?", (jid,)); c.commit()
    r, out = notify()
    check("running·pending_batch 도 통지하지 않는다", out == "", out)
    with rc() as c:
        c.execute("UPDATE job SET status='done', result=? WHERE id=?",
                  ('{"status": "ok", "buckets": []}', jid)); c.commit()
    r, out = notify()
    check("종결 → 통지 1회(헤더 1건·id·상태)", "종결된 배치 잡 1건" in out and jid in out and "→ done" in out, out)
    check("같은 입력 재실행 → 0", notify()[1] == "")
    check("전달하면 구독 행이 소비된다", count("SELECT count(*) FROM kv WHERE ns=? AND key=?", S.NOTIFY_WANT_NS, jid) == 0)
    check("job 행 자체는 남는다(영속 계층 — job_get 회수용)", count("SELECT count(*) FROM job WHERE id=?", jid) == 1)

    reset()
    job("job_f1", "consolidation", "failed", want=True, result="RuntimeError: boom")
    r, out = notify()
    check("failed 도 통지(원인 첫 줄 포함)", "job_f1" in out and "→ failed" in out and "boom" in out, out)
    job("job_i1", "index", "failed", want=True, result="미구현 kind: index")
    check("index kind 도 통지 대상", "job_i1" in notify()[1])

    print("\n[③ 한 번에 20건 상한 — 나머지는 다음 프롬프트, 모두 정확히 1회]")
    reset()
    for i in range(25):
        job("job_b%02d" % i, "consolidation", "done", want=True)
    sizes = []
    seen = []
    for _ in range(3):
        _, out = notify()
        m = re.search(r"종결된 배치 잡 (\d+)건", out)
        sizes.append(int(m.group(1)) if m else 0)
        seen += re.findall(r"job_b\d\d", out)
    check("20 → 5 → 0", sizes == [20, 5, 0], sizes)
    check("25건이 모두 정확히 1회", sorted(seen) == ["job_b%02d" % i for i in range(25)], len(seen))

    print("\n[재통지 없음 — TTL·시계와 무관]")
    reset()
    job("job_old", "consolidation", "done", want=True)
    check("1차 통지", "job_old" in notify()[1])
    real_now = S.now
    try:
        S.now = lambda: real_now() + 40 * DAY    # 30일 TTL 을 훌쩍 넘긴 시각
        check("🔑 40일 뒤에도 재통지 없음(전달 표식 TTL 이 없다)", notify()[1] == "")
    finally:
        S.now = real_now
    reset()
    job("job_nosub", "consolidation", "done", age_days=31)
    check("구독 없는 31일 경과 배치 잡(스케줄러 산출) → 통지 0", notify()[1] == "")
    job("job_exp", "consolidation", "done", want=True, want_exp=S.now() - 10)
    check("만료된 구독은 통지하지 않는다(모든 kv 읽기 만료 필터 의무)", notify()[1] == "")

    print("\n[통지 쿼리 비용 — 상태 인덱스 전수 스캔이 없다]")
    reset()
    with rc() as c:
        c.executemany("INSERT INTO job(id, store, kind, status, payload, result, attempts, owner, lease_until, "
                      "blocked_since, created_at) VALUES(?, 'fbot', 'fbot_event', 'done', NULL, NULL, 0, NULL, NULL, NULL, ?)",
                      [("ev%d" % i, S.now() - i) for i in range(5000)])
        c.commit()
    job("job_one", "consolidation", "done", want=True)
    with rc() as c:
        plan = " | ".join(r[3] for r in c.execute(
            "EXPLAIN QUERY PLAN " + N.select_sql(), N.select_args(S.now())).fetchall())
    check("job_status_idx 를 쓰지 않는다", "job_status_idx" not in plan, plan)
    check("job 전수 SCAN 이 없다", not re.search(r"SCAN j\b", plan) and "SCAN job" not in plan, plan)
    check("원장 5,000행이 있어도 통지 대상만 정확히 1건", "종결된 배치 잡 1건" in notify()[1])

    print("\n[④ GC — 배치 kind 의 종결·보존 경과 행만]")
    reset()
    # 지워질 것
    job("g-cons-done", "consolidation", "done", age_days=40, want=True)    # 구독이 남은 채 지워지면 고아 구독도 정리
    job("g-cons-fail", "consolidation", "failed", age_days=40)
    job("g-idx-fail", "index", "failed", age_days=40)
    # 남을 것 — 보존 기간 안
    job("k-cons-new", "consolidation", "done", age_days=5)
    # 남을 것 — 진행 중(오래돼도)
    job("k-pending", "consolidation", "pending", age_days=40)
    job("k-running", "consolidation", "running", age_days=40)
    job("k-batch", "consolidation", "pending_batch", age_days=40)
    # 남을 것 — 원장·타 소유 (fbot-arch: 원장 영구 · sel_event 는 selection.py 롤업 뒤 삭제)
    for kind, st in (("fbot_event", "fbot"), ("fbot_session", ""), ("fbot_report", "fbot"), ("fbot_request", "fbot"),
                     ("fbot_dispatch", "fbot"), ("fbot_solo", "fbot"), ("sel_event", "selection")):
        job("k-" + kind, kind, "done", age_days=40, store=st)
    # kv 위생
    with rc() as c:
        c.execute("INSERT INTO kv VALUES('notify','legacy-1','delivered',?,?, 'notify.py')", (S.now() + DAY, S.now()))
        c.execute("INSERT INTO kv VALUES('notify','legacy-2','delivered',NULL,?, 'notify.py')", (S.now(),))
        c.execute("INSERT INTO kv VALUES('sys','keep','x',NULL,?, 't')", (S.now(),))
        c.commit()
    job("k-live-want", "consolidation", "pending", age_days=1, want=True)        # 살아 있는 구독 — 보존
    with rc() as c:
        c.execute("INSERT INTO kv VALUES(?, 'ghost', 'pending', ?, ?, 't')", (S.NOTIFY_WANT_NS, S.now() + DAY, S.now()))  # job 없음
        c.commit()
    expect_deleted = {"g-cons-done", "g-cons-fail", "g-idx-fail"}
    total_before = count("SELECT count(*) FROM job")

    rep = W.gc_jobs(POL, apply=False)
    check("dry-run: 적격 3건 보고", rep.get("job_eligible") == 3, rep)
    check("dry-run: 아무것도 지우지 않는다", count("SELECT count(*) FROM job") == total_before
          and count("SELECT count(*) FROM kv WHERE ns='notify'") == 2)
    check("dry-run: 백업을 만들지 않는다", not os.path.isdir(os.path.join(S.AOA_DIR, "backup")))

    rep = W.gc_jobs(POL, apply=True)
    left = {r[0] for r in rc().execute("SELECT id FROM job").fetchall()}
    check("apply: 적격 3건 삭제", rep.get("job_deleted") == 3 and left.isdisjoint(expect_deleted), (rep, left))
    check("🔑 진행 중 잡(pending·running·pending_batch)은 오래돼도 남는다",
          {"k-pending", "k-running", "k-batch"} <= left, left)
    check("보존 기간 안 종결 잡은 남는다", "k-cons-new" in left)
    check("🔑 fbot 원장·sel_event 는 보존 기간이 지나도 지우지 않는다",
          {"k-fbot_event", "k-fbot_session", "k-fbot_report", "k-fbot_request", "k-fbot_dispatch", "k-fbot_solo",
           "k-sel_event"} <= left, left)
    check("삭제 전 registry 백업", any(f.startswith("registry-") for f in os.listdir(os.path.join(S.AOA_DIR, "backup"))))
    check("옛 전달 표식(kv ns=notify)은 전부 정리", count("SELECT count(*) FROM kv WHERE ns='notify'") == 0)
    check("지운 잡의 고아 구독·잡 없는 구독은 정리", count("SELECT count(*) FROM kv WHERE ns=? AND key IN ('g-cons-done','ghost')",
                                              S.NOTIFY_WANT_NS) == 0)
    check("살아 있는 구독·무관 ns 는 남는다", count("SELECT count(*) FROM kv WHERE ns=? AND key='k-live-want'", S.NOTIFY_WANT_NS) == 1
          and count("SELECT count(*) FROM kv WHERE ns='sys'") == 1)
    n_bak = len(os.listdir(os.path.join(S.AOA_DIR, "backup")))
    rep2 = W.gc_jobs(POL, apply=True)
    check("재실행: 0건 삭제·백업 추가 없음(멱등)", rep2.get("job_deleted", 0) == 0
          and len(os.listdir(os.path.join(S.AOA_DIR, "backup"))) == n_bak, rep2)

    print("\n[⑤ gc 의 job 부분이 관측 에이징 게이트 뒤에 숨지 않는다]")
    reset()
    job("h-old", "consolidation", "done", age_days=40)
    rep = W.gc(POL, apply=False)         # watermark 0 → 관측은 거부
    check("watermark 0 이어도 관측 거부와 별개로 job 적격이 보고된다(종전: 조기 반환으로 영원히 0)",
          rep.get("refused") and rep.get("job_eligible") == 1, rep)
    with S.connect(S.LEARN_DB) as lc:
        S.set_meta(lc, W.WATERMARK_KEY, str(S.now())); lc.commit()
    rep = W.gc(POL, apply=True)           # watermark>0 인데 지울 관측 0건 → 종전엔 job 부분까지 못 감
    check("적격 관측 0건이어도 종결 job 은 지워진다(종전: 도달 불가)",
          rep.get("job_deleted") == 1 and count("SELECT count(*) FROM job WHERE id='h-old'") == 0, rep)

    print("\n[⑥ CLI — gc --jobs 는 관측을 건드리지 않는다]")
    reset()
    job("c-old", "consolidation", "done", age_days=40)
    with S.connect(S.LEARN_DB) as lc:
        S.set_meta(lc, W.WATERMARK_KEY, str(S.now()))
        lc.execute("INSERT INTO observation(id, project_id, project_name, session_id, observed_at, body, source_path, ingested_at) "
                   "VALUES('o1','p','p','s',?, '{}', '/x', ?)", (S.now() - 200 * DAY, S.now()))
        lc.commit()
    env = dict(os.environ, AOA_MEMORY_DIR=S.AOA_DIR)
    p = subprocess.run([sys.executable, os.path.join(HERE, "worker.py"), "gc", "--jobs"],
                       capture_output=True, text=True, env=env, timeout=60)
    check("--jobs dry-run: 종결 job 적격 1행 보고", p.returncode == 0 and "종결 job 삭제 대상 1행" in p.stdout, p.stdout + p.stderr)
    check("--jobs dry-run: 관측 삭제 대상은 말하지 않는다", "삭제 대상 1행 · 시각 미상" not in p.stdout and "watermark" not in p.stdout, p.stdout)
    p = subprocess.run([sys.executable, os.path.join(HERE, "worker.py"), "gc", "--jobs", "--apply"],
                       capture_output=True, text=True, env=env, timeout=60)
    lc = sqlite3.connect(S.LEARN_DB)
    nobs = lc.execute("SELECT count(*) FROM observation").fetchone()[0]
    lc.close()
    check("--jobs --apply: 종결 job 삭제", p.returncode == 0 and count("SELECT count(*) FROM job WHERE id='c-old'") == 0, p.stdout + p.stderr)
    check("🔑 --jobs --apply 는 관측(learn.db)을 지우지 않는다", nobs == 1, nobs)
    check("--jobs --apply 는 learn.db 백업을 만들지 않는다(registry 백업만)",
          not any(f.startswith("learn-") for f in os.listdir(os.path.join(S.AOA_DIR, "backup"))))

    print("\n[⑦ tick 배선 — 1일 1회 · fail-soft]")
    # 배선(fbot-tick.sh)은 prj3 소유 — prj1 번들 사본(`~/_git/___pm/mcp/aoa-memory/`)에는 `../../hooks/` 가 없어 이 절을 건너뛴다
    tick_path = os.path.join(HERE, "..", "..", "hooks", "fbot-tick.sh")
    if not os.path.exists(tick_path):
        print(f"  skip tick 배선 — {os.path.normpath(tick_path)} 없음(번들 사본)")
        print(f"\n{PASS} passed, {FAIL} failed")
        shutil.rmtree(ROOT, ignore_errors=True)
        return 1 if FAIL else 0
    tick = open(tick_path, encoding="utf-8").read()
    check("worker 유닛이 run 뒤에 job_gc_gate 를 돈다",
          re.search(r'worker\.py" run[\s\S]{0,300}^    job_gc_gate$', tick, re.M) is not None)
    blk = re.search(r'^JOB_GC_MARKER=.*?^job_gc_gate\(\) \{\n.*?^\}\n', tick, re.S | re.M)
    check("게이트 정의가 있다", blk is not None)
    if blk:
        home = tempfile.mkdtemp(prefix="aoa-gate-")
        stub = os.path.join(home, "stubpy")
        slog = os.path.join(home, "stub.log")
        open(stub, "w").write('#!/bin/sh\necho "$@" >> "%s"\nexit "${FAKE_RC:-0}"\n' % slog)
        os.chmod(stub, 0o755)
        script = ('log() { printf "%s\\n" "$*"; }\nPY="' + stub + '"\nSRC="/src"\n' + blk.group(0) +
                  "\njob_gc_gate; echo rc=$?\n")

        def gate(fake_rc="0"):
            return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30,
                                  env=dict(os.environ, HOME=home, FAKE_RC=fake_rc))

        marker = os.path.join(home, ".claude", "data", "fbot", ".last-job-gc")
        g1 = gate()
        calls = open(slog).read().splitlines() if os.path.exists(slog) else []
        check("1회차: worker.py gc --jobs --apply 호출", len(calls) == 1 and "gc --jobs --apply" in calls[0], (calls, g1.stdout, g1.stderr))
        check("1회차: 마커 기록·rc=0", os.path.exists(marker) and "rc=0" in g1.stdout, g1.stdout + g1.stderr)
        gate()
        calls = open(slog).read().splitlines()
        check("같은 날 2회차는 건너뛴다", len(calls) == 1, calls)
        os.remove(marker)
        g3 = gate("3")
        calls = open(slog).read().splitlines()
        check("실패해도 tick 은 계속(rc=0)·마커 미기록(다음 tick 재시도)", len(calls) == 2 and not os.path.exists(marker)
              and "rc=0" in g3.stdout, (calls, g3.stdout))
        shutil.rmtree(home, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    shutil.rmtree(ROOT, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
