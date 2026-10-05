#!/usr/bin/env bash
# release-marketplace-install.sh — 배포 재생목록 3행 marketplace-install (Issue543 M1-3)
#
# 묻는 것: *"이 후보를 마켓에서 받으면 설치되고, 설치본의 hook 이 실제로 기동 가능한가."*
#   종전엔 `claude plugin validate` 가 발행(publish-scar.sh) 때만 돌았고, 설치까지 가는 검증은
#   출고 뒤 소비자 머신에서 사람이 했다. validate·install 은 hooks.json 이 가리키는 스크립트의
#   부재·실행 권한 상실을 잡지 않는다 — 설치는 «성공» 하고 세션마다 hook 이 조용히 실패한다.
#
# 절차 (후보 트리를 **로컬 마켓 소스**로 — 원격 마켓 검증은 출고 후 P2 소관):
#   1. claude plugin validate <번들>
#   2. 임시 HOME·CLAUDE_CONFIG_DIR 에서 marketplace add <후보> → install <plugin>@<마켓>
#   3. 설치 버전 = VERSION = 번들 plugin.json
#   4. 설치본 hooks.json 의 모든 command 스크립트가 존재하고 실행 가능 (hook 로드 오류 0)
#   실 ~/.claude 는 건드리지 않는다 — HOME·CLAUDE_CONFIG_DIR 를 함께 격리한다
#
# 사용: bash tdd/release-marketplace-install.sh [--repo <마켓 소스 루트>]   (기본: 이 스크립트의 repo)
# exit: 0 PASS · 1 FAIL · 3 검증 불가(claude CLI 없음 — partial)
set -uo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO_DIR="$(cd "${2:-.}" && pwd)"; shift 2 ;;
        *) echo "❌ 알 수 없는 인자: $1" >&2; exit 2 ;;
    esac
done

command -v claude >/dev/null 2>&1 || { echo "skip: claude CLI 없음 — 설치 검증 불가 (partial)"; exit 3; }
MKT_JSON="$REPO_DIR/.claude-plugin/marketplace.json"
[ -f "$MKT_JSON" ] || { echo "FAIL: 마켓 매니페스트 없음: $MKT_JSON"; exit 1; }

read -r MKT_NAME PLUGIN PSRC < <(python3 - "$MKT_JSON" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
p = next((x for x in m.get("plugins", []) if x.get("name") == "fpm-core"), (m.get("plugins") or [{}])[0])
print(m.get("name", "?"), p.get("name", "?"), p.get("source", "?"))
PYEOF
)
BUNDLE="$REPO_DIR/${PSRC#./}"
WANT="$(tr -d '[:space:]' < "$REPO_DIR/VERSION" 2>/dev/null)"
fails=0
okm()  { echo "  ok   $1"; }
bad()  { echo "  FAIL $1"; fails=$((fails+1)); }

# 1. validate — 경고는 허용(런타임이 수용), 오류만 실패
if vout="$(claude plugin validate "$BUNDLE" 2>&1)"; then okm "validate ($PLUGIN)"
else bad "validate: $(printf '%s' "$vout" | grep -v '^\s*$' | tail -2 | tr '\n' ' ')"; fi

# 2. 임시 HOME 설치
SBX="$(mktemp -d "${TMPDIR:-/tmp}/fpm-mkt.XXXXXX")"
trap 'case "$SBX" in */fpm-mkt.*) rm -rf "$SBX" ;; esac' EXIT
C() { (cd "$SBX" && env HOME="$SBX" CLAUDE_CONFIG_DIR="$SBX/.claude" claude "$@"); }
if out="$(C plugin marketplace add "$REPO_DIR" 2>&1)"; then okm "marketplace add $MKT_NAME (로컬 소스)"
else bad "marketplace add: $(printf '%s' "$out" | tail -1)"; echo "결과: FAIL $fails"; exit 1; fi
if out="$(C plugin install "$PLUGIN@$MKT_NAME" 2>&1)"; then okm "install $PLUGIN@$MKT_NAME"
else bad "install: $(printf '%s' "$out" | tail -1)"; echo "결과: FAIL $fails"; exit 1; fi

# 3·4. 설치 버전 · hook 스크립트 실행 가능성 — 설치본(installPath) 기준
list_json="$(C plugin list --json 2>/dev/null)"
chk="$(LIST_JSON="$list_json" python3 - "$PLUGIN@$MKT_NAME" "$WANT" "$BUNDLE/.claude-plugin/plugin.json" <<'PYEOF'
import json, os, sys
pid, want, pj = sys.argv[1:4]
items = json.loads(os.environ.get("LIST_JSON") or "[]")
it = next((x for x in items if x.get("id") == pid), None)
if not it:
    print(f"FAIL 설치 목록에 {pid} 없음"); sys.exit(0)
got = it.get("version", "?")
src = json.load(open(pj, encoding="utf-8")).get("version", "?")
print(("ok" if got == want == src else "FAIL") + f" 설치 버전 {got} (VERSION {want} · plugin.json {src})")
print(("ok" if it.get("enabled") else "FAIL") + " enabled")
root = it.get("installPath", "")
hj = os.path.join(root, "hooks", "hooks.json")
if not os.path.isfile(hj):
    print("ok hooks 없음 (hook 로드 대상 0)"); sys.exit(0)
bad, n = [], 0
for ev, arr in (json.load(open(hj, encoding="utf-8")).get("hooks") or {}).items():
    for m in arr:
        for h in m.get("hooks", []):
            cmd = (h.get("command") or "").replace("${CLAUDE_PLUGIN_ROOT}", root).replace("$CLAUDE_PLUGIN_ROOT", root)
            first = cmd.strip().strip('"').split()[0] if cmd.strip() else ""
            if not first.startswith(root):
                continue  # 인터프리터 경유(bash x.sh 등)는 첫 토큰이 번들 경로가 아니다
            n += 1
            rel = os.path.relpath(first, root)
            if not os.path.isfile(first):
                bad.append(f"{ev}: {rel} 없음")
            elif not os.access(first, os.X_OK):
                bad.append(f"{ev}: {rel} 실행 권한 없음")
if bad:
    for b in bad:
        print("FAIL hook " + b)
else:
    print(f"ok hook 스크립트 {n}건 전부 존재·실행 가능")
PYEOF
)"
while IFS= read -r line; do
    case "$line" in ok*) okm "${line#ok }" ;; FAIL*) bad "${line#FAIL }" ;; *) [ -n "$line" ] && echo "  $line" ;; esac
done <<< "$chk"

if [ "$fails" -eq 0 ]; then echo "결과: PASS — $PLUGIN v$WANT 로컬 마켓 설치·hook 기동 가능"; exit 0; fi
echo "결과: FAIL $fails"
exit 1
