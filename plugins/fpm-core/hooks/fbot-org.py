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

설계 SSOT: `_doc_arch/fbot-org.md`
"""
import argparse
import json
import re
import os
import sqlite3
import sys

try:
    import yaml
except ImportError:
    print(json.dumps({"ok": False, "error": "PyYAML 미설치 — 해소 불가"}), file=sys.stderr)
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# env knob 3종 — 스모크가 실제 선언·실제 대장을 건드리지 않게 한다(schedule-smoke 선례).
#   운영에서는 셋 다 미설정이므로 기본 경로가 그대로 쓰인다.
# 조직 선언 폴더 (prj3#Issue757 — 사용자 결정 2026-09-28 «번들에서 개인 선언 제거 + 로컬 선언 폴백»)
#   prj 별 선언(N.yml)은 **사용자 데이터**다. 플러그인 번들은 골격(`_hq.yml`·`_template/*`)만 싣는다.
#   ① `FBOT_ORG_DIR`(스모크 격리) — 그 폴더 하나, 폴백 없음
#   ② 사용자 폴더 `~/.claude/data/fbot/org` — 쓰기·목록 1순위. 없는 파일은 ③ 으로 폴백(파일 단위로 덮는다)
#   ③ 번들(이 파일 위치 기준) — prj3 자체는 ②와 같은 경로라 동작이 바뀌지 않는다
_BUNDLE_ORG = os.path.join(ROOT, "data", "fbot", "org")
_USER_ORG = os.path.join(os.path.expanduser("~"), ".claude", "data", "fbot", "org")
_ORG_ENV = os.environ.get("FBOT_ORG_DIR")
ORG_DIR = _ORG_ENV or _USER_ORG


def _org_fallback() -> bool:
    return not _ORG_ENV and os.path.realpath(ORG_DIR) != os.path.realpath(_BUNDLE_ORG)


def _org_file(rel):
    """선언 파일 읽기 경로 — 사용자 폴더에 있으면 그것, 없으면 번들(폴백이 켜졌을 때만)."""
    p = os.path.join(ORG_DIR, rel)
    if os.path.exists(p) or not _org_fallback():
        return p
    b = os.path.join(_BUNDLE_ORG, rel)
    return b if os.path.exists(b) else p


def _declared_names():
    """선언 파일명(확장자 제외) — 사용자 폴더 ∪ 번들(폴백일 때). `list`·보드·감사가 같은 원천을 본다."""
    names = set()
    for d in ([ORG_DIR] + ([_BUNDLE_ORG] if _org_fallback() else [])):
        if os.path.isdir(d):
            names |= {f[:-4] for f in os.listdir(d) if f.endswith(".yml")}
    return sorted(names)
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
ENGINES = ("claude", "codex", "agy")
CONTINUITIES = ("lazy", "resume", "fresh")
PERMISSION_MODES = ("inherit", "floor", "bypass")
_PERMISSION_RANK = {"bypass": 0, "floor": 1}


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


def role_engines(role):
    """직능의 판정 엔진 집합. 열거 밖 값은 버리고, 남는 값이 없으면 claude 다."""
    raw = (catalog_attrs().get(role or "", {}).get("engine") or "")
    engines = {v for v in raw.split("|") if v in ENGINES}
    return engines or {"claude"}


def is_checker(role):
    """카탈로그의 검증 직능 표지."""
    return (catalog_attrs().get(role or "", {}).get("checker") or "").lower() == "true"


def role_permission_default(role):
    """직능별 기동 권한 기본값. 미등재·미기재·무효값은 현행 bypass 다."""
    mode = (catalog_attrs().get(role or "", {}).get("permission_mode") or "").lower()
    return mode if mode in _PERMISSION_RANK else "bypass"


def is_manager(role):
    """매니저 판정 — **명령 인박스를 갖는가** (prj3#Issue552).

    🔴 상비봇(`CORE_ROLES`)과 **다른 축**이다. 상비는 *아카이브 제외* 판정이고
    매니저는 *명령 수신* 판정이다 — `recruit` 는 상비이나 매니저가 아니다(HR 이
    넘긴 일을 **수행**하지 조율하지 않는다).

    ⚠️ 미등재 role 은 `False`(fail-safe). 기본이 True 면 아무 봇이나 인박스를 갖게
    되어 요청이 워커에 직접 꽂히고, 그러면 이 설계의 목적(워커의 집중)이 무너진다.
    """
    return (catalog_attrs().get(role or "", {}).get("manager") or "").lower() == "true"


def is_nonexec(role):
    """비실행 판정 — **일을 하지 않고 시키기만 하는 관리직인가** (prj3#Issue757).

    대상은 지휘 계통 둘(총괄·팀장)뿐이다. 배분 채널(지휘 지시문)·쓰기 가드·환기·인박스 발신 제한이
    모두 이 한 곳을 읽는다 — 판정 단일 지점.

    🔴 `is_manager` 와 **다른 축**이다. manager 는 *명령 수신*(인박스) 판정이라 `hr` 에도 붙어 있고,
    그것을 재사용하면 인사핀봇 배분에도 «직접 수행 금지» 지시문이 붙는다(codex plan 점검 high 1).
    ⚠️ 미등재 role 은 `False`(fail-safe) — 모르면 종전 동작(워커 취급)으로 둔다.
    """
    return (catalog_attrs().get(role or "", {}).get("nonexec") or "").lower() == "true"


def bot_nonexec(bot_id, con=None):
    """봇 단위 `is_nonexec` — 대장의 role 로 판정한다 (prj3#Issue951 — 훅이 FBOT_ID 만 들고 묻는 자리).

    대장에 없거나 DB 를 못 읽으면 `False`(fail-safe — `is_nonexec` 와 같은 방향: 모르면 워커 취급).
    """
    if not bot_id:
        return False
    with _Con(con) as c:
        if c is None:
            return False
        try:
            r = c.execute("SELECT role FROM bot WHERE bot_id = ?", (bot_id,)).fetchone()
        except sqlite3.Error:
            return False
    return bool(r) and is_nonexec(r[0])


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


def _ro_con():
    """레지스트리 읽기 전용 connection. 실패(DB 부재·잠금)는 None — 호출자가 fail-soft 한다 (prj3#Issue732)."""
    try:
        return sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None


class _Con:
    """`con=None` 관통 규약 (prj3#Issue732) — 주어지면 빌려 쓰고 닫지 않는다, 없으면 열고 닫는다.

    prj1 hub 가 조직 한 번 그리는 데 판정 함수들이 각자 connection 을 열어 **요청당 177회**
    (2026-09-27 실측)였고, 파일시스템 정체에서 그 수만큼 증폭됐다(prj1#Issue551). hub 는
    connection 하나를 열어 `resolve`·`team_formed` 에 관통시키고, CLI 단발 호출은 종전처럼
    스스로 연다 — 호출 계약이 바뀌지 않는다.
    """
    def __init__(self, con=None):
        self.given = con
        self.con = None

    def __enter__(self):
        self.con = self.given if self.given is not None else _ro_con()
        return self.con

    def __exit__(self, *a):
        if self.given is None and self.con is not None:
            self.con.close()


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


def _add_invalid(invalid, seat, field, value, reason):
    """같은 선언 오류를 해소 단계가 겹쳐도 한 번만 싣는다."""
    item = {"seat": seat, "field": field, "value": value, "reason": reason}
    if item not in invalid:
        invalid.append(item)


def _stricter_permission(left, right):
    return max((left, right), key=lambda v: _PERMISSION_RANK[v])


def _absorb(seats, doc, source, permission_modes=None, invalid=None):
    """자리 단위 교체. 단, permission_mode 의 엄격도만 층을 넘어 누적한다."""
    for d in (doc.get("depts") or []):
        did = d.get("id")
        for s in (d.get("seats") or []):
            key = (did, s.get("id"))
            if s.get("drop"):
                # permission_mode 누적은 지우지 않는다 — 지우면 repo override 가 «drop 뒤 bypass 재선언»으로
                #   앞 층 floor 를 풀 수 있다(prj3#Issue859_1). 자리가 사라지면 누적은 쓰이지 않을 뿐이다
                seats.pop(key, None)
                continue
            if permission_modes is not None:
                candidate = role_permission_default(s.get("role"))
                raw_mode = s.get("permission_mode")
                if "permission_mode" in s:
                    if raw_mode not in PERMISSION_MODES:
                        if invalid is not None:
                            _add_invalid(invalid, s.get("id"), "permission_mode", raw_mode,
                                         "열거값은 inherit|floor|bypass 다")
                    elif raw_mode in _PERMISSION_RANK:
                        candidate = _stricter_permission(candidate, raw_mode)
                        if not str(s.get("permission_reason") or "").strip() and invalid is not None:
                            _add_invalid(invalid, s.get("id"), "permission_reason",
                                         s.get("permission_reason", ""),
                                         f"permission_mode={raw_mode} 명시에는 사유가 필요하다")
                permission_modes[key] = _stricter_permission(
                    permission_modes.get(key, "bypass"), candidate)
            raw_continuity = s.get("continuity")
            if ("continuity" in s and raw_continuity not in CONTINUITIES
                    and invalid is not None):
                _add_invalid(invalid, s.get("id"), "continuity", raw_continuity,
                             "열거값은 lazy|resume|fresh 다")
            seats[key] = dict(s, dept=did, dept_label=d.get("label") or did, source=source)


def _cycle_nodes(edges):
    """한 자리당 checked_by 하나인 그래프에서 순환에 직접 속한 자리만 돌려준다."""
    state, cycles = {}, set()
    for start in edges:
        if state.get(start) == 2:
            continue
        path, positions, cur = [], {}, start
        while cur in edges and state.get(cur, 0) != 2:
            if cur in positions:
                cycles.update(path[positions[cur]:])
                break
            if state.get(cur) == 1:
                break
            state[cur] = 1
            positions[cur] = len(path)
            path.append(cur)
            cur = edges[cur]
        for node in path:
            state[node] = 2
    return cycles


def _target_scope(addr):
    scope, sep, target = str(addr or "").partition("/")
    if not sep or not target:
        return False, None, ""
    if scope == "hq":
        return True, None, target
    try:
        return True, int(scope), target
    except (TypeError, ValueError):
        return False, None, target


def _target_exists(addr, local, cache):
    if addr in local:
        return True
    valid, target_prj, target_id = _target_scope(addr)
    if not valid:
        return False
    if target_prj not in cache:
        got = resolve(target_prj, _check_checked_by=False)
        cache[target_prj] = {s.get("id") for s in got.get("seats") or []} if got.get("ok") else set()
    return target_id in cache[target_prj]


def resolve(prj=None, with_formed=False, con=None, _check_checked_by=True):
    """prj=None 이면 본사(_hq.yml). 반환은 seat 목록 — **개체 정보는 섞지 않는다**.

    `with_formed` — 구성 판정(`team_formed`, Issue689)을 싣는다. 활동 시각 계산에 git 조회가
    들어가므로 기본은 끈다(bind·wake 등 내부 호출이 비용을 내지 않게). 보드만 켠다.
    """
    central = _org_file("_hq.yml" if prj is None else f"{prj}.yml")
    doc = _load(central)
    if doc is None:
        # declared — 자리 판정 가능 여부(prj3#Issue821: 선언 없는 prj 의 dispatch 채용은 종전 허용)
        return {"ok": True, "prj": prj, "seats": [], "invalid": [],
                "reason": "조직 선언 없음", "declared": False}

    seats, permission_modes, invalid = {}, {}, []
    ext = doc.get("extends")
    if ext:
        base = _load(_org_file(ext))
        if base is None:
            return {"ok": False, "prj": prj, "error": f"extends 대상 부재: {ext}"}
        _absorb(seats, base, "inherited", permission_modes, invalid)
    _absorb(seats, doc, "central", permission_modes, invalid)

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
                _absorb(seats, org, "override", permission_modes, invalid)

    _seats, by_addr = [], {}
    for key, st in seats.items():
        raw_continuity = st.get("continuity")
        continuity = raw_continuity if raw_continuity in CONTINUITIES else "lazy"
        item = dict(st, addr=seat_addr(prj, st.get("id")),
                    reports_to_addr=reports_addr(prj, st.get("reports_to")),
                    continuity=continuity,
                    permission_mode=permission_modes.get(key, role_permission_default(st.get("role"))),
                    permission_reason=st.get("permission_reason", ""), checked_by_addr="")
        _seats.append(item)
        by_addr[item["addr"]] = item

    if _check_checked_by:
        valid_edges, target_cache = {}, {}
        for st in _seats:
            raw = st.get("checked_by")
            if not raw:
                continue
            target = reports_addr(prj, raw)
            if target == st["addr"]:
                _add_invalid(invalid, st.get("id"), "checked_by", raw, "자기 자신을 가리킨다")
            elif not _target_exists(target, by_addr, target_cache):
                _add_invalid(invalid, st.get("id"), "checked_by", raw, "대상 자리가 없다")
            else:
                st["checked_by_addr"] = target
                if target in by_addr:
                    valid_edges[st["addr"]] = target
        for addr in _cycle_nodes(valid_edges):
            st = by_addr[addr]
            _add_invalid(invalid, st.get("id"), "checked_by", st.get("checked_by"), "검증선 순환")
            st["checked_by_addr"] = ""
    else:
        for st in _seats:
            if st.get("checked_by"):
                st["checked_by_addr"] = reports_addr(prj, st.get("checked_by"))
    return {"ok": True, "prj": prj, "title": doc.get("title"),
            "machine": doc.get("machine"), "seats": _seats,
            # prj3#Issue734 — 본사 개체(prj=NULL)의 몸체 cwd. 인박스 기상 스폰이 fpm-do 창을 여기 연다
            "body_prj": doc.get("body_prj"),
            "archived": (doc.get("status") == "archived"),
            "alive": team_alive(prj, con=con),
            **({"formed_info": team_formed(prj, con=con)} if with_formed else {}),
            "stale_drops": dropped_missing, "invalid": invalid}


IDLE_DAYS = int(os.environ.get("FBOT_ORG_IDLE_DAYS") or 3)
ALIVE_CAREERS = ("probation", "active")   # 호환 사영(career) 기준 — team_alive 는 employment 축을 본다(Issue551)


def team_alive(prj, con=None):
    """팀의 생사 — **그 팀 팀장핀봇의 career** 가 답한다.

    🔴 `state`(하루 축)를 보지 않는다. `checkout` 은 종료가 아니라 cold 이고
    (fbot-arch Issue498), 퇴근을 죽음으로 읽으면 매일 밤 전 조직이 사라진다.
    본사(prj=None)는 조직 골격이라 항상 살아 있다 — 상비 4종이 아카이브 제외인 것과
    같은 근거다.
    """
    if prj is None:
        return True
    with _Con(con) as c:
        if c is None:
            return False
        try:
            rows = _lead_rows(c, prj)
        except sqlite3.Error:
            return False
    return any(r[1] == "employed" for r in rows)   # 정직(suspended)·휴직·해고는 팀 비활성


def _lead_rows(con, prj):
    """그 prj 의 팀장핀봇 행 `[(bot_id, employment), …]` — **팀장 판정 단일 지점** (Issue689).

    🔴 `team_alive`·`pm_bot`·`check_pm` 이 전부 여기를 거친다. 예전엔 앞의 둘은 자리
    (`seat_id LIKE 'N/%'`)를, 뒤의 하나는 `prj` 열을 봤다. 채용 경로가 자리를 안 채운
    팀장(`fbot-lead-cg`, 2026-09-24)이 생기자 «팀장 있음»(check-pm)과 «팀 죽음»(보드)이
    동시에 참이 되어 prj7 이 보드에서 사라졌다.
    판정: 자리가 `N/…` 인 lead, 또는 **자리가 비었고** `prj=N` 인 lead. 자리 있는 쪽이 앞선다.
    자리가 다른 prj 를 가리키는 lead 는 prj 열이 N 이어도 N 의 팀장이 아니다(자리가 이긴다).
    employment 가 없는(백필 전) 행은 career 로 폴백한다(prj3#Issue551).
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info(bot)")}
    if "seat_id" not in cols:
        return []
    return [(r[0], r[1] or "") for r in con.execute(
        "SELECT bot_id, COALESCE(employment, CASE WHEN career IN ('leave','terminated')"
        " THEN career ELSE 'employed' END)"
        " FROM bot WHERE role='lead' AND (seat_id LIKE ?"
        "   OR (COALESCE(seat_id,'')='' AND prj=?))"
        " ORDER BY (COALESCE(seat_id,'')='') , bot_id",
        (f"{prj}/%", prj)).fetchall()]


def _org_files():
    """선언된 prj 조직 목록. `_hq`·`_template` 은 생명주기 대상이 아니다 —
    본사는 조직 골격이라 쉬지 않는다(상비 4종이 아카이브 제외인 것과 같은 이유)."""
    return sorted(int(n) for n in _declared_names() if n.isdigit())


_GIT_TS_CACHE = {}   # base → (head_key, ts) — prj3#Issue732


def _git_head_key(base):
    """HEAD 가 가리키는 커밋이 바뀌면 달라지는 키 — `.git/HEAD`·그 ref 파일·`packed-refs` 의 mtime.
    커밋·체크아웃·fetch 어느 쪽이든 이 셋 중 하나는 움직인다. 못 읽으면 None(캐시 안 씀)."""
    g = os.path.join(base, ".git")
    try:
        head = os.path.join(g, "HEAD")
        key = [os.stat(head).st_mtime_ns]
        with open(head, encoding="utf-8") as f:
            ref = f.read().strip()
        if ref.startswith("ref: "):
            rp = os.path.join(g, ref[5:].strip())
            if os.path.exists(rp):
                key.append(os.stat(rp).st_mtime_ns)
        pr = os.path.join(g, "packed-refs")
        if os.path.exists(pr):
            key.append(os.stat(pr).st_mtime_ns)
        return tuple(key)
    except OSError:
        return None


def last_activity(prj):
    """프로젝트의 마지막 활동(epoch). git 마지막 커밋을 쓴다 — job 원장은 대부분의
    prj 에서 0건이라 판정 근거가 못 된다(실측). 없으면 None.

    prj3#Issue732 — `git log` subprocess 는 HEAD 키(`_git_head_key`)가 같은 동안 재사용한다.
    hub 가 조직 한 번 그릴 때 prj 마다 spawn 하던 22회가 캐시 웜에서 0회가 된다."""
    import subprocess
    base = prj_path(prj)
    if not base or not os.path.isdir(os.path.join(base, ".git")):
        return None
    key = _git_head_key(base)
    hit = _GIT_TS_CACHE.get(base)
    if key is not None and hit is not None and hit[0] == key:
        return hit[1]
    try:
        r = subprocess.run(["git", "-C", base, "log", "-1", "--format=%ct"],
                           capture_output=True, text=True, timeout=10)
        ts = int(r.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
    if key is not None:
        _GIT_TS_CACHE[base] = (key, ts)
    return ts


def pm_bot(prj, con=None):
    """그 팀의 팀장핀봇 `bot_id`. 없으면 None."""
    with _Con(con) as c:
        if c is None:
            return None
        try:
            rows = _lead_rows(c, prj)
            # 재직자 우선 — 휴직 팀장이 앞에 오면 wake 대상이 되므로 재직자가 없을 때만 그를 낸다
            live = [r for r in rows if r[1] == "employed"]
            return (live or rows)[0][0] if rows else None
        except sqlite3.Error:
            return None


def pm_last_activity(prj, con=None):
    """팀장핀봇의 **마지막 실행** 시각(epoch).

    세 원천의 최댓값이다 — 어느 하나만 보면 살아 있는 팀을 재운다:
      ① 그 봇 귀속 `job` 마지막 기록 — 봇이 실제로 일한 증거
      ② 프로젝트 git 마지막 커밋 — 사람이 그 프로젝트를 만진 증거. PM 은 그
         프로젝트를 대표하므로 프로젝트 활동은 곧 그 팀의 활동이다
      ③ 봇 `created_at` — 채용 직후 아무 기록도 없는 구간의 하한. 이것이 없으면
         **갓 채용한 팀이 즉시 «구성 아님»**(`team_formed` False)으로 판정된다
         (휴직 전이는 Issue689 에서 폐기 — 표시 판정만 남았다)
    """
    ts = []
    bid = pm_bot(prj, con=con)
    if bid:
        with _Con(con) as c:
            try:
                if c is not None:
                    r = c.execute("SELECT MAX(created_at) FROM job WHERE owner=?", (bid,)).fetchone()
                    if r and r[0]:
                        ts.append(int(r[0]))
                    r = c.execute("SELECT created_at FROM bot WHERE bot_id=?", (bid,)).fetchone()
                    if r and r[0]:
                        ts.append(int(r[0]))
            except sqlite3.Error:
                pass
    g = last_activity(prj)
    if g:
        ts.append(g)
    return max(ts) if ts else None


DISBAND_NS = "fbot-org-disband"   # kv(ns, key=prj) = 해산 시각(epoch) — Issue689


def disbanded_at(prj, con=None):
    """사용자가 누른 해산 시각(epoch). 없으면 None. kv 1행 — career 를 건드리지 않는다."""
    with _Con(con) as c:
        if c is None:
            return None
        try:
            r = c.execute("SELECT value FROM kv WHERE ns=? AND key=?", (DISBAND_NS, str(prj))).fetchone()
            return int(r[0]) if r and str(r[0]).isdigit() else None
        except sqlite3.Error:
            return None


def team_formed(prj, idle_days=None, now=None, con=None):
    """팀이 지금 **구성 중**인가 — 보드가 그릴지 말지의 단일 판정 (Issue689).

    구성 중 = 재직 팀장 ∧ 마지막 활동이 `IDLE_DAYS`(기본 3일) 이내 ∧ (해산 기록이 있으면
    **그 뒤 배분**이 있어야). 본사는 항상 구성 중이다.

    🔴 **표시 판정이지 상태 전이가 아니다.** Issue538 은 유휴 팀장을 휴직(career)시켜 팀을
    지웠는데, Issue609 가 자리에 앉은 팀장을 상비봇으로 보호하자 휴직이 매번 거부됐다
    (2026-09-09~26, tick 마다 15건 실패·오류 삼킴). 원장을 바꾸지 않고 활동 시각에서
    파생하면 두 규칙이 부딪칠 자리가 없고, 배분이 오면 활동 시각이 갱신되어 저절로 재구성된다.
    해산 버튼 뒤에 **git 커밋·봇 이벤트로는 되살리지 않는다** — 사람이 방금 해산한 팀이
    퇴근 이벤트 하나로 다시 뜨면 버튼이 무의미하다. 재구성은 배분(일)이 한다.
    """
    import time
    now = time.time() if now is None else now
    days = IDLE_DAYS if idle_days is None else idle_days
    if prj is None:
        return {"formed": True, "reason": "본사", "idle_days": None, "disbanded_at": None}
    if not team_alive(prj, con=con):
        return {"formed": False, "reason": "재직 팀장 없음", "idle_days": None, "disbanded_at": None}
    d = disbanded_at(prj, con=con)
    ts = None
    if d:
        bid = pm_bot(prj, con=con)
        with _Con(con) as c:
            try:
                if c is not None and c.execute(
                        "SELECT 1 FROM job WHERE owner=? AND kind='fbot_dispatch' AND created_at>?",
                        (bid, d)).fetchone():
                    r = c.execute("SELECT MAX(created_at) FROM job WHERE owner=? AND created_at>?",
                                  (bid, d)).fetchone()
                    ts = int(r[0]) if r and r[0] else None
            except sqlite3.Error:
                ts = None
        if ts is None:
            return {"formed": False, "reason": "해산됨", "idle_days": None, "disbanded_at": d}
    else:
        ts = pm_last_activity(prj, con=con)
    idle = None if ts is None else round((now - ts) / 86400, 1)
    formed = idle is not None and idle <= days
    return {"formed": formed, "reason": "구성 중" if formed else f"유휴 {idle}일 > {days}일",
            "idle_days": idle, "disbanded_at": d}


def disband(prj, apply=False, by="", undo=False):
    """사용자 해산 버튼 — kv 에 해산 시각만 남긴다. 팀장 career·자리는 그대로다(Issue689).

    되돌리기는 `undo`(기록 삭제) 또는 그 prj 로의 다음 배분이다.
    """
    import sqlite3
    import time
    if prj is None:
        return {"ok": False, "error": "본사는 해산하지 않는다 — 조직 골격이다"}
    if not os.path.exists(_org_file(f"{prj}.yml")):
        return {"ok": False, "error": f"조직 선언 없음: prj{prj}"}
    if not apply:
        return {"ok": True, "mode": "dry-run", "prj": prj, "undo": undo, "next": "집행은 --apply"}
    con = sqlite3.connect(REGISTRY_DB, timeout=5.0)
    try:
        if undo:
            con.execute("DELETE FROM kv WHERE ns=? AND key=?", (DISBAND_NS, str(prj)))
        else:
            t = int(time.time())
            con.execute(
                "INSERT INTO kv (ns, key, value, expires_at, updated_at, updated_by) VALUES (?,?,?,NULL,?,?)"
                " ON CONFLICT(ns, key) DO UPDATE SET value=excluded.value,"
                " updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (DISBAND_NS, str(prj), str(t), t, by or "fbot-org"))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "mode": "집행", "prj": prj, "action": "undo" if undo else "disband",
            "formed": team_formed(prj)}


def sweep(idle_days=None):
    """유휴 팀 **판정 보고** — 휴직 전이는 하지 않는다(Issue689 에서 폐기).

    Issue538 의 `sweep --apply`(유휴 팀장 휴직)는 Issue609 상비 보호와 충돌해 한 번도
    성공하지 못했다. 구성 여부는 이제 `team_formed` 가 활동 시각에서 파생한다.
    """
    out, formed = [], 0
    for prj in _org_files():
        f = team_formed(prj, idle_days=idle_days)
        if f["formed"]:
            formed += 1
        else:
            out.append({"prj": prj, "title": resolve(prj).get("title"), **f})
    return {"ok": True, "action": "sweep", "mode": "판정만",
            "idle_days_threshold": IDLE_DAYS if idle_days is None else idle_days,
            "formed": formed, "not_formed": out}


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
    # 조직 목록 원천은 `list` 와 같다 — ORG_DIR 의 선언 파일명(갈리면 두 화면이 다른 조직을 말한다)
    _declared = _declared_names()
    try:
        # Issue689 — 팀장 판정은 `_lead_rows` 단일 지점. 예전 `prj IS NOT NULL` 직접 조회는
        #   자리 기준인 team_alive 와 갈라져 «팀장 있음 + 팀 죽음» 을 동시에 참으로 만들었다.
        pm, unseated = {}, []
        for prj in _declared:
            if not prj.isdigit():
                continue
            n = int(prj)
            for bid, emp in _lead_rows(con, n):
                st = con.execute("SELECT state, COALESCE(seat_id,'') AS seat FROM bot WHERE bot_id=?",
                                 (bid,)).fetchone()
                pm.setdefault(n, []).append({"bot_id": bid, "emp": emp, "state": st["state"]})
                if not st["seat"] and emp == "employed":   # 휴직·해고자는 앉힐 대상이 아니다(Issue692)
                    unseated.append({"prj": n, "bot_id": bid})
    finally:
        con.close()
    ok_list, missing = [], []
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
            "staffed": len(ok_list), "missing": missing, "staffed_list": ok_list,
            # Issue689 — 자리 없는 팀장. 판정은 통과시키되(prj 열로 인정) 상비 보호(is_core_bot)는
            #   자리를 요구하므로 여기 보이면 `bind` 로 앉혀야 한다. 결손이 아니라 경고라 ok 에 넣지 않는다
            "unseated": unseated}


# ── 인력 확보 사다리 (prj3#Issue757 T13) ─────────────────────────────────────────
#   사용자 결정 ③④(2026-09-28): *«팀에 핀봇이 없으면 총괄이 다른 팀에서 가져오거나 생성하고, 그래도 못 구하면
#   프로젝트 단위로 발굴한다»*. 판정 한 줄: **자리 안이면 팀장, 자리 밖이면 총괄, 카탈로그 밖이면 발굴**.
#   여기는 조직 쪽 재료(자리·개체·본거지)만 낸다 — 차용 기록·채용·배분은 fbot-lead·HR 게이트 몫이다.

def _live_catalog_role(role):
    a = catalog_attrs().get(role or "")
    return a is not None and a.get("status") != "archived"


def effective_employment(employment, career=None):
    """재직 축 해석 — `employment` 가 정본, 백필 전(NULL)은 career 사영으로(`_lead_rows` 와 같은 규칙).
    두 축이 어긋나면(사영 미동기) **재직이 아닌 쪽**을 믿는다 — 차용·배분이 휴직·해고를 깨우면 되돌리기가 비싸다."""
    if career in ("leave", "terminated") and (employment or "employed") == "employed":
        return career
    return employment or "employed"


def loanable(employment, career=None):
    """«차용 가능 재직» 술어 — 판정 단일 지점 (prj3#Issue822). `employed` 만 참 · 휴직·정직·해고는 거짓.

    🔴 `find_role`(총괄 모색)·`ladder_step`(org 후보)·`fbot-lead loan`(차용 기록)이 전부 이것을 쓴다. 종전
    `find_role` 은 해고만 걸러 휴직·정직 개체가 후보에 들었고, 총괄이 그것을 `loan` 으로 잇고 dispatch 가 HR
    `wake` 로 깨우면 휴직이 풀렸다 — 인사 수명주기 판정(휴직)을 차용 경로가 무력화한다. 표시(`EMPLOYMENT_LABEL`
    재직·정직·휴직·해고)와 같은 뜻이다."""
    return effective_employment(employment, career) == "employed"


def find_role(role, con=None):
    """직능 R 을 가진 prj(선언 자리)와 재직 개체 — 총괄의 모색 도구(사다리 ②).
    반환 {role, home, seats:[{prj, seat_id, addr}], bots:[{bot_id, prj, state, seat_id, employment}]}.
    개체는 «차용 가능 재직»(`loanable` — 휴직·정직·해고 제외)만 싣는다. 아카이브 직능은 `ladder_step` 이 scout 로 가른다."""
    seats = []
    for n in _org_files():
        for st in resolve(n, con=con).get("seats") or []:
            if st.get("role") == role:
                seats.append({"prj": n, "seat_id": st.get("id"), "addr": st.get("addr")})
    bots = []
    with _Con(con) as c:
        if c is not None:
            try:
                cols = {r[1] for r in c.execute("PRAGMA table_info(bot)").fetchall()}
                sel = ("bot_id, prj, state" + (", seat_id" if "seat_id" in cols else ", NULL")
                       + (", employment" if "employment" in cols else ", NULL") + ", career")
                for r in c.execute("SELECT %s FROM bot WHERE role=? ORDER BY bot_id" % sel, (role,)).fetchall():
                    if loanable(r[4], r[5]):          # prj3#Issue822 — 재직 판정은 술어 한 곳
                        bots.append({"bot_id": r[0], "prj": r[1], "state": r[2], "seat_id": r[3],
                                     "employment": effective_employment(r[4], r[5])})
            except sqlite3.Error:
                pass
    home = (catalog_attrs().get(role or "") or {}).get("home")
    try:
        home = int(home) if home not in (None, "") else None
    except ValueError:
        home = None
    return {"role": role, "home": home, "seats": seats, "bots": bots}


def body_prj():
    """본사 몸체 prj — `_hq.yml` body_prj (prj3#Issue734). 미선언·해소 실패는 None(본사 = 어느 prj 도 아님)."""
    try:
        bp = resolve(None).get("body_prj")
        return int(bp) if bp not in (None, "") else None
    except Exception:  # noqa: BLE001 — 해소 실패는 «팀 없음» 일 뿐 판정을 막지 않는다
        return None


_SEAT_PRJ = re.compile(r"^(\d+)/")


def team_prj(prj, seat_id=None):
    """«팀 소속» — 개체가 어느 팀(prj)의 일원인가. **판정 단일 지점** (prj3#Issue945).

    · 자리가 `N/…` 면 N — 자리가 prj 열을 이긴다(`_lead_rows` 팀장 판정과 같은 규칙)
    · 자리가 `hq/…` 거나 prj 열이 없으면 본사 몸체 prj(`body_prj` — prj3#Issue734). 본사 팀장·총괄이 prj3 워커를
      부르는 것은 타 팀 차용이 아니다(운영 실측 2026-09-28: 외부 에이전트 워커 ~90회/2주)
    · 그 외 prj 열. 해소 불가는 None(어느 팀도 아님)
    `fbot-lead.loan_reject`(배분자 팀)·`cross_step`(요청 팀장의 팀)이 이것을 쓴다 — 종전엔 loan_reject 안에만 있었다."""
    m = _SEAT_PRJ.match(str(seat_id or ""))
    if m:
        return int(m.group(1))
    if str(seat_id or "").startswith("hq/") or prj is None:
        return body_prj()
    try:
        return int(prj)
    except (TypeError, ValueError):
        return None


def _requester_lead_team(c, by):
    """요청자가 팀장(lead)이면 그 팀 prj, 아니면 None — ⓪ cross 의 판정 대상은 팀장뿐이다(총괄은 조직 단)."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(bot)").fetchall()}
    row = c.execute("SELECT role, prj, %s FROM bot WHERE bot_id=?" % ("seat_id" if "seat_id" in cols else "NULL"),
                    (by,)).fetchone()
    if not row or row[0] != "lead":
        return None
    return team_prj(row[1], row[2])


def chief_bot(c):
    """총괄 개체 id — 본사 chief 자리 점유자 우선, 없으면 role=chief 중 prj 없는 첫 개체. 없으면 None.

    **조회 단일 지점** (prj3#Issue945 검토 R3) — `fbot-inbox._chief_bot` 이 이것에 위임한다(종전 같은 SQL 사본 2벌).
    방향은 org ← inbox 다: inbox 는 이미 org 를 싣고(`_org()`), org 가 inbox 를 실으면 상호 의존이 된다.
    `c` = 열린 대장 연결(row_factory 무관 — 첫 열만 읽는다). `seat_id` 열이 없는 옛 대장은 자리 우선순위 없이 고른다."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(bot)").fetchall()}
    order = "CASE WHEN seat_id LIKE 'hq/%' THEN 0 ELSE 1 END, " if "seat_id" in cols else ""
    row = c.execute("SELECT bot_id FROM bot WHERE role='chief' AND prj IS NULL ORDER BY %screated_at, bot_id LIMIT 1"
                    % order).fetchone()
    return row[0] if row else None


def cross_step(prj, role, by, con=None):
    """⓪ cross — **남의 prj 일**은 그 prj 팀장 인박스로 (prj3#Issue945). 판정 단일 지점 — `ladder_step` 의 맨 앞 단.

    종전엔 «팀» 판정 축이 3벌이었다 — dispatch 는 대상 prj 를 cwd 로만 정해 그 prj 자리 개체를 고른 뒤 `loan_reject` 가
    «차용 필요» 로, staffing 은 `--prj` 를 요청 팀장 prj 와 대조하지 않아 `ladder_step` team 이 «팀장이 배분» 으로 거부했다
    (서로 떠넘김 — 2026-10-05 prj8 팀장 → prj1 일). 차용은 **내 prj 일**에 다른 팀 개체를 빌리는 것이고, 남의 prj 일은
    작업 경계(F5)상 그 prj 팀장이 배분한다.
    대상: 요청자가 팀장(`lead`) · 일의 prj 해소 · 관리직 아닌 직능 · 요청 팀장의 팀(`team_prj`) ≠ 일의 prj.
    반환 None(대상 밖) 또는 `{step: cross, prj, role, by, by_prj, lead, to, next, reason}` — `to` 는 그 prj 재직 팀장,
    없으면 총괄(그 prj 팀장을 세운다 — PM 필수 전제). 선언도 팀장 행도 없는 prj 는 None(prj3#Issue821 종전 허용 보호).
    대장 해소 실패는 None(fail-soft — 판정 불가는 거부 근거가 아니다)."""
    if not by or prj is None or not role or is_manager(role):
        return None
    try:
        prj = int(prj)
    except (TypeError, ValueError):
        return None
    with _Con(con) as c:
        if c is None:
            return None
        try:
            mine = _requester_lead_team(c, by)
            if mine is None or mine == prj:
                return None
            rows = _lead_rows(c, prj)
            chief = chief_bot(c)
        except sqlite3.Error:
            return None
    live = [r[0] for r in rows if r[1] == "employed"]
    lead = live[0] if live else None
    if lead is None and not rows and resolve(prj, con=con).get("declared") is False:
        return None
    to = lead or chief or "<총괄 bot_id>"
    cmd = (f"python3 ~/.claude/hooks/fbot-inbox.py send --to {to} --from-bot {by} --prj {prj} "
           f"--body \"<요지·기한 — {role}>\"")
    if lead:
        reason = (f"prj{prj} 일이다 — 남의 prj 일은 그 prj 팀장 {lead} 의 인박스로 보낸다(인력 확보 사다리 ⓪ cross · "
                  f"작업 경계 F5 · prj3#Issue945). 내 팀(prj{mine}) 배분·차용·채용 대상이 아니다 — 차용은 내 prj 일에 "
                  f"다른 팀 개체를 빌리는 것이다: {cmd} — {lead} 가 자기 팀에 배분한다")
    else:
        reason = (f"prj{prj} 일이다 — 그 prj 에 재직 팀장이 없다(인력 확보 사다리 ⓪ cross · 작업 경계 F5 · prj3#Issue945). "
                  f"내 팀(prj{mine})이 대신 배분·채용하지 않는다 — 총괄 인박스로: {cmd} — 총괄이 그 prj 팀장을 세워"
                  f"(dispatch --role lead) 넘긴다")
    return {"step": "cross", "prj": prj, "role": role, "by": by, "by_prj": mine, "lead": lead, "to": to,
            "next": cmd, "reason": reason}


def ladder_step(prj, role, con=None, by=None):
    """사다리 단 판정 — ⓪ cross(남의 prj 일 → 그 prj 팀장 인박스, prj3#Issue945) · team(자기 조직 선언 자리 안) ·
    org(카탈로그엔 있으나 자리 밖 → 총괄 차용·생성) · scout(카탈로그 밖·아카이브 → 프로젝트 단위 발굴).
    org 는 다른 prj 의 재직 개체를 후보로 싣는다(본거지 먼저).
    `by` = 요청자 bot_id — 팀장이면 그 팀(`team_prj`)과 일의 prj 를 대조해 ⓪ 을 먼저 본다(`cross_step`). 없으면 종전 판정.
    dispatch 입구·`fbot-inbox staffing`·채용 사다리(`fbot-lead.hire_ladder_verdict`)가 모두 `by` 를 넘겨 같은 판정을 받는다."""
    if by:
        x = cross_step(prj, role, by, con=con)
        if x:
            return x
    if not _live_catalog_role(role):
        return {"step": "scout", "prj": prj, "role": role,
                "reason": "카탈로그 밖(또는 아카이브) — 팀장이 발굴핀봇에 배분해 요청 prj 에 먼저 세운다"}
    got = resolve(prj, con=con)
    seats = got.get("seats") or []
    mine = [s.get("addr") for s in seats if s.get("role") == role]
    if mine:
        return {"step": "team", "prj": prj, "role": role, "seats": mine,
                "reason": "자기 조직 선언의 자리 안 — 팀장이 배분한다(공석이면 HR 게이트가 채용)"}
    f = find_role(role, con=con)
    cands = [b for b in f["bots"] if b.get("prj") != prj and loanable(b.get("employment"))]   # Issue822 같은 술어
    cands.sort(key=lambda b: (b.get("prj") != f["home"], b.get("bot_id")))
    return {"step": "org", "prj": prj, "role": role, "home": f["home"], "candidates": cands,
            # prj3#Issue821 — 선언이 없으면 «자리 밖» 은 판정 불가다(소비처 dispatch 가 종전 허용으로 가른다)
            "declared": got.get("declared", True),
            "reason": "카탈로그 직능이나 자리 밖 — 총괄에 인력 요청(차용 또는 생성)"}


def _validate_seat_ext(prj, ext, cur, sid=None):
    if ext is None:
        return None
    if not isinstance(ext, dict):
        return "ext 는 매핑이어야 한다"
    allowed = {"checked_by", "continuity", "permission_mode", "permission_reason"}
    unknown = sorted(set(ext) - allowed)
    if unknown:
        return f"지원하지 않는 확장 필드: {', '.join(unknown)}"
    for key in ext:
        if not isinstance(ext[key], str):
            return f"{key} 값은 문자열이어야 한다"
    if "continuity" in ext and ext["continuity"] not in CONTINUITIES:
        return f"continuity 열거 밖 값: {ext['continuity']}"
    if "permission_mode" in ext and ext["permission_mode"] not in PERMISSION_MODES:
        return f"permission_mode 열거 밖 값: {ext['permission_mode']}"
    if ext.get("permission_mode") in _PERMISSION_RANK and not ext.get("permission_reason", "").strip():
        return f"permission_mode={ext['permission_mode']} 명시에는 permission_reason 이 필요하다"
    checked_by = ext.get("checked_by")
    if checked_by:
        target = reports_addr(prj, checked_by)
        local = {s.get("addr"): s for s in cur}
        if sid and target == seat_addr(prj, sid):
            return "checked_by 는 자기 자신을 가리킬 수 없다"
        if not _target_exists(target, local, {}):
            return f"checked_by 대상 자리 부재: {checked_by}"
        if sid:
            new_addr, seen, cur_addr = seat_addr(prj, sid), set(), target
            while True:
                if cur_addr == new_addr:
                    return "checked_by 검증선 순환"
                if cur_addr not in local or cur_addr in seen:
                    break
                seen.add(cur_addr)
                raw = local[cur_addr].get("checked_by")
                if not raw:
                    break
                cur_addr = reports_addr(prj, raw)
    return None


def _yaml_flow_value(value):
    """JSON 문자열은 YAML flow mapping 안에서도 안전한 스칼라 표기다."""
    return json.dumps(value, ensure_ascii=False)


def add_seat(prj, role, dept="dev", reports_to="ops-lead-1", apply=False, note="", ext=None):
    """요청 prj 조직 선언에 자리를 더한다 — 사다리 ②ⓑ 생성·③ 발굴 (prj3#Issue757 T13).

    조직 선언은 사람이 쓴 파일이라 **텍스트로 덧붙인다**(yaml 재직렬화는 주석을 지운다). `depts:` 가 마지막
    최상위 키가 아니면 안전하게 덧붙일 수 없어 fail-loud. 쓰기 뒤 `resolve` 로 자리가 생겼는지 검증하고
    아니면 원문으로 되돌린다. 같은 직능 자리가 이미 있으면 멱등(existing)."""
    if prj is None:
        return {"ok": False, "error": "본사 자리는 이 경로로 추가하지 않는다(_hq.yml 은 조직 골격)"}
    if not _live_catalog_role(role):
        return {"ok": False, "error": f"카탈로그 밖(또는 아카이브) 직능 {role} — 자리는 등재 뒤에 만든다(발굴 ①~⑤)"}
    cur = resolve(prj).get("seats") or []
    error = _validate_seat_ext(prj, ext, cur)
    if error:
        return {"ok": False, "error": error}
    have = [s for s in cur if s.get("role") == role]
    if have:
        return {"ok": True, "existing": True, "seat_id": have[0].get("id"), "prj": prj}
    k = 1 + sum(1 for s in cur if s.get("dept") == dept)
    sid = f"{dept}-{role}-1"
    while any(s.get("id") == sid for s in cur):
        k += 1
        sid = f"{dept}-{role}-{k}"
    error = _validate_seat_ext(prj, ext, cur, sid=sid)
    if error:
        return {"ok": False, "error": error}
    label = next((s.get("dept_label") for s in cur if s.get("dept") == dept and s.get("dept_label")), dept)
    path = os.path.join(ORG_DIR, f"{prj}.yml")          # 쓰기는 사용자 폴더(번들 캐시는 갱신 때 덮인다)
    existed = os.path.exists(path)
    src = _org_file(f"{prj}.yml")                        # 원문은 사용자 → 번들 폴백(기존 자리 보존)
    orig = open(src, encoding="utf-8").read() if os.path.exists(src) else None
    text = orig if orig is not None else (f"# 조직 인스턴스 — prj{prj} (prj3#Issue757 사다리 — 자리 추가로 생성)\n"
                                          f"prj: {prj}\nextends: _template/general.yml\n")
    tops = [ln for ln in text.splitlines() if re.match(r"^[A-Za-z_][\w-]*:", ln)]
    has_depts = any(ln.startswith("depts:") for ln in tops)
    if has_depts and not tops[-1].startswith("depts:"):
        return {"ok": False, "error": f"{path}: `depts:` 가 마지막 최상위 키가 아니다 — 손으로 추가한다"}
    ext_text = "".join(f", {key}: {_yaml_flow_value(value)}" for key, value in (ext or {}).items())
    add = ("" if has_depts else "depts:\n") + (
        f"  # 자리 추가 — {note or '인력 확보 사다리'} (prj3#Issue757)\n"
        f"  - id: {dept}\n    label: {label}\n    seats:\n"
        f"      - {{ id: {sid}, role: {role}, reports_to: {reports_to}{ext_text} }}\n")
    new = text.rstrip("\n") + "\n" + add
    out = {"ok": True, "prj": prj, "seat_id": sid, "dept": dept, "path": path, "mode": "apply" if apply else "dry-run"}
    if not apply:
        return dict(out, preview=add)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    if not any(s.get("id") == sid for s in resolve(prj).get("seats") or []):
        if not existed:
            os.remove(path)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(orig)
        return {"ok": False, "error": f"추가 뒤 해소 결과에 {sid} 가 없다 — 원문 복구"}
    return out


# ── 기동 권한 플래그 — 조립 단일 지점 (prj3#Issue859_2) ─────────────────────────────
#   기동 3곳(`~/.bin/fpm-do`·`fbot-lead.py spawn_line_bytes`·`aoa-mq-lib.sh`)이 이 함수의 출력을 쓴다.
#   ⚠️ 플래그 리터럴은 여기 한 곳이다 — 바꾸면 줄 바이트 예산(fbot-lead LINE_BUDGET)에 닿는다.
LAUNCH_BYPASS = "--dangerously-skip-permissions"
FLOOR_TOOLS_DEFAULT = "Read,Grep,Glob"          # policy 에 목록이 없을 때의 fail-closed 최소(읽기 전용)
POLICY_FILE = os.environ.get("FBOT_POLICY_FILE")


def _floor_tools(role=None):
    """`floor` 의 허용 도구 목록 — policy.yml `fbot_floor_tools_<role>: A,B,C` 우선, 없으면 전역 `fbot_floor_tools`.

    둘 다 부재면 최소 읽기 목록(fail-closed). 직능 키는 자리 role(catalog id) 그대로 — Issue902.
    """
    paths = [POLICY_FILE] if POLICY_FILE else [os.path.join(ROOT, "data", "aoa", n)
                                                for n in ("policy.yml", "policy_org.yml")]
    keys = ([f"fbot_floor_tools_{re.escape(role)}"] if role and re.fullmatch(r"[A-Za-z0-9_\-]+", role) else []) \
        + ["fbot_floor_tools"]
    for key in keys:
        for path in paths:
            try:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        m = re.match(rf"^{key}:\s*([A-Za-z0-9_,\-\s]+?)\s*(#.*)?$", line)
                        if m and m.group(1).replace(" ", ""):
                            return m.group(1).replace(" ", "")
            except OSError:
                continue
    return FLOOR_TOOLS_DEFAULT


def launch_permission(bot_id=None):
    """봇의 기동 권한 해소 → `{mode, reason, flags}`. 자리를 찾을 키가 없으면 **현행 bypass**(바꾸려면 H).

    키 = `bot.seat_id`(`{hq|prj}/{seat}` 주소) → 같은 `addr` 자리의 `permission_mode`. `inherit` 는 bypass 로 읽는다
    (직능 기본값이 이미 해소에 반영돼 있다). 원장·선언 판독 실패는 현행 bypass — 기동이 막히지 않게(fail-open).
    """
    out = {"mode": "bypass", "reason": "자리 키 없음", "flags": LAUNCH_BYPASS}
    if not bot_id:
        return out
    try:
        with _Con() as con:
            row = con.execute("SELECT seat_id FROM bot WHERE bot_id=?", (bot_id,)).fetchone() if con else None
        addr = (row or [None])[0]
        if not addr:
            return out
        scope = addr.split("/", 1)[0]
        got = resolve(None if scope == "hq" else int(scope))
        seat = next((s for s in got.get("seats", []) if s.get("addr") == addr), None)
        if not seat:
            out["reason"] = f"자리 선언 없음: {addr}"
            return out
        mode = seat.get("permission_mode") or "bypass"
        reason = seat.get("permission_reason") or ""
        role = seat.get("role")
    except Exception as e:      # 기동을 막지 않는다 — 해소 실패는 현행 동작
        out["reason"] = f"해소 실패({type(e).__name__}) — 현행 유지"
        return out
    if mode == "floor":
        # prj3#Issue940 — `--tools` 는 MCP 를 거르지 않는다. floor 몸체는 MCP 0(--strict-mcp-config 단독, 설정 파일 없음) —
        #   floor 3직능 매뉴얼은 MCP 참조 0. fpm-do 는 이 플래그를 보고 몸체 MCP 부착(--mcp-config)을 뗀다
        return {"mode": "floor", "reason": reason or "floor 선언", "seat": addr,
                "flags": f"--permission-mode dontAsk --tools={_floor_tools(role)} --strict-mcp-config"}
    return {"mode": "bypass", "reason": reason or "bypass(기본)", "seat": addr, "flags": LAUNCH_BYPASS}


def launch_flags(bot_id=None):
    return launch_permission(bot_id)["flags"]


def audit_launch(bot_id, perm):
    """해소 결과를 원장 이벤트 `launch-perm` 으로 남긴다 — 실패는 조용히 무시(감사가 기동을 막지 않는다)."""
    import time
    import uuid
    try:
        con = sqlite3.connect(REGISTRY_DB, timeout=5)
        try:
            now = int(time.time())
            detail = f"mode={perm['mode']} seat={perm.get('seat', '-')} reason={perm['reason']}"[:300]
            con.execute(
                "INSERT INTO job (id, store, kind, status, payload, result, attempts, owner, lease_until, blocked_since, created_at)"
                " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
                (f"fbotev-{now}-{uuid.uuid4().hex[:8]}", "fbot", "fbot_event", "done",
                 json.dumps({"type": "launch-perm", "detail": detail, "ref": ""}, ensure_ascii=False),
                 bot_id, now))
            con.commit()
        finally:
            con.close()
    except sqlite3.Error:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="조직 선언 해소기 (Issue538)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="prj 조직 해소 (생략 시 본사)")
    r.add_argument("--prj", type=int, default=None)
    sub.add_parser("list", help="선언된 조직 목록")
    nx = sub.add_parser("nonexec", help="봇이 비실행 관리직(총괄·팀장)인가 — true|false 한 줄 (prj3#Issue951 Stop 훅용)")
    nx.add_argument("--bot-id", default="")
    lf = sub.add_parser("launch-flags", help="몸체 기동 권한 플래그 한 줄 — 기동 3곳의 단일 조립 지점 (prj3#Issue859_2)")
    lf.add_argument("--bot", default="")
    lf.add_argument("--audit", action="store_true", help="해소 결과를 원장 이벤트 launch-perm 으로 남긴다")
    sub.add_parser("check-pm", help="PM 필수 전제 검사 — 재직 PM 없는 prj 를 찾는다 (Issue609)")
    sw = sub.add_parser("sweep", help="구성 판정 보고 — 휴직 전이 없음 (Issue689 에서 --apply 폐기)")
    sw.add_argument("--idle-days", type=int, default=None)
    fm = sub.add_parser("formed", help="팀 구성 판정 (Issue689) — 보드 표시 기준")
    fm.add_argument("--prj", type=int, default=None)
    db = sub.add_parser("disband", help="사용자 해산 — kv 에 시각 기록, career 불변 (Issue689)")
    db.add_argument("--prj", type=int, required=True)
    db.add_argument("--by", default="")
    db.add_argument("--undo", action="store_true", help="해산 기록 삭제(즉시 재구성 판정)")
    db.add_argument("--apply", action="store_true")
    wk = sub.add_parser("wake", help="조직 부활 — 배분 발생 시 호출")
    wk.add_argument("--prj", type=int, required=True)
    wk.add_argument("--reason", default="")
    b = sub.add_parser("bind", help="개체를 자리에 결속")
    b.add_argument("--bot-id", required=True)
    b.add_argument("--seat-id", required=True)
    b.add_argument("--prj", type=int, default=None)
    b.add_argument("--apply", action="store_true")
    fr = sub.add_parser("find", help="직능 R 을 가진 prj·재직 개체 (prj3#Issue757 사다리 ②)")
    fr.add_argument("--role", required=True)
    ld = sub.add_parser("ladder", help="사다리 단 판정 cross·team·org·scout (prj3#Issue757 · prj3#Issue945)")
    ld.add_argument("--prj", type=int, default=None)
    ld.add_argument("--role", required=True)
    ld.add_argument("--by", default=None, help="요청 팀장 bot_id — 일의 prj 가 내 팀 밖이면 ⓪ cross(그 prj 팀장 인박스)")
    asx = sub.add_parser("add-seat", help="요청 prj 조직 선언에 자리 추가 — 생성·발굴 (prj3#Issue757)")
    asx.add_argument("--prj", type=int, required=True)
    asx.add_argument("--role", required=True)
    asx.add_argument("--dept", default="dev")
    asx.add_argument("--note", default="")
    asx.add_argument("--apply", action="store_true")
    asx.add_argument("--checked-by", default=None)
    asx.add_argument("--continuity", default=None)
    asx.add_argument("--permission-mode", default=None)
    asx.add_argument("--permission-reason", default=None)
    a = ap.parse_args(argv)

    if a.cmd == "nonexec":
        print("true" if bot_nonexec(a.bot_id) else "false")
        return 0
    if a.cmd == "launch-flags":
        perm = launch_permission(a.bot or None)
        if a.audit and a.bot:
            audit_launch(a.bot, perm)
        print(perm["flags"])
        return 0
    if a.cmd == "find":
        print(json.dumps(find_role(a.role), ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "ladder":
        print(json.dumps(ladder_step(a.prj, a.role, by=a.by), ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "add-seat":
        ext = {k: v for k, v in {
            "checked_by": a.checked_by, "continuity": a.continuity,
            "permission_mode": a.permission_mode, "permission_reason": a.permission_reason,
        }.items() if v is not None}
        out = add_seat(a.prj, a.role, dept=a.dept, apply=a.apply, note=a.note, ext=ext)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1

    if a.cmd == "resolve":
        out = resolve(a.prj)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1
    if a.cmd == "check-pm":
        out = check_pm()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else 1        # 부재가 있으면 rc=1 — 감사·CI 가 실패로 잡는다
    if a.cmd == "sweep":
        out = sweep(a.idle_days)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "formed":
        print(json.dumps(dict(team_formed(a.prj), prj=a.prj), ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "disband":
        out = disband(a.prj, apply=a.apply, by=a.by, undo=a.undo)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1
    if a.cmd == "wake":
        out = wake(a.prj, a.reason)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1
    if a.cmd == "bind":
        out = bind(a.bot_id, a.seat_id, a.prj, a.apply)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1
    if a.cmd == "list":
        names = _declared_names()
        print(json.dumps({"ok": True, "orgs": names}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
