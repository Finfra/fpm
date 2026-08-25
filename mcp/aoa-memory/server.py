#!/usr/bin/env python3
"""aoa-memory MCP 서버 — 최소셋 (prj5 Issue68 B-2)

⚠️ 설계 SSOT: ~/_git/___common/_doc_arch/aoa-memory-design.md
   도구 표면·통지 계층·강건성 규약은 그 문서가 정본이다.

설계 원칙 승계
  * **의존성 0** — MCP 는 JSON-RPC 2.0 over stdio. SDK 없이 표준 라이브러리로 짠다
    (aoa-mq 서버와 동일 규약 — prj5 에 venv 를 들이지 않는다).
  * **도구를 속도로 분리한다** — 빠른 계열(~ms·결정론·무과금)과 느린 계열(초 단위·과금)을
    이름으로 드러낸다. 느린 계열은 반드시 `job_id` 를 돌려주고 비동기로 회수한다.
  * **읽기 기본은 ns 단위 전체 반환 + 상한** — 키를 맞히게 하지 않는다. 초과분은
    `truncated` + `next_cursor` 로 알린다(부분 반환을 "없음" 으로 오독하는 환각 차단).

범위
  * ✅ **잡 실행기는 [`worker.py`](worker.py) 가 소비한다** (Issue69 B) — lease 선점·만료 회수·
    consolidation·watermark·에이징까지. 단 **상주 데몬이 아니다**(수동 실행 진입점).
    `learn_index` 는 여기서 enqueue 까지이고, 실제 실행은 `worker.py run` 이다.
  * ❌ **배치 LLM·예산 차감 미구현** — consolidation 기본 전략은 무과금 결정론 집계(stats)다.
    `llm` 전략은 자리만 있고 호출하면 fail-loud (Issue69 축소 — 예산 계층이 선행).
  * ❌ `kb-m.db`(2순위) · `mq.db`(3순위) 미착수.
"""

import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store as S  # noqa: E402

KV_LIMIT = 100          # 설계 초기값 — 실측 후 재산정 대상
SEARCH_LIMIT = 20

TOOLS = [
    {
        "name": "registry_list",
        "description": "aoa-memory 스토어 카탈로그를 조회한다(어떤 스토어가 있고 건강한가).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kv_get_all",
        "description": (
            "세션을 건너 유지되는 싱글톤 KV 를 **네임스페이스 단위로 전부** 돌려준다. "
            "키를 맞힐 필요가 없다. 만료분은 제외되며, 상한(100행) 초과 시 truncated 로 알린다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "네임스페이스(필수)"},
                "cursor": {"type": "string", "description": "이전 응답의 next_cursor"},
            },
            "required": ["ns"],
        },
    },
    {
        "name": "kv_set",
        "description": "싱글톤 KV 에 값을 쓴다. ttl_sec 을 주면 그만큼 뒤 만료(기본 영속).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string"},
                "key": {"type": "string"},
                "value": {"type": "string"},
                "ttl_sec": {"type": "integer", "description": "생략 시 영속"},
                "by": {"type": "string", "description": "쓴 주체 표기(선택)"},
            },
            "required": ["ns", "key", "value"],
        },
    },
    {
        "name": "learn_search",
        "description": (
            "learn.db 의 instinct 를 전문 검색한다(FTS5/BM25 · 무과금 · ~ms). "
            "⚠️ 정본은 `memory/instinct_*.md` 파일이고 여기 있는 것은 파생이다 — "
            "고칠 때는 파일을 고친다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "검색어(FTS5 문법)"},
                "project_id": {"type": "string", "description": "프로젝트 한정(선택)"},
                "limit": {"type": "integer", "description": "기본 20"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "learn_upsert",
        "description": (
            "instinct 1건을 learn.db 에 적재·갱신한다(결정론·무과금). 파일 어댑터의 착지점이다. "
            "origin 은 관측 유래면 'session-observation', consolidation 환원본이면 'consolidation' — "
            "후자는 재소화 대상에서 제외된다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "instinct_id": {"type": "string"},
                "title": {"type": "string"},
                "trigger": {"type": "string"},
                "confidence": {"type": "number"},
                "domain": {"type": "string"},
                "scope": {"type": "string"},
                "origin": {"type": "string"},
                "occurrences": {"type": "integer"},
                "body": {"type": "string"},
                "source_path": {"type": "string", "description": "원천 파일 경로(정본)"},
            },
            "required": ["project_id", "instinct_id", "source_path"],
        },
    },
    {
        "name": "learn_observe",
        "description": (
            "관측(raw)을 learn.db 에 **배치로** 적재한다(결정론·무과금). homunculus "
            "`observations*.jsonl` 어댑터의 착지점이다. 자연키는 (원천 파일, 줄번호)라 "
            "같은 파일을 다시 넣어도 늘지 않는다. ⚠️ 정본은 파일이고 여기 있는 것은 파생이다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "이 배치가 나온 원천 파일 경로(정본)"},
                "start_line": {"type": "integer", "description": "items[0] 의 원본 줄번호(1-based, 기본 1)"},
                "items": {
                    "type": "array",
                    "description": "원본 레코드 배열. 정규화는 이쪽이 한다 — 가공해서 넘기지 말 것",
                    "items": {"type": "object"},
                },
            },
            "required": ["source_path", "items"],
        },
    },
    {
        "name": "learn_index",
        "description": (
            "느린 계열 — consolidation·재색인을 **큐에 넣고 job_id 를 즉시 돌려준다**(동기 블로킹 없음). "
            "실행은 `worker.py run` 이 소비한다 — 상주 데몬이 아니라 **누군가 돌려야 도는** 큐다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "description": "consolidation | index (기본 consolidation)"},
                "payload": {"type": "string", "description": "잡 인자 JSON 문자열(선택)"},
            },
        },
    },
    {
        "name": "job_get",
        "description": "잡 상태를 조회한다. id 를 주면 1건, 생략하면 미종결·최근 종결 목록.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "limit": {"type": "integer", "description": "기본 20"},
            },
        },
    },
]


