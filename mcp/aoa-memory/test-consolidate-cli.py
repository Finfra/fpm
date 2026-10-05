#!/usr/bin/env python3
"""test-consolidate-cli.py — consolidation `llm` 전략의 구독(CLI) 백엔드 (prj3#Issue852)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

무엇을 지키나 — 학습 3단 티어의 «정리 = sonnet»(Issue850)을 API 키 없이 돌린다(사용자 결정 ⓓ, 2026-10-02):
  `consolidation_backend: cli` 면 worker 가 Batch API 대신 `claude -p --model <별칭> --output-format json` 을
  **버킷당 1회** 호출해(프로젝트별 호출은 시스템 프롬프트 오버헤드 ~56k 토큰이 배수로 붙는다) 프로젝트별 요약을
  JSON 으로 받아 같은 트랜잭션에서 instinct(origin=consolidation)·산출 파일·watermark 를 올린다.
  지키는 성질 —
    · API 키 없이 돈다 · `claude` 부재는 fail-loud · 월 예산 게이트는 그대로(실사용 usage 로 기록)
    · 프로젝트 상한(`consolidation_cli_max_projects`)·프로젝트별 문자 상한으로 프롬프트를 묶는다
    · CLI 오류·JSON 파싱 실패는 잡 failed + 롤백(watermark 불변·instinct 0) — 조용히 stats 로 강등하지 않는다
    · 호출 전 잡 lease 를 timeout 만큼 늘린다(동기 호출 중 recover_expired 가 재큐잉하지 않게)
    · api 백엔드(기본)의 종전 계약(ANTHROPIC_API_KEY 필수)은 불변

격리: AOA_MEMORY_DIR 임시 폴더 · PATH 앞에 가짜 `claude` 실행 파일. 실 claude 는 호출하지 않는다.
실행: python3 mcp/aoa-memory/test-consolidate-cli.py
"""
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PASS = FAIL = 0
ROOT = tempfile.mkdtemp(prefix="aoa-cli-")
os.environ["AOA_MEMORY_DIR"] = os.path.join(ROOT, "aoa0")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("AOA_MEMORY_MODEL", None)
sys.path.insert(0, HERE)
import store as S      # noqa: E402
import worker as W     # noqa: E402

FAKE_BIN = os.path.join(ROOT, "bin")
FAKE_LOG = os.path.join(ROOT, "fake-claude.log")
USAGE = {"input_tokens": 1000, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 300, "output_tokens": 50}
FAKE = r'''#!/usr/bin/env python3
import json, os, re, sys
argv = sys.argv[1:]
prompt = sys.stdin.read()   # 구현은 프롬프트를 stdin 으로 넘긴다(ARG_MAX 회피) — `-p` 는 플래그만
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "prompt": prompt}, ensure_ascii=False) + "\n")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
usage = json.loads(os.environ["FAKE_CLAUDE_USAGE"])
if mode == "error":
    print(json.dumps({"type": "result", "is_error": True, "result": "boom", "usage": usage})); sys.exit(1)
pids = re.findall(r"^### project_id: (\S+)", prompt, re.M)
if mode == "badjson":
    text = "요약은 다음과 같다: " + ", ".join(pids)
else:
    text = "```json\n" + json.dumps([{"project_id": p, "summary": "요약 %s" % p} for p in pids], ensure_ascii=False) + "\n```"
print(json.dumps({"type": "result", "is_error": False, "result": text, "usage": usage}, ensure_ascii=False))
'''


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name} {str(detail)[:240]}")


def install_fake():
    os.makedirs(FAKE_BIN, exist_ok=True)
    p = os.path.join(FAKE_BIN, "claude")
    with open(p, "w", encoding="utf-8") as f:
        f.write(FAKE)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
    os.environ["FAKE_CLAUDE_LOG"] = FAKE_LOG
    os.environ["FAKE_CLAUDE_USAGE"] = json.dumps(USAGE)


