#!/usr/bin/env python3
"""homunculus 관측 파일 → learn.observation 배치 적재기 (prj5 Issue69 A-2)

⚠️ 이 파일의 지위 — **참조 구현이자 실행 가능한 계약서**

적재 어댑터의 소유는 prj3 다([`learn-ingest.py`](~/.claude/skills/continuous-learning-v2/scripts/learn-ingest.py)
의 `ingest_observations()`). 그런데 그쪽은 *"prj5 가 관측 적재 도구를 안 냈다"* 는 이유로
계수만 하고 있었다. 그래서 prj5 가 낸 API 를 **실제로 호출해 보이는 쪽**을 함께 둔다:

  * prj3 어댑터는 이 파일의 `ingest_file()` 을 그대로 옮기거나 import 하면 된다
  * 무엇보다 **이것이 없으면 A 를 검증할 수 없다** — 도구만 만들고 한 번도 안 흘려보낸 채
    "됐다"고 보고하는 것이 정확히 Issue68 이 남긴 상태였다

경로 정본은 여전히 파일이다. 여기서는 **읽기만** 하며 원본을 지우거나 옮기지 않는다.

    python3 mcp/aoa-memory/ingest_obs.py --dry-run       # 세어만 본다
    python3 mcp/aoa-memory/ingest_obs.py --limit 5       # 최근 5파일
    python3 mcp/aoa-memory/ingest_obs.py                 # 전량
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as SV     # noqa: E402
import store as S       # noqa: E402

HOME = os.path.expanduser("~")
DEFAULT_ROOT = os.path.join(HOME, ".claude", "homunculus", "projects")

# 활성 파일도 넣는다 — append-only 라 줄번호 자연키가 안정적이고(store.observation_id),
# 회전을 기다리면 최근 관측이 최장 수개월 늦게 들어온다(실측 기록 지연 최대 87.9일).
PATTERNS = ("observations.jsonl", "observations.archive")


def find_files(root):
    """(mtime, path) 목록. 최근 것이 앞에 오게 정렬한다."""
    out = []
    if not os.path.isdir(root):
        return out
    for proj in sorted(os.listdir(root)):
        pdir = os.path.join(root, proj)
        if not os.path.isdir(pdir):
            continue
        active = os.path.join(pdir, "observations.jsonl")
        if os.path.isfile(active):
            out.append((os.path.getmtime(active), active))
        adir = os.path.join(pdir, "observations.archive")
        if os.path.isdir(adir):
            for fn in sorted(os.listdir(adir)):
                if fn.endswith(".jsonl"):
                    p = os.path.join(adir, fn)
                    out.append((os.path.getmtime(p), p))
    out.sort(reverse=True)
    return out


def read_records(path):
    """(레코드, 줄번호) 를 돌려준다. 줄번호는 **1-based 파일 줄번호** 로 자연키의 절반이다.

    ⚠️ 깨진 줄을 건너뛰더라도 **줄번호는 건너뛴 만큼 그대로 간다** — 재실행 때 같은 줄이
    같은 번호를 받아야 자연키가 안정적이다. `enumerate(유효한 것만)` 으로 매기면
    앞줄 하나가 고쳐지는 순간 뒤 전체의 id 가 밀린다.
    """
    recs, bad = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                bad += 1
                continue
            if isinstance(rec, dict):
                rec["line"] = i          # 도구가 이 값을 자연키에 쓴다
                recs.append(rec)
            else:
                bad += 1
    return recs, bad


def ingest_file(path, dry_run=False):
    """파일 1개를 통째로 1콜에 넘긴다 — 이것이 A-2 의 '배치 입력' 이다.

    실측 파일당 중앙값 45행·최대 수백 행이라 한 콜이 적당한 단위다. 건당 호출로 바꾸면
    41,466번 왕복이 되고, 파일을 넘어 묶으면 실패 시 되돌릴 경계가 흐려진다.
    """
    recs, bad = read_records(path)
    if dry_run or not recs:
        return len(recs), bad, "dry-run" if dry_run else "빈 파일"
    msg = SV.t_learn_observe({"source_path": path, "items": recs})
    return len(recs), bad, msg


def main():
    ap = argparse.ArgumentParser(description="homunculus 관측 → learn.observation")
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--limit", type=int, default=0, help="최근 N파일만 (0=전량)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="파일별 줄 대신 진행 요약만")
    args = ap.parse_args()

    S.init_stores()
    files = find_files(args.root)
    if args.limit:
        files = files[:args.limit]
    if not files:
        print("적재할 관측 파일이 없다 — root=%s" % args.root)
        return 0

    t0 = time.time()
    rows = badtotal = 0
    with S.connect(S.LEARN_DB) as c:
        before = c.execute("SELECT count(*) n FROM observation").fetchone()["n"]

    for i, (_, path) in enumerate(files, 1):
        n, bad, msg = ingest_file(path, args.dry_run)
        rows += n
        badtotal += bad
        if not args.quiet:
            head = msg.splitlines()[0] if isinstance(msg, str) else str(msg)
            print("[%d/%d] %-70s %s" % (i, len(files), os.path.relpath(path, args.root), head))
        elif i % 100 == 0:
            print("  … %d/%d 파일" % (i, len(files)))

    with S.connect(S.LEARN_DB) as c:
        after = c.execute("SELECT count(*) n FROM observation").fetchone()["n"]
        nul = c.execute("SELECT count(*) n FROM observation WHERE observed_at IS NULL").fetchone()["n"]

    print("\n%s파일 %d개 · 읽은 행 %d · 깨진 줄 %d · %.1fs"
          % ("[dry-run] " if args.dry_run else "", len(files), rows, badtotal, time.time() - t0))
    if not args.dry_run:
        print("observation %d → %d행 (신규 %d · 중복 무시 %d)"
              % (before, after, after - before, rows - (after - before)))
        print("시각 미상 %d행 — NULL 로 남았다(0 아님). 에이징 대상에서 제외된다" % nul)
    print("⚠️ 원본은 건드리지 않았다 — 파일이 정본, DB 는 파생(Issue403 ⓒ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
