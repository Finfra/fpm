#!/usr/bin/env python3
"""세션 종료 사유 판정 — **단일 지점** (prj3#Issue743).

왜 필요한가 (2026-09-27 21:25 실발생):
    prj1 Issue550 워커(`fbot-lead-pm`)가 `You've hit your session limit` 으로 죽었는데
    퇴근 훅이 종료 사유를 보지 않고 `fbot_session status=done` 을 적었다. 원장상 «정상 퇴근»
    이라 sweep·watch·fpm-do 어느 쪽도 원인을 몰랐고, 사람이 tmux 화면을 보고서야 알았다.

판정 재료는 transcript 의 구조화 신호다(화면 문구가 아니다 — 문구는 바뀐다):
    마지막 assistant 레코드가 `isApiErrorMessage` 이고 `error == "rate_limit"` 이면 쿼터.
    `quotaLimits.resetsAt`(epoch)·`rateLimitType` 이 해소 시각·한도 종류다.

중단(prj3#Issue788_1): 작업 도중 kill(exit 143)된 워커는 마지막 assistant 가
    API 오류가 아니라 normal 로 적혔고, sweep 이 배분을 done 으로 닫았다(거짓 종결). `claude -p` 워커의
    정상 완료는 `end_turn` 으로 끝난다 — 마지막 assistant 가 `stop_reason == tool_use` 이거나 그 뒤에
    `tool_result` 가 남아 있으면 도구 왕복 도중에 끊긴 것이다. 정상 종료 뒤의 사후 user 레코드
    (task-notification·/compact 출력 — 실측)는 중단 신호가 아니므로 `tool_result` 만 본다.

미완 백그라운드(prj3#Issue951): `claude -p` 몸체가 Bash `run_in_background`·Monitor 를 걸고 «끝나면 알림이 온다» 며
    턴을 끝내면 프로세스 종료와 함께 작업이 죽는다(2026-10-05 prj8 R1 `Terminated: 15`). 마지막 assistant 는 정상
    `end_turn` 이라 normal 로 적혔다. 시작 결과는 있는데 종결 알림·TaskStop 이 없는 작업이 남았으면 interrupted 다.
    같은 판정을 SubagentStop 퇴근 보류(fbot-agent-done.sh, prj3#Issue751_6)와 `-p` 몸체 Stop 가드(pm-do-bg-guard.sh)가 쓴다.

반환 end_reason:
    quota        마지막 응답이 쿼터 거부 — 해소 전에는 다시 띄워도 같다
    api_error    다른 API 오류(과부하 등) — 쿼터로 오판하지 않는다
    interrupted  도구 왕복 도중 종료(kill) · 미완 백그라운드를 남긴 종료 — 일을 끝내지 못했다
    normal       마지막 응답이 정상
    unknown    판독 불가(부재·빈 파일·꼬리에 assistant 없음) — **어느 쪽으로도 단정하지 않는다**

소비처는 이 판정을 다시 하지 않는다 — 퇴근 훅이 원장에 적고, 나머지는 원장을 읽는다.

CLI:
    session-end.py <transcript.jsonl>      → 종료 분류 JSON 1줄
    session-end.py stop-guard [--nonexec]           → stdin Stop 훅 JSON. block 판정일 때만 `{"decision":"block",...}` 출력
    session-end.py stop-verdict [--sh] [--nonexec]  → stdin Stop 훅 JSON. 판정 JSON(--sh: 1행 verdict · 2행부터 block 이면
                                                      Stop 훅 출력 JSON 1줄, abandon 이면 인계 표지 — 판정한 자리가 그대로 내보낸다)
    --nonexec: 비실행 관리직 몸체 — 미완 백그라운드를 치명으로 보지 않는다(bg_fatal=False)
"""
import json
import os
import re
import sys

TAIL_BYTES = 512 * 1024   # 마지막 assistant 레코드를 찾기에 충분 — 11k 줄 transcript 도 전체를 읽지 않는다

# 백그라운드 작업 시작·종결 신호 (prj3#Issue751_6 실측 형태 — fbot-agent-done.sh 에서 옮겨 왔다)
#   ⚠️ 시작은 **해당 도구(Bash·Monitor)의 tool_result 첫머리**만 본다 — foreground grep 출력·본문 인용이 같은 문구를
#      담아도 대기 작업으로 세지 않는다(오탐 = 영구 보류·헛 block)
BG_START = {"Bash": re.compile(r"Command running in background with ID: ([A-Za-z0-9_-]+)"),
            "Monitor": re.compile(r"Monitor started \(task ([A-Za-z0-9_-]+)")}
BG_OUTPUT = re.compile(r"Output is being written to: (\S+?\.output)\b")
# 한 알림 블록 안에서만 짝짓는다 — `.*?` 가 다음 알림까지 넘어가면 남의 종결 상태를 빌려 온다
#   종결은 두 형태다(실측 전수): `<status>` 4종 · Monitor 만료·시간 초과 알림 — 후자는 `<status>` 없이
#   `<event>[Monitor expired after Nm …]` / `<event>[Monitor timed out — re-arm if needed.]` 만 온다(prj3#Issue951 리뷰 H1:
#   빠뜨리면 끝난 Monitor 가 영구 미완 — 14일 재생 Monitor 판정 51건 중 ~48건이 이 오탐)
BG_END = re.compile(r"<task-id>([A-Za-z0-9_-]+)</task-id>(?:(?!<task-id>).)*?"
                    r"(?:<status>(?:completed|failed|killed|stopped)</status>|<event>\[Monitor (?:expired|timed out)\b)", re.S)
