#!/usr/bin/env python3
"""aoa-memory 잡 실행기 — consolidation·watermark·에이징 (prj5 Issue69 B)

⚠️ 설계 SSOT: ~/_git/___common/_doc_arch/aoa-memory-design.md
   §실행 토폴로지(lease·recovery) · §데이터 에이징 정책 · §영속 보증 · §승격 경로

## 이 파일이 메우는 구멍

`server.py` 의 `learn_index` 는 잡을 **큐에 넣고 job_id 를 돌려주기만** 한다
(설계의 "도구를 속도로 분리한다" 원칙 — 그 자체는 옳다). 그런데 Issue68 시점까지
**큐를 소비하는 주체가 없었다.** `registry.job` 0행 · `consolidated_until: 0` 이 그 증거였고,
그래서 관측을 아무리 넣어도 요약이 돌지 않았다.

## ⚠️ 이 파일 자체는 데몬이 아니다 — 상주는 launchd 가 준다 (2026-08-23 승격)

Issue68 은 *"lazy 로 시작하고, 배치 지연이 실제 pain 으로 관측될 때 상주로 승격"* 으로
정했고, **그 조건이 충족돼 2026-08-23 prj3#Issue436_3 s0 이 상주화했다.**
승격 방식은 이 파일을 무한 루프로 바꾸는 것이 **아니라**, 매 tick 이 clean 프로세스로
끝나는 launchd 주기 기동이다 — 그래서 아래 진입점은 코드 변경 없이 그대로 재사용된다.

    kr.finfra.fbot-worker   30분 주기 → worker.py enqueue → worker.py run
    kr.finfra.fbot-ingest   15분 주기 → ingest_obs.py --quiet

배관(plist + 래퍼 ~/.claude/hooks/fbot-tick.sh)은 **prj3 소유**이며, 이 파일에는
launchd 등재 로직이 없다. prj5 자립 진입점(`aoa-memory service install`)은 미착수다.

⚠️ 배관을 새로 세울 때 반드시 알아야 하는 두 가지 (설계 §실행기는 상주다):
  1. `run` 은 pending 잡을 **소비만** 한다 — 생산자가 없다. `enqueue` 를 앞에 붙여
     `enqueue → run` 을 잇지 않으면 매 tick "처리 0건"으로 영구 공회전한다
  2. 이 파일에 **적재(ingest) 경로가 없다** — 아래 cmd 목록에 부재하고 run_jobs() 는
     consolidation 전용이다. 관측 적재는 `ingest_obs.py` 별도 배관이 맡는다

    python3 mcp/aoa-memory/worker.py status
    python3 mcp/aoa-memory/worker.py enqueue        # 생산 — 소화 대상 구간을 잡으로 큐잉
    python3 mcp/aoa-memory/worker.py run            # 소비 — pending 전부 (1회 실행 후 종료)
    python3 mcp/aoa-memory/worker.py consolidate    # 큐 우회 직접 실행
    python3 mcp/aoa-memory/worker.py gc             # 에이징 — 기본 dry-run
    python3 mcp/aoa-memory/worker.py gc --apply     # 실제 삭제 (백업 후)

## 늦은 도착 유예가 왜 90일인가 (실측이 초안을 뒤집었다)

초안은 유예 35일이었다. 관측 아카이브는 **사건보다 한참 뒤에 기록된다** —
실측(2026-08-16 · 41,534행) 결과 기록 지연이 p50 0.0일 · p95 3.9일 · p99 29.5일이지만
**최대 87.9일**이고, 35일을 넘는 것이 311건이었다. 유예 35일이면 그 311건이
watermark 아래로 떨어져 **요약에 안 잡힌 채 90일 뒤 삭제**된다. 90일 초과는 0건이라
유예를 90일로 잡았다(policy.yml `consolidation_grace_days`).

## 재소화 차단 (설계 §승격 경로 · Issue403 반증 2)

산출물을 다음 라운드의 입력으로 넣지 않는다. 이 파일은 두 겹으로 막는다:
  1. 입력은 `observation`(raw) 뿐이다 — `instinct` 를 읽지 않으므로 환원본이 입력에 못 든다
  2. 산출 행은 `origin='consolidation'`, 산출 파일은 frontmatter `source: consolidation` —
     prj3 어댑터가 그 값을 보고 재적재를 막는다. 둘 중 하나만 박으면 파일 경로로 새어 들어온다
"""

import argparse
import calendar
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy as P      # noqa: E402
import server as SV     # noqa: E402
import store as S       # noqa: E402

WATERMARK_KEY = "consolidated_until"
BACKUP_KEEP = 3

# 판별 축 화이트리스트 — 알 수 없는 값은 버리지 않고 'other' 로 **사영**한다.
#   prj3 가 `origin` 열에 자유 텍스트가 섞여 GROUP BY 가 갈라진 것과 같은 계열의 오염을 막는다.
#   버리지 않는 이유: 새 event 종류가 생겼을 때 조용히 0건이 되면 어댑터 부패를 못 본다.
KNOWN_EVENTS = ("tool_complete",)
TOP_TOOLS_PER_PROJECT = 15      # 초과분은 'other' 로 합산 — 도구명은 열린 집합이라 상한을 둔다


