#!/usr/bin/env python3
"""fbot-inbox.py — 매니저 명령 인박스 (prj3#Issue552)

**결속된 매니저가 다른 프로젝트의 요청을 무시하던 문제**를 푼다. 종전에는 봇에게
일을 시키려면 그 봇에 **결속해야** 했고 결속은 배타라 두 번째 요청이 거부됐다.

🔴 **결속(몸)과 명령 수신(창구)은 다른 축이다.**
  * 결속은 **1:1 그대로** 둔다 — 다중화하면 "이 작업을 누가 했나" 가 흐려진다(F4)
  * 매니저는 결속 없이 **N:1** 요청을 받는다. 결속 여부와 무관하게 요청이 쌓인다

**인박스는 신설 테이블이 아니다** — `job.owner` 가 이미 *"누구에게 귀속된 일인가"*
를 답한다. 매니저 앞으로 온 `open` 요청 목록이 곧 인박스다.

⚠️ `kind` 는 `fbot` 접두를 유지한다 — `job` 트리거가 `kind LIKE 'fbot%'` 인 레코드의
`owner` 를 `owner_id`(FK→`bot`)로 옮긴다. 접두를 버리면 봇 축에서 빠져 감사기·조직도
집계가 이 요청들을 못 본다.

설계 SSOT: `_doc_arch/fbot-manager-design.md`
"""
import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_DB = os.environ.get("FBOT_REGISTRY_DB") or os.path.join(
    # prj3#Issue559 — fbot-state.py 와 같은 해석(AOA_MEMORY_DIR → ~/.claude/data/aoa). 개인 경로 하드코딩은
    #   번들로 나가는 순간 타 머신에서 "DB 없음" 이 된다.
    os.environ.get("AOA_MEMORY_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa"),
    "registry.db")
KIND = "fbot_request"          # ⚠️ fbot 접두 필수 (위 주석)
CHAIN_MAX = int(os.environ.get("FBOT_REQUEST_CHAIN_MAX") or 3)   # 되물음 체인 상한 (prj3#Issue563)


