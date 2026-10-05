#!/usr/bin/env python3
"""shcmd.py — Bash 명령 문자열 판정의 **단일 지점** (prj3#Issue699).

⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude 면 Issue.md 등록 후).
소비처: hooks/lib/bash-guard.py «outer-agent»·«pkill-order»(명령어 자리) · «file-loss»(파이썬 쓰기 후 읽기 · 공용 수면 로그 파괴 — prj3#Issue787)
        · hooks/fbot-writeguard.sh(리다이렉트 대상·파일 동사) — 구 개별 hook 3종은 prj3#Issue950 에서 bash-guard.py 로 통합

왜 한 곳인가 — 두 가드가 heredoc·주석·인용을 **각자** 구현하다가 한쪽만 «셸이 먹는 heredoc 은
본문도 명령» 예외를 가졌다(Issue699 codex 2차 리뷰 high: `bash <<EOF … > 보호경로 … EOF` 가
writeguard 를 통과). 판정이 갈라지는 자리를 없앤다.

판정 규칙
  * heredoc 본문은 명령이 아니다 — 단 **데이터로 확신할 때만** 걷는다. 셸 인터프리터가 받거나
    받는 명령을 못 정하면 본문도 명령이다(걷기 오판 = 우회, 남기기 오판 = 종전 오탐)
  * 산술 `$((a << b))` 의 `<<` · here-string `<<<` · 인용·주석 속 `<<` 는 heredoc 이 아니다
  * 주석은 **인용 밖**에서 단어 첫머리의 `#` 부터 줄 끝까지다(`'#'`·`$#`·`a#b` 는 주석 아님)
  * 줄바꿈은 `;` 와 같은 명령 경계다
"""
import fnmatch
import os
import re
import shlex

SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
WRAP = {"nohup", "command", "exec", "time", "sudo", "env", "xargs", "builtin"}
CTRL = set(";&|()\n")


def _words(text):
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>")
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return text.split()


def strip_redirects(tokens):
    """리다이렉트 연산자와 그 대상(·앞의 fd 번호)을 뺀 토큰열 — 명령어 자리 판정용."""
    out, skip = [], False
    for k, t in enumerate(tokens):
        if skip:
            skip = False
            continue
        if t and set(t) <= set("<>&|") and ("<" in t or ">" in t):
            if out and out[-1].isdigit() and tokens[k - 1] == out[-1]:
                out.pop()                       # `2>` 의 fd 번호
            skip = True                         # 대상(파일·fd) 한 토큰
            continue
        out.append(t)
    return out


def _command_at(tokens):
    """리다이렉트를 뺀 토큰열에서 **명령어 자리**의 위치 (없으면 -1). 대입·래퍼·timeout 인자를 건너뛴다."""
    i = 0
    while i < len(tokens):
        w = tokens[i]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w) or w in WRAP:
            i += 1
            continue
        if w == "timeout":
            i += 2 if i + 1 < len(tokens) and not tokens[i + 1].startswith("-") else 1
            continue
        return i
    return -1


def command_word(tokens):
    """단순 명령 토큰열에서 **명령어 자리** 단어의 basename (없으면 "")."""
    tokens = strip_redirects(tokens)
    i = _command_at(tokens)
    return tokens[i].lstrip("$(`").rsplit("/", 1)[-1] if i >= 0 else ""


def _heredoc_is_data(prefix):
    """그 heredoc 본문을 **데이터로 확신**할 수 있는가 — 확신할 때만 걷는다 (Issue699 codex 3회차).

    걷어내기가 틀리면 우회(미탐), 남기기가 틀리면 종전의 오탐이다. 우회 쪽이 비싸므로
    애매하면 남긴다: 명령어 자리를 못 정했거나 옵션·래퍼로 읽혔거나(`env -i bash`·`sudo -u x bash`),
    그 단순 명령 어디에든 셸 인터프리터 단어가 있으면 본문도 명령으로 본다.
    ⚠️ 대가: `cat bash <<EOF` 같은 드문 형태는 본문까지 판정된다(오탐 — 종전 동작과 같다)."""
    seg = re.split(r"[;&|(\n]", prefix)[-1]
    toks = [t for t in _words(seg) if not set(t) <= set("<>")]
    if any(t.lstrip("$(`").rsplit("/", 1)[-1] in SHELLS for t in toks):
        return False
    w = command_word(toks)
    return bool(w) and not w.startswith("-") and w not in WRAP and "=" not in w


META = set(" \t;&|()<>")


def _read_word(line, i):
    """셸 word 1개를 읽어 (인용 제거한 값, 끝 위치). heredoc delimiter 용 — `'END-MARK'`·`END+MARK`·`\\EOF`."""
    out, q, n = [], None, len(line)
    while i < n:
        c = line[i]
        if q:
            if c == q:
                q = None
            else:
                out.append(c)
        elif c in ("'", '"'):
            q = c
        elif c == "$" and i + 1 < n and line[i + 1] in ("'", '"'):
            q = line[i + 1]; i += 1               # $'…'(ANSI-C)·$"…" — `$` 는 delimiter 가 아니다
        elif c == "\\" and i + 1 < n:
            out.append(line[i + 1]); i += 1
        elif c in META:
            break
        else:
            out.append(c)
        i += 1
    return "".join(out), i