# --- 도구 구현 ------------------------------------------------------------

def t_registry_list(a):
    with S.connect(S.REGISTRY_DB) as c:
        S.version_gate(c)
        rows = c.execute(
            "SELECT name, kind, path, owner_prj, schema_version, health, note FROM store ORDER BY name"
        ).fetchall()
    if not rows:
        return "스토어 없음 — `python3 mcp/aoa-memory/store.py` 로 초기화할 것"
    out = ["| 스토어 | kind | v | health | 비고 |", "| :--- | :--- | :-: | :--- | :--- |"]
    for r in rows:
        out.append("| %s | %s | %s | %s | %s |" % (
            r["name"], r["kind"], r["schema_version"], r["health"], r["note"] or ""))
    return "\n".join(out)


def t_kv_get_all(a):
    ns = a["ns"]
    cursor = a.get("cursor") or ""
    now = S.now()
    with S.connect(S.REGISTRY_DB) as c:
        S.version_gate(c)
        rows = c.execute(
            "SELECT key, value, expires_at, updated_at, updated_by FROM kv "
            "WHERE ns=? AND key>? AND (expires_at IS NULL OR expires_at>?) "
            "ORDER BY key LIMIT ?",
            (ns, cursor, now, KV_LIMIT + 1),
        ).fetchall()
    truncated = len(rows) > KV_LIMIT
    rows = rows[:KV_LIMIT]
    payload = {
        "ns": ns,
        "count": len(rows),
        "truncated": truncated,
        "items": [{"key": r["key"], "value": r["value"], "updated_by": r["updated_by"]} for r in rows],
    }
    if truncated:
        payload["next_cursor"] = rows[-1]["key"]
        payload["hint"] = "상한 초과 — next_cursor 로 이어 받거나 ns 를 좁힐 것. 이것은 '없음' 이 아니다"
    return json.dumps(payload, ensure_ascii=False, indent=2)


def t_kv_set(a):
    ttl = a.get("ttl_sec")
    exp = (S.now() + int(ttl)) if ttl else None
    with S.connect(S.REGISTRY_DB) as c:
        S.version_gate(c)
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO kv(ns, key, value, expires_at, updated_at, updated_by) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(ns, key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (a["ns"], a["key"], a["value"], exp, S.now(), a.get("by") or "mcp"),
        )
        c.commit()
    return "✅ kv %s/%s 기록" % (a["ns"], a["key"]) + (" (TTL %ss)" % ttl if ttl else "")


