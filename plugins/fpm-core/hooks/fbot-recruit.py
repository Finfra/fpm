#!/usr/bin/env python3
"""fbot 리크루팅핀봇(recruit) 집행 코어 (prj3#Issue480).

계약: ~/.claude/_doc_arch/fbot-arch.md §조직(4종 — 축 분리)·§직능 카탈로그
      (등록 절차의 주체 / 직능 아카이브·부활)·§표준 시나리오 2.
      계약 참조만 하며 여기서 재결정하지 않는다.

역할 경계 — **직능(카탈로그) 축만 소유한다.** 개체(bot 테이블)는 인사핀봇 소관이라
    본 파일에 registry 접속 코드가 아예 없다. 판단 단계(⓪중복검사·①재료수집·②매뉴얼
    초안·③사람 승인)는 LLM 작업이라 스킬(skills/fbot-recruit/) 몫이고, 여기는 결정론
    집행(④카탈로그 등재·⑤아이콘)과 아카이브·부활만 한다.

CLI
    register --role R --shape S --base '#hex' --label L [--tags 't1|t2']
        ④+⑤ — 카탈로그 등재 후 아이콘 생성까지. 등재는 fbot-icon add-role 에
        위임한다(카탈로그 쓰기 단일 지점 유지 — 본 파일도 직접 append 하지 않는다).
        ⚠️ 사람 승인(③) 이후에만 부른다 — 호출 순서는 스킬이 지키고, 여기서는
        검증할 방법이 없다(승인 기록이 mq 에 있고 큐 조회는 이 계층의 소관이 아니다).
    archive [--role R] [--apply]
        직능 아카이브 — 기본 dry-run(후보 목록). --apply + --role 로 1건 집행.
        효과: hr-gate load_catalog 가 그 role 을 미등재와 동일하게 거부한다.
        파일(매뉴얼·아이콘·기록)은 남는다 — 아카이브는 삭제가 아니다.
    revive --role R
        부활 — status 필드 제거 1줄. 매뉴얼이 잔존하므로 ①~② 재수행 불요.
    list
        카탈로그 전체 + status 표시.

설계 원칙 (fbot-state.py·fbot-hr-gate.py 승계)
* 표준 라이브러리만 사용(무의존). catalog.yml 은 평탄 kv 라 정규식으로 읽는다.
* fail-loud: 미등재 role·상비 role 아카이브·중복 등재 전부 명시 에러 + exit != 0.
* 상비 4종은 아카이브 불가(계약 §조직) — CORE_ROLES 값의 SSOT 는 fbot-state.py.
"""

import argparse
import json
import os
import re
import subprocess
import sys

# 카탈로그 경로 — fbot-icon 스킬 소유 파일. env 는 테스트 픽스처 주입용.
CATALOG_PATH = os.environ.get("FBOT_CATALOG") or os.path.join(
    os.path.expanduser("~"), ".claude", "data", "fbot", "icons", "catalog.yml")

# 아이콘 생성기 (④⑤ 의 실행체 — 카탈로그 쓰기 단일 지점이라 등재도 여기에 위임)
ICON_GEN = os.path.join(os.path.expanduser("~"), ".claude", "skills", "fbot-icon",
                        "scripts", "fbot-icon-gen.py")

# 상비 role — 값의 SSOT 는 fbot-state.py CORE_ROLES (여기는 아카이브 가드용 사본)
CORE_ROLES = ("exec", "recruit", "hr", "taskmgr")


class RecruitError(Exception):
    """fail-loud 용 — stderr 출력 + exit 2."""


def parse_catalog(path=None) -> dict:
    """{role: {shape,base,label,tags[,status]}} — fbot-icon load_catalog 와 동형 kv 파서."""
    path = path or CATALOG_PATH
    if not os.path.exists(path):
        raise RecruitError(f"카탈로그 없음: {path} — fbot-icon 스킬로 초기화하라")
    roles = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([a-z0-9-]+):\s*(.+)$", line)
        if m:
            roles[m.group(1)] = dict(
                kv.split("=", 1) for kv in m.group(2).split() if "=" in kv)
    return roles


def set_status(path, role: str, status) -> None:
    """role 행의 status 필드를 갱신한다(None = 제거). 다른 행·주석은 건드리지 않는다.

    아카이브의 실체가 이 1줄이다 — 되돌리기(revive)가 1줄이라 판정이 다소 공격적이어도
    손실이 없고, 그래서 개체 축(archive --apply 일괄 허용)과 같은 안전 논리가 성립한다.
    """
    roles = parse_catalog(path)
    if role not in roles:
        raise RecruitError(f"미등재 role: {role!r} — 허용값 {', '.join(sorted(roles))}")
    if status == "archived" and role in CORE_ROLES:
        raise RecruitError(
            f"상비 role 아카이브 불가: {role} — 조직 골격이라 비면 판정 주체가 사라진다 "
            f"(계약 §조직, 상비 4종: {', '.join(CORE_ROLES)})")
    out = []
    for line in open(path, encoding="utf-8"):
        raw = line.rstrip("\n")
        m = re.match(r"^([a-z0-9-]+):\s*(.+)$", raw.strip())
        if m and m.group(1) == role:
            fields = [kv for kv in m.group(2).split() if not kv.startswith("status=")]
            if status:
                fields.append(f"status={status}")
            out.append(f"{role}: " + " ".join(fields))
        else:
            out.append(raw)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── CLI ─────────────────────────────────────────────────────────────────────

