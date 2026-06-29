#!/usr/bin/env bash
# install_manifest.sh — fpm 설치 아티팩트 (sourceable)
#
# ⚠️ AUTO-GENERATED — 직접 편집 금지.
#   SSOT: data/scar-manifest.yml  →  생성기: sh/gen-install-manifest.sh
#   값을 바꾸려면 yml 을 고친 뒤 `bash sh/gen-install-manifest.sh` 재실행.
#
# install.sh(생성)·check.sh(검증)·uninstall.sh·update.sh·publish-scar.sh 가 공통 source.
# 순수 bash sourceable(yq/pyyaml 무의존) — installer 무의존 유지.

# ── [셸] rc 블록 마커 ──
FPM_MARKER="# >>> fpm functions >>>"
FPM_MARKER_END="# <<< fpm functions <<<"

# ── [셸] FPM_BASE 베이스경로 기록 파일 ($HOME 기준) ──
FPM_BASEPATH_REL_HOME=".info/__pmBasePath.txt"

# ── [셸] 부트스트랩 source 대상 (repo 기준) ──
FPM_BOOTSTRAP_REL_REPO="sh/fpm.sh"

# ── [셸] projects/ 스캐폴드 — 필수 존재 인덱스 ──
FPM_SCAFFOLD_INDEXES=(0 1)

# ── [셸] 운영 필수 파일 (real:org, repo 기준) ──
FPM_ORG_FILES=(
    "Servers.md:Servers_org.md"
    "Projects.md:Projects_org.md"
    "data/hub_setting.yml:data/hub_setting_org.yml"
)

# ── [SCAR] fpm-core 플러그인 (공유 마켓 경유) ──
FPM_MKT_NAME="f-claude-plugins"
FPM_MKT_REF_DEFAULT="https://github.com/Finfra/f-claude-plugins"  # env FPM_MKT_REF 로 override
FPM_PLUGIN_NAME="fpm-core"

# ── [SCAR] 플러그인 소스 디렉토리 (repo 기준) ──
FPM_PLUGIN_SRC_REL_REPO="plugins/fpm-core"

# ── [SCAR] fpm-core 번들 SCAR 인벤토리 (선언적 drift 가드) ──
#   파일 규약: commands/<name>.md · skills/<name>/SKILL.md · agents/<name>.md
FPM_SCAR_COMMANDS=(
    fpm-cdf
    fpm-board
    fpm-board-server
    fpm-hub
    fpm-hub-server
    fpm-new-project
    fpm-pm-del
    fpm-pm-do
    fpm-pm-new
    fpm-pm-query
    fpm-pm-update
    fpm-show
)
FPM_SCAR_SKILLS=(
    fpm-cdf
    fpm-pm
    fpm-pm-do
)
FPM_SCAR_AGENTS=(
    fpm-board
)
