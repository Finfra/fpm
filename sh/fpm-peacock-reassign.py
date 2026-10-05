#!/usr/bin/env python3
"""fpm-peacock-reassign — 등록 팔레트를 목표 거리 공간으로 다시 배정한다 (Issue510).

무엇을 푸는가
------------
[Issue494](../Issue.md) 가 색 공간 설계를 확정했다 — 명도 가드(`L>=80%`·`lum>=78%`)는
그대로 두고 **채도 축**을 쓰면 거리 50 이상 76색이 나온다. 남은 일은 기존 52색을
그 공간으로 **옮기는 실행**이고, 그때 따라붙는 비용이 «사용자의 색 기억 리셋» 이다.

따라서 이 도구의 목적 함수는 *최대 분리* 가 아니라 **목표 거리 D 를 만족하는 배정 중
이동량이 최소인 것**이다:

1. **유지 단계** — 우선순위 순으로 훑어 이미 확정된 색들과 D 이상 떨어져 있으면 그대로 둔다.
   우선순위 앞쪽(일상 작업 프로젝트)이 색을 지킬 권리를 먼저 갖는다.
2. **배정 단계** — 남은 프로젝트에 가드를 통과하고 확정색 전부와 D 이상 떨어진 후보 중
   **현재 색에 가장 가까운** 것을 준다. 색상(hue)이 보존되므로 «비슷한데 조금 다른 색» 이 된다.

⚠️ 이 도구는 `Projects.md` 까지만 쓴다. `.vscode`·`.zed` 산출물은 각 repo 소유라
[fpm-projects-sync](fpm-projects-sync) 가 별도로 반영한다 (Issue510 ⑤).

사용
----
    sh/fpm-peacock-reassign.py --target 40              # 계획만 출력 (dry-run 기본)
    sh/fpm-peacock-reassign.py --target 30 --target 40 --target 50   # 안 비교
    sh/fpm-peacock-reassign.py --target 40 --md out.md  # 마크다운 리포트 저장
    sh/fpm-peacock-reassign.py --target 40 --apply      # Projects.md color 열 갱신

⚠️ `--apply` 직후 `python3 sh/fpm-projects-sync --no-reverse` 를 실행할 것.
`[0/4]` 역방향 reconcile 이 에디터 색을 SSOT 로 되받아 조용히 되돌린다 (Issue510 ④).
"""
import argparse
import importlib.util
import re
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent

# 거리·명도·휘도 공식은 audit 이 소유한다 — 두 벌로 쓰면 갈린다(Issue494 실사례).
_spec = importlib.util.spec_from_file_location(
    'fpm_peacock_audit', Path(__file__).resolve().parent / 'fpm-peacock-audit.py')
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)

# Issue510 ② — 일상 작업 프로젝트는 색을 지킬 권리를 먼저 갖는다.
DAILY = ['1', '2', '3', '5', '6', '9', '9a', '10', '11', '12', '13', '14', '15', '16']


def to_arr(hexes):
    return np.array([audit.rgb(h) for h in hexes], dtype=float).reshape(-1, 3)


def dist_arr(cands, ref):
    """가중 유클리드 거리 — audit.dist 와 같은 식의 벡터판."""
    w = np.array([2.0, 4.0, 3.0])
    d = (cands[:, None, :] - ref[None, :, :]) * w
    return np.sqrt((d ** 2).sum(axis=2))


def build_candidates(step, l_min, lum_min):
    """가드를 통과하는 격자 후보. step 이 작을수록 이동량이 줄지만 메모리가 는다."""
    g = np.arange(0, 256, step)
    grid = np.stack(np.meshgrid(g, g, g, indexing='ij'), axis=-1).reshape(-1, 3)
    hexes = [f'#{r:02x}{gg:02x}{b:02x}' for r, gg, b in grid]
    keep = np.array([audit.hsl_l(h) >= l_min and audit.lum(h) >= lum_min for h in hexes])
    return grid[keep].astype(float), [h for h, k in zip(hexes, keep) if k]


