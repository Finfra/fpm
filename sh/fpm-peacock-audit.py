#!/usr/bin/env python3
"""fpm-peacock-audit — peacock 팔레트 색 공간 실측·여유분 탐색 (Issue494).

왜 상설 도구인가
---------------
Issue494_1·494_2 가 쓴 거리 계산 스니펫은 **위임 지시서 안에만** 있었고 저장되지 않았다.
같은 수치를 다시 재려면 스니펫을 다시 써야 했고, 그때마다 공식이 갈릴 위험이 있다
(494_2 에서 Rec.601 계수를 섞어 lum 이 1%p 어긋난 실사례가 있다). 공식·임계·목표치를
한 파일에 고정한다.

척도 (고정)
----------
* 거리: 녹색 민감도 가중 유클리드 `sqrt((2ΔR)² + (4ΔG)² + (3ΔB)²)`
* 명도: HSL L
* 휘도: `0.2126R + 0.7152G + 0.0722B` (채널 0~1) — ⚠️ Rec.601(0.299/0.587/0.114) 과 섞지 말 것

사용
----
    sh/fpm-peacock-audit.py                    # 현황 실측 (중앙값·최소·가드 이탈)
    sh/fpm-peacock-audit.py --pairs 10         # 최근접 쌍 상위 N
    sh/fpm-peacock-audit.py --headroom 30      # 거리 30 이상 신규 배정 여유분 탐색
    sh/fpm-peacock-audit.py --headroom 30 --sat-only   # 채도 축만 (명도 가드 유지)
"""
import argparse
import colorsys
import re
import statistics
import sys
from pathlib import Path

L_MIN = 80.0      # HSL L 하한 (%)
LUM_MIN = 78.0    # 상대 휘도 하한 (%)
HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def dist(a, b):
    ar, ag, ab = rgb(a); br, bg, bb = rgb(b)
    return ((2 * (ar - br)) ** 2 + (4 * (ag - bg)) ** 2 + (3 * (ab - bb)) ** 2) ** 0.5


def hsl_l(h):
    r, g, b = [c / 255 for c in rgb(h)]
    return colorsys.rgb_to_hls(r, g, b)[1] * 100


def hsl_s(h):
    r, g, b = [c / 255 for c in rgb(h)]
    return colorsys.rgb_to_hls(r, g, b)[2] * 100


def lum(h):
    r, g, b = [c / 255 for c in rgb(h)]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) * 100


def load(pm_base):
    """Projects.md 표 파싱. ⚠️ 정규식으로 열을 «모양» 으로 맞추지 않는다 —
    Dmn 열이 `g`·`g(cli)`·`g(Exe)` 로 갈려 한 패턴이 6행을 조용히 흘렸다(2026-09-20 실측).
    열 분리 후 **마지막 hex 열**만 본다."""
    rows = []
    for line in (Path(pm_base) / 'Projects.md').read_text().splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 8 or not HEX_RE.match(cells[-1]):
            continue
        rows.append({'id': cells[0], 'name': cells[1], 'domain': cells[3],
                     'color': cells[-1].lower()})
    return rows


def nearest(rows):
    out = []
    for i, a in enumerate(rows):
        d = min(((dist(a['color'], b['color']), b) for j, b in enumerate(rows) if i != j),
                key=lambda x: x[0])
        out.append((a, d[1], d[0]))
    return out


def report(rows, top):
    n = len(rows)
    pairs = [(dist(rows[i]['color'], rows[j]['color']), rows[i], rows[j])
             for i in range(n) for j in range(i + 1, n)]
    near = nearest(rows)
    nd = sorted(x[2] for x in near)
    print(f'[peacock] 등록 {n}색 · 전체 {len(pairs)}쌍')
    print(f'  최근접 거리  중앙값 {statistics.median(nd):.1f} · 최소 {min(nd):.1f} · 최대 {max(nd):.1f}')
    for t in (10, 30, 50):
        print(f'  거리 {t} 미만 쌍: {sum(1 for p in pairs if p[0] < t)}')
    bad = [r for r in rows if hsl_l(r['color']) < L_MIN or lum(r['color']) < LUM_MIN]
    print(f'  명도 가드(L>={L_MIN:.0f}% · lum>={LUM_MIN:.0f}%) 이탈 {len(bad)}건: '
          + ', '.join(f"{r['id']}({r['color']} L{hsl_l(r['color']):.1f} lum{lum(r['color']):.1f})" for r in bad))
    print(f"  L 중앙값 {statistics.median([hsl_l(r['color']) for r in rows]):.1f}% · "
          f"S 중앙값 {statistics.median([hsl_s(r['color']) for r in rows]):.1f}% · "
          f"lum 중앙값 {statistics.median([lum(r['color']) for r in rows]):.1f}%")
    if top:
        print(f'  최근접 상위 {top}쌍:')
        for a, b, d in sorted(near, key=lambda x: x[2])[:top]:
            print(f"    {d:6.1f}  {a['id']:>4} {a['color']}  ↔  {b['id']:>4} {b['color']}")


def headroom(rows, min_d, l_min, lum_min, step=8):
    """가드를 만족하면서 기존 색·서로에게서 min_d 이상 떨어진 색을 탐욕적으로 고른다.
    격자 step(0~255)으로 훑는다 — 정확한 최대 독립집합이 아니라 **하한**이다."""
    existing = [r['color'] for r in rows]
    picked = []
    grid = range(0, 256, step)
    for r in grid:
        for g in grid:
            for b in grid:
                h = f'#{r:02x}{g:02x}{b:02x}'
                if hsl_l(h) < l_min or lum(h) < lum_min:
                    continue
                if any(dist(h, e) < min_d for e in existing):
                    continue
                if any(dist(h, p) < min_d for p in picked):
                    continue
                picked.append(h)
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument('--pairs', type=int, default=0)
    ap.add_argument('--headroom', type=float)
    ap.add_argument('--l-min', type=float, default=L_MIN)
    ap.add_argument('--lum-min', type=float, default=LUM_MIN)
    ap.add_argument('--step', type=int, default=8)
    ap.add_argument('--fresh', action='store_true',
                    help='기존 52색을 무시하고 «빈 팔레트» 에서 몇 색을 뽑을 수 있는지 — 전수 재배정 상한')
    a = ap.parse_args()
    rows = load(a.base)
    if not rows:
        print('[peacock] Projects.md 표를 읽지 못했다', file=sys.stderr)
        return 2
    report(rows, a.pairs)
    if a.headroom:
        p = headroom([] if a.fresh else rows, a.headroom, a.l_min, a.lum_min, a.step)
        print(f'\n[peacock] 여유분 탐색 — 거리 {a.headroom:.0f} 이상 · L>={a.l_min:.0f}% · lum>={a.lum_min:.0f}%')
        print(f'  확보 가능 {len(p)}색 (격자 step={a.step}, 하한 추정)')
        for i in range(0, len(p), 10):
            print('   ', ' '.join(p[i:i + 10]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
