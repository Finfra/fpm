#!/usr/bin/env bash
# fpm-lockstep-check.sh — 릴리스 버전 정합 게이트 (V4 / prj3 감사 F5)
#
# ⚠️ 글로벌 SCAR 변경 가드: cwd ≠ ~/_git/___pm 이면 즉흥 수정 금지.
#   선언 SSOT: data/releases/lockstep.yml · 마스터 현황: _doc_arch/fapp-version.md
#
# 왜: X3 로 prj16↔prj26 어긋남을 고쳤지만 **게이트가 없으면 다음 릴리스에 재발**한다.
#   선언(lockstep.yml)과 실물(VERSION 파일)을 대조해 배포 전에 막는다.
#
# ⚠️ 선언한 쌍만 본다. 전부를 강제하지 않는 이유는 lockstep.yml 헤더 참조
#   (paidApp↔cliApp 은 채널·주기가 독립이라 patch 가 갈리는 것이 정상이다).
#
# Usage:
#   bash scripts/fpm-lockstep-check.sh            # 전 쌍 검사
#   bash scripts/fpm-lockstep-check.sh fWarrange  # 특정 쌍만
#   rc=0 정합 / rc=1 위반

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DECL="${FPM_LOCKSTEP_DECL:-$HERE/../data/releases/lockstep.yml}"
ONLY="${1:-}"

[ -f "$DECL" ] || { echo "❌ 선언 파일 없음: $DECL" >&2; exit 1; }

DECL="$DECL" ONLY="$ONLY" python3 <<'PYEOF'
import os, re, sys

decl, only = os.environ["DECL"], os.environ.get("ONLY", "")
txt = open(decl, encoding="utf-8").read()

# 의존성 0 — 선언 스키마가 단순 고정 형태라 정규식으로 읽는다(PyYAML 을 새로 들이지 않는다)
pairs, cur = [], None
for ln in txt.splitlines():
    if re.match(r"^\s*-\s+name:", ln):
        cur = {"name": ln.split(":", 1)[1].strip(), "level": "minor", "members": []}
        pairs.append(cur)
    elif cur is not None and re.match(r"^\s+level:", ln):
        cur["level"] = ln.split(":", 1)[1].strip()
    elif cur is not None and "prj:" in ln and "path:" in ln:
        m = re.search(r"prj:\s*(\d+).*?path:\s*([^,}]+).*?role:\s*([^,}\s]+)", ln)
        if m:
            cur["members"].append((m.group(1), m.group(2).strip(), m.group(3).strip()))

fail = 0
checked = 0
for p in pairs:
    if only and p["name"] != only:
        continue
    if p["level"] == "none":
        print(f"⏭️  {p['name']} — level=none (검증 안 함)")
        continue
    vers = []
    for prj, path, role in p["members"]:
        vf = os.path.join(os.path.expanduser(path.replace("~", os.path.expanduser("~"))), "VERSION")
        try:
            v = open(vf, encoding="utf-8").read().strip()
        except Exception:
            print(f"❌ {p['name']} — VERSION 없음: {vf}")
            fail = 1
            v = None
        vers.append((prj, role, v))
    if any(v is None for _, _, v in vers):
        continue
    checked += 1

    def key(v):
        parts = v.split(".")
        return ".".join(parts[:3]) if p["level"] == "exact" else ".".join(parts[:2])

    keys = {key(v) for _, _, v in vers}
    detail = " · ".join(f"prj{prj}({role}) {v}" for prj, role, v in vers)
    if len(keys) == 1:
        print(f"✅ {p['name']} [{p['level']}] — {detail}")
    else:
        print(f"❌ {p['name']} [{p['level']}] 정합 위반 — {detail}")
        print(f"   {p['level']} 수준까지 일치해야 한다. 올리는 방향으로만 맞출 것"
              f"(App Store 는 버전 역행을 거부한다)")
        fail = 1

if checked == 0 and not fail:
    print("검사한 쌍 0 — 선언을 확인할 것")
sys.exit(fail)
PYEOF