def priority(rows):
    idx = {r['id']: i for i, r in enumerate(rows)}
    head = [idx[p] for p in DAILY if p in idx]
    return head + [i for i in range(len(rows)) if i not in set(head)]


def plan(rows, target, step, l_min, lum_min, keep_violators=False):
    """유지 → 배정 2단계. 반환: {id: (old, new, kept, moved_dist)} + 실패 목록."""
    cands, cand_hex = build_candidates(step, l_min, lum_min)
    order = priority(rows)
    fixed_rgb, fixed_hex = [], []
    result = {}

    # 1단계 — 유지
    for i in order:
        r = rows[i]
        c = r['color']
        guard_ok = audit.hsl_l(c) >= l_min and audit.lum(c) >= lum_min
        if not guard_ok and not keep_violators:
            continue  # 가드 이탈색은 유지 대상이 아니다 — 2단계에서 새로 받는다
        ref = np.array(audit.rgb(c), dtype=float).reshape(1, 3)
        if fixed_rgb and dist_arr(np.array(fixed_rgb), ref).min() < target:
            continue
        fixed_rgb.append(audit.rgb(c)); fixed_hex.append(c)
        result[r['id']] = (c, c, True, 0.0)

    # 2단계 — 배정 (남은 후보를 현재 색 기준 최근접으로)
    alive = np.ones(len(cands), dtype=bool)
    if fixed_rgb:
        alive &= (dist_arr(cands, np.array(fixed_rgb, dtype=float)) >= target).all(axis=1)
    failed = []
    for i in order:
        r = rows[i]
        if r['id'] in result:
            continue
        if not alive.any():
            failed.append(r['id']); continue
        ref = np.array(audit.rgb(r['color']), dtype=float).reshape(1, 3)
        d = dist_arr(cands, ref)[:, 0]
        d = np.where(alive, d, np.inf)
        j = int(np.argmin(d))
        if not np.isfinite(d[j]):
            failed.append(r['id']); continue
        new = cand_hex[j]
        result[r['id']] = (r['color'], new, False, float(d[j]))
        alive &= (dist_arr(cands, cands[j].reshape(1, 3))[:, 0] >= target)
    return result, failed


def measure(rows, result):
    colors = [result[r['id']][1] for r in rows]
    n = len(colors)
    pairs = [audit.dist(colors[i], colors[j]) for i in range(n) for j in range(i + 1, n)]
    near = []
    for i in range(n):
        near.append(min(audit.dist(colors[i], colors[j]) for j in range(n) if j != i))
    import statistics
    return {
        'n': n,
        'median': statistics.median(near),
        'min': min(near),
        'lt30': sum(1 for p in pairs if p < 30),
        'lt50': sum(1 for p in pairs if p < 50),
        'kept': sum(1 for r in rows if result[r['id']][2]),
        'moved': sum(1 for r in rows if not result[r['id']][2]),
        'move_median': statistics.median(
            [result[r['id']][3] for r in rows if not result[r['id']][2]] or [0]),
        'move_max': max([result[r['id']][3] for r in rows if not result[r['id']][2]] or [0]),
    }


def summary_line(t, m, failed):
    tag = f'거리 {t:.0f}'
    if failed:
        return f'| {tag} | ⛔ 배정 실패 {len(failed)}건 ({", ".join(failed)}) | | | | | |'
    return (f"| {tag} | {m['kept']} | {m['moved']} | {m['median']:.1f} | {m['min']:.1f} | "
            f"{m['lt30']} | {m['move_median']:.0f} / {m['move_max']:.0f} |")


def detail_table(rows, result):
    out = ['| id | 프로젝트 | Dmn | 현재 | 제안 | 이동 |',
           '| :-- | :--- | :-- | :--- | :--- | ---: |']
    for r in rows:
        old, new, kept, mv = result[r['id']]
        mark = '— (유지)' if kept else f'{mv:.0f}'
        out.append(f"| {r['id']} | {r['name']} | {r['domain']} | `{old}` | "
                   f"{'`' + old + '`' if kept else '**`' + new + '`**'} | {mark} |")
    return '\n'.join(out)


