#!/usr/bin/env bash
# fbot-bootstrap.sh — aoa 데이터 루트 최초 생성 (Issue451 ②·멱등)
#
# 왜 필요한가 (2026-08-26 fg1 실측):
#   fbot 진입점(fbot-state.py·fbot-taskmgr.py·fbot-hr-gate.py)은 registry.db·policy.yml 이
#   없으면 fail-loud 로 죽는다. 그 자체는 옳은 설계지만 — **아무도 그 둘을 만들지 않았다.**
#   개발 머신에는 prj5 작업 산출물로 우연히 존재했을 뿐이라, 소비자는 설치를 끝내고도
#   진입점 전부가 rc!=0 인 상태를 받는다. "설치는 됐는데 안 된다" 는 무신호 실패다.
#
# 무엇을 만드는가
#   1. $AOA_DIR                      (기본 ~/.claude/data/aoa)
#   2. registry.db · learn.db        mcp/aoa-memory/store.py 의 DDL 로 생성 — DDL 복제 금지
#   3. policy.yml                    data/aoa/policy.default.yml 기준. **비파괴**:
#                                      부재 → 통째 복사 / 존재 → 없는 키만 덧붙임
#
# 사용: bash sh/fbot-bootstrap.sh [--dry-run]
#   env: AOA_MEMORY_DIR (데이터 루트) · FBOT_PYTHON (python3 절대경로)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

info() { printf '\033[36m[fbot-bootstrap]\033[0m %s\n' "$1"; }
warn() { printf '\033[33m[fbot-bootstrap]\033[0m %s\n' "$1"; }
err()  { printf '\033[31m[fbot-bootstrap]\033[0m %s\n' "$1" >&2; }

DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

# ── python3 해석 (Issue451 ① 과 동일 계약 — 절대경로 하드코딩 금지) ──
resolve_python() {
    local c
    if [[ -n "${FBOT_PYTHON:-}" ]]; then printf '%s' "$FBOT_PYTHON"; return 0; fi
    c="$(command -v python3 2>/dev/null || true)"
    [[ -n "$c" ]] && { printf '%s' "$c"; return 0; }
    for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
        [[ -x "$c" ]] && { printf '%s' "$c"; return 0; }
    done
    return 1
}
PY="$(resolve_python)" || { err "🚨 python3 미발견 — FBOT_PYTHON 을 절대경로로 지정하라"; exit 1; }

AOA_DIR="${AOA_MEMORY_DIR:-$HOME/.claude/data/aoa}"
STORE_PY="$REPO_DIR/mcp/aoa-memory/store.py"
POLICY_SRC="$REPO_DIR/data/aoa/policy.default.yml"
POLICY_DST="$AOA_DIR/policy.yml"

[[ -f "$STORE_PY"   ]] || { err "🚨 store.py 부재: $STORE_PY (저장소 손상?)"; exit 1; }
[[ -f "$POLICY_SRC" ]] || { err "🚨 정책 템플릿 부재: $POLICY_SRC (저장소 손상?)"; exit 1; }

info "python3   : $PY"
info "데이터 루트: $AOA_DIR"
if [[ "$DRY" -eq 1 ]]; then info "--dry-run — 아무것도 만들지 않고 종료"; exit 0; fi

# ── 1·2. 스토어 생성 (멱등 — store.py 가 CREATE TABLE IF NOT EXISTS 로 보장) ──
mkdir -p "$AOA_DIR"
if AOA_MEMORY_DIR="$AOA_DIR" "$PY" "$STORE_PY"; then
    info "스토어 준비 완료 (registry.db · learn.db)"
else
    err "🚨 스토어 생성 실패 — 위 오류 참조 (FTS5 미탑재 python3 이면 sqlite3 빌드 교체 필요)"
    exit 1
fi

# ── 3. policy.yml — 비파괴 병합 ──
if [[ ! -f "$POLICY_DST" ]]; then
    cp "$POLICY_SRC" "$POLICY_DST"
    info "policy.yml 생성: $POLICY_DST (템플릿 복사 — 값은 자유롭게 편집)"
else
    # 기존 파일의 키 집합을 뽑아, 템플릿에만 있는 키를 말미에 덧붙인다.
    # 기존 줄은 한 줄도 건드리지 않는다 — 운영자가 조정한 값을 되돌리면 안 된다.
    missing="$(AOA_POLICY_SRC="$POLICY_SRC" AOA_POLICY_DST="$POLICY_DST" "$PY" - <<'PYEOF'
import os, re
src, dst = os.environ["AOA_POLICY_SRC"], os.environ["AOA_POLICY_DST"]
key = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")
have = set()
for line in open(dst, encoding="utf-8"):
    m = key.match(line)
    if m:
        have.add(m.group(1))
out = []
for line in open(src, encoding="utf-8"):
    m = key.match(line)
    if m and m.group(1) not in have:
        out.append(line.rstrip("\n"))
print("\n".join(out))
PYEOF
)"
    if [[ -n "$missing" ]]; then
        {
            printf '\n# ── 아래는 sh/fbot-bootstrap.sh 가 덧붙인 기본값 (%s) ──\n' "$(date '+%Y.%m.%d')"
            printf '%s\n' "$missing"
        } >> "$POLICY_DST"
        info "policy.yml 에 누락 키 추가 ($(printf '%s\n' "$missing" | grep -c . )건) — 기존 값 보존"
    else
        info "policy.yml 이미 완비 — 변경 없음"
    fi
fi

printf '\n✅ fbot 데이터 루트 준비 완료: %s\n' "$AOA_DIR"
printf '   확인: AOA_MEMORY_DIR=%s python3 <plugin>/hooks/fbot-state.py list\n' "$AOA_DIR"
