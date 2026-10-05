#!/usr/bin/env python3
"""이슈맵 «⏸️ 보류 포함» 토글 회귀 테스트 (prj3#Issue974).

재생목록 id: `issue-map-held-toggle` (prj3 `tdd/playlist.md`).

왜: 이슈맵은 보류·취소를 제외한다(Issue259). 보류 이슈의 의존 흐름을 보고 싶을 때 볼 수단이
  없었다 — 헤더 토글로 «보류 포함» 변형을 켜고, 선택값은 저장한다. 기본값은 미포함.

검증 축:
  1. 기본 변형(먼저 오는 쪽)은 종전과 같다 — 보류 이슈·그 선행이 관계도에 없다
  2. «보류 포함» 변형이 같은 파일에 있고 기본은 숨김 — 보류 이슈 노드·표 행이 있다
  3. 보류 이슈의 **타 prj 선행**도 포함 변형의 관계도(외부 노드)·연동 표에 들어간다
  4. 🚫 취소는 토글 대상 아님 — 포함 변형에도 없다
  5. `ISSUE-MAP:*` 마커는 기본 변형에만 1벌(hub `_issue_map_has_graph` 판정 불변)
  6. 포함 변형 SVG 의 mermaid id 는 `my-svg` 가 아니다(숨긴 변형의 marker 참조 방지) · 앵커 id 중복 0
  7. 헤더 토글 버튼 + localStorage 저장(try/catch) · 기본 미포함 · 인라인 스크립트 `node --check`
  8. 보류 이슈 0건이면 포함 변형을 만들지 않고 버튼은 비활성

mmdc 는 가짜 실행체로 대체한다(PATH 선두). 타 prj 는 임시 HOME 의 projects 레지스트리로 꾸민다.

실행:
    python3 ~/.claude/skills/issue-map/tests/test-held-toggle.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "build_issue_map.py"

ISSUE_MD = """# Issue Management
* Issue HWM: 8

# 🚧 진행중
## Issue2: 두번째 이슈 (등록: 2026-10-05)
* 목적: 테스트
* depends: Issue1

# 📙 일반
## Issue1: 첫번째 이슈 (등록: 2026-10-05)
* 목적: 테스트

# ✅ 완료

# ⏸️ 보류
## Issue5: 보류된 이슈 (등록: 2026-10-05)
* 목적: 테스트
* depends: Issue1, prj7#Issue50

## Issue6: 선행 없는 보류 (등록: 2026-10-05)
* 목적: 테스트

# 🚫 취소
## Issue8: 취소된 이슈 (등록: 2026-10-05)
* 목적: 테스트
* depends: prj7#Issue51
"""

ISSUE_MD_NO_HELD = """# Issue Management
* Issue HWM: 2

# 🚧 진행중
## Issue2: 두번째 이슈 (등록: 2026-10-05)
* 목적: 테스트
* depends: Issue1

# 📙 일반
## Issue1: 첫번째 이슈 (등록: 2026-10-05)
* 목적: 테스트

# ✅ 완료
"""

OTHER_ISSUE_MD = """# Issue Management
* Issue HWM: 51

# 📙 일반
## Issue50: 타 prj 선행 (등록: 2026-10-05)
* 목적: 테스트

## Issue51: 타 prj 선행2 (등록: 2026-10-05)
* 목적: 테스트

