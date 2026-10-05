#!/usr/bin/env python3
# playlist-run.py — 재생목록 md 표를 위에서 아래로 실행하고 행별 결과를 낸다 (Issue543 M1-0·M1-2)
#
# 왜: tdd/playlist.md·tdd/release.md 는 «무엇을 어떤 순서로 돌리나» 의 인덱스인데, 행을 실제로
#   돌리고 결과를 모으는 주체가 없었다(codex plan-check high, 2026-09-27). 사람이 행마다 명령을
#   복사해 돌리면 건너뛴 행이 «통과» 로 기억된다. 인덱스를 그대로 읽어 돌리면 표가 곧 실행 계획이다.
#
# 행 분류 — 실행 열(헤더 `실행`)을 본다:
#   none      `—` 로 시작 — 실행 수단이 아직 없다(🚧 plan). 셀 안의 백틱 경로를 **실행하지 않는다**
#   manual    `수동` 으로 시작 — `--manual <id>=<결과>[:<근거>]` 로만 결과가 생긴다
#   external  `기동 필요`·`외부 대기` 문구 — 후보 코드가 아닌 외부 상태(운영 hub 등)를 검사하게 되므로 돌리지 않는다
#   command   첫 백틱 명령(`bash …`·`python3 …`·`node …` 또는 `*.sh|*.py|*.js` 경로)
# 결과: rc 0 → pass · rc 3 → partial(하위 러너가 건너뛴 행을 보고) · 그 외 → fail · 분류 none·manual(미기록)·external → skip
#
# 사용: python3 tdd/playlist-run.py <playlist.md> [--rows-out <tsv>] [--manual id=result[:note]]...
#                                 [--only id,id] [--timeout 초] [--log-dir <dir>] [--list]
# exit: 0 전 행 pass · 3 fail 없이 skip·partial 존재 · 1 fail 존재 · 2 입력 오류(표 없음·행 0건·잘못된 --manual)
#
# 같은 실행 안의 중복 명령: env FPM_PLAYLIST_MEMO=<dir> 가 있으면 명령 문자열 기준으로 결과를 재사용한다
#   (release.md 1행이 부르는 개발 재생목록 안의 release-check 를 2행이 다시 돌리지 않게 — 분 단위다).
import argparse
import hashlib
import os
import re
import subprocess
import sys
import time

RESULTS = ("pass", "fail", "skip", "partial")
CMD_HEAD = re.compile(r"^(bash|sh|python3|python|node|env)\s")
CMD_PATH = re.compile(r"^[\w./-]+\.(sh|py|js)(\s|$)")
INTERP = {"sh": "bash", "py": "python3", "js": "node"}


def split_row(line):
    s = line.strip().replace("\\|", "\x00")
    if not (s.startswith("|") and s.endswith("|")):
        return None
    return [c.strip().replace("\x00", "|") for c in s[1:-1].split("|")]


def parse(path):
    """첫 번째 `id`·`실행` 헤더를 가진 표의 행 목록."""
    lines = open(path, encoding="utf-8").read().splitlines()
    rows, cols = [], None
    for line in lines:
        cells = split_row(line)
        if cells is None:
            if cols is not None and rows:
                break  # 표 끝
            continue
        if cols is None:
            if "id" in cells and "실행" in cells:
                cols = {name: i for i, name in enumerate(cells)}
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue  # 구분 행
        rid = cells[cols["id"]].strip("` ") if len(cells) > cols["id"] else ""
        run = cells[cols["실행"]] if len(cells) > cols["실행"] else ""
        if rid:
            rows.append((rid, run))
    return rows


def classify(run):
    t = run.strip()
    if t.startswith("—") or t.startswith("-") or not t:
        return "none", t.lstrip("—- ").strip()
    if t.startswith("수동"):
        return "manual", t
    if "기동 필요" in t or "외부 대기" in t:
        return "external", t
    for span in re.findall(r"`([^`]+)`", t):
        span = span.strip()
        if CMD_HEAD.match(span):
            return "command", span
        m = CMD_PATH.match(span)
        if m:
            return "command", f"{INTERP[m.group(1)]} {span}"
    return "none", t


def last_line(text):
    for ln in reversed(text.splitlines()):
        ln = re.sub(r"\x1b\[[0-9;]*m", "", ln).strip()
        if ln:
            return ln[:160]
    return ""


