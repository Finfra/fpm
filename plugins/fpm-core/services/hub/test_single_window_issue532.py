#!/usr/bin/env python3
# test_single_window_issue532.py — Issue532 회귀 테스트 (세션당 창 하나)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 라이브 뷰 탭과 md 문서 탭이 따로 떠
#   브라우저 탭이 두 배로 쌓이던 결함 검증:
#   A. mailbox 가 hub 문서 Write 를 `doc` 블록(경로만)으로 적재 — 본문·타 도구 인자는 적재하지 않음
#   B. `/md-doc?raw=1` 은 화이트리스트 통과분만 원문을 준다
#   C. `_live_route` — 라이브 창이 폴링 중이면 skip, 아니면 라이브 URL, archive·미등록은 원래 URL
#
# 실행: python3 plugins/fpm-core/services/hub/test_single_window_issue532.py
import json
import os
import sys
import tempfile
import time
from urllib.parse import urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mailbox  # noqa: E402
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


TMP = tempfile.mkdtemp(prefix="issue532-")
PROJ = os.path.join(TMP, "proj")
HTM_DIR = os.path.join(PROJ, "_doc_work", "htm")
os.makedirs(HTM_DIR)
SID = "sid-532"
DOC = os.path.join(HTM_DIR, "hub_htm_20260926_120000_a_topic.md")
SECRET = "본문-비밀-문자열"
with open(DOC, "w", encoding="utf-8") as f:
    f.write(f"---\ntitle: 토픽\nsid: {SID}\n---\n\n# 헤딩\n\n{SECRET}\n")


def assistant(*blocks):
    return {"type": "assistant", "timestamp": "2026-09-26T00:00:01Z",
            "message": {"role": "assistant", "content": list(blocks)}}


