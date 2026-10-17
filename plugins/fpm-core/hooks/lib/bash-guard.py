#!/usr/bin/env python3
"""bash-guard.py — PreToolUse Bash 가드 레지스트리 (prj3#Issue950 — 구 outer-agent-direct-guard·pkill-order-guard·file-loss-guard 통합)

⚠️ 글로벌 SCAR 변경 가드: 모든 프로젝트가 공유. cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md

Bash 명령 문자열만으로 판정되는 가드의 **판정 단일 지점**이다. 진입점은 둘이고 둘 다 이 파일을 부른다:
  * mod  ~/.claude/mods/bash-guard (classic.PreToolUse) — in-process prefilter 가 걸린 호출만 `$.process.run` 으로 넘긴다
  * 폴백 hooks/bash-guard.sh (settings PreToolUse Bash) — mod 가 로드되지 않은 프로세스에서만 판정한다

사용:
  python3 bash-guard.py              stdin = settings PreToolUse 입력 JSON → 결정이 있으면 hookSpecificOutput JSON 1줄, 없으면 무출력
  python3 bash-guard.py --prefilter  가드별 prefilter 정규식 JSON (JS 정규식 호환 — lookbehind 금지)

가드 추가: 아래 GUARDS 에 Guard(name, pattern, judge) 한 줄. judge(cmd, ctx) → ("deny"|"ask"|"warn", 사유) 또는 None.
  ctx = {cwd, session_id(훅 입력 — 없으면 None)} · warn = 결정 없는 경고(additionalContext 만, 차단 없음 — prj3#Issue1000)
  pattern 은 «명령 + "\n" + cwd» 텍스트에 대해 검사한다(mod 도 같은 텍스트로 검사) — 그 가드가 판정할 수 있는 모든 호출에
  걸려야 한다(누락 = 판정 없이 통과). 넓은 것은 비용일 뿐이다.
  폴백 hooks/bash-guard.sh 의 `case` 무비용 가드도 같이 넓힌다 — 거기 빠진 키워드는 mod 미로드 시 판정되지 않는다.
합성: deny 가 하나라도 있으면 첫 deny, 없으면 첫 ask, 없으면 첫 warn (settings 다중 hook 의 deny > ask 와 같다).
실패: 가드 하나가 예외를 내면 그 가드만 통과(fail-open) — 종전엔 가드마다 프로세스가 따로라 서로 영향이 없었다. 입력 파싱 실패도 통과.
"""
import fnmatch, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # ~/.claude
sys.path.insert(0, HERE)
import shcmd                                           # heredoc·주석·래퍼·예약어·줄 경계 판정 단일 지점 (prj3#Issue699)


class Guard:
    def __init__(self, name, pattern, judge):
        self.name, self.pattern, self.judge = name, pattern, judge


# ───────────────────────── outer-agent — 외부 LLM CLI 직접 호출 차단 (prj3#Issue690 → Issue708 · 표 Issue711) ─────────────────────────
# 명령어 자리에 외부 LLM CLI(`codex`·`agy`)가 오고 인자가 제공자별 허용 목록 밖 → deny.
# 왜 deny 인가: 직접 호출은 가용성 판정·rc 0 오류 문자열 판별·폴백·사용 원장·엔진 표기를 **전부** 건너뛴다.
#   래퍼로 가는 길이 늘 열려 있으므로 막아도 할 수 없게 되는 일이 없다 — ask 가 아니라 deny.
# 제공자 표는 인벤토리 SSOT(data/outer-agent/inventory.json providers.<p>.guard). 못 읽으면 fail-open — 부재·손상은 sh/outer-inventory.py --check 가 잡는다

def _providers():
    path = os.environ.get("OUTER_INVENTORY") or os.path.join(ROOT, "data", "outer-agent", "inventory.json")
    try:
        inv = json.load(open(path, encoding="utf-8"))
        return {pv["bin"]: dict(pv["guard"], allow=set(pv["guard"]["allow"])) for pv in inv["providers"].values()}
    except Exception as e:
        print(f"[bash-guard outer-agent] 인벤토리를 못 읽어 통과시킨다(fail-open): {e}", file=sys.stderr)
        return {}


def _outer_pattern():
    bins = sorted(_providers())
    return "|".join(re.escape(b) for b in bins) if bins else "(?!)"   # 인벤토리 부재면 판정도 fail-open 이라 걸 것이 없다


def judge_outer(cmd, ctx):
    providers = _providers()
    if not providers or not any(p in cmd for p in providers):
        return None
    # heredoc 본문(셸 인터프리터가 받는 것 제외)·주석은 명령어 자리가 아니다 (prj3#Issue699_3 — md 표 행 «| codex …» 오탐)
    segs = shcmd.simple_commands(cmd)
    if segs is None:
        segs = [cmd.split()]
    for s in segs:
        # 예약어(`then`·`{`·`!`)·대입·옵션 달린 래퍼(`sudo -u x`·`env -u`)를 건너뛴 명령어 자리 (prj3#Issue792)
        w, args = shcmd._mut_resolve(s)
        p = providers.get(w)
        if not p:
            continue
        if (args[0] if args else "") in p["allow"]:
            continue
        frag = " ".join([w] + args[:2])
        return ("deny", "[%s 직접 호출 차단 — %s] `%s` 는 %s 을 건너뛴다. %s 는 공통 래퍼로만 부른다: %s. 버전·도움말 등 허용 인자(%s)는 통과한다."
                % (w, p["issue"], frag, p["skips"], w, p["how"], "·".join(sorted(p["allow"]))))
    return None


