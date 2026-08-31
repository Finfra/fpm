#!/usr/bin/env python3
"""fbot 아이콘 생성기 — 카탈로그 기반 결정론 SVG. (fbot-arch §직능 카탈로그 ⑤단계)

규약: 도형은 role 소유(동형), 색은 개체(bot_id → 팔레트 슬롯) 유도. 표준 lib 만.
카탈로그 형식(사람 편집): `{role}: shape=<도형> base=<#hex> label=<한글> tags=<t1|t2>`
"""
import argparse, hashlib, json, os, re, sqlite3, sys

# fbot 루트 — DB `bot.icon` 은 이 루트 기준 상대경로로 기록된다(hub 렌더가 같은 규약으로 읽음).
FBOT_ROOT = os.environ.get("FBOT_ROOT") or os.path.expanduser("~/.claude")
ICON_DIR = os.path.join(FBOT_ROOT, "data", "fbot", "icons")
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
    # magnet — 리크루팅핀봇 (prj3#Issue480). 어휘 7종이 전부 사용 중이라 상비 4번째 봇에
    #   배정할 도형이 없었다(fbot-arch §미해결). U자 말굽자석 — "인재를 끌어온다".
    "magnet": '<g fill="none" stroke="#fff" stroke-width="14" stroke-linecap="butt">'
              '<path d="M44 30 V64 A20 20 0 0 0 84 64 V30"/></g>'
              '<g fill="#fff"><rect x="37" y="26" width="14" height="18"/>'
              '<rect x="77" y="26" width="14" height="18"/></g>',
    # frame — 인포그래픽핀봇 (prj3#Issue482 E2E 첫 실증 role). 그림틀(사각 프레임) 안에
    #   산·해 픽토그램 — "이미지를 도형으로" 의 시각적 은유.
    "frame": '<g fill="none" stroke="#fff" stroke-width="8"><rect x="30" y="34" width="68" '
             'height="60" rx="6"/></g><g fill="#fff"><circle cx="50" cy="52" r="7"/>'
             '<path d="M36 86 L58 62 L70 76 L80 66 L92 86 Z"/></g>',
    # speech — 컨설턴트핀봇 (2026-09-01, consultant-m agent 승격). 어휘 9종이 전부
    #   사용 중이라 신규 배정 도형이 없었다(magnet·frame 과 동일 경로). 꼬리 달린
    #   말풍선 — "조언·2차 의견". 내부 점 3개는 배경색으로 뚫어 상담 은유를 살린다.
    "speech": '<path fill="#fff" fill-rule="evenodd" d="M32 30 H96 A10 10 0 0 1 106 40 '
              'V78 A10 10 0 0 1 96 88 H60 L42 104 V88 H32 A10 10 0 0 1 22 78 V40 '
              'A10 10 0 0 1 32 30 Z M45 59 a5 5 0 1 0 10 0 a5 5 0 1 0 -10 0 '
              'M59 59 a5 5 0 1 0 10 0 a5 5 0 1 0 -10 0 '
              'M73 59 a5 5 0 1 0 10 0 a5 5 0 1 0 -10 0"/>',
    # venn — 교차검증핀봇 (2026-09-01, agy-* skill 승격 C안). 두 원의 윤곽 + 교차
    #   렌즈를 채운다 — "같은 것을 다른 눈으로 겹쳐 본다". 교차점은 중심 (50,64)·
    #   (78,64) r=28 에서 x=64, y=64±√(28²-14²)≈±24.2 로 산출.
    "venn": '<g fill="none" stroke="#fff" stroke-width="7"><circle cx="50" cy="64" r="28"/>'
            '<circle cx="78" cy="64" r="28"/></g>'
            '<path fill="#fff" d="M64 40 A28 28 0 0 1 64 88 A28 28 0 0 1 64 40 Z"/>',
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


