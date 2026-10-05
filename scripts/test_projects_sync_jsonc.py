#!/usr/bin/env python3
# test_projects_sync_jsonc.py — Issue520 회귀 테스트 (tdd playlist #9 projects-sync-jsonc)
#
# sh/fpm-projects-sync 가 VSCode settings.json(JSONC)을
#   ① 주석·trailing comma 가 있어도 파싱하고
#   ② 문자열 안의 `//`(URL 등)를 주석으로 오인하지 않으며
#   ③ 주석을 그대로 둔 채 peacock.color 값만 교체하고
#   ④ skip 사유를 [2/4] 요약 **뒤에** 다시 출력하는지 검증한다.
#
#   배경: 표준 json 파서가 주석 한 줄에 그 프로젝트를 통째로 skip 해 prj0(홈) 색 동기화가
#   조용히 끊겼다. skip 로그는 중간에 흘러 뒤 단계 출력에 묻혔다.
#
#   격리: FPM_BASE·대상 프로젝트 전부 임시 폴더. 실제 Projects.md·.vscode 무접촉.
#   [2/4] update_editors() 만 직접 부른다 — iterm·identity 단계는 사용자 환경을 건드린다.
#
# 실행: python3 scripts/test_projects_sync_jsonc.py
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="projects-sync-jsonc-")
os.environ["FPM_BASE"] = TMP  # 모듈 상수(PM_ROOT 등)가 import 시점에 고정된다

_loader = importlib.machinery.SourceFileLoader("fpm_projects_sync",
                                               os.path.join(REPO, "sh", "fpm-projects-sync"))
_spec = importlib.util.spec_from_loader("fpm_projects_sync", _loader)
sync = importlib.util.module_from_spec(_spec)
_loader.exec_module(sync)
sync.target_editors = lambda: ["vscode"]  # data/editor.yml 무관하게 VSCode 만

PASS = 0
FAIL = 0
NEW = "#aabbcc"

JSONC = """{
  // 홈 폴더 설정 — 이 주석이 있으면 종전 파서는 이 파일을 통째로 skip 했다
  "editor.fontSize": 13,
  /* 블록 주석도 JSONC 정상 문법 */
  "remote.url": "http://example.com//path",  // 문자열 안 // 는 주석이 아니다
  "peacock.color": "#112233",
  "workbench.colorCustomizations": {
    "titleBar.activeBackground": "#112233",
  },
}
"""


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _mk_project(name, body):
    d = os.path.join(TMP, name)
    os.makedirs(os.path.join(d, ".vscode"))
    p = os.path.join(d, ".vscode", "settings.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return d, p


def main():
    print("[test_projects_sync_jsonc]")
    good_dir, good = _mk_project("jsonc", JSONC)
    bad_dir, bad = _mk_project("broken", '{ "a": 1, "b": }\n')

    data, ok, raw, blanked = sync._load_jsonc(good)
    check("① 주석·trailing comma 포함 JSONC 파싱 성공", ok, f"data={data}")
    check("② 문자열 안 // 보존", data.get("remote.url") == "http://example.com//path",
          f"got={data.get('remote.url')!r}")

    rows = [
        {"id": "1", "path": good_dir, "color": NEW, "emoji": ""},
        {"id": "2", "path": bad_dir, "color": NEW, "emoji": ""},
    ]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        sync.update_editors(rows)
    log = out.getvalue()

    after = open(good, encoding="utf-8").read()
    check("③ 줄 주석 보존", "// 홈 폴더 설정" in after)
    check("③ 블록 주석 보존", "/* 블록 주석도 JSONC 정상 문법 */" in after)
    check("③ 문자열 뒤 인라인 주석 보존", "// 문자열 안 // 는 주석이 아니다" in after)
    check("③ URL 값 무손상", '"http://example.com//path"' in after)
    check("③ peacock.color 만 새 값으로 교체", f'"peacock.color": "{NEW}"' in after
          and '"peacock.color": "#112233"' not in after)
    data2, ok2, _, _ = sync._load_jsonc(good)
    check("③ 교체 후에도 JSONC 로 유효", ok2 and data2.get("peacock.color") == NEW)
    check("③ 무관 키 보존", data2.get("editor.fontSize") == 13)
    check("주석 보존 경로(재작성 고지 없음)", "주석 보존 실패" not in log, log)

    lines = log.splitlines()
    summary = next((i for i, l in enumerate(lines) if l.startswith("[2/4]")), -1)
    warn = next((i for i, l in enumerate(lines) if bad in l), -1)
    check("④ 파싱 불가 파일 skip 카운트 1", "파싱skip 1" in log, log)
    check("④ skip 사유가 [2/4] 요약 뒤에 재출력", summary >= 0 and warn > summary,
          f"summary={summary} warn={warn}\n{log}")
    check("④ 망가진 파일은 건드리지 않는다",
          open(bad, encoding="utf-8").read() == '{ "a": 1, "b": }\n')

    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
