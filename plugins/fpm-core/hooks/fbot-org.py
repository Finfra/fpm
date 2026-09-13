#!/usr/bin/env python3
"""fbot-org.py — 조직 선언 해소기 (prj3#Issue538)

조직도를 **런타임 관계의 파생물**에서 **선언된 구조**로 바꾸는 부품이다. 자리(seat)는
개체(bot)와 독립적으로 존재하므로, 봇이 전부 퇴근해도 조직도가 선다.

해소 순서 3단 — 뒤가 앞을 이긴다:
  ① `_template/{type}.yml`   타입별 기본 조직
  ② `org/{N}.yml`            중앙 인스턴스 (`extends` 로 ①을 가리킨다)
  ③ `{prj}/.claude/fbot.yml` 의 `org:` 키   repo override

🔴 **병합 단위는 자리(seat) 하나다.** 같은 `seat_id` 면 통째로 교체하고 부분 필드 머지는
하지 않는다 — 섞이면 `role` 은 중앙 것, 나머지는 템플릿 것이 되어 **어느 선언이 유효한지
추적할 수 없다**. 삭제는 `drop: true` 명시로만 하고 암묵적 소거를 허용하지 않는다.

⚠️ **repo override 는 새 파일이 아니라 기존 `.claude/fbot.yml` 의 `org:` 키다.**
`fbot.yml` 은 워크플로우 어댑터 선택값(`workflow: nptir|kanban`)을 이미 소유한다.
새 파일을 만들면 per-prj 봇 설정이 두 곳으로 갈린다.

설계 SSOT: `_doc_arch/fbot-org-design.md`
"""
import argparse
import json
import os
import sys

try:
    import yaml
except ImportError:
    print(json.dumps({"ok": False, "error": "PyYAML 미설치 — 해소 불가"}), file=sys.stderr)
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# env knob 3종 — 스모크가 실제 선언·실제 대장을 건드리지 않게 한다(schedule-smoke 선례).
#   운영에서는 셋 다 미설정이므로 기본 경로가 그대로 쓰인다.
ORG_DIR = os.environ.get("FBOT_ORG_DIR") or os.path.join(ROOT, "data", "fbot", "org")
def _pm_projects_default():
    """prj 번호 → 경로 SSOT 디렉토리. env → install.sh 가 기록한 `~/.info/__pmBasePath.txt`
    (fbot-lead.py PM_BASE_FILE 와 동일) → jm4 관행 경로 순 (prj3#Issue559 — 번들 이식성)."""
    v = os.environ.get("FBOT_PM_PROJECTS")
    if v:
        return v
    try:
        with open(os.path.join(os.path.expanduser("~"), ".info", "__pmBasePath.txt"), encoding="utf-8") as fh:
            b = fh.read().strip()
            if b:
                return os.path.expanduser(os.path.expandvars(b))
    except OSError:
        pass
    return os.path.expanduser("~/_git/___pm/projects")


PM_PROJECTS = _pm_projects_default()
REGISTRY_DB = os.environ.get("FBOT_REGISTRY_DB") or os.path.join(
    # prj3#Issue559 — fbot-state.py 와 같은 해석(AOA_MEMORY_DIR → ~/.claude/data/aoa). 개인 경로 하드코딩은
    #   번들로 나가는 순간 타 머신에서 "DB 없음" 이 된다.
    os.environ.get("AOA_MEMORY_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa"),
    "registry.db")
CATALOG = os.environ.get("FBOT_CATALOG") or os.path.join(
    ROOT, "data", "fbot", "icons", "catalog.yml")