# ───────────────────────── pkill-order — BSD pkill·pgrep·kill 광역 kill 차단 (prj3#Issue716 · Issue729 · Issue798) ─────────────────────────
# 명령어 자리가 `pkill`·`pgrep`·`killall`·`kill` 인 단순 명령 (복합·`$(…)`·backtick·`bash -c`·`eval` 문자열 안 포함)
#   deny ① 첫 비옵션 인자(패턴) 뒤에 토큰이 더 있음 (Issue716)
#   deny ② 패턴이 숫자뿐 · 정규식 메타를 뺀 글자가 3자 미만(`-x` 면 길이 면제) · `pkill -v` (Issue729)
#   ask  ③ `killall` — 이름 단위 전역 종료 (Issue729). 같은 명령에 deny 가 있으면 deny 가 이긴다
#   deny ④ 패턴 없는 `pkill` 이 `-P 0|1` 이거나 `-u`·`-U`·`-g`·`-G` 만으로 고름 (Issue798)
#   deny ⑤ `kill` 의 PID 자리 `-1` (Issue798)
# 왜 deny 인가: macOS BSD pkill·pgrep 은 첫 비옵션 인자 이후를 **전부 패턴(OR)** 으로 읽는다 — 2026-09-27 18:08
#   `pkill -f "node app.js" -P 1` 로 VSCode·tmux Claude 세션 전부 SIGTERM(143). 되돌릴 수 없는 광역 kill 이고 안전한 형태가 있다.

PKILL_PATTERN = r"pkill|pgrep|killall|(^|[^A-Za-z0-9_-])kill(\s|$)"   # 단어 `kill` — `skills/`·`kill-server` 는 아니다
VALUE_OPTS = set("FGgjMNPstUu")                        # BSD pkill·pgrep 에서 값을 받는 옵션
SIGNAL = re.compile(r"-(\d+|(SIG)?[A-Z][A-Z0-9]+)$")   # pkill 첫 인자 시그널(-9 · -HUP · -SIGTERM). 이름은 2자 이상 — 한 글자 대문자는 옵션(-P·-F·-U)
REGEX_META = re.compile(r"[.^$*+?()\[\]{}|\\]")       # 길이 판정에서 뺄 정규식 메타 — `.*`·`^ab$` 는 사실상 전부 일치
VARIABLE = re.compile(r"\$(\{|\(|[A-Za-z_0-9@*#?!-])|`")   # 셸 변수·치환 — 실행 시점 값이라 길이 판정 불가
SHELL_C = re.compile(r"-[a-zA-Z]*c[a-zA-Z]*$")         # `bash -c`·`bash -lc`
KILL_SIG = re.compile(r"-(\d+|[A-Za-z]+\d*)$")         # kill 의 시그널 자리(-9 · -KILL · -SIGTERM) · -l/-L(목록)도 같은 자리


def _pk_parse(args, is_pkill):
    """(패턴 또는 None, 패턴 뒤 토큰들, 패턴 앞 단일문자 플래그 집합, 값 옵션의 값 {옵션: 값})."""
    i, flags, vals = 0, set(), {}
    if is_pkill and args and SIGNAL.match(args[0]):
        i = 1
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if not a.startswith("-") or a == "-":
            break
        for k, ch in enumerate(a[1:]):
            flags.add(ch)
            if ch in VALUE_OPTS:
                if k == len(a) - 2:                    # 값이 다음 토큰(-P 1). 붙임형(-P1)은 이 토큰 안에서 끝
                    i += 1
                    vals[ch] = args[i] if i < len(args) else ""
                else:
                    vals[ch] = a[k + 2:]
                break
        i += 1
    if i >= len(args):
        return None, [], flags, vals
    return args[i], args[i + 1:], flags, vals


