#!/usr/bin/env python3
"""aoa-mq MCP 서버 — enqueue / list / ack (prj3 감사 F3-2, M2)

⚠️ 글로벌 SCAR 변경 가드 (prj3 Issue46): 본 서버는 여러 프로젝트가 공유한다.
  설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md
  절차: ~/.claude/rules/global-scar-change-rules.md

왜 (감사 v1.0.3 문제 2·3·9 삼중 공용):
  종전 큐 접근은 **폴링**이었다 — tick 이 1시간 게이트로 돌며 사람이 대시보드를 열어야
  움직였다. MCP 로 올리면 Claude 가 **tool call 로 직접** 큐를 읽고 쓴다.
  ◆P3 가 요구한 "누가 큐를 확인시키나" 는 F3-1(session-inbox 디스패처 편입)이
  이미 풀었으므로, 본 승격은 그 위에 얹힌다.

설계 원칙
  * **의존성 0** — MCP 는 JSON-RPC 2.0 over stdio 다. SDK 없이 표준 라이브러리로 구현한다.
    prj5 에 node_modules·venv 를 새로 들이지 않는다.
  * **enqueue 는 기존 helper 를 호출한다** — 원자적 쓰기(.tmp→mv)·id 발급·스키마가
    aoa-mq-enqueue.sh 에 있다. 여기서 재구현하면 두 경로가 갈라진다(2원 구조 금지).
  * **ack 만 직접 조작한다** — tick 의 finalize 는 대화형 폼 경로라 재사용할 수 없다.
    같은 상태 전이(queue → queue_done, status/acked 기록)를 원자적으로 수행한다.
"""

import json
import os
import subprocess
import sys
import datetime
import shutil

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))

# 경로 계약 (prj3#Issue450) — prj5(___common) 를 전제하지 않는다.
#   ① `AOA_MQ_DIR` env 최우선 = **정식 설정**. 설치 환경이 데이터 위치를 지정한다
#   ② env 부재 시 제품 중립 기본 `~/.claude/data/aoa/mq` — Claude Code 가 도는 모든 머신에 있다
# helper 는 이 서버와 **같은 폴더에 배포**된다(prj3 라이브·prj1 번들 양쪽 동일 배치).
#   과거 `___common/.claude/agents/` 절대경로를 물고 있었고 그 실체가 사라져 enqueue 도구가
#   상시 "helper 없음" 을 반환하고 있었다 — `__file__` 기준이면 repo 위치와 무관하게 맞는다.
MQ = os.environ.get("AOA_MQ_DIR") or os.path.join(HOME, ".claude", "data", "aoa", "mq")
QUEUE = os.path.join(MQ, "queue")
QDONE = os.path.join(MQ, "queue_done")
ENQUEUE = os.path.join(HERE, "aoa-mq-enqueue.sh")

TOOLS = [
    {
        "name": "aoa_mq_enqueue",
        "description": (
            "aoa-mq 큐에 메시지를 등록한다. 예약 리마인드(due)·완료 감시(watch)·즉시 알림(alert) 중 "
            "하나를 반드시 지정한다. 사용자 컨펌이 필요한 결정은 message 앞에 '[컨펌]' 을 붙이고 due='+0d' 로 "
            "등록하면 ACK 전까지 반복 질의된다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "메시지 본문"},
                "due": {"type": "string", "description": "'+7d' 또는 ISO 날짜. 예약 리마인드"},
                "watch": {"type": "string", "description": "fpm-board topic — 완료 감시"},
                "alert": {"type": "boolean", "description": "true 면 즉시 통지(ACK 전까지 반복)"},
                "kind": {"type": "string", "enum": ["pre", "post"], "description": "기본 pre"},
                "source": {"type": "string", "description": "발신 표기. 생략 시 helper 가 자동 기입"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "aoa_mq_list",
        "description": "미종결 큐를 조회한다. 폴링 대신 이걸 쓴다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "상태 필터(pending·done_unacked 등). 생략 시 전체"},
                "limit": {"type": "integer", "description": "최대 건수. 기본 20"},
            },
        },
    },
    {
        "name": "aoa_mq_ack",
        "description": (
            "큐 항목을 종결한다(ACK). confirmed=승인·처리됨, dismissed=폐기, snoozed=연기. "
            "snoozed 는 due 를 미루고 큐에 남기며, 나머지는 queue_done 으로 이동한다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "큐 항목 id (list 로 확인)"},
                "status": {"type": "string", "enum": ["confirmed", "dismissed", "snoozed"]},
                "note": {"type": "string", "description": "처리 사유 1줄(선택)"},
                "snooze_days": {"type": "integer", "description": "snoozed 일 때 미룰 일수. 기본 1"},
            },
            "required": ["id", "status"],
        },
    },
]


def _now():
    return datetime.datetime.now().astimezone().isoformat()


def _read_queue():
    out = []
    for d in (QUEUE,):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json") or fn.endswith(".tmp"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    item = json.load(f)
                item["_file"] = fn
                out.append(item)
            except Exception:
                continue
    return out