def catalog_attrs():
    """카탈로그 role → 속성 dict. 평탄 형식 `{role}: k=v k=v …` 를 그대로 읽는다."""
    out = {}
    if not os.path.exists(CATALOG):
        return out
    with open(CATALOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, _, rest = line.partition(":")
            k = k.strip()
            if not k or " " in k:
                continue
            attrs = {}
            for tok in rest.split():
                if "=" in tok:
                    a, _, b = tok.partition("=")
                    attrs[a] = b
            out[k] = attrs
    return out


def is_manager(role):
    """매니저 판정 — **명령 인박스를 갖는가** (prj3#Issue552).

    🔴 상비봇(`CORE_ROLES`)과 **다른 축**이다. 상비는 *아카이브 제외* 판정이고
    매니저는 *명령 수신* 판정이다 — `recruit` 는 상비이나 매니저가 아니다(HR 이
    넘긴 일을 **수행**하지 조율하지 않는다).

    ⚠️ 미등재 role 은 `False`(fail-safe). 기본이 True 면 아무 봇이나 인박스를 갖게
    되어 요청이 워커에 직접 꽂히고, 그러면 이 설계의 목적(워커의 집중)이 무너진다.
    """
    return (catalog_attrs().get(role or "", {}).get("manager") or "").lower() == "true"


def catalog_roles():
    """카탈로그 등재 role 집합. 형식: `{role}: shape=… base=… label=… tags=… [origin=…] [status=…]`
    (fbot-icon-gen.py 와 같은 평탄 형식 — PyYAML 로 읽으면 값이 문자열이라 키만 쓴다)"""
    roles = set()
    if not os.path.exists(CATALOG):
        return roles
    with open(CATALOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k = line.split(":", 1)[0].strip()
            if k and " " not in k:
                roles.add(k)
    return roles


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def prj_path(prj):
    """prj 번호 → 경로. SSOT 는 ___pm/projects/{번호} 파일이다(경로를 추측하지 않는다)."""
    p = os.path.join(PM_PROJECTS, str(prj))
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return os.path.expanduser(f.read().strip())


def seat_addr(prj, seat_id):
    """자리의 **유일 주소**. `{scope}/{seat_id}` — scope 는 `hq` 또는 prj 번호.

    🔴 seat_id 만으로는 자리를 특정할 수 없다. 템플릿을 공유하므로 `dev-architect-1`
    이 19개 조직에 동시에 존재한다 — 실측(2026-09-05)에서 감사기가 자리 93개를 12개로
    셌고, 그 상태로 `bot.seat_id` 를 조인하면 **다른 프로젝트의 자리에 앉은 봇이
    정상으로 통과한다**. 주소에 scope 를 넣어 원천 차단한다.
    """
    return f"{'hq' if prj is None else prj}/{seat_id}"


def reports_addr(prj, reports_to):
    """선언 보고선을 **자리 주소**로 정규화한다 (prj3#Issue550).

    표기 2종 — `/` 가 없으면 같은 조직 안의 자리(`ops-lead-1`), 있으면 절대 주소
    (`hq/hq-lead-1`)다. 접두 기호를 따로 두지 않은 이유는 `seat_addr` 이 이미
    `{scope}/{seat}` 형식을 쓰고 있어 **슬래시 유무가 곧 스코프 유무**이기 때문이다.

    🔴 이것은 **자리 간** 선이지 개체 간 선이 아니다. 개체(봇)에 사영하는 것은 소비처의
    몫이며, 그래야 **봇이 전부 퇴근해도 골격이 선다**(§조직 관측 — Issue538 전환 취지).
    """
    if not reports_to:
        return ""
    r = str(reports_to).strip()
    return r if "/" in r else seat_addr(prj, r)


def _absorb(seats, doc, source):
    """자리 단위 교체. `drop: true` 는 제거. 부분 머지 없음."""
    for d in (doc.get("depts") or []):
        did = d.get("id")
        for s in (d.get("seats") or []):
            key = (did, s.get("id"))
            if s.get("drop"):
                seats.pop(key, None)
                continue
            seats[key] = dict(s, dept=did, dept_label=d.get("label") or did, source=source)


def resolve(prj=None):
    """prj=None 이면 본사(_hq.yml). 반환은 seat 목록 — **개체 정보는 섞지 않는다**."""
    central = os.path.join(ORG_DIR, "_hq.yml" if prj is None else f"{prj}.yml")
    doc = _load(central)
    if doc is None:
        return {"ok": True, "prj": prj, "seats": [], "reason": "조직 선언 없음"}

    seats = {}
    ext = doc.get("extends")
    if ext:
        base = _load(os.path.join(ORG_DIR, ext))
        if base is None:
            return {"ok": False, "prj": prj, "error": f"extends 대상 부재: {ext}"}
        _absorb(seats, base, "inherited")
    _absorb(seats, doc, "central")

    # ③ repo override — 없으면 완전 no-op
    dropped_missing = []
    if prj is not None:
        base_path = prj_path(prj)
        if base_path:
            ov = _load(os.path.join(base_path, ".claude", "fbot.yml"))
            org = (ov or {}).get("org")
            if org:
                for d in (org.get("depts") or []):
                    for s in (d.get("seats") or []):
                        if s.get("drop") and (d.get("id"), s.get("id")) not in seats:
                            dropped_missing.append(f"{d.get('id')}/{s.get('id')}")
                _absorb(seats, org, "override")

    _seats = []
    for st in seats.values():
        _seats.append(dict(st, addr=seat_addr(prj, st.get("id")),
                           reports_to_addr=reports_addr(prj, st.get("reports_to"))))
    return {"ok": True, "prj": prj, "title": doc.get("title"),
            "machine": doc.get("machine"), "seats": _seats,
            "archived": (doc.get("status") == "archived"),
            "alive": team_alive(prj),
            "stale_drops": dropped_missing}


IDLE_DAYS = int(os.environ.get("FBOT_ORG_IDLE_DAYS") or 3)
ALIVE_CAREERS = ("probation", "active")   # 호환 사영(career) 기준 — team_alive 는 employment 축을 본다(Issue551)


def team_alive(prj):
    """팀의 생사 — **그 팀 팀장핀봇의 career** 가 답한다.

    🔴 `state`(하루 축)를 보지 않는다. `checkout` 은 종료가 아니라 cold 이고
    (fbot-arch Issue498), 퇴근을 죽음으로 읽으면 매일 밤 전 조직이 사라진다.
    본사(prj=None)는 조직 골격이라 항상 살아 있다 — 상비 4종이 아카이브 제외인 것과
    같은 근거다.
    """
    if prj is None:
        return True
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return False
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(bot)")}
        if "seat_id" not in cols:
            return False
        # prj3#Issue551 — 재직 축이 답한다. employment 가 없는(백필 전) 행은 career 로 폴백
        rows = con.execute(
            "SELECT COALESCE(employment, CASE WHEN career IN ('leave','terminated') THEN career ELSE 'employed' END)"
            " FROM bot WHERE role='lead' AND seat_id LIKE ?",
            (f"{prj}/%",)).fetchall()
    except sqlite3.Error:
        return False
    finally:
        con.close()
    return any((r[0] or "") == "employed" for r in rows)   # 정직(suspended)·휴직·해고는 팀 비활성


def _org_files():
    """선언된 prj 조직 목록. `_hq`·`_template` 은 생명주기 대상이 아니다 —
    본사는 조직 골격이라 쉬지 않는다(상비 4종이 아카이브 제외인 것과 같은 이유)."""
    if not os.path.isdir(ORG_DIR):
        return []
    out = []
    for f in sorted(os.listdir(ORG_DIR)):
        if f.endswith(".yml") and f[:-4].isdigit():
            out.append(int(f[:-4]))
    return out


def last_activity(prj):
    """프로젝트의 마지막 활동(epoch). git 마지막 커밋을 쓴다 — job 원장은 대부분의
    prj 에서 0건이라 판정 근거가 못 된다(실측). 없으면 None."""
    import subprocess
    base = prj_path(prj)
    if not base or not os.path.isdir(os.path.join(base, ".git")):
        return None
    try:
        r = subprocess.run(["git", "-C", base, "log", "-1", "--format=%ct"],
                           capture_output=True, text=True, timeout=10)
        return int(r.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def pm_bot(prj):
    """그 팀의 팀장핀봇 `bot_id`. 없으면 None."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None
    try:
        if "seat_id" not in {r[1] for r in con.execute("PRAGMA table_info(bot)")}:
            return None
        row = con.execute("SELECT bot_id FROM bot WHERE role='lead' AND seat_id LIKE ?",
                          (f"{prj}/%",)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def pm_last_activity(prj):
    """팀장핀봇의 **마지막 실행** 시각(epoch).

    세 원천의 최댓값이다 — 어느 하나만 보면 살아 있는 팀을 재운다:
      ① 그 봇 귀속 `job` 마지막 기록 — 봇이 실제로 일한 증거
      ② 프로젝트 git 마지막 커밋 — 사람이 그 프로젝트를 만진 증거. PM 은 그
         프로젝트를 대표하므로 프로젝트 활동은 곧 그 팀의 활동이다
      ③ 봇 `created_at` — 채용 직후 아무 기록도 없는 구간의 하한. 이것이 없으면
         **갓 채용한 팀이 즉시 휴직 대상**이 된다
    """
    import sqlite3
    ts = []
    bid = pm_bot(prj)
    if bid:
        try:
            con = sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True, timeout=1.0)
            try:
                r = con.execute("SELECT MAX(created_at) FROM job WHERE owner=?", (bid,)).fetchone()
                if r and r[0]:
                    ts.append(int(r[0]))
                r = con.execute("SELECT created_at FROM bot WHERE bot_id=?", (bid,)).fetchone()
                if r and r[0]:
                    ts.append(int(r[0]))
            finally:
                con.close()
        except sqlite3.Error:
            pass
    g = last_activity(prj)
    if g:
        ts.append(g)
    return max(ts) if ts else None


def sweep(apply=False, idle_days=None):
    """유휴 팀장핀봇을 **휴직**시킨다 — 그러면 그 팀이 조직도에서 사라진다.

    🔴 아카이브 대상은 조직이 아니라 **PM 개체**다. `org.status` 별도 축을 두면
    봇 career 와 두 벌이 되어 갈라진다(Issue538 개정). 해고가 아니라 휴직이므로
    배분 한 건으로 되돌아온다.
    """
    import subprocess
    import time
    days = IDLE_DAYS if idle_days is None else idle_days
    now = time.time()
    cands, kept = [], 0
    for prj in _org_files():
        bid = pm_bot(prj)
        if not bid:
            continue
        got = resolve(prj)
        if not got.get("alive"):
            kept += 1
            continue
        ts = pm_last_activity(prj)
        idle = None if ts is None else round((now - ts) / 86400, 1)
        if idle is not None and idle > days:
            cands.append({"prj": prj, "title": got.get("title"), "pm": bid,
                          "idle_days": idle})
    applied, errs = [], []
    if apply:
        for c in cands:
            r = subprocess.run(
                ["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "fbot-state.py"),
                 "career", "--bot-id", c["pm"], "--to", "leave",
                 "--reason", f"유휴 {c['idle_days']}일 > 임계 {days}일 (Issue538 조직 sweep)"],
                capture_output=True, text=True)
            (applied if r.returncode == 0 else errs).append(
                c["pm"] if r.returncode == 0 else {"pm": c["pm"], "err": (r.stdout or r.stderr)[:120]})
    return {"ok": not errs, "action": "sweep", "mode": "집행" if apply else "판정만",
            "idle_days_threshold": days, "candidates": cands,
            "already_asleep": kept, "applied": applied, "errors": errs,
            "next": None if apply else "집행은 --apply"}


def wake(prj, reason=""):
    """팀 부활 — 팀장핀봇을 휴직에서 복귀시킨다.

    🔴 **호출 지점은 배분 1곳이다.** 조직도 렌더나 hub 요청이 부활시키면 관측이
    상태를 바꾸는 것이라 원장이 거짓말을 시작한다.
    """
    import subprocess
    bid = pm_bot(prj)
    if not bid:
        return {"ok": True, "action": "wake", "prj": prj, "changed": False,
                "note": "PM 미배치 — 부활할 팀이 없다(채용이 먼저다)"}
    if resolve(prj).get("alive"):
        return {"ok": True, "action": "wake", "prj": prj, "changed": False,
                "note": "이미 활성"}
    r = subprocess.run(
        ["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-state.py"),
         "career", "--bot-id", bid, "--to", "active",
         "--reason", reason or "배분 도착 — 팀 부활(Issue538)"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "error": (r.stdout or r.stderr)[:160]}
    return {"ok": True, "action": "wake", "prj": prj, "pm": bid, "changed": True}


def bind(bot_id, seat_id, prj=None, apply=False):
    """개체를 자리에 앉힌다. **자리 실재를 먼저 확인**한다 — 없는 자리를 가리키면 조직도에서
    고아가 되고, 그것은 감사기가 잡아야 할 오류이지 만들어도 되는 상태가 아니다."""
    import sqlite3
    got = resolve(prj)
    if not got.get("ok"):
        return {"ok": False, "error": got.get("error")}
    _addr = seat_id if "/" in seat_id else seat_addr(prj, seat_id)
    if _addr not in {s["addr"] for s in got["seats"]}:
        return {"ok": False, "error": f"자리 부재: {_addr}"}
    con = sqlite3.connect(REGISTRY_DB)
    try:
        row = con.execute("SELECT bot_id FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
        if not row:
            return {"ok": False, "error": f"대장에 없는 개체: {bot_id}"}
        if not apply:
            return {"ok": True, "mode": "dry-run", "bot_id": bot_id, "seat_id": _addr,
                    "next": "집행은 --apply"}
        con.execute("UPDATE bot SET seat_id=? WHERE bot_id=?", (_addr, bot_id))
        con.commit()
        return {"ok": True, "mode": "집행", "bot_id": bot_id, "seat_id": _addr}
    finally:
        con.close()


def check_pm():
    """PM 필수 전제 검사 (prj3#Issue609) — 선언된 모든 prj 에 **재직 중인 PM** 이 있는가.

    왜 필요한가: Issue608 이 *"총괄은 PM 을 거친다"* 를 강제하므로, **PM 부재 = 그 prj 작업 불가**다.
    전제가 깨지면 가드가 막다른 길이 된다. 조직도에는 공석으로 보이지만
    *"PM 만은 공석이면 안 된다"* 는 판정은 어디에도 없었다(레지스트리 감사는 정합성만 본다).

    ⚠️ `employment='employed'` 를 본다 — 개체가 있어도 휴직이면 없는 것과 같다.
       실측(2026-09-09): prj13·40·42·57 PM 4명이 상비 판정 결함으로 `leave` 였다.
    """
    # 읽기 전용 접속 — 감사는 쓰지 않는다(다른 조회 지점과 같은 방식: 지역 import)
    import sqlite3
    con = sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True, timeout=1.0)
    con.row_factory = sqlite3.Row
    try:
        pm = {}
        for row in con.execute(
                "SELECT bot_id, prj, COALESCE(employment,'employed') AS emp, state "
                "FROM bot WHERE role='lead' AND prj IS NOT NULL"):
            pm.setdefault(int(row["prj"]), []).append(dict(row))
    finally:
        con.close()
    ok_list, missing = [], []
    # 조직 목록 원천은 `list` 와 같다 — ORG_DIR 의 선언 파일명(갈리면 두 화면이 다른 조직을 말한다)
    _declared = sorted(f[:-4] for f in os.listdir(ORG_DIR) if f.endswith(".yml"))
    for prj in _declared:
        try:
            n = int(prj)
        except (TypeError, ValueError):
            continue
        live = [b for b in pm.get(n, []) if b["emp"] == "employed"]
        if live:
            ok_list.append({"prj": n, "bot_id": live[0]["bot_id"], "state": live[0]["state"]})
        else:
            held = pm.get(n, [])
            missing.append({"prj": n,
                            "reason": ("휴직/정직 — " + held[0]["emp"]) if held else "개체 없음",
                            "bot_id": held[0]["bot_id"] if held else None})
    return {"ok": not missing, "declared": len(ok_list) + len(missing),
            "staffed": len(ok_list), "missing": missing, "staffed_list": ok_list}


def main(argv=None):
    ap = argparse.ArgumentParser(description="조직 선언 해소기 (Issue538)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="prj 조직 해소 (생략 시 본사)")
    r.add_argument("--prj", type=int, default=None)
    sub.add_parser("list", help="선언된 조직 목록")
    sub.add_parser("check-pm", help="PM 필수 전제 검사 — 재직 PM 없는 prj 를 찾는다 (Issue609)")
    sw = sub.add_parser("sweep", help="유휴 조직 아카이브 (판정만이 기본)")
    sw.add_argument("--apply", action="store_true")
    sw.add_argument("--idle-days", type=int, default=None)
    wk = sub.add_parser("wake", help="조직 부활 — 배분 발생 시 호출")
    wk.add_argument("--prj", type=int, required=True)
    wk.add_argument("--reason", default="")
    b = sub.add_parser("bind", help="개체를 자리에 결속")
    b.add_argument("--bot-id", required=True)
    b.add_argument("--seat-id", required=True)
    b.add_argument("--prj", type=int, default=None)
    b.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "resolve":
        out = resolve(a.prj)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1
    if a.cmd == "check-pm":
        out = check_pm()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else 1        # 부재가 있으면 rc=1 — 감사·CI 가 실패로 잡는다
    if a.cmd == "sweep":
        out = sweep(a.apply, a.idle_days)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "wake":
        out = wake(a.prj, a.reason)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1
    if a.cmd == "bind":
        out = bind(a.bot_id, a.seat_id, a.prj, a.apply)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1
    if a.cmd == "list":
        names = sorted(f[:-4] for f in os.listdir(ORG_DIR) if f.endswith(".yml"))
        print(json.dumps({"ok": True, "orgs": names}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