def _pk_broad(argv, flags, vals):
    """패턴 없는 pkill 의 값 기반 광역 판정 (Issue798) — deny 사유 또는 None."""
    ppid = (vals.get("P") or "").strip()
    if re.fullmatch(r"[01]", ppid):
        return ("[pkill 광역 kill 차단 — Issue798] `%s` 는 패턴 없이 부모 PID `%s` 만 주었다. launchd(1) 의 자식은 사용자 최상위 프로세스 "
                "**전부**(터미널·에디터·모든 Claude 세션)라 로그아웃과 같다. 죽일 프로세스를 이름으로 가리켜라(ex) `pkill -P 1 -x <이름>`) — "
                "자기 자식만이면 `pkill -P $$`. 먼저 `pgrep -lP 1` 로 대상 목록을 확인하라." % (argv, ppid))
    if {"u", "U", "g", "G"} & flags and not ({"t", "s", "F", "P"} & flags):
        return ("[pkill 광역 kill 차단 — Issue798] `%s` 는 패턴 없이 사용자·그룹만 주었다 — 그 사용자의 **모든** 프로세스"
                "(터미널·에디터·모든 Claude 세션)가 대상이라 로그아웃과 같다. 이름 패턴을 함께 주거나(ex) `pkill -u <user> -x <이름>`) "
                "`-P <ppid>`·`-t <tty>`·`-F <pidfile>` 로 좁혀라. 먼저 `pgrep -lu <user>` 로 대상 목록을 확인하라." % argv)
    return None


def _pk_judge_kill(args):
    """`kill` 한 호출의 deny 사유 (Issue798) — PID 자리에 `-1` 이 있으면 시그널 가능한 전 프로세스."""
    i = 0
    if i < len(args) and args[i] in ("-s", "-n"):
        i += 2
    elif i < len(args) and KILL_SIG.match(args[i]):
        if args[i] in ("-l", "-L"):
            return None
        i += 1
    if i < len(args) and args[i] == "--":
        i += 1
    if "-1" in args[i:]:
        return ("[kill 광역 차단 — Issue798] `%s` 의 PID `-1` 은 «시그널을 보낼 수 있는 **모든** 프로세스» 다 — 사용자 전 프로세스"
                "(터미널·에디터·모든 Claude 세션)가 죽어 로그아웃과 같다. PID 를 지정하거나(`kill <pid>`), 이름이면 `pkill -x <이름>`, "
                "프로세스 그룹이면 `kill -- -<pgid>` 로 좁혀라. 먼저 `pgrep -fl <이름>` 으로 대상을 확인하라." % " ".join(["kill"] + args))
    return None


