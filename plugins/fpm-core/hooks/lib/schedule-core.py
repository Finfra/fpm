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
import shlex
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


# ── 잡 본체 — run 한 줄 | steps 목록 (prj3#Issue691) ─────────────────────
#   잡 = 스텝 목록이다. `run:` 한 줄은 sh 스텝 1개의 축약이며 그대로 유효하다.
STEP_KINDS = {
    "script": ("path",),     # bash <path> <args>  (실행 비트 있으면 직접)
    "scar":   ("cmd",),      # claude -p '<cmd>'   (cwd 기본 ~/.claude)
    "prompt": ("text",),     # claude -p '<자연어>' (cwd 기본 ~/.claude) — Issue698: 커맨드 없는 지시
    "job":    ("ref",),      # 같은 프로세스에서 _run_binding 재귀
    "sh":     ("run",),      # 기존 run: 과 동일
}
MAX_JOB_DEPTH = 3            # job 스텝 중첩 hop 상한

# schedule-run.sh 종료코드 계약 — 래퍼와 한 벌이다(hooks/schedule-run.sh 머리 주석)
RC_OK, RC_FAILED, RC_TIMEOUT, RC_BUSY, RC_SKIP = 0, 10, 11, 12, 13
RESULT_OF = {RC_OK: "ok", RC_FAILED: "failed", RC_TIMEOUT: "timeout",
             RC_BUSY: "lock-busy", RC_SKIP: "skip"}


def _job_dict(j):
    return j if isinstance(j, dict) else {"run": j}


def _job_steps(j):
    """잡 → 스텝 목록. `run:` 잡은 sh 스텝 1개로 정규화한다."""
    j = _job_dict(j)
    if isinstance(j.get("steps"), list):
        return [st for st in j["steps"] if isinstance(st, dict)]
    if "run" in j:
        return [{"kind": "sh", "run": j["run"]}]
    return []


def _result_globs(j):
    """잡의 `result:`(산출물 glob — 문자열 또는 목록) → 문자열 목록. 없으면 [] (prj3#Issue893)."""
    r = _job_dict(j).get("result")
    if r is None:
        return []
    return [r] if isinstance(r, str) else list(r)


def _result_latest(globs):
    """glob 들의 일치 파일 중 mtime 최신 1건 → {path, mtime}. 일치 0건이면 None.

    🔴 hub 가 glob 을 다시 풀지 않는다 — 판정 단일 지점은 여기다. 상대경로는 홈 기준.
    """
    import glob as _glob
    best = None
    for g in globs:
        pat = os.path.expanduser(g)
        if not os.path.isabs(pat):
            pat = os.path.join(HOME, pat)
        for f in _glob.glob(pat):
            try:
                if not os.path.isfile(f):
                    continue
                m = os.path.getmtime(f)
            except OSError:
                continue
            if best is None or m > best["mtime"]:
                best = {"path": f, "mtime": m}
    return best


def _is_paused(x):
    return isinstance(x, dict) and x.get("paused") in (True, "true", "True")


def _validate_jobs(jobs, src_jobs=None):
    """잡 본체 구조를 fail-loud 로 검증한다 — **존재 검증은 하지 않는다**.

    스크립트 경로·커맨드 실존은 등록 시점(`user job-add`)에 본다. 여기서 보면 스크립트
    하나가 지워졌을 때 **모든** dispatch 가 선언 로드에서 죽는다 — 잡 하나의 문제가
    시스템 전체 정지가 된다.
    """
    src_jobs = src_jobs or {}
    for name, j in jobs.items():
        j = _job_dict(j)
        has_run, has_steps = "run" in j, "steps" in j
        if has_run and has_steps:
            die("잡 `%s` 에 run 과 steps 가 함께 있다 — 한 잡의 정본은 하나다" % name)
        if not has_run and not has_steps:
            die("잡 `%s` 에 run 도 steps 도 없다" % name)
        if has_run and not str(j.get("run") or "").strip():
            die("잡 `%s` 의 run 이 비어 있다" % name)
        r = j.get("result")
        if r is not None and not (isinstance(r, str) and r.strip() or
                                  isinstance(r, list) and r and all(isinstance(g, str) and g.strip() for g in r)):
            die("잡 `%s` 의 result 는 glob 문자열 또는 비어 있지 않은 문자열 목록이다: %r" % (name, r))
        if j.get("on_error", "stop") not in ("stop", "continue"):
            die("잡 `%s` 의 on_error 는 stop|continue 다: %r" % (name, j.get("on_error")))
        if not has_steps:
            continue
        steps = j["steps"]
        if not isinstance(steps, list) or not steps:
            die("잡 `%s` 의 steps 는 비어 있지 않은 목록이어야 한다" % name)
        for n, st in enumerate(steps, 1):
            if not isinstance(st, dict):
                die("잡 `%s` 스텝 #%d 가 매핑이 아니다: %r" % (name, n, st))
            kind = st.get("kind")
            if kind not in STEP_KINDS:
                die("잡 `%s` 스텝 #%d 의 kind 는 %s 중 하나다: %r"
                    % (name, n, "|".join(sorted(STEP_KINDS)), kind))
            for f in STEP_KINDS[kind]:
                if not str(st.get(f) or "").strip():
                    die("잡 `%s` 스텝 #%d(%s) 에 `%s` 가 없다" % (name, n, kind, f))
            if kind == "scar" and not str(st["cmd"]).strip().startswith("/"):
                die("잡 `%s` 스텝 #%d(scar) 의 cmd 는 `/` 로 시작한다: %s" % (name, n, st["cmd"]))
            if kind == "job":
                ref = st["ref"]
                if ref not in jobs:
                    die("잡 `%s` 스텝 #%d 가 없는 잡을 지목한다: %s" % (name, n, ref))
                if src_jobs.get(name, "system") == "system" and src_jobs.get(ref) == "user":
                    die("시스템 잡 `%s` 가 사용자 잡을 지목한다: %s — 참조는 user → system 단방향이다"
                        % (name, ref))

    # 순환·깊이 — DFS. 순환이면 dispatch 가 무한 재귀로 돈다
    def dfs(n, path):
        if n in path:
            die("잡 스텝 순환: %s" % " → ".join(path + (n,)))
        if len(path) > MAX_JOB_DEPTH:
            die("잡 스텝 중첩이 %d 단을 넘는다: %s" % (MAX_JOB_DEPTH, " → ".join(path + (n,))))
        for st in _job_steps(jobs.get(n, {})):
            if st.get("kind") == "job":
                dfs(st["ref"], path + (n,))
    for name in jobs:
        dfs(name, ())


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

    # prj3#Issue878: `catchup: <창>` — calendar 이벤트 전용, 창은 parse_every 형식(6h·90m)
    for name, ev in events.items():
        if isinstance(ev, dict) and "catchup" in ev:
            if ev.get("type") != "calendar":
                die("catchup 은 calendar 이벤트에만 쓴다: %s (type=%s)" % (name, ev.get("type")))
            if not re.fullmatch(r"\d+\s*[smh]", str(ev["catchup"]).strip()):
                die("catchup 창 형식이 아니다: %s=%r (6h·90m 처럼 단위 필수)" % (name, ev["catchup"]))

    # 잡 본체 — run/steps 형식·순환·깊이 (prj3#Issue691)
    _validate_jobs(jobs, src["jobs"])

    # 고아 — 부르는 이 없는 잡, 아무 잡도 안 부르는 이벤트
    used_jobs = {b["job"] for b in bindings}
    used_events = {b["event"] for b in bindings}
    # prj3#Issue691: 스텝의 `kind: job` 참조도 «부르는 이» 다
    for jn, jv in jobs.items():
        used_jobs |= {st.get("ref") for st in _job_steps(jv) if st.get("kind") == "job"}
    for j in sorted(set(jobs) - used_jobs):
        # prj3#Issue691: **사용자 잡은 무바인딩이 정상**이다 — 잡 탭은 카탈로그이고
        #   스케줄·큐는 그것을 지목할 뿐이다. 시스템 선언의 고아 검사는 그대로 둔다.
        if src["jobs"].get(j) == "user":
            continue
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
    for k in CALLER_ENV_KEYS:
        v = os.environ.get(k)
        if v:
            env[k] = v
    return env


# 유닛 env 중 «호출자 셸 env» 에서 오는 키 — write 한 셸에만 있고 check 하는 쪽엔 없을 수 있다
CALLER_ENV_KEYS = ("AOA_MEMORY_DIR", "AOA_MQ_DIR", "AOA_MQ_CWD", "AOA_HOME")


def plist_equivalent(actual, expected):
    """설치본 plist(bytes)가 선언에서 컴파일한 plist(bytes)와 같은가.

    prj3#Issue775 후속: 종전엔 바이트 비교라, aoa env 가 빈 호출자(tdd/run.sh 의 상속
      차단·launchd·봇 세션)가 check 하면 기대본에 `AOA_*` 가 빠져 정상 설치본을 전부
      «plist 내용이 선언과 다르다» 로 오판했다. 호출자 env 에 **없는** 키는 설치본 값을
      판정하지 않는다 — 호출자에게 있는 키는 종전대로 값까지 대조한다.
    """
    if actual == expected:
        return True
    try:
        a = plistlib.loads(actual)
        e = plistlib.loads(expected)
    except Exception:
        return False
    ae = dict(a.get("EnvironmentVariables") or {})
    ee = dict(e.get("EnvironmentVariables") or {})
    for k in CALLER_ENV_KEYS:
        if k not in ee:
            ae.pop(k, None)
    a["EnvironmentVariables"] = ae
    e["EnvironmentVariables"] = ee
    return a == e


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

    # prj3#Issue691: weekday·day 는 **목록**도 받는다(`mon,wed,fri` · `1,15`).
    #   launchd 는 사전 배열로 OR 를 표현하므로 목록은 교차곱으로 펼친다.
    wdays = _calendar_list(ev, "weekday")
    days = _calendar_list(ev, "day")
    month = int(ev["month"]) if "month" in ev else None

    out = []
    for w in wdays:
        for dd in days:
            for h in (hours if hours is not None else [None]):
                for mi in (minutes if minutes is not None else [None]):
                    e = {}
                    if w is not None:
                        e["Weekday"] = w
                    if dd is not None:
                        e["Day"] = dd
                    if month is not None:
                        e["Month"] = month
                    if h is not None:
                        e["Hour"] = h
                    if mi is not None:
                        e["Minute"] = mi
                    out.append(e)
    return out