def fresh(tag):
    """새 AOA 디렉토리로 스토어를 갈아끼운다 — 모듈 상수를 재지정(worker 는 호출 시점에 S.* 를 읽는다)."""
    d = os.path.join(ROOT, "aoa-" + tag)
    os.environ["AOA_MEMORY_DIR"] = d
    S.AOA_DIR = d
    S.LEARN_DB = os.path.join(d, "learn.db")
    S.REGISTRY_DB = os.path.join(d, "registry.db")
    S.init_stores()
    if os.path.exists(FAKE_LOG):
        os.remove(FAKE_LOG)
    os.environ["FAKE_CLAUDE_MODE"] = "ok"


BUCKET_TS = int(time.time()) - 130 * 86400   # 유예 90일 밖 — watermark 가 올라야 한다


def seed(projects):
    """projects: {pid: (name, 오류행 수, 정상행 수)} — 오류행만 LLM 필터를 통과한다."""
    b, st, en = W.month_bucket(BUCKET_TS)
    with S.connect(S.LEARN_DB) as c:
        i = 0
        for pid, (name, nerr, nok) in projects.items():
            for k in range(nerr + nok):
                err = k < nerr
                body = {"event": "tool_complete", "tool": "Bash",
                        "output": "cmd %d 출력 — 아주 긴 로그 %s" % (k, "x" * 300),
                        "stderr": ("오류 %d" % k) if err else "", "returnCode": 1 if err else 0}
                c.execute("INSERT INTO observation(id, project_id, project_name, session_id, observed_at, body, "
                          "source_path, ingested_at) VALUES(?,?,?,?,?,?,?,?)",
                          ("obs-%s-%d" % (pid, i), pid, name, "s1", st + 3600 + i, json.dumps(body, ensure_ascii=False),
                           "/x/%s.jsonl" % pid, S.now()))
                i += 1
        c.commit()
    return b, st, en


def enqueue():
    jid = "job_test%s" % os.urandom(3).hex()
    with S.connect(S.REGISTRY_DB) as rc:
        rc.execute("BEGIN IMMEDIATE")
        rc.execute("INSERT INTO job(id, store, kind, status, payload, result, attempts, owner, lease_until, "
                   "blocked_since, created_at) VALUES(?, 'learn', 'consolidation', 'pending', NULL, NULL, 0, "
                   "NULL, NULL, NULL, ?)", (jid, S.now()))
        rc.commit()
    return jid


def job_row(jid):
    with S.connect(S.REGISTRY_DB) as rc:
        r = rc.execute("SELECT status, result FROM job WHERE id=?", (jid,)).fetchone()
        return (r["status"], r["result"] or "") if r else (None, "")


def learn_state():
    with S.connect(S.LEARN_DB) as c:
        wm = int(S.get_meta(c, W.WATERMARK_KEY, "0"))
        rows = c.execute("SELECT project_id, body, origin FROM instinct WHERE origin='consolidation'").fetchall()
        return wm, {r["project_id"]: r["body"] for r in rows}


def budget():
    with S.connect(S.REGISTRY_DB) as rc:
        r = rc.execute("SELECT tokens, calls FROM budget_monthly WHERE store='llm'").fetchone()
        return (int(r["tokens"]), int(r["calls"])) if r else (0, 0)


def calls():
    if not os.path.exists(FAKE_LOG):
        return []
    return [json.loads(l) for l in open(FAKE_LOG, encoding="utf-8") if l.strip()]


POL = {"learn_consolidation_enabled": True, "consolidation_strategy": "llm", "consolidation_backend": "cli",
       "consolidation_budget_monthly_tokens": 100000, "learn_consolidate_model": "sonnet",
       "consolidation_cli_max_projects": 2, "consolidation_cli_chars_per_project": 500,
       "consolidation_cli_timeout_secs": 30, "consolidation_grace_days": 90,
       "lease_ttl_secs": 300, "job_max_attempts": 2, "observation_retention_days": 90, "job_retention_days": 30}


