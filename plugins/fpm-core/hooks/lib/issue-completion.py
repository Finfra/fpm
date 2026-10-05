#!/usr/bin/env python3
"""issue-completion.py — «이 이슈는 완료인가» 판정 단일 지점 (prj3#Issue944)

⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): 본 파일은 모든 프로젝트가 공유. cwd ≠ ~/.claude 면
  즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT: ~/.claude/_doc_arch/fbot-arch.md
  «완료 판정 단위» · ~/.claude/_doc_arch/issue-concurrency.md «완료 표기 경고» · 절차: ~/.claude/rules/global-scar-change-rules.md

소비처 — 규칙을 복제하지 않고 이 모듈을 불러 쓴다:
  * `hooks/fbot-lead.py` — sweep·회수의 배분 완료 판정(`issue_completed_in` 을 그 이름 그대로 다시 내보낸다)
  * `sh/issue-tx.py` — `move --to 완료`·`commit --issues` 의 완료 표기 경고(`done_unmarked`)
종전엔 fbot-lead 안에 있었다. issue-tx 가 같은 판정으로 «완료 섹션에 옮겼는데 sweep 이 못 보는 블록» 을 알리도록
뽑았다 — fbot-lead 를 통째로 import 하면 4.6k 줄 CLI(타 세션이 상시 고치는 파일)에 이슈 트랜잭션 도구가 묶인다.

⚠️ 같은 규칙의 zsh 판 `~/.bin/fpm-do` `is_completed` 가 따로 있다(언어가 달라 공유 불가). 둘의 일치는
[test-issue-completion-contract.py](../test-issue-completion-contract.py) 가 사례표로 지킨다 — 여기를 고치면 그쪽도.
"""
import os
import re

# 해시 기록 표기 — `~/.bin/fpm-do` 의 `HASH_RE` 와 **같은 식**이어야 한다(prj3#Issue693_2).
#   `commit: `abc1234`` (헤더 관행) · `* Hash: abc1234` (양식 SSOT 본문). 대소문자 무시.
# 🔧 prj3#Issue790 — `<repo>:<hash>` 접두를 선택적으로 인정한다(prj16 `public-path-rules.md` 규약
#   `commit: public:45688ee`). ⚠️ 2026-09-29 현재 `~/.bin/fpm-do` `HASH_RE` 는 **아직 접두를 모른다**
#   (별도 repo `~/.bin` — 방침 상신 대기, 경위는 prj3#Issue790 상세). 그쪽이 따라올 때까지 접두 해시는 두 식이 갈린다.
ISSUE_HASH_RE = re.compile(r"(commit|hash):[ \t]*`?(?:[a-z0-9_-]+:)?[a-f0-9]{7,40}", re.I)

# 헤더 완료 신호 — `✅`(prj3 관행) · `완료:`(prj82 등) · `해결:`(prj3 관행) · `commit:`(해시 기록·«commit: 없음 — 사유»)
DONE_SIGNALS = ("✅", "완료:", "해결:", "commit:")

# 블록 경계 = 다음 이슈 헤더(서브 `### Issue<N>_<M>` 포함) — fpm-do 와 같다
_ISSUE_HEAD_RE = re.compile(r"^#{2,}\s+Issue")


def is_done_section(line: str) -> bool:
    """최상위 `# ` 헤딩이고 «완료» 를 담는가 — `# ✅ 완료`·`# 🏁 완료-해결순` 둘 다. 보류·취소·참고는 안 걸린다.
    완료 섹션명은 프로젝트마다 달라 정확 일치가 아니라 포함으로 본다."""
    return line.startswith("# ") and "완료" in line


def done_block(lines, issue: str):
    """완료 섹션 안의 그 이슈 블록(헤더 줄 포함 줄 목록) — 완료 섹션에 없으면 None.

    ``lines`` 는 개행을 떼었든(`split("\\n")`) 붙였든(`splitlines(keepends=True)`) 같다.
    `##`·`###` 둘 다 받는다 — 서브 이슈(`### Issue<N>_<M>:`)가 그 깊이를 쓴다. 블록은 다음 이슈 헤더에서 끝나므로
    서브의 해시가 부모 완료로 번지지 않는다."""
    head_re = re.compile(r"^#{2,}\s+" + re.escape(issue) + r":")
    in_done, block = False, None
    for ln in lines:
        if ln.startswith("# "):
            if block is not None:
                break
            in_done = is_done_section(ln)
            continue
        if not in_done:
            continue
        if _ISSUE_HEAD_RE.match(ln):
            if block is not None:
                break
            if head_re.match(ln):
                block = [ln]
            continue
        if block is not None:
            block.append(ln)
    return block


def block_completed(block) -> bool:
    """블록이 완료 신호를 달고 있는가 — 헤더에 `DONE_SIGNALS` 중 하나, 없으면 블록 어디든 `ISSUE_HASH_RE`.

    🔧 prj3#Issue693_2 — 헤더에 신호가 없어도 **블록에 해시가 기록**돼 있으면 완료다. 양식 SSOT
      (`___pm/data/template/Issue.md` «완료 형태»)는 헤더를 `(등록: …)` 만 두고 본문에 `* Hash: {commit-hash}` 를 적는다."""
    if not block:
        return False
    if any(t in block[0] for t in DONE_SIGNALS):
        return True
    return any(ISSUE_HASH_RE.search(ln) for ln in block)


def completed_in_lines(lines, issue: str) -> bool:
    """그 이슈가 완료 섹션에 있고 완료 신호를 달고 있는가 (prj3#Issue644 ⑥)."""
    block = done_block(lines, issue)
    return block is not None and block_completed(block)


def done_unmarked(lines, issue: str) -> bool:
    """완료 섹션에 있는데 완료 판정을 통과하지 못하는가 — 종결 때 제목 표기를 빠뜨린 블록 (prj3#Issue944).

    sweep 은 이 블록을 영원히 미완료로 읽는다. 완료 섹션 밖·부재는 거짓(경고 대상이 아니다)."""
    block = done_block(lines, issue)
    return block is not None and not block_completed(block)


def issue_completed_in(cwd: str, issue: str):
    """그 이슈가 대상 repo(``cwd``)의 **완료 섹션**에 있고 완료 신호를 달고 있는가 (prj3#Issue644 ⑥).

    3-state — True=완료 · False=미완료 · None=**판정 불가**(Issue.md 접근 불가).
    판정 규칙은 `~/.bin/fpm-do` 의 `completed_block`/`is_completed` 와 **같은 것**이다 — 둘이 갈리면
    "위임은 완료로 보는데 원장은 아니다" 같은 어긋남이 생긴다.
    """
    if not cwd or not issue:
        return None
    path = os.path.join(os.path.expanduser(cwd), "Issue.md")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        return None                      # 부재·권한 — **미완료로 단정하지 않는다**(부재와 미감지를 구별)
    return completed_in_lines(lines, issue)