def _calendar_list(ev, key):
    """weekday·day 필드 → 정수 목록. 없으면 [None](와일드카드)."""
    if key not in ev:
        return [None]
    raw = ev[key]
    items = raw if isinstance(raw, list) else str(raw).split(",")
    out = []
    for x in items:
        if key == "weekday" and not isinstance(x, int):
            k = str(x).strip()[:3].lower()
            if k not in WEEKDAY:
                die("weekday 를 해석할 수 없다: %r (sun~sat)" % x)
            out.append(WEEKDAY[k])
        else:
            v = int(x)
            if key == "day" and not 1 <= v <= 31:
                die("day 는 1~31 이다: %r" % x)
            out.append(v)
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


# ── 발화 누락 판정 (prj3#Issue775) ──────────────────────────────────────
#   launchd `StartCalendarInterval` 은 **수면** 중 놓친 슬롯만 깨어날 때 보충한다(man
#   launchd.plist). **전원 꺼짐** 중 슬롯은 부팅 뒤 보충하지 않는다 — 발화가 없으니 ledger 에
#   한 줄도 안 남고, «실패» 조차 보이지 않았다(2026-09-22~27 daily-digest 8슬롯 누락 전건이
#   `last reboot`·`pmset` 의 전원 꺼짐 구간과 일치 — 실측). 그래서 **선언의 기대 슬롯**을
#   ledger 와 대조해 «발화 0» 을 드러낸다.
#
#   원인 분류 — ledger 자체가 가동 흔적(heartbeat)이다. 슬롯 앞 15분과 뒤 15분 **양쪽에**
#   다른 이벤트 줄이 있으면 머신이 켜져 있었는데 안 돈 것(`up` — 있어선 안 되는 일),
#   한쪽이라도 비면 꺼짐·수면(`off` — 판정 근거상 결함이 아님)이다.
MISS_HEARTBEAT_S = 15 * 60       # 가동 흔적 창 — t-5m 주기(300s)의 3배
MISS_SETTLE_S = 120              # 잡 timeout 뒤 ledger 기록까지의 여유
MISS_DEFAULT_TIMEOUT_S = 900     # timeout 미선언 잡의 판정 보류 시간
MISS_HOURS = 48                  # 기본 관찰 창 — 하루 2회 잡이면 4슬롯


