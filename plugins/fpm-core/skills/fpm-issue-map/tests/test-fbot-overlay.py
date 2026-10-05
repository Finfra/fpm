#!/usr/bin/env python3
"""issue-map `--fbot` 오버레이 + 이슈 앵커 딥링크 회귀 테스트 (prj3#Issue740, Issue725 M2).

재생목록 id: `issue-map-fbot-overlay` (prj3 `tdd/playlist.md`).

검증 축:
  1. 배분 fixture DB(임시 registry.db) → 배분된 이슈 **노드**에 담당 봇 배지 · 배분 없는 노드엔 없음
  2. 시간 창 — 열린 배분 + 최근 3일 종결만. 오래된 종결은 빠진다
  3. DB 부재 → 오버레이만 빠지고 맵은 정상 생성(rc 0) + 1줄 안내
  4. 앵커 — 노드 `id="issue-<N>"` · 표 행 `id="issue-<N>-row"` · `#issue=<N>` 수신 스크립트
  5. 옵트인 — `--fbot` 없으면 DB 가 있어도 배지 없음
  6. `payload.issue` 정규화 — 선두 식별자 · `prj<N>#` 접두가 `payload.prj`(작업 위치)보다 우선
  7. `--json` — `--fbot` 없으면 기존 4키 그대로, 있으면 `fbot` 키만 추가

mmdc 는 가짜 실행체로 대체한다(PATH 선두) — 브라우저 없이 돌고, 산출 SVG 의 노드 마크업
(`<g class="node …" id="flowchart-IssueN-k">`)은 실 mermaid 형식을 흉내 낸다.
원장 경로는 `AOA_MEMORY_DIR` 로 준다 — `fbot-state.py aoa_dir()` 해석 계약 그대로다.

실행:
    python3 ~/.claude/skills/issue-map/tests/test-fbot-overlay.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "build_issue_map.py"

ISSUE_MD = """# Issue Management
* Issue HWM: 3

# 🚧 진행중
## Issue2: 두번째 이슈 (등록: 2026-09-28)
* 목적: 테스트
* depends: Issue1

# 📙 일반
## Issue1: 첫번째 이슈 (등록: 2026-09-28)
* 목적: 테스트

## Issue3: 세번째 이슈 (등록: 2026-09-28)
* 목적: 테스트

# ✅ 완료
"""

# 실 mermaid 노드 마크업을 흉내 내는 가짜 mmdc — 노드 정의 줄을 <g id="flowchart-…"> 로 옮긴다
FAKE_MMDC = r'''#!/usr/bin/env python3
import re, sys
a = sys.argv[1:]
src, dst = a[a.index("-i") + 1], a[a.index("-o") + 1]
mmd = open(src, encoding="utf-8").read()
parts = ['<svg id="my-svg" style="max-width: 300px;" xmlns="http://www.w3.org/2000/svg"><g class="nodes">']
for k, m in enumerate(re.finditer(r'^\s+(\w+)\["(.*)"\]\s*$', mmd, re.M)):
    parts.append('<g class="node default" id="flowchart-%s-%d"><foreignObject><div>'
                 '<span class="nodeLabel"><p>%s</p></span></div></foreignObject></g>'
                 % (m.group(1), k, m.group(2)))
parts.append("</g></svg>")
open(dst, "w", encoding="utf-8").write("".join(parts))
'''


def load_module():
    spec = importlib.util.spec_from_file_location("build_issue_map", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_db(path: Path, jobs, bots=()):
    """registry.db 최소 스키마 — 오버레이가 읽는 열만. 실 스키마의 owner/owner_id 이원을 따른다."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE job(id TEXT PRIMARY KEY, store TEXT, kind TEXT, status TEXT,"
                " payload TEXT, result TEXT, attempts INT, owner TEXT, lease_until INT,"
                " blocked_since INT, created_at INT, owner_kind TEXT, owner_id TEXT)")
    con.execute("CREATE TABLE bot(bot_id TEXT PRIMARY KEY, title TEXT, role TEXT, state TEXT,"
                " career TEXT, icon TEXT, color TEXT, prj INT, created_at INT)")
    for j in jobs:
        con.execute("INSERT INTO job(id, store, kind, status, payload, owner, owner_id, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (j["id"], "fbot", j.get("kind", "fbot_dispatch"), j["status"],
                     json.dumps(j["payload"], ensure_ascii=False), j["owner"], j["owner"],
                     j["created_at"]))
    for b in bots:
        con.execute("INSERT INTO bot(bot_id, title, role, state, career, icon, color, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (b["bot_id"], b.get("title", ""), b["role"], "working", "active",
                     b.get("icon", ""), b.get("color", "#336699"), 0))
    con.commit()
    con.close()