def t_learn_search(a):
    limit = int(a.get("limit") or SEARCH_LIMIT)
    q = a["q"]
    sql = ("SELECT f.project_id, f.instinct_id, f.title, i.source_path, i.confidence, "
           "       bm25(instinct_fts) AS score "
           "FROM instinct_fts f "
           "LEFT JOIN instinct i ON i.project_id=f.project_id AND i.instinct_id=f.instinct_id "
           "WHERE instinct_fts MATCH ?")
    args = [q]
    if a.get("project_id"):
        sql += " AND f.project_id=?"
        args.append(a["project_id"])
    sql += " ORDER BY score LIMIT ?"
    args.append(limit)
    with S.connect(S.LEARN_DB) as c:
        try:
            rows = c.execute(sql, args).fetchall()
        except Exception as e:
            return "❌ 검색 실패(FTS5 문법 확인): %s" % e
    if not rows:
        return "매치 0건 — q=%r" % q
    out = ["| instinct | project | conf | 원천(정본) |", "| :--- | :--- | :-: | :--- |"]
    for r in rows:
        out.append("| %s | %s | %s | %s |" % (
            r["title"] or r["instinct_id"], r["project_id"], r["confidence"], r["source_path"] or ""))
    return "\n".join(out)


def upsert_instinct(c, a):
    """instinct 1건을 **주어진 커넥션·트랜잭션 안에서** 쓴다. 커밋하지 않는다.

    `t_learn_upsert` 에서 분리한 이유는 하나다 — consolidation 이 산출 행과
    `_meta.consolidated_until` 을 **한 커밋**으로 올려야 하는데(설계 §영속 보증 3항),
    스스로 커밋하는 함수로는 그 원자성을 만들 수 없다. SQL 을 worker 쪽에 복제하는 대신
    경계를 이렇게 갈랐다 — 스키마를 아는 곳은 여전히 이 파일 하나다.
    """
    now = S.now()
    src = a["source_path"]
    mtime = int(os.path.getmtime(src)) if os.path.exists(src) else None
    row = (
        a["project_id"], a["instinct_id"], a.get("title"), a.get("trigger"),
        float(a["confidence"]) if a.get("confidence") is not None else None,
        a.get("domain"), a.get("scope"), a.get("origin") or "session-observation",
        int(a["occurrences"]) if a.get("occurrences") is not None else None,
        a.get("body"), src, mtime, now,
    )
    c.execute(
        "INSERT INTO instinct(project_id, instinct_id, title, trigger, confidence, domain, "
        "scope, origin, occurrences, body, source_path, source_mtime, ingested_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(project_id, instinct_id) DO UPDATE SET "
        "title=excluded.title, trigger=excluded.trigger, confidence=excluded.confidence, "
        "domain=excluded.domain, scope=excluded.scope, origin=excluded.origin, "
        "occurrences=excluded.occurrences, body=excluded.body, source_path=excluded.source_path, "
        "source_mtime=excluded.source_mtime, ingested_at=excluded.ingested_at",
        row,
    )
    # FTS 는 외부 콘텐츠 연동이 아니라 코드가 동기화한다 — 재적재는 delete 후 insert(멱등)
    c.execute("DELETE FROM instinct_fts WHERE project_id=? AND instinct_id=?",
              (a["project_id"], a["instinct_id"]))
    c.execute(
        "INSERT INTO instinct_fts(project_id, instinct_id, title, trigger, body) VALUES(?,?,?,?,?)",
        (a["project_id"], a["instinct_id"], a.get("title") or "", a.get("trigger") or "",
         a.get("body") or ""),
    )


def t_learn_upsert(a):
    with S.connect(S.LEARN_DB) as c:
        c.execute("BEGIN IMMEDIATE")
        upsert_instinct(c, a)
        c.commit()
    return "✅ instinct %s/%s 적재 (원천 %s)" % (
        a["project_id"], a["instinct_id"], a["source_path"])