def tool(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


# --- A. mailbox doc 블록 ---
JSONL = os.path.join(TMP, "sess.jsonl")
with open(JSONL, "w", encoding="utf-8") as f:
    for e in (
        assistant(tool("Write", file_path=DOC, content=SECRET)),
        assistant(tool("Write", file_path=os.path.join(PROJ, "notes.md"), content="x")),
        assistant(tool("Bash", command=f"cat {DOC}")),
        assistant(tool("Write", file_path=os.path.join(HTM_DIR, "hub_htm_20260926_120001_b_ask.md"),
                       content="form")),
    ):
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
box = mailbox.SessionMailbox(("h532", SID), JSONL)
box.sync()
kinds = [(b["kind"], b["text"]) for b in box.blocks]
check("A1 hub a모드 문서 Write → doc 블록(경로)", ("doc", DOC) in kinds)
check("A2 문서 본문은 어떤 블록에도 없음", not any(SECRET in t for _, t in kinds))
check("A3 규약 밖 Write 는 도구 이름만", ("activity", "Write") in kinds
      and not any("notes.md" in t for _, t in kinds))
check("A4 Bash 인자(문서 경로 포함)는 적재 안 함", not any(k == "doc" and "cat" in t for k, t in kinds)
      and sum(1 for k, _ in kinds if k == "doc") == 1)
check("A5 b모드(폼)는 doc 블록 아님 — 폼 카드 경로가 담당", not any("_b_ask" in t for _, t in kinds))
check("A6 생성 직후 폴링 기록 없음", getattr(box, "last_poll", None) == 0)
box.read_since(0, "")
check("A7 /mail 폴링은 last_poll 을 갱신", box.last_poll > 0)


# --- B. /md-doc?raw=1 ---
class _W:
    def __init__(self, o):
        self.o = o

    def write(self, b):
        self.o.raw += b


class _H(server.Handler):
    def __init__(self):
        self.client_address = ("127.0.0.1", 0)
        self.json_responses = []
        self.raw = b""
        self._status = None

    def _send_json(self, status, body):
        self.json_responses.append((status, body))

    def send_response(self, status):
        self._status = status

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    @property
    def wfile(self):
        return _W(self)


server.HTM_REGISTRY = os.path.join(TMP, "htm-registry.json")
server.HTM_CLEARED = os.path.join(TMP, "htm-cleared.json")
server.save_registry(server.HTM_REGISTRY, [{"path": DOC, "cwd": PROJ}])
server.save_registry(server.HTM_CLEARED, [])

h = _H()
h._handle_md_doc(urlparse("/md-doc?path=" + quote(DOC) + "&raw=1"))
ok = h.json_responses and h.json_responses[0][0] == 200
check("B1 raw=1 → 200 JSON 원문", ok and SECRET in h.json_responses[0][1].get("md", ""))
OUT = os.path.join(PROJ, "notes.md")
open(OUT, "w").write("# outside\n")
h = _H()
h._handle_md_doc(urlparse("/md-doc?path=" + quote(OUT) + "&raw=1"))
check("B2 raw=1 도 화이트리스트 밖은 403", h.json_responses and h.json_responses[0][0] == 403)


# --- C. _live_route ---
H = server.cwd_hash(PROJ)
server.projects[H] = {"cwd": PROJ, "token": "t" * 32}
server._resolve_session_jsonl = lambda cwd, sid: JSONL if sid == SID else ""
doc_url = "http://127.0.0.1:9876/md-doc?path=" + quote(DOC)
_orig_setting = server._load_hub_setting


def with_display(v):
    server._load_hub_setting = lambda: dict(_orig_setting(), render_display=v)


with_display("auto")
live_box = mailbox.get_box(H, SID, JSONL)
live_box.last_poll = time.time()
r = server.Handler._live_route(doc_url)
check("C1 라이브 창이 폴링 중 → skip", r.get("action") == "skip")

live_box.last_poll = time.time() - 10_000
r = server.Handler._live_route(doc_url)
check("C2 창 없음(폴링 끊김) → 라이브 URL 을 연다",
      r.get("action") == "open" and f"/s/{H}/{SID}/live?token=" in r.get("url", ""))

live_box.last_poll = time.time()
mailbox.mark_closed(H, SID)
r = server.Handler._live_route(doc_url)
check("C3 닫힘 신호 후 → 폴링 시각이 최근이어도 라이브 URL", r.get("action") == "open"
      and "/live?" in r.get("url", ""))

with_display("archive")
r = server.Handler._live_route(doc_url)
check("C4 archive 모드 → 원래 문서 URL", r == {"action": "open", "url": doc_url})

with_display("auto")
r = server.Handler._live_route("http://127.0.0.1:9876/md-doc?path=" + quote(OUT))
check("C5 미등록 문서 → 원래 URL (fail-open)", r.get("action") == "open"
      and r.get("url", "").endswith(quote(OUT)))
r = server.Handler._live_route("http://127.0.0.1:9876/hub")
check("C6 md-doc 아닌 URL → 원래 URL", r == {"action": "open", "url": "http://127.0.0.1:9876/hub"})

server._load_hub_setting = _orig_setting

# --- D. 라이브 셸 — doc 블록 처리·닫힘 beacon 이 실리고, 셸이 UTF-8 로 인코딩된다 ---
#   (JS 이스케이프가 파이썬 문자열에서 한 단계 풀리면 surrogate·날 개행이 섞여 serve 가 깨진다)
import md_shell  # noqa: E402
try:
    shell = md_shell.render_live_shell("t", PROJ, "proj", SID, H, "t" * 32, md_shell.make_nonce())
    enc_ok = True
except UnicodeEncodeError:
    shell, enc_ok = b"", False
check("D1 라이브 셸 UTF-8 인코딩 성공", enc_ok)
check("D2 doc 블록 처리기·원문 경로가 셸에 있음", b"applyDoc" in shell and b"/md-doc?raw=1&path=" in shell)
check("D3 닫힘 beacon 경로가 셸에 있음", f"/s/{H}/{SID}/bye?token=".encode() in shell)

# --- E. 순서 경쟁 — Write 기록이 파일보다 먼저 도착해도 재시도로 결국 렌더한다 (node 실행) ---
import shutil  # noqa: E402
import subprocess  # noqa: E402
NODE_HARNESS = r"""
const fs = require('fs');
const js = fs.readFileSync(process.argv[2], 'utf8');
const cfg = {mail: '/mail?token=t', docRaw: '/raw?path=', bye: '/bye', degradeReport: '/deg',
             display: 'live', degrade: {nodes: 1e9, renderMs: 1e9, heapPct: 100}};
function el() { return {className: '', textContent: '', children: [], style: {}, classList: {add(){}, remove(){}, toggle(){}},
  appendChild(c) { this.children.push(c); return c; }, insertBefore(c) { this.children.unshift(c); return c; },
  addEventListener() {}, querySelectorAll() { return []; }, set innerHTML(v) { this.children = []; } }; }
const nodes = {'live-cfg': Object.assign(el(), {textContent: JSON.stringify(cfg)}), 'live-root': el(),
               'live-dot': el(), 'live-text': el(), 'form-slot': el()};
global.document = {getElementById: id => nodes[id] || el(), createElement: el, addEventListener() {},
                   hidden: false, getElementsByTagName: () => []};
global.window = {addEventListener() {}, performance: null};
global.navigator = {sendBeacon() {}};
let rawCalls = 0, rendered = null, mailServed = false;
global.fetch = (url) => {
  if (url.startsWith('/raw')) {
    rawCalls += 1;
    if (rawCalls < 3) return Promise.resolve({ok: false, status: 404});
    return Promise.resolve({ok: true, json: () => Promise.resolve({md: '---\nsid: x\n---\n# 본문', path: '/p'})});
  }
  if (url.startsWith('/mail') && !mailServed) {
    mailServed = true;
    return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve({epoch: 'e', max_seq: 1, min_seq: 1,
      blocks: [{seq: 1, kind: 'doc', text: '/p/_doc_work/htm/hub_htm_1_a_x.md', ts: ''}]})});
  }
  return new Promise(() => {});   // 이후 폴링은 보류
};
global.setTimeout = (fn) => { Promise.resolve().then(fn); return 1; };
global.clearTimeout = () => {};
window.hubRenderMd = (holder, md) => { rendered = md; };
eval(js);
setImmediate(() => setImmediate(() => setImmediate(() => {
  const done = () => console.log(JSON.stringify({rawCalls, rendered}));
  let n = 0; (function wait() { if (rendered !== null || n++ > 200) return done(); setImmediate(wait); })();
})));
"""
if shutil.which("node"):
    jsf = os.path.join(TMP, "live.js")
    with open(jsf, "w", encoding="utf-8") as f:
        f.write(md_shell.LIVE_JS)
    hf = os.path.join(TMP, "harness.js")
    with open(hf, "w", encoding="utf-8") as f:
        f.write(NODE_HARNESS)
    out = subprocess.run(["node", hf, jsf], capture_output=True, text=True, timeout=30)
    try:
        res = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        res = {}
        print(out.stdout[-500:], out.stderr[-800:])
    check("E1 404 두 번 뒤 세 번째 조회에서 렌더", res.get("rawCalls") == 3 and res.get("rendered") == "# 본문")
    check("E2 frontmatter 는 떼고 렌더", "sid:" not in (res.get("rendered") or ""))
else:
    print("  skip E (node 없음)")

# --- F. 턴은 시간순(위→아래) · 문서가 나오면 그 턴의 로그 단위를 접는다 (node 실행) ---
NODE_ORDER = r"""
const fs = require('fs');
const js = fs.readFileSync(process.argv[2], 'utf8');
const cfg = {mail: '/mail?token=t', docRaw: '/raw?path=', bye: '/bye', degradeReport: '/deg',
             display: 'live', degrade: {nodes: 1e9, renderMs: 1e9, heapPct: 100}};
function cls(e) { return (e.className || '').split(/\s+/).filter(Boolean); }
function el(tag) {
  const e = {tagName: (tag || 'div').toUpperCase(), className: '', textContent: '', children: [], style: {},
    appendChild(c) { this.children.push(c); return c; }, insertBefore(c) { this.children.unshift(c); return c; },
    addEventListener() {}, set innerHTML(v) { this.children = []; },
    querySelectorAll(sel) {
      const want = sel.split('.').filter(Boolean), out = [];
      (function walk(n) { n.children.forEach(k => { if (want.every(w => cls(k).includes(w))) out.push(k); walk(k); }); })(this);
      return out;
    }};
  e.classList = {add(c) { if (!cls(e).includes(c)) e.className = (e.className + ' ' + c).trim(); },
                 remove(c) { e.className = cls(e).filter(x => x !== c).join(' '); },
                 toggle(c) { cls(e).includes(c) ? this.remove(c) : this.add(c); },
                 contains(c) { return cls(e).includes(c); }};
  return e;
}
const nodes = {'live-cfg': Object.assign(el(), {textContent: JSON.stringify(cfg)}), 'live-root': el(),
               'live-dot': el(), 'live-text': el(), 'form-slot': el()};
global.document = {getElementById: id => nodes[id] || el(), createElement: el, addEventListener() {},
                   hidden: false, getElementsByTagName: () => [], documentElement: {scrollHeight: 0}};
global.window = {addEventListener() {}, performance: null, innerHeight: 0, scrollY: 0, scrollTo() {}};
global.navigator = {sendBeacon() {}};
let served = false;
const B = (seq, kind, text) => ({seq, kind, text, ts: ''});
global.fetch = (url) => {
  if (url.startsWith('/raw')) return Promise.resolve({ok: true, json: () => Promise.resolve({md: '# 문서', path: '/p'})});
  if (url.startsWith('/mail') && !served) {
    served = true;
    return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve({epoch: 'e', max_seq: 8, min_seq: 1,
      blocks: [B(1, 'turn', 'Q1'), B(2, 'text', '작업 중'), B(3, 'activity', 'Bash'),
               B(4, 'doc', '/p/_doc_work/htm/hub_htm_1_a_x.md'), B(5, 'text', '요약'),
               B(6, 'turn', 'Q2'), B(7, 'text', '짧은 답'), B(8, 'activity', 'Read')]})});
  }
  return new Promise(() => {});
};
global.setTimeout = (fn) => { Promise.resolve().then(fn); return 1; };
global.clearTimeout = () => {};
window.hubRenderMd = (h, md) => { h.textContent = md; };
eval(js);
let waited = 0;
(function wait() {
  const ready = nodes['live-root'].children.filter(t => cls(t).includes('turn')).length >= 2;
  if (!ready && waited++ < 500) return setImmediate(wait);
  setImmediate(report);
})();
function report() {
  const turns = nodes['live-root'].children.filter(t => cls(t).includes('turn'));
  const q = t => t.children[0].children[0].textContent;
  const units = t => t.children[1].children.map(u => cls(u).filter(c => ['log', 'doc', 'folded'].includes(c)).join('+'));
  const heads = t => t.children[1].children.map(u => u.children[0].textContent);
  console.log(JSON.stringify({order: turns.map(q), u1: units(turns[0]), u2: units(turns[1]), h1: heads(turns[0])}));
}
"""
if shutil.which("node"):
    of = os.path.join(TMP, "order.js")
    with open(of, "w", encoding="utf-8") as f:
        f.write(NODE_ORDER)
    out = subprocess.run(["node", of, jsf], capture_output=True, text=True, timeout=30)
    try:
        res = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        res = {}
        print(out.stdout[-500:], out.stderr[-800:])
    check("F1 턴은 시간순 — 먼저 온 턴이 위", res.get("order") == ["Q1", "Q2"])
    check("F2 문서 턴: 앞 로그 접힘 · 문서 펼침 · 뒤 로그도 접힘",
          res.get("u1") == ["log+folded", "doc", "log+folded"])
    check("F3 문서 없는 턴의 로그는 펼친 채", res.get("u2") == ["log"])
    check("F4 로그 단위 머리에 건수 표시", (res.get("h1") or [""])[0] == "로그 · 2")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