def _heredoc_ops(line, q):
    """한 줄에서 **진짜** heredoc 연산자를 찾는다 — 인용·이스케이프·주석 상태를 따라간다.
    `<<<`(here-string)·인용 속 `<<`·주석 속 `<<` 는 연산자가 아니다(Issue699 codex 재검토 high).
    반환 (연산자 목록[(dash, delim, 시작 위치)], 줄 끝의 인용 상태 — 여러 줄 인용을 잇는다)."""
    ops, i, n, arith = [], 0, len(line), 0
    while i < n:
        c = line[i]
        if not q and line.startswith("((", i):
            arith += 1; i += 2; continue          # `$((…))`·`((…))` 산술 — 안의 `<<` 는 시프트다
        if not q and arith and line.startswith("))", i):
            arith -= 1; i += 2; continue
        if q:
            if c == "\\" and q == '"' and i + 1 < n:
                i += 2; continue
            if c == q:
                q = None
            i += 1; continue
        if c == "\\":
            i += 2; continue
        if c in ("'", '"'):
            q = c; i += 1; continue
        if c == "#" and (i == 0 or line[i - 1] in " \t;&|()"):
            break                                  # 주석 — 줄 끝까지 연산자 없음
        if line.startswith("<<", i) and not arith:
            if line.startswith("<<<", i):
                i += 3; continue                   # here-string
            j = i + 2
            dash = j < n and line[j] == "-"
            j += 1 if dash else 0
            while j < n and line[j] in " \t":
                j += 1
            delim, j = _read_word(line, j)
            if delim:
                ops.append((dash, delim, i))
            i = max(j, i + 2); continue
        i += 1
    return ops, q


def strip_heredoc(src):
    """heredoc 본문을 걷어낸다. 셸 인터프리터가 받는 본문은 남긴다(그 본문이 곧 명령이다)."""
    out, pend, q = [], [], None
    for line in src.split("\n"):
        if pend:
            dash, delim, keep = pend[0]
            if (line.lstrip("\t") if dash else line) == delim:
                pend.pop(0)
            elif keep:
                out.append(line)
            continue
        out.append(line)
        ops, q = _heredoc_ops(line, q)
        for dash, delim, at in ops:
            pend.append((dash, delim, not _heredoc_is_data(line[:at])))
    return "\n".join(out)


def strip_comments(src):
    """인용 밖 단어 첫머리 `#` ~ 줄 끝을 지운다. 인용·이스케이프를 따라가는 1패스 스캐너."""
    out, q, i, n = [], None, 0, len(src)
    while i < n:
        c = src[i]
        if q:
            out.append(c)
            if c == "\\" and q == '"' and i + 1 < n:
                out.append(src[i + 1]); i += 2; continue
            if c == q:
                q = None
        elif c == "\\" and i + 1 < n:
            out.append(c); out.append(src[i + 1]); i += 2; continue
        elif c in ("'", '"'):
            q = c; out.append(c)
        elif c == "#" and (i == 0 or src[i - 1] in " \t\n;&|()"):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def normalize(src):
    """판정용 정규화 — heredoc 본문(비셸) 제거 → 주석 제거."""
    return strip_comments(strip_heredoc(src))


def tokens(src):
    """정규화한 명령의 셸 토큰. 제어·리다이렉트 연산자는 별도 토큰, 줄바꿈도 토큰으로 남는다.
    인용은 벗겨진다(posix). 파싱 불가면 None — 호출자가 fail-open 한다."""
    try:
        lex = shlex.shlex(normalize(src), posix=True, punctuation_chars=";&|()<>\n")
        lex.whitespace = " \t\r"             # 기본값은 \n 을 공백으로 먹어 줄 경계가 사라진다
        lex.whitespace_split = True
        lex.commenters = ""                  # 주석은 strip_comments 가 인용을 보며 처리했다
        return list(lex)
    except ValueError:
        return None


def simple_commands(src):
    """제어 연산자·줄바꿈으로 가른 단순 명령 토큰열 목록 (리다이렉트 연산자는 토큰에 남는다)."""
    toks = tokens(src)
    if toks is None:
        return None
    segs, cur = [], []
    for t in toks:
        if t and set(t) <= CTRL:
            if cur:
                segs.append(cur); cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


# 산출물이 아닌 리다이렉트 대상 — 변수 이름 경계까지 확인한다(`$TMPDIRTY` 는 TMPDIR 이 아니다).
#   `/tmp` 자체도 임시 경로다(`cp a.md /tmp` — codex 2차 O3: 끝 `/` 를 요구해 오탐했다)
SAFE_TARGET = re.compile(
    r"^(/dev/null$|/dev/std(out|err)$|/tmp(/|$)|/private/tmp(/|$)"
    r"|\$TMPDIR(/|$)|\$\{TMPDIR(:-/(private/)?tmp/?)?\}(/|$))")


def _norm(p):
    """판정용 경로 정규화 — 앞 `./` 제거, `~`·`$HOME`·`${HOME}` 펼침, `..` 접기(prj3#Issue757 C).
    `/private/tmp/../../Users/x` 가 접두 비교로 임시 경로가 되던 탈출을 막는다. 변수 경로는 펼치지 않는다."""
    home = os.path.expanduser("~")
    while p.startswith("./"):
        p = p[2:]
    for pre in ("~/", "$HOME/", "${HOME}/"):
        if p.startswith(pre):
            p = home + "/" + p[len(pre):]
            break
    if p in ("~", "$HOME", "${HOME}"):
        p = home
    if ".." in p.split("/"):
        p = os.path.normpath(p)
    return p


def _tmpdir():
    """펼친 `$TMPDIR` (끝 `/` 제거). 비었거나 루트면 None — `TMPDIR=/` 가 전 경로를 면제하지 않게."""
    t = (os.environ.get("TMPDIR") or "").rstrip("/")
    return t if len(t) > 1 else None


class _Ctx:
    """한 명령 안의 판정 문맥 — 관할 예외(allow) · 임시 경로를 담은 변수(tmpvars) · `cd` 로 들어간 곳이 안전한가(cwd_safe)."""
    def __init__(self, allow=None, tmpvars=None):
        self.allow, self.tmpvars, self.cwd_safe = allow, set(tmpvars or ()), False