def parse_observed_at(rec):
    """관측 시각을 epoch 초로. **못 읽으면 None 이다 — 0 이 아니다.**

    🔴 이 구별이 안전 장치다. `observed_at` 은 에이징 게이트의 판정 축(`observed_at < watermark`)
    이라 0 을 넣으면 1970년으로 읽혀 **다음 GC 에서 즉시 삭제 대상**이 된다. 시각을 못 읽은
    것은 "아주 오래됨"이 아니라 **미상**이고, 미상은 지우지 않는다(worker.gc 가 NULL 을 제외한다).

    prj3 가 instinct 적재에서 `occurrences`·`confidence` 를 0 으로 강제했다가 90건을 날조한
    것과 같은 결함이며, 이쪽은 결과가 삭제라 더 무겁다.
    """
    ts = rec.get("timestamp") or rec.get("observed_at")
    if ts is None:
        return None
    if isinstance(ts, (int, float)):          # 이미 epoch 인 입력도 받는다
        return int(ts)
    s = str(ts).strip()
    if not s:
        return None
    try:
        # homunculus 실측 형식은 `2026-04-13T05:58:51Z` (UTC). fromisoformat 은 Z 를 못 읽는다
        from datetime import datetime, timezone
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp())
    except Exception:
        return None


def project_id_of(rec, source_path):
    """판별 축은 `project_id` 다 — 없으면 경로에서 되찾는다.

    ⚠️ `project_name` 을 대신 쓰지 않는다. 프로젝트를 개명하면 같은 대상이 두 이름으로
    갈려 GROUP BY 가 쪼개진다(prj3 가 `origin` 열에서 겪은 것과 같은 계열의 오염 —
    판별 열에는 변하는 값을 넣지 않는다). `project_name` 은 서술용이며 최신값으로 덮인다.
    """
    pid = rec.get("project_id")
    if pid:
        return str(pid)
    parts = os.path.abspath(source_path).split(os.sep)
    if "projects" in parts:
        i = parts.index("projects")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def t_learn_observe(a):
    """관측 배치 적재 — 계약은 TOOLS 의 learn_observe 스키마.

    ## 배치인 이유 (A-2)
    원천이 931파일·41,466행·65.7MB(2026-08-16 실측)다. 건당 stdio 왕복은 성립하지 않는다.
    그래서 ① 도구 자체가 **리스트를 받고** ② 대량 적재는 stdio 를 건너뛰고 이 함수를
    **모듈 직접 호출**한다(prj3 어댑터가 `t_learn_upsert` 를 그렇게 쓰고 있다 —
    프로토콜만 우회하고 로직·스키마는 prj5 소유 그대로다).

    ## 멱등 (A-3)
    자연키 `(원천 파일, 줄번호)` → `store.observation_id()`. 충돌 시 **아무것도 하지 않는다**
    (`DO NOTHING`) — raw 는 불변이라 덮어쓸 것이 없고, 덮어쓰면 `ingested_at` 만 흔들려
    "다시 넣어도 같다"는 성질이 약해진다. 몇 건이 새로 들어가고 몇 건이 이미 있었는지는
    응답에 숫자로 나온다(조용한 성공 금지).
    """
    src = a["source_path"]
    items = a.get("items") or []
    start = int(a.get("start_line") or 1)
    now = S.now()

    rows, bad, no_ts = [], 0, 0
    for idx, rec in enumerate(items):
        if not isinstance(rec, dict):
            bad += 1
            continue
        line = int(rec.get("line") or (start + idx))
        path = rec.get("source_path") or src
        oat = parse_observed_at(rec)
        if oat is None:
            no_ts += 1
        rows.append((
            S.observation_id(path, line),
            project_id_of(rec, path), rec.get("project_name"),
            rec.get("session") or rec.get("session_id"),
            oat,
            # 원문을 그대로 싣는다 — 정렬 키로 직렬화해 같은 레코드가 항상 같은 바이트가 되게 한다.
            # 실측 최대 10.7KB·p99 5.9KB 라 자르지 않는다(자르면 소화가 조용히 부실해진다).
            json.dumps(rec, ensure_ascii=False, sort_keys=True),
            path, now,
        ))

    with S.connect(S.LEARN_DB) as c:
        before = c.total_changes
        wm = int(S.get_meta(c, "consolidated_until", "0"))
        c.execute("BEGIN IMMEDIATE")
        c.executemany(
            "INSERT INTO observation(id, project_id, project_name, session_id, observed_at, "
            "body, source_path, ingested_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO NOTHING",
            rows,
        )
        c.commit()
        inserted = c.total_changes - before

    # 🔴 늦은 도착 고지 — watermark 아래로 들어온 관측은 이미 소화가 끝난 구간이라
    #    **요약에 반영되지 않는다**. 조용히 넘기면 "적재됐으니 반영됐다"로 오독된다.
    #    유예(consolidation_grace_days)를 늘리면 줄어든다 — 근거는 policy.yml 주석.
    late = sum(1 for r in rows if wm and r[4] is not None and r[4] <= wm) if wm else 0

    out = ["✅ observation %d건 적재 (이미 있던 것 %d건) — 원천 %s"
           % (inserted, len(rows) - inserted, src)]
    if bad:
        out.append("⚠️ dict 아님 %d건 건너뜀" % bad)
    if no_ts:
        out.append("ℹ️ 시각 미상 %d건 → NULL. 0 이 아니다 — 미상은 에이징에서 제외된다" % no_ts)
    if late:
        out.append("🔴 watermark(%d) 이하 도착 %d건 — 이미 소화된 구간이라 **요약에 반영되지 않는다**"
                   % (wm, late))
    return "\n".join(out)


