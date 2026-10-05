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

가드 추가: 아래 GUARDS 에 Guard(name, pattern, judge) 한 줄. judge(cmd, ctx) → ("deny"|"ask", 사유) 또는 None.
  pattern 은 «명령 + "\n" + cwd» 텍스트에 대해 검사한다(mod 도 같은 텍스트로 검사) — 그 가드가 판정할 수 있는 모든 호출에
  걸려야 한다(누락 = 판정 없이 통과). 넓은 것은 비용일 뿐이다.
  폴백 hooks/bash-guard.sh 의 `case` 무비용 가드도 같이 넓힌다 — 거기 빠진 키워드는 mod 미로드 시 판정되지 않는다.
합성: deny 가 하나라도 있으면 첫 deny, 없으면 첫 ask (settings 다중 hook 의 deny > ask 와 같다).
실패: 가드 하나가 예외를 내면 그 가드만 통과(fail-open) — 종전엔 가드마다 프로세스가 따로라 서로 영향이 없었다. 입력 파싱 실패도 통과.
"""
import json, os, re, sys

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


# ───────────────────────── 레지스트리 ─────────────────────────
GUARDS = [
    Guard("outer-agent", _outer_pattern, judge_outer),
    Guard("pkill-order", lambda: PKILL_PATTERN, judge_pkill),
    Guard("file-loss", lambda: FILELOSS_PATTERN, judge_fileloss),
]


def decide(cmd, cwd):
    """(결정, 사유) 또는 None — 첫 deny, 없으면 첫 ask."""
    ctx = {"cwd": cwd}
    ask = None
    for g in GUARDS:
        try:
            r = g.judge(cmd, ctx)
        except Exception as e:                         # 가드 하나의 예외는 그 가드만 통과 — 다른 가드는 계속 판정
            print(f"[bash-guard {g.name}] 판정 예외로 통과(fail-open): {e!r}", file=sys.stderr)
            continue
        if r and r[0] == "deny":
            return r
        ask = ask or r
    return ask


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
    except Exception:
        return 0
    r = decide(cmd, cwd)
    if r:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": r[0],
                                                 "permissionDecisionReason": r[1]}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