def safe_path(p, allow=None, ctx=None):
    """산출물이 아닌 경로인가 — 임시 경로(SAFE_TARGET·펼친 $TMPDIR) · 관할 예외 · 임시 변수 · 안전한 cwd 의 상대 경로."""
    if ctx is not None:
        allow = ctx.allow
        m = re.match(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?(/|$)", p)
        if m and m.group(1) in ctx.tmpvars:
            return ".." not in p.split("/")
        if ctx.cwd_safe and p and not p.startswith(("/", "~", "$")) and ".." not in p.split("/"):
            return True
    n = _norm(p)
    if SAFE_TARGET.match(n):
        return True
    t = _tmpdir()
    if t and (n == t or n.startswith(t + "/")):
        return True
    return bool(allow and allow.search(n))


def writes_outside(src, allow=None):
    """산출물로 가는 리다이렉트가 있는가 — True/False, 파싱 불가면 None. (`writes` CLI 용 — 가드는 `mutates`)"""
    toks = tokens(src)
    if toks is None:
        return None
    for i, t in enumerate(toks):
        if ">" not in t or not set(t) <= set(">&|"):
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if "&" in t and not t.startswith("&") and (nxt.isdigit() or nxt == "-"):
            continue                          # fd 복제(2>&1 · >&2)
        if safe_path(nxt, allow):
            continue
        return True
    return False


# ── 변경 판정 (prj3#Issue757 C) ───────────────────────────────────────────────
#   실발생이 삭제 작업이었는데 `rm` 은 판정 밖이었다. codex 리뷰 2회(1차 141713 · 2차 144149)를 거쳐
#   «대상마다 예외를 본다» · «팀장 정상 업무(스크래치·보고 폴더·조회)를 막지 않는다» 로 정리했다.
FS_ALL_ARGS = {"rm", "rmdir", "mv", "mkdir", "touch", "trash", "unlink"}      # 인자 전부가 대상(`mv` 는 원본도 사라진다)
FS_DEST_ARG = {"cp", "ln", "install", "rsync"}                                 # 목적지만 대상
FS_VERBS = FS_ALL_ARGS | FS_DEST_ARG
FS_OPT_VALUE = {"mkdir": {"-m", "--mode"}, "touch": {"-t", "-d", "-r", "--date", "--reference"},
                "cp": {"-S", "--suffix"}, "mv": {"-S", "--suffix"}, "ln": {"-S", "--suffix"},
                "install": {"-m", "-o", "-g", "--mode", "--owner", "--group"},
                "rsync": {"-e", "--rsh", "--exclude", "--include", "--filter", "-f"},
                "truncate": {"-s", "--size", "-r", "--reference"}, "tee": set()}
FS_TARGET_OPT = {"-t", "--target-directory"}          # cp·mv·ln 의 목적지 지정(GNU)
QUERY_OPTS = {"--help", "--version"}
GIT_OPT_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
GIT_PATHS = {"add", "mv", "rm"}                        # 경로가 전부 관할 예외면 통과(`git add Issue.md`)
GIT_ALWAYS = {"commit", "clean", "revert", "cherry-pick", "merge", "am", "rebase", "apply", "restore"}
GIT_DRYRUN = {"clean", "add"}                          # `-n`·`--dry-run` 이면 조회
GIT_STASH_READ = {"list", "show"}
RESERVED = {"do", "then", "else", "elif", "if", "while", "until", "{", "!", "case", "in"}
WRAP_OPT_VALUE = {"env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
                  "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "--user", "--group",
                           "--host", "--prompt", "--chdir", "--role", "--type", "--close-from", "--other-user"},
                  "xargs": {"-I", "-L", "-n", "-P", "-s", "-E", "-d", "-a", "--max-args", "--max-procs",
                            "--max-lines", "--max-chars", "--delimiter", "--arg-file", "--eof"},
                  "timeout": {"-s", "--signal", "-k", "--kill-after"},
                  "nice": {"-n", "--adjustment"}, "exec": {"-a"}, "stdbuf": {"-i", "-o", "-e"}, "time": set()}
WRAPPERS = WRAP | set(WRAP_OPT_VALUE) | {"nice", "stdbuf", "time"}
ISSUE_TX_OPT_VALUE = {"-m", "--message", "-F", "--file", "--issues"}
ISSUE_TX_OPT_HUNK = "--hunk"        # `--hunk PATH SEL`(nargs=2) — PATH 는 경로 판정에 넣고 SEL(번호·정규식)만 건너뛴다(prj3#Issue932)
_ARITH = re.compile(r"\$?\(\((?:[^()]|\([^()]*\))*\)\)")        # `(( … ))`·`$(( … ))` — 안의 `>` 는 비교다
_TEST2 = re.compile(r"\[\[.*?\]\]", re.S)                       # `[[ … ]]` — 안의 `>` 는 문자열 비교다
_SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")                # 명령 치환 — 안도 명령이다(N5)
_TMPVAR = re.compile(r"(?:^|[\s;&|(])(?:export\s+|local\s+)?([A-Za-z_][A-Za-z0-9_]*)="
                     r"(?:\"|')?(?:\$\(\s*mktemp\b|/tmp(?:/|\b)|/private/tmp(?:/|\b)|\$TMPDIR\b|\$\{TMPDIR)")


def _mut_resolve(seg):
    """변경 판정용 (명령어, 인자) — 예약어·대입·함수 선언·**옵션 달린 래퍼**를 건너뛴다.
    `command -v X` 는 조회다(실행 아님). 명령어 자리 판정의 공용 경로다(outer-agent·pkill 가드 — prj3#Issue792). `command_word` 는 heredoc 판정이 쓰므로 건드리지 않는다."""
    t = strip_redirects(seg)
    i = 0
    while i < len(t):
        w = t[i]
        if w in RESERVED or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):
            i += 1
            continue
        if w == "function":
            i += 2
            continue
        b = w.lstrip("$(`").rsplit("/", 1)[-1]
        if b in WRAPPERS:
            i += 1
            vals = WRAP_OPT_VALUE.get(b, set())
            while i < len(t) and t[i].startswith("-") and t[i] != "--":
                if b == "command" and t[i] in ("-v", "-V"):
                    return "", []
                i += 2 if t[i] in vals else 1
            if i < len(t) and t[i] == "--":
                i += 1
            if b == "timeout" and i < len(t):
                i += 1                                   # 지속 시간 인자
            continue
        return b, t[i + 1:]
    return "", []


