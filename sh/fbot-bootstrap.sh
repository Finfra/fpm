#!/usr/bin/env bash
# fbot-bootstrap.sh — aoa 데이터 루트 최초 생성 (prj3#Issue451 ②·멱등)
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
#   3. policy.yml                    data/template/aoa-policy.default.yml 기준. **비파괴**:
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

# ── python3 해석 (prj3#Issue451 ① 과 동일 계약 — 절대경로 하드코딩 금지) ──
#   Issue436: 후보 목록이 /opt/homebrew/… 등 **Unix 경로뿐**이라 Windows 에는 대안이 없었고,
#   `command -v` 는 MS Store 스텁을 실물로 통과시켰다. 해석은 sh/fbot-python.sh 가 SSOT 다.
# shellcheck source=sh/fbot-python.sh
source "$REPO_DIR/sh/fbot-python.sh"
# store.py 가 sqlite3 를 요구한다 — "실행되는 python" 이 아니라 "이 일을 할 수 있는 python" 을 고른다.
if ! fbot_resolve_python sqlite3; then
    err "🚨 쓸 수 있는 python 없음 — 후보 전멸: ${FBOT_PY_REJECT:-없음}"
    err "   조치: python 을 PATH 에 두거나 FBOT_PYTHON 으로 절대경로를 지정하라"
    exit 1
fi
PY=("${FBOT_PY_ARGV[@]}")
# 채택 근거를 남긴다 (Issue436 ⓑ) — 스텁을 걸러낸 사실이 출력에 보이지 않으면 진단이 불가능하다.
# ⚠️ `[[ ]] && cmd` 형태로 쓰면 set -e 하에서 조건 거짓일 때 rc=1 로 스크립트가 죽는다.
if [[ -n "$FBOT_PY_REJECT" ]]; then info "python 후보 탈락: $FBOT_PY_REJECT"; fi

AOA_DIR="${AOA_MEMORY_DIR:-$HOME/.claude/data/aoa}"
STORE_PY="$REPO_DIR/mcp/aoa-memory/store.py"
# Issue449: 템플릿은 **런타임 데이터 디렉토리 밖**에 둔다. 종전 위치(data/aoa/)는 gitignore·
#   publishable 양쪽 규칙이 디렉토리 단위로 도는 곳이라, 한쪽을 만족시키면 다른 쪽이 깨졌다
#   (gitignore 축 = Issue447, 미러 배포 축 = Issue449). 배치를 고치는 것이 뿌리 제거다.
POLICY_SRC="$REPO_DIR/data/template/aoa-policy.default.yml"
# 이행 폴백(읽기 전용) — 구버전 클론에는 옛 경로만 있다. 새 경로가 있으면 그쪽이 항상 이긴다.
[[ -f "$POLICY_SRC" ]] || POLICY_SRC="$REPO_DIR/data/aoa/policy.default.yml"
POLICY_DST="$AOA_DIR/policy.yml"

[[ -f "$STORE_PY"   ]] || { err "🚨 store.py 부재: $STORE_PY (저장소 손상?)"; exit 1; }
# ⚠️ 정책 템플릿 가드는 여기 두지 않는다 (Issue447 ⓓ) — 템플릿 부재는 스토어 생성과 무관한데
#   앞에 두는 바람에 registry.db·learn.db 생성까지 함께 막았다. 3단계 직전으로 내렸다.

info "python3   : ${PY[*]}"
info "데이터 루트: $AOA_DIR"
if [[ "$DRY" -eq 1 ]]; then info "--dry-run — 아무것도 만들지 않고 종료"; exit 0; fi

# ── 1·2. 스토어 생성 (멱등 — store.py 가 CREATE TABLE IF NOT EXISTS 로 보장) ──
mkdir -p "$AOA_DIR"
if AOA_MEMORY_DIR="$AOA_DIR" "${PY[@]}" "$STORE_PY"; then
    info "스토어 준비 완료 (registry.db · learn.db)"
else
    # Issue436 ⓓ: FTS5 를 **실제로 검사한 뒤에만** 그 원인을 말한다.
    #   종전엔 실패하면 무조건 "FTS5 미탑재면 sqlite3 빌드 교체" 를 띄웠다. jpc1 실측에서
    #   FTS5 는 멀쩡했고(가상테이블 생성 통과) 진짜 원인은 인터프리터였다 — 오진을 유도했다.
    if "${PY[@]}" -c "
import sqlite3, sys
c = sqlite3.connect(':memory:')
n = c.execute(\"SELECT count(*) FROM pragma_compile_options WHERE compile_options LIKE 'ENABLE_FTS5%'\").fetchone()[0]
sys.exit(0 if n else 1)
" 2>/dev/null; then
        err "🚨 스토어 생성 실패 — 위 오류 참조 (FTS5 는 정상이다. 다른 원인을 볼 것)"
    else
        err "🚨 스토어 생성 실패 — FTS5 미탑재 확인됨: ${PY[*]} 의 sqlite3 빌드를 FTS5 포함본으로 교체할 것"
    fi
    exit 1
fi

# ── 3. policy.yml — 비파괴 병합 ──
# 여기서야 템플릿이 필요하다. 부재는 여전히 실패지만 **스토어는 이미 만들어진 뒤**라,
# 소비자는 "전부 실패" 가 아니라 "policy 만 남았다" 는 정확한 상태를 받는다.
if [[ ! -f "$POLICY_SRC" ]]; then
    err "🚨 정책 템플릿 부재: $POLICY_SRC"
    err "   스토어(registry.db · learn.db)는 생성됐다 — 남은 것은 policy.yml 뿐이다"
    err "   조치: 저장소를 최신으로 갱신하라(git pull). 그래도 없으면 배포 누락이다"
    exit 1
fi
if [[ ! -f "$POLICY_DST" ]]; then
    cp "$POLICY_SRC" "$POLICY_DST"
    info "policy.yml 생성: $POLICY_DST (템플릿 복사 — 값은 자유롭게 편집)"
else
    # 기존 파일의 키 집합을 뽑아, 템플릿에만 있는 키를 말미에 덧붙인다.
    # 기존 줄은 한 줄도 건드리지 않는다 — 운영자가 조정한 값을 되돌리면 안 된다.
    missing="$(AOA_POLICY_SRC="$POLICY_SRC" AOA_POLICY_DST="$POLICY_DST" "${PY[@]}" - <<'PYEOF'
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
printf '   확인: AOA_MEMORY_DIR=%s %s <plugin>/hooks/fbot-state.py list\n' "$AOA_DIR" "${PY[*]}"
