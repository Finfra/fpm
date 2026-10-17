#!/usr/bin/env python3
"""이슈맵 영숫자 prj id(`9t`·`42a`) 해석 회귀 테스트 (prj3#Issue1099).

재생목록 id: `issue-map-alnum-prj` (prj3 `tdd/playlist.md`).

왜: `_load_projects` 가 `f.name.isdigit()` 로 `~/_git/___pm/projects/9t` 를 건너뛰어
  `prj9t#Issue3` 이 «prj 매핑 없음» 미확인으로 표시됐다(prj7 `--check` 미확인 4건 중 3건, 2026-10-14).
  prj id 판정 단일 지점은 `hooks/lib/fbot-prj.py`(Issue1061) — 이 스킬도 그것을 거친다.

검증 축:
  1. `_load_projects` 가 `9t`·`42a` 를 싣고 `_hq`·`README.md` 는 거른다
  2. `PRJ_REF_RE` 가 `prj9t`·`prj42a` 를 규약 참조로 본다(경고 없음)
  3. `CrossResolver.resolve("prj9t")` 가 경로를 낸다
  4. 배분 접두 `prj9t#Issue3` 를 (`9t`, `Issue3`, 명시) 로 읽는다 · `payload.prj="9t"` 도 읽는다
  5. 숫자 prj 는 종전대로 int(`prj7#Issue2` → 7)

실행:
    python3 ~/.claude/skills/issue-map/tests/test-alnum-prj.py
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "build_issue_map.py"


def load():
    spec = importlib.util.spec_from_file_location("build_issue_map_alnum", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AlnumPrj(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.pdir = t / "projects"
        cls.pdir.mkdir()
        for name in ("7", "9t", "42a"):
            d = t / f"repo{name}"
            d.mkdir()
            (cls.pdir / name).write_text(str(d) + "\n")
        (cls.pdir / "_hq").write_text(str(t) + "\n")
        (cls.pdir / "README.md").write_text("x\n")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_load_projects_alnum(self):
        out = self.m.CrossResolver._load_projects(self.pdir)
        for k in ("prj7", "prj9t", "prj42a"):
            self.assertIn(k, out)
        self.assertNotIn("prj_hq", out)
        self.assertNotIn("prjREADME.md", out)

    def test_ref_re(self):
        for ok in ("prj7", "prj9t", "prj42a"):
            self.assertTrue(self.m.PRJ_REF_RE.match(ok), ok)
        for ng in ("prj", "prjx", "___pm"):
            self.assertFalse(self.m.PRJ_REF_RE.match(ng), ng)

    def test_resolve(self):
        old = self.m.resolve_projects_dir
        self.m.resolve_projects_dir = lambda: self.pdir
        try:
            r = self.m.CrossResolver(Path(self.tmp.name), enabled=True)
            self.assertEqual(r.resolve("prj9t"), Path(self.tmp.name) / "repo9t")
        finally:
            self.m.resolve_projects_dir = old

    def test_dispatch_ref(self):
        self.assertEqual(self.m._dispatch_ref("prj9t#Issue3", None), ("9t", "Issue3", True))
        self.assertEqual(self.m._dispatch_ref("Issue3", "9t"), ("9t", "Issue3", False))
        self.assertEqual(self.m._dispatch_ref("prj7#Issue2", None), (7, "Issue2", True))
        self.assertEqual(self.m._dispatch_ref("Issue2", "prj7"), (7, "Issue2", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