def _operands(verb, args):
    """(경로 인자, `-t` 목적지) — 옵션과 그 값을 뺀다. `--` 뒤는 전부 인자다."""
    vals = FS_OPT_VALUE.get(verb, set())
    out, dest, rest, i = [], None, False, 0
    while i < len(args):
        a = args[i]
        if not rest and a == "--":
            rest = True
        elif not rest and a in FS_TARGET_OPT and verb in ("cp", "mv", "ln"):
            dest = args[i + 1] if i + 1 < len(args) else ""
            i += 1
        elif not rest and a.startswith("--target-directory="):
            dest = a.split("=", 1)[1]
        elif not rest and a in vals:
            i += 1
        elif not rest and a.startswith("-"):
            pass
        else:
            out.append(a)
        i += 1
    return out, dest


def _git_sub(args):
    """git 전역 옵션을 건너뛴 (하위 명령, 그 뒤 인자, `-C` 경로)."""
    i, cdir = 0, None
    while i < len(args):
        a = args[i]
        if a in GIT_OPT_VALUE:
            if a == "-C" and i + 1 < len(args):
                cdir = args[i + 1]
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a, args[i + 1:], cdir
    return "", [], cdir


def _issue_tx_commit(rest, ctx):
    """`issue-tx.py <전역옵션> commit … <경로>` — 경로 인자가 전부 관할 예외인가(codex 리뷰 1차: 제품 파일을 끼워 커밋)."""
    k = 0
    while k < len(rest) and rest[k].startswith("-"):
        k += 2 if rest[k] in ISSUE_TX_OPT_VALUE else 1
    if k >= len(rest) or rest[k] != "commit":
        return False
    paths, m = [], k + 1
    while m < len(rest):
        if rest[m] in ISSUE_TX_OPT_VALUE:
            m += 2
            continue
        if rest[m] == ISSUE_TX_OPT_HUNK:
            # `--hunk PATH SEL` — PATH 는 커밋 대상이라 경로 판정에 넣고, SEL(`1`·`1,3`·정규식)만 건너뛴다.
            #   ⚠️ 값 옵션(ISSUE_TX_OPT_VALUE)에 넣어 2칸 건너뛰면 PATH 가 검사에서 빠지는 우회 구멍이다.
            #   PATH·SEL 이 다 있지 않으면(토큰 부족) argparse 도 실패하는 입력이라 안전 측으로 거부한다.
            if m + 2 >= len(rest):
                return True
            paths.append(rest[m + 1])
            m += 3
            continue
        if not rest[m].startswith("-"):
            paths.append(rest[m])
        m += 1
    return not all(safe_path(p, ctx=ctx) for p in paths)


def _all_safe(paths, ctx):
    return bool(paths) and all(safe_path(p, ctx=ctx) for p in paths)


def _seg_mutates(w, args, ctx, depth):
    """단순 명령 하나가 산출물을 바꾸는가."""
    if any(a in QUERY_OPTS for a in args):
        return False                                       # `rm --help` — 조회
    if w in SHELLS and "-c" in args:
        k = args.index("-c")
        return k + 1 < len(args) and bool(_analyze(args[k + 1], ctx, depth + 1))   # `bash -c '…'` — 문자열도 명령이다(N1)
    if w == "git":
        sub, rest, cdir = _git_sub(args)
        if cdir is not None and safe_path(cdir, ctx=ctx):
            return False                                   # 임시 저장소(`git -C /tmp/w …`)
        if sub in GIT_DRYRUN and any(a in ("-n", "--dry-run") or (re.fullmatch(r"-[a-zA-Z]+", a) and "n" in a)
                                     for a in rest):
            return False
        if sub in GIT_ALWAYS:
            return True
        if sub == "checkout":
            return not any(a in ("-b", "-B", "--orphan") for a in rest)   # 브랜치 생성만 조회 취급 — 전환은 `git switch`
        if sub == "reset":
            return any(a in ("--hard", "--merge", "--keep") for a in rest)
        if sub == "stash":
            return not rest or rest[0] not in GIT_STASH_READ
        if sub in GIT_PATHS:
            paths = [a for a in rest if not a.startswith("-")]
            return not _all_safe(paths, ctx)
        return False
    if w == "find":
        k, start = 0, []
        while k < len(args) and not args[k].startswith("-") and args[k] not in ("(", "!"):
            start.append(args[k])
            k += 1
        nested = False
        for m, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                end = next((n for n in range(m + 1, len(args)) if args[n] in (";", "\\;", "+")), len(args))
                nw, na = _mut_resolve(args[m + 1:end])
                nested = nested or nw in FS_VERBS or _seg_mutates(nw, na, _Ctx(ctx.allow, ctx.tmpvars), depth + 1)
        if "-delete" in args or nested:
            return not _all_safe(start or ["."], ctx)
        return False
    if w.startswith("python") and args:
        j = next((k for k, a in enumerate(args) if not a.startswith("-")), None)
        if j is not None and args[j].endswith("issue-tx.py"):
            return _issue_tx_commit(args[j + 1:], ctx)
        return False
    if w.endswith("issue-tx.py"):
        return _issue_tx_commit(args, ctx)                 # 직접 실행(N4)
    if w == "sed":
        if not any(a.startswith("-i") or a.startswith("--in-place") for a in args):
            return False
        pos, k, script_seen = [], 0, any(a in ("-e", "-f", "--expression", "--file") for a in args)
        while k < len(args):
            a = args[k]
            if a == "-i" and k + 1 < len(args) and (args[k + 1] == "" or args[k + 1].startswith(".")):
                k += 2
                continue
            if a in ("-e", "-f", "--expression", "--file"):
                k += 2
                continue
            if not a.startswith("-"):
                pos.append(a)
            k += 1
        files = pos if script_seen else pos[1:]
        return not _all_safe(files, ctx)
    if w in ("tee", "truncate"):
        paths, _ = _operands(w, args)
        return bool(paths) and not _all_safe(paths, ctx)
    if w == "perl":
        if not any(re.fullmatch(r"-[a-zA-Z]*i\S*", a) for a in args):
            return False
        pos, k = [], 0
        while k < len(args):
            if args[k] in ("-e", "-E"):
                k += 2
                continue
            if not args[k].startswith("-"):
                pos.append(args[k])
            k += 1
        return not _all_safe(pos, ctx)
    if w == "patch":
        return True
    if w in ("curl", "wget"):
        for k, a in enumerate(args):
            if a in ("-o", "--output", "-O", "--output-document") and k + 1 < len(args) and w == "wget" and a == "-O":
                return not safe_path(args[k + 1], ctx=ctx)
            if a in ("-o", "--output") and k + 1 < len(args):
                return not safe_path(args[k + 1], ctx=ctx)
        return False
    if w == "dd":
        return any(a.startswith("of=") and not safe_path(a[3:], ctx=ctx) for a in args)
    if w in FS_ALL_ARGS:
        paths, dest = _operands(w, args)
        if dest is not None:
            paths = paths + [dest]
        return not _all_safe(paths, ctx)
    if w in FS_DEST_ARG:
        paths, dest = _operands(w, args)
        target = dest if dest is not None else (paths[-1] if len(paths) >= 2 else None)
        return target is None or not safe_path(target, ctx=ctx)
    return False


