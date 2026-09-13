#!/usr/bin/env python3
"""schedule-core.py — schedule.sh 의 파싱·컴파일 코어 (Issue537)

⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude 면 Issue.md 등록 후 처리)
📚 설계 SSOT: ~/.claude/_doc_arch/schedule-arch.md

진입점 계약은 `hooks/schedule.sh` 가 소유한다. 이 파일은 그 안쪽이며 직접 부르지 않는다.

## 왜 python 인가
  YAML 파싱·시각 필드 전개·plist 직렬화를 bash 로 하면 따옴표와 배열에서 무너진다.
  bash 는 진입점 계약(서브커맨드·env knob)만 갖고, 해석은 전부 여기서 한다.

## ⚠️ 바인딩 키는 event/job 이다
  `on:` 은 YAML 1.1 에서 불리언 True 로 파싱되고, `yes:` 와 같은 키로 뭉개져 값이
  통째로 사라진다(2026.09.05 실측). `off`·`no`·`y`·`n`·`true`·`false` 도 같다.
  BOOL_KEYS 가 그 방어선이며, 선언에 섞이면 로드 시점에 fail-loud 한다.
"""
import os
import plistlib
import re
import sys
import time

try:
    import yaml
except ImportError:
    sys.exit("schedule: PyYAML 없음 — pip3 install pyyaml")

YML = os.environ.get("SCHEDULE_YML") or ""
# prj3#Issue579: UI 가 쓰는 두 번째 선언. 없으면 종전과 완전히 동일하게 돈다.
#   schedule.sh 가 기본값(= YML 옆의 schedule.user.yml)을 넣어 준다.
USER_YML = os.environ.get("SCHEDULE_USER_YML") or ""
LABEL_PREFIX = os.environ.get("SCHEDULE_LABEL_PREFIX") or "kr.finfra.sched-"
LEDGER = os.environ.get("SCHEDULE_LEDGER") or ""
ROOT = os.environ.get("SCHEDULE_ROOT") or os.path.expanduser("~/.claude")

HOME = os.path.expanduser("~")
LA_DIR = os.path.join(HOME, "Library", "LaunchAgents")

# YAML 1.1 이 불리언으로 삼키는 토큰 — 키·이름 어디에도 쓸 수 없다
BOOL_KEYS = {"on", "off", "yes", "no", "y", "n", "true", "false"}

WEEKDAY = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def die(msg):
    sys.exit("schedule: %s" % msg)


# ── 로드·검증 ────────────────────────────────────────────────────────────
def _read_decl(path, required=True):
    """선언 파일 하나를 읽어 3절을 돌려준다. 절 결손은 fail-loud."""
    if not os.path.exists(path):
        if required:
            die("선언 파일 없음: %s" % path)
        return {}, {}, []           # prj3#Issue579: user.yml 부재는 정상이다
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    if not isinstance(d, dict):
        die("선언이 매핑이 아니다: %s" % path)
    for sec in ("events", "jobs", "bindings"):
        if sec not in d:
            if required:
                die("선언에 `%s:` 절이 없다: %s" % (sec, path))
            d[sec] = {} if sec != "bindings" else []
        if d[sec] is None:          # `events:` 만 쓰고 비운 경우
            d[sec] = {} if sec != "bindings" else []
    if not isinstance(d["events"], dict) or not isinstance(d["jobs"], dict):
        die("events·jobs 는 매핑이어야 한다: %s" % path)
    if not isinstance(d["bindings"], list):
        die("bindings 는 목록이어야 한다: %s" % path)
    return d["events"], d["jobs"], d["bindings"]


def load(with_source=False):
    """선언을 읽고 **구조 위반을 전부 fail-loud** 로 잡는다.

    조용히 넘어가면 '선언에는 있는데 아무도 부르지 않는 이벤트' 가 생기고,
    그것은 이 설계가 고치려는 침묵과 같은 실패다.

    ## 2파일 체계 (prj3#Issue579)
      `schedule.yml` 은 **주석이 본체**다 — 왜 hub-down 이 없는지, 왜 --gate 를 뗐는지가
      전부 주석에 있다. 기계가 `yaml.dump` 로 쓰면 그 전부가 지워지므로, UI 가 쓰는
      선언은 `schedule.user.yml` 로 가른다. 소유권 경계가 파일 경계다.

      merge 규칙 셋:
        ① user 가 system 의 **이름을 덮으면 거부** — UI 로 시스템 잡을 못 지운다
        ② 참조는 **user → system 단방향** — system 파일만으로 항상 유효해야 한다
        ③ `user.yml` **부재는 정상** — 없으면 종전과 완전히 동일하다

    `with_source=True` 면 4번째 값으로 출처 맵을 준다(화면 배지·삭제 가드용).
    """
    events, jobs, bindings = _read_decl(YML, required=True)
    src = {"events": {k: "system" for k in events},
           "jobs": {k: "system" for k in jobs},
           "bindings": ["system"] * len(bindings)}

    if USER_YML and os.path.exists(USER_YML):
        u_events, u_jobs, u_bindings = _read_decl(USER_YML, required=False)

        # ① 이름 충돌 — 시스템 선언을 사용자 파일이 덮지 못한다
        for name in sorted(set(u_events) & set(events)):
            die("사용자 선언이 시스템 이벤트 이름을 덮는다: %s (%s) — "
                "시스템 선언은 UI 로 바꿀 수 없다" % (name, USER_YML))
        for name in sorted(set(u_jobs) & set(jobs)):
            die("사용자 선언이 시스템 잡 이름을 덮는다: %s (%s) — "
                "시스템 선언은 UI 로 바꿀 수 없다" % (name, USER_YML))

        # ② 역참조 — system 바인딩이 user 를 가리키면 거부
        for i, b in enumerate(bindings):
            if not isinstance(b, dict):
                continue
            if b.get("event") in u_events:
                die("시스템 바인딩[%d] 이 사용자 이벤트를 참조한다: %s — "
                    "참조는 user → system 단방향이다" % (i, b["event"]))
            if b.get("job") in u_jobs:
                die("시스템 바인딩[%d] 이 사용자 잡을 참조한다: %s — "
                    "참조는 user → system 단방향이다" % (i, b["job"]))

        events = dict(events, **u_events)
        jobs = dict(jobs, **u_jobs)
        bindings = list(bindings) + list(u_bindings)
        src["events"].update({k: "user" for k in u_events})
        src["jobs"].update({k: "user" for k in u_jobs})
        src["bindings"] += ["user"] * len(u_bindings)

    # 불리언 토큰 방어 — 이름과 키 양쪽
    for name in list(events) + list(jobs):
        if not isinstance(name, str):
            die("이벤트·잡 이름이 문자열이 아니다: %r (YAML 불리언 토큰인가?)" % (name,))
        if name.lower() in BOOL_KEYS:
            die("이름에 YAML 불리언 토큰을 쓸 수 없다: %s" % name)
    for i, b in enumerate(bindings):
        if not isinstance(b, dict):
            die("bindings[%d] 가 매핑이 아니다: %r — `- { event: …, job: … }` 형식이다" % (i, b))
        for k in b:
            if not isinstance(k, str):
                die("bindings[%d] 키가 문자열이 아니다: %r — `on:` 대신 `event:` 를 쓴다" % (i, k))
        if "event" not in b or "job" not in b:
            die("bindings[%d] 에 event/job 이 없다: %r" % (i, b))
        if b["event"] not in events:
            die("bindings[%d] 의 event 가 선언에 없다: %s" % (i, b["event"]))
        if b["job"] not in jobs:
            die("bindings[%d] 의 job 이 선언에 없다: %s" % (i, b["job"]))

    # 고아 — 부르는 이 없는 잡, 아무 잡도 안 부르는 이벤트
    used_jobs = {b["job"] for b in bindings}
    used_events = {b["event"] for b in bindings}
    for j in sorted(set(jobs) - used_jobs):
        # prj3#Issue553: `oneshot: true` 는 큐가 `dispatch --job` 으로 **지목**하는 일회성 잡이다.
        #   Issue540 이 "일회성 예약은 큐가 소유한 데이터, 큐는 선언된 잡을 지목할 뿐" 으로 정한
        #   그 지목 대상인데, 고아 검사가 그 존재를 몰라 선언 자체를 거부했다. 반복 바인딩을
        #   붙이면 일회성이 아니게 되므로 예외가 필요하다(2026.09.06 실측 — check rc=1).
        if isinstance(jobs[j], dict) and jobs[j].get("oneshot") in (True, "true", "True"):
            continue
        die("잡 `%s` 를 부르는 바인딩이 없다 — 선언만 있고 영원히 안 돈다 "
            "(일회성 지목 대상이면 `oneshot: true` 를 단다)" % j)
    for e in sorted(set(events) - used_events):
        die("이벤트 `%s` 에 걸린 바인딩이 없다 — 발화해도 아무 일도 안 일어난다" % e)

    if with_source:
        return events, jobs, bindings, src
    return events, jobs, bindings


