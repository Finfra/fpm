#!/usr/bin/env bash
# gen-install-manifest.sh — data/scar-manifest.yml → data/install_manifest.sh 생성기 (Issue240)
#
# scar-manifest.yml(SSOT) 의 shell + payloads(plugin·flat_file) 값을 bash sourceable 한
# install_manifest.sh 로 투영한다. installer(install/check/uninstall/update/publish)는
# yq·pyyaml 무의존이어야 하므로, 빌드 타임에 본 생성기가 한 번 돌려 .sh 를 만들어 커밋한다.
#
# 사용: bash sh/gen-install-manifest.sh            생성(덮어쓰기) + 결과 안내
#       bash sh/gen-install-manifest.sh --check    drift 검사(쓰기 X):
#                                                    ① yml → 생성결과 vs 현 install_manifest.sh
#                                                    ② yml flat_file.files[] vs 디스크 실제 파일
# exit: 0=성공/일치, 1=실패, 2=--check 불일치(drift)
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
YML="$REPO_DIR/data/scar-manifest.yml"
OUT="$REPO_DIR/data/install_manifest.sh"

info() { printf '\033[36m[gen-manifest]\033[0m %s\n' "$1"; }
err()  { printf '\033[31m[gen-manifest]\033[0m %s\n' "$1" >&2; }

[[ -f "$YML" ]] || { err "🚨 SSOT 없음: $YML"; exit 1; }
command -v python3 >/dev/null 2>&1 || { err "🚨 python3 필요(생성기는 dev 머신에서만 실행)"; exit 1; }
python3 -c 'import yaml' 2>/dev/null || { err "🚨 pyyaml 필요: pip3 install pyyaml"; exit 1; }

MODE="write"
[[ "${1:-}" == "--check" ]] && MODE="check"

# ── ① yml → install_manifest.sh 투영 텍스트 ─────────────────────────────────
GENERATED="$(python3 - "$YML" <<'PY'
import sys, yaml
y = yaml.safe_load(open(sys.argv[1]))
sh = y["shell"]
pl = y["payloads"]["plugin"]
ff = y["payloads"]["flat_file"]
mkt = pl["marketplace"]

def arr(name, items):
    lines = [f"{name}=("]
    for it in items:
        lines.append(f"    {it}")
    lines.append(")")
    return "\n".join(lines)

org = [f'    "{o["real"]}:{o["org"]}"' for o in sh["org_files"]]
scaffold = " ".join(str(i) for i in sh["scaffold_indexes"])