def node_block(html_text: str, n: str) -> str:
    """노드 앵커 id="issue-<n>" 인 <g> 의 내용 — 없으면 ""."""
    m = re.search(r'<g[^>]*\bid="issue-%s"[^>]*>(.*?)</g>' % re.escape(n), html_text, re.S)
    return m.group(1) if m else ""


def row_block(html_text: str, n: str) -> str:
    m = re.search(r'<tr[^>]*\bid="issue-%s-row"[^>]*>(.*?)</tr>' % re.escape(n), html_text, re.S)
    return m.group(1) if m else ""


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        (self.root / "Issue.md").write_text(ISSUE_MD, encoding="utf-8")
        self.aoa = self.tmp / "aoa"
        self.aoa.mkdir()
        bindir = self.tmp / "bin"
        bindir.mkdir()
        fake = bindir / "mmdc"
        fake.write_text(FAKE_MMDC, encoding="utf-8")
        fake.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("FBOT_", "AOA_", "CLAUDE_CODE_"))}
        self.env["PATH"] = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
        self.env["AOA_MEMORY_DIR"] = str(self.aoa)
        self.now = int(time.time())

    def tearDown(self):
        self._td.cleanup()

    def run_map(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--no-cross", *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True,
                              timeout=60)

    def seed(self, jobs, bots=()):
        make_db(self.aoa / "registry.db", jobs, bots)

    def disp(self, jid, issue, status, ago_secs, worker, owner="fbot-lead-repo", prj=None):
        pl = {"issue": issue, "ident_kind": "issue", "role": "developer",
              "worker_bot_id": worker, "cwd": str(self.root)}
        if prj is not None:
            pl["prj"] = prj
        return {"id": jid, "status": status, "owner": owner,
                "created_at": self.now - ago_secs, "payload": pl}