def expand(path):
    """`~` 와 상대경로를 **생성 시점에** 절대경로로 전개한다.

    launchd·systemd 는 env 를 확장하지 않는다. `~` 나 `$HOME` 이 유닛에 남으면
    실행 시점에 문자열 그대로 해석돼 조용히 실패한다(Issue451).
    """
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    return os.path.normpath(p)


def _resolve_unit_path():
    """유닛에 박을 PATH 를 **호출자 환경과 무관하게** 정한다 (prj3#Issue579).

    ⚠️ 종전엔 `os.environ["PATH"]` 를 그대로 박았다. 사람의 로그인 셸이 `write` 를
       부르는 동안은 옳았지만, hub(그 자신이 launchd 자식)가 부르는 순간 **짧은
       PATH** 가 박혀 Issue505 가 그대로 재발한다 — `claude`·`openclaw` 같은 node
       shebang CLI 가 exit 127 로 죽는다. 2026.09.08 실측: hub 가 `user add` 를
       처리하며 유닛 5개를 다시 구워 `check` 가 전부 불일치로 붉어졌다.

    같은 시스템의 유닛은 **같은 PATH** 여야 한다. 그래서 순서를 셋으로 고정한다:
      ① 선언의 `defaults.path` — 명시가 있으면 그것이 답이다(완전 환경 독립)
      ② **형제 유닛**에서 물려받기 — 한 번 제대로 구워진 값을 누가 굽든 지킨다
      ③ 호출자 환경 — 최초 생성 때만 여기까지 온다
    """
    # ① 선언 — load() 의 fail-loud 를 거치지 않고 얕게 읽는다(write 경로에서만 쓴다)
    try:
        with open(YML, encoding="utf-8") as f:
            decl = yaml.safe_load(f) or {}
        p = ((decl.get("defaults") or {}).get("path") or "").strip()
        if p:
            # `~` 는 launchd 가 확장하지 않는다(Issue451) — 여기서 전개해 머신별 홈을 살린다
            return ":".join(os.path.expanduser(x) for x in p.split(":") if x.strip())
    except Exception:
        pass

    # ② 형제 유닛 — 우리 prefix 로 이미 구워진 plist 중 하나의 PATH
    try:
        for fn in sorted(os.listdir(LA_DIR)):
            if not (fn.startswith(LABEL_PREFIX) and fn.endswith(".plist")):
                continue
            with open(os.path.join(LA_DIR, fn), "rb") as f:
                got = (plistlib.load(f).get("EnvironmentVariables") or {}).get("PATH")
            if got:
                return got
    except Exception:
        pass

    # ③ 호출자 — 최초 생성. 사람의 셸이면 온전하고, 아니면 다음 사람 write 가 바로잡는다
    return os.environ.get("PATH", "/usr/bin:/bin")


def _unit_env():
    """유닛에 박을 환경변수. schedule 자기 knob + 잡이 쓰는 aoa 3축.

    prj3#Issue553: 종전엔 SCHEDULE_* 만 넣었다. launchd 유닛에는 로그인 셸 환경이
      없으므로 `aoa-mq-tick` 의 HR 게이트가 `AOA_MEMORY_DIR` 을 못 받아 registry.db
      를 기본 경로에서 찾다 실패하고, fail-closed 라 post 셸 spawn 을 **영구히**
      거부했다(2026.09.06 실측 — 조용히 "컨펌 폼 fallback" 으로 빠져 자동 실행이
      한 번도 안 됐다). 구 실행 자리인 htm-server.plist 에는 이 키가 있었으므로
      Issue537 이관에서 딸려오지 못한 회귀다. 경로 3축 계약은 prj3#Issue458.
    """
    env = {
        "PATH": _resolve_unit_path(),
        "SCHEDULE_YML": YML,
        "SCHEDULE_LABEL_PREFIX": LABEL_PREFIX,
        "SCHEDULE_LEDGER": LEDGER,
    }
    # 설정된 것만 박는다 — 미설정 머신은 코드 기본값으로 떨어지는 편이 맞다.
    for k in ("AOA_MEMORY_DIR", "AOA_MQ_DIR", "AOA_MQ_CWD", "AOA_HOME"):
        v = os.environ.get(k)
        if v:
            env[k] = v
    return env


