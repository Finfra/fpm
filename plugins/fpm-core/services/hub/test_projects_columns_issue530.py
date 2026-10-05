#!/usr/bin/env python3
# test_projects_columns_issue530.py — Issue530 회귀 테스트 (Projects.md 컬럼 삽입 시 color·emoji 밀림)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). Projects.md 에 `tdd` 컬럼이 이모지 앞에 끼자
#   위치 인덱스로 읽던 로더가 한 칸씩 밀려 color 가 비고(→ 진한 hsl fallback) 이모지 자리에
#   tdd 상태가 뜨던 결함 검증. 헤더 기반 파싱이면 컬럼이 늘어도 무손상이어야 한다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_projects_columns_issue530.py
import os
import sys
import tempfile

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


def _load(table: str):
    tmp = tempfile.mkdtemp(prefix="___pm-issue530-")
    server.PROJECTS_MD = os.path.join(tmp, "Projects.md")
    with open(server.PROJECTS_MD, "w", encoding="utf-8") as f:
        f.write(table)
    server._projects_list_cache = []
    server._projects_list_cache_mtime = 0.0
    server._projects_emoji_cache = {}
    server._projects_emoji_cache_mtime = 0.0
    server._projects_color_cache = {}
    server._projects_color_cache_mtime = 0.0


# A. 현행 표 — tdd 컬럼이 이모지 앞에 있다
_load(
    "| id  | 프로젝트명 | 한국어명칭 | Dmn | 경로 | 설명 | tdd  | 이모지 | color   |\n"
    "| --- | :--------- | ---------- | :-- | :--- | :--- | :--: | :----- | :------ |\n"
    "| 2   | obsidian   | 옵시디언   | g   | `/tmp/i530/doc` | 문서 | 🆕 | 💜 | #cfedd9 |\n"
    "| 9a  | sub        | 하위       | g   | `/tmp/i530/sub` | 하위 | ➖ | 🔬 | #92dab6 |\n"
)
rows = {r["id"]: r for r in server._load_projects_list()}
check("A1 color 는 color 컬럼에서", rows.get("2", {}).get("color") == "#cfedd9")
check("A2 emoji 는 이모지 컬럼에서(tdd 아님)", rows.get("2", {}).get("emoji") == "💜")
check("A3 name·path 유지", rows.get("2", {}).get("name") == "obsidian"
      and rows.get("2", {}).get("path") == "/tmp/i530/doc")
check("A4 접미 id(9a) 행도 파싱", rows.get("9a", {}).get("color") == "#92dab6")
check("A5 _load_projects_emojis 도 헤더 기반", server._load_projects_emojis().get("/tmp/i530/doc") == "💜")
meta = server.project_meta("/tmp/i530/doc")
check("A6 project_meta 가 hsl fallback 이 아닌 peacock color", meta["color"] == "#cfedd9")

# B. 구 8컬럼 표(헤더 명칭이 달라도) — 위치 fallback 으로 기존 동작 유지
_load(
    "| No | Name | S | Domain | Path | Desc | Emoji | Color |\n"
    "| 1 | legacy | - | g | /tmp/i530/legacy | 테스트 | 🎮 | #aabbcc |\n"
)
rows = {r["id"]: r for r in server._load_projects_list()}
check("B1 구 표 color", rows.get("1", {}).get("color") == "#aabbcc")
check("B2 구 표 emoji", rows.get("1", {}).get("emoji") == "🎮")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