def main():
    install_fake()
    real_path = os.environ.get("PATH", "/usr/bin:/bin")
    os.environ["PATH"] = FAKE_BIN + os.pathsep + real_path

    print("\n[별칭 해석 — cli 백엔드는 별칭을 그대로 넘긴다(claude 가 버전으로 푼다)]")
    check("cli: 'sonnet' 그대로", W.resolve_model(POL, backend="cli") == "sonnet")
    os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "sonnet-vfake"
    check("api: 별칭은 env 로 풀린다(종전 계약 유지)", W.resolve_model(POL, backend="api") == "sonnet-vfake")
    os.environ.pop("ANTHROPIC_DEFAULT_SONNET_MODEL")

    print("\n[정상 — 버킷 1회 호출 · 프로젝트 상한 · instinct·파일·watermark·예산]")
    fresh("ok")
    b, st, en = seed({"A": ("alpha", 5, 2), "B": ("beta", 2, 0), "C": ("gamma", 1, 0)})
    jid = enqueue()
    done = W.run_jobs(POL)
    status, result = job_row(jid)
    check("잡 done", status == "done", "%s %s" % (status, result[:200]))
    cs = calls()
    check("🔑 claude 호출은 버킷당 정확히 1회(프로젝트별 호출 금지)", len(cs) == 1, str(len(cs)))
    if cs:
        argv = cs[0]["argv"]; prompt = cs[0]["prompt"]
        check("--model 별칭 sonnet · --output-format json · -p", "sonnet" in argv and "json" in argv and "-p" in argv, str(argv))
        check("프로젝트 상한 2 — 행 많은 A·B 만, C 제외",
              "### project_id: A" in prompt and "### project_id: B" in prompt and "### project_id: C" not in prompt,
              prompt[:300])
        check("프로젝트별 문자 상한(500)으로 잘린다 — A 는 5행×300자 이상인데 프롬프트는 상한 안",
              len(prompt) < 5 * 350 + 2000, str(len(prompt)))
    wm, rows = learn_state()
    check("instinct 행 origin=consolidation — A·B 두 건", set(rows) == {"A", "B"}, str(sorted(rows)))
    check("요약 본문이 들어간다", rows.get("A", "").startswith("요약 A"), str(rows.get("A"))[:80])
    check("watermark 가 유예 밖 버킷 끝으로 오른다", wm == en, "%s vs %s" % (wm, en))
    path = os.path.join(S.AOA_DIR, "consolidation", "evolved_obs_%s_llm.md" % b)
    check("산출 파일 — source: consolidation · backend: cli", os.path.exists(path)
          and "source: consolidation" in open(path, encoding="utf-8").read()
          and "backend: cli" in open(path, encoding="utf-8").read(), path)
    tok, ncalls = budget()
    check("예산은 실사용 usage 합(입력+캐시생성+캐시읽기+출력)으로 1회 기록", tok == sum(USAGE.values()) and ncalls == 1,
          "%s %s" % (tok, ncalls))

    print("\n[예산 게이트 — 소진 ≥ 한도면 호출 전 중단 · 정상 대기(월 상한은 실패가 아니다)]")
    fresh("budget")
    seed({"A": ("alpha", 3, 0)})
    with S.connect(S.REGISTRY_DB) as rc:
        rc.execute("BEGIN IMMEDIATE"); S.record_budget(rc, "llm", 100000, 9); rc.commit()
    jid = enqueue(); W.run_jobs(POL)
    status, result = job_row(jid)
    # cli 백엔드는 5분 tick 마다 잡이 생기므로 상한 도달을 failed 로 두면 하루 288건의 거짓 실패가 쌓인다 —
    #   done + budget_exhausted 로 닫고 호출은 하지 않는다(api 백엔드의 종전 raise 는 그대로)
    check("잡 done + budget_exhausted(예산 사유)", status == "done" and "budget_exhausted" in result and "예산" in result,
          "%s %s" % (status, result[:160]))
    check("claude 미호출", calls() == [])
    check("watermark 불변", learn_state()[0] == 0)

    print("\n[CLI 오류 — failed · 롤백]")
    fresh("err"); seed({"A": ("alpha", 3, 0)}); os.environ["FAKE_CLAUDE_MODE"] = "error"
    jid = enqueue(); W.run_jobs(POL)
    status, result = job_row(jid)
    wm, rows = learn_state()
    check("잡 failed", status == "failed", "%s %s" % (status, result[:120]))
    check("instinct 0 · watermark 0 (롤백)", rows == {} and wm == 0, "%s %s" % (rows, wm))
    check("실패 호출도 예산에 기록된다(사용은 됐다)", budget()[1] == 1, str(budget()))

    print("\n[응답이 JSON 이 아니면 failed — stats 로 조용히 강등하지 않는다]")
    fresh("badjson"); seed({"A": ("alpha", 3, 0)}); os.environ["FAKE_CLAUDE_MODE"] = "badjson"
    jid = enqueue(); W.run_jobs(POL)
    status, result = job_row(jid)
    check("잡 failed + 파싱 사유", status == "failed" and ("JSON" in result or "파싱" in result), "%s %s" % (status, result[:160]))
    check("watermark 0", learn_state()[0] == 0)

    print("\n[claude 부재 — fail-loud]")
    fresh("noclaude"); seed({"A": ("alpha", 3, 0)})
    os.environ["PATH"] = "/usr/bin:/bin"
    jid = enqueue(); W.run_jobs(POL)
    status, result = job_row(jid)
    check("잡 failed + claude 언급", status == "failed" and "claude" in result.lower(), "%s %s" % (status, result[:160]))
    os.environ["PATH"] = FAKE_BIN + os.pathsep + real_path

    print("\n[lease 연장 — 동기 호출 동안 recover_expired 가 재큐잉하지 않게]")
    fresh("lease"); seed({"A": ("alpha", 3, 0)})
    captured = {}
    _orig = W.run_claude_cli

    def spy(prompt, model, timeout, env=None):
        with S.connect(S.REGISTRY_DB) as rc:
            captured["lease"] = rc.execute("SELECT lease_until FROM job WHERE status='running'").fetchone()["lease_until"]
        return _orig(prompt, model, timeout, env)
    W.run_claude_cli = spy
    try:
        jid = enqueue(); W.run_jobs(dict(POL, consolidation_cli_timeout_secs=3600))
    finally:
        W.run_claude_cli = _orig
    check("호출 시점 lease 가 timeout 이상 남아 있다", captured.get("lease", 0) >= S.now() + 3000, str(captured))
    check("잡 done", job_row(jid)[0] == "done")

    print("\n[api 백엔드(기본) — 종전 계약: ANTHROPIC_API_KEY 필수]")
    fresh("api"); seed({"A": ("alpha", 3, 0)})
    os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "sonnet-vfake"   # 별칭 해석은 통과시키고 키 검사에서 멈추게
    jid = enqueue(); W.run_jobs(dict(POL, consolidation_backend="api"))
    os.environ.pop("ANTHROPIC_DEFAULT_SONNET_MODEL")
    status, result = job_row(jid)
    check("키 없으면 failed + ANTHROPIC_API_KEY", status == "failed" and "ANTHROPIC_API_KEY" in result, result[:160])
    check("claude CLI 미호출", calls() == [])

    print("\n[미지 백엔드 — fail-loud]")
    fresh("bad"); seed({"A": ("alpha", 3, 0)})
    jid = enqueue(); W.run_jobs(dict(POL, consolidation_backend="grpc"))
    status, result = job_row(jid)
    check("failed + 백엔드 사유", status == "failed" and "backend" in result, result[:160])

    print(f"\n{PASS} passed, {FAIL} failed")
    shutil.rmtree(ROOT, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
