#!/usr/bin/env python3
"""engine.py — gh-sync 동기 엔진 (Issue233 T6)

status / push / pull 서브커맨드. 로컬 Issue.md 가 SSOT, GitHub Issues 는
옵트인 미러. push=로컬→GH, pull=GH→로컬(dry-run+local-wins).

불변식(plan SSOT):
  - enabled:false 면 push/pull no-op (gate)
  - push 전 guard_before_push 시 fpm-guard.sh 호출(개인정보 abort) — 본 모듈은
    호출 결과만 신뢰, 내용 판단 안 함
  - pull 은 working tree 만 변경(자동 커밋 금지), 충돌은 local-wins + manual 표시
  - 외부 쓰기(gh create/edit)는 --apply 명시 시만. 기본 dry-run

설계 SSOT: _doc_work/plan/gh-issue-bridge_plan.md
"""
import os
import sys
import json
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from parse_issuemd import parse  # noqa: E402
from map import to_gh_payload, gh_to_summary, diff_local_remote  # noqa: E402

_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ISSUE_MD = os.path.join(_ROOT, "Issue.md")
_CFG = os.path.join(_ROOT, "data", "gh-sync.yml")
_GUARD = os.path.join(_ROOT, "scripts", "fpm-guard.sh")


def _log(msg):
    print(f"[gh-sync] {msg}", file=sys.stderr)


