#!/usr/bin/env python3
"""fbot 발굴핀봇(recruit) 집행 코어 (prj3#Issue480).

계약: ~/.claude/_doc_arch/fbot-arch.md §조직(4종 — 축 분리)·§직능 카탈로그
      (등록 절차의 주체 / 직능 아카이브·부활)·§표준 시나리오 2.
      계약 참조만 하며 여기서 재결정하지 않는다.

역할 경계 — **직능(카탈로그) 축만 소유한다.** 개체(bot 테이블)는 인사핀봇 소관이라
    본 파일에 registry 접속 코드가 아예 없다. 판단 단계(⓪중복검사·①재료수집·②매뉴얼
    초안·③사람 승인)는 LLM 작업이라 스킬(skills/fbot-scout/) 몫이고, 여기는 결정론
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
    set-kind --role R --kind tool|bot
        분류 기입 — `tool` 은 «도구 래핑» 재분류(prj3#Issue636). 엔트리를 지우지 않고
        표시만 단다(지우면 이력이 사라져 같은 승격이 반복된다). 배분은 막지 않는다.
    list
        카탈로그 전체 + status 표시.

설계 원칙 (fbot-state.py·fbot-hr-gate.py 승계)
* 표준 라이브러리만 사용(무의존). catalog.yml 은 평탄 kv 라 정규식으로 읽는다.
* fail-loud: 미등재 role·상비 role 아카이브·중복 등재 전부 명시 에러 + exit != 0.
* 상비 4종은 아카이브 불가(계약 §조직) — CORE_ROLES 값의 SSOT 는 fbot-state.py.
"""

import argparse
import hashlib
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
CORE_ROLES = ("chief", "scout", "hr", "lead")

# 행 안의 **위치가 계약인** 키 — hr-gate 정규식이 shape→base 순서를 강제한다
POSITIONAL_KEYS = ("shape", "base")

# 매뉴얼·SCAR 자산 루트 — env 는 테스트 픽스처 주입용(FBOT_CATALOG 선례).
#   origin 해소가 실제 파일 mtime 을 읽으므로 주입점이 없으면 테스트가 운영 파일에 의존한다.
MANUAL_DIR = os.environ.get("FBOT_MANUAL_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude", "data", "fbot", "manuals")
SCAR_ROOT = os.environ.get("FBOT_SCAR_ROOT") or os.path.join(
    os.path.expanduser("~"), ".claude")


class RecruitError(Exception):
    """fail-loud 용 — stderr 출력 + exit 2."""


#   ⚠️ 값에 공백·따옴표를 넣지 않는다 — 파서가 `split()` 기준이라 공백 1개로 필드가
#   갈라진다. URL 에 공백이 있으면 percent-encode 한다(계약 §A 형식).
ORIGIN_KINDS = (
    "agent:", "skill:", "plugin:", "command:", "hook:", "web:", "native")

# 분류 — 이 role 이 «봇이 수행하는 공정» 인가 «도구 래핑» 인가 (prj3#Issue636).
#   부재 = `bot`(기본). `tool` 은 **봇 계층 배분을 기대하지 않는다**는 선언이며, 개정
#   루프의 신호 기대가 여기서 갈린다(fbot-manual-review `role_kind`). 배분 0 이
#   «정상» 인지 «방치» 인지 구별되지 않던 것이 재분류가 답하는 질문이다.
KIND_VALUES = ("bot", "tool")


def validate_origin(value: str) -> str:
    """origin 값 검증 — 형식 위반은 fail-loud (prj3#Issue589).

    조용히 통과시키면 카탈로그 한 줄이 깨진 채 저장되고, 그 파손은 다음 `parse_catalog`
    에서야 엉뚱한 필드로 드러난다. 쓰기 시점에 막는 것이 유일하게 값싼 자리다.
    """
    v = (value or "").strip()
    if not v:
        raise RecruitError("origin 값이 비었다 — 재료 없는 신설은 `native` 로 명시한다")
    if v != value or any(c.isspace() for c in v) or '"' in v or "'" in v:
        raise RecruitError(
            f"origin 에 공백·따옴표 불가: {value!r} — 파서가 split() 기준이라 필드가 갈라진다"
            " (URL 은 percent-encode)")
    # prj3#Issue589 자체 검토 m3 — 값 안의 `status=archived` 부분문자열이 hr-gate 를
    #   오판시킨다. hr-gate 는 행 전체를 `"status=archived" not in line` 으로 보므로
    #   `web:…?status=archived` 같은 정상 URL 하나로 그 role 이 아카이브 취급된다.
    for k in ("status=", "manager=", "shape=", "base=", "label=", "tags=", "origin=",
              "kind="):
        if k in v:
            raise RecruitError(
                f"origin 값에 예약 키 {k!r} 불가: {value!r} — 소비처가 행 전체를 "
                "부분문자열로 판정한다(hr-gate). URL 이면 percent-encode")
    for part in v.split("|"):
        if not part:
            raise RecruitError(f"빈 출처 조각: {v!r} — `|` 구분자 주변을 확인하라")
        if not part.startswith(ORIGIN_KINDS):
            raise RecruitError(
                f"미정의 origin 종류: {part!r} — 허용 {', '.join(ORIGIN_KINDS)} (계약 §A)")
    return v


