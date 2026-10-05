#!/usr/bin/env python3
"""test_tagcheck_sync_dest_issue566.py — tagcheck 가 동기 산출물 전체를 같은 기준으로 제외하는가 (Issue566)

precommit-tagcheck.py 는 번들(`plugins/`)을 «동기 산출물 — 태그 저작처는 원본» 이유로 검사에서
뺀다(Issue364). 그런데 같은 동기 스크립트가 쓰는 또 하나의 목적지 `mcp/<유닛>/`
(`sync_mcp_unit`, prj3#Issue436_3)는 빠져 있어, prj3 사본을 싣는 동기 커밋이 prj3 번호 때문에
구조적으로 막혔다(2026-09-28 Issue566 커밋 실발생 — `mcp/aoa-mq/test-aoa-mq-confirm-gate.sh:37`).

판정은 동기 스크립트의 선언(`sync_mcp_unit <유닛>`)에서 파생한다 — 목록을 두 곳에 두면 또 갈라진다.
prj1 이 직접 저작하는 `mcp/server.py`(fpm MCP)는 계속 검사한다.

실행: python3 scripts/test_tagcheck_sync_dest_issue566.py
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('tagcheck', os.path.join(REPO, 'scripts', 'precommit-tagcheck.py'))
tc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tc)

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f'  ok   {name}')
    else:
        FAIL += 1
        print(f'  FAIL {name} (want={want!r} got={got!r})')


print('[test_tagcheck_sync_dest_issue566]')
units = tc.sync_mcp_units(REPO) if hasattr(tc, 'sync_mcp_units') else None
check('동기 스크립트에서 mcp 유닛 목록을 읽는다(공허하지 않음)', bool(units) and 'aoa-mq' in units and 'aoa-memory' in units, True)
check('mcp/aoa-mq 사본은 검사 제외', tc.is_checked('mcp/aoa-mq/test-aoa-mq-confirm-gate.sh'), False)
check('mcp/aoa-memory 사본은 검사 제외', tc.is_checked('mcp/aoa-memory/store.py'), False)
check('prj1 저작 mcp/server.py 는 계속 검사', tc.is_checked('mcp/server.py'), True)
check('유닛 이름 접두만 같은 경로는 제외하지 않는다', tc.is_checked('mcp/aoa-mq-extra/x.py'), True)
check('기존 번들 제외는 유지', tc.is_checked('plugins/fpm-core/hooks/x.sh'), False)
check('일반 코드는 계속 검사', tc.is_checked('scripts/fpm-bundle-sync.sh'), True)

# Issue591: 세 번째 동기 목적지 — flat_file 배포 사본(`sh/scar-flatfile-sync.sh`, prj3 룰·커맨드 사본).
#   prj3 번호를 그대로 싣는 재생성 커밋이 tagcheck 에 구조적으로 막혔다(2026-10-03 실발생 14건).
#   경로는 scar-manifest.yml `payloads.flat_file.src_rel_repo` 에서 파생한다.
flat = tc.flatfile_prefix(REPO) if hasattr(tc, 'flatfile_prefix') else None
check('매니페스트에서 flat_file 사본 경로를 읽는다', flat, 'data/claude_forNewServer/')
check('flat_file 사본은 검사 제외', tc.is_checked('data/claude_forNewServer/rules/issue-g.md'), False)
check('flat_file 접두만 같은 경로는 제외하지 않는다', tc.is_checked('data/claude_forNewServer.md'), True)
check('매니페스트 자체는 계속 검사', tc.is_checked('data/scar-manifest.yml'), True)

print(f'\n결과: PASS {PASS} / FAIL {FAIL}')
sys.exit(1 if FAIL else 0)
