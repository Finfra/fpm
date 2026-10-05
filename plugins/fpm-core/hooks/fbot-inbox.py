#!/usr/bin/env python3
"""fbot-inbox.py — 매니저 명령 인박스 (prj3#Issue552)

**결속된 매니저가 다른 프로젝트의 요청을 무시하던 문제**를 푼다. 종전에는 봇에게
일을 시키려면 그 봇에 **결속해야** 했고 결속은 배타라 두 번째 요청이 거부됐다.

🔴 **결속(몸)과 명령 수신(창구)은 다른 축이다.**
  * 결속은 **1:1 그대로** 둔다 — 다중화하면 "이 작업을 누가 했나" 가 흐려진다(F4)
  * 매니저는 결속 없이 **N:1** 요청을 받는다. 결속 여부와 무관하게 요청이 쌓인다

**인박스는 신설 테이블이 아니다** — `job.owner` 가 이미 *"누구에게 귀속된 일인가"*
를 답한다. 매니저 앞으로 온 `open` 요청 목록이 곧 인박스다.

⚠️ `kind` 는 `fbot` 접두를 유지한다 — `job` 트리거가 `kind LIKE 'fbot%'` 인 레코드의
`owner` 를 `owner_id`(FK→`bot`)로 옮긴다. 접두를 버리면 봇 축에서 빠져 감사기·조직도
집계가 이 요청들을 못 본다.

설계 SSOT: `_doc_arch/fbot-manager.md`
"""
import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_DB = os.environ.get("FBOT_REGISTRY_DB") or os.path.join(
    # prj3#Issue559 — fbot-state.py 와 같은 해석(AOA_MEMORY_DIR → ~/.claude/data/aoa). 개인 경로 하드코딩은
    #   번들로 나가는 순간 타 머신에서 "DB 없음" 이 된다.
    os.environ.get("AOA_MEMORY_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa"),
    "registry.db")
KIND = "fbot_request"          # ⚠️ fbot 접두 필수 (위 주석)
# prj3#Issue749 — `kind=question` 은 **묻는 봇 귀속**(owner=질문자)이고 수신은 `payload.to_session`(사람 세션)이다.
#   매니저 인박스가 아니므로 인박스 조회·기상·에스컬레이션 집계에서 빠진다 — 이 술어 하나를 공유한다.
Q_NOT = " AND COALESCE(json_extract(payload,'$.kind'),'') <> 'question'"
# prj3#Issue757 — 팀원 질문(owner = 묻는 봇)을 받는 팀장 쪽 조회 조건. `?` 1개 = 팀장 bot_id
Q_TO_LEAD = (" AND json_extract(payload,'$.kind')='question'"
             " AND json_extract(payload,'$.to_lead')=?")
SEND_DEDUP_WINDOW = int(os.environ.get("FBOT_SEND_DEDUP_WINDOW") or 300)   # send 재시도 멱등 창(초) — prj3#Issue892
CHAIN_MAX = int(os.environ.get("FBOT_REQUEST_CHAIN_MAX") or 3)   # 되물음 체인 상한 (prj3#Issue563)