def _pk_substs(src):
    """명령 치환 본문(`$(…)`·backtick) — 홑따옴표 안은 문자열이라 뺀다. 큰따옴표 안은 셸이 실행한다."""
    out, q, i, n = [], None, 0, len(src)
    while i < n:
        c = src[i]
        if q == "'":
            q = None if c == "'" else q
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        if c == "'" and q is None:
            q = c
        elif c == '"':
            q = None if q == '"' else '"'
        elif c == "`":
            j = src.find("`", i + 1)
            if j < 0:
                break
            out.append(src[i + 1:j])
            i = j + 1
            continue
        elif src.startswith("$(", i) and not src.startswith("$((", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(src[j], 0)
                j += 1
            out.append(src[i + 2:j - 1])
            i = j
            continue
        i += 1
    return out


def _pk_judge(w, args):
    """pkill·pgrep 한 호출의 deny 사유 (없으면 None)."""
    argv = " ".join([w] + args)
    pat, extra, flags, vals = _pk_parse(args, w == "pkill")
    if extra:
        return ("[%s 인자 순서 차단 — Issue716] `%s` 에서 패턴 뒤의 `%s` 는 옵션이 아니라 **추가 패턴(OR)** 으로 읽힌다(macOS BSD). "
                "명령줄에 그 문자열이 든 사용자 프로세스 전부가 대상이 된다 — 2026-09-27 `pkill -f \"node app.js\" -P 1` 로 전 Claude 세션이 SIGTERM 됐다. "
                "옵션을 모두 패턴 **앞**으로 옮겨라(ex) `%s -P 1 -f \"node app.js\"`). 패턴이 여럿이면 명령을 나누거나 정규식 하나(`a|b`)로 합친다. "
                "먼저 `pgrep -fl <같은 인자>` 로 대상 목록을 확인하는 것을 권한다." % (w, argv, " ".join(extra), w))
    if w == "pkill" and "v" in flags:
        return ("[pkill 반전 일치 차단 — Issue729] `%s` 의 `-v` 는 패턴에 **맞지 않는** 프로세스 전부를 죽인다. "
                "죽일 대상을 직접 가리키는 패턴으로 바꾸고, 먼저 `pgrep -fl <패턴>` 으로 목록을 확인하라." % argv)
    if pat is None:                                    # 필터형 — pgrep 은 조회라 밖, pkill 은 값의 광역성을 본다(Issue798)
        return _pk_broad(argv, flags, vals) if w == "pkill" else None
    pat = pat.rstrip("`")
    if re.fullmatch(r"\d+", pat):
        return ("[%s 숫자 패턴 차단 — Issue729] `%s` 의 패턴 `%s` 는 숫자뿐이다. pkill·pgrep 패턴은 PID 가 아니라 프로세스 이름"
                "(`-f` 면 명령줄 전체)의 **부분 일치**라 그 숫자가 든 프로세스 전부가 대상이 된다(`pgrep -f 1` = 322건 실측). "
                "PID 를 지정하려면 `kill <pid>`, 부모로 좁히려면 `-P <ppid>` 를 패턴 앞에 두고 구체적인 이름 패턴을 함께 준다." % (w, argv, pat))
    if VARIABLE.search(pat) or "x" in flags:
        return None                                    # 변수 패턴은 판정 불가 · `-x` 는 정확 일치라 짧아도 좁다
    lit = len(REGEX_META.sub("", pat))
    if lit < 3:
        return ("[%s 짧은 패턴 차단 — Issue729] `%s` 의 패턴 `%s` 는 정규식 메타를 빼면 %d자뿐이라 너무 많은 프로세스와 부분 일치한다. "
                "3자 이상의 구체적 이름을 쓰거나, 정확 일치 `-x` 를 붙이거나, `-P <ppid>`·`-u <user>` 를 패턴 앞에 더해 좁혀라. "
                "먼저 `pgrep -fl <패턴>` 으로 대상 목록을 확인하라." % (w, argv, pat, lit))
    return None


def _pk_scan(src, depth=0):
    """(deny 사유 또는 None, killall 호출 문자열 또는 None). 치환·셸 문자열은 depth 3 까지 따라간다."""
    if depth > 3:
        return None, None
    ask = None
    for body in _pk_substs(shcmd.normalize(src)):
        d, a = _pk_scan(body, depth + 1)
        if d:
            return d, a
        ask = ask or a
    for s in shcmd.simple_commands(src) or []:        # 파싱 실패 → 이 층은 fail-open
        w, args = shcmd._mut_resolve(s)                # 예약어(`{`·`then`)·대입·옵션 달린 래퍼(`sudo -u`)를 건너뛴 명령어 자리
        inner = None
        if w in shcmd.SHELLS:
            k = next((k for k, a in enumerate(args) if SHELL_C.match(a)), None)
            inner = args[k + 1] if k is not None and k + 1 < len(args) else None
        elif w == "eval":
            inner = " ".join(args)
        if inner:
            d, a = _pk_scan(inner, depth + 1)
            if d:
                return d, a
            ask = ask or a
            continue
        if w == "killall":
            ask = ask or " ".join([w] + args)
        elif w in ("pkill", "pgrep"):
            d = _pk_judge(w, args)
            if d:
                return d, ask
        elif w == "kill":
            d = _pk_judge_kill(args)
            if d:
                return d, ask
    return None, ask


def judge_pkill(cmd, ctx):
    if not re.search(PKILL_PATTERN, cmd):
        return None
    deny, ask = _pk_scan(cmd)
    if deny:
        return ("deny", deny)
    if ask:
        return ("ask", "[killall 확인 — Issue729] `%s` 는 이름이 같은 **모든** 프로세스(다른 세션·다른 창 포함)를 종료한다. "
                       "먼저 `pgrep -lx <이름>` 으로 대상을 확인하고, 특정 프로세스만이면 `kill <pid>` 또는 `pkill -P <ppid> -x <이름>` 으로 좁혀라." % ask)
    return None


# ───────────────────────── file-loss — 명령 문자열로 판정되는 파일 유실 2종 차단 (prj3#Issue787) ─────────────────────────
#   ① (Issue787_1) python 을 부르는 명령에서 `open(X,'w')` 뒤 **같은 문장**이 X 를 읽음 — heredoc 본문·`-c` 인자 모두
#   ② (Issue787_2) 공용 수면 로그 `.sleep-log/YYYY-MM-DD.md`(와 그 폴더)를 `>>` 밖으로 건드림
# 왜 deny 인가(fail-loud — 규칙4 «데이터 유실 위험»): 둘 다 되돌릴 수 없는 유실이고, 같은 의도를 안전하게 쓰는 형태가 있다.
# ⚠️ 명령 문자열 기반 — 변수로 조립한 명령·스크립트 파일은 보이지 않는다. 우회 불가능한 봉쇄가 아니라 기본 경로에서 사고 형태를 멈추는 장치다.

FILELOSS_PATTERN = r"open\(|\.sleep-log"


def judge_fileloss(cmd, ctx):
    if not re.search(FILELOSS_PATTERN, cmd + "\n" + ctx["cwd"]):   # 세션 cwd 가 로그 폴더면 `rm 2026-09-29.md` 도 대상이다
        return None
    x = shcmd.write_then_read(cmd)
    if x:
        return ("deny", "[쓰기 후 읽기 차단 — Issue787_1] 파이썬 `open(%s, \"w\")` 는 **인자를 평가하기 전에** 파일을 비운다 — 같은 문장에서 "
                        "`%s` 를 읽으면 빈 내용을 읽어 빈 파일을 쓴다(Issue719 Issue.md · Issue745 debug_TECH.md 0바이트, 타 세션 미커밋분 유실). "
                        "읽기를 먼저 별도 문장으로 하라: `s = open(%s).read()` 다음 줄에 `open(%s, \"w\").write(f(s))`. "
                        "또는 `Path(%s).write_text(f(Path(%s).read_text()))` — write_text 는 인자를 먼저 평가한다." % (x, x, x, x, x, x))
    t = shcmd.sleeplog_clobbers(cmd, ctx["cwd"])
    if t:
        return ("deny", "[공용 수면 로그 보호 — Issue787_2] `%s` 는 여러 세션이 append 하는 공용 로그(`.sleep-log/YYYY-MM-DD.md`)다 — "
                        "삭제·이동·덮어쓰기는 그 사이 다른 세션이 쓴 줄을 지운다(2026-09-29 핀봇 워커 2회 `rm`, «내가 만든 새 파일» 로 오인). "
                        "기록은 `>>` 로만 한다(`echo … >> <로그>` · `tee -a`). 내 세션 로그는 `session_*.md` 이고 리뷰 뒤 `z_done/` 이관은 그 파일만 옮긴다. "
                        "공용 로그를 정말 정리해야 하면 사람에게 묻는다." % t)
    return None


# ───────────────────────── version-guard — 버전 번호 사람 승인 우회 차단 (prj1#Issue612 · prj3#Issue973) ─────────────────────────
#   ① 승인 명령(`fpm-version-approve`·`version-guard.sh approve`) — 명령어 자리·인자 어디든(tmux send-keys 로 남의 pane 에 치는 것 포함).
#      읽기 전용 명령(grep·cat·git 커밋 메시지 등)의 언급과 heredoc 본문은 통과
#   ② 승인 저장소(`version-approvals/`)를 읽기 전용 명령(VG_READONLY · 리다이렉트 없음) 밖에서 다룸 — 쓰기·삭제·이동
#   ③ 버전 가드가 설치된 repo(`git config versionGuard.group`)에서 pre-commit 우회 — `commit --no-verify`·`commit -n`·`core.hooksPath`
# 왜 deny 인가: 2026-10-05 세션이 «사용자 지시» 표기만으로 0.8.3 → 0.8.4 출고·0.8.5 라인 개시. 버전 번호는 사람만 정한다(H:배포) —
#   본체 approve 는 CLAUDECODE·TTY 로 이미 거부하지만, TTY 가 있는 남의 pane 으로 치거나 기록을 직접 쓰는 길은 명령 문자열에서만 보인다.
# ⚠️ 명령 문자열 기반 — 변수로 조립한 명령·스크립트 파일 안은 보이지 않는다. 사고 형태를 기본 경로에서 멈추는 장치다.

VG_PATTERN = r"version-approv|fpm-version-approve|version-guard|no-verify|hooksPath|commit\s[^\n;&|]*-[a-zA-Z]*n"
VG_APPROVE = re.compile(r"fpm-version-approve|version-guard\.sh['\"]?\s+approve")
VG_COMMIT_VALUE = set("mFcCt")                         # git commit 에서 값을 받는 단일문자 옵션 — `-mn` 의 n 은 메시지다
VG_HOW = ("버전 번호(라인 개시·VERSION 변경·번호를 바꾸는 출고)는 사람만 정한다 — H:배포. 사람에게 요청하라: "
          "일반 터미널(iTerm)에서 `fpm-version-approve <V>` (Claude 세션·TTY 없는 실행은 본체가 거부). "
          "«사용자 지시»·«사람 결정» 표기나 mq 기록은 승인이 아니다.")


def _vg_guarded(path):
    """path 를 품은 git repo 가 버전 가드 대상인가 — .git/config 의 [versionGuard] (git 기동 없이 파일만 읽는다)."""
    p = os.path.abspath(os.path.expanduser(path))
    while True:
        g = os.path.join(p, ".git")
        if os.path.isdir(g):
            cfg = os.path.join(g, "config")
        elif os.path.isfile(g):                        # worktree — gitdir: …/worktrees/<n> → commondir
            try:
                gd = open(g, encoding="utf-8").read().split("gitdir:", 1)[1].strip()
                gd = gd if os.path.isabs(gd) else os.path.join(p, gd)
                cd = os.path.join(gd, "commondir")
                common = os.path.join(gd, open(cd).read().strip()) if os.path.isfile(cd) else gd
                cfg = os.path.join(common, "config")
            except Exception:
                return False
        else:
            parent = os.path.dirname(p)
            if parent == p:
                return False
            p = parent
            continue
        try:
            return re.search(r"^\s*\[versionGuard\]", open(cfg, encoding="utf-8").read(), re.M | re.I) is not None
        except Exception:
            return False


def git_argv(args):
    """git 인자열(명령어 `git` 뒤) → (서브커맨드, 그 인자들, `-C` 경로들, `-c` 값들) — git 전역 옵션 해석 단일 지점.
    version-guard(`_vg_bypass`)·issue-sweep 이 공유한다(prj3#Issue1000 · Issue1009ⓔ 의 `git config` 판정도 여기서 받는다)."""
    paths, cfgs, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a in ("-C", "-c") and i + 1 < len(args):
            (paths if a == "-C" else cfgs).append(args[i + 1]); i += 2; continue
        if a.startswith("-"):
            i += 1; continue
        break
    return (args[i], args[i + 1:], paths, cfgs) if i < len(args) else ("", [], paths, cfgs)


def _config_writes(rest):
    """`git config` 인자열이 값을 바꾸는 형태인가 — 읽기(`git config core.hooksPath`·`--get*`·`--list`)는 아니다(Issue1009 ⓔ).
    쓰기 = 변경 플래그(--unset*·--add·--replace-all·--edit) 또는 --get* 없이 키 뒤에 값 인자가 더 있는 형태."""
    flags = [r for r in rest if r.startswith("-")]
    if any(f in ("--unset", "--unset-all", "--add", "--replace-all", "--edit", "-e", "--rename-section", "--remove-section")
           for f in flags):
        return True
    if any(f.startswith("--get") or f in ("--list", "-l") for f in flags):
        return False
    return len([r for r in rest if not r.startswith("-")]) >= 2


def _vg_bypass(args):
    """git 인자열에서 pre-commit 우회 형태 — (사유 조각, -C 경로 목록) 또는 (None, 경로)."""
    sub, rest, paths, cfgs = git_argv(args)
    for c in cfgs:
        if "hookspath" in c.lower():
            return "git -c %s" % c, paths
    if sub == "config" and any("hookspath" in r.lower() for r in rest) and _config_writes(rest):
        return "git config core.hooksPath", paths
    if sub != "commit":
        return None, paths
    j = 0
    while j < len(rest):
        r = rest[j]
        if r == "--no-verify":
            return "git commit --no-verify", paths
        if r == "--":
            break
        if r.startswith("-") and not r.startswith("--") and len(r) > 1:
            for k, ch in enumerate(r[1:]):
                if ch == "n":
                    return "git commit %s (-n = --no-verify)" % r, paths
                if ch in VG_COMMIT_VALUE:
                    if k == len(r) - 2:                # 값이 다음 토큰
                        j += 1
                    break
        j += 1
    return None, paths


VG_READONLY = {"git", "grep", "rg", "egrep", "fgrep", "cat", "head", "tail", "less", "more", "ls", "wc", "stat", "file",
               "diff", "bat", "glow", "jq", "yq", "awk"}   # 언급만 하는 명령 — 승인을 실행하거나 저장소에 쓸 수 없다(리다이렉트 제외)


def judge_version(cmd, ctx):
    if not re.search(VG_PATTERN, cmd):
        return None
    segs = shcmd.simple_commands(cmd)                  # heredoc 본문(파일에 쓰는 문서 속 언급)은 명령이 아니다
    if segs is None:
        segs = [cmd.split()]
    for s in segs:
        w, args = shcmd._mut_resolve(s)
        text = " ".join(s)
        ro = os.path.basename(w or "") in VG_READONLY and not any(t.startswith(">") or t.endswith(">") for t in s)
        if (VG_APPROVE.search(text) and not ro) or os.path.basename(w or "") == "fpm-version-approve":
            return ("deny", "[버전 승인 차단 — prj1#Issue612] Claude 는 버전 승인을 만들 수 없다(남의 터미널 pane 에 쳐 넣는 것 포함). " + VG_HOW)
        if "version-approvals" in text and not ro:
            return ("deny", "[버전 승인 저장소 보호 — prj1#Issue612] `version-approvals/` 는 사람이 `fpm-version-approve` 로만 쓴다. "
                            "조회는 `version-guard.sh list`. " + VG_HOW)
    cwd = ctx["cwd"]
    for s in segs:
        w, args = shcmd._mut_resolve(s)
        if w == "cd" and args:
            cwd = os.path.join(cwd, os.path.expanduser(args[0]))
            continue
        if w != "git":
            continue
        frag, paths = _vg_bypass(args)
        if not frag:
            continue
        target = os.path.join(cwd, os.path.expanduser(paths[-1])) if paths else cwd
        if _vg_guarded(target):
            return ("deny", "[pre-commit 우회 차단 — prj1#Issue612] `%s` — 이 저장소는 버전 가드 대상(prj1·prj3·prj8)이라 "
                            "pre-commit 을 건너뛰면 사람 승인 없는 버전 변경이 들어간다. 훅이 막으면 사유를 해소한다 — "
                            "버전 변경이면 %s" % (frag, VG_HOW))
    return None


# ───────────────────────── issue-sweep — 봇 몸체의 공유 Issue.md 쓸어담기 차단 (prj3#Issue1000) ─────────────────────────
# 대상: 명령어 자리 `git` 의 ① `add` 대상에 `Issue.md`·`-A`/`--all`·`.` ② `commit` 의 `-a`/`--all`·pathspec `Issue.md`
# 누구냐로 갈린다 — 봇 몸체(`FBOT_ID` · `/fbot-bind` 결속 슬롯 — fbot-ident `caller_bot` 단일 지점)면 deny, 사람 세션은 경고만(warn).
# 왜 deny 인가: 공유 `Issue.md` 는 여러 세션이 동시에 고친다 — 맨 `git add`·`commit -a` 는 남의 미커밋분까지 담는다
#   (2026-10-09 회고 워커 `2edea707` 이 타 세션 Issue922·HWM·결정사항·Issue536 을 실어 팀장 반려). 규칙10(Issue754)은 문서뿐이었고
#   pre-commit(Issue752)은 낡은 blob 만 거부한다. 안전한 길(`issue-tx.py commit`)이 늘 열려 있어 막아도 못 하게 되는 일이 없다.
#   사람은 직접 판단한다 — 경고만 한다.
# ③ (Issue1019) `add -u`/`--update`(=`commit -a`)·`Issue.md` 를 품은 디렉토리 pathspec·`Issue.md` 에 매치되는 glob 도 대상. `add -n`/`--dry-run` 은 인덱스를 안 바꾸니 통과.
# ⚠️ 명령 문자열 기반 — 변수로 조립한 명령·스크립트 안은 보이지 않는다. 디렉토리 판정은 `-C`·앞선 `cd` 로 추적한 경로 기준(파일시스템 실측).

IS_PATTERN = r"git\s[\s\S]*?(add|commit|stash)"
IS_COMMIT_VALUE = set("mFcCt")                         # git commit 에서 값을 받는 단일문자 옵션 — `-ma` 의 a 는 메시지다
IS_COMMIT_LONG_VALUE = {"--message", "--file", "--author", "--date", "--template", "--reuse-message", "--reedit-message",
                        "--fixup", "--squash", "--cleanup", "--trailer", "--pathspec-from-file"}
IS_HOW = "`python3 ~/.claude/sh/issue-tx.py commit --issues <N> -m … [내 파일…]`"


def _is_issue_md(tok):
    return os.path.basename(tok.rstrip("/")) == "Issue.md"


def _dir_has_issue_md(path):
    """디렉토리 하위(.git 제외)에 `Issue.md` 가 있는가 — 디렉토리 pathspec 이 그것을 쓸어담는다."""
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != ".git"]
        if "Issue.md" in files:
            return True
    return False