def run_cmd(cmd, cwd, timeout, log_path):
    memo_dir = os.environ.get("FPM_PLAYLIST_MEMO", "")
    key = hashlib.sha1(f"{cwd}\n{cmd}".encode()).hexdigest()
    memo = os.path.join(memo_dir, key) if memo_dir else ""
    if memo and os.path.isfile(memo):
        rc, tail = open(memo, encoding="utf-8").read().split("\t", 1)
        return int(rc), tail, 0.0, True
    t0 = time.time()
    env = dict(os.environ, REPO_DIR=cwd)
    try:
        p = subprocess.run(["bash", "-c", cmd], cwd=cwd, env=env, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        rc, out = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        rc = 124
        out = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
        out += f"\ntimeout {timeout}s"
    dt = time.time() - t0
    if log_path:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"$ {cmd}\n# rc={rc} {dt:.1f}s\n{out}")
    tail = last_line(out)
    if memo:
        os.makedirs(memo_dir, exist_ok=True)
        with open(memo, "w", encoding="utf-8") as f:
            f.write(f"{rc}\t{tail}")
    return rc, tail, dt, False


def main():
    ap = argparse.ArgumentParser(description="재생목록 md 표 실행기 (Issue543)")
    ap.add_argument("playlist")
    ap.add_argument("--rows-out", default="")
    ap.add_argument("--manual", action="append", default=[])
    ap.add_argument("--only", default="")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--log-dir", default="")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    pl = os.path.abspath(a.playlist)
    if not os.path.isfile(pl):
        print(f"❌ 재생목록 없음: {a.playlist}", file=sys.stderr)
        return 2
    # 재생목록은 <repo>/tdd/ 에 있다 — 명령은 repo 루트 기준 상대경로다
    root = os.path.dirname(os.path.dirname(pl))
    rows = parse(pl)
    if not rows:
        print(f"❌ 행 0건 — `id`·`실행` 헤더 표를 찾지 못했다: {a.playlist}", file=sys.stderr)
        return 2

    manual = {}
    for m in a.manual:
        rid, _, rest = m.partition("=")
        res, _, note = rest.partition(":")
        if not rid or res not in RESULTS:
            print(f"❌ --manual 형식: <id>=<{'|'.join(RESULTS)}>[:근거] (got {m!r})", file=sys.stderr)
            return 2
        manual[rid] = (res, note)
    only = {x.strip() for x in a.only.split(",") if x.strip()}

    if a.list:
        for rid, run in rows:
            kind, what = classify(run)
            print(f"{rid}\t{kind}\t{what}")
        return 0

    if a.log_dir:
        os.makedirs(a.log_dir, exist_ok=True)
    out_rows = []
    for n, (rid, run) in enumerate(rows, 1):
        kind, what = classify(run)
        if only and rid not in only:
            res, note = "skip", "--only 제외"
        elif kind == "manual":
            res, note = manual.get(rid, ("skip", "수동 행 — --manual <id>=pass:<근거> 로 기록"))
            note = note or "수동 기록"
        elif kind == "external":
            res, note = "skip", f"외부 대기 — {what}"
        elif kind == "none":
            res, note = "skip", "실행 수단 없음" + (f" — {what}" if what else "")
        else:
            log = os.path.join(a.log_dir, f"{n:02d}-{rid}.log") if a.log_dir else ""
            rc, tail, dt, reused = run_cmd(what, root, a.timeout, log)
            res = "pass" if rc == 0 else ("partial" if rc == 3 else "fail")
            if reused:
                note = f"재사용 — 같은 실행에서 이미 돈 명령 (rc {rc})"
            elif res == "pass":
                note = f"rc 0 ({dt:.0f}s)"
            else:
                note = f"rc {rc} — {tail}" if tail else f"rc {rc}"
        mark = {"pass": "✅", "fail": "❌", "skip": "⏭ ", "partial": "◐ "}[res]
        print(f"  {mark} {n:>2} {rid:<24} {res:<7} {note}", flush=True)
        out_rows.append((rid, res, note))

    if a.rows_out:
        with open(a.rows_out, "w", encoding="utf-8") as f:
            for rid, res, note in out_rows:
                f.write(f"{rid}\t{res}\t{note.replace(chr(9), ' ')}\n")
    cnt = {k: sum(1 for r in out_rows if r[1] == k) for k in RESULTS}
    # 요약 줄이 곧 상위 러너의 비고가 된다(마지막 출력 줄) — 수만이 아니라 어느 행인지 싣는다
    def part(k):
        ids = [r[0] for r in out_rows if r[1] == k]
        return f"{k} {len(ids)}" + (f" ({', '.join(ids)})" if ids and k != "pass" else "")
    print("결과: " + " · ".join(part(k) for k in RESULTS))
    if cnt["fail"]:
        return 1
    if cnt["skip"] or cnt["partial"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