def _opt(argv, name, default=None):
    """`--name 값` 하나를 꺼낸다. 없으면 default."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
    return default


def _parse_now(argv):
    """`--now YYYY-MM-DDTHH:MM[:SS]` — 판정 기준 시각(테스트·사후 재현용). 없으면 현재."""
    import datetime
    raw = _opt(argv, "--now")
    if not raw:
        return datetime.datetime.now()
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError:
        die("--now 는 ISO 시각이다(ex 2026-09-28T16:00): %s" % raw)


def _calendar_slots(ev, start, end):
    """(start, end] 사이의 기대 발화 시각 — **선언의 해석**이다(next_fire 와 같은 축)."""
    import datetime
    out = set()
    specs = parse_calendar(ev)
    d = start.date()
    while d <= end.date():
        for c in specs:
            if "Weekday" in c and ((d.weekday() + 1) % 7) != c["Weekday"] % 7:
                continue
            if "Day" in c and d.day != c["Day"]:
                continue
            if "Month" in c and d.month != c["Month"]:
                continue
            for h in ([c["Hour"]] if "Hour" in c else range(24)):
                for mi in ([c["Minute"]] if "Minute" in c else range(60)):
                    t = datetime.datetime.combine(d, datetime.time(h, mi))
                    if start < t <= end:
                        out.add(t)
        d += datetime.timedelta(days=1)
    return sorted(out)


def missed_slots(events, jobs, bindings, now, hours=MISS_HOURS):
    """calendar 이벤트의 기대 슬롯 ↔ ledger 대조 → {expected, fired, missed:[…]}.

    기대 슬롯에서 빼는 것 — 기대할 근거가 없는 시각이다:
      · 활성 바인딩(바인딩·잡 모두 멈춤 아님)이 없는 이벤트
      · ledger 첫 줄 이전(기록이 없던 때) · 유닛(plist) 파일 mtime 이전(설치 전)
      · 그 이벤트·잡의 마지막 `rc=resume` 이전(멈춰 있던 때)
      · timeout+여유가 안 지난 슬롯(아직 도는 중일 수 있다 — ledger 는 **종료 시** 쓴다)
    발화 판정 — [슬롯, 다음 슬롯) 안에 그 이벤트 줄이 하나라도 있으면 발화다. 수면 보충으로
      늦게 돈 것도, lock-busy·unless 차단도 «디스패처는 불렸다» 이므로 발화다.
    """
    import datetime
    stamps = []
    for r in _ledger_rows():
        try:
            t = datetime.datetime.fromisoformat(r["ts"])
        except ValueError:
            continue
        stamps.append((t, r["event"], r["job"], r["rc"]))
    stamps.sort(key=lambda x: x[0])
    res = {"hours": hours, "now": now.isoformat(timespec="seconds"),
           "expected": 0, "fired": 0, "missed": []}
    if not stamps:
        return res                       # 기록 자체가 없다 — 판정 근거 없음
    runs = [s for s in stamps if s[3] not in ("pause", "resume")]   # 전환 줄은 실행이 아니다
    ledger_start = stamps[0][0]
    win = now - datetime.timedelta(hours=hours)

    for ev_name, ev in sorted(events.items()):
        if ev.get("type") != "calendar":
            continue
        active = [b for b in bindings if b["event"] == ev_name
                  and not _is_paused(b) and not _is_paused(_job_dict(jobs[b["job"]]))]
        if not active:
            continue
        job_names = {b["job"] for b in active}
        since = max(win, ledger_start)
        pp = plist_path(ev_name)
        if os.path.exists(pp):
            since = max(since, datetime.datetime.fromtimestamp(os.path.getmtime(pp)))
        for t, e, j, rc in stamps:
            if rc == "resume" and j in job_names and e in (ev_name, "-"):
                since = max(since, t)
        tmos = [int(_job_dict(jobs[j]).get("timeout") or MISS_DEFAULT_TIMEOUT_S) for j in job_names]
        settle = datetime.timedelta(seconds=max(tmos) + MISS_SETTLE_S)

        slots = _calendar_slots(ev, since, now)
        ev_runs = [t for t, e, _, _ in runs if e == ev_name]
        hb = datetime.timedelta(seconds=MISS_HEARTBEAT_S)
        for i, s in enumerate(slots):
            if s > now - settle:
                break
            res["expected"] += 1
            end = slots[i + 1] if i + 1 < len(slots) else now
            if any(s <= t < end for t in ev_runs):
                res["fired"] += 1
                continue
            before = any(s - hb <= t < s for t, e, _, _ in runs if e != ev_name)
            after = any(s < t <= s + hb for t, e, _, _ in runs if e != ev_name)
            res["missed"].append({
                "event": ev_name, "slot": s.isoformat(timespec="seconds"),
                "cause": "up" if (before and after) else "off",
                "jobs": sorted(job_names)})
    return res


MISS_TEXT = {"up": "가동 중 미발화(launchd 가 안 불렀다)",
             "off": "가동 흔적 없음(전원 꺼짐·수면 추정 — 부팅 뒤 보충 없음)"}


def _miss_line(m):
    mark = "❌" if m["cause"] == "up" else "⚠️"
    return "%s %s %s — %s (%s)" % (mark, m["event"], m["slot"][5:16].replace("T", " "),
                                  MISS_TEXT[m["cause"]], ",".join(m["jobs"]))


CATCHUP_SUFFIX = "~catchup"      # ledger 이벤트 라벨 — 정규 발화(이벤트명)와 구분해 missed 기록을 지우지 않는다


def cmd_catchup(argv):
    """`catchup [--now ISO] [--dry]` — 전원 꺼짐 중 놓친 슬롯을 `catchup: <창>` 안에서 1회 보충 (Issue878).

    launchd 는 전원 꺼짐 중 슬롯을 부팅 뒤 보충하지 않는다. 부팅 감지를 위해 plist 를 건드리지
    않고(RunAtLoad 재설치 불필요) t-5m 바인딩이 이 서브커맨드를 부른다 — 부팅 뒤 5분 안에 돈다.
    이벤트별 opt-in: 선언에 `catchup` 이 있는 calendar 이벤트만. 놓친 슬롯이 여럿이면 **가장
    최근 1건**만 보충한다(아침 요약 3일치를 한꺼번에 쏟지 않는다).
    멱등: ledger 에 `<이벤트>~catchup` 줄이 슬롯 이후에 있으면 이미 보충한 것이다. 이 라벨은
    정규 발화로 치지 않으므로 `check --missed` 의 누락 기록은 그대로 남는다.
    """
    import datetime
    events, jobs, bindings = load()
    now = _parse_now(argv)
    dry = "--dry" in argv
    wins = {n: parse_every(ev["catchup"]) for n, ev in events.items()
            if isinstance(ev, dict) and ev.get("catchup") and ev.get("type") == "calendar"}
    if not wins:
        print("catchup: 보충 대상 이벤트 없음(catchup 선언 0건)")
        return
    hours = max(MISS_HOURS, max(wins.values()) // 3600 + 1)
    r = missed_slots(events, jobs, bindings, now, hours=hours)
    done = {}
    for row in _ledger_rows():
        if row["event"].endswith(CATCHUP_SUFFIX):
            try:
                done.setdefault(row["event"][:-len(CATCHUP_SUFFIX)], []).append(
                    datetime.datetime.fromisoformat(row["ts"]))
            except ValueError:
                pass
    runner = os.path.join(ROOT, "hooks", "schedule-run.sh")
    n_run = 0
    for name, win in sorted(wins.items()):
        cands = [m for m in r["missed"] if m["event"] == name and
                 (now - datetime.datetime.fromisoformat(m["slot"])).total_seconds() <= win]
        if not cands:
            continue
        slot = datetime.datetime.fromisoformat(max(cands, key=lambda m: m["slot"])["slot"])
        if any(t >= slot for t in done.get(name, [])):
            continue                     # 이미 보충함
        tag = "%s %s" % (name, slot.strftime("%m-%d %H:%M"))
        if dry:
            print("catchup: %s — 보충 대상(창 %s, --dry 라 실행 안 함)" % (tag, ev_win_text(events[name])))
            continue
        print("catchup: %s → 실행(창 %s)" % (tag, ev_win_text(events[name])))
        for b in [b for b in bindings if b["event"] == name]:
            _run_binding(name + CATCHUP_SUFFIX, b, jobs, runner)
        n_run += 1
    print("catchup: %s" % ("보충 %d건" % n_run if not dry else "dry 종료"))


def ev_win_text(ev):
    return str(ev.get("catchup")).strip()


def _miss_summary(r):
    n_up = sum(1 for m in r["missed"] if m["cause"] == "up")
    return "missed: 기대 %d · 발화 %d · 누락 %d (가동중 %d · 꺼짐 %d) — 최근 %sh" % (
        r["expected"], r["fired"], len(r["missed"]), n_up, len(r["missed"]) - n_up, r["hours"])


def cmd_missed(argv, events=None, jobs=None, bindings=None):
    """`check --missed [--hours N] [--now ISO] [--strict] [--json]` — ledger 감사만.

    rc: 가동 중 미발화가 있으면 1. `--strict` 면 꺼짐 추정도 1(«연속 N슬롯 발화» 검증용).
    """
    import json
    if events is None:
        events, jobs, bindings = load()
    try:
        hours = int(_opt(argv, "--hours", MISS_HOURS))
    except ValueError:
        die("--hours 는 정수(시간)다: %s" % _opt(argv, "--hours"))
    r = missed_slots(events, jobs, bindings, _parse_now(argv), hours=hours)
    if "--json" in argv:
        print(json.dumps(r, ensure_ascii=False))
    else:
        for m in r["missed"]:
            print("  " + _miss_line(m))
        print(_miss_summary(r))
    n_up = sum(1 for m in r["missed"] if m["cause"] == "up")
    if n_up or ("--strict" in argv and r["missed"]):
        sys.exit(1)


# ── check ───────────────────────────────────────────────────────────────
def cmd_check(argv):
    """선언 ↔ 실제의 drift 를 **fail-loud** 로 알린다.

    ⚠️ 등재 대조에서 빠지는 것과 검증에서 빠지는 것은 다르다. state·probe·
    external 은 유닛이 없지만 `raised_by` 배선은 반드시 확인한다 — 그러지 않으면
    "선언만 있고 아무도 부르지 않는 이벤트" 가 조용히 생긴다.

    ④ 발화 누락(prj3#Issue775) — 가동 중 미발화는 ❌(rc=1), 꺼짐 추정은 ⚠️(rc 불변).
      꺼짐까지 실패로 치면 밤에 전원을 끄는 머신에서 check 가 상시 붉어져 ①~③ 의
      drift 신호가 묻힌다. `--missed` 는 ④ 만 돈다(launchctl 대조 생략).
    """
    if "--missed" in argv:
        return cmd_missed(argv)
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
            if not plist_equivalent(f.read(), unit_text(ev_name, ev)):
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

    # ④ 발화 누락 — 기대 슬롯 대비 ledger 0건 (prj3#Issue775)
    try:
        hours = int(_opt(argv, "--hours", MISS_HOURS))
    except ValueError:
        die("--hours 는 정수(시간)다: %s" % _opt(argv, "--hours"))
    miss = missed_slots(events, jobs, bindings, _parse_now(argv), hours=hours)
    for m in miss["missed"]:
        if m["cause"] == "up":
            bad.append("발화 누락 %s" % _miss_line(m)[2:])
    warn = [m for m in miss["missed"] if m["cause"] != "up"]

    if bad:
        print("check: %d 건 불일치" % len(bad))
        for b in bad:
            print("  ❌ %s" % b)
        for m in warn:
            print("  " + _miss_line(m))
        sys.exit(1)
    n_c = len(compiled_events(events))
    print("check: OK — 유닛 %d · 비유닛 이벤트 %d · 잡 %d · 바인딩 %d"
          % (n_c, len(events) - n_c, len(jobs), len(bindings)))
    for m in warn:
        print("  " + _miss_line(m))
    if miss["missed"]:
        print("  " + _miss_summary(miss))


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
def _call_runner(runner, ev, label, run, lock=None, timeout=None, ok_rc=None, log=None, cwd=None):
    """래퍼 1회 호출 → 종료코드 계약값(0/10/11/12/13). 그 밖의 값은 래퍼 자체 실패다."""
    import subprocess
    cmd = [runner, "--event", ev, "--job", label, "--run", run]
    if lock:
        cmd += ["--lock", str(lock)]
    if timeout:
        cmd += ["--timeout", str(timeout)]
    if ok_rc:
        cmd += ["--ok-rc", ",".join(str(x) for x in ok_rc)]
    if log:
        cmd += ["--log", expand(str(log))]
    if cwd:
        cmd += ["--cwd", expand(str(cwd))]
    env = dict(os.environ, SCHEDULE_LEDGER=LEDGER)
    r = subprocess.run(["/bin/bash", *cmd], env=env, stdout=sys.stderr if _QUIET else None)
    if r.returncode not in RESULT_OF:
        print("  ⚠️ 래퍼 자체가 실패했다 %s (rc=%d)" % (label, r.returncode), file=sys.stderr)
        return RC_FAILED
    return r.returncode


# prj3#Issue698: 실패하면 **왜** 를 결과에 싣는다. 화면이 «failed» 한 단어만 보이면
#   원인이 해소됐는지 아닌지 사람이 알 수 없다(2026.09.26 disk-check — fg1 꺼짐이 안 보였다).
#   로그인 셸 초기화 소음(tput·bashrc·fpm alias)은 걸러낸다 — 매 실행 err 에 섞인다
_LOG_NOISE = ("tput:", ".bashrc:", "fpm: alias", "iterm2_shell_integration")
# prj3#Issue780: schedule-run.sh 가 회차마다 남기는 경계 줄(`── <시각> <이벤트> <잡> pid=N ──`·
#   `── rc=N Ds ──`)은 hub 회차 절단용 표식이지 실패 사유가 아니다 — tail 에서 뺀다
_LOG_BOUNDARY = re.compile(r"^── .+ ──$")


def _log_paths(label, log=None):
    d = expand(str(log)) if log else os.path.join(ROOT, "data", "schedule", "log")
    return [os.path.join(d, "%s.%s" % (label, ext)) for ext in ("out", "err")]


def _log_mark(label, log=None):
    """실행 직전 로그 크기 — 로그는 **누적**이라 이 뒤에 붙은 것만 이번 실행분이다."""
    return [os.path.getsize(f) if os.path.exists(f) else 0 for f in _log_paths(label, log)]


def _log_tail(label, log=None, mark=None, n=3):
    out = []
    for i, f in enumerate(_log_paths(label, log)):
        try:
            with open(f, "rb") as fh:
                off = (mark or [0, 0])[i]
                if off > os.path.getsize(f):     # 회전(1MB)으로 파일이 새로 시작됐다
                    off = 0
                fh.seek(off)
                lines = fh.read()[-8192:].decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        out += [x.rstrip() for x in lines if x.strip() and not any(k in x for k in _LOG_NOISE)
                and not _LOG_BOUNDARY.match(x.strip())][-n:]
    return out[-n:]


# prj3#Issue863_7 — scar·prompt 스텝의 `claude -p` 는 모델을 Jev(selection.py pick)로 고른다. 종전엔 `--model` 이 없어
#   settings `model`(사람이 /model 로 고른 값)을 상속했다. 스텝 `model:`(별칭)이 이기고, 별칭 밖 값은 거부한다(명령 줄 주입 방지).
#   pick 은 어떤 실패에도 기본값을 낸다 — 스케줄이 Jev 장애로 멈추지 않는다.
_SCHED_ALIASES = ("haiku", "sonnet", "opus")
_SELECTION_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selection.py")
_PICK = None


def _step_model(step, question):
    m = step.get("model")
    if m is not None:
        if m not in _SCHED_ALIASES:
            die("스텝 model 은 별칭(haiku·sonnet·opus)만: %r" % (m,))
        return m
    global _PICK
    try:
        if _PICK is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location("_sched_selection", _SELECTION_PY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _PICK = mod.pick
        r = _PICK(question)
    except Exception:
        r = None
    return r if r in _SCHED_ALIASES else "sonnet"


def _step_run(step, arg):
    """스텝 → (셸 명령, 기본 cwd). `{arg}` 는 모든 문자열 필드에서 치환한다."""
    def sub(v):
        return str(v).replace("{arg}", str(arg if arg is not None else ""))
    kind = step["kind"]
    if kind == "sh":
        return sub(step["run"]), step.get("cwd")
    if kind == "script":
        path = expand(sub(step["path"]))
        args = sub(step.get("args", "")).strip()
        head = shlex.quote(path) if os.access(path, os.X_OK) else "bash " + shlex.quote(path)
        return (head + (" " + args if args else "")), step.get("cwd")
    if kind == "scar":
        # PATH 는 defaults.path 가 이미 해소한다(Issue505·579) — claude 를 찾는다
        #   SCHEDULE_CLAUDE 는 테스트 knob 이다 — 래퍼가 `bash -lc` 라 PATH 앞에 가짜를 끼워도
        #   로그인 셸이 PATH 를 다시 짜서 **진짜 claude 가 불린다**(2026.09.26 스모크 실측)
        cl = os.environ.get("SCHEDULE_CLAUDE") or "claude"
        return "%s --model %s -p %s" % (cl, _step_model(step, sub(step["cmd"])), shlex.quote(sub(step["cmd"]))), \
            (step.get("cwd") or "~/.claude")
    if kind == "prompt":
        # prj3#Issue698: 슬래시 커맨드가 없는 일을 자연어로 시킨다. 실행 경로는 scar 와 한 벌이다
        cl = os.environ.get("SCHEDULE_CLAUDE") or "claude"
        return "%s --model %s -p %s" % (cl, _step_model(step, sub(step["text"])), shlex.quote(sub(step["text"]))), \
            (step.get("cwd") or "~/.claude")
    die("전개할 수 없는 스텝 kind: %s" % kind)


def _ledger_rc(code):
    return {RC_OK: "rc=0", RC_FAILED: "rc=1", RC_TIMEOUT: "rc=timeout",
            RC_BUSY: "rc=skip", RC_SKIP: "rc=skip"}.get(code, "rc=1")


def _lock_acquire(name):
    """mkdir 원자 락 — 래퍼의 `--lock wrapper` 와 **같은 디렉토리**를 쓴다(상호 배제가 이어진다)."""
    d = os.path.join(ROOT, "data", "schedule", ".lock", name)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    try:
        os.mkdir(d)
    except FileExistsError:
        try:
            pid = int(open(os.path.join(d, "pid")).read().strip())
            os.kill(pid, 0)
            return None                      # 선행 실행 생존
        except (OSError, ValueError):
            import shutil
            shutil.rmtree(d, ignore_errors=True)   # 죽은 락 탈취
            try:
                os.mkdir(d)
            except FileExistsError:
                return None
    with open(os.path.join(d, "pid"), "w") as f:
        f.write(str(os.getpid()))
    return d


def _run_binding(ev, b, jobs, runner, force=False, deadline=None, stack=()):
    """바인딩 하나를 멈춤·조건 판정 후 실행하고 결과 dict 를 돌려준다.

    결과: {job, event, result, rc, steps:[{n,kind,result,rc,dur}]}
      rc 는 schedule-run.sh 종료코드 계약(0/10/11/12/13)이다.

    ## steps 잡 (prj3#Issue691)
      lock·timeout 은 **잡 단위 1회**다 — 스텝마다 래퍼에 lock 을 맡기면 스텝 사이에
      lock 이 풀린다. 잡 lock 은 여기서 쥐고, 스텝 호출에는 `--lock none` + 남은 초를 준다.
      ledger 에는 스텝 N줄(`<잡>#<n>`) + 잡 1줄이 남는다 — 어느 스텝에서 죽었는지 화면이 말한다.
      `kind: job` 스텝은 자식 잡을 **같은 프로세스에서 재귀**로 돌린다(자식 자기 기록 + 스텝 1줄).
    """
    import datetime
    job_name = b["job"]
    job = _job_dict(jobs[job_name])
    arg = b.get("arg")
    res = {"job": job_name, "event": ev, "result": "ok", "rc": RC_OK, "steps": []}

    # 멈춤 — 조건 판정 직전. ledger 는 전환 때만 쓴다(pause/resume CLI). 사람의 실행(--force)은 뚫는다
    if not force and (_is_paused(job) or _is_paused(b)):
        print("  paused %s%s" % (job_name, "" if _is_paused(job) else " (스케줄 %s)" % ev))
        res.update(result="paused", rc=RC_SKIP)
        return res

    # 조건 — 차단도 기록한다. 아무 줄도 안 남기면 침묵과 구분되지 않는다
    blocked = None
    if "unless" in b and eval_cond(b["unless"]):
        blocked = "unless=%s" % b["unless"]
    elif "when" in b and not eval_cond(b["when"]):
        blocked = "when=%s" % b["when"]
    if blocked:
        ledger_write(ev, job_name, "rc=skip", blocked)
        print("  skip %s (%s)" % (job_name, blocked))
        res.update(result="skip", rc=RC_SKIP)
        return res

    def remaining():
        return None if deadline is None else int(deadline - time.time())

    # ── run 한 줄 잡 — 종전 경로 그대로(무회귀). sh 스텝 1개로 보고한다
    if "steps" not in job:
        run = str(job.get("run", ""))
        if "{arg}" in run:
            run = run.replace("{arg}", str(b.get("arg", "")))
        tmo = job.get("timeout")
        left = remaining()
        if left is not None:
            if left <= 0:
                ledger_write(ev, job_name, "rc=timeout", "부모 잡 마감 초과 — 실행 안 함")
                res.update(result="timeout", rc=RC_TIMEOUT)
                return res
            tmo = min(int(tmo), left) if tmo else left
        t0 = time.time()
        mk = _log_mark(job_name, job.get("log"))
        rc = _call_runner(runner, ev, job_name, run, lock=job.get("lock"), timeout=tmo,
                          ok_rc=job.get("ok_rc"), log=job.get("log"), cwd=job.get("cwd"))
        res["steps"].append({"n": 1, "kind": "sh", "result": RESULT_OF[rc], "rc": rc,
                             "dur": int(time.time() - t0)})
        if rc not in (RC_OK, RC_SKIP):
            res["steps"][-1]["tail"] = _log_tail(job_name, job.get("log"), mk)
        res.update(result=RESULT_OF[rc], rc=rc)
        return res

    # ── steps 잡
    t_start = time.time()
    tmo = job.get("timeout")
    dl = (t_start + int(tmo)) if tmo else None
    if deadline is not None:
        dl = min(dl, deadline) if dl else deadline
    lockd = None
    if job.get("lock") in ("wrapper", "self"):   # steps 잡에서 self 는 의미가 없다 — wrapper 로 본다
        lockd = _lock_acquire(job_name)
        if lockd is None:
            ledger_write(ev, job_name, "rc=skip", "lock=busy")
            print("  skip %s (lock=busy)" % job_name)
            res.update(result="lock-busy", rc=RC_BUSY)
            return res
    on_error = job.get("on_error", "stop")
    final = RC_OK
    fail_at = None
    try:
        steps = job["steps"]
        for n, st in enumerate(steps, 1):
            label = "%s#%d" % (job_name, n)
            left = None if dl is None else int(dl - time.time())
            t0 = time.time()
            if left is not None and left <= 0:
                ledger_write(ev, label, "rc=timeout", "잡 마감 초과 — 실행 안 함")
                rc = RC_TIMEOUT
            elif st["kind"] == "job":
                sb = {"event": ev, "job": st["ref"]}
                if st.get("arg") is not None or arg is not None:
                    sb["arg"] = str(st.get("arg") if st.get("arg") is not None else arg).replace(
                        "{arg}", str(arg if arg is not None else ""))
                if st["ref"] in stack + (job_name,):          # load 가 막지만 실행에서도 한 번 더
                    ledger_write(ev, label, "rc=1", "순환 — %s" % st["ref"])
                    rc = RC_FAILED
                else:
                    sub = _run_binding(ev, sb, jobs, runner, force=force, deadline=dl,
                                       stack=stack + (job_name,))
                    rc = sub["rc"]
                    ledger_write(ev, label, _ledger_rc(rc), "job=%s result=%s %ds"
                                 % (st["ref"], sub["result"], int(time.time() - t0)))
            else:
                run, cwd = _step_run(st, arg)
                mk = _log_mark(label, job.get("log"))
                stmo = st.get("timeout")
                if left is not None:
                    stmo = min(int(stmo), left) if stmo else left
                rc = _call_runner(runner, ev, label, run, lock="none", timeout=stmo,
                                  ok_rc=st.get("ok_rc"), log=job.get("log"),
                                  cwd=cwd or job.get("cwd"))
            res["steps"].append({"n": n, "kind": st["kind"], "result": RESULT_OF.get(rc, "failed"),
                                 "rc": rc, "dur": int(time.time() - t0)})
            if rc not in (RC_OK, RC_SKIP) and st["kind"] != "job":
                res["steps"][-1]["tail"] = _log_tail(label, job.get("log"), mk if st["kind"] != "job" else None)
            if rc not in (RC_OK, RC_SKIP):
                if final == RC_OK:
                    final, fail_at = rc, n
                if on_error == "stop":
                    break
    finally:
        if lockd:
            import shutil
            shutil.rmtree(lockd, ignore_errors=True)

    n_ok = sum(1 for x in res["steps"] if x["rc"] in (RC_OK, RC_SKIP))
    ledger_write(ev, job_name, _ledger_rc(final), "steps=%d/%d ok%s %ds" % (
        n_ok, len(job["steps"]), (" fail=#%d" % fail_at) if fail_at else "",
        int(time.time() - t_start)))
    res.update(result=RESULT_OF[final], rc=final)
    return res


_QUIET = False     # --json 이면 래퍼·진행 출력을 stderr 로 돌려 stdout 을 JSON 1줄로 지킨다


def cmd_dispatch(argv):
    """신호원이 부르는 유일한 문.

    두 형태가 있다:
      dispatch <event>              — 선언된 바인딩을 따른다 (반복·상태·신호 이벤트)
      dispatch --job <잡> [--arg V] [--event L] [--force] [--json]
                                    — 잡을 직접 지목한다 (일회성 예약 Issue540 · 화면 ▶ 실행)

    ## 왜 `--job` 이 따로 있나
      일회성 예약(aoa-mq `--due`)을 `type: external` 이벤트로 표현하려 했으나
      **일회성인데 선언 파일에 영구히 남는 모순**이 생겼다 — 한 번 쓰고 나면 `check` 가
      "부르는 이 없는 이벤트" 로 잡거나, 남겨두면 선언이 로그가 된다.

      해소: **일회성은 이벤트가 아니다.** 이벤트는 *반복되거나 상태가 전이하는 것*이고,
      일회성 예약은 **큐가 소유한 데이터**다(crontab 과 `at` 의 경계). 큐는 선언된 잡을
      지목할 뿐이며, 잡이 `jobs:` 에 있어야 한다는 제약이 그대로 남아
      "선언에 있는 것만 실행" 보증은 유지된다.

    ## --force · --json (prj3#Issue691)
      `--force` 는 멈춤을 뚫는다 — 멈춤은 *자동* 발화를 막는 장치이고 사람이 누른 것은 돈다.
      `--json` 은 `{job,result,rc,steps[]}` 1줄을 낸다 — 큐 tick·hub 가 읽는다.

    한 이벤트에 여러 바인딩이 걸리면 **선언 순서대로 순차** 실행하고, 하나가 실패해도
    나머지를 계속한다(격리). 병렬로 하면 실패 원인이 서로 오염되고 ledger 순서가 흔들린다.
    """
    global _QUIET
    import json
    events, jobs, bindings = load()
    runner = os.path.join(ROOT, "hooks", "schedule-run.sh")

    # ── 잡 직접 지목 (일회성) ──
    if argv and argv[0] == "--job":
        opts = {}
        i = 0
        while i < len(argv):
            if argv[i] in ("--force", "--json"):
                opts[argv[i][2:]] = True
                i += 1
            elif argv[i] in ("--job", "--arg", "--event") and i + 1 < len(argv):
                opts[argv[i][2:]] = argv[i + 1]
                i += 2
            else:
                die("dispatch --job <잡> [--arg <값>] [--event <라벨>] [--force] [--json] — "
                    "알 수 없는 인자: %s" % argv[i])
        job_name = opts.get("job")
        if job_name not in jobs:
            die("선언에 없는 잡: %s — `jobs:` 에 있는 것만 실행할 수 있다" % job_name)
        _QUIET = bool(opts.get("json"))
        label = opts.get("event", "oneshot")
        b = {"event": label, "job": job_name}
        if "arg" in opts:
            b["arg"] = opts["arg"]
        stdout = sys.stdout
        if _QUIET:
            sys.stdout = sys.stderr
        try:
            res = _run_binding(label, b, jobs, runner, force=bool(opts.get("force")))
        finally:
            sys.stdout = stdout
        if _QUIET:
            print(json.dumps(res, ensure_ascii=False))
        return

    ev = argv[0]
    if ev not in events:
        die("선언에 없는 이벤트: %s" % ev)

    matched = [b for b in bindings if b["event"] == ev]
    if not matched:
        die("이벤트에 걸린 바인딩이 없다: %s" % ev)

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
            for dd in range(0, 367 if ("Day" in c or "Month" in c) else 8):
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
    # prj3#Issue775: 이벤트별 발화 누락 — 화면이 «안 돈 슬롯» 을 보여준다(판정은 check 와 한 벌)
    miss = missed_slots(events, jobs, bindings, _parse_now(argv))
    out["missed"] = {k: miss[k] for k in ("hours", "expected", "fired")}
    last = {}
    for r in rows:                   # 잡별 최근 1건
        if r["rc"] in ("pause", "resume"):   # prj3#Issue691: 전환 기록은 «실행» 이 아니다
            continue
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
            # prj3#Issue691: 날짜 축 — 화면이 «매주 월 09:00» 칩을 만든다
            "weekday": ev.get("weekday"), "day": ev.get("day"), "month": ev.get("month"),
            "loaded": loaded, "runs": runs, "next": next_fire(ev),
            "source": src["events"].get(name, "system"),
            "jobs": [b["job"] for b in bindings if b["event"] == name],
            "missed": [{"slot": m["slot"], "cause": m["cause"]}
                       for m in miss["missed"] if m["event"] == name],
        })

    bound = {b["job"] for b in bindings}
    for name in sorted(jobs):
        j = _job_dict(jobs[name])
        out["jobs"].append({
            "name": name, "run": j.get("run", ""), "lock": j.get("lock"),
            "timeout": j.get("timeout"),
            "oneshot": j.get("oneshot") in (True, "true", "True"),
            "cwd": j.get("cwd"), "log": j.get("log"),
            "source": src["jobs"].get(name, "system"),
            "bound": name in bound, "last": last.get(name),
            # prj3#Issue691 — 잡 탭(카탈로그)이 읽는다
            "desc": j.get("desc"), "steps": _job_steps(j),
            "on_error": j.get("on_error", "stop"),
            "paused": _is_paused(j),
            # prj3#Issue893 — 산출물 glob + 최신 일치 파일(hub «최신 결과 문서» 링크 재료)
            "result": _result_globs(j),
            "result_latest": _result_latest(_result_globs(j)),
            "bindings_n": sum(1 for b in bindings if b["job"] == name),
        })

    for i, b in enumerate(bindings):
        out["bindings"].append({"event": b["event"], "job": b["job"],
                                "arg": b.get("arg"), "unless": b.get("unless"),
                                "paused": _is_paused(b),
                                "desc": b.get("desc"),
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
    # prj3#Issue775: 안 돈 슬롯은 LAST RUN 한 칸으로는 안 보인다 — 따로 적는다
    miss = missed_slots(events, jobs, bindings, _parse_now(argv))
    if miss["missed"]:
        print("")
        for m in miss["missed"]:
            print("  " + _miss_line(m))
        print("  " + _miss_summary(miss))


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


_WD_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


def _event_name_for(kind, spec):
    """시각 → 이벤트 이름. 선언 파일에 이미 쓰던 규칙 그대로다(`t-5m`·`t-0703`).

    prj3#Issue691: 날짜 축이 붙으면 접두를 단다 — `t-mon-0900`(매주) · `t-d15-0900`(매월)
    · `t-y0115-0900`(매년). 매일은 종전 이름(`t-0900`) 그대로라 기존 선언과 충돌하지 않는다.
    """
    if kind == "every":
        return "t-%s" % str(spec).strip()
    hh, mm = str(spec["at"]).split(":", 1)
    hm = "%02d%02d" % (int(hh), int(mm))
    if "weekday" in spec:
        return "t-%s-%s" % ("".join(_WD_NAMES[w] for w in spec["weekday"]), hm)
    if "month" in spec:
        return "t-y%02d%02d-%s" % (spec["month"], spec["day"][0], hm)
    if "day" in spec:
        return "t-d%s-%s" % ("-".join(str(d) for d in spec["day"]), hm)
    return "t-%s" % hm


def _calendar_key(ev):
    """캘린더 이벤트의 비교 키 — at + 날짜 축. 시각만 비교하면 «매주 09:00» 이
    «매일 09:00» 이벤트를 재사용해 매일 돌아 버린다(prj3#Issue691 에서 잡은 함정)."""
    at = str(ev.get("at", "")).strip()
    wd = tuple(sorted(x for x in _calendar_list(ev, "weekday") if x is not None))
    dy = tuple(sorted(x for x in _calendar_list(ev, "day") if x is not None))
    mo = int(ev["month"]) if "month" in ev else None
    return (at, wd, dy, mo)


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
    want = _calendar_key(spec)
    for name, ev in events.items():
        if ev.get("type") == "calendar":
            try:
                if _calendar_key(ev) == want:
                    return name
            except SystemExit:
                continue
    return None


def _calendar_event(spec):
    """_parse_when 의 캘린더 spec → 선언에 쓸 이벤트 사전."""
    ev = {"type": "calendar", "at": _Quoted(spec["at"])}
    if "weekday" in spec:
        ev["weekday"] = _Quoted(",".join(_WD_NAMES[w] for w in spec["weekday"]))
    if "month" in spec:
        ev["month"] = spec["month"]
    if "day" in spec:
        ev["day"] = spec["day"][0] if len(spec["day"]) == 1 else _Quoted(",".join(str(d) for d in spec["day"]))
    return ev


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


# prj3#Issue701 — 아직 실행되지 않은 mq 예약 상태. `done_unacked` 는 이미 실행돼 결과 ACK 만
#   기다리는 것이라 잡이 없어져도 깨질 것이 없다.
MQ_PENDING_STATUSES = ("pending", "due", "in_progress")


def _mq_job_refs(name):
    """mq 큐(queue/)에서 `name` 잡을 지목한 미실행 예약 id 목록. 큐가 없으면 빈 목록.

    경로는 aoa-mq helper 와 같은 계약이다 — `AOA_MQ_DIR` 우선, 없으면 prj3 기본.
    읽기 실패한 항목은 **거부 쪽으로** 센다: 판정할 수 없는 예약을 무시하면 가드가 새는 구멍이 된다.
    """
    import glob
    import json
    qdir = os.path.join(os.environ.get("AOA_MQ_DIR")
                        or os.path.expanduser("~/.claude/data/aoa/mq"), "queue")
    hits = []
    for f in sorted(glob.glob(os.path.join(qdir, "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            # 판독 불가 — 원문에 이 잡 이름이 보이면 거부 쪽으로 센다(다른 잡 삭제까지 막지는 않는다)
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    if '"%s"' % name in fh.read():
                        hits.append(os.path.basename(f) + "(판독 불가)")
            except OSError:
                pass
            continue
        if d.get("job") == name and d.get("status") in MQ_PENDING_STATUSES:
            hits.append("%s(%s)" % (d.get("id") or os.path.basename(f), d.get("status")))
    return hits


def _kv(argv):
    """`--k v` 목록을 dict 로. 플래그(`--manual`·`--no-write`)는 True.

    `--at`·`--every` 는 **여러 번 줄 수 있고** 리스트로 모인다.
    """
    flags = {"--manual", "--no-write", "--cascade", "--replacing"}   # 뒤 둘: prj3#Issue701
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
    # prj3#Issue691: 날짜 축 — `<축>@HH:MM`
    #   매일 `09:00` · 매주 `mon@09:00`·`mon,wed,fri@09:00` · 매월 `d15@09:00`·`d1,15@09:00`
    #   · 매년 `y01-15@09:00`
    axis, _, hm = spec.rpartition("@")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", hm)
    if not m:
        die("--at 은 HH:MM (또는 mon@HH:MM · d15@HH:MM · y01-15@HH:MM) 형식이다: %s" % spec)
    if not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
        die("--at 범위를 벗어났다: %s (00:00~23:59)" % spec)
    out = {"at": "%02d:%02d" % (int(m.group(1)), int(m.group(2)))}
    axis = axis.strip().lower()
    if axis:
        ym = re.fullmatch(r"y(\d{1,2})-(\d{1,2})", axis)
        dm = re.fullmatch(r"d(\d{1,2}(?:,\d{1,2})*)", axis)
        if ym:
            mo, dd = int(ym.group(1)), int(ym.group(2))
            if not (1 <= mo <= 12 and 1 <= dd <= 31):
                die("매년 날짜 범위를 벗어났다: %s" % axis)
            out["month"], out["day"] = mo, [dd]
        elif dm:
            out["day"] = sorted({int(x) for x in dm.group(1).split(",")})
            if not all(1 <= d <= 31 for d in out["day"]):
                die("매월 일자는 1~31 이다: %s" % axis)
        else:
            wds = []
            for x in axis.split(","):
                k = x.strip()[:3]
                if k not in WEEKDAY:
                    die("요일을 해석할 수 없다: %s (sun~sat · d15 · y01-15)" % x)
                wds.append(WEEKDAY[k])
            out["weekday"] = sorted(set(wds))
    return out, (arg.strip() or None)


def _post_write(changed_units):
    """선언이 바뀐 뒤 launchd 에 반영. 새 유닛이 없으면 아무것도 하지 않는다."""
    if not changed_units:
        return
    if backend_name() != "launchd":
        print("  (백엔드가 launchd 가 아니다 — 등재 생략)")
        return
    cmd_write([])


# ── 카탈로그 — 잡 스텝이 고를 수 있는 것 (prj3#Issue691) ─────────────────
#   수집과 검증은 **코드**가 한다. LLM 제안(job suggest)은 이 목록 안에서만 고르고,
#   목록 밖을 지어내면 검증이 `invalid` 로 표시한다 — 환각을 화면이 거른다.
def _md_desc(path):
    """frontmatter `description:` 한 줄. 없으면 빈 문자열."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
    except OSError:
        return ""
    m = re.search(r"^description:\s*(.+)$", head, re.M)
    return m.group(1).strip().strip("'\"")[:160] if m else ""


def _sh_desc(path):
    """스크립트 머리 주석에서 첫 설명 줄 — `name.sh — 설명` 형태를 우선한다."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [next(f, "") for _ in range(25)]
    except OSError:
        return ""
    for ln in lines:
        m = re.match(r"#\s*\S+\.(?:sh|py)\s+[—-]\s+(.+)", ln)
        if m:
            return m.group(1).strip()[:160]
    for ln in lines[1:]:
        t = ln.lstrip("#").strip()
        if ln.startswith("#") and t and not t.startswith(("⚠️", "🔒", "📚", "!")):
            return t[:160]
    return ""


def _scar_dirs(cwd=None):
    """(커맨드 md 목록, 스킬 SKILL.md 목록). cwd 가 있으면 그 프로젝트 로컬도 더한다."""
    import glob
    roots = [ROOT]
    if cwd:
        roots.append(os.path.join(expand(cwd), ".claude"))
    cmds, skills = [], []
    for r in roots:
        cmds += glob.glob(os.path.join(r, "commands", "*.md"))
        skills += glob.glob(os.path.join(r, "skills", "*", "SKILL.md"))
        skills += glob.glob(os.path.join(r, "skills", "synced", "*", "*", "SKILL.md"))
    # 플러그인 — 이름은 `plugin:name` 으로도 불리므로 뒤쪽 이름으로 맞춘다
    cmds += glob.glob(os.path.join(ROOT, "plugins", "**", "commands", "*.md"), recursive=True)
    skills += glob.glob(os.path.join(ROOT, "plugins", "**", "skills", "*", "SKILL.md"), recursive=True)
    return cmds, skills


def _scar_exists(cmd, cwd=None):
    name = cmd.split(":")[-1]
    cmds, skills = _scar_dirs(cwd)
    names = {os.path.basename(c)[:-3] for c in cmds}
    names |= {os.path.basename(os.path.dirname(k)) for k in skills}
    return name in names


def catalog(jobs=None):
    """잡 스텝 후보 전체. 프로젝트 로컬 커맨드·플러그인은 뺀다(어디서 돌지 모르는 것은 추천하지 않는다)."""
    import glob
    out = {"commands": [], "skills": [], "jobs": [], "scripts": []}
    for c in sorted(glob.glob(os.path.join(ROOT, "commands", "*.md"))):
        out["commands"].append({"name": "/" + os.path.basename(c)[:-3], "desc": _md_desc(c)})
    for k in sorted(glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md"))):
        out["skills"].append({"name": "/" + os.path.basename(os.path.dirname(k)), "desc": _md_desc(k)})
    if jobs is None:
        _, jobs, _ = load()
    for n in sorted(jobs):
        j = _job_dict(jobs[n])
        out["jobs"].append({"name": n, "desc": j.get("desc") or (j.get("run") or "")[:120]})
    for d in ("hooks", "sh"):
        for f in sorted(glob.glob(os.path.join(ROOT, d, "*.sh"))):
            out["scripts"].append({"path": os.path.relpath(f, ROOT), "desc": _sh_desc(f)})
    return out


def cmd_catalog(argv):
    import json
    c = catalog()
    if "--json" in argv:
        print(json.dumps(c, ensure_ascii=False))
        return
    for k in ("commands", "skills", "jobs", "scripts"):
        print("%s: %d" % (k, len(c[k])))


SUGGEST_SCHEMA = {
    "type": "object", "required": ["candidates"],
    "properties": {"candidates": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
        "type": "object", "required": ["name", "desc", "steps"],
        "properties": {
            "name": {"type": "string"}, "desc": {"type": "string"},
            "when": {"type": "string"},
            "steps": {"type": "array", "minItems": 1, "items": {
                "type": "object", "required": ["kind"],
                "properties": {"kind": {"enum": sorted(STEP_KINDS)},
                               "ref": {"type": "string"}, "arg": {"type": "string"},
                               "cmd": {"type": "string"}, "cwd": {"type": "string"},
                               "path": {"type": "string"}, "args": {"type": "string"},
                               "run": {"type": "string"}, "text": {"type": "string"}}}}}}}}}


def _claude_bin():
    """제안 호출용 claude — hub(launchd 자식)는 PATH 가 짧으므로 선언 PATH 로 찾는다(Issue505)."""
    import shutil
    forced = os.environ.get("SCHEDULE_CLAUDE")
    if forced:
        return forced if (os.path.isfile(forced) and os.access(forced, os.X_OK)) else None
    return shutil.which("claude", path=_resolve_unit_path() + ":" + os.environ.get("PATH", ""))


def _suggest_llm(prompt, cat, timeout=60):
    """카탈로그 + 프롬프트 → 후보. **도구 없이** 부른다 — 텍스트 생성 외 부작용 경로가 없다."""
    import json
    import subprocess
    cl = _claude_bin()
    if not cl:
        raise RuntimeError("claude 실행 파일 없음")
    lines = ["[커맨드·스킬 — kind: scar, cmd 에 이름 그대로]"]
    lines += ["%s — %s" % (c["name"], c["desc"]) for c in cat["commands"] + cat["skills"]]
    lines += ["", "[기존 잡 — kind: job, ref]"]
    lines += ["%s — %s" % (c["name"], c["desc"]) for c in cat["jobs"]]
    lines += ["", "[스크립트 — kind: script, path (~/.claude 기준 상대경로)]"]
    lines += ["%s — %s" % (c["path"], c["desc"]) for c in cat["scripts"]]
    ask = ("너는 스케줄 잡 설계 보조다. 아래 카탈로그 **안에 있는 것만** 조합해 사용자의 요청을 이루는 "
           "잡 후보를 1~3개 제안한다. 카탈로그에 없는 커맨드·경로를 지어내지 않는다. 카탈로그로 안 되는 "
           "부분은 kind: prompt(text 에 claude 에게 시킬 한국어 지시) 또는 kind: sh 한 줄 셸로 채운다. name 은 소문자·숫자·하이픈 40자 이내. desc 는 한국어 한 줄. "
           "when 은 요청에 시각이 있으면 'HH:MM' 또는 '10m' 같은 주기, 없으면 빈 문자열.\n\n"
           "요청: %s\n\n카탈로그:\n%s" % (prompt, "\n".join(lines)))
    r = subprocess.run([cl, "-p", ask, "--tools", "", "--strict-mcp-config",
                        "--model", os.environ.get("SCHEDULE_SUGGEST_MODEL") or "haiku",
                        "--output-format", "json", "--json-schema", json.dumps(SUGGEST_SCHEMA)],
                       capture_output=True, text=True, timeout=timeout, cwd=ROOT,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError("claude rc=%d %s" % (r.returncode, (r.stderr or r.stdout)[-300:]))
    d = json.loads(r.stdout)
    so = d.get("structured_output")
    if not isinstance(so, dict) or not isinstance(so.get("candidates"), list):
        raise RuntimeError("구조화 출력 없음: %s" % str(d.get("result"))[:200])
    return so["candidates"]


def _suggest_fallback(prompt, cat, top=5):
    """키워드 매칭 — LLM 이 없어도 폼이 막히지 않게. 스텝 후보만 준다."""
    toks = [t.lower() for t in re.findall(r"[\w가-힣.-]{2,}", prompt)]
    cands = []
    for c in cat["commands"] + cat["skills"]:
        cands.append(({"kind": "scar", "cmd": c["name"]}, c["name"] + " " + c["desc"]))
    for c in cat["jobs"]:
        cands.append(({"kind": "job", "ref": c["name"]}, c["name"] + " " + c["desc"]))
    for c in cat["scripts"]:
        cands.append(({"kind": "script", "path": c["path"]}, c["path"] + " " + c["desc"]))
    scored = []
    for step, text in cands:
        low = text.lower()
        sc = sum(1 for t in toks if t in low)
        if sc:
            scored.append((sc, step, text))
    scored.sort(key=lambda x: -x[0])
    return [dict(st, desc=tx[:160], score=sc) for sc, st, tx in scored[:top]]


def _slug(name):
    n = re.sub(r"[^a-z0-9-]+", "-", str(name).lower()).strip("-")[:40]
    return n or "new-job"


def cmd_job(argv):
    """job suggest --prompt P [--json] — **제안만** 한다. 저장은 사람이 누른다(user job-add)."""
    import json
    if not argv or argv[0] != "suggest":
        die("job suggest --prompt P [--json]")
    o = _kv([a for a in argv[1:] if a != "--json"])
    prompt = (o.get("prompt") or "").strip()
    if not prompt:
        die("--prompt 가 필요하다")
    _, jobs, _ = load()
    cat = catalog(jobs)
    out = {"ok": True, "prompt": prompt, "fallback": False, "reason": None,
           "candidates": [], "step_hints": []}
    try:
        raw = _suggest_llm(prompt, cat, timeout=int(o.get("timeout") or 60))
    except Exception as e:           # 타임아웃·claude 부재·형식 오류 — 폼이 막히지 않게 폴백
        out.update(fallback=True, reason=str(e)[:300])
        out["step_hints"] = _suggest_fallback(prompt, cat)
        raw = []
    for c in raw[:3]:
        steps = [{k: v for k, v in st.items() if v not in (None, "")}
                 for st in (c.get("steps") or []) if isinstance(st, dict)]
        name = _slug(c.get("name"))
        invalid = []
        try:                         # 구조 — load 와 같은 검증기를 그대로 쓴다
            _validate_jobs(dict(jobs, **{name: {"steps": steps}}),
                           dict({k: "user" for k in jobs}, **{name: "user"}))
        except SystemExit as e:
            invalid.append(str(e).replace("schedule: ", ""))
        invalid += _steps_problems(steps, jobs)       # 실존
        if name in jobs:
            invalid.append("이미 있는 잡 이름: %s" % name)
        out["candidates"].append({"name": name, "desc": c.get("desc", ""),
                                  "when": c.get("when") or "", "steps": steps,
                                  "invalid": invalid})
    if "--json" in argv:
        print(json.dumps(out, ensure_ascii=False))
        return
    if out["fallback"]:
        print("⚠️ 제안 실패 → 키워드 폴백 (%s)" % out["reason"])
        for h in out["step_hints"]:
            print("  · %s" % json.dumps({k: v for k, v in h.items() if k not in ("desc",)}, ensure_ascii=False))
    for c in out["candidates"]:
        print("• %s — %s%s" % (c["name"], c["desc"], "  ⚠️ " + "; ".join(c["invalid"]) if c["invalid"] else ""))
        for st in c["steps"]:
            print("    %s" % json.dumps(st, ensure_ascii=False))


def _user_begin():
    """쓰기 트랜잭션 시작 — merge 뷰·사용자 원본·되돌리기 사본."""
    events, jobs, bindings, src = load(with_source=True)
    u_events, u_jobs, u_bindings = _user_decl()
    backup = open(USER_YML, encoding="utf-8").read() if os.path.exists(USER_YML) else None
    return events, jobs, bindings, src, u_events, u_jobs, u_bindings, backup


def _user_commit(u_events, u_jobs, u_bindings, backup):
    _dump_user(u_events, u_jobs, u_bindings, USER_YML)
    _verify_or_revert(USER_YML, backup)


def _require_user_job(name, jobs, src, verb):
    if not name:
        die("%s 에는 --name 이 필요하다" % verb)
    if name not in jobs:
        die("없는 잡이다: %s" % name)
    if src["jobs"].get(name) != "user":
        die("시스템 잡은 %s 할 수 없다: %s — `data/schedule.yml` 은 사람이 편집한다" % (verb, name))


def _check_name(name):
    if not name:
        die("--name 이 필요하다")
    if not NAME_RE.match(name):
        die("잡 이름은 소문자·숫자·하이픈만 쓴다(40자 이내): %s" % name)
    if name.lower() in BOOL_KEYS:
        die("이름에 YAML 불리언 토큰을 쓸 수 없다: %s" % name)


def _steps_problems(steps, jobs):
    """등록 시점 **실존** 검증 — 경로·커맨드·잡. 문제 목록을 돌려준다(빈 목록 = 통과).

    load() 는 구조만 본다(스크립트 하나가 지워져도 전체 dispatch 가 죽지 않게).
    실존은 사람이 저장 버튼을 누르는 이 시점에 fail-loud 로 본다.
    """
    bad = []
    names = None
    for n, st in enumerate(steps, 1):
        kind = st.get("kind")
        if kind == "script":
            path = expand(str(st.get("path", "")).replace("{arg}", ""))
            if not os.path.isfile(path):
                bad.append("#%d script 경로 없음: %s" % (n, st.get("path")))
        elif kind == "scar":
            if names is None:
                names = set()
            cwd = expand(str(st.get("cwd") or "~/.claude"))
            cmd = str(st.get("cmd", "")).strip().lstrip("/").split()[0] if st.get("cmd") else ""
            if cmd and not _scar_exists(cmd, cwd):
                bad.append("#%d 커맨드·스킬 없음: /%s (cwd %s)" % (n, cmd, st.get("cwd") or "~/.claude"))
        elif kind == "job":
            if st.get("ref") not in jobs:
                bad.append("#%d 없는 잡: %s" % (n, st.get("ref")))
    return bad


def _build_job(o, base=None):
    """CLI 인자 → 잡 dict. base 가 있으면 그 위에 덮는다(job-edit)."""
    import json
    job = dict(base or {})
    if o.get("run") is not None and o.get("steps_json") is not None:
        die("--run 과 --steps-json 은 함께 줄 수 없다 — 한 잡의 정본은 하나다")
    if o.get("run") is not None:
        job.pop("steps", None)
        job.pop("on_error", None)
        job["run"] = o["run"]
    if o.get("steps_json") is not None:
        try:
            steps = json.loads(o["steps_json"])
        except ValueError as e:
            die("--steps-json 파싱 실패: %s" % e)
        if not isinstance(steps, list) or not steps:
            die("--steps-json 은 비어 있지 않은 배열이다")
        clean = []
        for st in steps:
            if not isinstance(st, dict):
                die("--steps-json 항목이 객체가 아니다: %r" % (st,))
            clean.append({k: v for k, v in st.items() if v not in (None, "")})
        job.pop("run", None)
        job["steps"] = clean
    for k, cast in (("cwd", str), ("log", str), ("timeout", int), ("lock", str),
                    ("desc", str), ("on_error", str)):
        if o.get(k) is not None:
            if str(o[k]) == "":
                job.pop(k, None)             # 빈 값 = 지운다
            else:
                job[k] = cast(o[k])
    job.pop("oneshot", None)                 # prj3#Issue691: 신규 기록 안 함(읽기 호환만)
    return job


def _add_bindings(name, o, events, u_events, u_bindings, existing=()):
    """--at·--every 반복 → 사용자 바인딩 추가. (만든 목록, 새 이벤트 여부)."""
    made, new_event, seen = [], False, set(existing)
    for kind in ("every", "at"):
        for raw in (o.get(kind) or []):
            spec, arg = _parse_when(kind, raw)
            ev_name = _find_event(events, kind, spec)
            if ev_name is None:              # 같은 시각이 없을 때만 새로 만든다
                new_event = True
                ev_name = _event_name_for(kind, spec)
                if ev_name in events:
                    die("이벤트 이름이 이미 있다: %s" % ev_name)
                if kind == "every":
                    u_events[ev_name] = {"type": "timer", "every": _Quoted(spec)}
                else:
                    u_events[ev_name] = _calendar_event(spec)
                events = dict(events, **{ev_name: u_events[ev_name]})
            if ev_name in seen:
                die("같은 시각을 두 번 걸었다: %s (%s)" % (spec, ev_name))
            seen.add(ev_name)
            b = {"event": ev_name, "job": name}
            if arg or o.get("arg"):
                b["arg"] = arg or o["arg"]
            u_bindings.append(b)
            made.append(ev_name + ("(%s)" % b["arg"] if b.get("arg") else ""))
    return made, new_event


def _drop_orphan_events(u_events, u_bindings):
    """바인딩이 사라진 **사용자** 이벤트를 치운다 — 시스템 이벤트는 다른 잡이 쓴다."""
    _, _, sys_bindings = _read_decl(YML, required=True)
    still = {b["event"] for b in sys_bindings if isinstance(b, dict) and "event" in b}
    still |= {b["event"] for b in u_bindings if isinstance(b, dict)}
    dropped = [e for e in list(u_events) if e not in still]
    for e in dropped:
        u_events.pop(e, None)
    return dropped


def _bootout(dropped, o):
    """선언에서 사라진 이벤트는 등재도 걷는다(고아 유닛 방지)."""
    if dropped and backend_name() == "launchd" and not o.get("no_write"):
        for e in dropped:
            launchctl("bootout", "gui/%d/%s" % (os.getuid(), label_of(e)))
            path = plist_path(e)
            if os.path.exists(path):
                os.unlink(path)


def cmd_user(argv):
    """UI 가 쓰는 선언의 CRUD. 잡(무엇을)·바인딩(언제)을 **따로** 다룬다 (prj3#Issue691).

      list [--json]
      job-add  --name N (--run CMD | --steps-json '[…]') [--desc --cwd --timeout --lock --on-error]
      job-edit --name N [위와 같은 필드 — 준 것만 바꾼다. 빈 값은 지운다]
      bind     --job J --at HH:MM[=arg] | --every 5m[=arg]  (반복 가능)
      unbind   --job J --event E
      note     --job J --event E --desc TEXT   # 스케줄 1건 설명 (빈 값 = 지움)
      pause|resume --name J [--event E]   # 잡 전체 또는 그 잡의 스케줄 1건
      add      --name N --run CMD (--at|--every|--manual)  # 종전 계약 = job-add + bind
      remove   --name N [--cascade] [--replacing]  # 스케줄·mq 예약이 걸려 있으면 거부(Issue701)
    """
    if not argv:
        die("user list|job-add|job-edit|bind|unbind|note|pause|resume|add|remove — 서브커맨드가 필요하다")
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
        print("%-20s %-16s %s" % ("JOB", "WHEN", "RUN"))
        for name in sorted(u_jobs):
            j = _job_dict(u_jobs[name])
            evs = [b["event"] + ("⏸" if _is_paused(b) else "")
                   for b in u_bindings if b.get("job") == name]
            when = ",".join(evs) if evs else "수동"
            what = j.get("run") or "steps×%d" % len(j.get("steps") or [])
            print("%-20s %-16s %s%s" % (name, when, what, "  ⏸" if _is_paused(j) else ""))
        return

    o = _kv(rest)

    if sub in ("job-add", "add"):
        name = o.get("name")
        _check_name(name)
        if o.get("run") is None and o.get("steps_json") is None:
            die("%s 에는 --run 또는 --steps-json 이 필요하다" % sub)
        events, jobs, _, src, u_events, u_jobs, u_bindings, backup = _user_begin()
        if name in jobs:
            owner = src["jobs"][name]
            die("이미 있는 잡이다: %s (%s 선언)%s" %
                (name, owner, " — 시스템 잡은 UI 로 바꿀 수 없다" if owner == "system" else ""))
        if sub == "add":
            if o.get("manual") and (o.get("at") or o.get("every")):
                die("--manual 은 시각과 함께 줄 수 없다")
            if not o.get("manual") and not (o.get("at") or o.get("every")):
                die("실행시각이 없다 — --every 5m · --at 02:00 · --manual 중 하나를 준다")
        elif o.get("at") or o.get("every"):
            die("job-add 는 시각을 받지 않는다 — 잡을 만든 뒤 `user bind` 로 건다")
        job = _build_job(o)
        probs = _steps_problems(job.get("steps") or [], dict(jobs, **{name: job}))
        if probs:
            die("스텝 검증 실패 — %s" % " · ".join(probs))
        made, new_event = _add_bindings(name, o, events, u_events, u_bindings)
        u_jobs[name] = job
        _user_commit(u_events, u_jobs, u_bindings, backup)
        print("user %s: %s → %s" % (sub, name, " + ".join(made) or "잡만(스케줄 없음)"))
        if not o.get("no_write"):
            _post_write(new_event)           # 재사용이면 유닛이 이미 있다
        return

    if sub == "job-edit":
        name = o.get("name")
        events, jobs, _, src, u_events, u_jobs, u_bindings, backup = _user_begin()
        _require_user_job(name, jobs, src, "수정")
        job = _build_job(o, base=_job_dict(u_jobs[name]))
        probs = _steps_problems(job.get("steps") or [], dict(jobs, **{name: job}))
        if probs:
            die("스텝 검증 실패 — %s" % " · ".join(probs))
        u_jobs[name] = job
        _user_commit(u_events, u_jobs, u_bindings, backup)
        print("user job-edit: %s" % name)
        return

    if sub == "bind":
        name = o.get("job")
        events, jobs, _, src, u_events, u_jobs, u_bindings, backup = _user_begin()
        _require_user_job(name, jobs, src, "스케줄")
        if not (o.get("at") or o.get("every")):
            die("bind 에는 --at 또는 --every 가 필요하다")
        have = [b["event"] for b in u_bindings if b.get("job") == name]
        made, new_event = _add_bindings(name, o, events, u_events, u_bindings, existing=have)
        _user_commit(u_events, u_jobs, u_bindings, backup)
        print("user bind: %s → %s" % (name, " + ".join(made)))
        if not o.get("no_write"):
            _post_write(new_event)
        return

    if sub == "unbind":
        name, ev = o.get("job"), o.get("event")
        if not ev:
            die("unbind 에는 --job 과 --event 가 필요하다")
        events, jobs, _, src, u_events, u_jobs, u_bindings, backup = _user_begin()
        _require_user_job(name, jobs, src, "스케줄 해제")
        keep = [b for b in u_bindings if not (b.get("job") == name and b.get("event") == ev)]
        if len(keep) == len(u_bindings):
            die("걸린 스케줄이 없다: %s @ %s" % (name, ev))
        dropped = _drop_orphan_events(u_events, keep)
        _user_commit(u_events, u_jobs, keep, backup)
        _bootout(dropped, o)
        print("user unbind: %s @ %s%s" % (name, ev,
              " (이벤트 %s 도 정리)" % ", ".join(dropped) if dropped else ""))
        return

    if sub == "note":
        # 스케줄(바인딩) 1건의 설명 — 같은 잡이라도 시각마다 뜻이 다르다(daily-digest 아침·취침).
        #   잡 desc 는 «무엇을», 바인딩 desc 는 «이 시각에 왜» 다. 빈 값 = 지운다
        name, ev = o.get("job"), o.get("event")
        if not ev or "desc" not in o:
            die("note 에는 --job · --event · --desc 가 필요하다 (빈 --desc \"\" 는 지운다)")
        desc = str(o["desc"]).strip()
        if "\n" in desc or len(desc) > 200:
            die("설명은 한 줄 200자 이내다")
        events, jobs, _, src, u_events, u_jobs, u_bindings, backup = _user_begin()
        _require_user_job(name, jobs, src, "설명")
        targets = [b for b in u_bindings if b.get("job") == name and b.get("event") == ev]
        if not targets:
            die("걸린 스케줄이 없다: %s @ %s" % (name, ev))
        for t in targets:
            if desc:
                t["desc"] = desc
            else:
                t.pop("desc", None)
        _user_commit(u_events, u_jobs, u_bindings, backup)
        print("user note: %s @ %s%s" % (name, ev, " — 설명 지움" if not desc else ""))
        return

    if sub in ("pause", "resume"):
        # 멈춤은 선언의 속성이다 — launchd 유닛을 내리면 같은 이벤트를 쓰는 다른 잡까지 멈춘다
        name, ev = o.get("name"), o.get("event")
        events, jobs, _, src, u_events, u_jobs, u_bindings, backup = _user_begin()
        _require_user_job(name, jobs, src, "멈춤·재개")
        want = (sub == "pause")
        if ev:
            targets = [b for b in u_bindings if b.get("job") == name and b.get("event") == ev]
            if not targets:
                die("걸린 스케줄이 없다: %s @ %s" % (name, ev))
        else:
            if not isinstance(u_jobs[name], dict):
                u_jobs[name] = {"run": u_jobs[name]}
            targets = [u_jobs[name]]
        if all(_is_paused(t) == want for t in targets):
            print("user %s: %s%s — 이미 %s 상태다" % (sub, name, " @ " + ev if ev else "",
                                                  "멈춤" if want else "실행"))
            return
        for t in targets:
            if want:
                t["paused"] = True
            else:
                t.pop("paused", None)
        _user_commit(u_events, u_jobs, u_bindings, backup)
        # ledger 는 **전환 때 1줄**만 — 멈춘 동안의 skip 은 쓰지 않는다(10분 주기면 하루 144줄 소음)
        ledger_write(ev or "-", name, "rc=%s" % sub, "scope=%s" % ("binding" if ev else "job"))
        print("user %s: %s%s" % (sub, name, " @ " + ev if ev else ""))
        return

    if sub == "remove":
        name = o.get("name")
        events, jobs, _, src, u_events, u_jobs, u_bindings, backup = _user_begin()
        if not name:
            die("remove 에는 --name 이 필요하다")
        if name not in jobs:
            die("없는 잡이다: %s" % name)
        if src["jobs"][name] != "user":
            die("시스템 잡은 지울 수 없다: %s — `data/schedule.yml` 은 사람이 편집한다" % name)
        users = [j for j, v in u_jobs.items() if j != name and any(
            st.get("kind") == "job" and st.get("ref") == name for st in _job_steps(v))]
        if users:
            die("다른 잡이 스텝으로 지목한다: %s — 먼저 그 잡에서 빼야 한다" % ", ".join(users))
        # prj3#Issue701 — 걸려 있는 것을 **조용히 같이 지우지 않는다.** 종전에는 스케줄을 함께
        #   치웠고(예약 실행이 소리 없이 사라짐) mq 큐 예약은 보지도 않았다(due 에 없는 잡을 부름).
        #   ① 스케줄 — `--cascade` 를 줘야 함께 지운다(종전 동작을 명시 선택으로)
        #   ② 큐 예약 — `--cascade` 로도 풀리지 않는다. 큐는 이 파일의 소관이 아니라 지울 수 없고,
        #      남겨 두면 due 에 실패한다. `--replacing`(같은 이름으로 즉시 재생성 — hub 수정 경로)만 통과
        bound = sorted({b.get("event") for b in u_bindings if b.get("job") == name})
        if bound and not o.get("cascade"):
            die("스케줄에 걸려 있다: %s — 먼저 `user unbind --job %s --event <E>` 로 풀거나, "
                "스케줄까지 함께 지우려면 --cascade" % (", ".join(bound), name))
        queued = [] if o.get("replacing") else _mq_job_refs(name)
        if queued:
            die("mq 큐에 이 잡의 예약이 있다: %s — 먼저 hub /mq 또는 aoa_mq_ack 로 그 예약을 "
                "종결(dismissed)해야 한다" % ", ".join(queued))
        u_jobs.pop(name, None)
        u_bindings = [b for b in u_bindings if b.get("job") != name]
        dropped = _drop_orphan_events(u_events, u_bindings)
        _user_commit(u_events, u_jobs, u_bindings, backup)
        _bootout(dropped, o)
        print("user remove: %s%s" % (name,
              " (이벤트 %s 도 정리)" % ", ".join(dropped) if dropped else ""))
        return

    die("알 수 없는 user 서브커맨드: %s (list|job-add|job-edit|bind|unbind|note|pause|resume|add|remove)" % sub)


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
    elif cmd == "catchup":           # prj3#Issue878 — 부팅 보충
        cmd_catchup(argv)
    elif cmd == "dispatch":
        cmd_dispatch(argv)
    elif cmd == "user":
        cmd_user(argv)
    elif cmd == "catalog":           # prj3#Issue691 — 잡 스텝 후보
        cmd_catalog(argv)
    elif cmd == "job":               # prj3#Issue691 — job suggest
        cmd_job(argv)
    elif cmd == "check-load":        # 내부 전용 — 쓰기 후 merge 검증(prj3#Issue579)
        load()
    else:
        die("알 수 없는 서브커맨드: %s" % cmd)


if __name__ == "__main__":
    main()