IS_STASH_READONLY = {"list", "show"}                   # 워킹트리를 안 건드리는 stash 서브커맨드


def _is_sweep(sub, rest, base=None):
    """`git <sub> <rest…>` 의 쓸어담기 형태 — 사유 조각 또는 None. base = pathspec 을 풀 작업 디렉토리(-C·cd 추적)."""
    if sub == "stash":                                  # 🌱#5(22차) 공유 워킹트리의 타 세션 미커밋분을 일시 제거·복원 — pop 실패 시 유실
        op = next((r for r in rest if not r.startswith("-")), "push")
        return None if op in IS_STASH_READONLY else "git stash %s" % op
    if sub == "add":
        if any(r in ("-n", "--dry-run") or (r.startswith("-") and not r.startswith("--") and "n" in r) for r in rest):
            return None                                # 인덱스를 안 바꾸는 dry-run (Issue1019 ②)
        for r in rest:
            if r in ("-A", "--all", "--no-ignore-removal", "--update") or (r.startswith("-") and not r.startswith("--") and ("A" in r or "u" in r)):
                return "git add %s" % r
            if r.startswith("-"):
                continue
            if r.rstrip("/") in (".", ""):
                return "git add ."
            if _is_issue_md(r):
                return "git add %s" % r
            if re.search(r"[*?\[]", r) and fnmatch.fnmatch("Issue.md", os.path.basename(r.rstrip("/"))):
                return "git add %s (glob → Issue.md)" % r
            if base is not None:
                full = os.path.join(base, os.path.expanduser(r))
                if os.path.isdir(full) and _dir_has_issue_md(full):
                    return "git add %s (디렉토리 → Issue.md 포함)" % r
        return None
    if sub != "commit":
        return None
    j, spec = 0, False
    while j < len(rest):
        r = rest[j]
        if spec or not r.startswith("-") or r == "-":
            if _is_issue_md(r):
                return "git commit … %s" % r
        elif r == "--":
            spec = True
        elif r == "--all":
            return "git commit --all"
        elif r.startswith("--"):
            if "=" not in r and r in IS_COMMIT_LONG_VALUE:
                j += 1
        else:
            for k, ch in enumerate(r[1:]):
                if ch == "a":
                    return "git commit %s (-a = 추적 파일 전부)" % r
                if ch in IS_COMMIT_VALUE:
                    if k == len(r) - 2:                # 값이 다음 토큰
                        j += 1
                    break
        j += 1
    return None


