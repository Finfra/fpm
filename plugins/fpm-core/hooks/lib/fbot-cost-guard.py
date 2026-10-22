#!/usr/bin/env python3
"""fbot-cost-guard.py — 프로젝트 일일 비용 가드 판정 (prj3#Issue1153)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.

왜 있나 — 일 비용은 평시 4~57M 인데 10-16·17 에 182.6M·272.1M 로 몰렸다. 현 «폭주 가드»(fbot-lead judge_demand_guard)는
배분 **건수**만 보고 비용을 보지 않는다. 여기서는 프로젝트별 그날 누적 비용이 평시 분포의 상위 백분위를 넘었는지만 판정한다.

**차단이 아니라 강등·대기**다 — 소비처(fbot-lead dispatch · fbot-inbox wake)가 `over` 를 보고
  ① 배분 몸체 모델을 `demote_to`(기본 sonnet) 하한으로 **낮추고**(올리지 않음 · `--model` 명시는 건드리지 않음)
  ② **비긴급** 인박스 기상의 디바운스 창을 `wake_hold_secs` 로 늘린다(긴급·사람 결정 대기는 이 모듈을 부르지 않는다).
발동은 (프로젝트, 날짜)당 mq 알림 1회 — `notify_once`.

비용 = sh/token-usage.py 의 가중 비용(UTC 날짜). 트랜스크립트 30일 스캔은 ≈60초라 **일별 캐시**(data/fbot/cost-guard-cache.json)를
쓴다: 지난 날은 한 번 적재하면 불변, 오늘만 `cache_ttl_secs` 마다 다시 센다. 소비처 경로는 캐시만 읽고 낡으면 분리 프로세스로
`refresh` 를 건다(디스패치를 60초 붙잡지 않는다). 캐시가 없으면 **fail-open**(over=False) — 가드 결함이 일을 막지 않는다.

주간 %(Claude 쿼터, prj3#Issue1149): data/claude/quota-claude.json 에 실측 창이 있으면 함께 본다. **값이 없으면 건너뛴다** —
로그인이 필요한 부분은 사람 몫이고, 없어도 일일 비용만으로 동작한다.

사용:
  fbot-cost-guard.py status [--cwd DIR | --key 폴더명]   판정 JSON (캐시만)
  fbot-cost-guard.py refresh [--force]                  캐시 갱신(느림 — 첫 적재 ≈60초)
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".claude")
DATA_DIR = os.environ.get("FBOT_COST_GUARD_DIR") or os.path.join(CLAUDE, "data", "fbot")
CACHE_PATH = os.path.join(DATA_DIR, "cost-guard-cache.json")
STATE_PATH = os.path.join(DATA_DIR, "cost-guard-state.json")
POLICY_PATH = os.path.join(DATA_DIR, "cost-guard-policy.json")     # 선택 — 없으면 DEFAULTS
QUOTA_PATH = os.environ.get("FBOT_CLAUDE_QUOTA") or os.path.join(CLAUDE, "data", "claude", "quota-claude.json")
TOKEN_USAGE = os.path.join(CLAUDE, "sh", "token-usage.py")
TRANSCRIPT_ROOT = os.environ.get("FBOT_COST_GUARD_ROOT") or os.path.join(CLAUDE, "projects")
PM_PROJECTS = os.environ.get("FBOT_PM_PROJECTS") or os.path.join(HOME, "_git", "___pm", "projects")
MQ_ENQUEUE_SH = os.environ.get("FBOT_COST_GUARD_MQ") or os.path.join(CLAUDE, "mcp", "aoa-mq", "aoa-mq-enqueue.sh")

DEFAULTS = {
    "enabled": True,
    "window_days": 30,            # 평시 분포를 보는 과거 일수(오늘 제외)
    "percentile": 0.9,            # 평시 분포의 상위 백분위 — 이를 넘으면 «몰림»
    "min_days": 5,                # 표본이 이보다 적으면 분포를 믿지 않고 fallback
    "floor": 30_000_000,          # 임계 하한 — 조용한 프로젝트의 소규모 변동이 발동하지 않게
    "fallback": 80_000_000,       # 표본 부족 프로젝트의 고정 임계(평시 4~57M · 스파이크 182M+ 사이)
    "cache_ttl_secs": 600,        # 오늘 값을 다시 세는 주기
    "wake_hold_secs": 1800,       # 발동 시 비긴급 인박스 기상 대기 창
    "demote_to": "sonnet",        # 발동 시 몸체 모델 상한(낮추기만)
    "weekly_pct_limit": 85,       # Claude 주간 사용률이 이 이상이면 발동(실측 있을 때만)
    "weekly_max_age_min": 360,    # 이보다 낡은 주간 실측은 무시
}


def policy():
    p = dict(DEFAULTS)
    try:
        with open(POLICY_PATH, encoding="utf-8") as fh:
            extra = json.load(fh)
        if isinstance(extra, dict):
            p.update({k: v for k, v in extra.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return p


def proj_key(cwd):
    """트랜스크립트 폴더 이름 — Claude Code 가 cwd 의 영숫자 외 문자를 전부 `-` 로 바꾼다."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(os.path.expanduser(cwd)))