def apply_to_projects_md(rows, result, base):
    """표 행의 color 셀만 교체한다 — fpm-projects-sync 의 역방향 갱신과 같은 방식."""
    p = Path(base) / 'Projects.md'
    text = p.read_text()
    changed = 0
    for r in rows:
        old, new, kept, _ = result[r['id']]
        if kept or old.lower() == new.lower():
            continue
        pat = re.compile(r'^(\|\s*' + re.escape(r['id']) + r'\s*\|.*\|\s*)'
                         + re.escape(old) + r'(\s*\|\s*)$', re.M | re.I)
        text, n = pat.subn(lambda m: m.group(1) + new + m.group(2), text)
        if n != 1:
            print(f"  ⚠️ {r['id']}: 행 치환 {n}건 — 건너뜀", file=sys.stderr)
            continue
        changed += 1
    p.write_text(text)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=str(BASE))
    ap.add_argument('--target', type=float, action='append',
                    help='목표 최소 거리. 여러 번 주면 안 비교 (기본 30/40/50)')
    ap.add_argument('--step', type=int, default=4, help='격자 간격 (작을수록 이동량↓·느림)')
    ap.add_argument('--l-min', type=float, default=audit.L_MIN)
    ap.add_argument('--lum-min', type=float, default=audit.LUM_MIN)
    ap.add_argument('--keep-violators', action='store_true',
                    help='명도 가드를 이탈한 기존 색도 유지 대상에 넣는다')
    ap.add_argument('--detail', action='store_true', help='프로젝트별 표를 함께 출력')
    ap.add_argument('--md', help='마크다운 리포트 저장 경로')
    ap.add_argument('--apply', action='store_true',
                    help='Projects.md color 열을 갱신 (--target 1개일 때만)')
    a = ap.parse_args()

    rows = audit.load(a.base)
    if not rows:
        print('[peacock] Projects.md 표를 읽지 못했다', file=sys.stderr)
        return 2
    targets = a.target or [30.0, 40.0, 50.0]
    if a.apply and len(targets) != 1:
        print('[peacock] --apply 는 --target 을 정확히 1개만 받는다', file=sys.stderr)
        return 2

    head = ['| 안 | 유지 | 이동 | 최근접 중앙값 | 최소 | 30 미만 쌍 | 이동량 중앙/최대 |',
            '| :-- | ---: | ---: | ---: | ---: | ---: | ---: |']
    lines, plans = [], {}
    for t in targets:
        res, failed = plan(rows, t, a.step, a.l_min, a.lum_min, a.keep_violators)
        if failed:
            lines.append(summary_line(t, None, failed)); continue
        m = measure(rows, res)
        plans[t] = (res, m)
        lines.append(summary_line(t, m, failed))
    table = '\n'.join(head + lines)
    print(table)

    if a.detail or a.md:
        for t, (res, m) in plans.items():
            block = f'\n### 거리 {t:.0f} 안 — 상세\n\n' + detail_table(rows, res)
            if a.detail:
                print(block)
            if a.md:
                table += block
    if a.md:
        Path(a.md).write_text(table + '\n')
        print(f'\n[peacock] 리포트 → {a.md}')

    if a.apply:
        t = targets[0]
        if t not in plans:
            print('[peacock] 배정 실패 — 적용하지 않는다', file=sys.stderr)
            return 1
        n = apply_to_projects_md(rows, plans[t][0], a.base)
        print(f'\n[peacock] Projects.md {n}행 갱신 — 이어서 '
              f'`python3 sh/fpm-projects-sync --no-reverse` 를 즉시 실행할 것')
    return 0


if __name__ == '__main__':
    sys.exit(main())
