#!/usr/bin/env python3
"""이슈맵 관계도 확대·축소·이동 회귀 테스트 (prj3#Issue828).

재생목록 id: `issue-map-zoom` (prj3 `tdd/playlist.md`).

왜: 노드가 많은 prj 의 «전체 의존 관계» SVG 는 자연 폭이 화면의 몇 배라 `max-width:100%` 로
  눌려 글자가 점 크기가 된다. 되돌릴 수단이 없었다 — 확대 상자로 감싸 사용자가 키우고 이동한다.

검증 축:
  1. `fit_svg` 가 자연 폭을 `data-natural-w` 로 남긴다(Issue251 과확대 방지 캡은 유지)
  2. 관계도·임계 경로 SVG 가 확대 상자(`.zoom-box` > 도구 막대 + `.zoom-vp`)에 들어간다
  3. hub 판정 불변 — `ISSUE-MAP:GRAPH` 블록 안에 `<svg` 가 그대로 있다
  4. 도구 막대 조작 5종(`out`·`in`·`fit`·`1`·`full`) · 확대 스크립트 존재
  5. 딥링크 착지가 확대 훅(`__issueMapZoom`)을 부른다 — 노드로 가기 전에 읽을 수 있는 배율로
  6. 인라인 스크립트 전부 `node --check` 통과 (구문 오류 한 개면 확대·딥링크가 같이 죽는다)

mmdc 는 가짜 실행체로 대체한다(PATH 선두) — 넓은 그래프(자연 폭 3000px)를 흉내 낸다.

실행:
    python3 ~/.claude/skills/issue-map/tests/test-zoom.py
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
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

# 넓은 그래프를 흉내 내는 가짜 mmdc — 자연 폭 3000px, 노드 마크업은 실 mermaid 형식
FAKE_MMDC = r'''#!/usr/bin/env python3
import re, sys
a = sys.argv[1:]
src, dst = a[a.index("-i") + 1], a[a.index("-o") + 1]
mmd = open(src, encoding="utf-8").read()
parts = ['<svg id="my-svg" width="100%" style="max-width: 3000px;" viewBox="0 0 3000 200" '
         'xmlns="http://www.w3.org/2000/svg"><g class="nodes">']
for k, m in enumerate(re.finditer(r'^\s+(\w+)\["(.*)"\]\s*$', mmd, re.M)):
    parts.append('<g class="node default" id="flowchart-%s-%d"><foreignObject><div>'
                 '<span class="nodeLabel"><p>%s</p></span></div></foreignObject></g>'
                 % (m.group(1), k, m.group(2)))
parts.append("</g></svg>")
open(dst, "w", encoding="utf-8").write("".join(parts))
'''


def load_module():
    spec = importlib.util.spec_from_file_location("build_issue_map_zoom", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FitSvg(unittest.TestCase):
    def test_natural_width_kept_and_cap_unchanged(self):
        mod = load_module()
        out = mod.fit_svg('<svg id="my-svg" width="100%" style="max-width: 3000px;" '
                          'viewBox="0 0 3000 200"><g></g></svg>')
        head = out[:out.index(">")]
        self.assertIn('data-natural-w="3000"', head)
        self.assertIn("max-width:min(100%, 3000px)", head)      # Issue251 캡 유지
        self.assertEqual(head.count("style="), 1)                # style 이중 금지(Issue251)

    def test_natural_width_from_viewbox_when_no_max_width(self):
        mod = load_module()
        out = mod.fit_svg('<svg viewBox="0 0 812.5 90"><g></g></svg>')
        self.assertIn('data-natural-w="812.5"', out[:out.index(">")])


class BuiltHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        tmp = Path(cls._td.name)
        root = tmp / "repo"
        root.mkdir()
        (root / "Issue.md").write_text(ISSUE_MD, encoding="utf-8")
        bindir = tmp / "bin"
        bindir.mkdir()
        fake = bindir / "mmdc"
        fake.write_text(FAKE_MMDC, encoding="utf-8")
        fake.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("FBOT_", "AOA_"))}
        env["PATH"] = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
        r = subprocess.run([sys.executable, str(SCRIPT), "--no-cross"], cwd=root, env=env,
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"생성 실패 rc={r.returncode}\n{r.stderr[-800:]}")
        cls.html = (root / "Issue_map.htm").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def graph_block(self):
        m = re.search(r"<!-- ISSUE-MAP:GRAPH:START -->(.*?)<!-- ISSUE-MAP:GRAPH:END -->",
                      self.html, re.S)
        self.assertIsNotNone(m, "GRAPH 블록 부재")
        return m.group(1)

    def critical_block(self):
        m = re.search(r"<!-- ISSUE-MAP:CRITICAL:START -->(.*?)<!-- ISSUE-MAP:CRITICAL:END -->",
                      self.html, re.S)
        self.assertIsNotNone(m, "CRITICAL 블록 부재")
        return m.group(1)

    def test_graph_svg_in_zoom_box(self):
        g = self.graph_block()
        self.assertIn('class="zoom-box"', g)
        self.assertIn('class="zoom-vp"', g)
        vp = g[g.index('class="zoom-vp"'):]
        self.assertIn("<svg", vp, "SVG 가 뷰포트 안에 있어야 한다")

    def test_hub_graph_judgement_unchanged(self):
        self.assertIn("<svg", self.graph_block())                 # server `_issue_map_has_graph`

    def test_critical_svg_in_zoom_box(self):
        c = self.critical_block()
        self.assertIn('class="zoom-box"', c)
        self.assertIn("<svg", c[c.index('class="zoom-vp"'):])

    def test_toolbar_actions(self):
        g = self.graph_block()
        for act in ("out", "in", "fit", "1", "full"):
            self.assertIn(f'data-zoom="{act}"', g, f"도구 막대 {act} 부재")

    def test_natural_width_on_embedded_svg(self):
        self.assertRegex(self.graph_block(), r'<svg[^>]*data-natural-w="3000"')

    def test_zoom_script_present(self):
        self.assertIn("__issueMapZoom", self.html)
        self.assertIn("ctrlKey", self.html)                       # Ctrl/⌘+휠(핀치) 확대

    def test_deeplink_calls_zoom_hook(self):
        m = re.search(r"function land\(\)(.*?)\n  \}", self.html, re.S)
        self.assertIsNotNone(m, "딥링크 land() 부재")
        self.assertIn("__issueMapZoom", m.group(1), "착지 시 확대 훅을 불러야 한다")

    def test_inline_scripts_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 없음")
        scripts = re.findall(r"<script>(.*?)</script>", self.html, re.S)
        self.assertTrue(scripts)
        with tempfile.TemporaryDirectory() as t:
            for i, src in enumerate(scripts):
                fp = Path(t) / f"s{i}.js"
                fp.write_text(src, encoding="utf-8")
                r = subprocess.run([node, "--check", str(fp)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"script {i} 구문 오류: {r.stderr[:400]}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