def label_of(event):
    return LABEL_PREFIX + event


def plist_path(event):
    return os.path.join(LA_DIR, label_of(event) + ".plist")


# ── 시각 필드 전개 ───────────────────────────────────────────────────────
def parse_every(v):
    """`5m`·`90s`·`2h` → 초. 숫자만 오면 초로 본다."""
    s = str(v).strip()
    m = re.fullmatch(r"(\d+)\s*([smh]?)", s)
    if not m:
        die("every 형식이 아니다: %r (5m·90s·2h)" % v)
    n, unit = int(m.group(1)), m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def parse_calendar(ev):
    """`at` + weekday/day/month → launchd StartCalendarInterval 배열.

    ⚠️ `day` 와 `weekday` 를 함께 주면 launchd 는 **OR** 로 해석한다("매월 1일 또는
    매주 월요일"). cron 과 같은 함정이며 AND 가 필요하면 잡 안에서 재확인해야 한다.
    """
    at = str(ev.get("at", "")).strip()
    if not at:
        die("calendar 이벤트에 at 이 없다: %r" % ev)
    if ":" not in at:
        die("at 은 HH:MM 형식이다: %r" % at)
    hh, mm = at.split(":", 1)

    hours = None if hh.strip() == "*" else [int(x) for x in hh.split(",")]
    minutes = None if mm.strip() == "*" else [int(x) for x in mm.split(",")]

    base = {}
    if "weekday" in ev:
        w = ev["weekday"]
        w = WEEKDAY[str(w).strip()[:3].lower()] if not isinstance(w, int) else w
        base["Weekday"] = w
    if "day" in ev:
        base["Day"] = int(ev["day"])
    if "month" in ev:
        base["Month"] = int(ev["month"])

    out = []
    for h in (hours if hours is not None else [None]):
        for mi in (minutes if minutes is not None else [None]):
            e = dict(base)
            if h is not None:
                e["Hour"] = h
            if mi is not None:
                e["Minute"] = mi
            out.append(e)
    return out


# ── 유닛 생성 ────────────────────────────────────────────────────────────
def build_plist(event, ev):
    """이벤트 하나 → plist dict.

    ⚠️ `ProgramArguments` 는 **잡 명령이 아니라 `dispatch <event>`** 다.
    그래야 조건 판정·다중 바인딩·ledger 기록이 시간 이벤트에도 똑같이 걸린다.

    ⚠️ PATH 를 생성 시점 값으로 박는다 — launchd 프로세스 PATH 에는 nvm 이 없어
    `claude`·`openclaw` 같은 node shebang CLI 가 exit 127 로 죽는다(Issue505).
    """
    typ = ev.get("type")
    log_dir = os.path.join(ROOT, "data", "schedule", "log")
    d = {
        "Label": label_of(event),
        "ProgramArguments": ["/bin/bash", os.path.join(ROOT, "hooks", "schedule.sh"),
                             "dispatch", event],
        "RunAtLoad": False,
        "ProcessType": "Background",
        # prj3#Issue577: 잡이 띄운 자식을 launchd 가 거두지 않게 한다.
        #   기본 동작은 **메인 프로세스 종료 시 남은 자식 SIGKILL** 이다. `nohup` 은
        #   SIGHUP 만 막으므로 소용없다. aoa-mq-tick 이 `nohup … &` 로 띄우는 post 잡이
        #   이것 때문에 간헐 소실됐다 — 자식이 tick 종료 **전에** 끝나면 살고 아니면
        #   죽는 **경합**이라, 같은 경로가 어떤 날은 되고 어떤 날은 안 됐다
        #   (2026-09-07 실측: tick 4s 회차는 자식이 exec.log·ledger 양쪽에 0건).
        "AbandonProcessGroup": True,
        "StandardOutPath": os.path.join(log_dir, "dispatch-%s.out" % event),
        "StandardErrorPath": os.path.join(log_dir, "dispatch-%s.err" % event),
        # ⚠️ knob 을 **생성 시점 값으로 박는다.** 유닛이 기본 경로를 추측하게 두면
        #    테스트 유닛이 실제 선언을 읽고(2026.09.05 T2 실측 rc=1), 배포 머신에서는
        #    경로 가정이 틀려 통째로 미기동한다(fg1 2026.08.30 — 이 설계의 출발점).
        "EnvironmentVariables": _unit_env(),
    }
    if typ == "timer":
        d["StartInterval"] = parse_every(ev.get("every"))
    elif typ == "calendar":
        cal = parse_calendar(ev)
        d["StartCalendarInterval"] = cal[0] if len(cal) == 1 else cal
    else:
        die("유닛으로 컴파일할 수 없는 타입이다: %s (%s)" % (typ, event))
    return d


def compiled_events(events):
    """유닛으로 굽는 것만. state·probe·external 은 신호원이 직접 dispatch 한다."""
    return {k: v for k, v in events.items() if v.get("type") in ("timer", "calendar")}


# ── 서브커맨드 ───────────────────────────────────────────────────────────
def cmd_path(argv):
    events, _, _ = load()
    ev = argv[0]
    if ev not in events:
        die("선언에 없는 이벤트: %s" % ev)
    if ev not in compiled_events(events):
        die("유닛이 없는 이벤트다(type=%s) — 신호원이 직접 dispatch 한다" % events[ev].get("type"))
    print(plist_path(ev))


def cmd_show(argv):
    events, _, _ = load()
    ev = argv[0]
    if ev not in events:
        die("선언에 없는 이벤트: %s" % ev)
    if ev not in compiled_events(events):
        die("유닛이 없는 이벤트다(type=%s) — 신호원이 직접 dispatch 한다" % events[ev].get("type"))
    sys.stdout.write(plistlib.dumps(build_plist(ev, events[ev])).decode("utf-8"))


# ── write ───────────────────────────────────────────────────────────────
def unit_text(event, ev):
    return plistlib.dumps(build_plist(event, ev))