def _redirect_targets(seg):
    """세그먼트의 산출물 리다이렉트 대상들(fd 복제 제외)."""
    out = []
    for i, t in enumerate(seg):
        if ">" not in t or not set(t) <= set(">&|"):
            continue
        nxt = seg[i + 1] if i + 1 < len(seg) else ""
        if "&" in t and not t.startswith("&") and (nxt.isdigit() or nxt == "-"):
            continue
        out.append(nxt)
    return out


def _analyze(src, ctx, depth=0):
    """명령 문자열이 산출물을 바꾸는가 — True/False, 파싱 불가면 None. 세그먼트 순서대로 `cd` 를 따라간다."""
    if depth > 4:
        return False
    flat = _TEST2.sub(" true ", _ARITH.sub(" 0 ", normalize(src)))
    ctx.tmpvars |= {m.group(1) for m in _TMPVAR.finditer(flat)}
    for m in _SUBST.finditer(flat):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        if body and _analyze(body, ctx, depth + 1):
            return True
    segs = simple_commands(flat)
    if segs is None:
        return None
    for seg in segs:
        for tgt in _redirect_targets(seg):
            if not safe_path(tgt, ctx=ctx):
                return True
        w, args = _mut_resolve(seg)
        if w == "cd":
            ctx.cwd_safe = bool(args) and safe_path(args[0], ctx=_Ctx(ctx.allow, ctx.tmpvars))
            continue
        if _seg_mutates(w, args, ctx, depth):
            return True
    return False


def fs_mutates(src, allow=None):
    """파일을 바꾸는 명령(동사·리다이렉트·셸 `-c`·명령 치환)이 산출물에 닿는가 — True/False, 파싱 불가면 None.

    임시 경로·관할 예외(allow)만 건드리면 산출물이 아니다 — **대상마다** 판정한다. 같은 명령 안에서 임시 경로를
    담은 변수(`D=$(mktemp -d)`)와 `cd /tmp/w` 뒤의 상대 경로는 임시로 본다. 그 밖의 모르는 변수 경로는 임시가 아니다."""
    return _analyze(src, _Ctx(allow))


def mutates(src, allow=None):
    """산출물을 바꾸는가 — 판정 단일 지점(writeguard ⓑ). 파싱 불가면 None."""
    return fs_mutates(src, allow)


# 파이썬 쓰기 API(ⓐ)는 대상을 해석할 수 없다 — **경로처럼 생긴 문자열 리터럴**을 전부 모아 전부가 임시·관할
#   예외일 때만 통과시킨다(codex 2차 N6: 문자열 어딘가의 `Issue.md` 로 제품 파일 쓰기까지 면제하던 구멍).
#   경로 리터럴이 하나도 없으면(변수 경로) 판정 불가 — 쓰기 API 가 보였으므로 쓰기로 본다.
_PATHLIT = re.compile(r"""(['"])([^'"\s]+)\1""")
_PATHLIKE = re.compile(r"^(~|/|\.{1,2}/|\$\{?HOME\}?|\$\{?TMPDIR)|^[\w.-]+/|\.[A-Za-z0-9]{1,8}$")


def api_writes(src, allow=None):
    """파이썬 쓰기 API 가 산출물에 닿는가 — 경로 리터럴이 없거나 하나라도 산출물이면 True."""
    lits = [m.group(2) for m in _PATHLIT.finditer(src) if _PATHLIKE.search(m.group(2))]
    return not lits or not all(safe_path(p, allow) for p in lits)


_FBOT_LEAD = re.compile(r"(^|/)fbot-lead\.py$")