def parse_catalog(path=None) -> dict:
    """{role: {shape,base,label,tags[,status][,origin][,origin_seen]}} — generic kv 파서.

    fbot-icon `load_catalog` 와 동형이다. **키를 열거하지 않으므로** 필드가 늘어도
    파서 수정이 불요하다 — `origin`(prj3#Issue589)이 그 덕에 코드 변경 0으로 읽힌다.
    """
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


def set_field(path, role: str, key: str, value) -> None:
    """role 행의 임의 필드를 갱신한다(value=None → 제거). 다른 행·주석은 건드리지 않는다.

    prj3#Issue589 에서 `set_status` 를 일반화했다. 필드가 늘 때마다 같은 모양의 함수를
    복제하면 **행 재작성 규칙이 갈라진다** — 한쪽만 고쳐진 순간 다른 필드가 조용히
    유실된다. 재작성은 여기 한 곳이다.

    ⚠️ 미지정 필드는 원문 순서 그대로 보존된다. 갱신 대상 키만 빼고 뒤에 다시 붙이므로
       위치가 끝으로 옮겨질 뿐 값은 보존된다(archive→revive 왕복에서 origin 잔존 실측).

    🔴 그러나 **위치가 계약인 필드가 있다** (prj3#Issue589 자체 검토 m2) —
       `fbot-hr-gate.py` 는 `^(role): shape=… base=(#…)` 정규식으로 shape→base **순서를
       강제**한다. 그 둘을 끝으로 옮기면 정규식이 안 맞아 role 이 통째로 사라지고
       채용이 거부된다. 그래서 위치 의존 키는 아예 거부한다 — 필요해지면 hr-gate 를
       순서 비의존으로 먼저 고치는 것이 순서다.
    """
    if key in POSITIONAL_KEYS:
        raise RecruitError(
            f"위치 의존 필드는 set_field 로 옮기지 않는다: {key} — "
            f"hr-gate 정규식이 shape→base 순서를 강제한다(계약 F3). "
            f"순서 비의존으로 고친 뒤에 허용한다")
    roles = parse_catalog(path)
    if role not in roles:
        raise RecruitError(f"미등재 role: {role!r} — 허용값 {', '.join(sorted(roles))}")
    if key == "status" and value == "archived" and role in CORE_ROLES:
        raise RecruitError(
            f"상비 role 아카이브 불가: {role} — 조직 골격이라 비면 판정 주체가 사라진다 "
            f"(계약 §조직, 상비 4종: {', '.join(CORE_ROLES)})")
    out = []
    for line in open(path, encoding="utf-8"):
        raw = line.rstrip("\n")
        m = re.match(r"^([a-z0-9-]+):\s*(.+)$", raw.strip())
        if m and m.group(1) == role:
            fields = [kv for kv in m.group(2).split() if not kv.startswith(f"{key}=")]
            if value is not None:
                fields.append(f"{key}={value}")
            out.append(f"{role}: " + " ".join(fields))
        else:
            out.append(raw)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def set_status(path, role: str, status) -> None:
    """아카이브의 실체인 1줄 — `set_field` 의 얇은 별칭(호출처·테스트 호환).

    되돌리기(revive)가 1줄이라 판정이 다소 공격적이어도 손실이 없고, 그래서 개체 축과
    같은 안전 논리가 성립한다.
    """
    set_field(path, role, "status", status)


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── CLI ─────────────────────────────────────────────────────────────────────