def _org():
    """`is_manager` 판정을 재사용한다 — 로직을 복제하면 두 벌이 되어 갈라진다."""
    path = os.path.join(HERE, "fbot-org.py")
    spec = importlib.util.spec_from_file_location("fbot_org", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _state():
    """fbot-state.py 의 record_event/notify_hub_event 재사용 (prj3#Issue575) — 이벤트 형식을 두 벌 두지 않는다."""
    path = os.path.join(HERE, "fbot-state.py")
    spec = importlib.util.spec_from_file_location("fbot_state", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _con(readonly=False):
    if readonly:
        return sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True, timeout=5)
    con = sqlite3.connect(REGISTRY_DB, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def _bot(con, bot_id):
    con.row_factory = sqlite3.Row
    return con.execute("SELECT bot_id, role, state, career FROM bot WHERE bot_id=?",
                       (bot_id,)).fetchone()


def send(to, body, from_bot="", from_session="", req_kind="ask", prj=None, corr_id=None):
    """요청 적재. 🔴 **결속 여부를 보지 않는다** — 그것이 이 설계의 요점이다."""
    con = _con()
    try:
        row = _bot(con, to)
        if not row:
            return {"ok": False, "error": f"대장에 없는 수신자: {to}"}
        if not _org().is_manager(row["role"]):
            # 워커에게 직접 꽂으면 결속 경쟁·문맥 전환이 재발한다. 매니저를 거쳐야 한다.
            return {"ok": False, "error":
                    f"{to}(role={row['role']}) 는 매니저가 아니다 — 인박스가 없다. "
                    f"매니저(chief·lead·hr)에게 보내면 그가 판단해 지시한다"}
        rid = f"fbotreq-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        # prj3#Issue563 — 되물음 체인 깊이. corr_id 로 잇는 요청은 부모 depth+1 이고 상한을
        #   넘으면 거부한다. 매니저 둘이 서로 되묻는 핑퐁은 원리적으로 무한이라, 상한에서
        #   사람에게 올리는 것이 유일한 종결이다.
        depth = 0
        if corr_id:
            parent = con.execute(
                "SELECT payload FROM job WHERE kind=? AND (id=? OR json_extract(payload,'$.corr_id')=?)"
                " ORDER BY created_at LIMIT 1", (KIND, corr_id, corr_id)).fetchone()
            if parent:
                try:
                    depth = int(json.loads(parent[0] or "{}").get("depth") or 0) + 1
                except (ValueError, TypeError):
                    depth = 1
            if depth > CHAIN_MAX:
                return {"ok": False, "error":
                        f"되물음 체인 상한 초과 (depth {depth} > {CHAIN_MAX}) — corr_id {corr_id}. "
                        f"더 묻지 말고 사람에게 올린다: /mq-send --due +0d 또는 escalate", "depth": depth}
        payload = {"from": from_bot, "from_session": from_session, "kind": req_kind,
                   "body": body, "prj": prj, "corr_id": corr_id or rid, "depth": depth}
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (rid, "fbot", KIND, "open", json.dumps(payload, ensure_ascii=False),
             to, int(time.time())))
        _st = _state(); _st.record_event(con, to, "request", f"← {from_bot or from_session[:8] or '?'}: {body[:80]}", rid)   # prj3#Issue575
        _st.notify_hub_event(to, "request", rid)
        return {"ok": True, "action": "send", "id": rid, "to": to,
                "to_state": row["state"], "corr_id": payload["corr_id"],
                "note": "결속 여부와 무관하게 적재된다"}
    finally:
        con.close()


def inbox(bot_id, status="open", limit=20):
    con = _con(readonly=True)
    con.row_factory = sqlite3.Row
    try:
        q = ("SELECT id, status, payload, result, created_at FROM job"
             " WHERE kind=? AND owner=?" + (" AND status=?" if status else "") +
             " ORDER BY created_at")
        args = [KIND, bot_id] + ([status] if status else [])
        rows = con.execute(q, args).fetchall()[:limit]
    finally:
        con.close()
    out = []
    for r in rows:
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            pl = {}
        out.append({"id": r["id"], "status": r["status"], "from": pl.get("from"),
                    "kind": pl.get("kind"), "body": pl.get("body"),
                    "prj": pl.get("prj"), "corr_id": pl.get("corr_id"),
                    "created_at": r["created_at"],
                    "result": json.loads(r["result"]) if r["result"] else None})
    return {"ok": True, "action": "inbox", "bot_id": bot_id, "count": len(out),
            "items": out}


def reply(req_id, status, body="", by=""):
    """응답은 **요청 레코드에 붙인다**(`job.result`). 새 kind 를 만들면 응답이 또
    하나의 요청처럼 보여 인박스가 오염된다 — *"처리할 것"* 과 *"처리된 것"* 이
    구분되지 않는다."""
    if status not in ("accepted", "rejected", "done"):
        return {"ok": False, "error": f"허용되지 않은 status: {status}"}
    con = _con()
    try:
        row = con.execute("SELECT owner, status FROM job WHERE id=? AND kind=?",
                          (req_id, KIND)).fetchone()
        if not row:
            return {"ok": False, "error": f"요청 없음: {req_id}"}
        res = {"status": status, "body": body, "by": by or row[0], "at": int(time.time())}
        # done 이면 원장도 닫는다 — 미종결로 남으면 인박스에 계속 뜬다
        new_status = "done" if status == "done" else "open"
        con.execute("UPDATE job SET result=?, status=? WHERE id=?",
                    (json.dumps(res, ensure_ascii=False), new_status, req_id))
        _st = _state(); _st.record_event(con, row[0], f"reply:{status}", (body or "")[:80], req_id); _st.notify_hub_event(row[0], f"reply:{status}", req_id)   # prj3#Issue575
        return {"ok": True, "action": "reply", "id": req_id, "result": res,
                "job_status": new_status}
    finally:
        con.close()


def pending(bot_id=None, session_id=None, limit=10):
    """소비 3경로(출근·tick·결속 중)의 **공용 조회**. *"이 매니저(들) 앞에 아직 안 본 요청"*.

    `open` 만 센다 — 매니저가 `reply --status accepted` 로 받으면 그 순간 넛지가 그친다.
    이 전이가 곧 ACK 라 별도 읽음 표시가 필요 없다.

    ⚠️ `--session-id` 는 마커 파일 내용을 쓰지 않는다(Issue449 — 마지막 1건만 담겨
    권위가 아니다). *누가 이 세션에 있는가* 는 DB 가 답한다. 한 세션에 매니저가 둘이면
    둘 다 돌려준다."""
    con = _con(readonly=True)
    con.row_factory = sqlite3.Row
    try:
        if session_id:
            bots = [r for r in con.execute(
                "SELECT bot_id, role FROM bot WHERE session_id=? AND state<>'checkout'",
                (session_id,)).fetchall()]
        elif bot_id:
            r = _bot(con, bot_id)
            bots = [r] if r else []
        else:
            return {"ok": False, "error": "--bot-id 또는 --session-id 필요"}
        org = _org()
        mgrs = [b["bot_id"] for b in bots if org.is_manager(b["role"])]
        items = []
        for m in mgrs:
            rows = con.execute(
                "SELECT id, payload, created_at FROM job WHERE kind=? AND owner=?"
                " AND status='open' AND result IS NULL ORDER BY created_at",
                (KIND, m)).fetchall()[:limit]
            for r in rows:
                try:
                    pl = json.loads(r["payload"] or "{}")
                except ValueError:
                    pl = {}
                items.append({"id": r["id"], "to": m, "from": pl.get("from"),
                              "from_session": pl.get("from_session"),
                              "kind": pl.get("kind"), "body": pl.get("body"),
                              "prj": pl.get("prj"), "created_at": r["created_at"]})
    finally:
        con.close()
    return {"ok": True, "action": "pending", "managers": mgrs, "count": len(items),
            "items": items}


def escalate(older_than_min=30, apply=False):
    """tick 경로 — **임계 초과 미처리 요청**을 aoa-mq alert 로 올린다(1건당 1회).

    매니저가 출근하지 않으면 인박스는 영원히 안 읽힌다. 그 침묵을 사람에게 알리는
    것이 이 함수의 전부다 — 여기서 요청을 대신 처리하지 않는다(호출 경계 §F3).
    재알림 방지는 `payload.escalated_at` 으로 한다 — 큐 파일을 뒤지지 않는다."""
    now = int(time.time())
    cut = now - older_than_min * 60
    con = _con()
    try:
        rows = con.execute(
            "SELECT id, owner, payload, created_at FROM job WHERE kind=? AND status='open'"
            " AND result IS NULL AND created_at<=? ORDER BY created_at", (KIND, cut)).fetchall()
        due = []
        for r in rows:
            try:
                pl = json.loads(r["payload"] or "{}")
            except ValueError:
                pl = {}
            if pl.get("escalated_at"):
                continue
            due.append((r["id"], r["owner"], pl, r["created_at"]))
        alerted = []
        if due and apply:
            # 묶음 1회 (Issue399 규약: 통지 1회·묶음)
            lines = [f"[핀봇 인박스] 매니저 미응답 요청 {len(due)}건 (>{older_than_min}분)"]
            for rid, owner, pl, ts in due:
                age = (now - int(ts or now)) // 60
                lines.append(f"- {owner} ← {pl.get('from') or pl.get('from_session') or '?'}"
                             f" ({age}분): {(pl.get('body') or '')[:60]}  id={rid}")
            _mq_alert("\n".join(lines))
            _st = _state()
            for rid, owner, pl, ts in due:
                pl["escalated_at"] = now
                con.execute("UPDATE job SET payload=? WHERE id=?",
                            (json.dumps(pl, ensure_ascii=False), rid))
                _st.record_event(con, owner, "escalate", f"미응답 {older_than_min}분 초과 → mq alert", rid)   # prj3#Issue575
                alerted.append(rid)
    finally:
        con.close()
    return {"ok": True, "action": "escalate", "due": [d[0] for d in due],
            "alerted": alerted, "applied": apply}


# 주입구 FBOT_MQ_ENQUEUE_SH 는 **테스트 전용** — 스모크가 실큐를 건드리지 않게 스텁을 꽂는다
MQ_ENQUEUE_SH = os.environ.get("FBOT_MQ_ENQUEUE_SH") or os.path.join(
    os.path.expanduser("~"), ".claude", "mcp", "aoa-mq", "aoa-mq-enqueue.sh")


def _mq_alert(message, from_bot="fbot-lead"):
    """fbot-lead.py 의 발신구와 같은 helper 를 **호출만** 한다 — 큐 파일 직접 Write 금지."""
    import subprocess
    if not os.path.exists(MQ_ENQUEUE_SH):
        raise RuntimeError(f"aoa-mq enqueue helper 없음: {MQ_ENQUEUE_SH}")
    p = subprocess.run([MQ_ENQUEUE_SH, "--message", message, "--alert",
                        "--source", from_bot, "--from-bot", from_bot],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"에스컬레이션 enqueue 실패(exit {p.returncode}): "
                           f"{(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="매니저 명령 인박스 (Issue552)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("send", help="매니저에게 요청 적재")
    s1.add_argument("--to", required=True)
    s1.add_argument("--body", required=True)
    s1.add_argument("--from-bot", default="")
    s1.add_argument("--from-session", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    s1.add_argument("--kind", default="ask", help="요청 종류(ask·staffing·role …)")
    s1.add_argument("--prj", type=int, default=None)
    s1.add_argument("--corr-id", default=None)
    s2 = sub.add_parser("inbox", help="인박스 조회")
    s2.add_argument("--bot-id", required=True)
    s2.add_argument("--status", default="open", help="빈 문자열이면 전체")
    s3 = sub.add_parser("reply", help="요청에 응답")
    s3.add_argument("--id", required=True)
    s3.add_argument("--status", required=True, help="accepted|rejected|done")
    s3.add_argument("--body", default="")
    s3.add_argument("--by", default=os.environ.get("FBOT_ID", ""))
    s4 = sub.add_parser("pending", aliases=["list"],
                        help="미처리(open) 요청 — 매니저 1명 또는 세션의 매니저 전원 (별칭 list)")
    s4.add_argument("--bot-id", "--to", "--for", dest="bot_id", default=None)   # 별칭 3종 — 세션이 추측한 형태를 전부 받는다
    s4.add_argument("--session-id", default=None)
    s5 = sub.add_parser("escalate", help="임계 초과 미처리 요청을 aoa-mq alert (tick 경로)")
    s5.add_argument("--older-than-min", type=int,
                    default=int(os.environ.get("FBOT_INBOX_ESCALATE_MIN") or 30))
    s5.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "send":
        out = send(a.to, a.body, a.from_bot, a.from_session, a.kind, a.prj, a.corr_id)
    elif a.cmd == "inbox":
        out = inbox(a.bot_id, a.status)
    elif a.cmd in ("pending", "list"):
        out = pending(a.bot_id, a.session_id)
    elif a.cmd == "escalate":
        out = escalate(a.older_than_min, a.apply)
    else:
        out = reply(a.id, a.status, a.body, a.by)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