# --- 공통 ----------------------------------------------------------------

def owner_tag():
    return "%s/%d" % (socket.gethostname().split(".")[0], os.getpid())


def month_bucket(ts):
    """epoch → ('YYYY-MM', 구간 시작, 구간 끝(배타)). 전부 UTC 기준.

    관측 `timestamp` 가 UTC(`...Z`)라 로컬 시간대를 섞지 않는다 — 섞으면 월 경계에서
    같은 관측이 실행 머신의 TZ 에 따라 다른 버킷에 들어가 요약이 재현되지 않는다.
    """
    d = datetime.fromtimestamp(ts, timezone.utc)
    start = datetime(d.year, d.month, 1, tzinfo=timezone.utc)
    last = calendar.monthrange(d.year, d.month)[1]
    end = datetime(d.year, d.month, last, 23, 59, 59, tzinfo=timezone.utc)
    return "%04d-%02d" % (d.year, d.month), int(start.timestamp()), int(end.timestamp()) + 1


def resolve_model(pol):
    """consolidation 에 쓸 모델 ID 를 **설정에서만** 가져온다.

    🔴 하드코딩 금지 (prj3#Issue415). 거기서 한 세대 전 Sonnet 의 날짜 붙은 ID 가 코드에 박힌 채
    세대가 지나 발견됐다. 모델 ID 는 코드보다 훨씬 빨리 낡으므로 **코드가 값을 알면 안 된다** —
    기본값조차 두지 않고, 없으면 fail-loud 로 멈춰 운영자가 그 시점의 현행 모델을 적게 한다.
    """
    m = (os.environ.get("AOA_MEMORY_MODEL") or pol.get("consolidation_model") or "").strip()
    if not m:
        raise RuntimeError(
            "consolidation 모델 ID 미지정 — policy.yml `consolidation_model` 또는 "
            "환경변수 AOA_MEMORY_MODEL 에 **그 시점의 현행 모델**을 적을 것. "
            "코드에 기본값을 두지 않는 것은 의도다(모델 ID 는 코드보다 빨리 낡는다)"
        )
    return m


def check_anthropic_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 필요하다 (의존성 0 원칙으로 직접 HTTP 호출).")