def _org_module():
    """fbot-org.py — 자리 추가(`add_seat`)의 단일 원천. 호출 시점 env(FBOT_ORG_DIR·FBOT_CATALOG)를 따르도록 매번 적재한다."""
    import importlib.util
    sp = importlib.util.spec_from_file_location(
        "fbot_org_scout", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-org.py"))
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def apply_home(path, role: str, prj, dept: str = "dev") -> dict:
    """프로젝트 단위 발굴의 본거지 (prj3#Issue757 T13 사다리 ③) — 카탈로그 `home=<prj>` + 그 prj 조직 선언 자리.

    신설 직능은 **요청 prj 에 먼저** 선다. 다른 팀은 이후 사다리 ②(총괄 차용)로 쓰고, 총괄의 탐색(`fbot-org find`)은
    본거지를 1순위 후보로 낸다(plan 열린 질문 15 — prj42 슬라이드 선례)."""
    if role not in parse_catalog(path):
        raise RecruitError(f"미등재 role: {role} — 등재(register) 뒤에 본거지를 둔다")
    set_field(path, role, "home", str(int(prj)))
    out = _org_module().add_seat(int(prj), role, dept=dept, apply=True, note="발굴 등재 본거지")
    if not out.get("ok"):
        raise RecruitError(f"본거지 자리 추가 실패(prj{prj}): {out.get('error')}")
    return {"home": int(prj), "seat": out}


_AUTHOR_MARK_RE = re.compile(r"^<!-- fbot-manual-review:author=\S+ sha=[0-9a-f]{16} -->\n?", re.M)  # fbot-manual-review.py AUTHOR_RE 사본


def promote_draft(draft, manual):
    """`{role}.md.draft` → `{role}.md`. 기계 작성 표지 줄은 정본에 남기지 않는다. 정본이 있으면 거부(덮어쓰기 금지)."""
    if os.path.exists(manual):
        raise RecruitError(f"정본 존재: {manual} — 덮어쓰기 금지")
    with open(draft, encoding="utf-8") as fh:
        text = _AUTHOR_MARK_RE.sub("", fh.read())
    with open(manual, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.remove(draft)


def cmd_register(args) -> int:
    roles = parse_catalog()
    if args.role in roles:
        raise RecruitError(f"이미 등재된 role: {args.role} — 중복 등재 금지(부활은 revive)")
    manual = os.path.join(MANUAL_DIR, f"{args.role}.md")
    draft = manual + ".draft"
    promote = None
    if not os.path.exists(manual) and os.path.exists(draft):
        # prj3#Issue823_1 — writeguard 는 scout 에 `.md.draft` 만 연다(정본은 register 경유 계약).
        #   그 계약을 여기서 구현한다: draft → 정본 승격. 정본이 이미 있으면 이 분기에 안 들어온다
        #   (덮어쓰기 금지). 승인 근거 없는 승격은 «승인 전 등재 금지»(scout.md)의 코드 집행으로 거부.
        if not getattr(args, "approved_by", None):
            raise RecruitError(f"draft 승격 거부: {draft} — --approved-by <승인 근거 id> 필수 "
                               "(총괄 C 결정·mq ACK id, 승인 전 등재 금지)")
        promote = draft
    elif not os.path.exists(manual):
        # 절차 ①② 가 선행이다 — 매뉴얼 없는 등재는 "직능 정의 없이 이름만 있는" 상태
        raise RecruitError(f"매뉴얼 부재: {manual} — 등록 절차 ①② 선행 (계약 §직능 카탈로그)")
    cmd = [sys.executable, ICON_GEN, "add-role", args.role,
           "--shape", args.shape, "--base", args.base, "--label", args.label]
    if args.tags:
        cmd += ["--tags", args.tags]
    # prj3#Issue589 — 출처를 등재 시점에 박는다. 나중에 채우려 하면 *"이 핀봇이 무엇에서
    #   왔는가"* 를 기억하는 사람이 이미 없다. 미지정은 fail-loud 로 막지 않고 `native`
    #   로 기록한다 — 재료 부재는 실패가 아니다(계약 §E).
    origin = validate_origin(args.origin) if args.origin else "native"
    cmd += ["--origin", origin]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RecruitError(f"카탈로그 등재 실패: {(r.stderr or r.stdout).strip()}")
    g = subprocess.run([sys.executable, ICON_GEN, "gen", "--role", args.role, "--json"],
                       capture_output=True, text=True)
    if g.returncode != 0:
        raise RecruitError(f"아이콘 생성 실패: {(g.stderr or g.stdout).strip()}")
    if promote:
        promote_draft(draft, manual)
    home = apply_home(CATALOG_PATH, args.role, args.home, args.home_dept) if getattr(args, "home", None) is not None else None
    emit({"ok": True, "action": "register", "role": args.role,
          "manual": manual, **({"promoted_from": draft, "approved_by": args.approved_by} if promote else {}), "icon": json.loads(g.stdout.strip().splitlines()[-1]),
          **({"home": home} if home else {}),
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


def cmd_set_kind(args) -> int:
    """role 분류 기입 — `tool` 은 «도구 래핑» 재분류 (prj3#Issue636).

    🔴 **엔트리를 지우지 않는다.** 도구로 판정된 role 을 카탈로그에서 빼면 *"왜 이것이
      봇이 아닌가"* 의 근거가 함께 사라져 **같은 승격이 다시 올라온다**. 남은 표시가
      다음 발굴에게 하는 답이며, 그것이 재분류의 실체다(아카이브와 다른 축이다 —
      아카이브는 *"안 쓴다"*, 재분류는 *"봇으로 쓸 것이 아니다"*).

    ⚠️ **배분을 막지 않는다.** `lead dispatch --role R` 명시 배분 경로는 그대로 산다 —
      봇 경유 조건 3종(동시 다발·장기 실행·2회 실패 에스컬레이션)에 걸리면 도구 role
      에도 봇이 붙는다. 막는 순간 그 조건이 표현 불가능해진다.

    ⚠️ `origin` 2원화는 **유지**한다 — 도구에도 drift 감지는 유효하다(prj3#Issue634 성과).
    """
    roles = parse_catalog()
    if args.role not in roles:
        raise RecruitError(f"미등재 role: {args.role!r} — 허용값 {', '.join(sorted(roles))}")
    if args.kind not in KIND_VALUES:
        raise RecruitError(
            f"미정의 분류: {args.kind!r} — 허용 {', '.join(KIND_VALUES)} "
            "(`bot` 은 기본값이라 필드를 지운다)")
    # 기본값은 필드 부재로 표현한다 — `kind=bot` 12줄을 깔면 신호가 아니라 잡음이 된다
    set_field(CATALOG_PATH, args.role, "kind", None if args.kind == "bot" else args.kind)
    emit({"ok": True, "action": "set-kind", "role": args.role, "kind": args.kind,
          "note": "표시만 바뀐다 — 배분·채용·drift 감지 경로는 전부 그대로다"})
    return 0


def cmd_set_origin(args) -> int:
    """기존 role 의 출처를 기입·갱신한다 (prj3#Issue589).

    `register` 는 신설 시점에만 쓰므로 **이미 등재된 12종을 소급 기입할 경로가 없었다.**
    스킬은 `catalog.yml` 직접 Edit 이 금지라(카탈로그 쓰기 단일 지점) 이 명령이 없으면
    소급 기입 자체가 불가능하다.

    `origin_seen` 은 *"이 시점의 원본을 봤다"* 는 선언이다 — drift 판정의 기준선이며,
    매뉴얼 mtime 을 기준선으로 쓰면 `reject` 가 그것을 갱신하지 않아 같은 draft 가
    매주 재생성된다(prj3#Issue518 이 경계한 폭주). 그래서 기준선을 **명시 필드로 분리**한다.
    """
    roles = parse_catalog()
    if args.role not in roles:
        raise RecruitError(f"미등재 role: {args.role} — 허용값 {', '.join(sorted(roles))}")
    origin = validate_origin(args.origin)
    set_field(CATALOG_PATH, args.role, "origin", origin)
    # 🔴 기준선은 **명시적으로 대조했을 때만** 기입한다 (prj3#Issue589).
    #   `--reconciled` 없이 출처만 적는 것은 *"원본이 무엇인지"* 를 말한 것이지
    #   *"매뉴얼이 그 원본과 맞다"* 를 말한 것이 아니다. 기본값으로 현재 해시를 굽으면
    #   **대조한 적 없는 것을 대조했다고 선언**하게 되고, 실재하는 drift 가 지워진다.
    #   미기입 = 미대조 → 다음 review 가 drift 를 띄우고, 사람이 apply/reject 하는
    #   순간 기준선이 잡힌다. 노이즈가 아니라 **아직 아무도 안 본 것의 정직한 표시**다.
    seen = args.seen if args.seen else (origin_digest(origin) if args.reconciled else None)
    if seen is not None:
        set_field(CATALOG_PATH, args.role, "origin_seen", seen)
    else:
        set_field(CATALOG_PATH, args.role, "origin_seen", None)   # 남아 있던 값 제거
    emit({"ok": True, "action": "set-origin", "role": args.role,
          "origin": origin, "origin_seen": seen,
          "note": "origin_seen 미기입 = 미대조(다음 review 가 drift 를 띄운다). apply·reject 가 대조 시점에 기준선을 잡는다"})
    return 0


def manual_mtime(role: str):
    """role 매뉴얼의 mtime — drift 기준선의 기본값. 부재면 None."""
    p = os.path.join(MANUAL_DIR, f"{role}.md")
    return int(os.path.getmtime(p)) if os.path.exists(p) else None


def _plugin_install_path(marketplace: str, name: str) -> str:
    """plugin 원본 1개를 결정론적으로 고른다 (prj3#Issue833).

    marketplace 원본 호환을 우선하고, 설치 manifest 의 실존 경로, cache 버전 순으로
    내린다. cache 폴백은 클론·rsync 에서 흔들리는 mtime 대신 이름만 사용한다.
    """
    marketplace_path = os.path.join(
        SCAR_ROOT, "plugins", "marketplaces", marketplace, name)
    if os.path.exists(marketplace_path):
        return marketplace_path

    manifest_path = os.path.join(SCAR_ROOT, "plugins", "installed_plugins.json")
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {}
    plugins = manifest.get("plugins", {}) if isinstance(manifest, dict) else {}
    entries = plugins.get(f"{name}@{marketplace}", []) if isinstance(plugins, dict) else []
    installed = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            install_path = entry.get("installPath")
            if isinstance(install_path, str) and os.path.exists(install_path):
                installed.append((str(entry.get("lastUpdated") or ""), install_path))
    if installed:
        return max(installed)[1]

    cache_root = os.path.join(SCAR_ROOT, "plugins", "cache", marketplace, name)
    try:
        versions = [
            entry for entry in os.listdir(cache_root)
            if os.path.isdir(os.path.join(cache_root, entry))
        ]
    except OSError:
        versions = []
    if versions:
        # (prj3#Issue833) 전부 점 구분 정수일 때만 정수 튜플 비교한다. 하나라도 해시 등
        # 다른 형식이면 이름 정렬로 고정해 mtime 복제·동기화 차이를 배제한다.
        if all(all(piece.isdigit() for piece in version.split("."))
               for version in versions):
            selected = max(versions, key=lambda version: tuple(
                int(piece) for piece in version.split(".")))
        else:
            selected = max(versions)
        return os.path.join(cache_root, selected)

    # 종전 호출측 규약: 부재 경로를 돌려 digest 가 None 으로 판정하게 한다.
    return marketplace_path


def origin_source_paths(origin: str) -> list:
    """origin 값 → 로컬 원본 파일 경로들. `web:`·`native` 는 빈 목록(원본이 없다)."""
    paths = []
    for part in (origin or "").split("|"):
        if part.startswith("agent:"):
            paths.append(os.path.join(SCAR_ROOT, "agents", part[6:] + ".md"))
        elif part.startswith("skill:"):
            paths.append(os.path.join(SCAR_ROOT, "skills", part[6:], "SKILL.md"))
        elif part.startswith("plugin:"):
            marketplace, separator, name = part[7:].partition("/")
            if separator and marketplace and name:
                paths.append(_plugin_install_path(marketplace, name))
            else:
                paths.append(os.path.join(
                    SCAR_ROOT, "plugins", "marketplaces", part[7:]))
        elif part.startswith("command:"):
            paths.append(os.path.join(SCAR_ROOT, "commands", part[8:] + ".md"))
        elif part.startswith("hook:"):
            paths.append(os.path.join(SCAR_ROOT, "hooks", part[5:]))
    return paths


def origin_digest(origin: str):
    """로컬 원본들의 **내용 해시**(sha256 앞 16자). 원본이 전부 부재면 None.

    🔴 **mtime 이 아니라 내용이다** (prj3#Issue589 자체 검토 M4 — 첫 구현은 mtime 이었다).
      mtime 기준선은 세 방향으로 틀린다:
        · **클론·rsync** 하면 소비자 머신에서 전 원본 mtime 이 현재 시각이 되어
          비 native role 이 **전건 동시 오탐** → 월요일 tick 이 `[컨펌]` 다발을 낸다
        · 내용이 같은 재저장(touch)도 drift 로 잡힌다
        · 내용이 달라도 mtime 이 안 움직이면 놓친다
      실측으로도 드러났다 — 매뉴얼에 한 줄 추가했더니 기준선(당시 매뉴얼 mtime)이
      원본보다 새로워져 **실재하던 igmaker drift 가 소실**됐다.

    ⚠️ 경로를 함께 해싱한다 — 복수 출처에서 파일이 뒤바뀌는 것도 변경이다.
    ⚠️ 디렉토리(plugin:)는 하위 파일을 정렬 순회한다. 디렉토리 mtime 은 직속 엔트리
       추가·삭제에만 반응해 **내부 수정에 침묵**하기 때문이다.
    """
    h = hashlib.sha256()
    found = False
    for p in origin_source_paths(origin):
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                for fn in sorted(files):
                    fp = os.path.join(root, fn)
                    try:
                        h.update(os.path.relpath(fp, p).encode("utf-8"))
                        h.update(open(fp, "rb").read())
                        found = True
                    except OSError:
                        continue
        elif os.path.exists(p):
            try:
                h.update(os.path.basename(p).encode("utf-8"))
                h.update(open(p, "rb").read())
                found = True
            except OSError:
                continue
    return h.hexdigest()[:16] if found else None


def cmd_list(args) -> int:
    roles = parse_catalog()
    emit({"ok": True, "action": "list", "count": len(roles),
          "roles": [{"role": r, "label": f.get("label", ""),
                     "status": f.get("status", "active"),
                     "kind": f.get("kind", "bot"),
                     "origin": f.get("origin"), "origin_seen": f.get("origin_seen"),
                     "core": r in CORE_ROLES} for r, f in sorted(roles.items())]})
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="fbot 발굴 집행 코어 — 직능(카탈로그) 축 전용")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("register", help="④⑤ 카탈로그 등재+아이콘 — 사람 승인(③) 후에만")
    sp.add_argument("--role", required=True)
    sp.add_argument("--shape", required=True)
    sp.add_argument("--base", required=True, help="#rrggbb")
    sp.add_argument("--label", required=True)
    sp.add_argument("--tags", default=None)
    sp.add_argument("--origin", default=None,
                    help="재료 출처 — agent:N|skill:N|plugin:M/N|command:N|hook:N|web:URL|native "
                         "(생략 시 native. 복수는 '|' 구분, 공백·따옴표 불가)")
    sp.add_argument("--home", type=int, default=None,
                    help="프로젝트 단위 발굴의 본거지 prj — 카탈로그 home= + 그 prj 조직 선언 자리 (prj3#Issue757 T13)")
    sp.add_argument("--home-dept", default="dev", help="본거지 자리 부서(기본 dev)")
    sp.add_argument("--approved-by", default=None,
                    help="③ 승인 근거 id(총괄 C 결정·mq ACK id) — draft(`{role}.md.draft`) 승격 등재에 필수 (prj3#Issue823_1)")
    sp.set_defaults(func=cmd_register)

    sp = sub.add_parser("set-origin",
                        help="기존 role 의 출처 기입·갱신 (소급 기입 경로, prj3#Issue589)")
    sp.add_argument("--role", required=True)
    sp.add_argument("--origin", required=True,
                    help="재료 출처 — agent:N|skill:N|plugin:M/N|command:N|hook:N|web:URL|native "
                         "(복수는 '|' 구분, 공백·따옴표 불가)")
    sp.add_argument("--seen", default=None,
                    help="drift 기준선 해시를 직접 지정 (보통 쓰지 않는다)")
    sp.add_argument("--reconciled", action="store_true",
                    help="매뉴얼이 **현재 원본과 맞음을 확인했다**는 선언 — 이때만 기준선을 "
                         "현재 해시로 기입한다. 생략하면 미대조로 남아 다음 review 가 drift 를 띄운다")
    sp.set_defaults(func=cmd_set_origin)

    sp = sub.add_parser("archive", help="직능 아카이브 — 기본 dry-run, --apply --role 로 1건 집행")
    sp.add_argument("--role", default=None)
    sp.add_argument("--apply", action="store_true")
    sp.set_defaults(func=cmd_archive)

    sp = sub.add_parser("revive", help="부활 — status 제거 1줄")
    sp.add_argument("--role", required=True)
    sp.set_defaults(func=cmd_revive)

    sp = sub.add_parser("set-kind",
                        help="분류 기입 — tool=도구 재분류(표시만·배분 불변, prj3#Issue636)")
    sp.add_argument("--role", required=True)
    sp.add_argument("--kind", required=True, choices=KIND_VALUES,
                    help="tool=도구 래핑(배분 0 이 정상) · bot=공정 role(필드 제거)")
    sp.set_defaults(func=cmd_set_kind)

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