# ── 개체색 팔레트 (Issue440) ────────────────────────────────────────────────
# 구 방식은 `md5(bot_id) % 360` hue 1축이라 표현 가능한 색이 360개뿐이었고, 인지 가능한
# 차이는 그보다 훨씬 적어 13봇에서 이미 **완전 동색 1쌍**이 나왔다(실측 minΔE2000 = 0.00).
# hue 2축 변주(후보ⓐ)·role 대역 분할(후보ⓑ)은 순수 해시라 20봇 몬테카를로 400회에서
# 동색이 각각 5.2%·18.0% 남았다 — "임의 2색이 인지 임계 이상" 을 **보장**하지 못한다.
# 채택은 후보ⓒ(충돌 감지 후 결정론 재배치): 서로 충분히 떨어진 팔레트에서 슬롯을 잡되,
# 앞서 등록된 봇이 이미 쓴 슬롯은 결정론 probe 로 비켜간다 → 충돌 구조적 0.
#
# 팔레트 생성 레시피(재현 가능): OKLCH 격자 L∈[0.42,0.70] 8단 × C∈{0.06…0.26} 6단 ×
#   H 72단 = 1551 후보 → sRGB 게이멋 + **흰 도형 대비 ≥ 3:1**(WCAG 1.4.11) 필터 →
#   CIEDE2000 farthest-point sampling 64색.
# 실측 보증: 팔레트 내 임의 2색의 **최소 ΔE2000 = 9.71** · 최소 대비 3.03:1.
# ⚠️ 순서를 바꾸면 전 봇의 색이 바뀐다 — 추가는 **끝에만**, 재정렬 금지.
PALETTE = [
    "#0063EB", "#909B1F", "#FC4734", "#23584B", "#832151", "#F14BE9", "#7D4A07", "#659DA4",
    "#C8800D", "#A57785", "#5C10B4", "#019F68", "#575E0A", "#8790B8", "#A50D1C", "#545378",
    "#DA1D69", "#8B7851", "#1795FA", "#964E9B", "#945FF9", "#82564F", "#1E7729", "#386B7B",
    "#869A73", "#B87252", "#0B517F", "#AD7EB8", "#558675", "#DA6A76", "#67754E", "#7B566E",
    "#3E9F24", "#DF5BA1", "#CD4805", "#7584FE", "#65396F", "#9C19DB", "#79371E", "#3A4198",
    "#DE1D3F", "#7A6FB1", "#5A4C24", "#425430", "#2B85AA", "#AA8F44", "#796006", "#353FF3",
    "#117555", "#A33949", "#CC2997", "#7E7F32", "#AE615C", "#AC8B6B", "#627C9E", "#A36D34",
    "#7D5B40", "#8A6F91", "#B4857D", "#209993", "#693F49", "#B45BC8", "#7198B4", "#59894F",
]


def bot_color(bot_id, taken=()):
    """bot_id → 결정론 개체색. `taken` 은 **먼저 등록된 봇들이 이미 쓴 색**.

    결정론: 같은 (bot_id, taken) 이면 언제나 같은 색. taken 이 앞선 등록분만 담기므로
    (bot 레코드는 append-only) **한 번 배정된 색은 이후 채용이 늘어도 변하지 않는다** —
    재현성 계약 유지. taken 이 비면 순수 해시 슬롯(구 방식과 같은 무상태 동작)이다.

    probe: step 은 항상 홀수라 팔레트 크기 64(2의 거듭제곱)와 서로소 → 64슬롯 전수 순회.
    """
    h = int(hashlib.md5(bot_id.encode()).hexdigest(), 16)
    n = len(PALETTE)
    base = h % n
    step = 2 * ((h // n) % (n // 2)) + 1
    taken = set(taken)
    for k in range(n):
        c = PALETTE[(base + k * step) % n]
        if c not in taken:
            return c
    # 팔레트 포화(봇 > 64) — 색만으로는 더 못 가른다. 죽지 않고 기본 슬롯으로 되돌리되
    #   호출부가 `audit` 로 중복을 볼 수 있게 남긴다(도형+호칭 병기로 식별은 유지).
    return PALETTE[base]


def registry_db():
    aoa = os.environ.get("AOA_MEMORY_DIR") or os.path.expanduser("~/.claude/data/aoa")
    return os.path.join(aoa, "registry.db")


def registered_bot_ids():
    """등록 순서(created_at, rowid)로 전 봇 id. DB 부재면 None → 무상태 폴백.

    왜 순서인가 — 충돌 회피는 "누가 먼저 잡았나" 를 알아야 성립한다. rowid 동반 정렬은
    created_at 동률(같은 초에 2건 채용)일 때 **삽입 순서**를 그대로 쓰기 위함이다.
    """
    db = registry_db()
    if not os.path.exists(db):
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("SELECT bot_id FROM bot ORDER BY created_at, rowid")]
    finally:
        con.close()


def assign_colors(bot_ids):
    """등록 순서대로 색 배정 — 앞선 봇이 잡은 색을 뒤가 피한다. 같은 입력 → 같은 출력(멱등)."""
    taken, out = set(), {}
    for b in bot_ids:
        c = bot_color(b, taken)
        out[b] = c
        taken.add(c)
    return out


def color_for(bot_id):
    """개체색 단건 — 등록 순서상 자기 **앞**의 봇만 회피 대상으로 삼는다.

    채용 경로(HR 게이트)는 register 이전에 부르므로 미등록이 정상이다 → 맨 뒤로 붙인다.
    등록 후 `sync-registry` 가 전 코호트를 재계산해도 같은 값이 나온다(멱등).
    """
    ids = registered_bot_ids()
    if ids is None:
        return bot_color(bot_id)
    ids = ids[:ids.index(bot_id) + 1] if bot_id in ids else ids + [bot_id]
    return assign_colors(ids)[bot_id]


def render(shape, color):
    body = SHAPES[shape]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
            f'<circle cx="64" cy="64" r="60" fill="{color}"/>{body}</svg>\n')