def assert_no_tilde(event, blob):
    """유닛에 `~`·`$HOME` 이 남았으면 **굽지 않는다**.

    launchd 는 env 를 확장하지 않으므로 남은 채 등재되면 실행 시점에 조용히
    실패한다. 실패를 늦게 아는 것보다 아예 만들지 않는 편이 낫다(Issue451).
    """
    text = blob.decode("utf-8")
    for pat in ("$HOME", "<string>~"):
        if pat in text:
            die("유닛에 %s 가 남았다: %s — 경로 전개 실패" % (pat, event))


def launchctl(*args):
    import subprocess
    r = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def cmd_write(argv):
    events, _, _ = load()
    only = set(argv) if argv else None
    targets = compiled_events(events)
    if only:
        unknown = only - set(targets)
        if unknown:
            die("유닛 대상이 아닌 이벤트: %s" % ", ".join(sorted(unknown)))
        targets = {k: v for k, v in targets.items() if k in only}

    if backend_name() != "launchd":
        die("현재 백엔드는 %s — systemd 생성기는 미구현이다(Issue537 범위 밖)" % backend_name())

    os.makedirs(LA_DIR, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "data", "schedule", "log"), exist_ok=True)
    wrote = skipped = 0
    for ev_name in sorted(targets):
        blob = unit_text(ev_name, targets[ev_name])
        assert_no_tilde(ev_name, blob)
        path = plist_path(ev_name)
        old = None
        if os.path.exists(path):
            with open(path, "rb") as f:
                old = f.read()
        label = label_of(ev_name)
        loaded = launchctl("print", "gui/%d/%s" % (os.getuid(), label))[0] == 0
        if old == blob and loaded:
            skipped += 1
            print("  = %s (변경 없음)" % label)
            continue
        with open(path, "wb") as f:
            f.write(blob)
        # 재등재 — bootout 은 멱등이라 실패를 무시해도 된다(2026.09.05 실측)
        launchctl("bootout", "gui/%d/%s" % (os.getuid(), label))
        rc, out = launchctl("bootstrap", "gui/%d" % os.getuid(), path)
        if rc != 0:
            die("등재 실패 %s: rc=%d %s" % (label, rc, out))
        wrote += 1
        print("  + %s" % label)
    print("write: %d 생성·등재 · %d 변경 없음" % (wrote, skipped))


# ── check ───────────────────────────────────────────────────────────────
def cmd_check(argv):
    """선언 ↔ 실제의 drift 를 **fail-loud** 로 알린다.

    ⚠️ 등재 대조에서 빠지는 것과 검증에서 빠지는 것은 다르다. state·probe·
    external 은 유닛이 없지만 `raised_by` 배선은 반드시 확인한다 — 그러지 않으면
    "선언만 있고 아무도 부르지 않는 이벤트" 가 조용히 생긴다.
    """
    events, jobs, bindings = load()
    bad = []

    # ① timer·calendar — 등재 대조
    for ev_name, ev in sorted(compiled_events(events).items()):
        label = label_of(ev_name)
        rc, _ = launchctl("print", "gui/%d/%s" % (os.getuid(), label))
        if rc != 0:
            bad.append("%s: 미등재 (launchctl 에 %s 없음)" % (ev_name, label))
            continue
        path = plist_path(ev_name)
        if not os.path.exists(path):
            bad.append("%s: plist 파일 없음 — %s" % (ev_name, path))
            continue
        with open(path, "rb") as f:
            if f.read() != unit_text(ev_name, ev):
                bad.append("%s: plist 내용이 선언과 다르다 — write 재실행 필요" % ev_name)

    # ② state·probe·external — raised_by 배선
    for ev_name, ev in sorted(events.items()):
        typ = ev.get("type")
        if typ in ("timer", "calendar"):
            continue
        rb = ev.get("raised_by")
        if not rb:
            bad.append("%s: type=%s 인데 raised_by 가 없다 — 아무도 올리지 않는 이벤트다" % (ev_name, typ))
            continue
        if typ == "probe":
            if rb not in jobs:
                bad.append("%s: raised_by=%s 가 jobs 에 없다" % (ev_name, rb))
            elif rb not in {b["job"] for b in bindings}:
                bad.append("%s: probe 잡 %s 가 어떤 바인딩에도 없다 — 영원히 안 돈다" % (ev_name, rb))
        else:
            f = expand(rb)
            if not os.path.exists(f):
                bad.append("%s: raised_by 파일 없음 — %s" % (ev_name, f))
            else:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    if ("dispatch %s" % ev_name) not in fh.read():
                        bad.append("%s: %s 에 `dispatch %s` 가 없다 — 배선 누락" % (ev_name, rb, ev_name))

    # ③ 관할 밖 유닛 — 선언에 없는데 우리 prefix 로 등재된 것
    rc, out = launchctl("list")
    if rc == 0:
        declared = {label_of(e) for e in compiled_events(events)}
        for line in out.splitlines():
            parts = line.split("\t")
            lbl = parts[-1] if parts else ""
            if lbl.startswith(LABEL_PREFIX) and lbl not in declared:
                bad.append("%s: 선언에 없는데 등재돼 있다 — 고아 유닛" % lbl)

    if bad:
        print("check: %d 건 불일치" % len(bad))
        for b in bad:
            print("  ❌ %s" % b)
        sys.exit(1)
    n_c = len(compiled_events(events))
    print("check: OK — 유닛 %d · 비유닛 이벤트 %d · 잡 %d · 바인딩 %d"
          % (n_c, len(events) - n_c, len(jobs), len(bindings)))


def backend_name():
    import platform
    sysname = platform.system()
    if sysname == "Darwin":
        return "launchd"
    if sysname == "Linux":
        import shutil
        return "systemd" if shutil.which("systemctl") else "none"
    return "none"


# ── 조건 판정 ────────────────────────────────────────────────────────────
#   조건은 **바인딩의 속성**이라 여기서 판정한다. 래퍼에 넘기면 잡과 바인딩이 다시 붙는다.
#   ⚠️ `state` 이벤트가 유실돼도 조건은 정확하다 — 이벤트는 즉시성, 조건은 정확성을 담당한다.
CONDITIONS = {
    "state.sleep.global": lambda: os.path.exists(os.path.join(HOME, ".claude", ".sleep-mode-active")),
    "state.sleep.any": lambda: (
        os.path.exists(os.path.join(HOME, ".claude", ".sleep-mode-active"))
        or bool(os.path.isdir(os.path.join(HOME, ".claude", ".sleep-state"))
                and os.listdir(os.path.join(HOME, ".claude", ".sleep-state")))
    ),
}


