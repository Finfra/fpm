#!/usr/bin/env python3
"""fbot 아이콘 생성기 — 카탈로그 기반 결정론 SVG. (fbot-arch §직능 카탈로그 ⑤단계)

규약: 도형은 role 소유(동형), 색은 개체(bot_id md5→HSL) 유도. 표준 lib 만.
카탈로그 형식(사람 편집): `{role}: shape=<도형> base=<#hex> label=<한글> tags=<t1|t2>`
"""
import argparse, colorsys, hashlib, os, re, sys

ICON_DIR = os.path.expanduser("~/.claude/data/fbot/icons")
CATALOG = os.path.join(ICON_DIR, "catalog.yml")

DEFAULT_CATALOG = """\
# fbot 아이콘 카탈로그 — 사람 편집 가능. 형식: {role}: shape=<도형> base=<#hex> label=<한글> tags=<t1|t2>
# 도형 어휘: star shield hexagon triangle grid check magnifier
exec: shape=star base=#B8860B label=중역핀봇 tags=보고|승인
hr: shape=shield base=#2E6E4E label=인사핀봇 tags=채용|게이트
taskmgr: shape=hexagon base=#3A5FA0 label=작업핀봇 tags=배분|모니터링
architect: shape=triangle base=#7A4FA0 label=설계핀봇 tags=설계|점검
planner: shape=grid base=#A0623A label=기획자핀봇 tags=plan|task
qa: shape=check base=#3A8A8A label=QA핀봇 tags=검증|판정
research: shape=magnifier base=#6E6E3A label=리서치핀봇 tags=조사|선례
"""

# 도형: 128x128 viewBox 중앙, 흰색 — role 동형의 실체
SHAPES = {
    "star": '<polygon fill="#fff" points="64,26 75,52 103,54 82,73 88,101 64,86 40,101 46,73 25,54 53,52"/>',
    "shield": '<path fill="#fff" d="M64 24 L98 36 V66 C98 88 84 100 64 108 C44 100 30 88 30 66 V36 Z"/>',
    "hexagon": '<polygon fill="#fff" points="64,24 98,44 98,84 64,104 30,84 30,44"/>',
    "triangle": '<polygon fill="#fff" points="64,26 102,98 26,98"/>',
    "grid": '<g fill="#fff"><rect x="34" y="34" width="26" height="26" rx="4"/><rect x="68" y="34" width="26" height="26" rx="4"/><rect x="34" y="68" width="26" height="26" rx="4"/><rect x="68" y="68" width="26" height="26" rx="4"/></g>',
    "check": '<g stroke="#fff" stroke-width="10" fill="none" stroke-linecap="round"><circle cx="64" cy="64" r="34"/><polyline points="48,64 60,78 84,50"/></g>',
    "magnifier": '<g stroke="#fff" stroke-width="10" fill="none" stroke-linecap="round"><circle cx="56" cy="56" r="26"/><line x1="76" y1="76" x2="100" y2="100"/></g>',
}


def load_catalog():
    # 부재 시 표준 7종으로 자동 초기화 — 부트스트랩은 fail-loud 대상이 아니다
    # (fail-loud 는 "미등재 role" 에만. 기존 카탈로그가 있으면 절대 건드리지 않는다)
    if not os.path.exists(CATALOG):
        os.makedirs(ICON_DIR, exist_ok=True)
        open(CATALOG, "w", encoding="utf-8").write(DEFAULT_CATALOG)
        print(f"카탈로그 부재 — 표준 7종으로 자동 초기화: {CATALOG}")
    roles = {}
    for line in open(CATALOG, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([a-z0-9-]+):\s*(.+)$", line)
        if not m:
            continue
        fields = dict(kv.split("=", 1) for kv in m.group(2).split() if "=" in kv)
        roles[m.group(1)] = fields
    return roles


def bot_color(bot_id):
    """bot_id → 결정론 색 (md5 → hue, 채도·명도 고정 — 재현성 보장)."""
    hue = int(hashlib.md5(bot_id.encode()).hexdigest(), 16) % 360
    r, g, b = colorsys.hls_to_rgb(hue / 360, 0.48, 0.62)
    return "#{:02X}{:02X}{:02X}".format(int(r * 255), int(g * 255), int(b * 255))


def render(shape, color):
    body = SHAPES[shape]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
            f'<circle cx="64" cy="64" r="60" fill="{color}"/>{body}</svg>\n')


def write_svg(path, content, force):
    if os.path.exists(path) and not force:
        print(f"skip (기존 파일 보호 — 덮어쓰려면 --force): {path}")
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"생성: {path}")
    return True


def cmd_init(_):
    os.makedirs(ICON_DIR, exist_ok=True)
    if os.path.exists(CATALOG):
        print(f"이미 존재: {CATALOG}")
        return
    open(CATALOG, "w", encoding="utf-8").write(DEFAULT_CATALOG)
    print(f"카탈로그 초기화: {CATALOG}")


def cmd_list(_):
    for role, f in load_catalog().items():
        print(f"{role:12s} shape={f.get('shape','?'):10s} base={f.get('base','?'):8s} "
              f"label={f.get('label','?')} tags={f.get('tags','')}")


def cmd_gen(a):
    roles = load_catalog()
    targets = list(roles) if a.all else [a.role]
    if not targets or targets == [None]:
        sys.exit("--role 또는 --all 필요")
    for role in targets:
        if role not in roles:
            sys.exit(f"미등재 role: {role} — `add-role` 로 먼저 등재 (자동 등재 금지)")
        shape = roles[role].get("shape")
        if shape not in SHAPES:
            sys.exit(f"미정의 도형: {shape} (role={role}) — 어휘: {', '.join(SHAPES)}")
        if a.bot_id:
            path = os.path.join(ICON_DIR, f"{a.bot_id}.svg")
            write_svg(path, render(shape, bot_color(a.bot_id)), a.force)
        else:
            path = os.path.join(ICON_DIR, f"{role}.svg")
            write_svg(path, render(shape, roles[role].get("base", "#555555")), a.force)


def cmd_add_role(a):
    roles = load_catalog()
    if a.role in roles:
        sys.exit(f"이미 등재됨: {a.role}")
    if a.shape not in SHAPES:
        sys.exit(f"미정의 도형: {a.shape} — 어휘: {', '.join(SHAPES)}")
    tags = a.tags.replace(",", "|") if a.tags else ""
    with open(CATALOG, "a", encoding="utf-8") as f:
        f.write(f"{a.role}: shape={a.shape} base={a.base} label={a.label} tags={tags}\n")
    print(f"등재: {a.role} (shape={a.shape})")


def main():
    p = argparse.ArgumentParser(description="fbot 아이콘 생성기")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("list")
    g = sub.add_parser("gen")
    g.add_argument("--role")
    g.add_argument("--bot-id")
    g.add_argument("--all", action="store_true")
    g.add_argument("--force", action="store_true")
    r = sub.add_parser("add-role")
    r.add_argument("role")
    r.add_argument("--shape", required=True)
    r.add_argument("--base", default="#555555")
    r.add_argument("--label", required=True)
    r.add_argument("--tags", default="")
    a = p.parse_args()
    if a.cmd == "gen" and a.bot_id and not a.role:
        sys.exit("--bot-id 는 --role 과 함께 (도형은 role 소유)")
    {"init": cmd_init, "list": cmd_list, "gen": cmd_gen, "add-role": cmd_add_role}[a.cmd](a)


if __name__ == "__main__":
    main()