def cmd_register(args) -> int:
    roles = parse_catalog()
    if args.role in roles:
        raise RecruitError(f"이미 등재된 role: {args.role} — 중복 등재 금지(부활은 revive)")
    manual = os.path.join(os.path.expanduser("~"), ".claude", "data", "fbot",
                          "manuals", f"{args.role}.md")
    if not os.path.exists(manual):
        # 절차 ①② 가 선행이다 — 매뉴얼 없는 등재는 "직능 정의 없이 이름만 있는" 상태
        raise RecruitError(f"매뉴얼 부재: {manual} — 등록 절차 ①② 선행 (계약 §직능 카탈로그)")
    cmd = [sys.executable, ICON_GEN, "add-role", args.role,
           "--shape", args.shape, "--base", args.base, "--label", args.label]
    if args.tags:
        cmd += ["--tags", args.tags]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RecruitError(f"카탈로그 등재 실패: {(r.stderr or r.stdout).strip()}")
    g = subprocess.run([sys.executable, ICON_GEN, "gen", "--role", args.role, "--json"],
                       capture_output=True, text=True)
    if g.returncode != 0:
        raise RecruitError(f"아이콘 생성 실패: {(g.stderr or g.stdout).strip()}")
    emit({"ok": True, "action": "register", "role": args.role,
          "manual": manual, "icon": json.loads(g.stdout.strip().splitlines()[-1]),
          "note": "이 시점부터 HR 배치 가능 (계약 §직능 카탈로그 ④)"})
    return 0


def cmd_archive(args) -> int:
    roles = parse_catalog()
    # 후보 = 비상비 + 미아카이브. 유휴 판정(개체 0·유휴일수)은 스킬이 registry 를 물어
    # 판단한다 — 여기는 카탈로그만 보므로 후보 나열과 집행만 한다(축 경계).
    cands = sorted(r for r, f in roles.items()
                   if r not in CORE_ROLES and f.get("status") != "archived")
    if not args.apply:
        emit({"ok": True, "action": "archive", "mode": "dry-run", "candidates": cands,
              "next": "집행은 --apply --role R (부활은 revive — 1줄이라 값싸다)"})
        return 0
    if not args.role:
        raise RecruitError("--apply 는 --role 을 요구한다 — 직능 일괄 아카이브는 두지 않는다"
                           " (개체와 달리 직능은 몇 안 되고 하나하나가 조직 계약이다)")
    set_status(CATALOG_PATH, args.role, "archived")
    emit({"ok": True, "action": "archive", "mode": "집행", "role": args.role,
          "effect": "HR 배치 거부(미등재 동일 취급) · 파일은 전부 잔존"})
    return 0


def cmd_revive(args) -> int:
    roles = parse_catalog()
    if args.role not in roles:
        raise RecruitError(f"미등재 role: {args.role}")
    if roles[args.role].get("status") != "archived":
        raise RecruitError(f"아카이브 상태가 아님: {args.role} — 부활할 것이 없다")
    set_status(CATALOG_PATH, args.role, None)
    emit({"ok": True, "action": "revive", "role": args.role,
          "note": "매뉴얼·아이콘 잔존 — 등록 절차 ①② 재수행 불요 (계약 §직능 카탈로그)"})
    return 0


def cmd_list(args) -> int:
    roles = parse_catalog()
    emit({"ok": True, "action": "list", "count": len(roles),
          "roles": [{"role": r, "label": f.get("label", ""),
                     "status": f.get("status", "active"),
                     "core": r in CORE_ROLES} for r, f in sorted(roles.items())]})
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="fbot 리크루팅 집행 코어 — 직능(카탈로그) 축 전용")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("register", help="④⑤ 카탈로그 등재+아이콘 — 사람 승인(③) 후에만")
    sp.add_argument("--role", required=True)
    sp.add_argument("--shape", required=True)
    sp.add_argument("--base", required=True, help="#rrggbb")
    sp.add_argument("--label", required=True)
    sp.add_argument("--tags", default=None)
    sp.set_defaults(func=cmd_register)

    sp = sub.add_parser("archive", help="직능 아카이브 — 기본 dry-run, --apply --role 로 1건 집행")
    sp.add_argument("--role", default=None)
    sp.add_argument("--apply", action="store_true")
    sp.set_defaults(func=cmd_archive)

    sp = sub.add_parser("revive", help="부활 — status 제거 1줄")
    sp.add_argument("--role", required=True)
    sp.set_defaults(func=cmd_revive)

    sp = sub.add_parser("list", help="카탈로그 전체 + status")
    sp.set_defaults(func=cmd_list)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RecruitError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