def eval_cond(expr):
    fn = CONDITIONS.get(expr)
    if fn is None:
        die("알 수 없는 조건: %s (쓸 수 있는 것: %s)" % (expr, ", ".join(sorted(CONDITIONS))))
    return bool(fn())


def ledger_write(event, job, rc, extra=""):
    import datetime
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write("%s\t%s\t%s\t%s\t%s\n"
                % (datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), event, job, rc, extra))


# ── dispatch ─────────────────────────────────────────────────────────────
def _run_binding(ev, b, jobs, runner):
    """바인딩 하나를 조건 판정 후 래퍼에 넘긴다."""
    import subprocess
    job_name = b["job"]
    job = jobs[job_name]

    # 조건 — 차단도 기록한다. 아무 줄도 안 남기면 침묵과 구분되지 않는다
    blocked = None
    if "unless" in b and eval_cond(b["unless"]):
        blocked = "unless=%s" % b["unless"]
    elif "when" in b and not eval_cond(b["when"]):
        blocked = "when=%s" % b["when"]
    if blocked:
        ledger_write(ev, job_name, "rc=skip", blocked)
        print("  skip %s (%s)" % (job_name, blocked))
        return

    run = str(job.get("run", ""))
    if "{arg}" in run:
        run = run.replace("{arg}", str(b.get("arg", "")))

    cmd = [runner, "--event", ev, "--job", job_name, "--run", run]
    if job.get("lock"):
        cmd += ["--lock", str(job["lock"])]
    if job.get("timeout"):
        cmd += ["--timeout", str(job["timeout"])]
    if job.get("ok_rc"):
        cmd += ["--ok-rc", ",".join(str(x) for x in job["ok_rc"])]
    if job.get("log"):
        cmd += ["--log", expand(str(job["log"]))]
    if job.get("cwd"):
        cmd += ["--cwd", expand(str(job["cwd"]))]

    env = dict(os.environ, SCHEDULE_LEDGER=LEDGER)
    r = subprocess.run(["/bin/bash", *cmd], env=env)
    if r.returncode != 0:
        print("  ⚠️ 래퍼 자체가 실패했다 %s (rc=%d)" % (job_name, r.returncode))


def cmd_dispatch(argv):
    """신호원이 부르는 유일한 문.

    두 형태가 있다:
      dispatch <event>              — 선언된 바인딩을 따른다 (반복·상태·신호 이벤트)
      dispatch --job <잡> [--arg V] — 잡을 직접 지목한다 (일회성 예약, Issue540)

    ## 왜 `--job` 이 따로 있나
      일회성 예약(aoa-mq `--due`)을 `type: external` 이벤트로 표현하려 했으나
      **일회성인데 선언 파일에 영구히 남는 모순**이 생겼다 — 한 번 쓰고 나면 `check` 가
      "부르는 이 없는 이벤트" 로 잡거나, 남겨두면 선언이 로그가 된다.

      해소: **일회성은 이벤트가 아니다.** 이벤트는 *반복되거나 상태가 전이하는 것*이고,
      일회성 예약은 **큐가 소유한 데이터**다(crontab 과 `at` 의 경계). 큐는 선언된 잡을
      지목할 뿐이며, 잡이 `jobs:` 에 있어야 한다는 제약이 그대로 남아
      "선언에 있는 것만 실행" 보증은 유지된다.

    한 이벤트에 여러 바인딩이 걸리면 **선언 순서대로 순차** 실행하고, 하나가 실패해도
    나머지를 계속한다(격리). 병렬로 하면 실패 원인이 서로 오염되고 ledger 순서가 흔들린다.
    """
    events, jobs, bindings = load()
    runner = os.path.join(ROOT, "hooks", "schedule-run.sh")

    # ── 잡 직접 지목 (일회성) ──
    if argv and argv[0] == "--job":
        opts = {}
        i = 0
        while i < len(argv):
            if argv[i] in ("--job", "--arg", "--event") and i + 1 < len(argv):
                opts[argv[i][2:]] = argv[i + 1]
                i += 2
            else:
                die("dispatch --job <잡> [--arg <값>] [--event <라벨>] — 알 수 없는 인자: %s" % argv[i])
        job_name = opts.get("job")
        if job_name not in jobs:
            die("선언에 없는 잡: %s — `jobs:` 에 있는 것만 실행할 수 있다" % job_name)
        label = opts.get("event", "oneshot")
        b = {"event": label, "job": job_name}
        if "arg" in opts:
            b["arg"] = opts["arg"]
        _run_binding(label, b, jobs, runner)
        return

    ev = argv[0]
    if ev not in events:
        die("선언에 없는 이벤트: %s" % ev)

    matched = [b for b in bindings if b["event"] == ev]
    if not matched:
        die("이벤트에 걸린 바인딩이 없다: %s" % ev)

    runner = os.path.join(ROOT, "hooks", "schedule-run.sh")
    for b in matched:
        _run_binding(ev, b, jobs, runner)


# ── status ───────────────────────────────────────────────────────────────
def next_fire(ev):
    """다음 발화 예정 시각 — **선언에서 계산한다.**

    launchd 도 cron 도 이 값을 주지 않는다(`systemctl list-timers` 의 NEXT 같은 것이
    없다). OS 상태가 아니라 선언의 해석이므로 `check` 통과 후에만 신뢰할 수 있다.
    """
    import datetime
    now = datetime.datetime.now()
    typ = ev.get("type")
    if typ == "timer":
        return "+%ds 이내" % parse_every(ev.get("every"))
    if typ == "calendar":
        cands = []
        for c in parse_calendar(ev):
            for dd in range(0, 8):
                d = now + datetime.timedelta(days=dd)
                if "Weekday" in c and ((d.weekday() + 1) % 7) != c["Weekday"]:
                    continue
                if "Day" in c and d.day != c["Day"]:
                    continue
                if "Month" in c and d.month != c["Month"]:
                    continue
                for h in ([c["Hour"]] if "Hour" in c else range(24)):
                    for mi in ([c["Minute"]] if "Minute" in c else range(60)):
                        t = d.replace(hour=h, minute=mi, second=0, microsecond=0)
                        if t > now:
                            cands.append(t)
                            break
                    if cands:
                        break
                if cands:
                    break
        return min(cands).strftime("%m-%d %H:%M") if cands else "?"
    return "신호원 의존"


