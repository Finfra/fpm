#!/usr/bin/env python3
"""aoa-mq MCP 서버 — enqueue / list / ack / progress (prj3 감사 F3-2, M2 · 진행 3종 Issue643 · 대기·사람 몫 Issue770)

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
  * **연기(snoozed)는 helper `--reschedule` 에 위임한다** (Issue770 원인 ⑤) — 종전엔 여기서 `now+N일` 을
    직접 계산해 원래 시각이 사라지고 `status=snoozed` 로 남아 **tick 이 다시 보지 않는** 상태가 됐다
    (tick 은 pending 만 due 로 올린다). tick 의 snooze 는 Issue63 에서 이미 위임으로 고쳐져 두 경로가
    갈라져 있었다 — due_ts 를 바꾸는 경로를 하나로 모으면 시각 보존·status=pending 이 공짜로 따라온다.
  * **ack 만 직접 조작한다** — tick 의 finalize 는 대화형 폼 경로라 재사용할 수 없다.
    같은 상태 전이(queue → queue_done, status/acked 기록)를 원자적으로 수행한다.
    ⚠️ **ack 는 handoff 스냅샷을 만들지 않는다** — handoff 는 *"응답은 받았으나 tick 이 실행할 수
    없는 일"* 의 우편함이고, 세션이 직접 ack 한 건은 그 세션이 이미 처리한 것이다. 여기서
    스냅샷을 만들면 적체 감시·stale 승격이 **끝난 일을 다시 일로 띄운다**. 결과 되짚기는
    `queue_done/<id>.json` 의 `result`·`progress` 가 답한다 (Issue643).
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
PROGRESS = os.path.join(HERE, "aoa-mq-progress.sh")   # 진행 3종 기록 단일 지점 (Issue643)

TOOLS = [
    {
        "name": "aoa_mq_enqueue",
        "description": (
            "aoa-mq 큐에 메시지를 등록한다. 예약 리마인드(due)·완료 감시(watch)·즉시 알림(alert) 중 "
            "하나를 반드시 지정한다. 사람만 정할 수 있는 결정(H 등급 — 배포·스토어·공개·비용·계정·법무·브랜드·"
            "파괴·보안·방침)은 message 머리에 '[컨펌] [H:<분류>]' 를 붙이고 due='+0d' 로 등록하면 ACK 전까지 "
            "반복 질의된다. 태그 없는 [컨펌] 은 거부된다(rc 5) — H 가 아니면 mq 에 올리지 말고 결정한다"
            "(C 총괄·L 팀장 전결, ~/.claude/_doc_arch/decision-authority.md). job 을 주면 due 시각에 선언된 스케줄 잡을 실행하고 "
            "결과를 기록한다(message 생략 가능, kind=post 고정)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "메시지 본문 (job 을 주면 생략 가능)"},
                "job": {"type": "string", "description": "지목할 스케줄 잡 이름(schedule.sh 선언). due 와 함께"},
                "job_arg": {"type": "string", "description": "잡의 {arg} 에 넘길 값"},
                "due": {"type": "string", "description": "'+7d' 또는 ISO 날짜. 예약 리마인드"},
                "watch": {"type": "string", "description": "fpm-board topic — 완료 감시"},
                "alert": {"type": "boolean", "description": "true 면 즉시 통지(ACK 전까지 반복)"},
                "kind": {"type": "string", "enum": ["pre", "post"], "description": "기본 pre"},
                "source": {"type": "string", "description": "발신 표기. 생략 시 helper 가 자동 기입"},
                "target": {"type": "string", "description": (
                    "이 항목을 수행할 프로젝트 prj<N>(Issue770). 넛지 범위(그 prj 세션만 본문 주입)·기동 cwd 의 1순위 근거. "
                    "생략하면 message 첫 prjN → source 프로젝트 순으로 판정한다")},
            },
            "required": [],
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
            "snoozed 는 종결이 아니다 — due 를 N일 미루고(원래 시각 보존) pending 으로 되돌린다(tick 과 같은 --reschedule 경로). "
            "조건을 기다리는 것이면 snoozed 대신 aoa_mq_progress 의 wait_for 를 쓴다. 나머지는 queue_done 으로 이동한다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "큐 항목 id (list 로 확인)"},
                "status": {"type": "string", "enum": ["confirmed", "dismissed", "snoozed"]},
                "note": {"type": "string", "description": "처리 사유 1줄(선택). snoozed 면 progress 에 «연기(+Nd): 사유» 로 남는다"},
                "result": {"type": "string", "description": (
                    "무엇을 했는지 결과 요약·산출물 경로(선택이나 confirmed 면 사실상 필수). "
                    "종결 후 되짚을 수 있는 유일한 기록이다 — 비우면 '했다' 만 남고 '무엇을' 이 사라진다"
                )},
                "snooze_days": {"type": "integer", "description": "snoozed 일 때 미룰 일수. 기본 1"},
            },
            "required": ["id", "status"],
        },
    },
    {
        "name": "aoa_mq_progress",
        "description": (
            "진행 중인 큐 항목에 **진행 상황을 남긴다**(Issue643). 사용자가 /mq 에서 [진행] 을 누른 뒤 "
            "무슨 일이 일어나는지 볼 수 있는 유일한 경로다. progress 는 갱신형 1줄 메모이고, "
            "**착수했으나 할 수 없는 경우의 사유도 여기 적는다** — 다음 사람이 같은 조사를 반복하지 않는다. "
            "claimed_by 는 집은 주체 표식으로 잠금이 아니다(다른 주체가 적혀 있어도 착수를 막지 않는다). "
            "Issue770: 사람의 결정·행동이 필요하면 산문으로 적고 턴을 끝내지 말고 needs_human 에 올린다"
            "(decide:결정 / act:사람 행동). 외부 조건을 기다려야 하면 wait_for(+recheck)로 ⏳ 대기 전환한다 — "
            "대기 항목은 적체 통지·자동 기동·세션 넛지에서 빠지고 recheck 시각에 다시 묻는다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "큐 항목 id"},
                "progress": {"type": "string", "description": "진행 메모 1줄(갱신형). 진행 불가 사유도 여기"},
                "result": {"type": "string", "description": "결과 요약·산출물 경로. 종결 전에 남길 때만 — 종결과 함께면 aoa_mq_ack 의 result 를 쓴다"},
                "claimed_by": {"type": "string", "description": "집은 주체(세션 sid·bot_id). 보통 세션 넛지가 자동 기록하므로 인계할 때만 지정"},
                "force": {"type": "boolean", "description": "claimed_by 인계 — 이미 다른 주체가 적혀 있을 때만 필요"},
                "wait_for": {"type": "string", "description": (
                    "⏳ 대기 전환 — 풀려야 할 조건 1줄. 선행 mq 항목이면 'mq:<id>'(그 항목이 종결되면 자동 재개)")},
                "recheck": {"type": "string", "description": "wait_for 의 재확인 시각: +Nd · +Nh · YYYY-MM-DD · ISO. 생략 시 3일 뒤"},
                "resume": {"type": "boolean", "description": "대기 해제 — 대기 전 상태로 되돌린다"},
                "needs_human": {"type": "string", "description": "🙋 사람 몫 1건 추가 — 'decide:<결정>' 또는 'act:<사람의 물리 행동>'"},
                "needs_human_done": {"type": "string", "description": "사람 몫 1건 해소(항목 문자열 그대로) — 이력에 남는다"},
            },
            "required": ["id"],
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
    # prj3#Issue691: «message 또는 job» 하나 이상 — 검증은 helper 가 한다(한 곳)
    if not a.get("message") and not a.get("job"):
        return "❌ message 또는 job 중 하나는 필수다"
    cmd = ["bash", ENQUEUE]
    if a.get("message"):
        cmd += ["--message", a["message"]]
    if a.get("job"):
        cmd += ["--job", a["job"]]
        if a.get("job_arg"):
            cmd += ["--arg", a["job_arg"]]
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
    if a.get("target"):                                  # Issue770 — 검증(형식·매핑)은 helper 가 한다
        cmd += ["--target", a["target"]]
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
        # 진행 3종 (Issue643) — **있는 항목만**. 부재가 정상이므로 "-" 로 채우지 않는다
        # (마이그레이션 없이 기존 항목이 그대로 렌더돼야 한다).
        if i.get("job"):                                  # prj3#Issue691 — 잡 지목 예약
            lines.append(f"    · 잡: {i['job']}" + (f" ⟨{i['job_arg']}⟩" if i.get("job_arg") else ""))
        for label, key in (("집은 주체", "claimed_by"), ("진행", "progress"), ("결과", "result")):
            v = i.get(key)
            if v:
                lines.append(f"    · {label}: {str(v)[:160]}")
        # Issue770 — 대상·승인·대기·사람 몫. 역시 **있는 항목만**
        if i.get("target"):
            lines.append(f"    · 대상: {i['target']}")
        if i.get("approved_ts"):
            lines.append(f"    · 착수 승인: {i.get('approved_by', '-')} {str(i['approved_ts'])[:16]}")
        if i.get("wait_for"):
            lines.append(f"    · ⏳ 대기: {str(i['wait_for'])[:160]} (재확인 {str(i.get('recheck_ts') or '-')[:16]})")
        if i.get("needs_human"):
            lines.append("    · 🙋 사람 몫: " + " / ".join(str(x) for x in i["needs_human"])[:300])
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
    qid_full = target.get("id") or fn[:-5]

    if status == "snoozed":
        # Issue770 원인 ⑤ — due_ts 를 바꾸는 경로는 helper --reschedule **하나**다(tick snooze 와 같은 결과:
        #   status=pending · 원래 시각 보존 · tick 과 같은 락). 여기서 계산하면 두 경로가 다시 갈라진다.
        if not os.path.isfile(ENQUEUE):
            return f"❌ helper 없음: {ENQUEUE}"
        days = int(a.get("snooze_days") or 1)
        r = subprocess.run(["bash", ENQUEUE, "--reschedule", qid_full, "--due", f"+{days}d"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return f"❌ 연기 실패 (rc={r.returncode})\n{r.stderr.strip() or r.stdout.strip()}"
        # 사유·결과는 버리지 않는다 — reschedule 은 due_ts 만 바꾸므로 진행 3종 단일 경로(helper)로 남긴다
        extra = []
        for sub, val in (("note", f"연기(+{days}d): {a['note']}" if a.get("note") else None),
                         ("result", a.get("result"))):
            if not val:
                continue
            pr = subprocess.run(["bash", PROGRESS, sub, qid_full, "--text", str(val)],
                                capture_output=True, text=True)
            if pr.returncode != 0:
                extra.append(f"⚠️ {sub} 기록 실패: {pr.stderr.strip() or pr.stdout.strip()}")
        new_due = "?"
        try:
            with open(src, encoding="utf-8") as f:
                new_due = str(json.load(f).get("due_ts") or "?")
        except Exception:
            pass
        return "\n".join([f"✅ {qid} → pending (due {new_due[:16]} 로 연기 · 원래 시각 보존)"] + extra)

    target["status"] = status
    target["acked"] = True
    target["ack_ts"] = _now()
    if a.get("note"):
        target["ack_note"] = a["note"]
    # 결과 기록 (Issue643) — helper 를 거치지 않고 **여기서** 쓴다.
    #   ack 는 파일 전체를 한 번에 다시 쓰는 원자 연산이라, result 를 helper 로 따로 쓰면
    #   두 번의 비원자 쓰기 사이에 tick 이 끼어들 수 있다. 같은 트랜잭션에 담는 쪽이 안전하다.
    #   (종결과 무관하게 결과만 남길 때는 aoa_mq_progress → aoa-mq-progress.sh result 가 단일 지점)
    if a.get("result"):
        # 상한 400 **문자** + 절단 표식 — helper 의 oneline() 과 셈 단위·표식을 맞춘다
        # (prj3#Issue651: 두 경로가 «같은 400» 을 다르게 세던 비대칭이 버그의 뿌리였다).
        _r = " ".join(str(a["result"]).split())
        target["result"] = (_r[:399] + "\u2026") if len(_r) > 400 else _r
        target["result_ts"] = _now()

    os.makedirs(QDONE, exist_ok=True)
    dst = os.path.join(QDONE, fn)

    tmp = src + ".tmp"       # 원자적 쓰기 — 반쯤 쓰인 상태를 tick 이 읽으면 안 된다
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(target, f, ensure_ascii=False, indent=2)
    os.replace(tmp, src)
    if dst != src:
        shutil.move(src, dst)
    return f"✅ {qid} → {status}"


def t_progress(a):
    # helper 재사용 — 원자적 쓰기·락·필드 규약이 거기 있다. enqueue 와 같은 이유로
    # 여기서 재구현하면 두 경로가 갈라진다(2원 구조 금지).
    if not os.path.isfile(PROGRESS):
        return f"❌ helper 없음: {PROGRESS}"
    qid = a.get("id")
    if not qid:
        return "❌ id 필수"
    keys = ("progress", "result", "claimed_by", "wait_for", "resume", "needs_human", "needs_human_done")
    if not any(a.get(k) for k in keys):
        # 조회는 aoa_mq_list 가 한다 — 여기서 show 로 갈라지면 "어느 쪽으로 보나" 가 또 생긴다
        return "❌ " + "·".join(keys) + " 중 하나는 필수다(조회는 aoa_mq_list)"
    out = []
    # 순서: 표식·메모·결과 → 사람 몫 → 대기 전환/해제(상태를 바꾸는 것은 마지막)
    steps = (
        ("claim", a.get("claimed_by"), lambda v: ["--by", str(v)] + (["--force"] if a.get("force") else [])),
        ("note", a.get("progress"), lambda v: ["--text", str(v)]),
        ("result", a.get("result"), lambda v: ["--text", str(v)]),
        ("need", a.get("needs_human"), lambda v: ["--text", str(v)]),
        ("need-done", a.get("needs_human_done"), lambda v: ["--text", str(v)]),
        ("resume", a.get("resume"), lambda v: ["--via", "mcp"]),
        ("wait", a.get("wait_for"), lambda v: ["--for", str(v)] + (["--recheck", str(a["recheck"])] if a.get("recheck") else [])),
    )
    for sub, val, argf in steps:
        if not val:
            continue
        r = subprocess.run(["bash", PROGRESS, sub, qid] + argf(val),
                           capture_output=True, text=True)
        if r.returncode != 0:
            # fail-loud — 조용히 삼키면 "기록했다고 믿는데 비어 있는" 상태가 된다
            return f"❌ {sub} 실패 (rc={r.returncode})\n{r.stderr.strip() or r.stdout.strip()}"
        out.append(r.stdout.strip())
    return "\n".join(out) or "변경 없음"


HANDLERS = {"aoa_mq_enqueue": t_enqueue, "aoa_mq_list": t_list, "aoa_mq_ack": t_ack,
            "aoa_mq_progress": t_progress}


SESSION_TOUCH = os.path.join(MQ, ".last-session-touch")
DISCOVER_TTL_MS = 60000  # prj1#Issue484 — server/discover·tools/list 캐시 수명. prj20 cd8972f 와 동일 값


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
        # prj1#Issue600 — 2026-07-28 은 tools/list 를 포함한 모든 result 에 resultType 을 요구한다.
        # 메서드별로 넣으면 한 곳이 빠진다(Issue484 가 tools/call 에만 넣어 «tools fetch failed») → 판정 단일 지점.
        # 이 서버는 부분 응답을 만들지 않으므로 항상 complete.
        if isinstance(result, dict):
            result.setdefault("resultType", "complete")
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
        # prj1#Issue484 — server/discover 를 함께 마커로 삼는다. 신 클라이언트는 initialize 를 아예 보내지
        # 않으므로 이 항목이 빠지면 세션 개시 시점의 마커가 찍히지 않고, MCP 도구를 한 번도 부르지
        # 않는 세션은 tick 이 죽은 것으로 오판해 통지를 과다 발송한다.
        if method in ("server/discover", "initialize", "tools/call"):
            touch_session()                             # F3-3 세션 활성 마커
        if method == "server/discover":
            # MCP 2026-07-28 무상태 코어(SEP-2575). 이 서버의 모듈 전역은 TOOLS·HANDLERS·상수뿐이라
            # 요청 간 세션 변수가 없다 — 이 분기는 이미 무상태인 사실을 프로토콜 표면에 선언하는 것이다.
            reply(rid, {"ttlMs": DISCOVER_TTL_MS,
                        "cacheScope": "private",
                        "supportedVersions": ["2026-07-28"],
                        "capabilities": {"tools": {"listChanged": False}}})
        elif method == "initialize":
            # 삭제하지 않는다 — server/discover 를 모르는 구 클라이언트의 유일한 진입점이다.
            reply(rid, {"protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "aoa-mq", "version": "1.0.0"}})
        elif method == "tools/list":
            reply(rid, {"ttlMs": DISCOVER_TTL_MS, "cacheScope": "private", "tools": TOOLS})  # prj1#Issue484 캐시 힌트(SEP-2549)
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
            # prj1#Issue484 — resultType 은 2026-07-28 필수 필드. 부분 응답을 만들지 않으므로 항상 complete.
            reply(rid, {"content": [{"type": "text", "text": text}], "resultType": "complete"})
        elif rid is not None:
            reply(rid, error={"code": -32601, "message": f"unknown method: {method}"})


if __name__ == "__main__":
    main()