class OverlayTest(Base):
    def test_badge_on_dispatched_node_only(self):
        self.seed([self.disp("d1", "Issue2", "open", 600, "fbot-developer-issue2")],
                  [{"bot_id": "fbot-developer-issue2", "role": "developer", "color": "#AE615C"}])
        r = self.run_map("--fbot")
        self.assertEqual(r.returncode, 0, r.stderr)
        h = (self.root / "Issue_map.htm").read_text(encoding="utf-8")
        n2 = node_block(h, "2")
        self.assertIn("developer-issue2", n2, "배분된 Issue2 노드에 담당 봇 배지가 없다")
        self.assertIn("⏳", n2, "열린 배분 사인(⏳)이 노드에 없다")
        self.assertNotIn("developer-issue2", node_block(h, "1"), "배분 없는 노드에 배지가 붙었다")
        self.assertIn("developer-issue2", row_block(h, "2"), "표 행에 담당 봇이 없다")
        self.assertIn("fbot-lead-repo", row_block(h, "2"), "표 행에 배분자(누가 시켰나)가 없다")

    def test_window_open_or_recent_3days(self):
        day = 86400
        self.seed([
            self.disp("old", "Issue1", "done", 5 * day, "fbot-developer-old"),
            self.disp("new", "Issue3", "done", 1 * day, "fbot-developer-new"),
            self.disp("stale-open", "Issue2", "open", 9 * day, "fbot-developer-long"),
        ])
        r = self.run_map("--fbot")
        self.assertEqual(r.returncode, 0, r.stderr)
        h = (self.root / "Issue_map.htm").read_text(encoding="utf-8")
        self.assertNotIn("developer-old", h, "3일 넘은 종결 배분이 남았다")
        self.assertIn("developer-new", node_block(h, "3"), "최근 종결 배분이 빠졌다")
        self.assertIn("✓", node_block(h, "3"), "완료 사인(✓)이 없다")
        self.assertIn("developer-long", node_block(h, "2"), "오래됐어도 열린 배분은 남아야 한다")

    def test_db_absent_map_still_generated(self):
        r = self.run_map("--fbot")          # aoa 디렉터리는 비어 있다
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.root / "Issue_map.htm"
        self.assertTrue(out.exists(), "DB 부재에 맵이 생성되지 않았다")
        notes = [ln for ln in (r.stdout + r.stderr).splitlines() if "fbot 오버레이" in ln]
        self.assertEqual(len(notes), 1, f"DB 부재 안내가 정확히 1줄이어야 한다: {notes!r}")
        self.assertTrue(node_block(out.read_text(encoding="utf-8"), "2") != "")

    def test_db_unreadable_map_still_generated(self):
        (self.aoa / "registry.db").write_bytes(b"not a sqlite database" * 50)
        r = self.run_map("--fbot")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / "Issue_map.htm").exists())
        notes = [ln for ln in (r.stdout + r.stderr).splitlines() if "fbot 오버레이" in ln]
        self.assertEqual(len(notes), 1, f"읽기 실패 안내가 정확히 1줄이어야 한다: {notes!r}")

    def test_malformed_row_does_not_crash(self):
        # 원장 행이 계약을 어겨도(created_at 비정수) 맵 생성이 죽으면 안 된다 — 오버레이만 빠진다
        self.seed([self.disp("d1", "Issue2", "open", 600, "fbot-developer-issue2")])
        con = sqlite3.connect(self.aoa / "registry.db")
        con.execute("UPDATE job SET created_at='어제' WHERE id='d1'")
        con.commit()
        con.close()
        r = self.run_map("--fbot")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / "Issue_map.htm").exists())

    def test_opt_in_only(self):
        self.seed([self.disp("d1", "Issue2", "open", 600, "fbot-developer-issue2")])
        r = self.run_map()
        self.assertEqual(r.returncode, 0, r.stderr)
        h = (self.root / "Issue_map.htm").read_text(encoding="utf-8")
        self.assertNotIn("developer-issue2", h, "--fbot 없이 봇 명부가 새었다(옵트인 위반)")


class AnchorTest(Base):
    def test_node_and_row_anchor_ids(self):
        r = self.run_map()
        self.assertEqual(r.returncode, 0, r.stderr)
        h = (self.root / "Issue_map.htm").read_text(encoding="utf-8")
        for n in ("1", "2", "3"):
            self.assertRegex(h, r'<g[^>]*\bid="issue-%s"' % n, f"노드 앵커 issue-{n} 없음")
            self.assertRegex(h, r'<tr[^>]*\bid="issue-%s-row"' % n, f"표 행 앵커 issue-{n}-row 없음")
            self.assertRegex(h, r'data-issue="%s"' % n)
        self.assertEqual(len(re.findall(r'\bid="issue-2"', h)), 1, "앵커 id 는 문서에서 유일해야 한다")

    def test_deeplink_receiver_script(self):
        r = self.run_map()
        self.assertEqual(r.returncode, 0, r.stderr)
        h = (self.root / "Issue_map.htm").read_text(encoding="utf-8")
        self.assertIn("hashchange", h, "#issue= 변경 수신 리스너가 없다")
        self.assertRegex(h, r"issue=", "#issue=<N> 파서가 없다")
        self.assertIn("scrollIntoView", h, "착지 스크롤이 없다")


class NormalizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_dispatch_issue_ref(self):
        f = self.m.dispatch_issue_ref
        self.assertEqual(f("Issue415", 42), (42, "Issue415"))
        self.assertEqual(f("718", 3), (3, "Issue718"), "숫자만 적힌 배분도 이슈다")
        self.assertEqual(f("`prj3#Issue651`", 3), (3, "Issue651"))
        self.assertEqual(f("Issue10 fCapture MCP 플러그인 신설", 20), (20, "Issue10"))
        self.assertEqual(f("Issue21 자산 격리 → Issue22 표 작성", 61), (61, "Issue21"),
                         "선두 식별자가 주제다 — 뒤에 언급된 이슈로 붙지 않는다")
        # 접두가 작업 위치(payload.prj)보다 우선 — prj5 의 이슈를 prj15 에서 수행한 배분
        self.assertEqual(f("prj5#Issue99 TDD 라운드: 전 목표 실행", 15), (5, "Issue99"))
        self.assertEqual(f("Issue7_2", None), (None, "Issue7_2"))
        self.assertIsNone(f("2일차 도면 부시·핀 계열 보강", 60), "이슈 식별자 없는 topic 은 붙이지 않는다")
        self.assertIsNone(f("", 3))

    def test_match_by_project(self):
        root = Path("/tmp/nonexistent-issue-map-root")
        rows = [
            {"id": "a", "status": "open", "owner": "o", "created_at": 1,
             "payload": {"issue": "Issue99", "prj": 5, "worker_bot_id": "w1", "cwd": "/x"}},
            {"id": "b", "status": "open", "owner": "o", "created_at": 1,
             "payload": {"issue": "prj5#Issue99 라운드", "prj": 15, "worker_bot_id": "w2", "cwd": "/y"}},
            {"id": "c", "status": "open", "owner": "o", "created_at": 1,
             "payload": {"issue": "Issue99", "prj": 15, "worker_bot_id": "w3", "cwd": "/y"}},
            {"id": "d", "status": "open", "owner": "o", "created_at": 1,
             "payload": {"issue": "Issue99", "worker_bot_id": "w4", "cwd": str(root)}},
        ]
        got = self.m.match_dispatches(rows, {"Issue99"}, root, 5)
        self.assertEqual(sorted(r["id"] for r in got.get("Issue99", [])), ["a", "b", "d"],
                         "prj5 맵: 필드 5·접두 5·(prj 미상이면 cwd 일치)만 — 다른 prj 의 동번호는 제외")
        got15 = self.m.match_dispatches(rows, {"Issue99"}, Path("/y"), 15)
        self.assertEqual(sorted(r["id"] for r in got15.get("Issue99", [])), ["c"],
                         "접두 prj5 배분이 작업 위치 prj15 맵에 붙으면 안 된다")


class JsonTest(Base):
    def test_json_keys_unchanged_without_fbot(self):
        self.seed([self.disp("d1", "Issue2", "open", 600, "fbot-developer-issue2")])
        r = self.run_map("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(json.loads(r.stdout)), ["cross", "generated", "issues", "root"])

    def test_json_fbot_key_added(self):
        self.seed([self.disp("d1", "Issue2", "open", 600, "fbot-developer-issue2")])
        r = self.run_map("--json", "--fbot")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(sorted(d), ["cross", "fbot", "generated", "issues", "root"])
        self.assertTrue(d["fbot"]["ok"])
        badge = d["fbot"]["issues"]["Issue2"][0]
        self.assertEqual(badge["worker"], "fbot-developer-issue2")
        self.assertEqual(badge["owner"], "fbot-lead-repo")
        self.assertEqual(badge["status"], "open")

    def test_json_fbot_db_absent_still_pure_json(self):
        r = self.run_map("--json", "--fbot")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertFalse(d["fbot"]["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
