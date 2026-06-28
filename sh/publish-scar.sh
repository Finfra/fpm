#!/usr/bin/env bash
# publish-scar.sh — fpm-core SCAR 발행 (소스 → 마켓), Issue236
#
# fpm `plugins/fpm-core/`(소스 SSOT) → `f-claude-plugins/fpm-core/`(마켓) 발행을 자동화한다.
# 과거 수동 rsync + 버전 bump + push 라 누락되기 쉬웠고, 소스 ↔ 마켓 버전이 크게 벌어진
# 채 방치되는 드리프트가 반복됐다(ex: 소스 0.8.x ↔ 마켓 0.7.11).
#
# 동작:
#   1. 소스 plugin.json version 읽기 → 마켓 plugin.json + marketplace.json entry 3곳 동기
#   2. rsync --delete 로 소스 → 마켓 미러 (소스에 없는 파일은 마켓에서 제거)
#   3. `claude plugin validate` 게이트 (실패 시 push 중단)
#   4. f-claude-plugins 의 fpm-core/ + marketplace.json 만 staging → commit → push
#
# 사용: bash sh/publish-scar.sh              발행 (commit + push)
#       bash sh/publish-scar.sh --dry-run    검사·diff 만, 쓰기/commit/push 없음
#       bash sh/publish-scar.sh --no-push     commit 까지만 (push 생략)
#   env FPM_MKT_LOCAL=<path>  마켓 로컬 사본 경로 override (기본: 자동 탐지)
# exit: 0=발행 성공/dry-run PASS, 1=실패(검증·경로·push)
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

info()  { printf '\033[36m[publish]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[publish]\033[0m %s\n' "$1"; }
err()   { printf '\033[31m[publish]\033[0m %s\n' "$1" >&2; }

MANIFEST="$REPO_DIR/data/install_manifest.sh"
[[ -f "$MANIFEST" ]] || { err "🚨 매니페스트 없음: $MANIFEST"; exit 1; }
# shellcheck source=data/install_manifest.sh
source "$MANIFEST"

DRY=0; NO_PUSH=0
for a in "$@"; do
    case "$a" in
        --dry-run|-n) DRY=1 ;;
        --no-push)    NO_PUSH=1 ;;
        -h|--help) echo "usage: sh/publish-scar.sh [--dry-run] [--no-push]  (env FPM_MKT_LOCAL=<path>)"; exit 0 ;;
        *) warn "알 수 없는 인자: $a (무시)" ;;
    esac
done

# ── 소스 (SSOT) ─────────────────────────────────────────────
SRC="$REPO_DIR/$FPM_PLUGIN_SRC_REL_REPO"            # plugins/fpm-core
SRC_PJSON="$SRC/.claude-plugin/plugin.json"
[[ -d "$SRC" && -f "$SRC_PJSON" ]] || { err "🚨 소스 미발견: $SRC_PJSON"; exit 1; }

SRC_VER="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$SRC_PJSON")" \
    || { err "🚨 소스 version 파싱 실패"; exit 1; }
info "소스: $SRC (version $SRC_VER)"

# ── 마켓 dest 탐지 (env > 인접 > __all) ──────────────────────
DEST_ROOT=""
for c in "${FPM_MKT_LOCAL:-}" "$REPO_DIR/../f-claude-plugins" "$HOME/_git/__all/f-claude-plugins"; do
    [[ -n "$c" && -d "$c/.claude-plugin" ]] && { DEST_ROOT="$(cd "$c" && pwd)"; break; }
done
[[ -n "$DEST_ROOT" ]] || { err "🚨 마켓 사본 미발견 — FPM_MKT_LOCAL=<path> 로 지정"; exit 1; }
DEST="$DEST_ROOT/$FPM_PLUGIN_NAME"                  # f-claude-plugins/fpm-core
DEST_PJSON="$DEST/.claude-plugin/plugin.json"
MKT_JSON="$DEST_ROOT/.claude-plugin/marketplace.json"
[[ -d "$DEST" && -f "$MKT_JSON" ]] || { err "🚨 마켓 구조 이상: $DEST / $MKT_JSON"; exit 1; }
info "마켓: $DEST_ROOT"

