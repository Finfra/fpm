#!/usr/bin/env python3
"""fbot-outbox.py — 머신 간 봇 메시지 (prj3#Issue538 s6)

머신이 갈리면 `registry.db` 도 갈린다. 상대 머신의 봇은 이쪽 대장에 없으므로
**요청을 그대로 원장에 넣을 수 없다** — `job.owner_id` 가 `bot(bot_id)` FK 이고
트리거가 `kind LIKE 'fbot%'` 인 레코드의 owner 를 거기 밀어넣기 때문이다.

🔴 **총괄이 대리 접수한다.** 원격 요청의 `owner` 를 **수신 머신 총괄의 bot_id** 로
재귀속하고 원 발신자는 `payload.origin` 에 보존한다. FK·트리거를 한 줄도 고치지
않는다. ❌ `kind` 를 `fbot%` 밖으로 지어 회피하는 길은 막았다 — 그러면 감사기와
조직도 집계가 이 요청들을 못 본다(우회가 곧 관측 구멍).

전달은 **양방향 pull** 이다. 각 머신이 outbox 에 쌓고 상대가 tick 에서 당긴다 —
미는 쪽에 수집자의 경로·권한 지식을 요구하면 결합이 커진다(Issue468 계승).

실측(2026-09-05): tick 30분 · ssh 왕복 194ms → 종단 지연 평균 ≈15분. 지배 항은
네트워크가 아니라 **주기**다(약 4,600배 차). 비동기 요청 성격상 수용 가능.
"""
import argparse
import json
import os
import socket
import sqlite3
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTBOX = os.environ.get("FBOT_OUTBOX_DIR") or os.path.join(ROOT, "data", "fbot", "outbox")
INBOX_DONE = os.path.join(OUTBOX, ".consumed")
REGISTRY_DB = os.environ.get("FBOT_REGISTRY_DB") or os.path.join(
    # prj3#Issue559 — fbot-state.py 와 같은 해석(AOA_MEMORY_DIR → ~/.claude/data/aoa). 개인 경로 하드코딩은
    #   번들로 나가는 순간 타 머신에서 "DB 없음" 이 된다.
    os.environ.get("AOA_MEMORY_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa"),
    "registry.db")
# 대리 접수자 — 총괄핀봇. 머신 경계를 넘는 유일한 배관 보유자다(§보고 폴백 사다리).
PROXY_ROLE = "chief"


def this_machine():
    return os.environ.get("FBOT_MACHINE") or socket.gethostname().split(".")[0]


def put(to_machine, kind, payload, from_bot=""):
    """outbox 에 적재. 상대 머신이 tick 에서 당겨간다."""
    d = os.path.join(OUTBOX, to_machine)
    os.makedirs(d, exist_ok=True)
    mid = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    msg = {"id": mid, "from_machine": this_machine(), "from_bot": from_bot,
           "to_machine": to_machine, "kind": kind, "payload": payload,
           "created_at": int(time.time())}
    path = os.path.join(d, f"{mid}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(msg, f, ensure_ascii=False, indent=2)
    return {"ok": True, "action": "put", "id": mid, "path": path}


def _proxy_bot(con):
    """대리 접수자 조회 — 이 머신의 총괄핀봇. 없으면 접수 불가(fail-loud)."""
    row = con.execute(
        "SELECT bot_id FROM bot WHERE role=? AND career IN ('probation','active')"
        " ORDER BY created_at LIMIT 1", (PROXY_ROLE,)).fetchone()
    return row[0] if row else None


def accept(path, apply=False):
    """원격 메시지 1건을 원장에 접수한다."""
    with open(path, encoding="utf-8") as f:
        msg = json.load(f)
    if not str(msg.get("kind") or "").startswith("fbot"):
        return {"ok": False, "error": f"봇 축이 아닌 kind: {msg.get('kind')}"}
    con = sqlite3.connect(REGISTRY_DB)
    try:
        proxy = _proxy_bot(con)
        if not proxy:
            return {"ok": False, "error": "대리 접수자(총괄핀봇) 부재 — 접수 불가"}
        jid = f"fbotmsg-{msg['id']}"
        if con.execute("SELECT 1 FROM job WHERE id=?", (jid,)).fetchone():
            return {"ok": True, "action": "accept", "id": jid, "skipped": "이미 접수(멱등)"}
        # 원 발신자는 payload 에 보존한다 — owner 를 바꾸는 것은 **접수 창구**를
        #   기록하는 것이지 발신자를 지우는 것이 아니다.
        pl = dict(msg.get("payload") or {})
        pl["origin"] = {"machine": msg.get("from_machine"), "bot": msg.get("from_bot"),
                        "msg_id": msg.get("id")}
        if not apply:
            return {"ok": True, "action": "accept", "mode": "dry-run", "job_id": jid,
                    "proxy": proxy, "kind": msg["kind"], "next": "집행은 --apply"}
        con.execute(
            "INSERT INTO job(id, store, kind, status, payload, attempts, owner, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (jid, "fbot", msg["kind"], "open", json.dumps(pl, ensure_ascii=False),
             0, proxy, int(time.time())))
        con.commit()
        return {"ok": True, "action": "accept", "mode": "집행", "job_id": jid,
                "proxy": proxy, "kind": msg["kind"]}
    finally:
        con.close()


def consume(apply=False):
    """이 머신 앞으로 온 메시지를 전부 접수한다. tick 이 부른다."""
    me = this_machine()
    d = os.path.join(OUTBOX, me)
    if not os.path.isdir(d):
        return {"ok": True, "action": "consume", "machine": me, "accepted": 0,
                "reason": "수신함 없음 — 완전 no-op"}
    os.makedirs(INBOX_DONE, exist_ok=True)
    done, errs = [], []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        p = os.path.join(d, f)
        r = accept(p, apply)
        if r.get("ok"):
            done.append(r.get("job_id"))
            if apply:
                # 소비 표시는 **이동**이다 — 지우면 "받은 적 있나" 를 물을 수 없다
                os.replace(p, os.path.join(INBOX_DONE, f))
        else:
            errs.append({"file": f, "error": r.get("error")})
    return {"ok": not errs, "action": "consume", "machine": me,
            "mode": "집행" if apply else "dry-run",
            "accepted": len(done), "job_ids": done, "errors": errs}


def main(argv=None):
    ap = argparse.ArgumentParser(description="머신 간 봇 메시지 (Issue538 s6)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("put", help="outbox 적재")
    p1.add_argument("--to-machine", required=True)
    p1.add_argument("--kind", required=True)
    p1.add_argument("--payload", default="{}")
    p1.add_argument("--from-bot", default="")
    p2 = sub.add_parser("consume", help="수신 메시지 접수 (tick 이 호출)")
    p2.add_argument("--apply", action="store_true")
    sub.add_parser("status", help="수신함 현황")
    a = ap.parse_args(argv)

    if a.cmd == "put":
        out = put(a.to_machine, a.kind, json.loads(a.payload), a.from_bot)
    elif a.cmd == "consume":
        out = consume(a.apply)
    else:
        me = this_machine()
        d = os.path.join(OUTBOX, me)
        pend = sorted(f for f in os.listdir(d)) if os.path.isdir(d) else []
        out = {"ok": True, "action": "status", "machine": me, "pending": len(pend),
               "files": pend[:10]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