def approves(src):
    """`fbot-lead.py solo-approve` 를 **실행**하는가 — 문자열 언급(grep·로그)은 아니다(codex 2차 O1)."""
    segs = simple_commands(src)
    for seg in segs or []:
        w, args = _mut_resolve(seg)
        if w.startswith("python"):
            j = next((k for k, a in enumerate(args) if not a.startswith("-")), None)
            if j is None:
                continue
            w, args = args[j].rsplit("/", 1)[-1], args[j + 1:]
        if w == "fbot-lead.py" and args[:1] == ["solo-approve"]:
            return True
    return False


# ── 파일 유실 판정 (prj3#Issue787) ────────────────────────────────────────────
#   명령 문자열만으로 판정되는 유실 2종(hook-rules 규칙9 — 산출물만 보고 기계적으로 판정된다).
#   ① 파이썬 `open(X,'w')` 는 **인자 평가보다 먼저** truncate 한다 — 같은 식 안에서 X 를 읽으면 빈 파일을 읽고
#      빈 내용을 쓴다(Issue719 Issue.md · Issue745 debug_TECH.md 0바이트, 두 번째는 타 세션 미커밋분 유실).
#      대상 식이 다르면 판정하지 않는다 — 변수 두 개가 같은 파일을 가리키는지는 문자열로 알 수 없다.
#   ② 공용 수면 로그 `.sleep-log/YYYY-MM-DD.md` 는 여러 세션이 append 하는 파일이다 — `>>` 밖의 삭제·이동·덮어쓰기는
#      그 사이 남이 쓴 줄을 지운다(2026-09-29 핀봇 워커 2회 `rm`, 둘 다 «내가 만든 새 파일» 로 오인).
_PY_RUN = re.compile(r"(?<![\w.-])python[0-9.]*(?![\w-])")
_PY_OPEN = re.compile(r"(?<![\w.])open\(")
_PY_STR = re.compile(r"""^[rRbBuUfF]{0,2}(['"])(.*)\1$""", re.S)
_PY_KW = re.compile(r"^[A-Za-z_]\w*\s*=(?!=)")
_PY_DESTROY = re.compile(r"\.(write_text|write_bytes|unlink)\s*\(|\bos\.(remove|unlink|rename|replace)\s*\(|\bshutil\.(move|rmtree)\s*\(")


def _py_skip_str(code, i):
    """code[i] 가 따옴표면 그 문자열 끝 다음 위치, 아니면 None. 삼중 따옴표·이스케이프를 따른다(한 줄 문자열은 줄 끝에서 닫는다)."""
    q = code[i]
    if q not in "'\"":
        return None
    if code.startswith(q * 3, i):
        j = code.find(q * 3, i + 3)
        return len(code) if j < 0 else j + 3
    j = i + 1
    while j < len(code):
        if code[j] == "\\":
            j += 2
            continue
        if code[j] in (q, "\n"):
            return j + 1
        j += 1
    return len(code)


def _py_statements(code):
    """괄호 깊이 0 의 줄바꿈·`;` 로 가른 문장들 — 문자열·주석 안은 가르지 않는다(여러 줄 호출은 한 문장)."""
    out, start, depth, i, n = [], 0, 0, 0, len(code)
    while i < n:
        j = _py_skip_str(code, i)
        if j is not None:
            i = j
            continue
        c = code[i]
        if c == "#":
            k = code.find("\n", i)
            i = n if k < 0 else k
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c in "\n;" and depth == 0:
            out.append(code[start:i])
            start = i + 1
        i += 1
    out.append(code[start:])
    return out


def _py_mask(code):
    """문자열 리터럴 내용·주석을 `\\0` 으로 가린 같은 길이 사본 — 호출 탐색은 가린 사본에서, 인자 값은 원문에서 읽는다.
    설명 문구·grep 패턴 속 `open(X,'w')` 를 호출로 읽던 오탐(Issue787 배선 직후 실측)을 막는다."""
    out, i, n = list(code), 0, len(code)
    while i < n:
        j = _py_skip_str(code, i)
        if j is not None:
            q = 3 if code.startswith(code[i] * 3, i) else 1
            for k in range(i + q, max(i + q, j - q)):
                out[k] = "\0"
            i = j
            continue
        if code[i] == "#":
            k = code.find("\n", i)
            k = n if k < 0 else k
            out[i:k] = "\0" * (k - i)
            i = k
            continue
        i += 1
    return "".join(out)