def t_enqueue(a):
    # helper 재사용 — 원자적 쓰기·id 발급·스키마가 거기 있다(여기서 재구현하면 갈라진다)
    if not os.path.isfile(ENQUEUE):
        return f"❌ helper 없음: {ENQUEUE}"
    cmd = ["bash", ENQUEUE, "--message", a["message"]]
    if a.get("due"):
        cmd += ["--due", a["due"]]
    elif a.get("watch"):
        cmd += ["--watch", a["watch"]]
    elif a.get("alert"):
        cmd += ["--alert"]
    else:
        return "❌ due·watch·alert 중 하나는 필수다(전부 없으면 언제 발화할지 알 수 없다)"
    if a.get("kind"):
        cmd += ["--kind", a["kind"]]
    if a.get("source"):
        cmd += ["--source", a["source"]]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return f"❌ enqueue 실패 (rc={r.returncode})\n{r.stderr.strip() or r.stdout.strip()}"
    return r.stdout.strip() or "enqueued"


def t_list(a):
    items = _read_queue()
    st = a.get("status")
    if st:
        items = [i for i in items if i.get("status") == st]
    items = items[: int(a.get("limit") or 20)]
    if not items:
        return "미종결 큐 0건"
    lines = [f"미종결 {len(items)}건", ""]
    for i in items:
        msg = (i.get("message") or "").replace("\n", " ")
        # 봇 귀속(from_bot/to_bot) 있으면 함께 표시 — 있는 항목만 (prj3#Issue436_3 s4)
        bot = ""
        if i.get("from_bot") or i.get("to_bot"):
            bot = f" bot={i.get('from_bot','-')}→{i.get('to_bot','-')}"
        lines.append(
            f"* `{i.get('id','?')}` [{i.get('status','?')}/{i.get('type','?')}] "
            f"due={(i.get('due_ts') or '-')[:16]} ask={i.get('ask_count',0)}{bot}\n"
            f"    {msg[:160]}"
        )
    return "\n".join(lines)


def t_ack(a):
    qid, status = a["id"], a["status"]
    target = None
    for i in _read_queue():
        if i.get("id") == qid or i.get("_file", "").startswith(qid):
            target = i
            break
    if not target:
        return f"❌ 큐에 없음: {qid} (이미 종결됐거나 id 오타)"

    fn = target.pop("_file")
    src = os.path.join(QUEUE, fn)
    target["status"] = status
    target["acked"] = status != "snoozed"
    target["ack_ts"] = _now()
    if a.get("note"):
        target["ack_note"] = a["note"]

    if status == "snoozed":
        days = int(a.get("snooze_days") or 1)
        target["due_ts"] = (datetime.datetime.now().astimezone()
                            + datetime.timedelta(days=days)).isoformat()
        dst = src            # 큐에 남긴다 — 연기이지 종결이 아니다
    else:
        os.makedirs(QDONE, exist_ok=True)
        dst = os.path.join(QDONE, fn)

    tmp = src + ".tmp"       # 원자적 쓰기 — 반쯤 쓰인 상태를 tick 이 읽으면 안 된다
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(target, f, ensure_ascii=False, indent=2)
    os.replace(tmp, src)
    if dst != src:
        shutil.move(src, dst)
    return f"✅ {qid} → {status}" + (f" (due {target['due_ts'][:16]} 로 연기)" if status == "snoozed" else "")


HANDLERS = {"aoa_mq_enqueue": t_enqueue, "aoa_mq_list": t_list, "aoa_mq_ack": t_ack}


SESSION_TOUCH = os.path.join(MQ, ".last-session-touch")


def touch_session():
    """세션 활성 마커 갱신 (F3-3 — prj5 Issue37).

    tick 은 이 파일의 mtime 으로 "지금 세션이 살아 있는가"를 판정해 통지 계층
    (폼 렌더·누적 경고)을 건너뛴다. MCP 서버는 Claude Code 세션당 stdio 로 뜨므로
    initialize·tools/call 이 곧 세션 활동의 지표다 — 타 repo 신호에 의존하지 않고
    prj5 안에서 판정이 완결된다.

    fail-soft: 마커를 못 써도 큐 동작은 계속돼야 한다. 실패하면 tick 이 통지를
    건너뛰지 않을 뿐이라 안전한 쪽(더 많이 알림)으로 기운다.
    """
    try:
        with open(SESSION_TOUCH, "a"):
            os.utime(SESSION_TOUCH, None)
    except Exception:
        pass


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
        if method in ("initialize", "tools/call"):
            touch_session()                             # F3-3 세션 활성 마커
        if method == "initialize":
            reply(rid, {"protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "aoa-mq", "version": "1.0.0"}})
        elif method == "tools/list":
            reply(rid, {"tools": TOOLS})
        elif method == "tools/call":
            p = req.get("params") or {}
            fn = HANDLERS.get(p.get("name"))
            if not fn:
                reply(rid, error={"code": -32601, "message": f"unknown tool: {p.get('name')}"})
                continue
            try:
                text = fn(p.get("arguments") or {})
            except Exception as e:                      # fail-soft — 서버가 죽으면 세션이 끊긴다
                text = f"❌ 실행 오류: {e}"
            reply(rid, {"content": [{"type": "text", "text": text}]})
        elif rid is not None:
            reply(rid, error={"code": -32601, "message": f"unknown method: {method}"})


if __name__ == "__main__":
    main()