def proj_key_for_prj(prj):
    """prj 번호 → 폴더 키. ___pm 원장(파일 1줄=경로)을 읽는다. 못 찾으면 None."""
    try:
        with open(os.path.join(PM_PROJECTS, str(prj)), encoding="utf-8") as fh:
            line = fh.readline().strip()
    except OSError:
        return None
    return proj_key(line) if line else None


def utc_day(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def quantile(vals, q):
    v = sorted(vals)
    if not v:
        return 0.0
    pos = (len(v) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def read_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) and isinstance(d.get("days"), dict) else None
    except (OSError, ValueError):
        return None


def _atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".cg-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_token_usage():
    import importlib.util
    spec = importlib.util.spec_from_file_location("token_usage", TOKEN_USAGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def refresh(now=None, force=False, scan=None):
    """일별 캐시 갱신. 마지막 완결일(`through`) 다음 날부터만 다시 센다 — 첫 적재만 느리다.
    `scan(since_dt, until_dt) -> {폴더: {날짜: 비용}}` 는 테스트 주입구."""
    now = int(now if now is not None else time.time())
    pol = policy()
    cache = read_cache() or {"days": {}, "through": None, "scanned_at": 0}
    if not force and now - int(cache.get("scanned_at") or 0) < pol["cache_ttl_secs"]:
        return {"ok": True, "skipped": "fresh", "scanned_at": cache.get("scanned_at")}
    utc = dt.timezone.utc
    today = dt.datetime.fromtimestamp(now, utc).replace(hour=0, minute=0, second=0, microsecond=0)
    floor_day = today - dt.timedelta(days=int(pol["window_days"]))
    if cache.get("through"):
        since = max(dt.datetime.strptime(cache["through"], "%Y-%m-%d").replace(tzinfo=utc) + dt.timedelta(days=1), floor_day)
    else:
        since = floor_day
    until = today + dt.timedelta(days=1)
    if scan is None:
        tu = _load_token_usage()
        scan = lambda s, u: tu.scan(TRANSCRIPT_ROOT, s, u)["by_proj_day"]  # noqa: E731
    fresh = scan(since, until)
    days = cache["days"]
    for key, per_day in fresh.items():
        days.setdefault(key, {}).update(per_day)
    keep_from = floor_day.strftime("%Y-%m-%d")
    for key in list(days):                                  # 창 밖 날짜는 버린다
        days[key] = {d: v for d, v in days[key].items() if d >= keep_from}
        if not days[key]:
            del days[key]
    cache.update({"days": days, "through": (today - dt.timedelta(days=1)).strftime("%Y-%m-%d"), "scanned_at": now})
    _atomic_write(CACHE_PATH, cache)
    return {"ok": True, "scanned_at": now, "since": since.strftime("%Y-%m-%d"), "projects": len(days)}


def _spawn_refresh():
    """낡은 캐시를 분리 프로세스로 갱신 — 소비처를 붙잡지 않는다. 임시 디렉토리(테스트)에서는 걸지 않는다."""
    if os.environ.get("FBOT_COST_GUARD_NO_SPAWN"):
        return False
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "refresh"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except OSError:
        return False


def weekly_status(now=None, pol=None):
    """Claude 주간 사용률 — {pct, age_min} 또는 None(실측 없음·낡음 → 건너뜀)."""
    pol = pol or policy()
    now = now if now is not None else time.time()
    try:
        with open(QUOTA_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("windows") or not d.get("fetched_at"):
        return None
    age = (now - float(d["fetched_at"])) / 60
    if age > float(pol["weekly_max_age_min"]):
        return None
    wk = [w for w in d["windows"] if w.get("window") == "weekly"]
    if not wk:
        return None
    return {"pct": max(float(w.get("used_pct") or 0) for w in wk), "age_min": round(age, 1)}


def judge(key, now=None, pol=None, cache=None):
    """프로젝트 `key`(폴더 이름)의 오늘 비용이 임계를 넘었는지. 캐시만 읽는다 — 낡으면 갱신을 걸되 기다리지 않는다.
    반환: {over, reason, key, day, today_cost, threshold, basis, samples, weekly}. 가드 해제·캐시 없음·키 없음은 over=False."""
    pol = pol or policy()
    now = int(now if now is not None else time.time())
    day = utc_day(now)
    out = {"over": False, "reason": "", "key": key, "day": day, "today_cost": 0.0, "threshold": None,
           "basis": None, "samples": 0, "weekly": None}
    if not pol["enabled"] or not key:
        out["reason"] = "disabled" if not pol["enabled"] else "no_key"
        return out
    cache = cache if cache is not None else read_cache()
    if cache is None:
        _spawn_refresh()
        out["reason"] = "no_cache"
        return out
    if now - int(cache.get("scanned_at") or 0) >= pol["cache_ttl_secs"]:
        _spawn_refresh()
    per_day = cache["days"].get(key, {})
    first = utc_day(now - int(pol["window_days"]) * 86400)
    hist = [v for d, v in per_day.items() if first <= d < day]
    cost = float(per_day.get(day, 0.0))
    if len(hist) >= int(pol["min_days"]):
        th, basis = max(float(pol["floor"]), quantile(hist, float(pol["percentile"]))), f"p{int(float(pol['percentile']) * 100)}"
    else:
        th, basis = float(pol["fallback"]), "fallback"
    out.update({"today_cost": cost, "threshold": th, "basis": basis, "samples": len(hist)})
    wk = weekly_status(now, pol)
    out["weekly"] = wk
    if cost >= th:
        out["over"], out["reason"] = True, f"일일 비용 {cost / 1e6:.1f}M ≥ 임계 {th / 1e6:.1f}M({basis}, 표본 {len(hist)}일)"
    elif wk and wk["pct"] >= float(pol["weekly_pct_limit"]):
        out["over"], out["reason"] = True, f"Claude 주간 사용률 {wk['pct']:.0f}% ≥ {pol['weekly_pct_limit']}%"
    return out


def send_mq(message, timeout=15):
    """aoa-mq 에 alert 1건 — helper 경유(직접 큐 파일 Write 금지). 실패는 예외로 올린다(notify_once 가 표지를 안 남긴다)."""
    if not os.path.exists(MQ_ENQUEUE_SH):
        raise RuntimeError(f"aoa-mq enqueue helper 없음: {MQ_ENQUEUE_SH}")
    r = subprocess.run([MQ_ENQUEUE_SH, "--message", message, "--alert", "--source", "fbot-cost-guard", "--from-bot",
                        os.environ.get("FBOT_ID") or "fbot-cost-guard"],
                       capture_output=True, text=True, timeout=timeout, start_new_session=True)
    if r.returncode != 0:
        raise RuntimeError(f"enqueue rc={r.returncode}: {(r.stderr or r.stdout)[-160:]}")


def alert_over(verdict, action, send=None):
    """발동 알림 — (프로젝트, 날짜)당 mq 1회. 반환은 notify_once 와 같다."""
    msg = (f"[fbot-cost-guard] {verdict['key']} {verdict['day']} 일일 비용 가드 발동 — {verdict['reason']}. "
           f"{action} (차단 아님 · 긴급·사람 결정 대기는 그대로)")
    return notify_once(verdict["key"], verdict["day"], msg, send or send_mq)


def notify_once(key, day, message, send):
    """(프로젝트, 날짜)당 1회만 `send(message)` — 성공했을 때만 표지를 남긴다(실패는 다음 호출이 다시 시도).
    반환: 'sent' | 'already' | 'error:<msg>'."""
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    marks = st.setdefault("notified", {})
    if marks.get(key) == day:
        return "already"
    try:
        send(message)
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}: {e}"[:200]
    marks[key] = day
    try:
        _atomic_write(STATE_PATH, st)
    except OSError as e:
        return f"sent(표지 기록 실패: {e})"
    return "sent"


def main(argv=None):
    ap = argparse.ArgumentParser(description="프로젝트 일일 비용 가드 (prj3#Issue1153)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("status")
    s.add_argument("--cwd")
    s.add_argument("--key")
    r = sp.add_parser("refresh")
    r.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "refresh":
        print(json.dumps(refresh(force=a.force), ensure_ascii=False))
        return 0
    key = a.key or (proj_key(a.cwd) if a.cwd else proj_key(os.getcwd()))
    print(json.dumps(judge(key), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
