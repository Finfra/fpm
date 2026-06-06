#!/usr/bin/env python3
# test_feed_link.py — Issue62 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 피드↔htm 문서
#   ↗ 링크 매칭 헬퍼(_link_feed_htm_docs 등)를 검증한다.
#
# 실행: python3 services/htm-server/test_feed_link.py
"""server.py 피드↔htm 문서 링크 3단계 매칭 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def doc(path, cwd, ts_mtime=0, view="/htm-doc?path=x", title="T", missing=False):
    return {"path": path, "cwd": cwd, "mtime_ts": ts_mtime,
            "view_url": view, "title": title, "missing": missing}


def feed(cwd, ts, detail=""):
    return {"cwd": cwd, "ts": ts, "detail": detail}


# --- _htm_doc_ts ---
check("htm_doc_ts: 본문 문서",
      server._htm_doc_ts("/p/_doc_work/z_htm/claude-htm-1779282225.html") == 1779282225)
check("htm_doc_ts: B모드 ask 폼",
      server._htm_doc_ts("/p/_doc_work/z_htm/claude-htm-ask-1779284908.html") == 1779284908)
check("htm_doc_ts: auto 폼",
      server._htm_doc_ts("/p/_doc_work/z_htm/claude-htm-auto-1779200000.html") == 1779200000)
check("htm_doc_ts: 미일치 → 0", server._htm_doc_ts("/p/foo.html") == 0)

# --- _cwd_related ---
check("cwd_related: 동일", server._cwd_related("/a/b", "/a/b"))
check("cwd_related: 하위 디렉토리", server._cwd_related("/a/b", "/a/b/cli"))
check("cwd_related: 상위 디렉토리", server._cwd_related("/a/b/cli", "/a/b"))
check("cwd_related: 무관", not server._cwd_related("/a/b", "/a/c"))
check("cwd_related: prefix 오탐 차단", not server._cwd_related("/a/bcd", "/a/b"))
check("cwd_related: 빈 값", not server._cwd_related("", "/a/b"))

# --- tier 1: 절대경로 ---
p1 = "/p/_doc_work/z_htm/claude-htm-1779282225.html"
fd = [feed("/p", 1000, detail=f"렌더 완료\n\n📁 {p1}")]
server._link_feed_htm_docs(fd, [doc(p1, "/p")])
check("tier1: 절대경로 detail → 연결", fd[0].get("htm_view_url"))

# --- tier 2: basename (상대경로/백틱) ---
p2 = "/p/_doc_work/z_htm/claude-htm-1779282223.html"
fd = [feed("/p", 1000,
           detail="HTML 저장. `_doc_work/z_htm/claude-htm-1779282223.html`")]
server._link_feed_htm_docs(fd, [doc(p2, "/p")])
check("tier2: basename 만 등장해도 연결", fd[0].get("htm_view_url"))

# --- tier 3: 턴 근접 (B모드 폼, detail 에 경로 언급 전무) ---
p3 = "/p/cli/_doc_work/z_htm/claude-htm-ask-1779283496.html"
fd = [
    feed("/p", 1779282742, detail="Issue137 Test 완료"),    # 직전 Stop
    feed("/p", 1779284600, detail="Issue137 plan 완료"),    # 폼 생성 턴의 완료
    feed("/p", 1779286172, detail="Issue135 cliApp 완료"),  # 다음 턴
]
server._link_feed_htm_docs(fd, [doc(p3, "/p/cli")])  # 폼 cwd 는 하위 디렉토리
check("tier3: 턴 구간 내 폼 → 해당 완료 피드 연결", fd[1].get("htm_view_url"))
check("tier3: 직전 턴 피드는 미연결", not fd[0].get("htm_view_url"))
check("tier3: 다음 턴 피드는 미연결", not fd[2].get("htm_view_url"))

# --- 음성: htm 문서 없는 턴은 미연결 ---
fd = [
    feed("/p", 1000, detail="그냥 커밋 완료"),
    feed("/p", 2000, detail="리팩터링 완료"),
]
server._link_feed_htm_docs(fd, [doc(p3, "/p/cli")])  # 폼 ts 1779283496 ≫ 2000+윈도우
check("음성: 윈도우 밖 문서는 어느 피드에도 미연결",
      not fd[0].get("htm_view_url") and not fd[1].get("htm_view_url"))

# --- missing 문서 / view_url 없는 문서는 제외 ---
fd = [feed("/p", 1779284600, detail="x")]
server._link_feed_htm_docs(fd, [doc(p3, "/p/cli", missing=True)])
check("missing 문서는 링크 대상 제외", not fd[0].get("htm_view_url"))
fd = [feed("/p", 1779284600, detail="x")]
server._link_feed_htm_docs(fd, [doc(p3, "/p/cli", view="")])
check("view_url 빈 문서는 링크 대상 제외", not fd[0].get("htm_view_url"))

# --- tier 3 경계: Stop 직후 생성 문서는 직전 완료가 아닌 다음 턴에 연결 ---
# 회귀 — 시계 오차 유예(+120s)가 다음 턴 문서를 직전 완료로 새게 했던 버그.
p4 = "/q/_doc_work/z_htm/claude-htm-1779285483.html"  # ts 1779285483
fd = [
    feed("/q", 1779285367, detail="ComponentTest 완료"),  # 문서보다 116s 앞선 Stop
    feed("/q", 1779285567, detail="Firefox diagram 완료"),  # 문서가 생성된 턴
]
server._link_feed_htm_docs(fd, [doc(p4, "/q")])
check("tier3 경계: 직전 Stop(문서보다 앞섬)에 미연결",
      not fd[0].get("htm_view_url"))
check("tier3 경계: 문서 생성 턴의 완료 피드에 연결", fd[1].get("htm_view_url"))

# --- 보조키 _htm_link_ts 누수 없음 ---
fd = [feed("/p", 1779284600, detail="x")]
server._link_feed_htm_docs(fd, [doc(p3, "/p/cli")])
check("내부 보조키 _htm_link_ts 미누수", "_htm_link_ts" not in fd[0])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
