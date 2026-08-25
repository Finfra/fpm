#!/usr/bin/env python3
"""aoa-memory 회귀 검증 — 격리 디렉토리에서 스키마·도구·통지를 전수 확인 (prj5 Issue68)

실행:  python3 mcp/aoa-memory/selftest.py
  * `AOA_MEMORY_DIR` 을 임시 폴더로 돌려 **실데이터(`data/aoa/`)를 건드리지 않는다**.
  * 서버는 실제 stdio JSON-RPC 로 구동한다 — 함수 직접 호출로 우회하면 프로토콜 회귀를 놓친다.
  * 종료 코드 0 = 전체 통과. 실패는 즉시 fail-loud 로 멈춘다(조용한 스킵 금지).
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s %s%s" % ("✅" if cond else "❌", name, (" — " + detail) if detail and not cond else ""))


def rpc(env, calls):
    """서버를 1회 띄워 요청 목록을 순서대로 보내고 응답을 돌려준다."""
    lines = "\n".join(json.dumps(c, ensure_ascii=False) for c in calls) + "\n"
    p = subprocess.run([sys.executable, os.path.join(HERE, "server.py")],
                       input=lines, capture_output=True, text=True, env=env, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("server exit %s\n%s" % (p.returncode, p.stderr))
    return [json.loads(l) for l in p.stdout.splitlines() if l.strip()]


def call(i, tool, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": tool, "arguments": args}}


def text(resp):
    return resp["result"]["content"][0]["text"]


# 관측 표본 3건. 셋 다 의도가 있다:
#   ①② 는 **내용이 완전히 동일**하다 — 같은 초에 같은 툴이 같은 출력으로 끝난 관측이며
#      실측 41,466행에서 534건이 이랬다. 내용 해시를 자연키로 쓰면 하나가 사라지므로,
#      "둘 다 남는다"가 자연키 선택(줄번호)의 회귀 조건이다.
#   ③ 은 **timestamp 가 없다** — NULL 로 남아야 하고 0 이 되면 안 된다(GC 즉시 삭제 방지).
#   셋 다 project_id 필드가 없다 — 경로에서 복원되는지 함께 본다.
OBS_ITEMS = [
    {"timestamp": "2026-04-13T05:58:51Z", "event": "tool_complete", "tool": "Bash",
     "session": "s1", "project_name": "alpha", "output": ""},
    {"timestamp": "2026-04-13T05:58:51Z", "event": "tool_complete", "tool": "Bash",
     "session": "s1", "project_name": "alpha", "output": ""},
    {"event": "tool_complete", "tool": "Read",
     "session": "s1", "project_name": "alpha", "output": ""},
]


def worker(env, *argv):
    return subprocess.run([sys.executable, os.path.join(HERE, "worker.py"), *argv],
                          capture_output=True, text=True, env=env, timeout=120)


def main():
    tmp = tempfile.mkdtemp(prefix="aoa-memory-selftest-")
    env = dict(os.environ, AOA_MEMORY_DIR=tmp)
    src = os.path.join(tmp, "fake_instinct.md")
    open(src, "w").write("dummy source")
    # 경로에 `projects/<id>/` 를 넣는다 — project_id 복원 경로를 함께 검증하기 위해서다
    obs_src = os.path.join(tmp, "projects", "p_alpha", "observations.archive", "processed-1.jsonl")

    # 1. 스키마 초기화 (멱등 — 두 번 돌린다)
    for _ in range(2):
        r = subprocess.run([sys.executable, os.path.join(HERE, "store.py")],
                           capture_output=True, text=True, env=env, timeout=60)
        if r.returncode != 0:
            print(r.stderr)
            check("스키마 초기화", False, r.stderr.strip()[:200])
            return 1
    check("스키마 초기화 (멱등 2회)", True)
    check("registry.db 실재", os.path.exists(os.path.join(tmp, "registry.db")))
    check("learn.db 실재", os.path.exists(os.path.join(tmp, "learn.db")))

    # 2. 프로토콜 + 도구 표면
    out = rpc(env, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        call(3, "registry_list", {}),
        call(4, "kv_set", {"ns": "sys", "key": "hello", "value": "world"}),
        call(5, "kv_set", {"ns": "sys", "key": "gone", "value": "x", "ttl_sec": -1}),
        call(6, "kv_get_all", {"ns": "sys"}),
        call(7, "learn_upsert", {
            "project_id": "prj5", "instinct_id": "aoa-memory-smoke",
            "title": "smoke instinct", "trigger": "when testing aoa-memory",
            "confidence": 0.9, "domain": "infra", "scope": "project",
            "occurrences": 3, "body": "learn.db 적재 경로 검증용 본문",
            "source_path": src}),
        call(8, "learn_upsert", {                      # 재적재 = 멱등 (FTS 중복 금지)
            "project_id": "prj5", "instinct_id": "aoa-memory-smoke",
            "title": "smoke instinct", "body": "learn.db 적재 경로 검증용 본문",
            "source_path": src}),
        call(9, "learn_search", {"q": "적재"}),
        call(10, "learn_search", {"q": "존재하지않는단어xyzzy"}),
        call(11, "learn_index", {"kind": "consolidation"}),
        call(12, "job_get", {}),
        call(13, "kv_get_all", {}),                    # ns 누락 → 오류 응답이어야 한다
        # 관측 적재 — 같은 배치를 두 번 보낸다(자연키 멱등). 3번째 항목은 **시각이 없다**
        call(14, "learn_observe", {"source_path": obs_src, "items": OBS_ITEMS}),
        call(15, "learn_observe", {"source_path": obs_src, "items": OBS_ITEMS}),
    ])
    got = {r["id"]: r for r in out}

    check("initialize 응답", got[1]["result"]["serverInfo"]["name"] == "aoa-memory")
    check("tools/list 8종", len(got[2]["result"]["tools"]) == 8,
          str(len(got[2]["result"]["tools"])))
    check("registry_list 에 learn 등재", "learn" in text(got[3]))
    kv = json.loads(text(got[6]))
    check("kv 왕복", kv["count"] == 1 and kv["items"][0]["value"] == "world", json.dumps(kv))
    check("만료 kv 는 조회에서 제외", all(i["key"] != "gone" for i in kv["items"]))
    check("learn_upsert 성공", text(got[7]).startswith("✅"))
    check("learn_search 매치", "smoke instinct" in text(got[9]), text(got[9]))
    check("재적재 후에도 1행 (FTS 멱등)", text(got[9]).count("| smoke instinct") == 1, text(got[9]))
    check("무매치는 0건으로 명시", "매치 0건" in text(got[10]))
    check("learn_index → job_id 반환", "enqueue job_" in text(got[11]), text(got[11]))
    check("상주 아님을 명시 고지", "worker.py run" in text(got[11]), text(got[11]))
    check("job_get 에 pending 잡", "pending" in text(got[12]))
    check("ns 누락은 fail-loud", "실행 오류" in text(got[13]), text(got[13]))

    # --- 관측 적재 (Issue69 A) ---
    check("learn_observe 배치 적재", "observation 3건 적재" in text(got[14]), text(got[14]))
    check("시각 미상은 NULL 로 고지", "시각 미상 1건" in text(got[14]), text(got[14]))
    check("재적재는 늘지 않는다 (자연키 멱등)",
          "observation 0건 적재 (이미 있던 것 3건)" in text(got[15]), text(got[15]))

    lc = sqlite3.connect(os.path.join(tmp, "learn.db"))
    check("observation 3행", lc.execute("SELECT count(*) FROM observation").fetchone()[0] == 3)
    check("🔴 시각 미상은 NULL 이다 (0 이면 첫 GC 에 전멸한다)",
          lc.execute("SELECT count(*) FROM observation WHERE observed_at IS NULL").fetchone()[0] == 1)
    check("observed_at 0 행이 없다",
          lc.execute("SELECT count(*) FROM observation WHERE observed_at=0").fetchone()[0] == 0)
    check("project_id 를 경로에서 복원",
          lc.execute("SELECT count(*) FROM observation WHERE project_id='p_alpha'").fetchone()[0] == 3)
    lc.close()

    # 같은 줄은 항상 같은 id — 어댑터가 각자 키를 만들면 깨지는 성질이라 못 박는다
    sys.path.insert(0, HERE)
    # in-process import 도 임시 디렉토리를 보게 한다 — 이후 Issue70 회귀가 worker 를
    # 직접 부르므로, 여기서 안 돌리면 S.LEARN_DB 가 실데이터를 가리킨다.
    os.environ["AOA_MEMORY_DIR"] = tmp
    import store as S                                          # noqa: E402
    check("자연키 결정론", S.observation_id("/x/y.jsonl", 7) == S.observation_id("/x/y.jsonl", 7))
    check("줄이 다르면 id 도 다르다",
          S.observation_id("/x/y.jsonl", 7) != S.observation_id("/x/y.jsonl", 8))

    # 3. 통지 가속 B — done 잡 1건을 심고 hook 출력·멱등을 확인
    con = sqlite3.connect(os.path.join(tmp, "registry.db"))
    con.execute("INSERT INTO job(id, store, kind, status, payload, result, attempts, owner, "
                "lease_until, blocked_since, created_at) "
                "VALUES('job_done1','learn','consolidation','done',NULL,'요약 3건 생성',0,"
                "NULL,NULL,NULL,1)")
    con.commit()
    con.close()

    n1 = subprocess.run([sys.executable, os.path.join(HERE, "notify.py")],
                        capture_output=True, text=True, env=env, timeout=60)
    n2 = subprocess.run([sys.executable, os.path.join(HERE, "notify.py")],
                        capture_output=True, text=True, env=env, timeout=60)
    check("notify 가 done 잡을 고지", "job_done1" in n1.stdout, n1.stdout + n1.stderr)
    check("notify 재실행은 침묵 (전달 표식)", n2.stdout.strip() == "", n2.stdout)

    # --- consolidation 실행기 (Issue69 B) ---
    def learn(sql):
        con = sqlite3.connect(os.path.join(tmp, "learn.db"))
        try:
            return con.execute(sql).fetchone()[0]
        finally:
            con.close()

    # B-3 게이트 ① — 소화 이력이 없으면 한 건도 지우지 않는다
    g0 = worker(env, "gc")
    check("🔴 watermark 0 이면 GC 거부", "삭제 거부" in g0.stdout, g0.stdout + g0.stderr)

    r = worker(env, "consolidate")
    check("consolidate 실행", r.returncode == 0 and "소화 버킷" in r.stdout, r.stdout + r.stderr)
    wm = int(learn("SELECT value FROM _meta WHERE key='consolidated_until'"))
    check("B-2 watermark 전진", wm > 0, "watermark=%d" % wm)
    check("B-4 산출은 origin=consolidation",
          learn("SELECT count(*) FROM instinct WHERE origin='consolidation'") >= 1)

    digest = os.path.join(tmp, "consolidation", "evolved_obs_2026-04.md")
    check("환원 파일 생성", os.path.exists(digest), digest)
    if os.path.exists(digest):
        head = open(digest, encoding="utf-8").read()
        # 이 표식이 빠지면 prj3 어댑터가 산출물을 다시 적재해 요약의 요약이 증폭된다
        check("🔴 B-4 환원 파일에 source: consolidation", "source: consolidation" in head)
        check("산출 요약이 두 건을 다 셈", "| 2 |" in head or " 2 " in head, head[:400])

    g1 = worker(env, "gc")
    check("B-3 소화분만 삭제 대상", "삭제 대상 2행" in g1.stdout, g1.stdout)
    check("🔴 시각 미상은 보호된다", "시각 미상 보호 1행" in g1.stdout, g1.stdout)
    check("dry-run 이 기본", "dry-run" in g1.stdout and learn("SELECT count(*) FROM observation") == 3)

    g2 = worker(env, "gc", "--apply")
    check("GC 적용", "삭제 2행" in g2.stdout, g2.stdout + g2.stderr)
    check("삭제 전 백업", "backup/" in g2.stdout, g2.stdout)
    check("🔴 시각 미상 행은 살아남는다", learn("SELECT count(*) FROM observation") == 1)

    # 얼린 구간 보호 — raw 가 사라진 뒤 다시 돌려도 요약이 부실해지면 안 된다
    occ_before = learn("SELECT sum(occurrences) FROM instinct WHERE origin='consolidation'")
    r2 = worker(env, "consolidate")
    occ_after = learn("SELECT sum(occurrences) FROM instinct WHERE origin='consolidation'")
    check("🔴 GC 후 재소화가 요약을 덮어쓰지 않는다", occ_before == occ_after,
          "%s → %s\n%s" % (occ_before, occ_after, r2.stdout))

    # B-1 잡 큐 — enqueue 한 것이 실제로 소비된다
    worker(env, "enqueue")
    r3 = worker(env, "run")
    check("B-1 잡 소비", "처리 " in r3.stdout and "pending 없음" not in r3.stdout,
          r3.stdout + r3.stderr)
    rc = sqlite3.connect(os.path.join(tmp, "registry.db"))
    check("잡이 done 으로 종결",
          rc.execute("SELECT count(*) FROM job WHERE status='done'").fetchone()[0] >= 1)
    # 소화할 raw 가 없는 것은 **실패가 아니다** — 여기서 failed 가 나오면 정상 상태를
    # 장애로 보고하는 것이고, 그 오보가 쌓이면 job 테이블을 아무도 안 믿게 된다
    check("소화 대상 부재를 failed 로 만들지 않는다",
          rc.execute("SELECT count(*) FROM job WHERE status='failed'").fetchone()[0] == 0)
    rc.execute("INSERT INTO job VALUES('job_bogus','learn','index','pending',NULL,NULL,0,"
               "NULL,NULL,NULL,1)")
    rc.commit()
    rc.close()
    worker(env, "run")
    rc = sqlite3.connect(os.path.join(tmp, "registry.db"))
    st = rc.execute("SELECT status FROM job WHERE id='job_bogus'").fetchone()[0]
    rc.close()
    check("모르는 kind 를 성공으로 닫지 않는다", st == "failed", st)

    # B-5 모델 ID — 코드에 박혀 있으면 안 된다 (prj3#Issue415 재발 방지)
    hard = []
    for fn in sorted(os.listdir(HERE)):
        if not fn.endswith(".py"):
            continue
        body = open(os.path.join(HERE, fn), encoding="utf-8").read()
        for m in re.findall(r"claude-[a-z0-9.\-]*\d[a-z0-9.\-]*", body):
            hard.append("%s: %s" % (fn, m))
    check("🔴 B-5 모델 ID 하드코딩 없음", not hard, ", ".join(hard))

    # 4. fail-soft — 스토어가 없으면 조용히 끝난다
    empty = dict(os.environ, AOA_MEMORY_DIR=os.path.join(tmp, "nope"))
    n3 = subprocess.run([sys.executable, os.path.join(HERE, "notify.py")],
                        capture_output=True, text=True, env=empty, timeout=60)
    check("스토어 부재 시 notify 무출력·정상종료", n3.returncode == 0 and n3.stdout.strip() == "")

    # --- Issue70: llm 전략 — 예산 게이트·필터·JSONL 파싱 ---
    import worker as W                                         # noqa: E402
    pol_llm = {"learn_consolidation_enabled": True, "consolidation_strategy": "llm",
               "consolidation_model": "test-model", "consolidation_grace_days": 90}
    saved_key = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "selftest-dummy-key"
    try:
        # ① JSONL 파싱 — 리터럴 '\n' split 회귀 고정 (실제 개행으로 갈라야 한다)
        check("🔴 JSONL 은 실제 개행으로 가른다",
              W._parse_jsonl('{"a": 1}\n{"b": 2}\n') == [{"a": 1}, {"b": 2}])

        # ② registry 없이 llm 실행 금지 (예산 기록·배치 추적 불성립)
        try:
            W.do_consolidate(pol_llm, verbose=False, rc=None)
            check("llm 전략은 잡 큐 경유만", False, "예외가 나지 않았다")
        except RuntimeError as e:
            check("llm 전략은 잡 큐 경유만", "잡 큐" in str(e), str(e))

        with S.connect(os.path.join(tmp, "registry.db")) as rcon:
            # ③ 한도 미지정(기본 0)은 fail-loud — 한도 없는 배치는 발주하지 않는다
            try:
                W.do_consolidate(pol_llm, verbose=False, rc=rcon)
                check("🔴 예산 한도 미지정 fail-loud", False, "예외가 나지 않았다")
            except RuntimeError as e:
                check("🔴 예산 한도 미지정 fail-loud", "한도 미지정" in str(e), str(e))

            # ④ 예산 기록 가산 (일별·월별 동시) + 월 소진 조회
            S.record_budget(rcon, "llm", 700, 1)
            S.record_budget(rcon, "llm", 300, 2)
            rcon.commit()
            check("예산 기록이 가산된다", S.budget_month_spent(rcon, "llm") == 1000,
                  "spent=%d" % S.budget_month_spent(rcon, "llm"))

            # ⑤ 예산 게이트 fire — 소진 ≥ 한도면 배치 발주 전에 중단 (명세 6)
            pol_cap = dict(pol_llm, consolidation_budget_monthly_tokens=1000)
            try:
                W.do_consolidate(pol_cap, verbose=False, rc=rcon)
                check("🔴 예산 게이트 fire (한도 초과 시 중단)", False, "예외가 나지 않았다")
            except RuntimeError as e:
                check("🔴 예산 게이트 fire (한도 초과 시 중단)", "예산 게이트" in str(e), str(e))
    finally:
        if saved_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = saved_key

    # ⑥ 필터 전처리 — 오류·의사결정 행만 투입, 빈 output 은 버린다 (명세 2)
    with S.connect(os.path.join(tmp, "learn.db")) as lcon:
        rows = [
            ("f1", json.dumps({"tool": "Bash", "output": "boom", "returnCode": 1})),      # 오류 → 채택
            ("f2", json.dumps({"tool": "AskUserQuestion", "output": "결정: A안"})),        # 의사결정 → 채택
            ("f3", json.dumps({"tool": "Bash", "output": "ok", "returnCode": 0})),         # 정상 → 제외
            ("f4", json.dumps({"tool": "Read", "output": ""})),                            # 빈 출력 → 제외
        ]
        lcon.execute("BEGIN IMMEDIATE")
        for rid, body in rows:
            lcon.execute(
                "INSERT OR REPLACE INTO observation(id, project_id, project_name, session_id, "
                "observed_at, body, source_path, ingested_at) "
                "VALUES(?, 'p_filter', 'filter', 's9', 1900000000, ?, '/x.jsonl', 1)",
                (rid, body))
        lcon.commit()
        projs = W.digest_bucket_llm_filter(lcon, 1900000000 - 10, 1900000000 + 10)
        picked = len(projs.get("p_filter", {}).get("rows", []))
        total = projs.get("p_filter", {}).get("count", 0)
        check("🔴 필터는 오류·의사결정 행만 투입", picked == 2 and total == 4,
              "picked=%d total=%d" % (picked, total))
        lcon.execute("DELETE FROM observation WHERE project_id='p_filter'")
        lcon.commit()

    print("\n%d/%d 통과 (임시: %s)" % (len(PASS), len(PASS) + len(FAIL), tmp))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