def _anthropic_request(method, path, body=None):
    url = "https://api.anthropic.com" + path
    headers = {
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "message-batches-2024-09-24",
        "content-type": "application/json"
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode("utf-8")

def _parse_jsonl(raw):
    """JSONL 본문 → dict 목록. **실제 개행**으로 가른다.

    🔴 회귀 고정 (Issue70): 초안이 `split('\\\\n')`(리터럴 백슬래시+n 두 글자)로 갈라
    Batch 결과 전체가 한 줄로 남았고, 첫 `json.loads` 에서 즉사했다. splitlines 로 고정.
    """
    return [json.loads(l) for l in raw.splitlines() if l.strip()]


def _anthropic_request_jsonl(method, path):
    url = "https://api.anthropic.com" + path
    headers = {
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "message-batches-2024-09-24"
    }
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return _parse_jsonl(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode("utf-8")


def backup_db(path, keep=BACKUP_KEEP):
    """`.backup` API 로 스냅샷. cp 사본 금지 — WAL 이 찢긴다(설계 §백업).

    파괴 작업 직전에만 부른다. 실패하면 예외를 올려 **삭제를 막는다**
    (설계 §데이터 에이징: "삭제는 백업 이후에만 — 삭제 먼저 하면 복구 불능 창이 생긴다").
    """
    bdir = os.path.join(S.AOA_DIR, "backup")
    os.makedirs(bdir, exist_ok=True)
    name = "%s-%s.db" % (os.path.basename(path).replace(".db", ""),
                         time.strftime("%Y%m%d-%H%M%S"))
    dst = os.path.join(bdir, name)
    with S.connect(path) as src, S.connect(dst) as out:
        src.backup(out)
    old = sorted(f for f in os.listdir(bdir)
                 if f.startswith(os.path.basename(path).replace(".db", "") + "-"))
    for f in old[:-keep]:
        os.remove(os.path.join(bdir, f))
    return dst


# --- consolidation -------------------------------------------------------

def digest_bucket(c, bucket, start, end, pol):
    """한 달 구간의 raw 를 집계해 (프로젝트별 요약 dict) 를 돌려준다. 무과금·결정론.

    ⚠️ 그룹 축은 `project_id` 다. `project_name` 은 표시용으로만 싣는다 — 프로젝트를
    개명하면 같은 대상이 두 이름으로 갈려 집계가 쪼개지기 때문이다(같은 이유로 적재 때도
    `project_id` 를 판별 축으로 고정했다 — server.project_id_of).

    `observed_at IS NULL`(시각 미상)은 **구간에 속하지 않으므로 제외**된다. 버리는 게 아니라
    어느 버킷에도 안 들어가는 것이며, 에이징에서도 제외되므로 사라지지 않는다.
    """
    rows = c.execute(
        "SELECT project_id, project_name, session_id, "
        "       json_extract(body,'$.tool')  AS tool, "
        "       json_extract(body,'$.event') AS event, "
        "       observed_at "
        "FROM observation "
        "WHERE observed_at IS NOT NULL AND observed_at >= ? AND observed_at < ?",
        (start, end),
    ).fetchall()

    projs = {}
    for r in rows:
        pid = r["project_id"] or "_unknown"
        p = projs.setdefault(pid, {
            "project_id": pid, "name": r["project_name"], "rows": 0,
            "tools": {}, "events": {}, "sessions": set(),
            "first": r["observed_at"], "last": r["observed_at"],
        })
        p["rows"] += 1
        p["name"] = r["project_name"] or p["name"]      # 최신 이름으로 덮는다(서술용)
        t = r["tool"] or "_none"
        p["tools"][t] = p["tools"].get(t, 0) + 1
        ev = r["event"] if r["event"] in KNOWN_EVENTS else "other"
        p["events"][ev] = p["events"].get(ev, 0) + 1
        if r["session_id"]:
            p["sessions"].add(r["session_id"])
        p["first"] = min(p["first"], r["observed_at"])
        p["last"] = max(p["last"], r["observed_at"])

    for p in projs.values():
        top = sorted(p["tools"].items(), key=lambda kv: (-kv[1], kv[0]))
        head, tail = top[:TOP_TOOLS_PER_PROJECT], top[TOP_TOOLS_PER_PROJECT:]
        if tail:
            head.append(("other", sum(v for _, v in tail)))
        p["tools"] = head
        p["sessions"] = len(p["sessions"])
    return projs


def write_digest_file(emit_dir, bucket, projs):
    """산출을 **파일로 환원**한다 (B-4).

    파일이 산출의 durable 한 자리인 이유: raw 는 90일 뒤 지워지므로, 요약을 DB 에만 두면
    원천이 사라진 뒤 그 행은 어디서도 재생성할 수 없는 고아가 된다. 파일로 내보내고
    DB 행의 `source_path` 가 그것을 가리키게 하면 "모든 행이 원천을 갖는다"는 설계 불변식
    (store.py LEARN_DDL 주석)이 산출물에도 유지된다.

    🔴 frontmatter `source: consolidation` 은 **선택이 아니다.** prj3 어댑터가 이 값으로
    재적재를 거른다 — 빠지면 `consolidation → memory/ → 재적재 → consolidation` 루프가 열려
    요약의 요약이 증폭된다(Issue403 반증 2 · 설계 §승격 경로).
    """
    os.makedirs(emit_dir, exist_ok=True)
    path = os.path.join(emit_dir, "evolved_obs_%s.md" % bucket)
    total = sum(p["rows"] for p in projs.values())
    lines = [
        "---",
        "name: evolved_obs_%s" % bucket,
        "description: %s 관측 요약 — 프로젝트 %d개 · 관측 %d건 (aoa-memory consolidation 산출)"
        % (bucket, len(projs), total),
        "metadata:",
        "  source: consolidation",          # 🔴 재소화 차단 표식 — 지우지 말 것
        "  bucket: %s" % bucket,
        "  generated_by: aoa-memory/worker.py",
        "  strategy: stats",
        "---",
        "",
        "# %s 관측 요약" % bucket,
        "",
        "aoa-memory consolidation 이 `learn.db` 의 raw 관측을 집계한 산출물이다. "
        "무과금 결정론 집계(strategy=stats)이며 같은 입력에 같은 결과가 난다.",
        "",
        "| 프로젝트 | 이름 | 관측 | 세션 | 상위 도구 |",
        "| :--- | :--- | ---: | ---: | :--- |",
    ]
    for p in sorted(projs.values(), key=lambda x: -x["rows"]):
        tools = " · ".join("%s %d" % (t, n) for t, n in p["tools"][:5])
        lines.append("| `%s` | %s | %d | %d | %s |"
                     % (p["project_id"], p["name"] or "-", p["rows"], p["sessions"], tools))
    lines += ["", "> 정본은 원천 관측 파일(`observations.archive/*.jsonl`)이다. "
                  "이 문서와 `learn.instinct` 행은 그 파생이다."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path



def digest_bucket_llm_filter(c, start, end):
    rows = c.execute(
        "SELECT project_id, project_name, json_extract(body,'$.tool') AS tool, body "
        "FROM observation "
        "WHERE observed_at IS NOT NULL AND observed_at >= ? AND observed_at < ?",
        (start, end)
    ).fetchall()
    
    projs = {}
    for r in rows:
        pid = r["project_id"] or "_unknown"
        p = projs.setdefault(pid, {"name": r["project_name"], "rows": [], "count": 0})
        p["count"] += 1
        try:
            body = json.loads(r["body"])
        except Exception:
            continue
            
        out = str(body.get("output", "")).strip()
        stderr = str(body.get("stderr", "")).strip()
        if not out and not stderr:
            continue
            
        is_error = body.get("returnCode", 0) != 0 or bool(stderr) or bool(body.get("interrupted"))
        is_decision = r["tool"] in ("AskUserQuestion", "Agent", "UserPromptSubmit")
        if is_error or is_decision:
            p["rows"].append(json.dumps(body, ensure_ascii=False))
    return projs

def do_consolidate(pol, emit_dir=None, verbose=True, rc=None):
    """소화 1회. **watermark 는 성공했을 때만 오른다** (B-2).

    ## 왜 '월 버킷' 이고 왜 watermark 위만 다시 도는가

    버킷을 월로 자르면 재실행이 자연스럽게 멱등이 된다 — 같은 달을 다시 집계하면 같은
    행을 upsert 할 뿐이다. 다만 **watermark 이하 버킷은 다시 건드리지 않는다**:
    그 구간은 GC 가 raw 를 이미 지웠을 수 있어, 다시 집계하면 남은 일부만으로
    **정확한 요약을 부실한 요약으로 덮어쓰게** 된다. 소화가 끝난 구간은 얼린다.
    """
    if not pol.get("learn_consolidation_enabled", True):
        # 설계 §착수 조건: 비활성 상태의 호출은 "기능 보류" 즉답(0 토큰)
        return {"status": "disabled", "msg": "learn_consolidation_enabled=false — 기능 보류"}

    strategy = str(pol.get("consolidation_strategy") or "stats")
    budget_limit = spent = 0
    if strategy == "llm":
        model = resolve_model(pol)
        check_anthropic_key()
        if rc is None:
            # 예산 기록·배치 추적(payload 저장)이 registry 없이는 성립하지 않는다.
            # 조용히 stats 로 강등하지 않는다(silent-failure 금지) — 명세 1 의 순서 조항.
            raise RuntimeError(
                "llm 전략은 잡 큐(worker.py run) 경유만 — 예산 기록과 배치 추적에 "
                "registry 연결이 필수다. enqueue 후 run 으로 실행할 것")
        # 🔴 예산 게이트 (Issue70 명세 1) — 한도 없는 LLM 배치는 상한 없는 과금 경로.
        #    한도는 운영자가 명시해야 한다. 코드 기본값(0)은 '미지정' 이며 fail-loud 다.
        budget_limit = int(pol.get("consolidation_budget_monthly_tokens", 0) or 0)
        if budget_limit <= 0:
            raise RuntimeError(
                "월 예산 한도 미지정 — policy.yml `consolidation_budget_monthly_tokens` 에 "
                "월 토큰 상한을 적을 것. 한도 없는 LLM 배치는 실행하지 않는다(Issue70 명세 1)")
        spent = S.budget_month_spent(rc, "llm")
        if spent >= budget_limit:
            raise RuntimeError(
                "예산 게이트: 이번 달 소진 %d ≥ 한도 %d — 배치 중단" % (spent, budget_limit))
        active = rc.execute("SELECT count(*) c FROM job WHERE kind='consolidation' AND status='pending_batch'").fetchone()["c"]
        if active > 0:
            return {"status": "delayed", "msg": "이전 LLM 배치가 진행 중이라 다음 버킷을 미룸 (순차 소진)"}

    emit_dir = emit_dir or os.path.join(S.AOA_DIR, "consolidation")
    grace = int(pol.get("consolidation_grace_days", 90)) * 86400
    now = S.now()

    with S.connect(S.LEARN_DB) as c:
        wm = int(S.get_meta(c, WATERMARK_KEY, "0"))
        row = c.execute(
            "SELECT min(observed_at) lo, max(observed_at) hi, count(*) n "
            "FROM observation WHERE observed_at IS NOT NULL"
        ).fetchone()
        if not row or not row["n"]:
            return {"status": "empty", "msg": "소화할 raw 관측이 없다 — 적재가 선행이다", "watermark": wm}

        # 버킷 열거: watermark 위쪽만. 아래쪽은 얼린 구간이다(위 docstring).
        buckets, cur = [], max(row["lo"], wm)
        while cur < row["hi"] + 1:
            b, st, en = month_bucket(cur)
            if en > wm:
                buckets.append((b, st, en))
            cur = en

        if strategy == "llm" and buckets:
            buckets = [buckets[0]] # 순차 소진 - 한 번에 1버킷만

        digested, new_wm, files = [], wm, []
        c.execute("BEGIN IMMEDIATE")
        try:
            for b, st, en in buckets:
                if strategy == "llm":
                    projs = digest_bucket_llm_filter(c, st, en)
                    requests = []
                    for pid, p in projs.items():
                        if not p["rows"]: continue
                        prompt = (f"프로젝트 {pid} ({p['name']}) 의 이번 달 주요 관측 기록(장애/의사결정)이다.\n"
                                  f"총 관측 {p['count']}건 중 주요 신호 {len(p['rows'])}건이 필터링되었다.\n\n"
                                  f"기록:\n")
                        obs_text = "\n".join(p["rows"])[:100000]
                        prompt += obs_text + "\n\n이 기록을 바탕으로 이번 달 프로젝트의 주요 장애 해결 서사와 의사결정을 요약하라."
                        requests.append({
                            "custom_id": pid,
                            "params": {
                                "model": model, "max_tokens": 1024,
                                "messages": [{"role": "user", "content": prompt}]
                            }
                        })
                    if requests:
                        estimated_tokens = sum(len(req["params"]["messages"][0]["content"]) // 4 for req in requests) + len(requests) * 1024
                        # 🔴 예산 게이트 2단 — 예상 소진까지 합산해 한도를 넘으면 발주 전에 멈춘다
                        if spent + estimated_tokens > budget_limit:
                            raise RuntimeError(
                                "예산 게이트: 소진 %d + 예상 %d > 한도 %d — 배치 발주 전 중단"
                                % (spent, estimated_tokens, budget_limit))
                        # 차감은 발주와 같은 순서로 — 발주 실패 시 과대 기록은 다음 달 보정보다
                        # 과금 누락이 나쁘다는 설계 방향(과대 추정 안전측)
                        S.record_budget(rc, "llm", estimated_tokens, len(requests))
                        res, err = _anthropic_request("POST", "/v1/messages/batches", {"requests": requests})
                        if err: raise RuntimeError(f"Anthropic API Error: {err}")
                        return {
                            "status": "pending_batch", "batch_id": res["id"], "bucket": b, "end_ts": en,
                            "projs": {pid: {"name": p["name"], "count": p["count"], "filtered": len(p["rows"])} for pid, p in projs.items()}
                        }
                    projs = digest_bucket(c, b, st, en, pol)
                else:
                    projs = digest_bucket(c, b, st, en, pol)
                
                if not projs:
                    continue
                path = write_digest_file(emit_dir, b, projs)
                files.append(path)
                for p in projs.values():
                    tools = ", ".join("%s %d" % (t, n) for t, n in p["tools"])
                    SV.upsert_instinct(c, {
                        "project_id": p["project_id"],
                        "instinct_id": "evolved_obs_%s" % b,
                        "title": "%s 관측 요약 (%s)" % (b, p["name"] or p["project_id"]),
                        "trigger": "관측 집계 — 구간 %s" % b,
                        "domain": "observation", "scope": "project",
                        # 🔴 산출물 표식 — 다음 라운드의 입력이 되지 않게 하는 쪽 절반
                        "origin": "consolidation",
                        "occurrences": p["rows"],
                        "body": ("관측 %d건 · 세션 %d개 · 구간 %s\n\n도구 분포: %s"
                                 % (p["rows"], p["sessions"], b, tools)),
                        "source_path": path,
                    })
                digested.append((b, en, sum(x["rows"] for x in projs.values())))
                # 유예가 지난 **닫힌** 구간까지만 watermark 를 올린다. 유예 안쪽 구간은
                # 아직 늦은 관측이 도착할 수 있어, 여기서 올리면 그 관측이 소화 없이 늙는다.
                if en <= now - grace:
                    new_wm = max(new_wm, en)
            # watermark 는 산출과 **같은 커밋**으로 올린다(설계 §영속 보증 3항 · agy C-2).
            # 갈라지면 "요약은 실패했는데 원본은 늙어 죽는" 창이 열린다.
            if new_wm > wm:
                S.set_meta(c, WATERMARK_KEY, new_wm)
            c.commit()
        except Exception:
            c.rollback()        # 실패하면 watermark 도 안 오른다 — B-2 의 핵심
            raise

    res = {"status": "ok", "buckets": digested, "files": files,
           "watermark_before": wm, "watermark_after": new_wm}
    if verbose:
        print("소화 버킷 %d개 · 산출 파일 %d개" % (len(digested), len(files)))
        for b, en, n in digested:
            print("  %s  관측 %d건" % (b, n))
        print("watermark %d → %d%s" % (wm, new_wm, "" if new_wm > wm else " (변화 없음 — 유예 안쪽)"))
    return res


# --- 잡 큐 ---------------------------------------------------------------

def recover_expired(rc, pol):
    """만료 lease 회수 (설계 §실행 토폴로지 recovery).

    **살아 있는 잡은 건드리지 않는다** — 판정은 `lease_until < now` 하나이고, 그것이
    "이 잡은 아무도 갱신하지 않는다"는 증거다. 상한을 넘긴 것은 재큐하지 않고 failed 로
    확정한다(poison job 차단).

    consolidation 은 **watermark 교차 검증**을 먼저 한다 — 소화 커밋은 끝났는데 done 마킹
    전에 죽은 잡을 다시 돌리면 이중 실행이 된다(agy 2차 C-1). payload 에 구간 상한(`until`)이
    있고 watermark 가 이미 그 위면 재실행 없이 done 으로 복구한다.
    """
    now = S.now()
    maxatt = int(pol.get("job_max_attempts", 2))
    wm = 0
    try:
        with S.connect(S.LEARN_DB) as lc:
            wm = int(S.get_meta(lc, WATERMARK_KEY, "0"))
    except Exception:
        wm = 0      # 판정 불능이면 기본값은 재실행이다(설계 §recovery)

    recovered = []
    rows = rc.execute(
        "SELECT id, kind, payload, attempts FROM job WHERE status='running' AND lease_until < ?",
        (now,),
    ).fetchall()
    for r in rows:
        until = None
        if r["kind"] in ("consolidation", "index") and r["payload"]:
            try:
                until = json.loads(r["payload"]).get("until")
            except Exception:
                until = None
        rc.execute("BEGIN IMMEDIATE")
        if until is not None and wm >= int(until):
            rc.execute(
                # recovery 전용 술어 — fencing(owner=me)이 아니라 '만료 확인' 자체가
                # 살아 있는 잡 불가침의 근거다(설계 4차 #3·#4)
                "UPDATE job SET status='done', result=? WHERE id=? AND status='running' AND lease_until < ?",
                ("watermark %d ≥ until %d — 소화 완료 확인, 재실행 생략" % (wm, int(until)), r["id"], now),
            )
            recovered.append((r["id"], "done(watermark 확인)"))
        elif r["attempts"] + 1 >= maxatt:
            rc.execute(
                "UPDATE job SET status='failed', attempts=attempts+1, result=? "
                "WHERE id=? AND status='running' AND lease_until < ?",
                ("lease 만료 · 재시도 상한(%d) 도달" % maxatt, r["id"], now),
            )
            recovered.append((r["id"], "failed(상한)"))
        else:
            rc.execute(
                "UPDATE job SET status='pending', attempts=attempts+1, owner=NULL, lease_until=NULL "
                "WHERE id=? AND status='running' AND lease_until < ?",
                (r["id"], now),
            )
            recovered.append((r["id"], "pending(재큐)"))
        rc.commit()
    return recovered


def lease_one(rc, pol):
    """pending 1건을 선점한다. 없으면 None."""
    me, now = owner_tag(), S.now()
    ttl = int(pol.get("lease_ttl_secs", 300))
    rc.execute("BEGIN IMMEDIATE")
    r = rc.execute(
        "SELECT id, kind, payload FROM job WHERE status='pending' ORDER BY created_at LIMIT 1"
    ).fetchone()
    if not r:
        rc.commit()
        return None
    rc.execute(
        "UPDATE job SET status='running', owner=?, lease_until=? WHERE id=? AND status='pending'",
        (me, now + ttl, r["id"]),
    )
    rc.commit()
    return {"id": r["id"], "kind": r["kind"], "payload": r["payload"], "owner": me}


def finish(rc, job, status, result):
    """fencing — 내 lease 인 동안에만 쓴다. 남이 회수해 간 잡을 덮어쓰지 않는다."""
    rc.execute("BEGIN IMMEDIATE")
    rc.execute(
        "UPDATE job SET status=?, result=?, lease_until=NULL "
        "WHERE id=? AND owner=? AND status='running'",
        (status, result[:2000], job["id"], job["owner"]),
    )
    rc.commit()



def check_pending_batches(rc, pol):
    now = S.now()
    rc.execute("BEGIN IMMEDIATE")
    rows = rc.execute("SELECT id, kind, payload, owner FROM job WHERE status='pending_batch'").fetchall()
    rc.commit()
    for r in rows:
        payload = json.loads(r["payload"]) if r["payload"] else {}
        batch_id = payload.get("batch_id")
        bucket = payload.get("bucket")
        if not batch_id:
            finish(rc, r, "failed", "batch_id 없음")
            continue
        
        res, err = _anthropic_request("GET", f"/v1/messages/batches/{batch_id}")
        if err:
            print(f"❌ Anthropic API 에러: {err}")
            continue
        
        status = res.get("processing_status")
        print(f"ℹ️ LLM 배치 {batch_id} 상태: {status}")
        if status == "ended":
            results, err2 = _anthropic_request_jsonl("GET", f"/v1/messages/batches/{batch_id}/results")
            if err2:
                print(f"❌ Anthropic API 에러 (결과 조회): {err2}")
                continue
            
            emit_dir = os.path.join(S.AOA_DIR, "consolidation")
            os.makedirs(emit_dir, exist_ok=True)
            path = os.path.join(emit_dir, f"evolved_obs_{bucket}_llm.md")
            
            lines = [
                "---",
                f"name: evolved_obs_{bucket}_llm",
                f"description: {bucket} 관측 요약 (LLM) — aoa-memory consolidation 산출",
                "metadata:",
                "  source: consolidation",
                f"  bucket: {bucket}",
                "  generated_by: aoa-memory/worker.py",
                "  strategy: llm",
                "---",
                "",
                f"# {bucket} 관측 요약 (LLM)",
                ""
            ]
            
            with S.connect(S.LEARN_DB) as lc:
                lc.execute("BEGIN IMMEDIATE")
                try:
                    for req in results:
                        pid = req["custom_id"]
                        pinfo = payload.get("projs", {}).get(pid, {})
                        if req["result"]["type"] == "succeeded":
                            text = req["result"]["message"]["content"][0]["text"]
                            lines.extend([f"## 프로젝트 `{pid}` ({pinfo.get('name', '-')})", ""])
                            lines.extend([text, ""])
                            
                            SV.upsert_instinct(lc, {
                                "project_id": pid,
                                "instinct_id": f"evolved_obs_{bucket}",
                                "title": f"{bucket} 관측 요약 (LLM) ({pinfo.get('name', pid)})",
                                "trigger": f"관측 집계(LLM) — 구간 {bucket}",
                                "domain": "observation", "scope": "project",
                                "origin": "consolidation",
                                "occurrences": pinfo.get("count", 0),
                                "body": text,
                                "source_path": path,
                            })
                    
                    with open(path, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines) + "\n")
                    
                    en = payload.get("end_ts")
                    grace = int(pol.get("consolidation_grace_days", 90)) * 86400
                    wm = int(S.get_meta(lc, WATERMARK_KEY, "0"))
                    new_wm = wm
                    if en and en <= S.now() - grace:
                        new_wm = max(wm, en)
                    if new_wm > wm:
                        S.set_meta(lc, WATERMARK_KEY, new_wm)
                    lc.commit()
                except Exception as e:
                    lc.rollback()
                    finish(rc, r, "failed", f"DB 저장 실패: {e}")
                    continue
            
            finish(rc, r, "done", f"LLM 배치 {batch_id} 완료, watermark {new_wm}")
            
        elif status in ("canceling", "canceled", "expired"):
            finish(rc, r, "failed", f"LLM 배치 실패/만료: {status}")

def run_jobs(pol, limit=50):
    """큐를 비운다. **상주하지 않는다** — pending 이 마르면 끝난다."""
    done = []
    with S.connect(S.REGISTRY_DB) as rc:
        S.version_gate(rc)
        check_pending_batches(rc, pol)
        for jid, how in recover_expired(rc, pol):
            print("♻️  회수 %s → %s" % (jid, how))
        for _ in range(limit):
            job = lease_one(rc, pol)
            if not job:
                break
            print("▶️  %s (kind=%s)" % (job["id"], job["kind"]))
            try:
                if job["kind"] == "consolidation":
                    r = do_consolidate(pol, verbose=False, rc=rc)
                    if r.get("status") == "pending_batch":
                        rc.execute("BEGIN IMMEDIATE")
                        rc.execute(
                            "UPDATE job SET status='pending_batch', payload=?, lease_until=NULL, owner=NULL "
                            "WHERE id=? AND owner=? AND status='running'",
                            (json.dumps(r, ensure_ascii=False), job["id"], job["owner"])
                        )
                        rc.commit()
                        done.append((job["id"], "pending_batch"))
                    else:
                        finish(rc, job, "done", json.dumps(
                            {k: v for k, v in r.items() if k != "files"}, ensure_ascii=False))
                        done.append((job["id"], "done"))
                else:
                    # 모르는 kind 를 성공으로 닫지 않는다 — 조용한 성공이 가장 나쁜 실패다
                    finish(rc, job, "failed", "미구현 kind: %s" % job["kind"])
                    done.append((job["id"], "failed(미구현)"))
            except Exception as e:
                finish(rc, job, "failed", "%s: %s" % (type(e).__name__, e))
                done.append((job["id"], "failed"))
                print("❌ %s — %s" % (job["id"], e))
    return done


# --- 에이징 (B-3) ---------------------------------------------------------

def gc(pol, apply=False):
    """raw 관측 에이징. 🔴 **watermark 성공 게이트 뒤에만** 지운다.

    삭제 조건은 **셋 다** 만족해야 한다:
      ① `observed_at < watermark`  — 요약이 실제로 소화한 구간만
      ② `observed_at < now - 보존일` — 그리고 충분히 늙었을 때만
      ③ `observed_at IS NOT NULL`  — 시각 미상은 **영원히 대상 아님**

    ③ 이 있는 이유: 미상을 0(=1970)으로 적었다면 ①②를 항상 만족해 첫 GC 에 전멸한다.
    적재 쪽에서 미상을 NULL 로 남기고(server.parse_observed_at) 여기서 NULL 을 제외하는
    두 조치가 짝이다 — 한쪽만 있으면 성립하지 않는다.

    watermark 가 0 이면 **한 건도 지우지 않는다.** 소화가 한 번도 성공하지 않았다는 뜻이고,
    그 상태의 삭제는 요약 없는 원본 소실이다(설계: "요약이 실패했는데 원본이 늙어 죽으면
    지식 손실이다 — silent-failure 금지").

    기본은 dry-run 이다. 실제 삭제는 `--apply` 를 받아야 하고, 그 전에 백업이 성공해야 한다.
    """
    now = S.now()
    keep = int(pol.get("observation_retention_days", 90))
    cutoff = now - keep * 86400
    report = {"applied": bool(apply)}

    with S.connect(S.LEARN_DB) as c:
        wm = int(S.get_meta(c, WATERMARK_KEY, "0"))
        report["watermark"] = wm
        if wm <= 0:
            report["refused"] = ("watermark 0 — 소화가 한 번도 성공하지 않았다. "
                                 "요약 없이 원본을 지우지 않는다")
            report["eligible"] = 0
            return report
        lim = min(wm, cutoff)
        n = c.execute(
            "SELECT count(*) n FROM observation "
            "WHERE observed_at IS NOT NULL AND observed_at < ?", (lim,)
        ).fetchone()["n"]
        report["eligible"] = n
        report["cutoff"] = lim
        report["protected_null"] = c.execute(
            "SELECT count(*) n FROM observation WHERE observed_at IS NULL"
        ).fetchone()["n"]
        if not apply or not n:
            return report
        report["backup"] = backup_db(S.LEARN_DB)   # 실패하면 예외 → 삭제 안 함
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM observation WHERE observed_at IS NOT NULL AND observed_at < ?", (lim,))
        c.commit()
        report["deleted"] = n

    # 종결 job 행도 같은 게이트 아래에서 정리한다(에이징 표 — watermark 와 무관한 축)
    jkeep = int(pol.get("job_retention_days", 30))
    with S.connect(S.REGISTRY_DB) as rc:
        jn = rc.execute(
            "SELECT count(*) n FROM job WHERE status IN ('done','failed') AND created_at < ?",
            (now - jkeep * 86400,),
        ).fetchone()["n"]
        report["job_eligible"] = jn
        if apply and jn:
            rc.execute("BEGIN IMMEDIATE")
            rc.execute("DELETE FROM job WHERE status IN ('done','failed') AND created_at < ?",
                       (now - jkeep * 86400,))
            rc.commit()
            report["job_deleted"] = jn
    return report


# --- CLI ------------------------------------------------------------------

def cmd_status(pol):
    with S.connect(S.LEARN_DB) as c:
        wm = int(S.get_meta(c, WATERMARK_KEY, "0"))
        obs = c.execute("SELECT count(*) n, min(observed_at) lo, max(observed_at) hi, "
                        "sum(observed_at IS NULL) nul FROM observation").fetchone()
        ins = c.execute("SELECT count(*) n, sum(origin='consolidation') ev FROM instinct").fetchone()
    with S.connect(S.REGISTRY_DB) as rc:
        jobs = rc.execute("SELECT status, count(*) n FROM job GROUP BY status").fetchall()

    def ts(v):
        return datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%d") if v else "-"

    print("| 항목 | 값 |")
    print("| :--- | :--- |")
    print("| observation | %d행 (구간 %s ~ %s · 시각 미상 %d) |"
          % (obs["n"], ts(obs["lo"]), ts(obs["hi"]), obs["nul"] or 0))
    print("| instinct | %d행 (그 중 consolidation 산출 %d) |" % (ins["n"], ins["ev"] or 0))
    print("| watermark | %d (%s) |" % (wm, ts(wm) if wm else "미소화"))
    print("| job | %s |" % (", ".join("%s %d" % (r["status"], r["n"]) for r in jobs) or "없음"))
    print("| strategy | %s · 유예 %s일 · 보존 %s일 |"
          % (pol.get("consolidation_strategy"), pol.get("consolidation_grace_days"),
             pol.get("observation_retention_days")))


def main():
    ap = argparse.ArgumentParser(description="aoa-memory 잡 실행기 (1회 실행 후 종료 — 상주는 launchd 주기 기동이 준다)")
    ap.add_argument("cmd", choices=("status", "run", "consolidate", "gc", "enqueue"))
    ap.add_argument("--apply", action="store_true", help="gc: 실제 삭제 (기본은 dry-run)")
    ap.add_argument("--emit-dir", help="consolidate: 산출 파일 디렉토리 (기본 data/aoa/consolidation)")
    args = ap.parse_args()

    S.init_stores()
    pol = P.load()

    if args.cmd == "status":
        cmd_status(pol)
    elif args.cmd == "run":
        d = run_jobs(pol)
        print("처리 %d건%s" % (len(d), "" if d else " — pending 없음"))
    elif args.cmd == "consolidate":
        r = do_consolidate(pol, emit_dir=args.emit_dir)
        if r["status"] != "ok":
            print("ℹ️ %s" % r.get("msg"))
    elif args.cmd == "enqueue":
        jid = "job_" + uuid.uuid4().hex[:12]
        with S.connect(S.REGISTRY_DB) as rc:
            rc.execute("BEGIN IMMEDIATE")
            rc.execute("INSERT INTO job(id, store, kind, status, payload, result, attempts, "
                       "owner, lease_until, blocked_since, created_at) "
                       "VALUES(?, 'learn', 'consolidation', 'pending', NULL, NULL, 0, "
                       "NULL, NULL, NULL, ?)", (jid, S.now()))
            rc.commit()
        print("✅ enqueue %s — `worker.py run` 으로 소비" % jid)
    elif args.cmd == "gc":
        r = gc(pol, apply=args.apply)
        if r.get("refused"):
            print("🛑 삭제 거부 — %s" % r["refused"])
            return 0
        print("watermark %d · 삭제 대상 %d행 · 시각 미상 보호 %d행"
              % (r["watermark"], r["eligible"], r.get("protected_null", 0)))
        print("종결 job 삭제 대상 %d행" % r.get("job_eligible", 0))
        if args.apply:
            print("🗑  삭제 %d행 (백업 %s)" % (r.get("deleted", 0), r.get("backup", "-")))
        else:
            print("ℹ️ dry-run — 실제 삭제는 `--apply`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