def _is_caller_bot(session_id):
    """호출 세션의 봇 id — fbot-ident `caller_bot`(FBOT_ID → 결속 슬롯). 훅 입력 session_id 가 있으면 그 세션의 슬롯을 본다."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fbot_ident", os.path.join(HERE, "fbot-ident.py"))
    ident = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ident)
    env = dict(os.environ)
    if session_id:
        env["CLAUDE_CODE_SESSION_ID"] = session_id
    return ident.caller_bot(env)


def judge_issue_sweep(cmd, ctx):
    if not re.search(IS_PATTERN, cmd):
        return None
    segs = shcmd.simple_commands(cmd)                  # heredoc 본문·문자열 속 언급은 명령이 아니다
    if segs is None:
        segs = [cmd.split()]
    frag = None
    cur = ctx.get("cwd") or os.getcwd()
    for s in segs:
        w, args = shcmd._mut_resolve(s)
        if w == "cd" and args:
            cur = os.path.join(cur, os.path.expanduser(args[0]))
            continue
        if w != "git":
            continue
        sub, rest, cpaths, _ = git_argv(args)
        base = cur
        for c in cpaths:
            base = os.path.join(base, os.path.expanduser(c))
        frag = _is_sweep(sub, rest, base)
        if frag:
            break
    if not frag:
        return None
    bot = _is_caller_bot(ctx.get("session_id"))
    if bot:
        return ("deny", "[공유 Issue.md 쓸어담기 차단 — prj3#Issue1000] 봇 몸체(%s)의 `%s` 는 다른 세션이 고치고 있는 미커밋분까지 커밋에 담는다"
                        "(2026-10-09 `2edea707` 이 타 세션 변경 4건을 실어 반려). 공유 `Issue.md`·내 파일은 %s 로만 커밋한다 — "
                        "내 이슈 블록과 지정 경로만 임시 인덱스로 올린다. 같은 파일에 남의 변경이 섞였으면 `--hunk PATH SEL`. "
                        "타 repo 의 Issue.md 면 그 repo 로 `cd` 한 뒤 실행한다(경로는 repo 기준 상대 — 밖 절대경로는 «저장소 밖 경로» 로 거부). "
                        "규칙: rules/issue-g.md 규칙10" % (bot, frag, IS_HOW)) if not frag.startswith("git stash") else (
            "deny", "[공유 워킹트리 stash 차단 — 🌱#5] 봇 몸체(%s)의 `%s` 는 다른 세션의 미커밋분을 일시 제거한다 — pop 이 충돌·중단되면 "
                    "타 세션 작업이 유실된다(prj3#Issue1079 작업자가 68개 파일을 stash 했다 복원한 실발생). 내 변경만 올리려면 %s "
                    "(같은 파일에 남의 변경이 섞였으면 `--hunk PATH SEL`), 격리가 필요하면 `git worktree`·임시 인덱스를 쓴다." % (bot, frag, IS_HOW))
    return ("warn", "[공유 Issue.md 쓸어담기 경고 — prj3#Issue1000] `%s` 는 다른 세션의 미커밋분까지 담을 수 있다. 내 변경만 올리려면 %s "
                    "(rules/issue-g.md 규칙10). 사람 세션이라 막지 않는다 — 판단해서 진행한다." % (frag, IS_HOW))


# ───────────────────────── 레지스트리 ─────────────────────────
GUARDS = [
    Guard("outer-agent", _outer_pattern, judge_outer),
    Guard("pkill-order", lambda: PKILL_PATTERN, judge_pkill),
    Guard("file-loss", lambda: FILELOSS_PATTERN, judge_fileloss),
    Guard("version-guard", lambda: VG_PATTERN, judge_version),
    Guard("issue-sweep", lambda: IS_PATTERN, judge_issue_sweep),
]


def decide(cmd, cwd, session_id=None):
    """(결정, 사유) 또는 None — 첫 deny, 없으면 첫 ask, 없으면 첫 warn(차단 없는 경고 — prj3#Issue1000)."""
    ctx = {"cwd": cwd, "session_id": session_id}
    ask = warn = None
    for g in GUARDS:
        try:
            r = g.judge(cmd, ctx)
        except Exception as e:                         # 가드 하나의 예외는 그 가드만 통과 — 다른 가드는 계속 판정
            print(f"[bash-guard {g.name}] 판정 예외로 통과(fail-open): {e!r}", file=sys.stderr)
            continue
        if r and r[0] == "deny":
            return r
        if r and r[0] == "warn":
            warn = warn or r
        else:
            ask = ask or r
    return ask or warn


def main(argv):
    if argv[1:2] == ["--prefilter"]:
        print(json.dumps({"guards": [{"name": g.name, "pattern": g.pattern()} for g in GUARDS]}, ensure_ascii=False))
        return 0
    try:
        d = json.load(sys.stdin)
        if d.get("tool_name") not in (None, "Bash"):
            return 0
        cmd = (d.get("tool_input") or {}).get("command") or ""
        cwd = d.get("cwd") or os.getcwd()              # mod 경로는 cwd 를 싣지 않는다 — process.run 의 cwd 가 세션 cwd 다
        sid = d.get("session_id") or None
    except Exception:
        return 0
    r = decide(cmd, cwd, sid)
    if r and r[0] == "warn":                           # 결정 없이 맥락만 — 차단하지 않는다 (mod guard.ts parseVerdict 가 warn 으로 읽는다)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": r[1]}}, ensure_ascii=False))
    elif r:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": r[0],
                                                 "permissionDecisionReason": r[1]}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