# ✅ 완료
"""

FAKE_MMDC = r'''#!/usr/bin/env python3
import re, sys
a = sys.argv[1:]
src, dst = a[a.index("-i") + 1], a[a.index("-o") + 1]
mmd = open(src, encoding="utf-8").read()
parts = ['<svg id="my-svg" width="100%" style="max-width: 900px;" viewBox="0 0 900 200" '
         'xmlns="http://www.w3.org/2000/svg"><style>#my-svg .node{fill:#eee}</style>'
         '<g class="nodes">']
for k, m in enumerate(re.finditer(r'^\s+(\w+)\["(.*)"\]\s*$', mmd, re.M)):
    parts.append('<g class="node default" id="flowchart-%s-%d"><foreignObject><div>'
                 '<span class="nodeLabel"><p>%s</p></span></div></foreignObject></g>'
                 % (m.group(1), k, m.group(2)))
parts.append("</g></svg>")
open(dst, "w", encoding="utf-8").write("".join(parts))
'''


def build(issue_md: str):
    """임시 repo·HOME·가짜 mmdc 로 생성기를 돌려 (html, stdout) 을 돌려준다."""
    td = tempfile.TemporaryDirectory()
    tmp = Path(td.name)
    root = tmp / "repo"
    root.mkdir()
    (root / "Issue.md").write_text(issue_md, encoding="utf-8")
    other = tmp / "other"
    other.mkdir()
    (other / "Issue.md").write_text(OTHER_ISSUE_MD, encoding="utf-8")
    projects = tmp / "projects"
    projects.mkdir()
    (projects / "7").write_text(str(other), encoding="utf-8")
    home = tmp / "home"
    (home / ".info").mkdir(parents=True)
    (home / ".info" / "__pmBasePath.txt").write_text(str(projects), encoding="utf-8")
    bindir = tmp / "bin"
    bindir.mkdir()
    fake = bindir / "mmdc"
    fake.write_text(FAKE_MMDC, encoding="utf-8")
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FBOT_", "AOA_"))}
    env["PATH"] = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
    env["HOME"] = str(home)
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=root, env=env,
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        td.cleanup()
        raise RuntimeError(f"생성 실패 rc={r.returncode}\n{r.stderr[-800:]}")
    html_text = (root / "Issue_map.htm").read_text(encoding="utf-8")
    td.cleanup()
    return html_text, r.stdout


def variant(html_text: str, name: str):
    """`<div class="im-v im-body" data-variant="<name>" …>` 블록 본문 (다음 변형 또는 메모 절 전까지)."""
    m = re.search(r'<div class="im-v im-body" data-variant="%s"[^>]*>(.*?)\n</div><!-- /im-body -->'
                  % name, html_text, re.S)
    return m.group(1) if m else None


class WithHeld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html, cls.out = build(ISSUE_MD)
        cls.base = variant(cls.html, "base")
        cls.held = variant(cls.html, "held")

    def test_variants_exist(self):
        self.assertIsNotNone(self.base, "기본 변형 블록 부재")
        self.assertIsNotNone(self.held, "보류 포함 변형 블록 부재")
        self.assertLess(self.html.index('data-variant="base"'),
                        self.html.index('data-variant="held"'), "기본 변형이 먼저 와야 한다")

    def test_held_variant_hidden_by_default(self):
        m = re.search(r'<div class="im-v im-body" data-variant="held"([^>]*)>', self.html)
        self.assertIsNotNone(m)
        self.assertIn("hidden", m.group(1), "포함 변형은 기본 숨김")

    def test_base_excludes_held(self):
        self.assertNotIn("Issue5", self.base, "기본 변형에 보류 이슈가 있으면 안 된다")
        self.assertNotIn("EXT_prj7_Issue50", self.base)

    def test_held_includes_held_issue_node_and_row(self):
        self.assertIn('data-issue="5"', self.held, "보류 이슈 노드·행 부재")
        self.assertIn("flowchart-", self.held)
        self.assertRegex(self.held, r'<tr id="held-issue-5-row"')
        self.assertIn("Issue6", self.held, "선행 없는 보류 이슈도 포함")

    def test_held_includes_cross_prj_dep(self):
        self.assertIn("EXT_prj7_Issue50", self.held, "보류 이슈의 타 prj 선행 노드 부재")
        cross = self.held[self.held.index("타 프로젝트 연동"):]
        self.assertIn("prj7#Issue50", cross, "타 prj 연동 표에 보류 이슈 선행 부재")

    def test_cancelled_stays_excluded(self):
        self.assertNotIn("Issue8", self.held)
        self.assertNotIn("prj7#Issue51", self.held)

    def test_markers_only_once(self):
        for mk in ("GRAPH", "CRITICAL", "CROSS", "TABLE", "PENDING", "TRIGGER"):
            self.assertEqual(self.html.count(f"<!-- ISSUE-MAP:{mk}:START -->"), 1, mk)
        g = re.search(r"<!-- ISSUE-MAP:GRAPH:START -->(.*?)<!-- ISSUE-MAP:GRAPH:END -->",
                      self.html, re.S)
        self.assertIn("<svg", g.group(1))                        # hub 판정 불변
        self.assertNotIn("Issue5", g.group(1))                   # 마커 블록 = 기본 변형

    def test_held_svg_id_renamed(self):
        self.assertNotIn('id="my-svg"', self.held, "포함 변형 SVG id 가 기본과 겹친다")
        self.assertNotIn("#my-svg ", self.held, "포함 변형 SVG 내부 선택자도 바꿔야 한다")

    def test_anchor_ids_unique(self):
        ids = Counter(re.findall(r'\sid="((?:held-)?issue-[^"]+)"', self.html))
        dup = [k for k, v in ids.items() if v > 1]
        self.assertEqual(dup, [], f"앵커 id 중복: {dup}")

    def test_toggle_button(self):
        hdr = self.html[self.html.index("<header>"):self.html.index("</header>")]
        m = re.search(r'<button[^>]*class="held-toggle"[^>]*>', hdr)
        self.assertIsNotNone(m, "헤더 토글 버튼 부재")
        self.assertIn('aria-pressed="false"', m.group(0), "기본값은 미포함")
        self.assertNotIn("disabled", m.group(0))

    def test_toggle_persists(self):
        self.assertIn("localStorage", self.html)
        self.assertIn("issueMap.includeHeld", self.html)
        m = re.search(r"<script>[^<]*issueMap\.includeHeld.*?</script>", self.html, re.S)
        self.assertIsNotNone(m)
        self.assertIn("try", m.group(0), "저장소 접근은 try/catch 로 감싼다")

    def test_deeplink_scoped_to_visible_variant(self):
        m = re.search(r"function land\(\)(.*?)\n  \}", self.html, re.S)
        self.assertIsNotNone(m)
        self.assertIn("held-", m.group(1), "딥링크가 보이는 변형의 앵커를 찾아야 한다")

    def test_inline_scripts_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 없음")
        scripts = re.findall(r"<script>(.*?)</script>", self.html, re.S)
        with tempfile.TemporaryDirectory() as t:
            for i, src in enumerate(scripts):
                fp = Path(t) / f"s{i}.js"
                fp.write_text(src, encoding="utf-8")
                r = subprocess.run([node, "--check", str(fp)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"script {i} 구문 오류: {r.stderr[:400]}")


class NoHeld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html, _ = build(ISSUE_MD_NO_HELD)

    def test_no_held_variant(self):
        self.assertIsNone(variant(self.html, "held"), "보류 0건이면 포함 변형을 만들지 않는다")
        self.assertIsNotNone(variant(self.html, "base"))

    def test_button_disabled(self):
        hdr = self.html[self.html.index("<header>"):self.html.index("</header>")]
        m = re.search(r'<button[^>]*class="held-toggle"[^>]*>', hdr)
        self.assertIsNotNone(m)
        self.assertIn("disabled", m.group(0))


if __name__ == "__main__":
    unittest.main(verbosity=1)