def _ledger_rows(limit=None):
    """ledger.tsv 를 dict 리스트로. 형식: ts \t event \t job \t rc=N \t detail"""
    rows = []
    if not os.path.exists(LEDGER):
        return rows
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 4:
                continue
            rows.append({"ts": p[0], "event": p[1], "job": p[2],
                         "rc": p[3].replace("rc=", ""),
                         "detail": p[4] if len(p) > 4 else ""})
    return rows[-limit:] if limit else rows


def cmd_status_json(argv):
    """선언 3종 + 실행 실적을 JSON 으로. hub `/schedule-data` 가 소비한다 (prj3#Issue570).

    🔴 파싱은 여기 한 곳이다 — hub 가 schedule.yml 을 따로 읽으면 판정이 두 벌로 갈린다.
       hub 는 이 출력을 렌더만 한다(prj1 → prj3 단방향).
    """
    import json
    limit = 30
    for i, a in enumerate(argv):
        if a == "--runs" and i + 1 < len(argv):
            limit = int(argv[i + 1])
    out = {"ok": True, "error": None, "ts": int(time.time()),
           "yml": YML, "user_yml": USER_YML, "ledger": LEDGER,
           "events": [], "jobs": [], "bindings": [], "runs": []}
    try:
        events, jobs, bindings, src = load(with_source=True)
    except SystemExit as e:          # load() 는 die() 로 빠진다 — 화면에 사유를 올린다
        out["ok"] = False
        out["error"] = "선언 로드 실패: %s" % e
        print(json.dumps(out, ensure_ascii=False))
        return

    rows = _ledger_rows()
    last = {}
    for r in rows:                   # 잡별 최근 1건
        last[r["job"]] = r

    for name in sorted(events):
        ev = events[name]
        typ = ev.get("type", "?")
        unit = loaded = None
        if typ in ("timer", "calendar"):
            unit = label_of(name)
            rc, txt = launchctl("print", "gui/%d/%s" % (os.getuid(), unit))
            loaded = (rc == 0)
            m = re.search(r"runs = (\d+)", txt) if rc == 0 else None
            runs = int(m.group(1)) if m else None
        else:
            runs = None
        spec = ev.get("every") or ev.get("at") or ev.get("raised_by") or ""
        out["events"].append({
            "name": name, "type": typ, "spec": spec, "unit": unit,
            "loaded": loaded, "runs": runs, "next": next_fire(ev),
            "source": src["events"].get(name, "system"),
            "jobs": [b["job"] for b in bindings if b["event"] == name],
        })

    bound = {b["job"] for b in bindings}
    for name in sorted(jobs):
        j = jobs[name] if isinstance(jobs[name], dict) else {"run": jobs[name]}
        out["jobs"].append({
            "name": name, "run": j.get("run", ""), "lock": j.get("lock"),
            "timeout": j.get("timeout"),
            "oneshot": j.get("oneshot") in (True, "true", "True"),
            "cwd": j.get("cwd"), "log": j.get("log"),
            "source": src["jobs"].get(name, "system"),
            "bound": name in bound, "last": last.get(name),
        })

    for i, b in enumerate(bindings):
        out["bindings"].append({"event": b["event"], "job": b["job"],
                                "arg": b.get("arg"), "unless": b.get("unless"),
                                "source": src["bindings"][i]})

    out["runs"] = list(reversed(rows[-limit:]))   # 최신 먼저
    print(json.dumps(out, ensure_ascii=False))


def cmd_status(argv):
    if "--json" in argv:
        return cmd_status_json(argv)
    events, jobs, bindings = load()
    last = {}
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 4:
                    last[p[2]] = (p[0], p[3])

    print("%-14s %-9s %-10s %-16s %s" % ("EVENT", "TYPE", "OS", "NEXT", "LAST RUN (job)"))
    for ev_name in sorted(events):
        ev = events[ev_name]
        typ = ev.get("type", "?")
        if typ in ("timer", "calendar"):
            rc, out = launchctl("print", "gui/%d/%s" % (os.getuid(), label_of(ev_name)))
            if rc != 0:
                os_col = "미등재"
            else:
                m = re.search(r"runs = (\d+)", out)
                os_col = "runs=%s" % (m.group(1) if m else "?")
        else:
            os_col = "-"
        js = [b["job"] for b in bindings if b["event"] == ev_name]
        shown = []
        for j in js:
            t, rcv = last.get(j, ("-", "-"))
            shown.append("%s %s %s" % (j, t[5:16] if t != "-" else "-", rcv))
        print("%-14s %-9s %-10s %-16s %s" % (ev_name, typ, os_col, next_fire(ev),
                                             " | ".join(shown) if shown else "-"))


# ── user — UI 가 쓰는 선언의 CRUD (prj3#Issue579) ────────────────────────
#   ⚠️ 여기가 **쓰기의 유일한 지점**이다. hub 는 YAML 을 열지 않고 이 명령을 부른다.
#      hub 가 직접 쓰면 이름 충돌·고아 판정이 CLI 와 갈려 두 벌이 된다.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _user_decl():
    """user.yml 원본을 3절로. 없으면 빈 구조 — 파일을 만들지는 않는다.

    시각 필드는 `_Quoted` 로 되살린다 — 재기록 때 따옴표가 빠지면 다음 로드에서
    60진수로 삼켜진다(위 `_Quoted` 주석).
    """
    if not USER_YML:
        die("SCHEDULE_USER_YML 미설정 — schedule.sh 를 통해 실행한다")
    ev, jobs, bindings = _read_decl(USER_YML, required=False)
    for e in ev.values():
        if isinstance(e, dict):
            for k in ("at", "every"):
                if k in e:
                    e[k] = _Quoted(e[k])
    return ev, jobs, bindings


def _event_name_for(kind, spec):
    """시각 → 이벤트 이름. 선언 파일에 이미 쓰던 규칙 그대로다(`t-5m`·`t-0703`)."""
    if kind == "every":
        return "t-%s" % str(spec).strip()
    hh, mm = str(spec).split(":", 1)
    return "t-%02d%02d" % (int(hh), int(mm))


def _find_event(events, kind, spec):
    """같은 시각의 이벤트가 이미 있으면 그 이름을 준다 — 유닛을 늘리지 않는다."""
    if kind == "every":
        want = parse_every(spec)
        for name, ev in events.items():
            if ev.get("type") == "timer" and "every" in ev:
                try:
                    if parse_every(ev["every"]) == want:
                        return name
                except SystemExit:
                    continue
        return None
    hh, mm = str(spec).split(":", 1)
    want = "%02d:%02d" % (int(hh), int(mm))
    for name, ev in events.items():
        if ev.get("type") == "calendar" and str(ev.get("at", "")).strip() == want:
            return name
    return None