def write_svg(path, content, force, quiet=False):
    if os.path.exists(path) and not force:
        if not quiet:
            print(f"skip (기존 파일 보호 — 덮어쓰려면 --force): {path}")
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if not quiet:
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
    out = []
    for role in targets:
        if role not in roles:
            sys.exit(f"미등재 role: {role} — `add-role` 로 먼저 등재 (자동 등재 금지)")
        shape = roles[role].get("shape")
        if shape not in SHAPES:
            sys.exit(f"미정의 도형: {shape} (role={role}) — 어휘: {', '.join(SHAPES)}")
        if a.bot_id:
            path = os.path.join(ICON_DIR, f"{a.bot_id}.svg")
            color = color_for(a.bot_id)   # 개체별 색 (결정론 — 팔레트 슬롯 + 충돌 probe)
        else:
            path = os.path.join(ICON_DIR, f"{role}.svg")
            color = roles[role].get("base", "#555555")   # 종류 기본색
        created = write_svg(path, render(shape, color), a.force, quiet=a.json)
        out.append({"role": role, "bot_id": a.bot_id, "path": path,
                    "rel_path": os.path.relpath(path, FBOT_ROOT),
                    "color": color, "shape": shape, "created": created})
    if a.json:
        # 소비처(HR 게이트)가 색·경로를 **묻는** 경로. 색 계산을 복제하면 그 순간 판정이 갈라진다.
        print(json.dumps(out if a.all else out[0], ensure_ascii=False))


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


