#!/usr/bin/env python3
# test_fbot_bots.py — prj3#Issue438 ③ 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 핀봇 현황 수집기
#   (_collect_bots / _fbot_icon_data_uri)와 spa_widgets badge icon 스킴 가드를 검증한다.
#
# 왜 이 테스트가 필요한가 — 이 경로는 **타 프로젝트(prj3) 데이터에 의존**한다. fbot 미설치
#   환경(레지스트리 DB 자체가 없음)에서 hub 홈이 깨지면 안 되고, DB 값이 오염돼도 아이콘
#   디렉터리 밖 파일을 읽어선 안 된다. 둘 다 조용히 실패하는 종류라 회귀로 박제한다.
#
# 실행: python3 services/hub/test_fbot_bots.py
"""핀봇 현황 payload 수집기 단위 테스트."""
import base64
import os
import re
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402
import spa_widgets  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


SCHEMA = """CREATE TABLE bot(
  bot_id TEXT PRIMARY KEY, title TEXT, role TEXT NOT NULL, state TEXT NOT NULL,
  career TEXT NOT NULL, icon TEXT, color TEXT, prj INT, current_task TEXT,
  parent_bot_id TEXT, lease_expires INT, created_at INT NOT NULL) STRICT;"""

JOB_SCHEMA = """CREATE TABLE job(
  id TEXT PRIMARY KEY, store TEXT, kind TEXT, status TEXT,
  payload TEXT, result TEXT, attempts INT,
  owner TEXT, lease_until INT, blocked_since INT, created_at INT) STRICT;"""

ICON_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><circle r="4"/></svg>'


def build_fixture(tmp):
    """레지스트리 DB + 아이콘 디렉터리 픽스처. server 모듈 전역을 픽스처로 향하게 한다."""
    aoa = os.path.join(tmp, "aoa")
    os.makedirs(aoa)
    icons = os.path.join(tmp, "root", "data", "fbot", "icons")
    os.makedirs(icons)
    with open(os.path.join(icons, "exec.svg"), "wb") as f:
        f.write(ICON_SVG)
    # 아이콘 디렉터리 **밖**의 파일 — 경로 탈출이 뚫리면 이게 읽힌다.
    with open(os.path.join(tmp, "root", "secret.svg"), "wb") as f:
        f.write(b"<svg>SECRET</svg>")
    db = os.path.join(aoa, "registry.db")
    now = int(time.time())
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # 활성 3종 — 정렬은 working → checkin → waiting_input 순이어야 한다.
            ("b-wait", "대기봇", "qa", "waiting_input", "수습",
             None, "#111111", 12, "", None, now + 600, now),
            ("b-work", "작업봇", "chief", "working", "정식",
             "data/fbot/icons/exec.svg", "#872EC6", None, "이슈 처리", None, now + 600, now),
            ("b-in", "출근봇", "hr", "checkin", "정식", None, "", None, "", None, now - 10, now),
            # 퇴근 — 활성이 아니므로 카드에서 빠지되 total 에는 잡힌다.
            ("b-out", "퇴근봇", "research", "checkout", "수습",
             None, "", None, "", None, None, now),
            # 경로 탈출 시도 — icon 값이 아이콘 디렉터리 밖을 가리킨다.
            ("b-esc", "탈출봇", "qa", "working", "수습",
             "../root/secret.svg", "", None, "", None, now + 600, now),
        ])
    con.commit()
    con.close()
    server.FBOT_AOA_DIR = aoa
    server.FBOT_ROOT = os.path.join(tmp, "root")
    return aoa