print(f'''#!/usr/bin/env bash
# install_manifest.sh — fpm 설치 아티팩트 (sourceable)
#
# ⚠️ AUTO-GENERATED — 직접 편집 금지.
#   SSOT: data/scar-manifest.yml  →  생성기: sh/gen-install-manifest.sh
#   값을 바꾸려면 yml 을 고친 뒤 `bash sh/gen-install-manifest.sh` 재실행.
#
# install.sh(생성)·check.sh(검증)·uninstall.sh·update.sh·publish-scar.sh 가 공통 source.
# 순수 bash sourceable(yq/pyyaml 무의존) — installer 무의존 유지.

# ── [셸] rc 블록 마커 ──
FPM_MARKER="{sh["rc_marker"]}"
FPM_MARKER_END="{sh["rc_marker_end"]}"

# ── [셸] FPM_BASE 베이스경로 기록 파일 ($HOME 기준) ──
FPM_BASEPATH_REL_HOME="{sh["basepath_rel_home"]}"

# ── [셸] 부트스트랩 source 대상 (repo 기준) ──
FPM_BOOTSTRAP_REL_REPO="{sh["bootstrap_rel_repo"]}"

# ── [셸] projects/ 스캐폴드 — 필수 존재 인덱스 ──
FPM_SCAFFOLD_INDEXES=({scaffold})

# ── [셸] 운영 필수 파일 (real:org, repo 기준) ──
FPM_ORG_FILES=(
{chr(10).join(org)}
)

# ── [SCAR] fpm-core 플러그인 (공유 마켓 경유) ──
FPM_MKT_NAME="{mkt["name"]}"
FPM_MKT_REF_DEFAULT="{mkt["ref_default"]}"  # env FPM_MKT_REF 로 override
FPM_PLUGIN_NAME="{pl["plugin_name"]}"

# ── [SCAR] 플러그인 소스 디렉토리 (repo 기준) ──
FPM_PLUGIN_SRC_REL_REPO="{pl["src_rel_repo"]}"

# ── [SCAR] fpm-core 번들 SCAR 인벤토리 (선언적 drift 가드) ──
#   파일 규약: commands/<name>.md · skills/<name>/SKILL.md · agents/<name>.md
{arr("FPM_SCAR_COMMANDS", pl["scar"]["commands"])}
{arr("FPM_SCAR_SKILLS", pl["scar"]["skills"])}
{arr("FPM_SCAR_AGENTS", pl["scar"]["agents"])}

# ── [flat_file] 원격 ~/.claude 플랫파일 페이로드 (repo 기준 소스 + 인벤토리) ──
#   check.sh 가 FPM_FLATFILE_FILES ↔ <src>/ 실제 파일을 양방향 대조(drift 검출).
FPM_FLATFILE_SRC_REL_REPO="{ff["src_rel_repo"]}"
{arr("FPM_FLATFILE_FILES", ff["files"])}''')
PY
)" || { err "🚨 생성 실패(yml 파싱 오류?)"; exit 1; }

# ── ② yml flat_file.files[] vs 디스크 실제 파일 drift (yml 직독) ──────────────
flat_disk_drift() {
    python3 - "$YML" "$REPO_DIR" <<'PY'
import sys, yaml, os
y = yaml.safe_load(open(sys.argv[1])); repo = sys.argv[2]
ff = y["payloads"]["flat_file"]
src = os.path.join(repo, ff["src_rel_repo"])
declared = set(ff.get("files") or [])
actual = set()
for root, _, files in os.walk(src):
    for f in files:
        actual.add(os.path.relpath(os.path.join(root, f), src))
missing = sorted(declared - actual)   # yml 에 있으나 디스크 없음
undecl  = sorted(actual - declared)   # 디스크에 있으나 yml 미선언
if missing or undecl:
    if missing: print("MISSING(yml 선언·디스크 없음): " + ", ".join(missing))
    if undecl:  print("UNDECLARED(디스크 존재·yml 미선언): " + ", ".join(undecl))
    sys.exit(2)
sys.exit(0)
PY
}

if [[ "$MODE" == "check" ]]; then
    rc=0
    # ① 투영 동기 검사
    if [[ -f "$OUT" ]] && diff -q <(printf '%s\n' "$GENERATED") "$OUT" >/dev/null 2>&1; then
        info "✅ install_manifest.sh 는 yml 과 일치 (투영 drift 없음)"
    else
        err "⚠️ 투영 drift — install_manifest.sh 가 yml 과 불일치. 'bash sh/gen-install-manifest.sh' 재생성 필요"
        diff <(printf '%s\n' "$GENERATED") "$OUT" 2>/dev/null | head -40
        rc=2
    fi
    # ② flat_file 디스크 drift 검사
    if drift_out="$(flat_disk_drift)"; then
        info "✅ flat_file.files[] 는 디스크와 일치 (drift 없음)"
    else
        err "⚠️ flat_file drift — yml files[] 와 $(basename "$YML") payloads.flat_file.src 디스크 불일치:"
        printf '%s\n' "$drift_out" | sed 's/^/    /'
        rc=2
    fi
    exit $rc
fi

printf '%s\n' "$GENERATED" > "$OUT"
info "✅ 생성 완료: data/install_manifest.sh (SSOT: data/scar-manifest.yml)"