def _py_call(code, i):
    """code[i] 가 `(` 일 때 (최상위 `,` 로 가른 인자 목록, 닫는 괄호 다음 위치). 닫히지 않으면 (None, 끝)."""
    args, depth, start, j, n = [], 0, i + 1, i, len(code)
    while j < n:
        k = _py_skip_str(code, j)
        if k is not None:
            j = k
            continue
        c = code[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                args.append(code[start:j])
                return [a.strip() for a in args if a.strip()], j + 1
        elif c == "," and depth == 1:
            args.append(code[start:j])
            start = j + 1
        j += 1
    return None, n


def _py_lit(expr):
    """문자열 리터럴 하나면 그 값, 아니면 None."""
    m = _PY_STR.match(expr.strip())
    return m.group(2) if m and m.group(1) not in m.group(2) else None


def _py_key(expr):
    """같은 대상 비교 키 — 리터럴은 값(따옴표 종류 무시), 식은 공백을 뺀 원문."""
    lit = _py_lit(expr)
    return ("s", lit) if lit is not None else ("e", re.sub(r"\s+", "", expr))


def _py_opens(stmt):
    """문장 안의 `open()` 호출 — (대상 키, 대상 식, mode, 닫는 괄호 다음 위치). mode 는 생략이면 'r', 리터럴이 아니면 None."""
    out = []
    for m in _PY_OPEN.finditer(_py_mask(stmt)):
        args, end = _py_call(stmt, m.end() - 1)
        if not args:
            continue
        pos = [a for a in args if not _PY_KW.match(a)]
        kw = dict((a.split("=", 1)[0].strip(), a.split("=", 1)[1]) for a in args if _PY_KW.match(a))
        target = pos[0] if pos else kw.get("file")
        if target is None:
            continue
        mode = pos[1] if len(pos) > 1 else kw.get("mode")
        out.append((_py_key(target), target.strip(), "r" if mode is None else _py_lit(mode), end))
    return out


def _py_heredocs(src):
    """명령어 자리가 python 인 heredoc 본문들 — `cat > f <<EOF` 같은 데이터 본문(커밋 메시지 등)은 코드가 아니다
    (Issue787 배선 직후 실측 오탐: 메시지 속 설명 문구를 같은 명령의 `python3` 때문에 코드로 읽었다)."""
    out, pend, q = [], [], None
    for line in src.split("\n"):
        if pend:
            dash, delim, body = pend[0]
            if (line.lstrip("\t") if dash else line) == delim:
                pend.pop(0)
                if body is not None:
                    out.append("\n".join(body))
            elif body is not None:
                body.append(line)
            continue
        ops, q = _heredoc_ops(line, q)
        for dash, delim, at in ops:
            seg = re.split(r"[;&|(\n]", line[:at])[-1]
            w, _ = _mut_resolve([t for t in _words(seg) if not set(t) <= set("<>")])
            pend.append((dash, delim, [] if w.startswith("python") else None))
    return out


def _py_sources(src):
    """판정할 파이썬 코드 조각 — python 이 받는 heredoc 본문 + python 명령의 `-c` 인자."""
    out = _py_heredocs(src)
    for seg in simple_commands(src) or []:
        w, args = _mut_resolve(seg)
        if w.startswith("python") and "-c" in args:
            k = args.index("-c")
            if k + 1 < len(args):
                out.append(args[k + 1])
    return out


def write_then_read(src):
    """파이썬이 `open(X,'w')` 로 연 뒤 **같은 문장에서** X 를 읽는가 — 걸린 X 의 식, 없으면 None.
    읽기 = `open(X)`(쓰기·append 모드 아님) · `X.read_text()`·`read_bytes()` · `Path(X).read_text()`.
    python 을 부르는 명령만 본다 — grep 으로 이 형태를 찾는 조회는 막지 않는다."""
    if "open(" not in src or not _PY_RUN.search(src):
        return None
    for code in _py_sources(src):
        for stmt in _py_statements(code):
            opens = _py_opens(stmt)
            for key, expr, mode, end in opens:
                if not mode or "w" not in mode:
                    continue
                if any(k2 == key and m2 is not None and not set(m2) & set("wax") and e2 > end
                       for k2, _, m2, e2 in opens):
                    return expr
                tail, mtail = stmt[end:], _py_mask(stmt)[end:]
                if key[0] == "e" and re.search(r"(?<![\w.])" + re.escape(expr) + r"\s*\.\s*read_(text|bytes)\s*\(", mtail):
                    return expr
                for pm in re.finditer(r"(?<![\w.])(?:pathlib\.)?Path\(", mtail):
                    a, e = _py_call(tail, pm.end() - 1)
                    if a and _py_key(a[0]) == key and re.match(r"\s*\.\s*read_(text|bytes)\s*\(", mtail[e:]):
                        return expr
    return None


SLEEPLOG_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\.md")
_SLEEPLOG = re.compile(r"(?:^|/)\.sleep-log(?:/(.*))?$")
_SLEEPLOG_SAMPLE = "2026-09-29.md"                     # glob 이 날짜 로그와 맞는지 볼 대표 이름


def _sleeplog_dir(p):
    """경로가 수면 로그 폴더 자체인가."""
    m = _SLEEPLOG.search(_norm(p)) if p else None
    return bool(m) and not (m.group(1) or "").strip("/")


def sleeplog_file(p, in_log=False):
    """경로가 공용 수면 로그(`.sleep-log/YYYY-MM-DD.md`) 또는 그 폴더 자체를 가리킬 수 있는가.
    glob 은 날짜 이름과 맞으면 · 변수·치환(`$`) 이름은 `session_*` 가 아니면 가리킬 수 있다고 본다.
    하위 폴더(`z_done/`)·세션 로그(`session_*.md`)는 대상이 아니다 — sleep off 리뷰의 정식 이관 경로다."""
    if not p:
        return False
    n = _norm(p)
    m = _SLEEPLOG.search(n)
    if m:
        rest = (m.group(1) or "").strip("/")
        if not rest:
            return True
    elif in_log and not n.startswith(("/", "~", "$")):
        rest = n
    else:
        return False
    if "/" in rest or rest.startswith("session_"):
        return False
    if SLEEPLOG_DATE.fullmatch(rest):
        return True
    if any(c in rest for c in "*?["):
        return fnmatch.fnmatchcase(_SLEEPLOG_SAMPLE, rest)
    return "$" in rest or "`" in rest


def _clobber_redirects(seg):
    """덮어쓰기 리다이렉트 대상(`>`·`>|`·`&>`) — append(`>>`)·fd 복제는 뺀다."""
    out = []
    for i, t in enumerate(seg):
        if ">" not in t or not set(t) <= set(">&|") or t.count(">") > 1:
            continue
        nxt = seg[i + 1] if i + 1 < len(seg) else ""
        if "&" in t and not t.startswith("&") and (nxt.isdigit() or nxt == "-"):
            continue
        out.append(nxt)
    return out


def _into(dest, srcs):
    """목적지가 수면 로그 폴더 자체면 원본 이름으로 들어갈 경로들, 아니면 목적지 그대로."""
    if dest and _sleeplog_dir(dest):
        return [dest.rstrip("/") + "/" + s.rstrip("/").rsplit("/", 1)[-1] for s in srcs]
    return [dest] if dest else []


def _clobber_targets(w, args):
    """단순 명령 하나가 지우거나 덮어쓰는 경로들 — 읽기·append·생성(mkdir·touch)은 넣지 않는다."""
    if any(a in QUERY_OPTS for a in args):
        return []
    if w in ("rm", "unlink", "trash", "srm", "shred"):
        return _operands(w, args)[0]
    if w in ("mv", "cp", "ln", "install", "rsync"):
        paths, dest = _operands(w, args)
        if dest is None and len(paths) >= 2:
            paths, dest = paths[:-1], paths[-1]
        if w == "rsync" and dest and _sleeplog_dir(dest):
            return [dest]                                   # `--delete`·디렉토리 동기화 — 폴더째 대상
        return (paths if w == "mv" else []) + _into(dest, paths)
    if w == "tee":
        return [] if any(a in ("-a", "--append") or re.fullmatch(r"-[a-zA-Z]*a[a-zA-Z]*", a) for a in args) \
            else _operands(w, args)[0]
    if w == "truncate":
        return _operands(w, args)[0]
    if w == "sed" and any(a.startswith("-i") or a.startswith("--in-place") for a in args):
        pos, k, script_seen = [], 0, any(a in ("-e", "-f", "--expression", "--file") for a in args)
        while k < len(args):
            a = args[k]
            if a == "-i" and k + 1 < len(args) and (args[k + 1] == "" or args[k + 1].startswith(".")):
                k += 2
                continue
            if a in ("-e", "-f", "--expression", "--file"):
                k += 2
                continue
            if not a.startswith("-"):
                pos.append(a)
            k += 1
        return pos if script_seen else pos[1:]
    if w == "dd":
        return [a[3:] for a in args if a.startswith("of=")]
    if w == "find":
        start, k = [], 0
        while k < len(args) and not args[k].startswith("-") and args[k] not in ("(", "!"):
            start.append(args[k])
            k += 1
        destroys = "-delete" in args or any(
            a in ("-exec", "-execdir", "-ok", "-okdir") and m + 1 < len(args)
            and _mut_resolve(args[m + 1:m + 2])[0] in ("rm", "mv", "unlink", "trash", "truncate")
            for m, a in enumerate(args))
        if not destroys:
            return []
        names = [args[m + 1] for m, a in enumerate(args) if a in ("-name", "-iname") and m + 1 < len(args)]
        if names and not any(fnmatch.fnmatchcase(_SLEEPLOG_SAMPLE, x) for x in names):
            return []                                       # 이름 조건이 날짜 로그를 고르지 않는다
        return start or ["."]
    return []


def _sl_analyze(src, in_log, depth=0):
    """수면 로그를 지우거나 덮어쓰는 대상 — 첫 대상 경로, 없거나 파싱 불가면 None. `cd`·셸 `-c`·`eval`·명령 치환을 따라간다."""
    if depth > 4:
        return None
    flat = _TEST2.sub(" true ", _ARITH.sub(" 0 ", normalize(src)))
    for m in _SUBST.finditer(flat):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        hit = body and _sl_analyze(body, in_log, depth + 1)
        if hit:
            return hit
    for seg in simple_commands(flat) or []:
        for tgt in _clobber_redirects(seg):
            if sleeplog_file(tgt, in_log):
                return tgt
        w, args = _mut_resolve(seg)
        if w == "cd":
            in_log = bool(args) and (_sleeplog_dir(args[0]) or (in_log and args[0] in (".", "./")))
            continue
        inner = None
        if w in SHELLS and "-c" in args:
            k = args.index("-c")
            inner = args[k + 1] if k + 1 < len(args) else None
        elif w == "eval":
            inner = " ".join(args)
        if inner:
            hit = _sl_analyze(inner, in_log, depth + 1)
            if hit:
                return hit
            continue
        for tgt in _clobber_targets(w, args):
            if sleeplog_file(tgt, in_log):
                return tgt
    return None


def sleeplog_clobbers(src, cwd=None):
    """공용 수면 로그를 `>>` 밖으로 건드리는가 — 걸린 대상 경로, 없으면 None.
    셸(삭제·이동·덮어쓰기 동사·리다이렉트) + 파이썬(`open(…,'w')`·삭제·이동 API 에 로그 경로 리터럴)."""
    hit = _sl_analyze(src, bool(cwd) and _sleeplog_dir(cwd))
    if hit or ".sleep-log" not in src or not _PY_RUN.search(src):
        return hit
    for code in _py_sources(src):
        for stmt in _py_statements(code):
            for key, expr, mode, _ in _py_opens(stmt):
                if key[0] == "s" and mode and "w" in mode and sleeplog_file(key[1]):
                    return key[1]
            if _PY_DESTROY.search(_py_mask(stmt)):
                for m in _PATHLIT.finditer(stmt):
                    if sleeplog_file(m.group(2)):
                        return m.group(2)
    return None


if __name__ == "__main__":
    # CLI: shcmd.py writes|mutates < cmd  → exit 0=쓰기 있음 · 1=없음/판정불가(fail-open)
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "writes":
        sys.exit(0 if writes_outside(sys.stdin.read()) else 1)
    # prj3#Issue757 C — writeguard 가 쓴다. `--allow <정규식>` = 관할 예외 경로(정규화한 대상에 search)
    _allow = re.compile(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--allow" else None
    if len(sys.argv) > 1 and sys.argv[1] == "mutates":
        sys.exit(0 if mutates(sys.stdin.read(), _allow) else 1)
    if len(sys.argv) > 1 and sys.argv[1] == "apiwrites":
        sys.exit(0 if api_writes(sys.stdin.read(), _allow) else 1)
    if len(sys.argv) > 1 and sys.argv[1] == "approves":
        sys.exit(0 if approves(sys.stdin.read()) else 1)
    sys.exit(2)
