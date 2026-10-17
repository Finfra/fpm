#!/usr/bin/env python3
"""lib/fbot-prj.py — prj 식별자 판정 단일 지점 (prj3#Issue1061)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

___pm 의 prj id 는 숫자만이 아니다 — `projects/9t`(fTyping)·`9a`·`42a`·`58a`·`61a` 처럼 **숫자 + 영소문자 접미**가
정식 id 다(prj1#Issue303 `/open-prj` 가 이미 받는다). 핀봇 도구는 `--prj type=int`·`isdigit()`·`int(prj)` 를
파일마다 따로 두어 접미 id 를 거부하거나 조용히 버렸다(fTyping 에 팀장을 둘 수 없었다 — Issue1061 실측).

판정 한 줄: **숫자는 int, 접미 id 는 소문자 str, 그 외는 prj 가 아니다.**
  · 숫자를 int 로 두는 이유 — 원장(`bot.prj`)·JSON 출력·hub 소비처가 숫자 prj 를 int 로 읽는다(종전 형태 유지)
  · 원장 열은 `ANY`(fbot-state `_ensure_bot_prj_any`) — STRICT `ANY` 는 형 변환을 하지 않으므로
    쓰는 쪽과 찾는 쪽이 **반드시 이 함수를 거쳐야** `9` 와 `"9"` 가 갈리지 않는다
  · 경로·파일명(`org/{prj}.yml`·`projects/{prj}`)에 들어가므로 `/`·`.` 은 형식에서 원천 거부된다

`hooks/lib/` 에 두는 이유 — prj1 번들 동기(`fpm-bundle-sync.sh` Issue561)가 편입된 훅의 `lib/<x>` 참조를 자동 동반한다.
훅 옆(`hooks/`)에 두면 «신규 편입은 수동» 원칙에 걸려 번들 훅만 새 판으로 올라가고 이 파일은 빠진다.

소비처는 importlib 로 싣는다(hooks 관행 — 하이픈 파일명):
    spec = importlib.util.spec_from_file_location("fbot_prj", os.path.join(HERE, "lib/fbot-prj.py"))
"""
import argparse
import re

PRJ_TOKEN = r"\d+(?:[a-z][a-z0-9]*)?"           # 정규식 조각 — `prj{PRJ_TOKEN}#` 등 이슈 표기에 끼워 쓴다
PRJ_RE = re.compile(rf"^{PRJ_TOKEN}$")


def norm_prj(v):
    """prj 값 정규화 — None·"" → None · 숫자(int 또는 숫자 문자열) → int · 접미 id → 소문자 str.
    형식 밖이면 ValueError (bool 도 거부 — int 의 하위형이라 조용히 0·1 이 된다)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        raise ValueError(f"prj 형식 아님: {v!r}")
    if isinstance(v, int):
        if v < 0:
            raise ValueError(f"prj 형식 아님: {v!r}")
        return v
    s = str(v).strip().lower()
    if s.startswith("prj"):
        s = s[3:]
    if not PRJ_RE.match(s):
        raise ValueError(f"prj 형식 아님: {v!r} (숫자 또는 숫자+영소문자 접미 — ex) 42·9t)")
    return int(s) if s.isdigit() else s


def try_prj(v):
    """`norm_prj` 의 관대판 — 형식 밖은 None(판정 불가를 «prj 없음» 으로 읽는 fail-soft 자리용)."""
    try:
        return norm_prj(v)
    except (TypeError, ValueError):
        return None


def is_prj_name(name) -> bool:
    """파일·폴더 이름이 prj id 인가 — `_hq`·`_template`·README 등을 거른다(종전 `name.isdigit()` 자리)."""
    return isinstance(name, str) and bool(PRJ_RE.match(name))


def prj_arg(v):
    """argparse `type=` — 형식 밖은 사용법 오류(rc 2)로 거부한다(종전 `type=int` 와 같은 자리)."""
    try:
        return norm_prj(v)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def prj_sort_key(v):
    """숫자·접미 혼재 정렬 — `3 < 9 < 9a < 9t < 10`. 숫자부 → 접미 순(접미 없는 쪽이 먼저)."""
    s = str(v)
    m = re.match(r"^(\d+)(.*)$", s)
    return (int(m.group(1)), m.group(2)) if m else (float("inf"), s)