def cmd_sync_registry(a):
    """레지스트리 `bot` 레코드의 icon/color 를 아이콘 자산과 맞춘다 (기본 dry-run).

    왜 필요한가 — 채용 경로에 아이콘 배선이 없던 기간에 등록된 봇은 icon 이 NULL 이고
    color 에 **role 기본색**이 들어가 있다(prj3#Issue438 실측 13봇 중 12건). 계약은
    "종류별 동형 도형 + 개체별 색" 이므로 같은 role 봇이 동색이면 카드에서 구분되지 않는다.

    판정: icon 이 비었거나, color 가 개체색(bot_color)과 다르면 대상. 사람이 손으로 정한
    색을 덮지 않도록 --apply 없이는 아무것도 쓰지 않고 목록만 보여준다.
    """
    db = registry_db()
    if not os.path.exists(db):
        sys.exit(f"레지스트리 DB 없음: {db} (AOA_MEMORY_DIR 확인)")
    roles = load_catalog()
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    # 색 배정은 **등록 순서 전 코호트를 한 번에** 계산한다(Issue440) — 개별 재계산으로는
    #   "앞선 봇이 무엇을 잡았나" 를 알 수 없어 충돌 회피가 성립하지 않는다. 같은 순서 →
    #   같은 결과이므로 반복 실행이 곧 멱등이다.
    order = [r["bot_id"] for r in
             con.execute("SELECT bot_id FROM bot ORDER BY created_at, rowid").fetchall()]
    colors = assign_colors(order)
    rows = con.execute("SELECT bot_id, role, icon, color FROM bot ORDER BY bot_id").fetchall()
    plan = []
    for r in rows:
        role = r["role"]
        if role not in roles:
            print(f"  skip {r['bot_id']}: 미등재 role={role}")
            continue
        want_color = colors[r["bot_id"]]
        want_icon = os.path.relpath(os.path.join(ICON_DIR, f"{r['bot_id']}.svg"), FBOT_ROOT)
        need_icon = (r["icon"] or "") != want_icon
        need_color = (r["color"] or "") != want_color
        if need_icon or need_color:
            plan.append((r["bot_id"], role, want_icon, want_color,
                         r["icon"], r["color"], need_icon, need_color))
    if not plan:
        print("드리프트 없음 — 전 봇의 icon/color 가 자산과 일치")
        con.close()
        return
    for bid, role, wi, wc, oi, oc, ni, nc in plan:
        marks = ("icon" if ni else "") + ("+color" if ni and nc else ("color" if nc else ""))
        print(f"  {bid:26s} [{role:9s}] {marks:11s} icon {oi or '(null)'} → {wi}"
              f" | color {oc or '(null)'} → {wc}")
    if not a.apply:
        print(f"\n{len(plan)}건 (dry-run — 실제 적용은 --apply)")
        con.close()
        return
    applied, protected = [], []
    for bid, role, wi, wc, _oi, oc, _ni, _nc in plan:
        shape = roles[role].get("shape")
        path = os.path.join(ICON_DIR, f"{bid}.svg")
        # 사람이 손본 아이콘 보호 (스킬 규약 — `--force` 없이 덮지 않는다).
        #   판정은 "기존 파일이 **현재 DB 색으로 이 생성기가 뽑았을 바이트와 동일한가**".
        #   같으면 기계 생성물이라 재생성이 안전하고, 다르면 손댄 흔적이라 건드리지 않는다.
        #   ⚠️ 보호 시 DB 색도 함께 두어야 한다 — 파일만 남기고 색을 바꾸면 카드 dot 과
        #   아이콘이 갈라져 오히려 조용한 드리프트가 된다.
        machine = (not os.path.exists(path)) or (
            bool(oc) and read_text(path) == render(shape, oc))
        if not machine and not a.force:
            protected.append(bid)
            continue
        write_svg(path, render(shape, wc), True, quiet=True)
        con.execute("UPDATE bot SET icon = ?, color = ? WHERE bot_id = ?", (wi, wc, bid))
        applied.append(bid)
    con.commit()
    con.close()
    print(f"\n{len(applied)}건 적용 (아이콘 생성 + 레지스트리 갱신)")
    if protected:
        print(f"⚠️ {len(protected)}건 보호 — 사람이 손본 아이콘으로 판정해 건너뜀"
              f" (덮어쓰려면 --force): {', '.join(protected)}")


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def cmd_audit(_):
    """전 봇의 개체색 배정을 실측 출력 + 중복 검출 (Issue440 검증구).

    "충돌 0" 은 주장이 아니라 **세어서 보여줄 수 있는 값**이어야 한다.
    """
    ids = registered_bot_ids()
    if ids is None:
        sys.exit(f"레지스트리 DB 없음: {registry_db()} (AOA_MEMORY_DIR 확인)")
    colors = assign_colors(ids)
    db = registry_db()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    have = {r["bot_id"]: (r["role"], r["color"]) for r in
            con.execute("SELECT bot_id, role, color FROM bot")}
    con.close()
    seen = {}
    for b in ids:
        role, cur = have[b]
        mark = "" if (cur or "") == colors[b] else f"  ← DB {cur or '(null)'} (sync-registry 필요)"
        print(f"  {b:26s} [{role:9s}] {colors[b]}{mark}")
        seen.setdefault(colors[b], []).append(b)
    dup = {c: bs for c, bs in seen.items() if len(bs) > 1}
    print(f"\n봇 {len(ids)}건 · 고유색 {len(seen)}건 · 팔레트 {len(PALETTE)}슬롯 "
          f"(여유 {len(PALETTE)-len(ids)})")
    if dup:
        for c, bs in dup.items():
            print(f"⚠️ 동색 {c}: {', '.join(bs)}")
        sys.exit(f"충돌 {len(dup)}쌍 — 팔레트 포화 여부 확인")
    print("충돌 0 ✅")


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
    g.add_argument("--json", action="store_true",
                   help="생성 결과(경로·개체색)를 JSON 으로 출력 — 소비처가 색을 재계산하지 않게 한다")
    sr = sub.add_parser("sync-registry")
    sr.add_argument("--apply", action="store_true",
                    help="실제 적용 (생략 시 dry-run)")
    sr.add_argument("--force", action="store_true",
                    help="사람이 손본 것으로 판정된 아이콘까지 덮어쓴다 (기본은 보호·건너뜀)")
    sub.add_parser("audit", help="전 봇 개체색 배정 실측 + 동색 검출 (Issue440 검증구)")
    r = sub.add_parser("add-role")
    r.add_argument("role")
    r.add_argument("--shape", required=True)
    r.add_argument("--base", default="#555555")
    r.add_argument("--label", required=True)
    r.add_argument("--tags", default="")
    a = p.parse_args()
    if a.cmd == "gen" and a.bot_id and not a.role:
        sys.exit("--bot-id 는 --role 과 함께 (도형은 role 소유)")
    {"init": cmd_init, "list": cmd_list, "gen": cmd_gen, "add-role": cmd_add_role,
     "sync-registry": cmd_sync_registry, "audit": cmd_audit}[a.cmd](a)


if __name__ == "__main__":
    main()