OLD_VER="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$DEST_PJSON" 2>/dev/null || echo '?')"
info "버전: 마켓 $OLD_VER → $SRC_VER"

if [[ "$DRY" -eq 1 ]]; then
    info "[dry-run] rsync diff (소스 → 마켓):"
    rsync -ain --delete --exclude '.git' --exclude '.DS_Store' "$SRC/" "$DEST/" | sed 's/^/  /' || true
    info "[dry-run] 버전 동기 대상: $DEST_PJSON, $MKT_JSON entry(fpm-core) → $SRC_VER"
    info "[dry-run] 쓰기·commit·push 없음. 종료."
    exit 0
fi

# ── 1. rsync 미러 (--delete) ────────────────────────────────
info "rsync 미러 (--delete)…"
rsync -a --delete --exclude '.git' --exclude '.DS_Store' "$SRC/" "$DEST/" || { err "🚨 rsync 실패"; exit 1; }

# ── 2. 버전 3곳 동기 (소스→마켓 plugin.json + marketplace.json entry) ──
python3 - "$DEST_PJSON" "$MKT_JSON" "$FPM_PLUGIN_NAME" "$SRC_VER" <<'PY'
import json, sys
dest_pjson, mkt_json, name, ver = sys.argv[1:5]
# 마켓 plugin.json (rsync 로 소스값 복사됐으나 명시 보정)
d = json.load(open(dest_pjson)); d["version"] = ver
json.dump(d, open(dest_pjson, "w"), ensure_ascii=False, indent=2); open(dest_pjson,"a").write("\n")
# marketplace.json entry
m = json.load(open(mkt_json)); hit = False
for p in m.get("plugins", []):
    if p.get("name") == name:
        p["version"] = ver; hit = True
if not hit:
    raise SystemExit(f"marketplace.json 에 {name} entry 없음")
json.dump(m, open(mkt_json, "w"), ensure_ascii=False, indent=2); open(mkt_json,"a").write("\n")
print(f"[publish] 버전 동기 완료 → {ver}")
PY
[[ $? -eq 0 ]] || { err "🚨 버전 동기 실패"; exit 1; }

# ── 3. validate 게이트 ──────────────────────────────────────
if command -v claude >/dev/null 2>&1; then
    info "claude plugin validate 게이트…"
    if ! claude plugin validate "$DEST" 2>&1 | sed 's/^/  /'; then
        err "🚨 validate 실패 — push 중단. 마켓 사본 변경은 남아있으니 수동 확인."
        exit 1
    fi
else
    warn "claude CLI 미발견 — validate 게이트 생략 (계속 진행)"
fi

# ── 4. commit + push (fpm-core/ + marketplace.json 만) ──────
if ! git -C "$DEST_ROOT" diff --quiet -- "$FPM_PLUGIN_NAME" "$MKT_JSON" 2>/dev/null \
   || [[ -n "$(git -C "$DEST_ROOT" status --porcelain -- "$FPM_PLUGIN_NAME")" ]]; then
    git -C "$DEST_ROOT" add "$FPM_PLUGIN_NAME" ".claude-plugin/marketplace.json"
    git -C "$DEST_ROOT" commit -q -m "Publish: fpm-core $OLD_VER → $SRC_VER (자동 발행)" \
        || { err "🚨 commit 실패"; exit 1; }
    info "commit 완료: fpm-core $OLD_VER → $SRC_VER"
    if [[ "$NO_PUSH" -eq 0 ]]; then
        if ! git -C "$DEST_ROOT" push 2>&1 | sed 's/^/  /'; then
            err "🚨 push 실패 — 1회 재시도 후에도 실패 시 수동 push 필요"; exit 1
        fi
        info "push 완료 ✅"
    else
        info "--no-push: push 생략 (commit 까지만)"
    fi
else
    info "변경 없음 — 마켓이 이미 최신($SRC_VER). 발행 생략."
fi