def t_learn_index(a):
    jid = "job_" + uuid.uuid4().hex[:12]
    kind = a.get("kind") or "consolidation"
    with S.connect(S.REGISTRY_DB) as c:
        S.version_gate(c)
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO job(id, store, kind, status, payload, result, attempts, owner, "
            "lease_until, blocked_since, created_at) "
            "VALUES(?, 'learn', ?, 'pending', ?, NULL, 0, NULL, NULL, NULL, ?)",
            (jid, kind, a.get("payload"), S.now()),
        )
        c.commit()
    return ("✅ enqueue %s (kind=%s, status=pending)\n"
            "⚠️ 실행 대기 — 상주 데몬이 없다. `python3 mcp/aoa-memory/worker.py run` 을 돌려야 "
            "소비된다(설계상 lazy — 배치 지연이 실제 pain 일 때 상주로 승격)." % (jid, kind))


def t_job_get(a):
    with S.connect(S.REGISTRY_DB) as c:
        S.version_gate(c)
        if a.get("id"):
            r = c.execute("SELECT * FROM job WHERE id=?", (a["id"],)).fetchone()
            if not r:
                return "❌ 없는 잡: %s" % a["id"]
            return json.dumps({k: r[k] for k in r.keys()}, ensure_ascii=False, indent=2)
        rows = c.execute(
            "SELECT id, store, kind, status, attempts, created_at FROM job "
            "ORDER BY created_at DESC LIMIT ?", (int(a.get("limit") or 20),)
        ).fetchall()
    if not rows:
        return "잡 없음"
    out = ["| id | store | kind | status | attempts |", "| :--- | :--- | :--- | :--- | :-: |"]
    for r in rows:
        out.append("| %s | %s | %s | %s | %s |" % (
            r["id"], r["store"], r["kind"], r["status"], r["attempts"]))
    return "\n".join(out)


HANDLERS = {
    "registry_list": t_registry_list,
    "kv_get_all": t_kv_get_all,
    "kv_set": t_kv_set,
    "learn_search": t_learn_search,
    "learn_upsert": t_learn_upsert,
    "learn_observe": t_learn_observe,
    "learn_index": t_learn_index,
    "job_get": t_job_get,
}


def reply(rid, result=None, error=None):
    m = {"jsonrpc": "2.0", "id": rid}
    if error:
        m["error"] = error
    else:
        m["result"] = result
    sys.stdout.write(json.dumps(m, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method, rid = req.get("method"), req.get("id")
        if method == "initialize":
            reply(rid, {"protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "aoa-memory", "version": "0.1.0"}})
        elif method == "tools/list":
            reply(rid, {"tools": TOOLS})
        elif method == "tools/call":
            p = req.get("params") or {}
            fn = HANDLERS.get(p.get("name"))
            if not fn:
                reply(rid, error={"code": -32601, "message": "unknown tool: %s" % p.get("name")})
                continue
            try:
                text = fn(p.get("arguments") or {})
            except Exception as e:      # fail-soft — 서버가 죽으면 세션의 도구가 통째로 끊긴다
                text = "❌ 실행 오류: %s" % e
            reply(rid, {"content": [{"type": "text", "text": text}]})
        elif rid is not None:
            reply(rid, error={"code": -32601, "message": "unknown method: %s" % method})


if __name__ == "__main__":
    main()