def _org():
    """`is_manager` 판정을 재사용한다 — 로직을 복제하면 두 벌이 되어 갈라진다."""
    path = os.path.join(HERE, "fbot-org.py")
    spec = importlib.util.spec_from_file_location("fbot_org", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _state():
    """fbot-state.py 의 record_event/notify_hub_event 재사용 (prj3#Issue575) — 이벤트 형식을 두 벌 두지 않는다."""
    path = os.path.join(HERE, "fbot-state.py")
    spec = importlib.util.spec_from_file_location("fbot_state", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _body_scope(con, owner, session):
    """관리직 몸체 원장(prj3#Issue757 T15 ⑤) — 이 세션이 `owner` 의 살아 있는 몸체면 그 봇의 몸체 목록, 아니면 None.
    스위치 꺼짐·워커(fail-closed)·몸체 아닌 세션(사람·관리 경로)은 None = 종전 동작."""
    if not session:
        return None
    st = _state()
    if not st.multibody_enabled():
        return None
    r = con.execute("SELECT role FROM bot WHERE bot_id=?", (owner,)).fetchone()
    if r is None or not st._is_nonexec(r[0], on_error=False):
        return None
    bodies = st.open_bodies(con, owner)
    return bodies if any(b["session_id"] == session for b in bodies) else None


def _con(readonly=False):
    if readonly:
        return sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True, timeout=5)
    con = sqlite3.connect(REGISTRY_DB, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def _bot(con, bot_id):
    con.row_factory = sqlite3.Row
    return con.execute("SELECT bot_id, role, state, career FROM bot WHERE bot_id=?",
                       (bot_id,)).fetchone()


# ── 대화 상대 규칙 (prj3#Issue757) ───────────────────────────────────────────────
# *"총괄은 팀장과만 대화한다"* · *"인간의 지시를 받는 것은 총괄과 팀장 뿐"* (사용자 지시 2026-09-28).
#   판정 재료는 카탈로그 `nonexec`(fbot-org.is_nonexec) 하나 — 총괄·팀장이 true 다.
#   ⓐ 총괄 인박스: 봇 발신은 관리직(nonexec)만. 워커·인사·발굴은 배분한 팀장에게 보낸다
#   ⓑ 사람 발신(세션·hub): 수신은 관리직만. 워커를 부르면 그 워커의 팀장에게 돌려 적재한다
#   판정 재료가 없으면(대장에 없는 발신 id·카탈로그 미표기) 종전대로 통과 — 가드가 정상 흐름을 막는 피해가 크다
CHIEF_ROLE = "chief"


HR_ROLE = "hr"
LEAD_ROLE = "lead"


def _talk_error(org, sender, recv):
    """봇 발신 → 매니저 인박스 대화 자격 — 거부 사유 또는 None. `send` 가드와 `defer` 수신자 선택이 같이 쓴다
    (한쪽만 고치면 defer 가 받을 수 없는 매니저를 골라 적재에 실패한다). `sender`·`recv` 는 `bot` 행(bot_id·role).
      ⓐ 총괄은 팀장(과 동급 총괄)과만 대화한다 — 받는 쪽(prj3#Issue757 F)
      ⓐ' 나가는 쪽도 같다 — 총괄이 인사·발굴·워커에게 직접 말하지 않는다(그 prj 팀장을 통한다)
      ⓒ 인사핀봇 인박스는 **팀장 발신만** 받는다(prj3#Issue831 ③) — 팀원은 그 팀장에게 말하고, 채용은 팀장의 배분이
         HR 게이트(`hire` 함수)를 부른다. 총괄은 ⓐ' 로 이미 막힌다. 운영 원장 실측(2026-09-29): 인사핀봇 수신 요청 0건"""
    if recv["role"] == CHIEF_ROLE and not org.is_nonexec(sender["role"]):
        return (f"총괄({recv['bot_id']})은 팀장·총괄과만 대화한다 — {sender['bot_id']}(role={sender['role']}) 는 "
                f"자기에게 일을 배분한 팀장에게 보낸다(fbot-inbox.py defer — 배분 체인 상향)")
    if sender["role"] == CHIEF_ROLE and not org.is_nonexec(recv["role"]):
        return (f"총괄({sender['bot_id']})은 팀장·총괄과만 대화한다 — {recv['bot_id']}(role={recv['role']}) 에게는 "
                f"그 prj 팀장을 통한다(인력 확보는 팀장의 인력 요청을 받아 차용·생성으로)")
    if recv["role"] == HR_ROLE and sender["role"] != LEAD_ROLE:
        return (f"인사핀봇({recv['bot_id']})은 팀장 발신만 받는다 — {sender['bot_id']}(role={sender['role']}) 는 "
                f"그 팀장에게 말한다(채용은 팀장의 dispatch 가 HR 게이트를 부른다)")
    return None


def _team_lead(con, bot_id, org=None):
    """그 봇이 속한 팀의 팀장 — prj 가 있으면 그 prj 팀장, 없으면 본사 팀장(`hq/…` 자리). 없으면 None.
    판정은 fbot-org.pm_bot(팀장 판정 단일 지점) 재사용."""
    org = org or _org()
    r = con.execute("SELECT prj FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
    prj = r[0] if r else None
    lead = org.pm_bot(prj if prj is not None else "hq", con=con)
    return lead if lead and lead != bot_id else None


# ── 자동 기상 (prj3#Issue734) ─────────────────────────────────────────────────
# 적재만으로는 퇴근(cold)한 매니저가 영원히 안 읽는다 — wake 트리거가 배분 하나라 루트인 총괄에게는
# 오지 않았다(2026-09-27 나래 인박스 3건 방치). 판정은 HR 게이트 `wake`, 스폰 명령은 fbot-lead
# `_spawn_commands(mode="wake")` 가 만든다 — 여기는 **호출·잠금·집행**만 한다(dispatch 와 같은 계약).
HR_GATE_PY = os.path.join(HERE, "fbot-hr-gate.py")
SPAWN_GRACE = int(os.environ.get("FBOT_SPAWN_GRACE_SECS") or 600)   # prj1 server.py 스폰 대기와 같은 값
SPAWN_SH = os.environ.get("FBOT_SPAWN_SH")   # 🧪 테스트 전용 주입구 — 설정 시 명령 문자열을 인자로 넘긴다
LOCK_KEY = "wake_spawn_at"


def _mod(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ident():
    """봇 신원 대조 판정 단일 지점(hooks/lib/fbot-ident.py, prj3#Issue832) — `FBOT_ID == --by` 를 복제하지 않는다."""
    return _mod("fbot_ident", os.path.join("lib", "fbot-ident.py"))


def _wakeable(row):
    """깨울 대상인가 — `checkout`(cold) 이거나 bind 판정이 `dead` 인 몸체. 판정은 fbot-state 한 곳."""
    if row["state"] == "checkout":
        return True, "checkout"
    v = _state().bind_occupancy_verdict(row, "")[0]
    return v == "dead", v


def _run_spawn(cmd, probe_secs=0):
    """스폰 명령 집행 — 분리 실행(발신자를 블로킹하지 않는다). 상속 봇 env 는 끊는다:
    발신자가 봇 세션이면 `FBOT_ID` 가 새 몸체로 새어 인격이 섞인다(hook-smoke 상속 env 사고와 같은 경로).

    `probe_secs`(prj3#Issue786_2 부수) — 그 창 안에 비0 으로 끝나면 즉시 실패(fpm-do 가드 거부·경로 오류)로
    `ok=false`. 창을 넘겨 살아 있거나 0 으로 끝나면(--no-wait) 기동으로 본다. 0 이면 종전대로 기다리지 않는다."""
    import subprocess
    if SPAWN_SH:
        p = subprocess.run([SPAWN_SH, cmd], capture_output=True, text=True, timeout=20)
        return {"ok": p.returncode == 0, "rc": p.returncode}
    home = os.path.expanduser("~")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("FBOT_", "CLAUDE_CODE_", "PM_DO_"))}
    env["PATH"] = os.pathsep.join([os.path.join(home, ".bin"), os.path.join(home, ".local", "bin"),
                                   "/opt/homebrew/bin", "/usr/local/bin", env.get("PATH", "/usr/bin:/bin")])
    import shutil
    zsh = shutil.which("zsh", path=env["PATH"])
    if not zsh or not shutil.which("fpm-do", path=env["PATH"]):
        return {"ok": False, "error": "zsh 또는 fpm-do 없음 — 스폰 불가(tick 이 재시도)"}
    os.makedirs(os.path.dirname(WAKE_LOG), exist_ok=True)          # 기본값은 종전 data/fbot/logs/inbox-wake.log
    with open(WAKE_LOG, "a", encoding="utf-8") as lf:
        lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {cmd}\n"); lf.flush()
        p = subprocess.Popen([zsh, "-c", cmd], stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                             env=env, start_new_session=True)
    if probe_secs > 0:
        try:
            rc = p.wait(timeout=probe_secs)
        except subprocess.TimeoutExpired:
            rc = None
        if rc not in (None, 0):
            return {"ok": False, "pid": p.pid, "rc": rc,
                    "error": f"기동 즉시 실패 rc={rc} — 사유는 {WAKE_LOG}"}
    return {"ok": True, "pid": p.pid}


def _lock_body_ended(con, bot_id, lock_at):
    """이 잠금이 띄운 몸체가 **출근했다가 이미 퇴근**했는가 (prj3#Issue749 — 재기상 틈).

    잠금은 «몸체가 뜨는 중» 을 뜻한다. 그 몸체가 출근(state:checkin)한 뒤 퇴근(state:checkout)까지
    마쳤다면 잠금은 지킬 것이 없다 — 그런데도 10분을 막아, 퇴근 1분 뒤 도착한 요청이 tick(최대 30분)
    까지 방치됐다(2026-09-28 10:06 퇴근 · 10:07 도착 · 10:16 수동 wake-pending 실측).
    ⚠️ 출근 없는 퇴근(reap — 몸체가 아직 안 뜬 개체의 정리)은 풀지 않는다. 그것까지 풀면 스폰 중인
    몸체 위에 두 번째 몸체가 뜬다."""
    try:
        ci = con.execute(
            "SELECT MIN(created_at) FROM job WHERE kind='fbot_event' AND owner=?"
            " AND json_extract(payload,'$.type')='state:checkin' AND created_at>=?", (bot_id, lock_at)).fetchone()[0]
        if not ci:
            return False
        return con.execute(
            "SELECT 1 FROM job WHERE kind='fbot_event' AND owner=?"
            " AND json_extract(payload,'$.type')='state:checkout' AND created_at>=? LIMIT 1",
            (bot_id, int(ci))).fetchone() is not None
    except sqlite3.Error:
        return False


# prj3#Issue757 J — 새 지휘 흐름을 여는 요청 종류(판정 단일 지점). 흐름 = 관리직 몸체 1(몸체 원장).
#   보고(`defer`)·팀원 질문(`question`)은 받은 배분·요청의 결과·질의가 올라오는 길이라 **기존 흐름에 딸린다** —
#   흐름으로 치면 보고마다 관리직 몸체가 새로 떠 Issue791 이 막은 «보고가 층마다 새 세션» 증폭이 되살아난다.
#   살아 있는 몸체가 넛지로 받고, 퇴근·사망이면 종전 기상이 깨운다
#   prj3#Issue929 — sweep 의 «완료 미확인» 통지(`unconfirmed`)도 받은 배분의 결과가 올라오는 길이다(워커 보고가 없어 sweep 이
#   대신 올린 것). 흐름으로 치면 미확인마다 관리직 몸체가 새로 뜬다. 리터럴인 이유: 어휘 정본은 fbot-state `UNCONFIRMED` 인데
#   이 튜플은 모듈 적재 시점 상수라 fbot-state 를 여기서 실행하지 않는다 — 값이 갈라지면 test-fbot-inbox-defer I 절이 잡는다
NON_FLOW_KINDS = ("defer", "question", "unconfirmed")


def opens_flow(req_kind):
    return (req_kind or "ask") not in NON_FLOW_KINDS


def wake_and_spawn(bot_id, reason="", spawn=True, lock_since=None, flow=None):
    """퇴근·사망 매니저를 깨운다. 반환 `(wake, spawn)` — 둘 다 결과 dict. **예외를 올리지 않는다**:
    적재가 본업이고 기상은 부가라, 여기 실패가 `send` 를 실패시키면 요청이 유실된다.

    `lock_since`(prj3#Issue748 퇴근 재기상) — 잠금이 이 시각 **이후** 걸린 것일 때만 막는다.
    이 몸체를 띄운 잠금(출근 전)은 몸체가 끝났으니 의미가 없고, 퇴근 뒤 다른 발신이 건 잠금은
    새 몸체가 이미 뜨는 중이라는 뜻이다(중복 방지).

    `flow`(prj3#Issue757 J — 몸체 추가 배선) — 이 기상을 부른 **요청 id**. 관리직·스위치 on 이면 흐름 키가 된다:
    살아 있는 관리직도 새 흐름이면 HR 게이트가 «몸체 추가» 를 판정하고(상한·흐름 잠금 — `wake --flow`), 스폰은
    `FBOT_FLOW=<요청 id>` 로 뜬다. 종전엔 흐름을 넘기지 않아 판정은 있어도 운영에서 몸체가 한 번도 더해지지 않았다
    (2026-09-29 codex-arch-checker high). 흐름이 없거나(일괄 안전망·재기상) 스위치 꺼짐·워커면 종전대로 건너뛴다."""
    import subprocess
    try:
        con = _con()
        try:
            row = con.execute("SELECT * FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
        finally:
            con.close()
        if not row or not _org().is_manager(row["role"]):
            return {"skipped": "not_manager"}, {"skipped": "not_woken"}
        fk = None
        if flow and _org().is_nonexec(row["role"]) and _state().multibody_enabled():
            _lead = _mod("fbot_lead", "fbot-lead.py")
            fk = flow if _lead.FLOW_KEY_RE.match(flow) else None   # 셸에 싣는 값 — 스폰과 같은 형식 판정
        ok, verdict = _wakeable(row)
        if not ok and not fk:
            # alive·idle — 몸이 있다. 결속 중 넛지(③)가 다음 턴에 본다
            return {"skipped": verdict}, {"skipped": "not_woken"}
        if not spawn:
            return {"skipped": "no_spawn", "judged": verdict}, {"skipped": "no_spawn"}
        # prj3#Issue859_3 typing-guard — 사람이 쓰는 pane 에 몸체를 끼워 넣지 않는다. 게이트·잠금 **앞**에서 막는다(보류가
        #   게이트 기록·잠금을 소모하지 않는다). 요청은 이미 적재됐고 입력이 멎으면 tick 안전망(wake-pending)이 다시 잡는다
        con = _con()
        try:
            held = _state().typing_guard(con, row)
            if held:
                _state().record_event(con, bot_id, "wake-held", f"typing-guard · {reason[:60]} · {held[:100]}")
        finally:
            con.close()
        if held:
            return {"skipped": "typing_guard", "judged": verdict, "reason": held}, {"skipped": "typing_guard"}
        # HR 게이트·reap 이 **이 인박스와 같은 원장**을 보게 한다 — FBOT_REGISTRY_DB 만 갈아끼운 환경에서
        #   게이트가 AOA 기본 경로(다른 DB)로 판정하면 기상 판정이 엉뚱한 대장에서 난다
        genv = dict(os.environ, AOA_MEMORY_DIR=os.path.dirname(os.path.abspath(REGISTRY_DB)))
        g = subprocess.run([sys.executable, HR_GATE_PY, "wake", "--bot", bot_id] + (["--flow", fk] if fk else []),
                           capture_output=True, text=True, env=genv)
        if g.returncode != 0:
            return ({"verdict": "거부", "rc": g.returncode, "error": (g.stderr or g.stdout).strip()[:300]},
                    {"skipped": "wake_rejected"})
        wk = json.loads(g.stdout or "{}")
        body_add = bool(wk.get("body_add"))   # 살아 있는 관리직에 흐름 몸체 하나 더 — 잠금·지시문이 흐름 단위다
        # 몸체 prj — 개체 prj, 없으면(본사 개체) _hq.yml body_prj
        prj = row["prj"]
        if prj is None:
            prj = _org().body_prj()           # 본사 몸체 prj 해소 단일 지점(prj3#Issue945 검토 S1)
        if prj is None:
            return wk, {"skipped": "no_body_prj"}
        # 잠금 — 같은 매니저에게 요청이 연달아 오면(실측 3건/2분) 첫 요청만 스폰한다.
        #   몸체 추가는 **흐름 단위** 잠금이다(Issue757 J) — 봇 단위로 잠그면 다른 흐름의 몸체 추가까지 막고,
        #   흐름 몸체가 출근하기 전(수십 초) 같은 흐름의 두 번째 기상이 몸체를 하나 더 띄운다. 흐름 잠금은
        #   «몸체가 끝났다» 로 풀지 않는다 — 봇의 출근·퇴근 이벤트는 몸체 집계라 다른 몸체의 것일 수 있다
        lock_key = f"{LOCK_KEY}:{fk}" if body_add else LOCK_KEY
        now = int(time.time())
        con = _con()
        try:
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT value FROM kv WHERE ns=? AND key=?", (f"fbot:{bot_id}", lock_key)).fetchone()
            if (r and now - int(r[0] or 0) < SPAWN_GRACE and (lock_since is None or int(r[0] or 0) >= lock_since)
                    and (body_add or not _lock_body_ended(con, bot_id, int(r[0] or 0)))):
                con.execute("ROLLBACK")
                return wk, {"skipped": "claimed", "since": int(r[0]), "prj": prj}
            con.execute("INSERT INTO kv(ns,key,value,updated_at,updated_by) VALUES(?,?,?,?,?)"
                        " ON CONFLICT(ns,key) DO UPDATE SET value=excluded.value,"
                        " updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                        (f"fbot:{bot_id}", lock_key, str(now), now, "fbot-inbox"))
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            con.close()
        # prj3#Issue779_7 — 출근 훅이 미처리 목록을 이미 주입한다(fbot-checkin «인박스» 절). 종전 지시문은
        #   `pending` 을 다시 부르게 해 몸체마다 조회 1회(4일 70회)가 더 들었다
        task = "인박스 요청 reply — 출근 컨텍스트 «인박스» 절 참조"   # Issue889 — 기동 줄 1,000B 예산(prj3 팀장 id·flow 포함 최악에도 들어가게 짧게)
        if body_add:
            # 흐름 몸체는 자기 요청을 맡는다 — 다른 요청은 이미 살아 있는 몸체가 본다(요청별 claim 이 중복을 막는다)
            task = f"인박스 요청 {fk} reply — 출근 컨텍스트 «인박스» 절 참조"
        nxt = _mod("fbot_lead", "fbot-lead.py")._spawn_commands(bot_id, task, "", prj, mode="wake",
                                                                 role=row["role"], flow=fk)
        cmd = nxt["fpm_do"]
        # prj3#Issue889 — 줄여도 한도를 넘는 기동 줄은 잘려 `quote>` 로 멈춘다 — 띄우지 않고 실패로 드러낸다(침묵 실패 금지)
        res = ({"ok": False, "error": f"기동 줄 {nxt.get('line_bytes')}B 가 한도 초과 — 잘림 방지로 기동 거부"}
               if nxt.get("line_over") else _run_spawn(cmd))
        sp = dict(res, prj=prj, cmd=cmd)
        con = _con()
        try:
            _st = _state()
            _st.record_event(con, bot_id, "wake",
                             f"인박스 기상 prj{prj}{f' · 몸체 추가 흐름 {fk}' if body_add else ''} · {reason[:60]} · "
                             f"{'ok' if res.get('ok') else res.get('error', 'fail')}")
            _st.notify_hub_event(bot_id, "wake")
        finally:
            con.close()
        return wk, sp
    except Exception as e:   # 기상 실패는 드러내되 적재를 막지 않는다
        return {"error": f"{type(e).__name__}: {e}"[:300]}, {"skipped": "error"}


REWAKE_WAIT = int(os.environ.get("FBOT_REWAKE_WAIT") or 30)   # 전 몸체가 창을 비울 때까지 대기 상한(초)
WAKE_LOG = os.environ.get("FBOT_WAKE_LOG") or os.path.join(   # 🧪 FBOT_WAKE_LOG 는 테스트 주입구(실로그 오염 방지)
    os.path.expanduser("~"), ".claude", "data", "fbot", "logs", "inbox-wake.log")


def _wake_log(line):
    try:
        os.makedirs(os.path.dirname(WAKE_LOG), exist_ok=True)
        with open(WAKE_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
    except OSError:
        pass


def rewake(bot_id, wait_secs=None):
    """퇴근 재기상 (prj3#Issue748) — 퇴근 훅이 부른다. **이 몸체가 출근한 뒤 도착한** 미응답 요청이
    남았으면 바로 다시 깨운다.

    요청 도착 시 몸체가 살아 있으면 `send` 는 기상을 건너뛴다(`alive`). 그런데 봇 몸체는 `claude -p`
    1회 실행이라 실행 중 넛지(③)가 닿지 않는다 — 몸체가 스스로 재조회하지 않고 끝나면 그 요청은
    다음 tick(최대 30분)까지 방치됐다(Issue734 실증 2026-09-27).

    기준을 «출근 후 도착분» 으로 좁히는 것이 루프 방지다. 출근 전부터 있던 요청은 그 몸체가 출근
    주입으로 이미 받았다 — 못 끝냈으면 tick·에스컬레이션이 맡는다. 그래서 몸체가 곧바로 죽어도
    퇴근 → 재기상 → 퇴근 이 반복되지 않는다."""
    con = _con(readonly=True)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT * FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
        if not row or not _org().is_manager(row["role"]):
            return {"ok": True, "action": "rewake", "bot_id": bot_id, "skipped": "not_manager"}
        if row["state"] != "checkout":
            # 퇴근 전이가 안 됐거나, 그 사이 다른 발신이 이미 깨웠다
            return {"ok": True, "action": "rewake", "bot_id": bot_id, "skipped": "not_checkout"}
        since = con.execute(
            "SELECT MAX(created_at) FROM job WHERE kind='fbot_event' AND owner=?"
            " AND json_extract(payload,'$.type')='state:checkin'", (bot_id,)).fetchone()[0]
        if not since:
            return {"ok": True, "action": "rewake", "bot_id": bot_id, "skipped": "no_checkin"}
        n = con.execute("SELECT COUNT(*) FROM job WHERE kind=? AND owner=? AND status='open'"
                        " AND result IS NULL AND created_at>=?" + Q_NOT, (KIND, bot_id, int(since))).fetchone()[0]
        n += con.execute("SELECT COUNT(*) FROM job WHERE kind=?" + Q_TO_LEAD + " AND status='open'"   # Issue757 팀원 질문
                         " AND result IS NULL AND created_at>=?", (KIND, bot_id, int(since))).fetchone()[0]
        tmux_target = row["tmux_target"]
    finally:
        con.close()
    if not n:
        out = {"ok": True, "action": "rewake", "bot_id": bot_id, "skipped": "no_new_requests", "since": since}
        _wake_log(f"rewake {bot_id} — 출근 후 도착 미응답 0건, 재기상 안 함")
        return out
    # 전 몸체가 창을 비울 때까지 — fpm-do 는 살아 있는 봇 창에 주입을 거부한다(«봇 창 점유 중»)
    wait = REWAKE_WAIT if wait_secs is None else wait_secs
    if wait > 0 and tmux_target:
        end = time.time() + wait
        while time.time() < end and _state().session_presence(tmux_target) == "present":
            time.sleep(1)
    wk, sp = wake_and_spawn(bot_id, reason=f"퇴근 재기상 — 출근 후 도착 {n}건", lock_since=int(since))
    _wake_log(f"rewake {bot_id} — 출근 후 도착 {n}건 → wake={wk.get('verdict') or wk} spawn="
              f"{'ok' if sp.get('ok') else sp.get('skipped') or sp.get('error')}")
    return {"ok": True, "action": "rewake", "bot_id": bot_id, "since": since, "new_requests": n,
            "wake": wk, "spawn": sp}


def wake_pending(apply=False):
    """tick 안전망 — 미응답 `open` 요청이 있는 퇴근·사망 매니저를 일괄 기상한다.
    `send` 의 기상이 실패했거나(tmux 없는 발신 환경 등) 잠금이 풀린 뒤 재시도하는 자리다."""
    con = _con(readonly=True)
    con.row_factory = sqlite3.Row
    try:
        owners = [r[0] for r in con.execute(
            "SELECT DISTINCT owner FROM job WHERE kind=? AND status='open' AND result IS NULL" + Q_NOT
            + Q_NOT_DISPATCHING, (KIND,))]
        owners += [r[0] for r in con.execute(   # prj3#Issue757 — 팀원 질문을 받은 팀장
            "SELECT DISTINCT json_extract(payload,'$.to_lead') FROM job WHERE kind=? AND status='open'"
            " AND result IS NULL AND json_extract(payload,'$.kind')='question'"
            " AND json_extract(payload,'$.to_lead') IS NOT NULL", (KIND,)) if r[0] and r[0] not in owners]
        rows = [con.execute("SELECT * FROM bot WHERE bot_id=?", (o,)).fetchone() for o in owners]
    finally:
        con.close()
    org = _org()
    cands = [r["bot_id"] for r in rows if r and org.is_manager(r["role"]) and _wakeable(r)[0]]
    out = {"ok": True, "action": "wake-pending", "candidates": cands, "applied": apply, "woken": [], "results": {}}
    if apply:
        for b in cands:
            wk, sp = wake_and_spawn(b, reason="tick wake-pending")
            out["results"][b] = {"wake": wk, "spawn": sp}
            if sp.get("ok"):
                out["woken"].append(b)
    return out


def send(to, body, from_bot="", from_session="", req_kind="ask", prj=None, corr_id=None, spawn=True,
         from_human=None, extra=None):
    """요청 적재. 🔴 **결속 여부를 보지 않는다** — 그것이 이 설계의 요점이다.
    적재 뒤 수신 매니저가 퇴근·사망이면 깨운다(prj3#Issue734) — `spawn=False` 면 판정만 건너뛴다.

    `from_human`(prj3#Issue749) — 발신 세션이 **사람이 보는 세션**인가. 미지정이면 env 로 판정한다
    (`FPM_SESSION_ORIGIN=pm-do` 는 `claude -p` 봇 몸체 = 사람 없음). 이 요청을 처리하며 낸 배분의
    질문이 어디로 올라갈지(`requester_of` ③)를 이 값이 정한다."""
    if from_human is None:
        from_human = bool(from_session) and os.environ.get("FPM_SESSION_ORIGIN") != "pm-do"
    con = _con()
    try:
        row = _bot(con, to)
        if not row:
            return {"ok": False, "error": f"대장에 없는 수신자: {to}"}
        org = _org()
        rerouted_from = None
        sender = _bot(con, from_bot) if from_bot else None
        ambiguous = False
        if sender is None and not from_bot and from_session:
            # 봇 몸체 세션이 --from-bot 을 빼고 보내면 «사람» 으로 보여 ⓐ 를 비켜간다 — 세션의 결속으로 발신 봇을 찾는다.
            #   한 세션에 결속이 여럿(부모 + Agent 하청 — 같은 session_id, Issue449)이면 누구인지 모른다 →
            #   봇으로도 사람으로도 보지 않는다(재료 부재 = 종전 통과)
            bs = con.execute("SELECT bot_id FROM bot WHERE session_id=? AND state<>'checkout' LIMIT 2",
                             (from_session,)).fetchall()
            if len(bs) == 1:
                sender = _bot(con, bs[0][0])
            ambiguous = len(bs) > 1
        human = sender is None and not ambiguous and not from_bot and bool(from_session)
        # ⓐ 총괄 ↔ 비관리직 양방향 거부(prj3#Issue757 F) · ⓒ 인사핀봇은 팀장 발신만(prj3#Issue831 ③) — 판정은 _talk_error 한 곳
        terr = _talk_error(org, sender, row) if sender else None
        if terr:
            return {"ok": False, "error": terr}
        # ⓑ 사람의 지시는 총괄·팀장이 받는다 — prj3#Issue757 I
        if human and not org.is_nonexec(row["role"]):
            if org.is_manager(row["role"]):
                return {"ok": False, "error":
                        f"{to}(role={row['role']}) 는 사람의 지시를 받지 않는다 — 사람의 지시는 "
                        f"그 prj 팀장 또는 총괄이 받아 배분한다"}
            lead = _team_lead(con, to, org)
            if not lead:
                return {"ok": False, "error":
                        f"{to}(role={row['role']}) 는 사람의 지시를 받지 않고, 돌려 보낼 팀장도 없다 — "
                        f"그 prj 팀장 또는 총괄에게 보낸다"}
            rerouted_from, to = to, lead
            body = f"[원 수신자 {rerouted_from} — 사람의 지시는 팀장이 받는다(Issue757)] {body}"
            row = _bot(con, to)
        if not org.is_manager(row["role"]):
            # 워커에게 직접 꽂으면 결속 경쟁·문맥 전환이 재발한다. 매니저를 거쳐야 한다.
            return {"ok": False, "error":
                    f"{to}(role={row['role']}) 는 매니저가 아니다 — 인박스가 없다. "
                    f"매니저(chief·lead·hr)에게 보내면 그가 판단해 지시한다"}
        rid = f"fbotreq-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        # prj3#Issue563 — 되물음 체인 깊이. corr_id 로 잇는 요청은 부모 depth+1 이고 상한을
        #   넘으면 거부한다. 매니저 둘이 서로 되묻는 핑퐁은 원리적으로 무한이라, 상한에서
        #   사람에게 올리는 것이 유일한 종결이다.
        depth = 0
        if corr_id:
            parent = con.execute(
                "SELECT payload FROM job WHERE kind=? AND (id=? OR json_extract(payload,'$.corr_id')=?)"
                " ORDER BY created_at LIMIT 1", (KIND, corr_id, corr_id)).fetchone()
            if parent:
                try:
                    depth = int(json.loads(parent[0] or "{}").get("depth") or 0) + 1
                except (ValueError, TypeError):
                    depth = 1
            if depth > CHAIN_MAX:
                return {"ok": False, "error":
                        f"되물음 체인 상한 초과 (depth {depth} > {CHAIN_MAX}) — corr_id {corr_id}. "
                        f"더 묻지 말고 사람에게 올린다: /mq-send --due +0d 또는 escalate", "depth": depth}
        payload = {"from": from_bot, "from_session": from_session, "kind": req_kind,
                   "body": body, "prj": prj, "corr_id": corr_id or rid, "depth": depth,
                   "from_human": bool(from_human)}
        if extra:                                   # prj3#Issue757 T13 — 인력 요청의 직능·사다리 단 등
            payload.update({k: v for k, v in extra.items() if k not in payload})
        # prj3#Issue892 — 응답 못 받은 재시도 멱등: 같은 (수신·발신·세션·kind·본문·상관 id) 가 창 안에 open 이면
        #   새로 적재하지 않고 먼저 것을 돌려준다. 판정·INSERT 를 한 트랜잭션에 둔다(TOCTOU 금지 — Issue843)
        now = int(time.time())
        con.execute("BEGIN IMMEDIATE")
        try:
            dup = con.execute(
                "SELECT id FROM job WHERE kind=? AND status='open' AND owner=? AND created_at>=?"
                " AND json_extract(payload,'$.from') IS ? AND json_extract(payload,'$.from_session') IS ?"
                " AND json_extract(payload,'$.kind') IS ? AND json_extract(payload,'$.body') IS ?"
                " AND json_extract(payload,'$.corr_id') = " + ("?" if corr_id else "job.id") +
                " ORDER BY created_at LIMIT 1",
                (KIND, to, now - SEND_DEDUP_WINDOW, from_bot, from_session, req_kind, body)
                + ((corr_id,) if corr_id else ())).fetchone()
            if not dup:
                con.execute(
                    "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
                    " owner, lease_until, blocked_since, created_at)"
                    " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
                    (rid, "fbot", KIND, "open", json.dumps(payload, ensure_ascii=False), to, now))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        if dup:
            return {"ok": True, "action": "send", "id": dup[0], "to": to, "to_state": row["state"],
                    "corr_id": payload["corr_id"], "dedup": True,
                    "note": f"같은 요청이 {SEND_DEDUP_WINDOW}초 창 안에 이미 open — 새로 적재하지 않았다(Issue892)"}
        _st = _state(); _st.record_event(con, to, "request", f"← {from_bot or from_session[:8] or '?'}: {body[:80]}", rid)   # prj3#Issue575
        _st.notify_hub_event(to, "request", rid)
        out = {"ok": True, "action": "send", "id": rid, "to": to,
               "to_state": row["state"], "corr_id": payload["corr_id"],
               "note": "결속 여부와 무관하게 적재된다"}
        if rerouted_from:
            out["rerouted_from"] = rerouted_from
    finally:
        con.close()
    # 적재 커밋·커넥션 반납 **뒤** 기상 — HR 게이트·reap 이 같은 DB 에 쓰므로 잠금을 쥔 채 부르지 않는다
    out["wake"], out["spawn"] = wake_and_spawn(to, reason=f"요청 {rid}", spawn=spawn,
                                               flow=rid if opens_flow(req_kind) else None)
    return out


# ── 응답 defer (prj3#Issue736) ────────────────────────────────────────────────
# 실발생(2026-09-27 21:17): prj13 팀장핀봇이 총괄 배분(Issue58)을 마치며 «push 는 사용자 몫» 으로 끝났다.
#   그 몸체는 fpm-do 의 `claude -p` 라 응답 1회 뒤 종료됐고 pane 은 zsh 로 돌아갔다 — 응답을 줄 사람은 그 세션에
#   닿을 수 없는데 봇은 응답 대기였다. sweep 의 완료 통지는 verdict·해시만 실어 «사용자가 결정할 것» 을 나르지 못한다.
# 규칙(사용자 제시): 응답 대기 봇은 **팀장에게 보고**하고, 팀장이 받은 일이 아니면 **총괄이 받은 일이니 총괄에게 defer**.
#   한 줄로: **그 일을 받은 사람이 응답도 받는다** — 활성 배분의 배분자(owner) → 부모 매니저 → 총괄. 매니저만 받는다.
DEFER_BODY_MAX = int(os.environ.get("FBOT_DEFER_BODY_MAX") or 1500)
DISPATCH_ACTIVE = ("open", "blocked", "logged", "deferred")   # fbot-lead active_dispatches 와 같은 집합
# prj3#Issue953 ② — «완료 미확인» 통지가 **살아 있는** 배분 상태. 보류(`deferred`)는 미확인이 풀린 것이라 통지를 닫는다
#   (요청 종결 판정의 `DISPATCH_ACTIVE` 와는 다르다 — 보류 배분은 요청을 닫을 근거가 아니지만 미확인 통지의 용무는 끝났다)
UNCONF_OPEN_STATES = ("open", "blocked", "logged")
# prj3#Issue816 — «배분 중» 판정 단일 지점. `dispatch --request` 로 살아 있는 배분에 연결된 요청은 처리 중이다 —
#   넛지(pending·wake_pending·escalate)에서 뺀다. ACK(accepted) 없이도 그친다. 연결 배분이 전부 취소되면 다시 뜬다.
#   바깥 행은 `job` 으로 참조한다(별칭 없이 FROM job 인 조회에 붙는다)
Q_NOT_DISPATCHING = (" AND NOT EXISTS (SELECT 1 FROM job d WHERE d.kind='fbot_dispatch' AND d.status IN (%s)"
                     " AND json_extract(d.payload,'$.request_id')=job.id)"
                     % ",".join("'%s'" % s for s in DISPATCH_ACTIVE))


def last_assistant_text(transcript_path, limit=DEFER_BODY_MAX):
    """transcript JSONL 의 **마지막 assistant 텍스트**(텍스트 블록 결합, 도구·thinking 제외). 없으면 ""."""
    last = ""
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as f:
            for ln in f:
                if '"assistant"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                c = (d.get("message") or {}).get("content")
                if isinstance(c, str):
                    txt = c.strip()
                elif isinstance(c, list):
                    txt = " ".join((b.get("text") or "").strip() for b in c
                                   if isinstance(b, dict) and b.get("type") == "text").strip()
                else:
                    txt = ""
                if txt:
                    last = txt
    except OSError:
        return ""
    return _clip(last, limit)


def _clip(text, limit):
    """머리를 남기고 꼬리를 조금 붙인다 — 질문·결정 요구는 대개 끝에 있다."""
    if len(text) <= limit:
        return text
    tail = min(300, limit // 5)
    return text[: limit - tail - 1] + "…" + text[-tail:]


def _chief_bot(con, org=None):
    """총괄 개체 — 본사 chief 자리 점유자 우선, 없으면 role=chief 중 prj 없는 첫 개체.
    조회는 fbot-org `chief_bot` 한 곳에 위임한다(prj3#Issue945 검토 R3 — 같은 SQL 사본이 ⓪ cross 와 갈리지 않게).
    `org` = 호출측이 이미 실은 fbot-org 모듈(재적재 비용 생략)."""
    return (org or _org()).chief_bot(con)


def _report_chain(con, bot, dispatcher=None, requester=None, org=None):
    """배분 체인 상향 수신 후보 `[(route, bot_id)]` — 판정 단일 지점. `defer`(워커 보고)와 `notify_unconfirmed`(sweep 이 대신
    올리는 «완료 미확인»)가 같이 쓴다 — 둘이 갈리면 워커가 직접 올렸을 때와 다른 매니저가 미확인을 받는다(prj3#Issue929 검토 ③).
    `bot` = 보고 주체 bot 행(bot_id·role·parent_bot_id). 순서: 기원 요청 발신자(requester) → 배분자 → 부모 →
    팀장(비관리직 발신만) → 총괄(관리직 발신만)."""
    org = org or _org()
    # prj3#Issue757 F — 총괄은 팀장과만 대화한다. 관리직이 아닌 봇(워커·인사·발굴)의 보고는
    #   배분자가 총괄이어도(옛 직행 기록) 총괄로 가지 않고 **그 팀의 팀장**(prj 없으면 본사 팀장)이 받는다
    sender_nx = org.is_nonexec(bot["role"])
    chain = []
    # prj3#Issue791 — 몸체가 그 요청 때문에 떴으면(흐름 = 요청 id) 그 발신자가 «그 일을 받은 매니저» 다.
    #   배분과 둘 다 있으면 흐름이 앞선다 — 흐름은 이 몸체가 깬 이유를 말한다
    if requester:
        chain.append(("requester", requester))
    if dispatcher:
        chain.append(("dispatcher", dispatcher))
    if bot["parent_bot_id"]:
        chain.append(("parent", bot["parent_bot_id"]))
    if not sender_nx:
        tl = _team_lead(con, bot["bot_id"], org)
        if tl:
            chain.append(("team_lead", tl))
    chief = _chief_bot(con, org)
    if chief and sender_nx:
        chain.append(("chief", chief))
    return chain


def _report_target(con, bot, chain, org):
    """사슬에서 첫 수신 가능 매니저 `(bot_id, route)` — 없으면 `(None, None)`. 자기 자신·대장 부재·비매니저·
    대화 규칙 거부(`_talk_error` — send 가드와 같은 판정, Issue831 ③)는 건너뛴다."""
    for why, cand in chain:
        if cand == bot["bot_id"]:
            continue
        r = _bot(con, cand)
        if not (r and org.is_manager(r["role"])):
            continue
        if _talk_error(org, bot, r):
            continue
        return cand, why
    return None, None


def notify_unconfirmed(dispatch_id, body, extra=None):
    """sweep 의 «완료 미확인» 통지 적재 (prj3#Issue929 검토 ③) — fbot-lead `_notify_unconfirmed` 가 부른다.

    수신자 = 워커가 직접 `defer` 했다면 받았을 매니저 — **워커를 보고 주체로 놓은** `_report_chain`(기원 요청 없음: sweep 에는
    몸체 흐름이 없다). 배분자 → 워커의 부모 → 워커 팀의 팀장(비관리직 워커) / 총괄(관리직 워커). 워커가 대장에 없으면
    배분자 → 총괄 중 매니저. 발신은 sweep(봇·세션 없음)이라 사람 지시로 읽히지 않는다. `spawn=False` — 무인 주기라 몸체를
    띄우지 않는다(퇴근 매니저는 tick `wake-pending`). kind 는 fbot-state `UNCONFIRMED`, corr_id = 배분 id(`close_fulfilled` 가 닫는다).
    반환 `send` 결과 + `to`·`route`. 받을 매니저가 없으면 `ok=false`·`tried` — 폴백 수신자를 지어내지 않는다
    (종전 `[owner, "fbot-lead"]` 는 실재하지 않을 수 있는 이름으로 보냈다)."""
    con = _con()
    chain, to, route, prj = [], None, None, None
    try:
        d = con.execute("SELECT owner, payload FROM job WHERE id=? AND kind='fbot_dispatch'", (dispatch_id,)).fetchone()
        if not d:
            return {"ok": False, "error": f"배분 없음: {dispatch_id}", "dispatch_id": dispatch_id, "tried": []}
        pl = _pl(d["payload"])
        org = _org()
        wid = pl.get("worker_bot_id")
        bot = con.execute("SELECT bot_id, role, prj, parent_bot_id FROM bot WHERE bot_id=?",
                          (wid,)).fetchone() if wid else None
        if bot:
            chain = _report_chain(con, bot, dispatcher=d["owner"], org=org)
            to, route = _report_target(con, bot, chain, org)
            prj = bot["prj"]
        else:
            chief = _chief_bot(con, org)
            chain = [(w, c) for w, c in (("dispatcher", d["owner"]), ("chief", chief)) if c]
            for why, cand in chain:
                r = _bot(con, cand)
                if r and org.is_manager(r["role"]):
                    to, route = cand, why
                    break
            prj = pl.get("prj")
    finally:
        con.close()
    if not to:
        return {"ok": False, "dispatch_id": dispatch_id, "tried": [f"{w}:{c}" for w, c in chain],
                "error": "«완료 미확인» 을 받을 매니저가 없다 — 배분자·부모·팀장·총괄 모두 부재·비매니저·대화 규칙 밖"}
    out = send(to, body, "", "", req_kind=_state().UNCONFIRMED, prj=prj, corr_id=dispatch_id, spawn=False,
               extra=extra or None)
    out.update({"to": to, "route": route})
    return out


def defer(from_bot="", from_session="", body="", transcript="", spawn=True, status=None, note=""):
    """응답 대기 봇의 응답을 **배분 체인 위로** 올린다. 반환 dict 는 `send` 의 것 + route.

    수신자: ① 그 일을 받은 매니저 — **흐름이 가리키는 기원 인박스 요청의 발신자**(prj3#Issue791) 또는 활성 배분의
    배분자 ② 부모 매니저 ③ 총괄. 매니저가 아니면 다음 후보로.
      Issue791 — 배분이 아닌 **인박스 요청 기원** 작업(총괄 요청으로 깬 팀장 몸체)은 활성 배분이 없어 route=parent 로
      떨어졌고, 결정 요구 없는 경과·완료 보고가 층마다 새 `-p` 세션을 띄웠다(prj16 팀장 → 본사 팀장 → 총괄).
      «받은 일» 의 판정에 인박스 요청을 더한다 — 식별은 몸체 흐름(`_origin_request`)뿐, 지어내지 않는다.
    본문: `--body` 우선, 없으면 transcript 의 마지막 assistant 텍스트. 둘 다 없으면 fail-loud —
    빈 인계는 받는 쪽이 판단할 수 없어 «무시된 요청» 과 같다.
    `status`(prj3#Issue929) — 워커가 **명시**하는 배분 결과 `done`·`incomplete`. 요청 payload `report_status` 로 싣고, sweep 이
      topic 배분의 완료 증적으로 읽는다(마지막 명시 status 가 done 이 아니면 «완료 미확인»). 명시 보고는 질문 판정·질문 덧붙임을
      타지 않는다 — 결과 선언이지 결정 요구가 아니다. 활성 배분이 있으면 `dispatch_id` 를 함께 단다(요청자 경로로 가도 짝이 남게).
    `note`(prj3#Issue951) — 본문 **앞**에 붙이는 표지. Stop 가드가 «미완 백그라운드를 남기고 퇴근» 을 알릴 때 쓴다 — 몸체의
      마지막 말(«끝나면 알림이 온다»)만 올라가면 매니저는 진행 중으로 읽는다(2026-10-05 prj8 실발생). 마지막 말이 없어도 표지만으로 보낸다.
    """
    if status is not None:
        allowed = _state().REPORT_STATUSES   # 어휘 정본 fbot-state(prj3#Issue929) — fbot-lead sweep 이 같은 값을 읽는다
        if status not in allowed:
            return {"ok": False, "error": f"--status 는 {'·'.join(allowed)} 중 하나: {status!r}"}
    con = _con()
    is_q = None
    try:
        if not from_bot and from_session:
            r = con.execute("SELECT bot_id FROM bot WHERE session_id=? ORDER BY "
                            "CASE state WHEN 'checkout' THEN 1 ELSE 0 END LIMIT 1", (from_session,)).fetchone()
            from_bot = r["bot_id"] if r else ""
        if not from_bot:
            return {"ok": False, "error": "발신 봇을 알 수 없다 — --from-bot 또는 결속된 --from-session 필요"}
        bot = con.execute("SELECT bot_id, role, prj, parent_bot_id FROM bot WHERE bot_id=?", (from_bot,)).fetchone()
        if not bot:
            return {"ok": False, "error": f"대장에 없는 발신 봇: {from_bot}"}
        text = (body or "").strip()
        # prj3#Issue749 — 질문 판정은 **자르기 전 원문**(줄 구조 보존)으로 한다. 선택지는 줄머리에 있다
        full = text or (_qjudge().last_assistant_text(transcript) if transcript else "")
        if not text and transcript:
            text = last_assistant_text(transcript)
        if (note or "").strip():
            text = note.strip() + ("\n\n" + text if text else "")
        if not text:
            return {"ok": False, "error": "위임할 응답 본문이 없다 — --body 또는 --transcript(마지막 assistant 텍스트) 필요",
                    "from_bot": from_bot}
        text = _clip(text, DEFER_BODY_MAX)
        disp = _active_dispatch(con, from_bot)
        origin = _origin_request(con, from_bot, from_session)
        # prj3#Issue749 ⑤ — 미종결 질문이 있으면 새 인계를 만들지 않고 그 질문에 덧붙인다.
        #   2차 Stop(«도구 없음» 등)이 질문을 덮는 두 번째 요청이 되어 사람이 엉뚱한 것에 답했다.
        oq = _open_question(con, from_bot) if status is None else None
        if oq:
            return _question_append(con, oq, text, from_bot)
        verdict = _qjudge().judge(full) if status is None else {"question": False}
        if status is None:
            _qjudge().shadow(full, verdict)  # prj3#Issue863_11 — Jev shadow(분리 기동 · 판정 불변)
        if verdict["question"]:
            is_q = verdict
        else:
            org = _org()
            # 수신 사슬·선택은 `_report_chain`·`_report_target` 단일 지점(«완료 미확인» 통지와 공용 — prj3#Issue929 검토 ③)
            chain = _report_chain(con, bot, dispatcher=disp["owner"] if disp else None,
                                  requester=origin["from"] if origin else None, org=org)
            to, route = _report_target(con, bot, chain, org)
            if not to:
                return {"ok": False, "error": "응답을 받을 매니저가 없다 — 배분자·부모·팀장(총괄은 관리직 발신만) 모두 부재 또는 비매니저",
                        "from_bot": from_bot, "tried": [f"{w}:{c}" for w, c in chain]}
        prj = bot["prj"]
    finally:
        con.close()
    if is_q:
        # 끝난 말(defer)이 아니라 **진행 중 결정 요구**다 — 매니저 인박스가 아니라 사람이 있는 세션으로
        return ask_question(from_bot, from_session, text, is_q.get("options") or [], disp, spawn=spawn)
    # 상관 id 는 보고가 «어느 일» 의 것인가 — 요청자에게 가면 그 요청, 그 밖은 활성 배분(Issue791)
    corr = origin["id"] if route == "requester" else (disp["id"] if disp else None)
    extra = dict(_state().body_stamp() or {})         # prj3#Issue757 T15 ⑥ — 어느 몸체(세션·흐름)가 올렸나
    if disp:
        extra["dispatch_id"] = disp["id"]              # prj3#Issue929 — 요청자 경로(corr=요청 id)로 가도 배분과 짝이 남는다
    if status:
        extra["report_status"] = status                # prj3#Issue929 — sweep 의 topic 배분 완료 증적
    out = send(to, text, from_bot, from_session, req_kind="defer", prj=prj,
               corr_id=corr, spawn=spawn, extra=extra or None)
    if out.get("ok"):
        con = _con()
        try:
            _state().record_event(con, from_bot, "defer", f"→ {to} ({route}): {text[:80]}", out["id"])
        finally:
            con.close()
    out.update({"action": "defer", "from_bot": from_bot, "route": route, "to": to,
                "dispatch": disp["id"] if disp else None, "origin": origin["id"] if origin else None})
    return out


def _body_flow(con, from_bot, from_session):
    """이 몸체의 흐름 키 — env `FBOT_FLOW`(스폰 시 주입, prj3#Issue757 T15 ④) 우선, 없으면 몸체 원장(`fbot_body.flow`)."""
    fk = (os.environ.get("FBOT_FLOW") or "").strip()
    if fk:
        return fk
    if not from_session:
        return ""
    for b in _state().open_bodies(con, from_bot):
        if b.get("session_id") == from_session and b.get("flow"):
            return str(b["flow"])
    return ""


def _origin_request(con, from_bot, from_session):
    """몸체가 **그 요청 때문에 떴는가** — 흐름이 이 봇 앞 인박스 요청(질문 제외)이고 발신자가 봇이면 그 요청 (prj3#Issue791).
    반환 `{"id", "from", "status"}` 또는 None. 상태는 보지 않는다 — 요청자에게 `done` 으로 답한 뒤의 마지막 보고도
    같은 요청자의 것이다(실측 3번째 defer 가 부모로 새던 자리). 남의(owner≠봇) 요청·사람 발신(from 없음)은 None —
    사람 요청의 보고는 종전 체인(부모·팀장)으로 간다(수신자 판정에 사람 세션을 지어내지 않는다)."""
    fk = _body_flow(con, from_bot, from_session)
    if not fk:
        return None
    r = con.execute("SELECT owner, status, payload FROM job WHERE kind=? AND id=?", (KIND, fk)).fetchone()
    if not r or r["owner"] != from_bot:
        return None
    pl = _pl(r["payload"])
    if pl.get("kind") == "question" or not pl.get("from"):
        return None
    return {"id": fk, "from": pl["from"], "status": r["status"]}


# ── 질문 상향 중계 (prj3#Issue749) ────────────────────────────────────────────
# 실발생(2026-09-28 prj5 test-folder 정리): 팀장이 사람에게 물을 것(보호 폴더)을 mq [컨펌] 으로 우회했고,
#   ACK 뒤 아무 일도 일어나지 않아 의뢰 세션이 손으로 나래 인박스에 전달하고 wake-pending 을 돌렸다.
#   사용자 지시: «mq 를 통하는 방식은 권장되지 않음». `claude -p` 몸체에는 AskUserQuestion 이 없다(M0 실측).
# 규칙: **사람에게 의뢰를 받은 세션이 질문도 받는다.** 워커 평문 질문(Stop) → 의뢰 세션 다음 턴 넛지 →
#   그 세션이 AskUserQuestion 으로 묻고 `reply` → 배분 재개 + **같은 봇 재기동**(답을 들고).
# 🔴 개정(prj3#Issue757): *"사람의 지시를 받는 것은 총괄과 팀장뿐"*. 워커 질문이 사람 세션으로 직통하면 사람의 답이
#   곧 워커에게 내리는 지시가 된다. **관리직(nonexec)이 아닌 봇의 질문은 그 팀장이 받는다**(배분한 팀장 → 그 prj
#   팀장 → 본사 팀장) — 팀장 인박스에 보이고 팀장을 깨운다. 팀장은 L 로 답하거나, 사람 결정이 필요하면 자기 질문으로
#   올린다 — 🔴 개정(prj3#Issue831 ①): 팀장의 질문은 **총괄**이 받는다(사람 결정은 팀장 → 총괄 → 사람 한 갈래,
#   `reply --needs-human` 의 총괄 상신과 같은 길). 사람 세션·공용 경로는 **총괄의 질문**에만 남는다 — 팀장 질문은 원 의뢰
#   세션(`requester_session`)을 싣고 가서 총괄이 되물을 때 `requester_of` ④ 가 그 세션을 고른다.
#   ⓐ 판정 = hooks/lib/decision-question.py(가드와 공용) ⓑ 수신 = requester_of() 단일 지점
#   ⓒ 질문은 묻는 봇 귀속(owner) — 매니저 인박스·기상·mq 에스컬레이션 밖(Q_NOT)
#   ⓓ 의뢰 세션 미상 → 공용(어느 사람 세션이든 다음 턴) · 오래되면 공용으로 확대 — mq 폴백 없음
REQUESTER_DEPTH = 6
SAY_SH = os.environ.get("FBOT_QUESTION_SAY_SH") or os.path.join(HERE, "hook-say.sh")   # 🧪 "off"·스텁 주입구


def _qjudge():
    return _mod("decision_question", os.path.join("lib", "decision-question.py"))


def _pl(raw):
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


def _handoff_dir():
    """질문 마커 디렉토리 — `fbot-inbox-nudge.sh` 의 `_QD` 와 **같은 해석**(둘이 갈리면 질문이 안 닿는다).
    ① 주입구 FBOT_HANDOFF_DIR(테스트) ② 원장을 갈아끼운 실행(FBOT_REGISTRY_DB)이면 그 원장 옆 — 격리 원장이
    운영 마커를 지우는 사고를 구조적으로 막는다 ③ 운영 `~/.claude/.fbot-handoff`(결속 마커와 같은 곳, gitignore).
    ⚠️ 운영 판정에 원장 경로를 쓰지 않는다 — 운영 원장은 `AOA_MEMORY_DIR`(prj5 ___common) 아래라 경로로는
    테스트와 구분되지 않고, 그 옆에 두면 타 repo 에 미추적 파일이 생긴다."""
    d = os.environ.get("FBOT_HANDOFF_DIR")
    if d:
        return d
    rdb = os.environ.get("FBOT_REGISTRY_DB")
    if rdb:
        return os.path.join(os.path.dirname(os.path.abspath(rdb)), ".fbot-questions")
    return os.path.join(os.path.expanduser("~"), ".claude", ".fbot-handoff")


def _is_human_request(pl):
    fh = pl.get("from_human")
    if fh is not None:
        return bool(fh) and bool(pl.get("from_session"))
    # 구 요청(필드 도입 전) — 봇 명의가 없고 세션이 보낸 것만 사람으로 본다
    return bool(pl.get("from_session")) and not pl.get("from")


def _checkin_at(con, bot_id):
    r = con.execute("SELECT MAX(created_at) FROM job WHERE kind='fbot_event' AND owner=?"
                    " AND json_extract(payload,'$.type')='state:checkin'", (bot_id,)).fetchone()
    return int(r[0] or 0) if r else 0


def _worker_dispatches(con, bot_id):
    """이 봇이 **워커로 받은** 활성 배분 — open·blocked 우선, 그다음 최신순(fpm-do 사후 기록 logged 와의 이중 기록 대비)."""
    rows = con.execute(
        "SELECT id, owner, status, payload FROM job WHERE kind='fbot_dispatch' AND status IN (%s)"
        " AND json_extract(payload,'$.worker_bot_id')=?"
        " ORDER BY CASE WHEN status IN ('open','blocked') THEN 0 ELSE 1 END, created_at DESC, rowid DESC"
        % ",".join("?" * len(DISPATCH_ACTIVE)), (*DISPATCH_ACTIVE, bot_id)).fetchall()
    return [{"id": r[0], "owner": r[1], "status": r[2], "payload": _pl(r[3])} for r in rows]


def _active_dispatch(con, bot_id):
    ds = _worker_dispatches(con, bot_id)
    return ds[0] if ds else None


def requester_of(con, bot_id, env=None, _depth=0, _seen=None):
    """«사람에게 의뢰를 받은 세션» 판정 **단일 지점** (prj3#Issue749). 반환 dict 또는 None.

    `{"session": <사람 세션 id>, "via": session|dispatch|lineage|question|request, "ref": <근거 job id>, "ambiguous": bool}`
      ① env — 호출 세션이 사람 세션(`FPM_SESSION_ORIGIN≠pm-do` + `CLAUDE_CODE_SESSION_ID`)이면 그 세션.
         배분 시점(fbot-lead dispatch)에만 넘긴다 — 질문 시점의 env 는 묻는 봇 몸체의 것이다
      ② 이 봇이 워커로 받은 배분의 `requester_session` 상속 — 없으면 그 배분자의 계보를 올라간다(구 배분 소급)
      ④ 이 봇이 받은 팀장 질문의 `requester_session` — 총괄이 팀장 대신 사람에게 되물을 때(prj3#Issue831 ①)
      ③ 이 봇 앞 인박스 요청 중 **사람 세션이 보낸 것** — 총괄이 인박스 요청을 처리하며 낸 배분
    판정 불가는 None 이다 — 지어내지 않는다(호출자가 공용 경로로 보낸다)."""
    if env is not None:
        sid = env.get("CLAUDE_CODE_SESSION_ID") or ""
        if sid and env.get("FPM_SESSION_ORIGIN") != "pm-do":
            return {"session": sid, "via": "session", "ref": None, "ambiguous": False}
    seen = _seen if _seen is not None else set()
    if not bot_id or _depth > REQUESTER_DEPTH or bot_id in seen:
        return None
    seen.add(bot_id)
    ds = _worker_dispatches(con, bot_id)
    for d in ds:
        if d["payload"].get("requester_session"):
            return {"session": d["payload"]["requester_session"], "via": "dispatch", "ref": d["id"],
                    "ambiguous": False}
    for d in ds:
        if d["owner"] and d["owner"] != bot_id:
            r = requester_of(con, d["owner"], None, _depth + 1, seen)
            if r:
                return dict(r, via="lineage", ref=d["id"])
    # ④ prj3#Issue831 ① — 이 봇(총괄)이 받은 **팀장의 미결 질문**이 실어 온 원 의뢰 세션. 팀장의 사람 결정은 총괄을
    #   거친다 — 총괄이 사람에게 되물을 때 원래 의뢰한 사람의 세션으로 간다. ③ 보다 앞: 총괄 앞 사람 요청은 이 결정과
    #   무관할 수 있지만, 받은 질문은 총괄이 지금 되묻는 바로 그 결정이다
    for r in con.execute("SELECT id, payload FROM job WHERE kind=? AND status='open'" + Q_TO_LEAD +
                         " ORDER BY created_at DESC, rowid DESC LIMIT 10", (KIND, bot_id)).fetchall():
        sid = _pl(r[1]).get("requester_session")
        if sid:
            return {"session": sid, "via": "question", "ref": r[0], "ambiguous": False}
    since = _checkin_at(con, bot_id)
    cands = []
    for r in con.execute("SELECT id, status, payload, result FROM job WHERE kind=? AND owner=?" + Q_NOT +
                         " ORDER BY created_at DESC, rowid DESC LIMIT 30", (KIND, bot_id)).fetchall():
        pl = _pl(r[2])
        if not _is_human_request(pl):
            continue
        at = int(_pl(r[3]).get("at") or 0) if r[3] else 0
        # 미결(open) 이거나 이 몸체가 출근한 뒤 처리한 것 — 몸체 수명 밖의 옛 요청은 근거가 아니다
        if r[1] == "open" or (since and at >= since):
            cands.append((r[0], pl["from_session"]))
    if cands:
        return {"session": cands[0][1], "via": "request", "ref": cands[0][0],
                "ambiguous": len({c[1] for c in cands}) > 1}
    return None


def _open_questions(con):
    rows = con.execute("SELECT id, owner, payload, created_at FROM job WHERE kind=? AND status='open'"
                       " AND json_extract(payload,'$.kind')='question' ORDER BY created_at", (KIND,)).fetchall()
    return [{"id": r[0], "owner": r[1], "payload": _pl(r[2]), "created_at": r[3]} for r in rows]


def _open_question(con, bot_id):
    for q in reversed(_open_questions(con)):
        if q["payload"].get("from") == bot_id:
            return q
    return None


def _q_public(pl):
    """공용 질문 — 의뢰 세션 미상이거나 오래 답이 없어 확대된 것. 어느 사람 세션이든 본다."""
    if pl.get("to_lead"):          # 팀장 앞 질문(prj3#Issue757)은 사람 세션에 보이지 않는다
        return False
    return not pl.get("to_session") or bool(pl.get("widened_at"))


def _qmark_sync():
    """질문 마커 = 원장의 사영. 원장을 다시 읽어 필요한 마커만 남긴다(생성·제거가 한 함수).
    마커는 넛지 hook 의 무비용 게이트(`[ -f ]`)일 뿐 권위가 아니다 — 권위는 원장이다."""
    try:
        con = _con(readonly=True)
        try:
            qs = _open_questions(con)
        finally:
            con.close()
    except sqlite3.Error:
        return
    want = {"q-any"} if any(_q_public(q["payload"]) for q in qs) else set()
    for q in qs:
        sid = q["payload"].get("to_session") or ""
        if sid and all(c.isalnum() or c in "-_" for c in sid):
            want.add(f"q-{sid}")
    d = _handoff_dir()
    try:
        os.makedirs(d, exist_ok=True)
        have = {f for f in os.listdir(d) if f.startswith("q-")}
        for f in want - have:
            open(os.path.join(d, f), "a").close()
        for f in have - want:
            os.remove(os.path.join(d, f))
    except OSError:
        pass


def _say_alert(text):
    """유휴 의뢰 세션 대비 음성 1회 — 세션에 턴이 오지 않으면 넛지가 뜨지 않는다. mq 가 아니다.
    격리 실행(`FBOT_HUB_EVENT_URL=off` — fbot 테스트 공통 격리 신호)에서는 스텁을 주입하지 않으면 울리지 않는다."""
    import subprocess
    if SAY_SH == "off" or (os.environ.get("FBOT_HUB_EVENT_URL") == "off"
                           and not os.environ.get("FBOT_QUESTION_SAY_SH")):
        return
    try:
        subprocess.run([SAY_SH, "waiting", text], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def _question_append(con, q, text, from_bot):
    """같은 봇의 미종결 질문에 후속 말을 덧붙인다 — 새 요청을 만들지 않는다(⑤ 이중 인계 방지)."""
    pl = q["payload"]
    fu = pl.get("followups") if isinstance(pl.get("followups"), list) else []
    fu.append({"at": int(time.time()), "text": text[:500]})
    pl["followups"] = fu[-5:]
    cur = con.execute("UPDATE job SET payload=? WHERE id=? AND status='open'",
                      (json.dumps(pl, ensure_ascii=False), q["id"]))
    if cur.rowcount != 1:
        # 조회와 갱신 사이에 답이 와서 닫혔다 — 덧붙임이 사라졌는데 성공으로 보고하지 않는다(리뷰 LOW-1)
        return {"ok": False, "action": "question-append", "id": q["id"], "from_bot": from_bot,
                "error": "질문이 방금 닫혔다 — 덧붙임 미적용(재기동 몸체가 이어서 보고한다)"}
    return {"ok": True, "action": "question-append", "id": q["id"], "from_bot": from_bot,
            "to_session": pl.get("to_session"), "followups": len(pl["followups"]),
            "note": "미종결 질문에 덧붙임 — 새 인계를 만들지 않는다"}


def _question_lead(con, from_bot, role, disp, org):
    """질문을 받을 **윗 관리직** — 사람 결정은 팀장 → 총괄 → 사람 한 갈래다(prj3#Issue831 ①).
      팀원(nonexec 아님, prj3#Issue757): ① 그 일을 배분한 팀장(총괄 직행 옛 기록은 제외) ② 그 봇 팀의 팀장(prj 없으면 본사 팀장)
      팀장(총괄 아닌 관리직): 총괄 — 팀장은 사람 세션으로 직접 묻지 않는다. 총괄 부재면 None(종전 사람 경로 — 재료 부재 = 종전)
      총괄: None — 사람 창구는 총괄이다(의뢰 세션·공용)."""
    if role == CHIEF_ROLE:
        return None
    if org.is_nonexec(role):
        ch = _chief_bot(con, org)
        return ch if ch and ch != from_bot else None
    if disp and disp.get("owner") and disp["owner"] != from_bot:
        r = _bot(con, disp["owner"])
        if r and org.is_nonexec(r["role"]) and r["role"] != CHIEF_ROLE:
            return disp["owner"]
    return _team_lead(con, from_bot, org)


def ask_question(from_bot, from_session, text, options, disp, spawn=True):
    """질문 적재 + 배분 `blocked(question)` 을 **한 트랜잭션**으로.
    총괄 질문은 의뢰 세션(사람)으로 — 매니저를 깨우지 않는다. 팀장 질문은 **총괄**에게(Issue831 ①), 그 밖의 봇 질문은
    **그 팀장**에게(Issue757) — 받는 관리직을 깨운다."""
    now = int(time.time())
    rid = f"fbotreq-{now}-{uuid.uuid4().hex[:8]}"
    con = _con()
    _st = _state()
    org = _org()
    try:
        r0 = con.execute("SELECT * FROM bot WHERE bot_id=?", (from_bot,)).fetchone()
        lead_to = _question_lead(con, from_bot, (dict(r0) if r0 else {}).get("role"), disp, org)
        if r0 and not org.is_nonexec(r0["role"]) and not lead_to:
            return {"ok": False, "action": "question", "from_bot": from_bot,
                    "error": "질문을 받을 팀장이 없다 — 배분한 팀장·그 prj 팀장·본사 팀장 모두 부재. "
                             "사람 세션으로 직통하지 않는다(Issue757 — 사람의 지시는 총괄·팀장이 받는다)"}
        con.execute("BEGIN IMMEDIATE")
        brow = dict(r0) if r0 else {}
        dpl = (disp or {}).get("payload") or {}
        req = None
        to_session = None
        to_bot = lead_to
        asker_mgr = bool(r0) and org.is_nonexec(r0["role"])
        if not lead_to or asker_mgr:
            # 의뢰 세션 판정 — 관리직 질문만. 팀장 질문(→ 총괄)에는 **원 의뢰 세션**으로 실어 총괄이 되물을 곳을 남긴다(Issue831 ①)
            if dpl.get("requester_session"):
                req = {"session": dpl["requester_session"], "via": "dispatch", "ref": disp["id"], "ambiguous": False}
            if not req:
                req = requester_of(con, from_bot)
        if not lead_to:
            to_session = (req or {}).get("session")
            if to_session:
                r = con.execute("SELECT bot_id FROM bot WHERE session_id=? AND state<>'checkout'"
                                " ORDER BY created_at LIMIT 1", (to_session,)).fetchone()
                to_bot = r[0] if r else None
        task = (dpl.get("issue") or dpl.get("topic") or "") if disp else \
            (brow.get("current_task") or brow.get("last_task") or "")
        payload = {"from": from_bot, "from_session": from_session, "kind": "question",
                   "body": text, "options": options, "prj": dpl.get("prj", brow.get("prj")),
                   "corr_id": disp["id"] if disp else rid, "depth": 0, "from_human": False,
                   "dispatch": disp["id"] if disp else None, "task": task,
                   "to_session": to_session, "to_bot": to_bot, "to_lead": lead_to,
                   "requester_session": (req or {}).get("session"),
                   "requester_via": (req or {}).get("via"), "requester_ref": (req or {}).get("ref"),
                   "requester_ambiguous": bool((req or {}).get("ambiguous"))}
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at) VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (rid, "fbot", KIND, "open", json.dumps(payload, ensure_ascii=False), from_bot, now))
        if disp:
            # WIP 미점유 · sweep 이 워커 종료를 완료로 닫지 않는다(쿼터 종료 blocked 의 payload.quota 선례)
            dpl2 = dict(dpl, blocked_by="question", question_id=rid)
            con.execute("UPDATE job SET status='blocked', blocked_since=?, payload=? WHERE id=?"
                        " AND status IN ('open','blocked','logged')",
                        (now, json.dumps(dpl2, ensure_ascii=False), disp["id"]))
        up = "팀장" if not asker_mgr else "총괄"
        dest = (f"{up} {lead_to}" if lead_to else
                f"의뢰 세션 {to_session[:8]}" if to_session else "공용(의뢰 세션 미상)")
        _st.record_event(con, from_bot, "question", f"→ {dest}: {text[:80]}", rid)
        if lead_to:
            _st.record_event(con, lead_to, "question",
                             f"← {'팀장' if asker_mgr else '팀원'} {from_bot} 질문(답하거나 사람에게 올린다): {text[:60]}", rid)
        elif disp and disp.get("owner") and disp["owner"] != from_bot:
            # 중간 매니저는 기록만 — 사람만 답할 질문으로 `-p` 팀장을 깨우는 비용을 쓰지 않는다
            _st.record_event(con, disp["owner"], "question",
                             f"하위 {from_bot} 질문 → {dest} 중계(기상 없음): {text[:60]}", rid)
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        con.close()
    _st.notify_hub_event(from_bot, "question", rid)
    _qmark_sync()
    out = {"ok": True, "action": "question", "id": rid, "from_bot": from_bot,
           "to": to_bot, "to_session": to_session,
           "route": ("chief" if asker_mgr else "team_lead") if lead_to else ("requester" if to_session else "orphan"),
           "requester_via": payload["requester_via"], "dispatch": disp["id"] if disp else None,
           "corr_id": payload["corr_id"], "options": options}
    if lead_to:
        # 팀장이 답할 질문 — 퇴근한 팀장을 깨운다(인박스 요청과 같은 기상 계약). 사람 대상 음성 알림은 없다
        out["wake"], out["spawn"] = wake_and_spawn(lead_to, reason=f"{'팀장' if asker_mgr else '팀원'} 질문 {rid}", spawn=spawn)   # 질문은 배분 흐름에 딸린다(opens_flow)
    else:
        _say_alert(f"핀봇 질문 대기 — {from_bot}")
    return out


def questions_for(session_id):
    """이 세션이 답할 미종결 질문 — 자기 앞(to_session) + 공용. 넛지 hook 의 조회."""
    con = _con(readonly=True)
    try:
        qs = _open_questions(con)
    finally:
        con.close()
    items = []
    for q in qs:
        pl = q["payload"]
        mine = bool(session_id) and pl.get("to_session") == session_id
        if not (mine or _q_public(pl)):
            continue
        items.append({"id": q["id"], "from": pl.get("from"), "to_session": pl.get("to_session"),
                      "public": not mine, "body": pl.get("body"), "options": pl.get("options") or [],
                      "task": pl.get("task"), "dispatch": pl.get("dispatch"), "prj": pl.get("prj"),
                      "followups": [f.get("text") for f in (pl.get("followups") or []) if isinstance(f, dict)],
                      "created_at": q["created_at"]})
    if not items:
        _qmark_sync()   # 마커는 있는데 질문이 없다 — 낡은 마커 자가 치유
    return {"ok": True, "action": "questions", "session_id": session_id, "count": len(items), "items": items}


def _resume_prompt(task, q, a, status, disp_id, qid=""):
    """재기동 프롬프트 — **한 줄·짧게**. fpm-do send-keys 는 약 1,100바이트에서 조용히 잘린다(Issue416 실측,
    한글 1자 = 3바이트)에 규약 꼬리(~450바이트)가 붙는다. 그래서 답 요지만 싣고 전문은 원장 조회 명령으로 넘긴다."""
    one = lambda t, n: " ".join((t or "").split())[:n]
    ans = f"사람 답: «{one(a, 100)}»" if status == "done" else \
        f"사람이 답하지 않기로 함: «{one(a, 60)}» — 질문 없이 가능한 범위만 하고 보고"
    return (f"[질문 답변 재개 — prj3#Issue749] 원 작업: {one(task, 50) or '(미기록)'}. {ans}. "
            + (f"질문·답 전문: python3 ~/.claude/hooks/fbot-inbox.py qa --id {qid} — " if qid else "")
            + "답을 반영해 원 작업을 이어서 끝낸다.")


def qa(req_id):
    """질문·답 전문 조회 — 재기동된 봇이 짧은 프롬프트 너머의 원문을 읽는 자리."""
    con = _con(readonly=True)
    try:
        r = con.execute("SELECT status, payload, result FROM job WHERE id=? AND kind=?", (req_id, KIND)).fetchone()
    finally:
        con.close()
    if not r:
        return {"ok": False, "error": f"질문 없음: {req_id}"}
    pl, res = _pl(r[1]), (_pl(r[2]) if r[2] else {})
    if pl.get("kind") != "question":
        return {"ok": False, "error": f"질문이 아니다: {req_id} (kind={pl.get('kind')})"}
    return {"ok": True, "action": "qa", "id": req_id, "status": r[0], "from": pl.get("from"),
            "task": pl.get("task"), "dispatch": pl.get("dispatch"), "question": pl.get("body"),
            "options": pl.get("options") or [], "followups": pl.get("followups") or [],
            "answer": res.get("body"), "answer_status": res.get("status"), "answered_by": res.get("by")}


def resume_asker(bot_id, prompt, disp_payload=None):
    """질문한 봇을 답을 들고 다시 띄운다. **새 배분이 아니다** — 월 예산 미차감(resume 선례).
    예외를 올리지 않는다 — 답은 이미 원장에 붙었다. 실패하면 사유와 수동 명령을 돌려준다."""
    import subprocess
    try:
        con = _con()
        try:
            r0 = con.execute("SELECT * FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
        finally:
            con.close()
        if not r0:
            return {"skipped": "no_bot"}
        row = dict(r0)
        dpl = disp_payload or {}
        prj = dpl.get("prj") if dpl.get("prj") is not None else row["prj"]
        if prj is None:
            prj = _org().body_prj()           # 본사 몸체 prj 해소 단일 지점(prj3#Issue945 검토 S1)
        lead = _mod("fbot_lead", "fbot-lead.py")
        cmd = lead._spawn_commands(bot_id, dpl.get("issue") or row.get("current_task") or "", dpl.get("cwd") or "",
                                   prj, mode="resume", prompt=prompt,
                                   model=dpl.get("model_override"))   # prj3#Issue849 — 배분 override 유지
        if cmd.get("run") != "fpm_do":
            return {"skipped": "no_prj", "next_step": cmd}
        # 전 몸체가 창을 비울 때까지 — fpm-do 는 살아 있는 봇 창에 주입을 거부한다(rewake 와 같은 대기)
        wait = REWAKE_WAIT
        if wait > 0 and row.get("tmux_target"):
            end = time.time() + wait
            while time.time() < end and _state().session_presence(row["tmux_target"]) == "present":
                time.sleep(1)
        genv = dict(os.environ, AOA_MEMORY_DIR=os.path.dirname(os.path.abspath(REGISTRY_DB)))
        g = subprocess.run([sys.executable, HR_GATE_PY, "wake", "--bot", bot_id],
                           capture_output=True, text=True, env=genv)
        if g.returncode != 0:
            return {"skipped": "wake_rejected", "error": (g.stderr or g.stdout).strip()[:300],
                    "manual": cmd["fpm_do"]}
        res = _run_spawn(cmd["fpm_do"])
        con = _con()
        try:
            _state().record_event(con, bot_id, "resume", f"질문 답변 재개 prj{prj} · "
                                  f"{'ok' if res.get('ok') else res.get('error', 'fail')}")
        finally:
            con.close()
        return dict(res, prj=prj, cmd=cmd["fpm_do"])
    except Exception as e:
        return {"skipped": "error", "error": f"{type(e).__name__}: {e}"[:300]}


def inbox(bot_id, status="open", limit=20):
    con = _con(readonly=True)
    con.row_factory = sqlite3.Row
    try:
        q = ("SELECT id, status, payload, result, created_at FROM job"
             " WHERE kind=? AND owner=?" + Q_NOT + (" AND status=?" if status else "") +
             " ORDER BY created_at")
        args = [KIND, bot_id] + ([status] if status else [])
        rows = con.execute(q, args).fetchall()
        # prj3#Issue757 — 팀원 질문(owner=묻는 봇, to_lead=이 팀장)도 이 팀장 앞 요청이다
        rows += con.execute(
            "SELECT id, status, payload, result, created_at FROM job WHERE kind=?" + Q_TO_LEAD +
            (" AND status=?" if status else "") + " ORDER BY created_at",
            [KIND, bot_id] + ([status] if status else [])).fetchall()
        rows = sorted(rows, key=lambda r: r["created_at"])[:limit]
    finally:
        con.close()
    out = []
    for r in rows:
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            pl = {}
        out.append({"id": r["id"], "status": r["status"], "from": pl.get("from"),
                    "kind": pl.get("kind"), "body": pl.get("body"),
                    "prj": pl.get("prj"), "corr_id": pl.get("corr_id"),
                    "created_at": r["created_at"],
                    "result": json.loads(r["result"]) if r["result"] else None})
    return {"ok": True, "action": "inbox", "bot_id": bot_id, "count": len(out),
            "items": out}


STAFFING_KIND = "staffing"                     # prj3#Issue757 T13 — 팀장 → 총괄 인력 요청
STAFFING_VERDICTS = ("loan", "created", "none")  # 총괄 응답 3종 — 사다리 감사가 기계로 센다(plan 열린 질문 14)


def staffing(by, role, body, prj=None, spawn=True):
    """인력 요청 — 팀장이 **자리 밖** 직능을 총괄에게 요청한다(인력 확보 사다리 ②, prj3#Issue757 T13).

    사다리 순서를 강제한다: 자리 안(team)이면 팀장이 배분하고, 카탈로그 밖(scout)이면 발굴핀봇에 배분한다 —
    둘 다 총괄에게 올릴 일이 아니다. 총괄은 `reply --verdict loan|created|none` 으로 닫는다.
    봇 세션은 자기 이름으로만 요청한다(prj3#Issue832 — `--by` 사칭 차단, 비봇 세션은 종전 그대로)."""
    err = _ident().bot_caller_error(by, "인력 요청")
    if err:
        return {"ok": False, "error": err}
    org = _org()
    con = _con()
    try:
        r = con.execute("SELECT role, prj FROM bot WHERE bot_id=?", (by,)).fetchone()
        if not r or r["role"] != "lead":
            return {"ok": False, "error": f"인력 요청은 팀장만 한다 — {by} 는 {r['role'] if r else '대장에 없음'}. "
                                          "팀원은 그 팀장에게 말한다"}
        p = prj if prj is not None else r["prj"]
        chief = _chief_bot(con, org)
    finally:
        con.close()
    if not chief:
        return {"ok": False, "error": "총괄 개체가 없다 — 인력 요청을 받을 자가 없다"}
    # prj3#Issue945 — `--prj` 가 요청 팀장의 팀 밖이면 ⓪ cross(그 prj 팀장 인박스). 종전엔 대조 없이 그 prj 자리를 보고
    #   «팀장이 배분한다(dispatch --by <나>)» 로 돌려보냈고, 그 dispatch 는 «차용 필요» 로 다시 거부했다(서로 떠넘김).
    #   판정은 fbot-org `ladder_step(by=…)` → `cross_step` 한 곳 — dispatch 입구·채용 사다리와 같은 사유 문구다
    step = org.ladder_step(p, role, by=by)
    if step["step"] == "cross":
        return {"ok": False, "error": step["reason"], "step": "cross", "lead": step.get("lead"),
                "to": step.get("to"), "next": step.get("next")}
    if step["step"] == "team":
        return {"ok": False, "error": f"prj{p} 조직 선언에 {role} 자리가 있다 — 팀장이 배분한다(공석이면 HR 게이트가 채용): "
                                      f"fbot-lead.py dispatch --by {by} --role {role}"}
    if step["step"] == "scout":
        return {"ok": False, "error": f"{role} 은 카탈로그 밖(또는 아카이브) — 발굴이다: "
                                      f"fbot-lead.py dispatch --by {by} --role scout --topic \"{role} 직능 신설\""}
    cands = [c.get("bot_id") for c in step.get("candidates") or []]
    return send(chief, body, from_bot=by, req_kind=STAFFING_KIND, prj=p, spawn=spawn,
                extra={"role": role, "ladder": step["step"], "candidates": cands, "home": step.get("home")})


def _status_after_reply(status):
    """`reply` 뒤 요청 원장(`job.status`) — 몸체·비몸체 두 행이 같이 쓰는 **단일 판정**(prj3#Issue937).
    `done`·`rejected` 는 결정이 끝난 것이라 닫는다(fbot-manager §응답 — 질문 경로 `_reply_question` 도 rejected 를 `done` 으로
    닫는다). `open` 유지는 `accepted`(ACK 일 뿐) 뿐이다 — 배분 완료 때 sweep `close_fulfilled` 가, 수락 뒤 사람 결정은
    `done|rejected` 응답이 닫는다. 미응답 판정은 status 가 아니라 `result IS NULL`(넛지·pending·escalate)이다."""
    return "open" if status == "accepted" else "done"


def reply(req_id, status, body="", by="", spawn=True, verdict=None, session=None, needs_human=None):
    """응답은 **요청 레코드에 붙인다**(`job.result`). 새 kind 를 만들면 응답이 또
    하나의 요청처럼 보여 인박스가 오염된다 — *"처리할 것"* 과 *"처리된 것"* 이
    구분되지 않는다.

    `kind=question`(prj3#Issue749)이면 답이 곧 재개 신호다 — `done`(답)·`rejected`(답 거절)만 받고,
    같은 트랜잭션에서 배분을 `blocked(question) → open` 으로 되돌린 뒤 **묻던 봇을 답을 들고 재기동**한다."""
    if status not in ("accepted", "rejected", "done"):
        return {"ok": False, "error": f"허용되지 않은 status: {status}"}
    con = _con()
    try:
        row = con.execute("SELECT owner, status, payload FROM job WHERE id=? AND kind=?",
                          (req_id, KIND)).fetchone()
        if not row:
            return {"ok": False, "error": f"요청 없음: {req_id}"}
        qpl = _pl(row["payload"])
        # prj3#Issue832 — 봇 세션은 자기 이름으로, 자기 앞 요청에만 답한다. 비봇(사람) 세션은 종전 그대로
        err = _reply_identity_error(row["owner"], qpl, by)
        if err:
            return {"ok": False, "error": err, "id": req_id}
        by = by or _ident().caller_bot()
        # prj3#Issue757 T13 — 인력 요청은 **무엇으로 답했는지**(차용·생성·없음)를 남겨야 사다리 감사가 된다
        if qpl.get("kind") == STAFFING_KIND:
            if status == "done" and verdict not in STAFFING_VERDICTS:
                return {"ok": False, "error": f"인력 요청은 --verdict {'|'.join(STAFFING_VERDICTS)} 로 닫는다(받은 값: {verdict})"}
            if verdict is not None and verdict not in STAFFING_VERDICTS:
                return {"ok": False, "error": f"허용되지 않은 verdict: {verdict}"}
        elif verdict is not None:
            return {"ok": False, "error": "verdict 는 인력 요청(kind=staffing)에만 쓴다"}
        if qpl.get("kind") == "question":
            if status == "accepted":
                return {"ok": False, "error": "질문은 done(답)·rejected(답 거절)만 받는다 — 사람에게 물은 뒤 답으로 닫는다"}
            if row["status"] != "open":
                return {"ok": False, "error": f"이미 닫힌 질문: {req_id}"}
            return _reply_question(con, req_id, row["owner"], qpl, status, body, by, spawn)
        # prj3#Issue757 T15 ⑤ — 관리직 몸체가 여럿이면 **요청 하나에 몸체 하나**. 판정과 기록을 한 트랜잭션에 둔다
        #   (두 몸체가 동시에 accepted 하면 뒤엣것이 거부돼야 한다). 몸체 아닌 세션·스위치 꺼짐은 종전 그대로
        session = session if session is not None else os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        # prj3#Issue773 — 수락하며 사람 결정을 기다리면 **같은 호출에서** 결정 채널에 올린다. 산문 «사용자 확인 후» 는
        #   hub 도 인박스도 해석하지 않는다(09-27 나래 18건이 open·accepted 로 굳었다). 등록이 실패하면 응답도 남기지 않는다
        nh = None
        if needs_human is not None:
            err = _needs_human_precheck(con, req_id, row, status, body, session)
            if not err:
                nh, err = _raise_to_human(con, req_id, row["owner"], qpl, needs_human, body, spawn)
            if err:
                return {"ok": False, "error": err, "id": req_id}
        res = {"status": status, "body": body, "by": by or row[0], "at": int(time.time())}
        if verdict is not None:
            res["verdict"] = verdict
        if nh:
            res["needs_human"] = nh
        res.update(_state().body_stamp())       # T15 ⑥ — 응답한 몸체(세션·흐름) 동반
        if session:
            res["by_session"] = session
        scope = _body_scope(con, row["owner"], session)
        if scope is not None:
            con.execute("BEGIN IMMEDIATE")
            try:
                cur = con.execute("SELECT result FROM job WHERE id=?", (req_id,)).fetchone()
                prev = _pl(cur["result"]) if cur and cur["result"] else {}
                err = _claim_error(scope, req_id, session, prev)
                if err:
                    con.execute("ROLLBACK")
                    return {"ok": False, "error": err, "id": req_id}
                res["by_session"] = session
                new_status = _status_after_reply(status)
                con.execute("UPDATE job SET result=?, status=? WHERE id=?",
                            (json.dumps(res, ensure_ascii=False), new_status, req_id))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            _st = _state(); _st.record_event(con, row[0], f"reply:{status}", (body or "")[:80], req_id); _st.notify_hub_event(row[0], f"reply:{status}", req_id)
            return {"ok": True, "action": "reply", "id": req_id, "result": res, "job_status": new_status}
        # done·rejected 면 원장도 닫는다 — 미종결로 남으면 인박스에 계속 뜬다(prj3#Issue937)
        new_status = _status_after_reply(status)
        con.execute("UPDATE job SET result=?, status=? WHERE id=?",
                    (json.dumps(res, ensure_ascii=False), new_status, req_id))
        _st = _state(); _st.record_event(con, row[0], f"reply:{status}", (body or "")[:80], req_id); _st.notify_hub_event(row[0], f"reply:{status}", req_id)   # prj3#Issue575
        return {"ok": True, "action": "reply", "id": req_id, "result": res,
                "job_status": new_status}
    finally:
        con.close()


def _reply_identity_error(owner, qpl, by):
    """봇 세션의 응답 자격 — 거부 사유 또는 None (prj3#Issue832).
    ① 사칭 금지(`FBOT_ID == --by`, 생략하면 FBOT_ID) ② 자기 앞 요청만 — 요청은 `owner`, 질문(owner=묻는 봇)은
    받는 관리직(`to_lead`·`to_bot`). 비봇 세션(FBOT_ID 없음)은 None — 사람이 hub·세션에서 답하는 경로는 종전 그대로."""
    ident = _ident()
    fid = ident.caller_bot()
    if not fid:
        return None
    me = by or fid
    err = ident.impersonation_error(me, "응답")
    if err:
        return err
    if qpl.get("kind") == "question":
        allowed = {qpl.get("to_lead"), qpl.get("to_bot")} - {None, ""}
        if me not in allowed:
            return (f"이 질문은 {'·'.join(sorted(allowed)) or '사람 세션'} 이 답한다 — {me} 앞 질문이 아니다"
                    "(봇은 자기 앞 질문에만 답한다)")
    elif me != owner:
        return f"{owner} 앞 요청이다 — 봇({me})은 자기 인박스 요청에만 응답한다(남의 요청 대신 닫기 금지)"
    return None


def _claim_error(scope, req_id, session, prev):
    """몸체 claim 판정(prj3#Issue757 T15 ⑤) — 거부 사유 또는 None. reply 트랜잭션과 상신 사전 판정(Issue773)이 같이 쓴다."""
    owner_flow = next((b for b in scope if b["flow"] == req_id and b["session_id"] != session), None)
    claimer = prev.get("by_session")
    if owner_flow:
        return f"이 요청은 다른 몸체({(owner_flow['session_id'] or '')[:8]})의 흐름이다 — 그 몸체가 처리한다"
    if claimer and claimer != session and any(b["session_id"] == claimer for b in scope):
        return f"다른 몸체({claimer[:8]})가 이미 집은 요청이다 — 요청 하나에 몸체 하나(prj3#Issue757 T15)"
    return None


# ── 사람 결정 대기 (prj3#Issue773) ──────────────────────────────────────────────
# 수락(accepted)은 ACK 일 뿐이다. 사람 결정을 기다리는 수락은 결정 채널에 올라가야 사람에게 보인다 —
#   총괄: mq `[컨펌] [H:분류]`(source=<bot_id>@… — hub «사람 결정 대기» 가 이 형식으로 매칭, prj1#Issue570)
#   팀장·그 밖: 총괄 인박스 `decision` — 봇의 H 는 총괄이 상신한다(decision-authority «봇은 총괄이»)
DECISION_POLICY = os.environ.get("AOA_DECISION_POLICY") or os.path.join(
    os.path.expanduser("~"), ".claude", "data", "decision-authority.yml")


def _h_categories():
    """H 분류 목록 — helper(aoa-mq-enqueue.sh) 게이트와 **같은 정책 파일**을 읽는다. 없으면 빈 목록(= 전부 거부)."""
    try:
        for line in open(DECISION_POLICY, encoding="utf-8"):
            if line.startswith("h_categories:"):
                return [c.strip() for c in line.split(":", 1)[1].split(",") if c.strip()]
    except OSError:
        pass
    return []


def _needs_human_precheck(con, req_id, row, status, body, session):
    """상신 전 판정 — 거부 사유 또는 None. 부작용(mq·인박스 적재) 전에 끝낸다."""
    if status != "accepted":
        return "--needs-human 은 accepted 와 함께 쓴다 — 수락하며 사람 결정을 기다릴 때다(done·rejected 는 결정이 끝난 것)"
    if not (body or "").strip():
        return "--needs-human 에는 --body 로 사람이 정할 것을 적는다 — 결정 항목의 본문이 된다"
    if row["status"] != "open":
        return f"이미 닫힌 요청: {req_id}"
    cur = con.execute("SELECT result FROM job WHERE id=?", (req_id,)).fetchone()
    prev = _pl(cur[0]) if cur and cur[0] else {}
    if prev.get("needs_human"):
        return f"이미 사람 결정 대기 중인 요청이다: {json.dumps(prev['needs_human'], ensure_ascii=False)}"
    scope = _body_scope(con, row["owner"], session)
    return _claim_error(scope, req_id, session, prev) if scope is not None else None


def _raise_to_human(con, req_id, owner, qpl, category, body, spawn):
    """결정 채널에 올린다 → (needs_human 기록, 오류). 오류면 호출자가 응답을 기록하지 않는다."""
    cat = (category or "").strip()
    cats = _h_categories()
    if cat not in cats:
        return None, (f"H 분류가 아니다: '{cat}' (H: {','.join(cats) or '정책 없음'}) — C·L 이면 묻지 말고 결정·진행한다"
                      f"(fbot-state.py decide). 권한표 ~/.claude/_doc_arch/decision-authority.md")
    r = con.execute("SELECT role FROM bot WHERE bot_id=?", (owner,)).fetchone()
    prj = qpl.get("prj")
    now = int(time.time())
    if r is not None and r[0] == CHIEF_ROLE:
        msg = (f"[컨펌] [H:{cat}] {_clip(body, 400)} — {owner} 가 인박스 요청 {req_id} 를 수락하고 사람 결정을 기다린다. "
               f"결정 뒤 총괄이 `fbot-inbox.py reply --id {req_id} --status done|rejected` 로 닫는다")
        try:
            mid = _mq_confirm(msg, owner)
        except RuntimeError as e:
            return None, f"mq [컨펌] 등록 실패 — 응답을 기록하지 않았다: {e}"
        return {"grade": "H", "category": cat, "mq": mid, "at": now}, None
    chief = _chief_bot(con)
    if not chief:
        return None, "총괄 개체가 없다 — 봇의 H 는 총괄이 상신한다(decision-authority). 응답을 기록하지 않았다"
    out = send(chief, f"[H:{cat}] 사람 결정 필요 — {owner} 가 수락한 요청 {req_id}: {_clip(body, 600)}",
               from_bot=owner, from_session="", req_kind="decision", prj=prj, corr_id=req_id,
               spawn=spawn, from_human=False)
    if not out.get("ok"):
        return None, f"총괄 상신 실패 — 응답을 기록하지 않았다: {out.get('error')}"
    return {"grade": "H", "category": cat, "via": out["id"], "to": chief, "at": now}, None


# ── 요청 종결 — 배분이 끝나면 그 배분이 처리한 요청도 (prj3#Issue773 ③) ─────────────
# `accepted` 는 ACK 일 뿐 종결이 아니다. 매니저가 요청을 배분으로 처리하면 `dispatch --request <R>` 가 배분에
#   `payload.request_id` 를 싣고, sweep 이 배분을 닫을 때 이 함수가 R 을 닫는다. 판정은 여기 한 곳.

def request_link_error(con, req_id, by):
    """배분 ↔ 요청 연결 검사 — 통과면 None, 아니면 사유. 자기 앞 열린 요청만 · 질문은 배분으로 닫지 않는다."""
    r = con.execute("SELECT owner, status, payload FROM job WHERE id=? AND kind=?", (req_id, KIND)).fetchone()
    if not r:
        return f"--request {req_id}: 인박스 요청이 아니다(원장에 없음)"
    if r[0] != by:
        return f"--request {req_id}: {r[0]} 앞 요청이다 — 자기 인박스 요청만 배분에 잇는다"
    if r[1] != "open":
        return f"--request {req_id}: 이미 닫힌 요청이다"
    if _pl(r[2]).get("kind") == "question":
        return f"--request {req_id}: 질문은 배분으로 닫지 않는다 — reply 로 답한다"
    return None


def close_fulfilled(dispatch_ids, by="sweep"):
    """닫힌 배분들 → 연결된 요청 종결. R 에 걸린 배분이 하나라도 살아 있거나 `done` 이 하나도 없으면(전부 취소) 둔다.
    반환 {"closed": [...], "kept": [...]} — 이미 닫힌 요청은 어느 쪽에도 넣지 않는다(멱등).
    `by` — 배분을 닫은 경로(sweep·close·cancel). 배분 종결 경로마다 부른다 — sweep 만 부르면 수동 `close` 로
    끝난 요청이 accepted 로 굳는다(prj3#Issue816 실측 `fbotreq-1790627807-31b16ac3`)."""
    out = {"closed": [], "kept": []}
    ids = [d for d in (dispatch_ids or []) if d]
    if not ids:
        return out
    con = _con()
    try:
        reqs = []
        for d in ids:
            r = con.execute("SELECT json_extract(payload,'$.request_id') FROM job WHERE id=? AND kind='fbot_dispatch'",
                            (d,)).fetchone()
            if r and r[0] and r[0] not in reqs:
                reqs.append(r[0])
        for rid in reqs:
            con.execute("BEGIN IMMEDIATE")
            try:
                q = con.execute("SELECT owner, status, result FROM job WHERE id=? AND kind=?", (rid, KIND)).fetchone()
                links = con.execute("SELECT id, status FROM job WHERE kind='fbot_dispatch'"
                                    " AND json_extract(payload,'$.request_id')=? ORDER BY created_at, id",
                                    (rid,)).fetchall()
                if not q or q["status"] != "open":
                    con.execute("ROLLBACK")
                    continue
                if any(l["status"] in DISPATCH_ACTIVE for l in links) or not any(l["status"] == "done" for l in links):
                    con.execute("ROLLBACK")
                    out["kept"].append(rid)
                    continue
                prev = _pl(q["result"]) if q["result"] else {}
                res = {"status": "done", "body": f"배분 {len(links)}건 완료로 종결", "by": by,
                       "closed_by": by, "dispatches": [l["id"] for l in links], "at": int(time.time())}
                for k in ("body", "by", "at"):
                    if prev.get(k) is not None:
                        res["accepted_" + k] = prev[k]
                if prev.get("needs_human"):
                    res["needs_human"] = prev["needs_human"]
                con.execute("UPDATE job SET result=?, status='done' WHERE id=?",
                            (json.dumps(res, ensure_ascii=False), rid))
                _state().record_event(con, q["owner"], "reply:done", res["body"], rid)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            out["closed"].append(rid)
            _state().notify_hub_event(q["owner"], "reply:done", rid)
        # prj3#Issue929 — sweep 이 올린 «완료 미확인» 통지(kind=unconfirmed · corr_id=배분 id)는 그 배분이 종결되면 닫는다.
        #   매니저가 `close`·`cancel` 로 정리했거나 뒤늦은 증적으로 sweep 이 닫았는데 통지가 열려 있으면 넛지·30분 escalate(mq)가
        #   처리된 일을 계속 울린다. 배분이 아직 미종결(blocked 등)이면 둔다. kind 는 fbot-state `UNCONFIRMED`(어휘 정본)
        unconf_kind = None
        for d in ids:
            st = con.execute("SELECT status FROM job WHERE id=? AND kind='fbot_dispatch'", (d,)).fetchone()
            if not st or st[0] in UNCONF_OPEN_STATES:
                continue
            now = int(time.time())
            unconf_kind = unconf_kind or _state().UNCONFIRMED
            con.execute("BEGIN IMMEDIATE")
            try:
                rows = con.execute("SELECT id, owner FROM job WHERE kind=? AND status='open'"
                                   " AND json_extract(payload,'$.kind')=? AND json_extract(payload,'$.corr_id')=?",
                                   (KIND, unconf_kind, d)).fetchall()
                done_ids = []
                for r in rows:
                    res = {"status": "done", "body": f"배분 {d} 종결({st[0]})로 통지 종결", "by": by,
                           "closed_by": by, "dispatches": [d], "at": now}
                    cur = con.execute("UPDATE job SET result=?, status='done' WHERE id=? AND status='open'",
                                      (json.dumps(res, ensure_ascii=False), r["id"]))
                    if cur.rowcount == 1:
                        _state().record_event(con, r["owner"], "reply:done", res["body"], r["id"])
                        done_ids.append((r["owner"], r["id"]))
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            for owner, rid in done_ids:
                out["closed"].append(rid)
                _state().notify_hub_event(owner, "reply:done", rid)
    finally:
        con.close()
    return out


def _reply_question(con, req_id, asker, qpl, status, body, by, spawn):
    """질문 닫기 + 배분 재개(한 트랜잭션) → 커밋 뒤 마커 정리·재기동. `con` 은 호출자가 닫는다."""
    now = int(time.time())
    res = {"status": status, "body": body, "by": by or os.environ.get("CLAUDE_CODE_SESSION_ID") or "?", "at": now}
    _st = _state()
    dpl = None
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("UPDATE job SET result=?, status='done' WHERE id=? AND status='open'",
                    (json.dumps(res, ensure_ascii=False), req_id))
        did = qpl.get("dispatch")
        if did:
            d = con.execute("SELECT status, payload FROM job WHERE id=? AND kind='fbot_dispatch'", (did,)).fetchone()
            dp = _pl(d["payload"]) if d else {}
            if d and d["status"] == "blocked" and dp.get("blocked_by") == "question" and dp.get("question_id") == req_id:
                dp.pop("blocked_by", None)
                dp.pop("question_id", None)
                qa = dp.get("qa") if isinstance(dp.get("qa"), list) else []
                qa.append({"qid": req_id, "q": (qpl.get("body") or "")[:500], "a": body,
                           "status": status, "by": res["by"], "at": now})
                dp["qa"] = qa[-10:]
                # 질문 전 몸체가 잡은 스폰 잠금 — 몸체는 이미 끝났다. 두면 재기동이 rc 3 으로 막힌다
                if dp.get("spawned_by"):
                    _st._clear_claim(dp, res["by"], "question-answered", now)
                con.execute("UPDATE job SET status='open', blocked_since=NULL, payload=? WHERE id=?",
                            (json.dumps(dp, ensure_ascii=False), did))
                dpl = dp
        _st.record_event(con, asker, f"reply:{status}", f"질문 답: {(body or '')[:80]}", req_id)
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    _st.notify_hub_event(asker, f"reply:{status}", req_id)
    _qmark_sync()
    out = {"ok": True, "action": "reply", "id": req_id, "result": res, "job_status": "done",
           "kind": "question", "dispatch": qpl.get("dispatch"), "dispatch_status": "open" if dpl else None}
    prompt = _resume_prompt(qpl.get("task") or "", qpl.get("body") or "", body, status, qpl.get("dispatch"), req_id)
    if spawn:
        out["resume"] = resume_asker(asker, prompt, dpl if dpl is not None else {"prj": qpl.get("prj")})
    else:
        out["resume"] = {"skipped": "no_spawn", "prompt": prompt}
    return out


def pending(bot_id=None, session_id=None, limit=10, viewer=None):
    """소비 3경로(출근·tick·결속 중)의 **공용 조회**. *"이 매니저(들) 앞에 아직 안 본 요청"*.

    `open` 만 센다 — 매니저가 `reply --status accepted` 로 받으면 그 순간 넛지가 그친다.
    이 전이가 곧 ACK 라 별도 읽음 표시가 필요 없다. `dispatch --request` 로 살아 있는 배분에 연결된
    요청도 ACK 없이 빠지고 `dispatching`(«배분 중 <배분 id>»)에 실린다(prj3#Issue816).

    ⚠️ `--session-id` 는 마커 파일 내용을 쓰지 않는다(Issue449 — 마지막 1건만 담겨
    권위가 아니다). *누가 이 세션에 있는가* 는 DB 가 답한다. 한 세션에 매니저가 둘이면
    둘 다 돌려준다."""
    con = _con(readonly=True)
    con.row_factory = sqlite3.Row
    try:
        if session_id:
            bots = [r for r in con.execute(
                "SELECT bot_id, role FROM bot WHERE session_id=? AND state<>'checkout'",
                (session_id,)).fetchall()]
            # prj3#Issue757 T15 ⑤ — bot.session_id 는 최근 몸체뿐이다. 이전 몸체 세션은 몸체 원장으로 찾는다
            if _state().multibody_enabled():
                seen = {b["bot_id"] for b in bots}
                for _bid, owner in _state().session_bodies(con, session_id):
                    if owner not in seen:
                        r = con.execute("SELECT bot_id, role FROM bot WHERE bot_id=? AND state<>'checkout'",
                                        (owner,)).fetchone()
                        if r:
                            bots.append(r); seen.add(owner)
        elif bot_id:
            r = _bot(con, bot_id)
            bots = [r] if r else []
        else:
            return {"ok": False, "error": "--bot-id 또는 --session-id 필요"}
        org = _org()
        mgrs = [b["bot_id"] for b in bots if org.is_manager(b["role"])]
        items = []
        dispatching = []
        for m in mgrs:
            rows = con.execute(
                "SELECT id, payload, created_at FROM job WHERE kind=? AND owner=?"
                " AND status='open' AND result IS NULL" + Q_NOT + Q_NOT_DISPATCHING + " ORDER BY created_at",
                (KIND, m)).fetchall()
            # prj3#Issue816 — 넛지에서 뺀 «배분 중» 요청은 따로 드러낸다(무엇에 걸려 있는지). ACK 여부 무관
            dispatching += [{"id": x[0], "to": m, "dispatch": x[1]} for x in con.execute(
                "SELECT job.id, d.id, MAX(d.created_at) FROM job JOIN job d ON d.kind='fbot_dispatch'"
                " AND d.status IN (%s) AND json_extract(d.payload,'$.request_id')=job.id"
                " WHERE job.kind=? AND job.owner=? AND job.status='open' GROUP BY job.id ORDER BY job.created_at"
                % ",".join("?" * len(DISPATCH_ACTIVE)), (*DISPATCH_ACTIVE, KIND, m)).fetchall()]
            rows += con.execute(      # prj3#Issue757 — 팀원 질문
                "SELECT id, payload, created_at FROM job WHERE kind=?" + Q_TO_LEAD +
                " AND status='open' AND result IS NULL ORDER BY created_at", (KIND, m)).fetchall()
            rows = sorted(rows, key=lambda r: r["created_at"])
            # prj3#Issue757 T15 ⑤ — 다른 살아 있는 몸체의 흐름 요청(그 요청 때문에 뜬 몸체)은 이 몸체에 보이지 않는다
            viewer_sid = viewer or session_id    # 조회자 — 출근 훅은 --bot-id 로 부르므로 세션은 env 로 온다
            scope = _body_scope(con, m, viewer_sid)
            if scope is not None:
                theirs = {b["flow"] for b in scope if b["session_id"] != viewer_sid}
                rows = [r for r in rows if r["id"] not in theirs]
            rows = rows[:limit]
            for r in rows:
                try:
                    pl = json.loads(r["payload"] or "{}")
                except ValueError:
                    pl = {}
                items.append({"id": r["id"], "to": m, "from": pl.get("from"),
                              "from_session": pl.get("from_session"),
                              "kind": pl.get("kind"), "body": pl.get("body"),
                              "prj": pl.get("prj"), "created_at": r["created_at"]})
    finally:
        con.close()
    return {"ok": True, "action": "pending", "managers": mgrs, "count": len(items),
            "items": items, "dispatching": dispatching}


def escalate(older_than_min=30, apply=False):
    """tick 경로 — **임계 초과 미처리 요청**을 aoa-mq alert 로 올린다(1건당 1회).

    매니저가 출근하지 않으면 인박스는 영원히 안 읽힌다. 그 침묵을 사람에게 알리는
    것이 이 함수의 전부다 — 여기서 요청을 대신 처리하지 않는다(호출 경계 §F3).
    재알림 방지는 `payload.escalated_at` 으로 한다 — 큐 파일을 뒤지지 않는다.

    질문(`kind=question`, prj3#Issue749)은 mq 로 가지 않는다(사용자 지시 2026-09-28). 대신 **공용으로
    확대**한다 — `widened_at` + `q-any` 마커로 어느 사람 세션이든 다음 턴에 본다. 의뢰 세션이 닫혔거나
    사람이 다른 창에 있어도 답이 닿는다."""
    now = int(time.time())
    cut = now - older_than_min * 60
    con = _con()
    widened = []
    try:
        rows = con.execute(
            "SELECT id, owner, payload, created_at FROM job WHERE kind=? AND status='open'"
            " AND result IS NULL AND created_at<=?" + Q_NOT_DISPATCHING + " ORDER BY created_at", (KIND, cut)).fetchall()
        due = []
        for r in rows:
            try:
                pl = json.loads(r["payload"] or "{}")
            except ValueError:
                pl = {}
            if pl.get("kind") == "question":
                if not pl.get("widened_at") and pl.get("to_session"):
                    widened.append((r["id"], r["owner"], pl))
                continue
            if pl.get("escalated_at"):
                continue
            due.append((r["id"], r["owner"], pl, r["created_at"]))
        if widened and apply:
            _stw = _state()
            for rid, owner, pl in widened:
                pl["widened_at"] = now
                con.execute("UPDATE job SET payload=? WHERE id=?", (json.dumps(pl, ensure_ascii=False), rid))
                _stw.record_event(con, owner, "question", f"미응답 {older_than_min}분 초과 → 공용 확대(모든 사람 세션)", rid)
        alerted = []
        if due and apply:
            # 묶음 1회 (Issue399 규약: 통지 1회·묶음)
            lines = [f"[핀봇 인박스] 매니저 미응답 요청 {len(due)}건 (>{older_than_min}분)"]
            for rid, owner, pl, ts in due:
                age = (now - int(ts or now)) // 60
                lines.append(f"- {owner} ← {pl.get('from') or pl.get('from_session') or '?'}"
                             f" ({age}분): {(pl.get('body') or '')[:60]}  id={rid}")
            _mq_alert("\n".join(lines))
            _st = _state()
            for rid, owner, pl, ts in due:
                pl["escalated_at"] = now
                con.execute("UPDATE job SET payload=? WHERE id=?",
                            (json.dumps(pl, ensure_ascii=False), rid))
                _st.record_event(con, owner, "escalate", f"미응답 {older_than_min}분 초과 → mq alert", rid)   # prj3#Issue575
                alerted.append(rid)
    finally:
        con.close()
    if widened and apply:
        _qmark_sync()
    return {"ok": True, "action": "escalate", "due": [d[0] for d in due],
            "alerted": alerted, "applied": apply, "widened": [w[0] for w in widened]}


# 주입구 FBOT_MQ_ENQUEUE_SH 는 **테스트 전용** — 스모크가 실큐를 건드리지 않게 스텁을 꽂는다
MQ_ENQUEUE_SH = os.environ.get("FBOT_MQ_ENQUEUE_SH") or os.path.join(
    os.path.expanduser("~"), ".claude", "mcp", "aoa-mq", "aoa-mq-enqueue.sh")
# 거처 prj 판정 lib(prj3#Issue925) — enqueue 스텁과 따로 둔다: 스텁 디렉토리엔 lib 이 없다
MQ_LIB_SH = os.environ.get("FBOT_MQ_LIB_SH") or os.path.join(
    os.path.expanduser("~"), ".claude", "mcp", "aoa-mq", "aoa-mq-lib.sh")


def _mq_alert(message, from_bot="fbot-lead"):
    """fbot-lead.py 의 발신구와 같은 helper 를 **호출만** 한다 — 큐 파일 직접 Write 금지."""
    import subprocess
    if not os.path.exists(MQ_ENQUEUE_SH):
        raise RuntimeError(f"aoa-mq enqueue helper 없음: {MQ_ENQUEUE_SH}")
    p = subprocess.run([MQ_ENQUEUE_SH, "--message", message, "--alert",
                        "--source", from_bot, "--from-bot", from_bot],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"에스컬레이션 enqueue 실패(exit {p.returncode}): "
                           f"{(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def _home_prj():
    """상신하는 봇 몸체의 거처 prj(`prjN`) — 해소 실패면 None + stderr 경고 (prj3#Issue925).

    판정은 **넛지 쪽과 같은 함수** aoa-mq-lib `aoa_mq_project_of_cwd`(최장 접두)다 — session-inbox 가 «내 prj»
    를 그것으로 정하므로, 다른 판정(`fbot-lead.resolve_prj` 는 숫자 이름만·realpath)을 쓰면 `42a` 같은 거처에서
    target 과 세션 prj 가 갈린다. lib 은 realpath 없이 비교하므로 논리 경로(`PWD`)를 우선 넘긴다.
    판정 수단이 깨져도(lib 부재·bash 실패) 상신은 막지 않는다 — 결정 채널이 닫히는 피해가 더 크다."""
    import subprocess
    cwd = os.getcwd()
    pwd = os.environ.get("PWD")
    try:
        if pwd and os.path.samefile(pwd, cwd):
            cwd = pwd
    except OSError:
        pass
    prj, why = "", ""
    try:
        p = subprocess.run(["bash", "-c", '. "$1" && aoa_mq_project_of_cwd "$2" && printf "%s" "$MQ_C_PRJ"',
                            "_", MQ_LIB_SH, cwd], capture_output=True, text=True, timeout=10)
        prj = (p.stdout or "").strip() if p.returncode == 0 else ""
        why = "" if p.returncode == 0 else f"lib rc={p.returncode} {(p.stderr or '').strip()[-120:]}"
    except (OSError, subprocess.SubprocessError) as e:
        why = f"{type(e).__name__}: {e}"
    if not prj:
        print(f"[fbot-inbox] ⚠️ 거처 prj 해소 실패(cwd={cwd}{' · ' + why if why else ''}) — mq [컨펌] 을 --target 없이"
              " 올린다(판정이 message·source 로 폴백 — 본문 첫 prjN 으로 갈 수 있다)", file=sys.stderr)
        return None
    return prj


def _mq_confirm(message, bot):
    """봇 명의 mq `[컨펌]` 등록 (prj3#Issue773) — helper **호출만**(큐 직접 Write 금지). 반환 mq id.
    `source=<bot_id>@<cwd 이름>` — hub «사람 결정 대기»(prj1#Issue570)가 `@` 앞 전체 일치로 그 봇 카드에 싣는다.
    helper 의 `[H:분류]` 게이트(exit 5)가 등급 판정 단일 지점이다.

    `--target` = **상신하는 봇 자신의 거처 prj**(prj3#Issue925). target 은 «이 항목을 수행할 prj»(Issue770 —
    넛지 범위·launch cwd 1순위)이고 결정 뒤 처리자는 상신한 봇이다(`fbot-inbox.py reply` 로 닫는다). 종전엔
    인박스 요청의 prj(관련 prj)를 넘겨 넛지가 그 prj 세션에만 갔고, 총괄은 «다른 prj 몫» 으로 넘겨 [진행] 뒤
    아무도 집지 않았다(실례 `20261004-183430-001` 외 3건). 요청 prj 는 메시지 본문이 이미 싣는다."""
    import subprocess
    if not os.path.exists(MQ_ENQUEUE_SH):
        raise RuntimeError(f"aoa-mq enqueue helper 없음: {MQ_ENQUEUE_SH}")
    cmd = [MQ_ENQUEUE_SH, "--message", message, "--due", "+0d",
           "--source", f"{bot}@{os.path.basename(os.getcwd()) or 'fbot'}", "--from-bot", bot, "--json"]
    home = _home_prj()
    if home is not None:
        cmd += ["--target", home]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        why = "H 등급 게이트 거부" if p.returncode == 5 else f"exit {p.returncode}"
        raise RuntimeError(f"{why}: {(p.stderr or p.stdout).strip()[-300:]}")
    # 출력 계약 = `--json` 1줄(prj3#Issue811) — id 는 helper 가 채번값 그대로 준다. 종전 산문 «enqueued: <경로>» 를
    #   정규식·splitext 로 자르던 경로는 cwd 이름의 `.`(`.claude`)에 걸리는 함정이라 쓰지 않는다
    try:
        info = json.loads((p.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        raise RuntimeError(f"helper --json 출력 파싱 실패({e}): {(p.stdout or '').strip()[-200:]}")
    mid = info.get("id") if isinstance(info, dict) else None
    if not mid:
        raise RuntimeError(f"helper --json 출력에 id 가 없다: {(p.stdout or '').strip()[-200:]}")
    return str(mid)


def main(argv=None):
    ap = argparse.ArgumentParser(description="매니저 명령 인박스 (Issue552)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("send", help="매니저에게 요청 적재")
    s1.add_argument("--to", required=True)
    s1.add_argument("--body", required=True)
    s1.add_argument("--from-bot", default=os.environ.get("FBOT_ID", ""))   # prj3#Issue757 — 봇 몸체가 생략해도 발신자가 선다(defer 와 같은 기본값)
    s1.add_argument("--from-session", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    s1.add_argument("--kind", default="ask", help="요청 종류(ask·staffing·role·defer …)")
    s1.add_argument("--prj", type=int, default=None)
    s1.add_argument("--corr-id", default=None)
    s1.add_argument("--no-spawn", action="store_true", help="적재만 — 퇴근 매니저 자동 기상 생략 (Issue734)")
    s7 = sub.add_parser("defer", help="응답 대기 봇의 응답을 배분 체인 위로 — 기원 요청 발신자·배분자 → 부모 매니저 → 총괄 (Issue736·791)")
    s7.add_argument("--from-bot", default=os.environ.get("FBOT_ID", ""))
    s7.add_argument("--from-session", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    s7.add_argument("--body", default="", help="위임할 응답 본문 — 없으면 --transcript 의 마지막 assistant 텍스트")
    s7.add_argument("--transcript", default="", help="세션 JSONL 경로(hook 의 transcript_path)")
    s7.add_argument("--no-spawn", action="store_true", help="적재만 — 수신 매니저 자동 기상 생략")
    # choices 를 두지 않는다 — 허용 어휘는 fbot-state `REPORT_STATUSES` 정본이고 `defer` 가 검증한다(파서 생성마다 fbot-state 를
    #   실행하지 않게 · 사본을 두지 않게 — prj3#Issue929 검토 ⑥)
    s7.add_argument("--status", default=None,
                    help="받은 배분의 결과를 명시 — done(산출 완료)·incomplete(못 끝냄). sweep 이 topic 배분 완료 증적으로 "
                         "읽는다. 마지막 명시 status 가 done 이 아니면 «완료 미확인» (prj3#Issue929)")
    s7.add_argument("--note", default="",
                    help="본문 앞에 붙일 표지 — Stop 가드의 «미완 백그라운드 퇴근» 알림 등 (prj3#Issue951)")
    s8 = sub.add_parser("rewake", help="퇴근 재기상 — 출근 후 도착 미응답이 남으면 다시 깨운다 (퇴근 훅, Issue748)")
    s8.add_argument("--bot-id", required=True)
    s8.add_argument("--wait", type=int, default=None, help="전 몸체 창이 빌 때까지 대기 상한(초)")
    s6 = sub.add_parser("wake-pending", help="미응답 요청이 있는 퇴근 매니저 일괄 기상 (tick 안전망, Issue734)")
    s6.add_argument("--apply", action="store_true")
    s2 = sub.add_parser("inbox", help="인박스 조회")
    s2.add_argument("--bot-id", required=True)
    s2.add_argument("--status", default="open", help="빈 문자열이면 전체")
    s3 = sub.add_parser("reply", help="요청에 응답")
    s3.add_argument("--id", required=True)
    s3.add_argument("--status", required=True, help="accepted|rejected|done")
    s3.add_argument("--body", default="")
    s3.add_argument("--by", default=os.environ.get("FBOT_ID", ""))
    s3.add_argument("--no-spawn", action="store_true", help="질문 답이어도 묻던 봇 재기동 생략(적재·재개 판정만, Issue749)")
    s3.add_argument("--verdict", default=None, help="인력 요청 응답 loan|created|none (prj3#Issue757 T13)")
    s3.add_argument("--needs-human", default=None, metavar="H분류",
                    help="accepted 와 함께 — 사람 결정 대기를 같은 호출로 상신(총괄: mq [컨펌] [H:분류] · 팀장: 총괄 인박스). "
                         "등록 실패면 응답 미기록 (prj3#Issue773)")
    s3.add_argument("--session-id", default=None,
                    help="응답하는 몸체 세션(기본 env CLAUDE_CODE_SESSION_ID) — 관리직 다중 몸체 claim (prj3#Issue757 T15 ⑤)")
    sst = sub.add_parser("staffing", help="팀장 → 총괄 인력 요청 — 자리 밖 직능 (prj3#Issue757 T13)")
    sst.add_argument("--by", default=os.environ.get("FBOT_ID", ""))
    sst.add_argument("--role", required=True)
    sst.add_argument("--body", required=True)
    sst.add_argument("--prj", type=int, default=None)
    sst.add_argument("--no-spawn", action="store_true")
    s10 = sub.add_parser("qa", help="질문·답 전문 — 재기동된 봇이 읽는다 (Issue749)")
    s10.add_argument("--id", required=True)
    s9 = sub.add_parser("questions", help="이 세션이 답할 핀봇 질문 — 자기 앞 + 공용 (Issue749)")
    s9.add_argument("--session-id", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    s4 = sub.add_parser("pending", aliases=["list"],
                        help="미처리(open) 요청 — 매니저 1명 또는 세션의 매니저 전원 (별칭 list)")
    s4.add_argument("--bot-id", "--to", "--for", dest="bot_id", default=None)   # 별칭 3종 — 세션이 추측한 형태를 전부 받는다
    s4.add_argument("--session-id", default=None)
    s4.add_argument("--viewer-session", default=os.environ.get("CLAUDE_CODE_SESSION_ID") or None,
                    help="조회자 세션(기본 env) — 관리직 몸체면 다른 몸체의 흐름 요청을 숨긴다 (prj3#Issue757 T15 ⑤)")
    s5 = sub.add_parser("escalate", help="임계 초과 미처리 요청을 aoa-mq alert (tick 경로)")
    s5.add_argument("--older-than-min", type=int,
                    default=int(os.environ.get("FBOT_INBOX_ESCALATE_MIN") or 30))
    s5.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "send":
        out = send(a.to, a.body, a.from_bot, a.from_session, a.kind, a.prj, a.corr_id, spawn=not a.no_spawn)
    elif a.cmd == "defer":
        out = defer(a.from_bot, a.from_session, a.body, a.transcript, spawn=not a.no_spawn, status=a.status, note=a.note)
    elif a.cmd == "wake-pending":
        out = wake_pending(a.apply)
    elif a.cmd == "rewake":
        out = rewake(a.bot_id, a.wait)
    elif a.cmd == "inbox":
        out = inbox(a.bot_id, a.status)
    elif a.cmd in ("pending", "list"):
        out = pending(a.bot_id, a.session_id, viewer=a.viewer_session)
    elif a.cmd == "escalate":
        out = escalate(a.older_than_min, a.apply)
    elif a.cmd == "questions":
        out = questions_for(a.session_id)
    elif a.cmd == "qa":
        out = qa(a.id)
    elif a.cmd == "staffing":
        out = staffing(a.by, a.role, a.body, a.prj, spawn=not a.no_spawn)
    else:
        out = reply(a.id, a.status, a.body, a.by, spawn=not a.no_spawn, verdict=a.verdict, session=a.session_id,
                    needs_human=a.needs_human)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