class _Quoted(str):
    """dump 시 **반드시 따옴표**로 나가는 문자열.

    ⚠️ YAML 1.1 은 `7:03` 을 60진수로 읽어 **423** 으로 만든다(2026.09.08 실측).
       `02:00` 은 앞자리 0 덕에 우연히 문자열로 남지만 그 우연에 기대지 않는다.
       `on:` 불리언 함정과 같은 계열이며, 여기서 막지 않으면 저장한 시각이
       조용히 정수로 바뀌어 `parse_calendar` 가 뒤늦게 죽는다.
    """


def _quoted_repr(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


class _UserDumper(yaml.SafeDumper):
    pass


_UserDumper.add_representer(_Quoted, _quoted_repr)


def _dump_user(events, jobs, bindings, path):
    """**원자적으로** 쓴다 — tmp 에 굽고 rename. 중간 실패가 파일을 깨지 않는다.

    ⚠️ 주석은 여기 없다. 주석이 본체인 선언은 `schedule.yml` 이고 그 파일은
       기계가 손대지 않는다. 이 파일은 기계 소유이므로 dump 로 충분하다.
    """
    doc = {"events": events, "jobs": jobs, "bindings": bindings}
    head = ("# schedule.user.yml — **UI 가 쓰는 선언** (prj3#Issue579)\n"
            "#\n"
            "# 🤖 이 파일은 기계가 생성한다. 손으로 고쳐도 되지만 주석은 다음 쓰기에 사라진다.\n"
            "#    설계 결정·근거는 옆 `schedule.yml` 이 소유한다 — 그쪽은 기계가 손대지 않는다.\n"
            "#\n"
            "#   추가:  bash ~/.claude/hooks/schedule.sh user add --name N --run CMD --at 02:00\n"
            "#   제거:  bash ~/.claude/hooks/schedule.sh user remove --name N\n"
            "#   목록:  bash ~/.claude/hooks/schedule.sh user list\n\n")
    body = yaml.dump(doc, Dumper=_UserDumper, allow_unicode=True,
                     sort_keys=False, default_flow_style=False)
    tmp = path + ".tmp.%d" % os.getpid()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(head + body)
    os.replace(tmp, path)


def _verify_or_revert(path, backup):
    """쓴 뒤 merge 검증. 실패하면 **되돌리고** 사유를 올린다.

    깨진 선언을 남기면 `check` 가 계속 붉고 launchd 반영도 막힌다. 부분 성공보다
    아무 일도 없었던 편이 낫다.
    """
    import subprocess
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "check-load"],
                       capture_output=True, text=True, env=dict(
                           os.environ, SCHEDULE_YML=YML, SCHEDULE_USER_YML=USER_YML,
                           SCHEDULE_LABEL_PREFIX=LABEL_PREFIX, SCHEDULE_LEDGER=LEDGER,
                           SCHEDULE_ROOT=ROOT))
    if r.returncode == 0:
        return
    if backup is None:
        if os.path.exists(path):
            os.unlink(path)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(backup)
    die("검증 실패로 되돌렸다 — %s" % (r.stdout + r.stderr).strip())


# 반복 지정이 되는 키 — 잡 하나가 여러 시각에 걸리는 것이 정상이기 때문이다.
#   `daily-digest` 가 그 실례다: t-0703(morning) · t-2303(bedtime) (prj3#Issue587)
MULTI_KEYS = {"at", "every"}


def _kv(argv):
    """`--k v` 목록을 dict 로. 플래그(`--manual`·`--no-write`)는 True.

    `--at`·`--every` 는 **여러 번 줄 수 있고** 리스트로 모인다.
    """
    flags = {"--manual", "--no-write"}
    out, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if not a.startswith("--"):
            die("알 수 없는 인자: %s" % a)
        if a in flags:
            out[a[2:].replace("-", "_")] = True   # `--no-write` → `no_write`
            i += 1
            continue
        if i + 1 >= len(argv):
            die("%s 에 값이 없다" % a)
        k = a[2:].replace("-", "_")
        if k in MULTI_KEYS:
            out.setdefault(k, []).append(argv[i + 1])
        else:
            out[k] = argv[i + 1]
        i += 2
    return out


def _parse_when(kind, raw):
    """`07:03=morning` → (spec, arg). `=` 가 없으면 arg 없음.

    시각마다 인자가 다른 잡이 있다(아침 브리핑 vs 취침 브리핑). 바인딩의 `arg` 는
    원래 그것을 위한 자리이므로, 시각과 함께 받는 편이 폼 하나로 끝난다.
    """
    spec, _, arg = str(raw).partition("=")
    spec = spec.strip()
    if kind == "every":
        secs = parse_every(spec)
        if secs < 60:
            die("--every 는 60초 이상이다: %s (launchd 가 과도한 재기동을 막는다)" % spec)
        return spec, (arg.strip() or None)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", spec)
    if not m:
        die("--at 은 HH:MM 형식이다: %s" % spec)
    if not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
        die("--at 범위를 벗어났다: %s (00:00~23:59)" % spec)
    return "%02d:%02d" % (int(m.group(1)), int(m.group(2))), (arg.strip() or None)


def _post_write(changed_units):
    """선언이 바뀐 뒤 launchd 에 반영. 새 유닛이 없으면 아무것도 하지 않는다."""
    if not changed_units:
        return
    if backend_name() != "launchd":
        print("  (백엔드가 launchd 가 아니다 — 등재 생략)")
        return
    cmd_write([])