def load_cfg():
    import yaml
    if not os.path.exists(_CFG):
        return {}
    with open(_CFG, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_repo(cfg):
    repo = (cfg.get("repo") or "").strip()
    if repo:
        return repo
    # git origin 추론
    try:
        url = subprocess.check_output(
            ["git", "-C", _ROOT, "remote", "get-url", "origin"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return ""
    # git@github.com:owner/name.git | https://github.com/owner/name.git
    import re
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def load_issues(active_only=True):
    with open(_ISSUE_MD, encoding="utf-8") as f:
        issues = parse(f.read())
    if active_only:
        # 동기 대상 = 비완료(open) 또는 이미 매핑된 것. 완료 208건 전체 push 방지.
        issues = [i for i in issues if i["state"] == "open" or i["gh"] is not None]
    return issues


def filter_syncable(issues, cfg):
    excl = set(cfg.get("exclude_sections", []))
    return [i for i in issues if i["section"] not in excl]


# ── status ──────────────────────────────────────────────
def cmd_status(args):
    cfg = load_cfg()
    repo = resolve_repo(cfg)
    issues = load_issues(active_only=True)
    syncable = filter_syncable(issues, cfg)
    mapped = [i for i in syncable if i["gh"] is not None]
    unmapped = [i for i in syncable if i["gh"] is None]
    print(f"enabled       : {cfg.get('enabled', False)}")
    print(f"repo          : {repo or '(미설정)'}")
    print(f"conflict      : {cfg.get('conflict', 'local')}")
    print(f"동기대상(active): {len(syncable)}")
    print(f"  매핑됨       : {len(mapped)}")
    print(f"  미매핑       : {len(unmapped)}")
    if unmapped:
        print("  미매핑 목록  :")
        for i in unmapped[:20]:
            print(f"    Issue{i['num']} [{i['section']}] {i['title'][:50]}")
    return 0


# ── push ────────────────────────────────────────────────
def _run_guard():
    if not os.path.exists(_GUARD):
        _log("WARN: fpm-guard.sh 없음 — 가드 skip")
        return True
    r = subprocess.run(["bash", _GUARD], cwd=_ROOT)
    return r.returncode == 0


def _gh(args, repo, input_=None, capture=True):
    cmd = ["gh"] + args + ["-R", repo]
    return subprocess.run(cmd, input=input_, text=True,
                          capture_output=capture)


def writeback_gh(num, gh_num):
    """Issue.md 의 Issue{num} 헤더 다음 `* 목적:` 줄 아래에 `* gh: #M` 삽입.
    이미 있으면 값 갱신. working tree 만 변경(커밋은 호출측)."""
    with open(_ISSUE_MD, encoding="utf-8") as f:
        lines = f.readlines()
    import re
    hdr = re.compile(rf"^##\s+Issue{num}(?:_\d+)?:")
    gh_line = re.compile(r"^\*\s+gh:\s*#?\d+\s*$")
    out = []
    i = 0
    inserted = False
    while i < len(lines):
        out.append(lines[i])
        if hdr.match(lines[i]):
            # 헤더 발견 → 블록 내 기존 gh 줄 갱신 or 목적 아래 삽입
            j = i + 1
            block = []
            while j < len(lines) and not lines[j].startswith("## ") and not lines[j].startswith("# "):
                block.append(lines[j])
                j += 1
            # 기존 gh 줄 있으면 갱신
            replaced = False
            for k, bl in enumerate(block):
                if gh_line.match(bl):
                    block[k] = f"* gh: #{gh_num}\n"
                    replaced = True
                    break
            if not replaced:
                # 첫 `* 목적:` 다음에 삽입, 없으면 블록 맨 앞
                pos = 0
                for k, bl in enumerate(block):
                    if bl.startswith("* 목적:"):
                        pos = k + 1
                        break
                block.insert(pos, f"* gh: #{gh_num}\n")
            out.extend(block)
            inserted = True
            i = j
            continue
        i += 1
    if inserted:
        with open(_ISSUE_MD, "w", encoding="utf-8") as f:
            f.writelines(out)
    return inserted


def cmd_push(args):
    cfg = load_cfg()
    if not cfg.get("enabled", False):
        _log("enabled:false — push no-op. data/gh-sync.yml 에서 enabled:true 설정 후 재시도")
        return 0
    repo = resolve_repo(cfg)
    if not repo:
        _log("repo 미해결 — data/gh-sync.yml repo 지정 또는 git origin 설정 필요")
        return 1

    label_map = cfg.get("label_map", {})
    issues = filter_syncable(load_issues(active_only=True), cfg)
    targets = issues  # 미매핑=create, 매핑=edit

    if not args.apply:
        _log(f"[DRY-RUN] repo={repo} 대상 {len(targets)}건")
        for i in targets:
            payload = to_gh_payload(i, label_map)
            action = "EDIT #%d" % i["gh"] if i["gh"] else "CREATE"
            print(f"  {action}: {payload['title']}  labels={payload['labels']} state={payload['state']}")
        _log("실제 반영하려면 --apply (개인정보 가드 후 gh 쓰기)")
        return 0

    # --apply: 가드 → gh 쓰기
    if cfg.get("guard_before_push", True) and not _run_guard():
        _log("🚨 개인정보 가드 abort — push 중단")
        return 2

    created = edited = 0
    for i in targets:
        payload = to_gh_payload(i, label_map)
        if i["gh"]:
            r = _gh(["issue", "edit", str(i["gh"]), "--title", payload["title"],
                     "--body", payload["body"]], repo)
            if r.returncode == 0:
                edited += 1
            else:
                _log(f"edit #{i['gh']} 실패: {r.stderr.strip()[:120]}")
        else:
            r = _gh(["issue", "create", "--title", payload["title"],
                     "--body", payload["body"]], repo)
            if r.returncode == 0:
                # 생성된 issue URL 끝 번호 파싱
                import re
                m = re.search(r"/issues/(\d+)", r.stdout.strip())
                if m:
                    ghn = int(m.group(1))
                    writeback_gh(i["num"], ghn)
                    created += 1
                else:
                    _log(f"create 응답 파싱 실패: {r.stdout.strip()[:120]}")
            else:
                _log(f"create Issue{i['num']} 실패: {r.stderr.strip()[:120]}")
    _log(f"push 완료 — created={created} edited={edited}. Issue.md 매핑 변경분 검토 후 커밋")
    return 0


# ── pull ────────────────────────────────────────────────
def cmd_pull(args):
    cfg = load_cfg()
    if not cfg.get("enabled", False):
        _log("enabled:false — pull no-op")
        return 0
    repo = resolve_repo(cfg)
    if not repo:
        _log("repo 미해결")
        return 1

    r = _gh(["issue", "list", "--state", "all", "--limit", "500",
             "--json", "number,title,state,labels,body"], repo)
    if r.returncode != 0:
        _log(f"gh issue list 실패: {r.stderr.strip()[:120]}")
        return 1
    remote = [gh_to_summary(x) for x in json.loads(r.stdout or "[]")]
    remote_by_local = {x["local_num"]: x for x in remote if x["local_num"]}

    local = {i["num"]: i for i in load_issues(active_only=True)}
    conflicts = []
    for num, rsum in remote_by_local.items():
        l = local.get(num)
        if not l:
            continue
        d = diff_local_remote(l, rsum)
        if d:
            conflicts.append((num, d))

    _log(f"[PULL DRY-RUN] repo={repo} 매핑 {len(remote_by_local)}건, 충돌 {len(conflicts)}건")
    if not conflicts:
        _log("로컬과 차이 없음 — pull 불필요 (local-wins)")
        return 0
    print("충돌(로컬 != GH) — local-wins 기본, manual 검토 대상:")
    for num, diffs in conflicts:
        for field, lval, rval in diffs:
            print(f"  Issue{num} {field}: 로컬='{lval}' / GH='{rval}'")
    _log("정책: conflict=%s. 자동 병합 미수행(working tree 보호). 수동 반영 필요." % cfg.get("conflict", "local"))
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="gh-sync 엔진")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_push = sub.add_parser("push")
    p_push.add_argument("--apply", action="store_true", help="실제 gh 쓰기(기본 dry-run)")
    sub.add_parser("pull")
    args = ap.parse_args()

    return {"status": cmd_status, "push": cmd_push, "pull": cmd_pull}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
