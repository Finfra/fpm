#!/usr/bin/env python3
"""MCP 2026-07-28 무상태 스펙 회귀 테스트 (Issue484).

두 서버는 원래부터 요청 간 세션 변수가 없다 — 이 테스트가 지키는 것은 "무상태로 만든 것"이
아니라 **무상태라는 사실이 프로토콜 표면에 계속 선언되어 있는가**다.

🔴 핵심은 마지막 절이다. aoa-mq 의 `initialize` 는 순수 핸드셰이크가 아니라 세션 활성 마커를
갱신한다(F3-3, prj5#Issue37). 신 클라이언트는 `initialize` 를 보내지 않으므로, `server/discover`
가 마커를 찍지 않으면 tick 이 살아 있는 세션을 죽은 것으로 오판해 통지를 과다 발송한다.
증상이 "알림이 좀 많아졌다" 로만 나타나 사람이 원인에 도달하기 어렵다 — 그래서 테스트로 박는다.

실행: python3 mcp/tests/test_stateless_spec.py
      python3 mcp/tests/test_stateless_spec.py --mcp-dir ~/.claude/mcp   # 배포 사본 검사
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = []


def rpc(server, requests, env):
    """서버에 요청 줄들을 밀어넣고 응답 줄만 파싱해 돌려준다(stdio JSON-RPC)."""
    p = subprocess.run(
        [sys.executable, server],
        input="\n".join(json.dumps(r) for r in requests) + "\n",
        capture_output=True, text=True, env=env, timeout=30,
    )
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]


def check(cond, label):
    print(("  ✅ " if cond else "  ❌ ") + label)
    if not cond:
        FAIL.append(label)


def suite(name, server, env, tool):
    print(f"\n=== {name} ===")

    # ① 신 클라이언트 — initialize 없이 server/discover → tools/list 만으로 성립해야 한다
    res = rpc(server, [
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ], env)
    check(len(res) == 2, f"신 경로 응답 2건 (실제 {len(res)})")
    if len(res) != 2:
        return
    d, t = res[0].get("result", {}), res[1].get("result", {})
    check(d.get("supportedVersions") == ["2026-07-28"], f"discover supportedVersions={d.get('supportedVersions')}")
    check(d.get("cacheScope") == "private", f"discover cacheScope={d.get('cacheScope')}")
    check(isinstance(d.get("ttlMs"), int) and d["ttlMs"] > 0, f"discover ttlMs={d.get('ttlMs')}")
    check(d.get("capabilities", {}).get("tools", {}).get("listChanged") is False,
          "discover capabilities.tools.listChanged=false")
    check(bool(t.get("tools")), f"initialize 없이 도구 {len(t.get('tools') or [])}종 수신")
    check(t.get("ttlMs") == d.get("ttlMs") and t.get("cacheScope") == "private",
          "tools/list 캐시 힌트 동반 (SEP-2549)")

    # ② 구 클라이언트 — initialize 분기를 지우면 여기서 깨진다
    res = rpc(server, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},   # id 없음 = 통지, 응답하면 안 된다
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ], env)
    check(len(res) == 2, f"구 경로 응답 2건 — 통지에 응답하지 않음 (실제 {len(res)})")
    if len(res) == 2:
        check(res[0].get("result", {}).get("protocolVersion") == "2024-11-05", "initialize 하위호환 유지")
        check(bool(res[1].get("result", {}).get("tools")), "구 경로 tools/list 정상")

    # ③ 도구 호출 — resultType 추가가 기존 응답을 깨지 않았는가
    res = rpc(server, [
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": {}}},
    ], env)
    call = res[-1].get("result", {}) if res else {}
    check(call.get("resultType") == "complete", f"{tool} resultType={call.get('resultType')}")
    text = (call.get("content") or [{}])[0].get("text", "")
    check(bool(text) and not text.startswith("❌"),
          f"{tool} 응답 정상: {text.splitlines()[0][:60] if text else '(빈 응답)'}")


def main():
    # 배포 사본(~/.claude/mcp 등)도 같은 계약을 지키는지 검사할 수 있게 대상 폴더를 인자로 연다.
    mcp = os.path.dirname(HERE)
    if "--mcp-dir" in sys.argv:
        mcp = os.path.expanduser(sys.argv[sys.argv.index("--mcp-dir") + 1])
    print(f"대상: {mcp}")
    memory_server = os.path.join(mcp, "aoa-memory", "server.py")
    mq_server = os.path.join(mcp, "aoa-mq", "server.py")
    for p in (memory_server, mq_server):
        if not os.path.isfile(p):
            print(f"❌ 서버 없음: {p}")
            return 1

    tmp = tempfile.mkdtemp(prefix="mcp-stateless-")   # 실제 큐·DB 를 건드리지 않는다
    mem_dir = os.path.join(tmp, "aoa")
    mq_dir = os.path.join(tmp, "mq")
    os.makedirs(mem_dir, exist_ok=True)
    os.makedirs(os.path.join(mq_dir, "queue"), exist_ok=True)
    env_mem = dict(os.environ, AOA_MEMORY_DIR=mem_dir)
    env_mq = dict(os.environ, AOA_MQ_DIR=mq_dir)

    subprocess.run([sys.executable, os.path.join(mcp, "aoa-memory", "store.py")],
                   capture_output=True, text=True, env=env_mem, timeout=60)

    suite("aoa-memory", memory_server, env_mem, "registry_list")
    suite("aoa-mq", mq_server, env_mq, "aoa_mq_list")

    # ④ 회귀 방지 본체 — server/discover 가 세션 활성 마커를 갱신하는가 (F3-3)
    print("\n=== aoa-mq 세션 활성 마커 (F3-3 회귀 방지) ===")
    marker = os.path.join(mq_dir, ".last-session-touch")
    if os.path.exists(marker):
        os.remove(marker)                       # 앞 절이 이미 찍었다 — 이 절만의 사전 상태를 만든다
    check(not os.path.exists(marker), "사전 상태: 마커 없음")

    rpc(mq_server, [{"jsonrpc": "2.0", "id": 1, "method": "server/discover"}], env_mq)
    check(os.path.exists(marker), "server/discover 단독 수신으로 마커 생성")
    if os.path.exists(marker):
        t0 = os.path.getmtime(marker)
        time.sleep(1.1)                         # mtime 해상도에 여유를 둔다
        rpc(mq_server, [{"jsonrpc": "2.0", "id": 1, "method": "server/discover"}], env_mq)
        check(os.path.getmtime(marker) > t0, "재수신 시 mtime 갱신")
        os.remove(marker)

    # 대조군 — 마커 범위를 넓힌 것이 아님을 함께 고정한다
    rpc(mq_server, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], env_mq)
    check(not os.path.exists(marker), "대조군: tools/list 단독은 마커를 찍지 않음")

    print("\n" + ("🎉 전건 통과" if not FAIL else f"❌ 실패 {len(FAIL)}건: " + " / ".join(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