def cmd_user(argv):
    if not argv:
        die("user add|remove|list — 서브커맨드가 필요하다")
    sub, rest = argv[0], argv[1:]

    if sub == "list":
        import json
        _, _, _, src = load(with_source=True)
        u_events, u_jobs, u_bindings = _user_decl()
        if "--json" in rest:
            print(json.dumps({"events": u_events, "jobs": u_jobs,
                              "bindings": u_bindings, "path": USER_YML},
                             ensure_ascii=False, default=str))
            return
        if not u_jobs:
            print("사용자 잡 없음 (%s)" % USER_YML)
            return
        print("%-20s %-10s %s" % ("JOB", "WHEN", "RUN"))
        for name in sorted(u_jobs):
            j = u_jobs[name] if isinstance(u_jobs[name], dict) else {"run": u_jobs[name]}
            evs = [b["event"] for b in u_bindings if b.get("job") == name]
            when = ",".join(evs) if evs else ("수동" if j.get("oneshot") else "-")
            print("%-20s %-10s %s" % (name, when, j.get("run", "")))
        return

    if sub == "add":
        o = _kv(rest)
        name, run = o.get("name"), o.get("run")
        if not name or not run:
            die("add 에는 --name 과 --run 이 필요하다")
        if not NAME_RE.match(name):
            die("잡 이름은 소문자·숫자·하이픈만 쓴다(40자 이내): %s" % name)
        if name.lower() in BOOL_KEYS:
            die("이름에 YAML 불리언 토큰을 쓸 수 없다: %s" % name)

        events, jobs, _, src = load(with_source=True)
        if name in jobs:
            owner = src["jobs"][name]
            die("이미 있는 잡이다: %s (%s 선언)%s" %
                (name, owner, " — 시스템 잡은 UI 로 바꿀 수 없다" if owner == "system" else ""))

        if o.get("manual") and (o.get("at") or o.get("every")):
            die("--manual 은 시각과 함께 줄 수 없다")
        if not o.get("manual") and not (o.get("at") or o.get("every")):
            die("실행시각이 없다 — --every 5m · --at 02:00 · --manual 중 하나를 준다")

        u_events, u_jobs, u_bindings = _user_decl()
        backup = open(USER_YML, encoding="utf-8").read() if os.path.exists(USER_YML) else None

        job = {"run": run}
        for k, cast in (("cwd", str), ("log", str), ("timeout", int), ("lock", str)):
            if o.get(k) is not None:
                job[k] = cast(o[k])
        made = []                            # 화면·로그에 무엇을 걸었는지 말해 준다
        new_event = False                    # 유닛을 새로 구워야 하는가
        if o.get("manual"):
            job["oneshot"] = True            # 고아 검사 예외 — 큐·버튼이 지목한다
        else:
            # 한 잡이 여러 시각에 걸리는 것이 정상이다(아침·취침 브리핑) — prj3#Issue587
            seen = set()
            for kind in ("every", "at"):
                for raw in (o.get(kind) or []):
                    spec, arg = _parse_when(kind, raw)
                    ev_name = _find_event(events, kind, spec)
                    if ev_name is None:      # 같은 시각이 없을 때만 새로 만든다
                        new_event = True
                        ev_name = _event_name_for(kind, spec)
                        if ev_name in events:
                            die("이벤트 이름이 이미 있다: %s" % ev_name)
                        if kind == "every":
                            u_events[ev_name] = {"type": "timer", "every": _Quoted(spec)}
                        else:
                            hh, mm = (int(x) for x in spec.split(":", 1))
                            u_events[ev_name] = {"type": "calendar",
                                                 "at": _Quoted("%02d:%02d" % (hh, mm))}
                        events = dict(events, **{ev_name: u_events[ev_name]})
                    if ev_name in seen:
                        die("같은 시각을 두 번 걸었다: %s (%s)" % (spec, ev_name))
                    seen.add(ev_name)
                    b = {"event": ev_name, "job": name}
                    if arg or o.get("arg"):
                        b["arg"] = arg or o["arg"]
                    u_bindings.append(b)
                    made.append(ev_name + ("(%s)" % b["arg"] if b.get("arg") else ""))

        u_jobs[name] = job
        _dump_user(u_events, u_jobs, u_bindings, USER_YML)
        _verify_or_revert(USER_YML, backup)
        print("user add: %s → %s" % (name, " + ".join(made) or "수동 실행(oneshot)"))
        if not o.get("no_write"):
            _post_write(new_event)           # 재사용이면 유닛이 이미 있다
        return

    if sub == "remove":
        o = _kv(rest)
        name = o.get("name")
        if not name:
            die("remove 에는 --name 이 필요하다")
        events, jobs, _, src = load(with_source=True)
        if name not in jobs:
            die("없는 잡이다: %s" % name)
        if src["jobs"][name] != "user":
            die("시스템 잡은 지울 수 없다: %s — `data/schedule.yml` 은 사람이 편집한다" % name)

        u_events, u_jobs, u_bindings = _user_decl()
        backup = open(USER_YML, encoding="utf-8").read() if os.path.exists(USER_YML) else None

        u_jobs.pop(name, None)
        u_bindings = [b for b in u_bindings if b.get("job") != name]

        # 고아가 된 **사용자** 이벤트만 치운다 — 시스템 이벤트는 다른 잡이 쓴다
        sys_events, _, sys_bindings = _read_decl(YML, required=True)
        still_used = {b["event"] for b in sys_bindings if isinstance(b, dict) and "event" in b}
        still_used |= {b["event"] for b in u_bindings if isinstance(b, dict)}
        dropped = [e for e in list(u_events) if e not in still_used]
        for e in dropped:
            u_events.pop(e, None)

        _dump_user(u_events, u_jobs, u_bindings, USER_YML)
        _verify_or_revert(USER_YML, backup)

        # 유닛 정리 — 선언에서 사라진 이벤트는 등재도 걷는다(고아 유닛 방지)
        if dropped and backend_name() == "launchd" and not o.get("no_write"):
            for e in dropped:
                launchctl("bootout", "gui/%d/%s" % (os.getuid(), label_of(e)))
                path = plist_path(e)
                if os.path.exists(path):
                    os.unlink(path)
        print("user remove: %s%s" % (name,
              " (이벤트 %s 도 정리)" % ", ".join(dropped) if dropped else ""))
        return

    die("알 수 없는 user 서브커맨드: %s (add|remove|list)" % sub)


def cmd_todo(name):
    die("`%s` 는 아직 구현되지 않았다 (Issue537 Phase 3)" % name)


def main():
    if not YML:
        die("SCHEDULE_YML 미설정 — schedule.sh 를 통해 실행한다")
    if len(sys.argv) < 2:
        die("서브커맨드가 없다")
    cmd, argv = sys.argv[1], sys.argv[2:]
    if cmd == "path":
        cmd_path(argv)
    elif cmd == "show":
        cmd_show(argv)
    elif cmd == "write":
        cmd_write(argv)
    elif cmd == "check":
        cmd_check(argv)
    elif cmd == "status":
        cmd_status(argv)
    elif cmd == "dispatch":
        cmd_dispatch(argv)
    elif cmd == "user":
        cmd_user(argv)
    elif cmd == "check-load":        # 내부 전용 — 쓰기 후 merge 검증(prj3#Issue579)
        load()
    else:
        die("알 수 없는 서브커맨드: %s" % cmd)


if __name__ == "__main__":
    main()