def main():
    print("== _collect_bots / _fbot_icon_data_uri (prj3#Issue438 ③) ==")

    # 1) fbot 미설치 — DB 부재는 에러가 아니라 "봇 0" 이다.
    with tempfile.TemporaryDirectory() as tmp:
        server.FBOT_AOA_DIR = os.path.join(tmp, "nope")
        server.FBOT_ROOT = tmp
        r = server._collect_bots()
        check("DB 부재 → 빈 결과(예외 없음)",
              r == {"bots": [], "bots_active": 0, "bots_total": 0})

    # 2-b) DB 손상 등 진짜 오류는 "봇 0" 과 구분되어 bots_error 로 노출되어야 한다.
    #      조용한 0 은 "봇이 놀고 있다" 로 읽혀 이 섹션의 목적을 배반한다.
    with tempfile.TemporaryDirectory() as tmp:
        aoa = os.path.join(tmp, "aoa")
        os.makedirs(aoa)
        with open(os.path.join(aoa, "registry.db"), "wb") as f:
            f.write(b"this is not a sqlite database" * 40)
        server.FBOT_AOA_DIR = aoa
        server.FBOT_ROOT = tmp
        r = server._collect_bots()
        check("DB 손상 → bots_error 노출", bool(r.get("bots_error")))

    # 2) DB 는 있으나 bot 테이블이 없는 경우(마이그레이션 전)도 정상 경로.
    with tempfile.TemporaryDirectory() as tmp:
        aoa = os.path.join(tmp, "aoa")
        os.makedirs(aoa)
        sqlite3.connect(os.path.join(aoa, "registry.db")).close()
        server.FBOT_AOA_DIR = aoa
        server.FBOT_ROOT = tmp
        r = server._collect_bots()
        check("bot 테이블 부재 → 빈 결과", r["bots"] == [])
        check("bot 테이블 부재는 오류가 아님", "bots_error" not in r)

    with tempfile.TemporaryDirectory() as tmp:
        build_fixture(tmp)
        r = server._collect_bots()
        ids = [b["bot_id"] for b in r["bots"]]

        # 3) 활성만 카드에 오른다. total 은 전원.
        check("퇴근 봇 제외", "b-out" not in ids)
        check("활성 4건", r["bots_active"] == 4 and len(ids) == 4)
        check("total 은 퇴근 포함 5건", r["bots_total"] == 5)

        # 4) 정렬 — working 이 먼저, 같은 상태면 호칭순.
        check("working 우선 정렬", ids[0] in ("b-work", "b-esc") and ids[1] in ("b-work", "b-esc"))
        check("checkin 이 waiting_input 보다 앞", ids.index("b-in") < ids.index("b-wait"))

        by = {b["bot_id"]: b for b in r["bots"]}

        # 5) 아이콘 인라인 — data URI 로 실제 SVG 바이트가 실려야 한다.
        uri = by["b-work"]["icon_uri"]
        check("아이콘 data URI 접두", uri.startswith("data:image/svg+xml;base64,"))
        check("아이콘 바이트 일치",
              base64.b64decode(uri.split(",", 1)[1]) == ICON_SVG)

        # 6) 경로 탈출 차단 — 아이콘 디렉터리 밖은 읽지 않는다.
        #    단 role 아이콘 폴백은 살아 있으므로, 탈출 대상 파일 내용이 실리지 않았음을 본다.
        esc_uri = by["b-esc"]["icon_uri"]
        check("경로 탈출 차단(비밀 파일 미유출)",
              b"SECRET" not in (base64.b64decode(esc_uri.split(",", 1)[1]) if esc_uri else b""))
        # 7) role 아이콘 폴백 — 개체 아이콘이 없어도 종류 도형은 뜬다.
        #    (b-wait 은 qa role, 픽스처에 qa.svg 없음 → 폴백도 실패 → 빈 문자열)
        check("개체·role 아이콘 모두 부재 → 빈 문자열", by["b-wait"]["icon_uri"] == "")
        role_icon = os.path.join(server.FBOT_ROOT, "data", "fbot", "icons", "qa.svg")
        with open(role_icon, "wb") as f:
            f.write(b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')
        again = {b["bot_id"]: b for b in server._collect_bots()["bots"]}
        check("role 아이콘 폴백 작동", again["b-wait"]["icon_uri"].startswith("data:image/svg+xml;base64,"))
        check("개체 아이콘이 role 폴백보다 우선",
              base64.b64decode(again["b-work"]["icon_uri"].split(",", 1)[1]) == ICON_SVG)

        # 8) lease 만료 → 크래시 의심 표시.
        check("lease 만료 감지", by["b-in"]["lease_stale"] is True)
        check("lease 유효는 미표시", by["b-work"]["lease_stale"] is False)
        # 8-a) Issue531 — 수신대기 봇은 lease 가 끊겨도 idle 유예 안이면 크래시가 아니다.
        #   reap(fbot-state.py, prj3#Issue554)과 같은 규칙이어야 한다 — 갈리면 reap 은
        #   안 건드리는 살아 있는 세션을 화면만 "크래시 의심" 으로 부른다(나래 실측).
        cx = sqlite3.connect(os.path.join(server.FBOT_AOA_DIR, "registry.db"))
        cx.execute("UPDATE bot SET lease_expires=? WHERE bot_id='b-wait'", (int(time.time()) - 1140,))
        cx.commit()
        idle = {b["bot_id"]: b for b in server._collect_bots()["bots"]}
        check("수신대기 + 유예 내 → stale 아님", idle["b-wait"]["lease_stale"] is False)
        check("수신대기 + 유예 내 → lease_idle", idle["b-wait"]["lease_idle"] is True)
        check("출근봇 만료는 유예 없음(stale)", idle["b-in"]["lease_stale"] is True
              and idle["b-in"]["lease_idle"] is False)
        cx.execute("UPDATE bot SET lease_expires=? WHERE bot_id='b-wait'", (int(time.time()) - 7300,))
        cx.commit()
        over = {b["bot_id"]: b for b in server._collect_bots()["bots"]}
        check("수신대기 + 유예 초과 → stale", over["b-wait"]["lease_stale"] is True
              and over["b-wait"]["lease_idle"] is False)
        # 유예 수치는 policy.yml 이 정본 — 픽스처 policy 가 기본 7200 을 이겨야 한다.
        with open(os.path.join(server.FBOT_AOA_DIR, "policy.yml"), "w") as f:
            f.write("idle_ttl_secs: 600\n")
        cx.execute("UPDATE bot SET lease_expires=? WHERE bot_id='b-wait'", (int(time.time()) - 1140,))
        cx.commit()
        pol = {b["bot_id"]: b for b in server._collect_bots()["bots"]}
        check("policy idle_ttl_secs 반영", pol["b-wait"]["lease_stale"] is True)
        os.remove(os.path.join(server.FBOT_AOA_DIR, "policy.yml"))
        cx.execute("UPDATE bot SET lease_expires=? WHERE bot_id='b-wait'", (int(time.time()) + 600,))
        cx.commit()
        cx.close()
        # 8-b) Issue401 — 펼침 상세가 잔여/경과 분을 계산하려면 원본 epoch 이 필요하다.
        #      lease_stale(bool) 만으로는 "몇 분 지났나" 를 못 만든다.
        check("lease_expires epoch 노출", isinstance(by["b-work"]["lease_expires"], int))
        # lease NULL(아직 출근 전·리스 미발급)이 0 으로 뭉개지면 상세가 "만료 57년 경과"
        #   같은 헛소리를 쓴다 — None 으로 남아 lease 줄 자체가 생략돼야 한다.
        cx = sqlite3.connect(os.path.join(server.FBOT_AOA_DIR, "registry.db"))
        cx.execute("UPDATE bot SET lease_expires=NULL WHERE bot_id='b-work'")
        cx.commit(); cx.close()
        nl = {b["bot_id"]: b for b in server._collect_bots()["bots"]}
        check("lease NULL 은 None (0 으로 뭉개지지 않음)", nl["b-work"]["lease_expires"] is None)
        check("lease NULL 은 stale 도 아님", nl["b-work"]["lease_stale"] is False)
        check("펼침 상세용 필드 3종 동반(career·parent·lease)",
              all(k in by["b-work"] for k in ("career", "parent_bot_id", "lease_expires")))

        # 9) 상태 라벨·이모지 매핑 (prj3 fbot-state.py STATE_LABEL 정합).
        check("state_label 한국어 매핑", by["b-work"]["state_label"] == "작업중")
        check("state_emoji 매핑", by["b-wait"]["state_emoji"] == "⏳")

        # 10) 아이콘 크기 상한 — 상한 초과는 인라인하지 않는다(payload 비대 차단).
        big = os.path.join(tmp, "root", "data", "fbot", "icons", "big.svg")
        with open(big, "wb") as f:
            f.write(b"<svg>" + b"x" * (17 * 1024) + b"</svg>")
        check("상한 초과 아이콘 미인라인",
              server._fbot_icon_data_uri("data/fbot/icons/big.svg") == "")

    # 12) Issue400 — 유휴 요약용 오늘 집계(bots_today).
    #     "전원 퇴근" 을 숨기지 않고 1줄로 보이려면 실적 수치가 payload 에 있어야 한다.
    with tempfile.TemporaryDirectory() as tmp:
        build_fixture(tmp)
        # 12-a) job 원장이 없는 환경도 정상 경로 — 예외 없이 빈 dict.
        r = server._collect_bots()
        check("job 테이블 부재 → bots_today 빈 dict", r.get("bots_today") == {})
        check("job 테이블 부재는 봇 카드를 깨지 않음", r["bots_active"] == 4)

        db = os.path.join(server.FBOT_AOA_DIR, "registry.db")
        midnight = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
        noon = midnight + 43200
        con = sqlite3.connect(db)
        con.executescript(JOB_SCHEMA)
        con.executemany(
            "INSERT INTO job VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                # 오늘 배분 2건(1 done · 1 cancelled)
                ("j1", "fbot", "fbot_dispatch", "done", "", "", 0, "", None, None, noon),
                ("j2", "fbot", "fbot_dispatch", "cancelled", "", "", 0, "", None, None, noon),
                # ⚠️ store 가 빈 문자열인 세션 완료 — 실제 원장이 이렇게 갈려 있다.
                #    store='fbot' 으로 걸렀다면 이 건이 통째로 사라진다(회귀 박제).
                ("j3", "", "fbot_session", "done", "", "", 0, "", None, None, noon),
                # 어제 건 — 오늘 집계에서 빠져야 한다.
                ("j4", "fbot", "fbot_dispatch", "done", "", "", 0, "", None, None,
                 midnight - 3600),
                # fbot 이 아닌 job — 남의 원장을 세면 안 된다. **가장 최신**으로 두어
                #   kind 필터가 풀리면 done 과 last_ts 가 동시에 틀어지게 한다.
                ("j5", "learn", "consolidation", "done", "", "", 0, "", None, None,
                 noon + 600),
            ])
        con.commit()
        con.close()

        td = server._collect_bots()["bots_today"]
        check("오늘 배분 2건", td["dispatched"] == 2)
        check("완료는 배분+세션 합산 2건 (store 혼재 무관)", td["done"] == 2)
        check("취소 1건", td["cancelled"] == 1)
        check("어제 건 제외", td["dispatched"] == 2 and td["done"] == 2)
        # kind 필터가 풀리면 learn 의 done 이 섞여 3 이 되고 last_ts 도 noon+600 이 된다.
        check("learn job 미집계 (done)", td["done"] == 2)
        check("learn job 미집계 (last_ts 는 fbot job 최댓값)", td["last_ts"] == noon)

    # 12) Issue404 ⓒ — "미설치" 와 "설치됐는데 레지스트리를 못 찾는다" 는 갈려야 한다.
    #     후자까지 조용히 감추면 launchd hub 가 env 없이 떠서 핀봇 섹션을 통째로 잃은
    #     사고(실발생)가 화면상 "봇이 한 명도 없다" 와 구분되지 않는다.
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "root")
        os.makedirs(os.path.join(root, "data", "fbot", "icons"))
        server.FBOT_AOA_DIR = os.path.join(tmp, "nope")
        server.FBOT_ROOT = root
        keep = os.environ.pop("AOA_MEMORY_DIR", None)
        try:
            r = server._collect_bots()
        finally:
            if keep is not None:
                os.environ["AOA_MEMORY_DIR"] = keep
        err = r.get("bots_error") or ""
        check("설치 흔적 O + DB 부재 → bots_error 노출", bool(err))
        check("bots_error 에 조회한 경로가 담긴다", "nope" in err)
        check("env 미설정이면 그 사실을 밝힌다", "AOA_MEMORY_DIR" in err)
        check("오류여도 봇 0 형태는 유지(카드가 깨지지 않는다)",
              r["bots"] == [] and r["bots_total"] == 0)

    with tempfile.TemporaryDirectory() as tmp:
        # 진짜 미설치 — data/fbot 자체가 없다. 섹션을 띄우지 않는 것이 옳다.
        server.FBOT_AOA_DIR = os.path.join(tmp, "nope")
        server.FBOT_ROOT = tmp
        check("미설치(흔적 없음) 는 오류가 아니다", "bots_error" not in server._collect_bots())

    # 13) Issue405 — 퇴근 봇의 **마지막 실행 시각**. 이 필드가 없어 5분 전 퇴근과 두 달
    #     전 퇴근이 같은 칩으로 그려졌다.
    with tempfile.TemporaryDirectory() as tmp:
        aoa = build_fixture(tmp)
        now = int(time.time())
        con = sqlite3.connect(os.path.join(aoa, "registry.db"))
        con.executescript(JOB_SCHEMA)
        # job 기록이 하나도 없는 퇴근 봇 — 없는 시각을 지어내면 안 된다.
        con.execute("INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("b-idle", "무기록봇", "qa", "checkout", "수습",
                     None, "", None, "", None, None, now))
        con.executemany(
            "INSERT INTO job VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                # 퇴근봇 — 최신 2시간 전. store 가 '' 로 갈린 구건도 함께 둔다.
                ("j1", "fbot", "fbot_session", "done", "{}", "", 0, "b-out", None, None, now - 7200),
                ("j0", "", "fbot_session", "done", "{}", "", 0, "b-out", None, None, now - 99999),
                # 활성 봇도 원장에는 있지만 roster 에 실리면 안 된다(소비처 없음).
                ("j2", "fbot", "fbot_session", "done", "{}", "", 0, "b-work", None, None, now - 60),
                # fbot 이 아닌 kind 는 집계 대상이 아니다 — 섞이면 시각이 최신으로 오염된다.
                ("j3", "", "learn", "done", "{}", "", 0, "b-out", None, None, now - 1),
            ])
        con.commit()
        con.close()
        r = server._collect_bots()
        by = {m["bot_id"]: m for m in r["bots_roster"]}
        check("퇴근 봇에 last_seen 부여", by["b-out"].get("last_seen") == now - 7200)
        check("MAX 로 최신 건 선택(오래된 건에 눌리지 않음)",
              by["b-out"].get("last_seen") != now - 99999)
        check("fbot 이외 kind 는 집계 제외", by["b-out"].get("last_seen") != now - 1)
        check("활성 봇에는 last_seen 미부여", "last_seen" not in by["b-work"])
        check("job 기록 없는 퇴근 봇은 키 자체가 없다", "last_seen" not in by["b-idle"])

    # 14) Issue405 — 24h 경계 판정은 **클라이언트**에 있다. 상수·비교 방향·배선을
    #     소스에서 뽑아 박제한다: 문구만 바뀌고 판정이 뒤집히는 종류의 회귀를 잡는다.
    hub_dir = os.path.dirname(os.path.abspath(server.__file__))
    src = open(os.path.join(hub_dir, "server.py"), encoding="utf-8").read()
    # prj1#Issue449: 퇴근 칩은 최근(24h) 만 남기고 나머지는 "외 N개" 로 접는다 —
    #   무한 성장 방지(실측 워커 11칩). 전체는 조직도 ?all=1 이 담당.
    check("최근 퇴근만 botChip 으로 배선(Issue546 상한 안)",
          "const shown = recent.slice(0, BOT_CHIP_MAX);" in src and "shown.map(botChip)" in src)
    check("오래된 퇴근은 외 N개 링크로 접힘", "bot-rest-more" in src and "bots.restMore" in src)
    check("접힘 링크는 조직도 전체 뷰로", "&all=1" in src)
    check("24h 상수 존재", "const BOT_RECENT_SEC = 86400;" in src)
    check("경계 비교 방향(24h 미만 = 최근)",
          "const fresh = (Date.now() / 1000 - ts) < BOT_RECENT_SEC;" in src)
    check("24h 초과분은 상대시각을 붙이지 않는다", "if (!fresh) return" in src)
    check("기록 없으면 시각을 지어내지 않는다", "if (!ts) return" in src)
    check("최근 퇴근 칩 전용 클래스", ".bot-chip-recent" in src)
    for key in ("bots.chipCheckout", "bots.chipLastSeen"):
        check(f"{key} 사용", key in src)
        for loc in ("ko", "en"):
            lp = os.path.join(os.path.dirname(os.path.dirname(hub_dir)),
                              "data", "locales", f"{loc}.json")
            check(f"{key} 번역 존재({loc})", key in open(lp, encoding="utf-8").read())

    # 15) Issue445 — 지시 관계와 봇↔세션 연결. **표시가 없으면 사용자가 세션 UUID 를
    #     들고 와 되물어야 한다**(2026-08-31 실발생). 두 축을 함께 박제한다:
    #     ⓐ 결속 컬럼이 있는 DB 에서 값이 실린다  ⓑ 없는 DB 에서도 죽지 않는다.
    BIND_SCHEMA = SCHEMA.replace(
        "lease_expires INT, created_at INT NOT NULL) STRICT;",
        "lease_expires INT, created_at INT NOT NULL,"
        " tmux_target TEXT, session_id TEXT) STRICT;")
    with tempfile.TemporaryDirectory() as tmp:
        aoa = os.path.join(tmp, "aoa")
        os.makedirs(aoa)
        now = int(time.time())
        con = sqlite3.connect(os.path.join(aoa, "registry.db"))
        con.executescript(BIND_SCHEMA)
        con.executemany(
            "INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # 지시자는 **퇴근** 상태다 — 활성 봇만으로 호칭 맵을 만들면 여기서 깨진다.
                ("b-boss", "나래(총괄)", "chief", "checkout", "정식",
                 None, "", None, "", None, None, now, "pm:w.0", "sid-boss"),
                ("b-kid", "리서치 워커", "research", "working", "수습",
                 None, "", 3, "조사", "b-boss", now + 600, now, None, "sid-kid"),
                # 부모가 레지스트리에서 사라진 봇 — 이름을 **지어내면 안 된다**.
                ("b-lost", "고아 워커", "qa", "working", "수습",
                 None, "", None, "", "b-gone", now + 600, now, None, None),
            ])
        con.commit()
        con.close()
        server.FBOT_AOA_DIR = aoa
        server.FBOT_ROOT = tmp
        by = {b["bot_id"]: b for b in server._collect_bots()["bots"]}
        check("지시자 호칭 resolve (ID 원문 아님)", by["b-kid"]["parent_title"] == "나래(총괄)")
        check("지시자가 퇴근해도 호칭이 남는다", by["b-kid"]["parent_bot_id"] == "b-boss")
        check("session_id 편입", by["b-kid"]["session_id"] == "sid-kid")
        check("tmux_target 없으면 빈 값(NULL 을 문자열로 오염시키지 않는다)",
              by["b-kid"]["tmux_target"] == "")
        check("부모가 명부에 없으면 호칭을 지어내지 않는다", by["b-lost"]["parent_title"] == "")
        # 조직도도 같은 값을 봐야 한다 — 홈과 조직도가 다른 사실을 말하면 안 된다.
        nodes = {n["bot_id"]: n for n in server._fbot_org_data()["nodes"]}
        check("조직도 노드에도 결속이 실린다", nodes["b-boss"]["tmux_target"] == "pm:w.0")
        check("조직도 노드 session_id 일치", nodes["b-kid"]["session_id"] == "sid-kid")

    # 15-b) 결속 컬럼이 **없는** 구 스키마(prj3#Issue448 마이그레이션 전). 명시 SELECT 가
    #       `no such column` 으로 죽으면 핀봇 섹션이 통째로 오류가 된다 — 그 회귀를 막는다.
    with tempfile.TemporaryDirectory() as tmp:
        build_fixture(tmp)
        r = server._collect_bots()
        check("구 스키마에서도 오류 없음", "bots_error" not in r and r["bots_active"] == 4)
        check("구 스키마 결속 값은 빈 문자열",
              all(b["session_id"] == "" and b["tmux_target"] == "" for b in r["bots"]))
        check("구 스키마에서도 조직도가 선다", server._fbot_org_data()["error"] == "")

    # 15-c) 클라이언트 배선 — 표면 노출과 상세 resolve 를 소스에서 박제한다.
    check("카드 표면에 지시자·세션 칩 줄", 'class="bot-meta"' in src)
    check("지시자는 호칭 우선 ID 폴백", "b.parent_title || b.parent_bot_id" in src)
    check("상세의 parent 는 이름(ID) 병기", "${b.parent_title} (${b.parent_bot_id})" in src)
    for key in ("bots.parentBy", "bots.parentTitle", "bots.sessionTitle",
                "bots.d.session", "bots.d.pane"):
        check(f"{key} 사용", key in src)
        for loc in ("ko", "en"):
            lp = os.path.join(os.path.dirname(os.path.dirname(hub_dir)),
                              "data", "locales", f"{loc}.json")
            check(f"{key} 번역 존재({loc})", key in open(lp, encoding="utf-8").read())

    # 16) prj3#Issue611 — 이름 개편(Issue610) 이전 원장의 옛 부모 id. 해소가 빠지면
    #     **전원이 자기 자신의 루트**가 되어 조직이 화면에서 사라진다(실측 2026-09-10:
    #     봇 25명 → 그룹 25개, 전부 멤버1·활성0). 저장은 원본이므로 판정에서 푼다.
    with tempfile.TemporaryDirectory() as tmp:
        aoa = os.path.join(tmp, "aoa")
        os.makedirs(aoa)
        now = int(time.time())
        con = sqlite3.connect(os.path.join(aoa, "registry.db"))
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                # 현 id 로 존재하는 부모. 원장의 자식들은 **옛 id** 로 이 봇을 가리킨다.
                ("fbot-lead", "팀장핀봇", "lead", "checkout", "정식",
                 None, "", None, "", None, None, now),
                ("fbot-lead-pm", "pm 팀장핀봇", "lead", "checkout", "정식",
                 None, "", 1, "", "fbot-taskmgr", None, now),
                ("fbot-research-s4", "조사 워커", "research", "working", "수습",
                 None, "", 3, "조사", "fbot-taskmgr", now + 600, now),
                # 진짜로 부모가 사라진 봇 — 해소를 넣어도 자기 루트로 남아야 한다.
                ("fbot-orphan", "고아", "qa", "working", "수습",
                 None, "", None, "", "fbot-nobody", now + 600, now),
            ])
        con.commit()
        con.close()
        server.FBOT_AOA_DIR = aoa
        server.FBOT_ROOT = tmp
        r = server._collect_bots()
        rmap = {m["bot_id"]: m["root"] for m in r["bots_roster"]}
        check("옛 부모 id 가 현 루트로 해소된다(자식 → fbot-lead)",
              rmap["fbot-lead-pm"] == "fbot-lead" and rmap["fbot-research-s4"] == "fbot-lead")
        check("현 루트는 자기 자신", rmap["fbot-lead"] == "fbot-lead")
        check("진짜 고아는 자기 루트로 남는다", rmap["fbot-orphan"] == "fbot-orphan")
        check("그룹 수가 봇 수만큼 폭발하지 않는다(4봇 → 2그룹)",
              len(set(rmap.values())) == 2)
        by = {b["bot_id"]: b for b in r["bots"]}
        check("카드의 지시자도 현 id 로 해소",
              by["fbot-research-s4"]["parent_bot_id"] == "fbot-lead")
        check("해소된 지시자 호칭이 붙는다",
              by["fbot-research-s4"]["parent_title"] == "팀장핀봇")
        # 조직도도 같은 사실을 말해야 한다 — 채용 엣지가 조용히 0건이 되면 계층이 소실된다.
        nodes = {n["bot_id"]: n for n in server._fbot_org_data()["nodes"]}
        check("조직도 채용 엣지도 해소된다",
              nodes["fbot-research-s4"]["parent"] == "fbot-lead")
        check("조직도의 고아는 부모 없음", nodes["fbot-orphan"]["parent"] == "")

    # 16-b) prj3#Issue611(사용자 지시 2026-09-10) — 활성 0 그룹은 그리지 않는다.
    #       팀장핀봇은 프로젝트마다 상주해 20명을 넘고 전원 퇴근이 정상이라, 그대로
    #       그리면 홈이 조직 명부가 된다. 판정은 클라이언트에 있어 소스에서 박제한다.
    check("활성 0 그룹 미렌더 배선", "if (!act) return '';" in src)
    #       ⚠️ Issue400 의 하한선 — 유휴 요약 1줄과 미설치 판정은 살아 있어야 한다.
    #       이 둘이 죽으면 "fbot 사망" 과 "봇 유휴" 가 화면에서 같아진다.
    check("유휴 요약 1줄은 유지(전원 퇴근을 감추지 않는다)",
          "renderBotsIdle" in src and "bot-idle" in src)
    check("섹션 통째 숨김은 미설치(total 0) 한 경우뿐",
          "if (!total) { sec.style.display = 'none';" in src)

    # 15) Issue546 — 퇴근 칩은 **기본 접힘 + 개수 상한**. Issue450 의 24h 창은 시간 기준뿐이라
    #     웨이브 날(24h 내 31 퇴근)에 무력했다 — 칩 30개. 접힘 안에서 Issue405 강조 사양은 그대로 산다.
    check("퇴근 칩 상한 상수", "const BOT_CHIP_MAX = 6;" in src)
    check("펼침 상태 유지 집합(5초 재렌더 생존)", "const openBotRest = new Set();" in src)
    check("한 줄 토글 버튼 렌더", 'class="bot-rest-toggle"' in src and "bots.restToggle" in src)
    check("기본 접힘 — 펼친 그룹만 hidden 해제", "openBotRest.has(rid)" in src and "' hidden'" in src)
    check("최근 퇴근은 최신순 정렬 후 상한", "recent.sort((a, b) => b.last_seen - a.last_seen)" in src)
    check("hidden 이 flex 를 이긴다", ".bot-group-rest[hidden] { display: none; }" in src)
    check("토글 클릭 배선(아코디언·이름 링크보다 먼저)", ".bot-rest-toggle[data-rest]" in src)
    for loc in ("ko", "en"):
        lp = os.path.join(os.path.dirname(os.path.dirname(hub_dir)), "data", "locales", f"{loc}.json")
        check(f"bots.restToggle 번역 존재({loc})", "bots.restToggle" in open(lp, encoding="utf-8").read())

    # 17) Issue547 — 홈 카드 그룹 축 = **prj 조직**. 원장의 parent 는 55/60 이 `fbot-lead`(본사 자리)라
    #     루트 봇 축으로 묶으면 "팀장핀봇 1/56" 한 덩어리가 된다(2026-09-27 실측). `root` 는 조직도
    #     관계 축이라 그대로 두고, 홈만 `group`(prj{N} | hq)·`group_head` 로 묶는다.
    with tempfile.TemporaryDirectory() as tmp:
        aoa = os.path.join(tmp, "aoa")
        os.makedirs(aoa)
        now = int(time.time())
        con = sqlite3.connect(os.path.join(aoa, "registry.db"))
        con.executescript(SCHEMA)
        L = now + 600
        con.executemany(
            "INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("fbot-chief", "나래", "chief", "working", "정식", None, "", None, "보고", None, L, now),
                ("fbot-hr", "인사핀봇", "hr", "checkout", "정식", None, "", None, "", "fbot-chief", None, now),
                ("fbot-lead", "팀장핀봇", "lead", "checkout", "정식", None, "", None, "", "fbot-chief", None, now),
                ("fbot-lead-a", "a 팀장핀봇", "lead", "working", "정식", None, "", 26, "배포", "fbot-lead", L, now),
                ("fbot-qa-a", "Issue9 담당 qa 워커", "qa", "checkout", "수습", None, "", 26, "", "fbot-lead", None, now),
                ("fbot-lead-issue4", "Issue4 담당 lead 워커", "lead", "checkout", "수습", None, "", 60, "", "fbot-lead", None, now),
                ("fbot-lead-lec", "lec 팀장핀봇", "lead", "checkout", "정식", None, "", 60, "", "fbot-lead", None, now),
                ("fbot-qa-lec", "Issue4 담당 qa 워커", "qa", "working", "수습", None, "", 60, "검증", "fbot-lead", L, now),
                ("fbot-lead-c", "c 팀장핀봇", "lead", "checkout", "정식", None, "", 5, "", "fbot-lead", None, now),
            ])
        con.commit()
        con.close()
        server.FBOT_AOA_DIR = aoa
        server.FBOT_ROOT = tmp
        ros = server._collect_bots()["bots_roster"]
        by = {m["bot_id"]: m for m in ros}
        check("roster 에 group 키", all("group" in m for m in ros))
        check("prj 없는 봇 → 본사 그룹", {by[b]["group"] for b in ("fbot-chief", "fbot-hr", "fbot-lead")} == {"hq"})
        check("prj 봇 → prj{N} 그룹", by["fbot-lead-a"]["group"] == "prj26" and by["fbot-qa-a"]["group"] == "prj26")
        heads = {m["group"]: m["bot_id"] for m in ros if m.get("group_head")}
        check("본사 그룹 머리 = chief", heads.get("hq") == "fbot-chief")
        check("prj 그룹 머리 = 그 prj 팀장", heads.get("prj26") == "fbot-lead-a")
        check("팀장 중복이면 '팀장핀봇' 호칭이 머리", heads.get("prj60") == "fbot-lead-lec")
        check("그룹당 머리는 하나", len(heads) == len({m["group"] for m in ros})
              and sum(1 for m in ros if m.get("group_head")) == len(heads))
        order = []
        for m in ros:
            if m["group"] not in order:
                order.append(m["group"])
        check("활성 그룹 먼저·본사 먼저·prj 자연 정렬", order == ["hq", "prj26", "prj60", "prj5"])
        firsts = {}
        for m in ros:
            firsts.setdefault(m["group"], m["bot_id"])
        check("그룹 안에서 머리가 먼저", all(firsts[g] == heads[g] for g in heads))
        check("root(조직도 관계 축)는 불변", by["fbot-lead-a"]["root"] == "fbot-chief")
        check("group 머리 아이콘 키 동반", "icon_uri" in by["fbot-lead-a"])
    check("홈 그룹핑은 group 우선·구 payload 는 root 폴백", "const gk = m.group || m.root;" in src)
    check("그룹 머리 판정은 group_head 우선", "(m.group ? m.group_head : m.is_root)" in src)
    check("prj 그룹 👥 링크는 조직도 org 탭", "/fbot-map?tab=org&prj=" in src)

    # 18) Issue552 — 퇴역(해고·휴직)은 홈 명부·총계에서 빠진다. 조직도(_fbot_filter_career, Issue451)와
    #     같은 판정이어야 한다 — 갈리면 prj60 처럼 해고된 중복 팀장이 홈에서만 구성원으로 남는다.
    with tempfile.TemporaryDirectory() as tmp:
        aoa = os.path.join(tmp, "aoa")
        os.makedirs(aoa)
        now = int(time.time())
        con = sqlite3.connect(os.path.join(aoa, "registry.db"))
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("fbot-lead-lec", "lec 팀장핀봇", "lead", "working", "active", None, "", 60, "x", None, now + 600, now),
                ("fbot-lead-issue4", "Issue4 담당 lead 워커", "lead", "checkout", "terminated", None, "", 60, "", None, None, now),
                ("fbot-qa-old", "휴직 워커", "qa", "checkout", "leave", None, "", 60, "", None, None, now),
                ("fbot-qa-ok", "재직 워커", "qa", "checkout", "probation", None, "", 60, "", None, None, now),
            ])
        con.commit()
        con.close()
        server.FBOT_AOA_DIR = aoa
        server.FBOT_ROOT = tmp
        r = server._collect_bots()
        ids = {m["bot_id"] for m in r["bots_roster"]}
        check("해고자는 홈 명부에서 빠진다", "fbot-lead-issue4" not in ids)
        check("휴직자는 홈 명부에서 빠진다", "fbot-qa-old" not in ids)
        check("재직자는 남는다", {"fbot-lead-lec", "fbot-qa-ok"} <= ids)
        check("총계도 재직 기준(4행 → 2)", r["bots_total"] == 2)
    check("퇴역 판정 단일 지점", "def _fbot_retired(" in src and src.count('("leave", "terminated")') == 1)

    # 11) badge 위젯 icon 스킴 가드 — data:/http(s) 만 <img> 로 렌더한다.
    #     문자열 존재만 보면 가드가 뒤집혀도 통과하므로, JS 소스에서 정규식을 **뽑아
    #     실제로 평가**한다. javascript: 주입이 통과하면 여기서 잡힌다.
    js = spa_widgets.WIDGET_JS
    check("badge icon 필드 존재", "w.icon" in js and "badge-icon" in js)
    m = re.search(r"const iconOk = /(.+?)/\.test\(rawIcon\);", js)
    check("icon 스킴 정규식 존재", m is not None)
    if m:
        pat = re.compile(m.group(1).replace("\\/", "/"))
        check("data: 이미지 허용", bool(pat.match("data:image/svg+xml;base64,AAA")))
        check("https 허용", bool(pat.match("https://example.test/a.svg")))
        check("javascript: 차단", not pat.match("javascript:alert(1)"))
        check("data:text/html 차단", not pat.match("data:text/html,<script>"))
        check("상대경로 차단", not pat.match("data/fbot/icons/exec.svg"))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