BG_STOP_TOOLS = ("TaskStop", "KillShell", "KillBash")


def _tail_records(path: str, tail_bytes: int):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if tail_bytes and size > tail_bytes:
            f.seek(size - tail_bytes)
            f.readline()   # 잘린 첫 줄 버림
        data = f.read()
    out = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _text(rec: dict) -> str:
    c = (rec.get("message") or {}).get("content")
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return c if isinstance(c, str) else ""


def _pending_tool(last: dict, after: list):
    """도구 왕복 도중 끊겼으면 그 도구 이름(모르면 "?"), 아니면 None (prj3#Issue788_1)."""
    m = last.get("message") or {}
    content = m.get("content") if isinstance(m.get("content"), list) else []
    names = [x.get("name") or "?" for x in content if isinstance(x, dict) and x.get("type") == "tool_use"]
    result_left = any(
        r.get("type") == "user" and isinstance((r.get("message") or {}).get("content"), list)
        and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in r["message"]["content"])
        for r in after)
    if m.get("stop_reason") == "tool_use" or result_left:
        return ",".join(names) or "?"
    return None


def _block_text(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(b.get("text") or "" for b in c if isinstance(b, dict))
    return ""


def _pending_in(recs: list) -> list:
    """레코드열에서 시작됐으나 종결 알림·TaskStop 이 없는 백그라운드 작업 — 시작 순서대로."""
    uses, started, ended = {}, {}, set()
    for e in recs:
        a = e.get("attachment")
        if isinstance(a, dict):   # 대기 중 도착한 알림은 queued_command attachment 로 온다(prj3#Issue751_6 X3 실측)
            ended.update(BG_END.findall(str(a.get("prompt") or "")))
        m = e.get("message")
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if m.get("role") == "assistant" and isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    uses[b.get("id")] = b.get("name")
                    if b.get("name") in BG_STOP_TOOLS:
                        i = b.get("input") or {}
                        ended.update(str(i[k]) for k in ("task_id", "shell_id", "bash_id") if i.get(k))
        elif m.get("role") == "user":
            for b in ([c] if isinstance(c, str) else (c if isinstance(c, list) else [])):
                if isinstance(b, str):
                    ended.update(BG_END.findall(b))
                elif isinstance(b, dict) and b.get("type") == "text":
                    ended.update(BG_END.findall(b.get("text") or ""))
                elif isinstance(b, dict) and b.get("type") == "tool_result":
                    tool = uses.get(b.get("tool_use_id"))
                    rx = BG_START.get(tool)
                    body = _block_text(b.get("content")).lstrip()
                    hit = rx.match(body) if rx else None
                    if hit and hit.group(1) not in started:
                        out = BG_OUTPUT.search(body)
                        started[hit.group(1)] = {"id": hit.group(1), "tool": tool, "output": out.group(1) if out else None}
    return [t for tid, t in started.items() if tid not in ended]


def pending_background(path: str, tail_bytes: int = TAIL_BYTES) -> list:
    """transcript 에 남은 미완 백그라운드 작업 `[{id, tool, output}]` — **판정 단일 지점** (prj3#Issue751_6·951).

    `tail_bytes=0` 이면 전체를 읽는다(SubagentStop 의 하청 기록). 꼬리 창 밖에서 시작해 끝나지 않은 작업은
    못 본다 — 미완으로 단정하지 않는 쪽(보류·block 을 덜 하는 쪽)으로 틀린다. 읽기 실패는 빈 목록.
    """
    try:
        return _pending_in(_tail_records(path, tail_bytes))
    except (OSError, TypeError):
        return []


def _bg_list(pend: list) -> str:
    return ", ".join(f"{t['id']}({t.get('tool') or '?'}" + (f" · 출력 {t['output']}" if t.get("output") else "") + ")"
                     for t in pend)


def stop_verdict(transcript: str, stop_active: bool, bg_fatal: bool = True) -> dict:
    """`-p` 몸체 Stop 판정 (prj3#Issue951) — ok · block(같은 턴에서 기다리게 되돌림) · abandon(되돌린 뒤에도 끝냄).

    block 은 한 번뿐이다 — `stop_hook_active`(Stop 훅이 이미 턴을 이은 상태)면 다시 막지 않는다(무한 루프 방지).
    그때 남은 작업은 프로세스와 함께 죽으므로 abandon — 호출자가 즉시 미완료로 보고하고 퇴근을 적는다.
    `bg_fatal=False` — 비실행 관리직(총괄·팀장) 몸체. 그 백그라운드는 배분한 워커를 지켜보는 대기 루프라 죽어도
      일이 사라지지 않는다(워커 보고는 인박스로 와서 다시 깨운다 — 실측 3일 22건 전부 이 형태). 항상 ok.
    """
    pend = pending_background(transcript) if transcript and bg_fatal else []
    if not pend:
        return {"verdict": "ok", "pending": []}
    ids = ", ".join(t["id"] for t in pend)
    if stop_active:
        return {"verdict": "abandon", "pending": pend,
                "note": (f"[Stop 가드 — prj3#Issue951] 백그라운드 작업({ids})이 끝나기 전에 -p 몸체가 턴을 끝냄 — "
                         "프로세스 종료와 함께 그 작업은 중단됐다. 그 결과가 필요한 일이었다면 미완료(incomplete)다 — "
                         "아래 몸체의 마지막 말로 판단하고, 재배분 시 foreground 실행 또는 같은 턴 대기를 지시할 것.")}
    return {"verdict": "block", "pending": pend,
            "reason": (f"⏳ 백그라운드 작업이 끝나지 않았다(prj3#Issue951) — 미완: {_bg_list(pend)}. "
                       "이 세션은 `claude -p` 1회 실행이라 **지금 턴을 끝내면 프로세스와 함께 작업이 죽는다**"
                       "(완료 알림을 받을 다음 턴이 없다). 같은 턴에서 끝날 때까지 기다릴 것: foreground Bash"
                       "(timeout 600000)로 `until <종료 조건>; do sleep 20; done` — 명령이 종료 표지(ex) `echo rc=$? >> LOG`)를 "
                       "남기면 그 표지를, 아니면 `sleep 300` 을 반복하며 <task-notification> 도착을 본다. 10분을 넘기면 같은 "
                       "호출을 반복한다. 결과를 확인한 뒤 답을 끝낸다. 일에 필요 없는 서비스·감시 작업(dev 서버·watcher)이면 "
                       "TaskStop 으로 정리한 뒤 정상 보고한다. 결과가 필요한데 기다릴 수 없는 사정이면 TaskStop 후 미완료로 보고한다.")}


def classify(path: str, tail_bytes: int = TAIL_BYTES, bg_fatal: bool = True) -> dict:
    base = {"end_reason": "unknown", "resets_at": None, "limit_type": None, "error": None, "message": None}
    try:
        recs = _tail_records(path, tail_bytes)
    except (OSError, TypeError):
        return base
    li = next((i for i in range(len(recs) - 1, -1, -1) if recs[i].get("type") == "assistant"), None)
    if li is None:
        return base
    last = recs[li]
    if not last.get("isApiErrorMessage"):
        pending = _pending_tool(last, recs[li + 1:])
        if pending is not None:
            return {**base, "end_reason": "interrupted", "message": f"도구 왕복 도중 종료: {pending}"[:200]}
        # prj3#Issue951 — 정상 end_turn 이어도 미완 백그라운드가 남았으면 일을 끝내지 못했다.
        #   bg_fatal=False(비실행 관리직)는 제외 — 워커 대기 루프가 죽은 것이라 세션을 failed 로 세지 않는다(HR fail_pct)
        bg = _pending_in(recs) if bg_fatal else []
        if bg:
            return {**base, "end_reason": "interrupted",
                    "message": f"백그라운드 작업 미완 상태로 종료: {', '.join(t['id'] for t in bg)}"[:200]}
        return {**base, "end_reason": "normal"}
    msg = _text(last)[:200] or None
    if last.get("error") == "rate_limit":
        ql = last.get("quotaLimits") or {}
        return {**base, "end_reason": "quota", "resets_at": ql.get("resetsAt"),
                "limit_type": ql.get("rateLimitType"), "error": "rate_limit", "message": msg}
    return {**base, "end_reason": "api_error", "error": last.get("error"), "message": msg}


def _stop_event() -> dict:
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        ev = {}
    return ev if isinstance(ev, dict) else {}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] in (["stop-guard"], ["stop-verdict"]):
        # Stop 훅 입력 JSON 이 판정 재료의 단일 출처다 — transcript_path·stop_hook_active 를 같은 곳에서 읽는다
        ev = _stop_event()
        v = stop_verdict(ev.get("transcript_path") or "", bool(ev.get("stop_hook_active")),
                         bg_fatal="--nonexec" not in args[1:])
        if args[0] == "stop-guard":
            if v["verdict"] == "block":
                print(json.dumps({"decision": "block", "reason": v["reason"]}, ensure_ascii=False))
        elif "--sh" in args[1:]:
            print(v["verdict"])
            if v["verdict"] == "block":   # 다시 판정하지 않고 이 결과를 내보내게 — 두 번 읽으면 그 사이 알림 도착으로 갈린다
                print(json.dumps({"decision": "block", "reason": v["reason"]}, ensure_ascii=False))
            elif v.get("note"):
                print(v["note"])
        else:
            print(json.dumps(v, ensure_ascii=False))
        sys.exit(0)
    if len(args) != 1:
        print("사용: session-end.py <transcript.jsonl> | stop-guard [--nonexec] | stop-verdict [--sh] [--nonexec]",
              file=sys.stderr)
        sys.exit(2)
    print(json.dumps(classify(args[0]), ensure_ascii=False))
