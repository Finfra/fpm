#!/bin/bash
# fpm-bundle-sync.sh — plugins/fpm-core 번들을 라이브 SCAR·서버 코드와 동기 (Issue291)
#
# 배경: 번들이 라이브 대비 ~100개 이슈 정체된 채 VERSION 은 최신을 주장하는 상태가 발생했다
#   (2026-07-19 실측: 번들 server.py 6,838줄 vs 라이브 10,537줄, 마지막 반영 Issue193).
#   버전이 내용을 보증하지 못하면 플러그인 사용자는 수개월치 수정이 빠진 hub 를 받는다.
#
# 원칙:
#   1. 라이브가 원본, 번들은 배포 스냅샷. 단방향(라이브 → 번들)만 수행한다.
#   2. **번들 전용 파일은 절대 삭제하지 않는다** (hooks.json·fpm-browser-open.sh·fpm-cdf.md·
#      fpm-hub-server.md·vscode-ext/ 등 배포 전용 자산). rsync --delete 금지.
#   3. 개인 환경 파일은 반입하지 않는다 (data/hub_setting.yml 등). 공개 안전장치는
#      forward 스냅샷 단계(fpm-guard/fpm-sanitize)가 담당하나, 여기서도 최소 반입 원칙을 지킨다.
#   4. server.py 만 옮기고 의존(i18n.py·assets/)을 빠뜨리면 플러그인이 import 에서 죽는다 →
#      services/hub 는 파일 단위가 아니라 디렉토리 전체를 동기한다.
#
# 사용:
#   scripts/fpm-bundle-sync.sh          # 동기 실행
#   scripts/fpm-bundle-sync.sh --check  # 표류 검사만 (변경 없음, 표류 시 exit 1)
#
# 설계 SSOT: _doc_arch/htm-lifecycle-design.md 는 htm 수명주기, 본 스크립트는 Issue291.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="$REPO/plugins/fpm-core"
GLOBAL="$HOME/.claude"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

cd "$REPO" || exit 1
drift=0
changed=0

say() { printf '[bundle-sync] %s\n' "$*"; }

# 파일 1건 동기 (번들에 이미 있는 것만 — 신규 파일은 의도적 편입이므로 수동)
sync_file() {  # $1=번들경로 $2=라이브경로
  local dst="$1" src="$2"
  [ -f "$src" ] || return 0          # 라이브에 없음 = 번들 전용 → 보존
  cmp -s "$dst" "$src" && return 0   # 동일
  drift=$((drift + 1))
  if [ "$CHECK" -eq 1 ]; then
    say "DRIFT ${dst#$REPO/}"
  else
    cp "$src" "$dst" && changed=$((changed + 1))
  fi
}

sync_dir_by_name() {  # $1=번들 디렉토리 $2=라이브 디렉토리
  local bdir="$1" ldir="$2" f
  [ -d "$bdir" ] || return 0
  for f in "$bdir"/*; do
    [ -f "$f" ] || continue
    sync_file "$f" "$ldir/$(basename "$f")"
  done
}

# --- 1. services/hub — 디렉토리 전체 (의존 파일 누락 방지) ---
RSYNC_EX=(--exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='.vscode/' --exclude='.DS_Store')
if [ "$CHECK" -eq 1 ]; then
  n=$(rsync -an --itemize-changes "${RSYNC_EX[@]}" "$REPO/services/hub/" "$BUNDLE/services/hub/" | grep -c '^[>c]')
  [ "$n" -gt 0 ] && { drift=$((drift + n)); say "DRIFT services/hub ($n 파일)"; }
else
  n=$(rsync -a --itemize-changes "${RSYNC_EX[@]}" "$REPO/services/hub/" "$BUNDLE/services/hub/" | grep -c '^[>c]')
  [ "$n" -gt 0 ] && { changed=$((changed + n)); say "services/hub $n 파일 갱신"; }
fi

# --- 2. hooks / commands / agents — 이름 일치분만 ---
sync_dir_by_name "$BUNDLE/hooks"    "$GLOBAL/hooks"
sync_dir_by_name "$BUNDLE/commands" "$GLOBAL/commands"
sync_dir_by_name "$BUNDLE/agents"   "$GLOBAL/agents"

# --- 3. skills — 번들 이름과 라이브 이름이 다른 케이스가 있어 명시 매핑 ---
#   fpm-cdf ← prj1 .claude/skills/cdf, fpm-pm ← prj1 .claude/skills/pm,
#   fpm-pm-do ← 글로벌 ~/.claude/skills/fpm-pm-do
sync_skill() {  # $1=번들 스킬명 $2=라이브 디렉토리
  local dst="$BUNDLE/skills/$1" src="$2"
  [ -d "$dst" ] && [ -d "$src" ] || return 0
  local flag=""; [ "$CHECK" -eq 1 ] && flag="-n"
  local n
  n=$(rsync -a $flag --itemize-changes --exclude='__pycache__/' --exclude='.DS_Store' "$src/" "$dst/" | grep -c '^[>c]')
  [ "$n" -gt 0 ] || return 0
  if [ "$CHECK" -eq 1 ]; then drift=$((drift + n)); say "DRIFT skills/$1 ($n)"
  else changed=$((changed + n)); say "skills/$1 $n 파일 갱신"; fi
}
sync_skill fpm-pm-do "$GLOBAL/skills/fpm-pm-do"
sync_skill fpm-pm    "$REPO/.claude/skills/pm"
sync_skill fpm-cdf   "$REPO/.claude/skills/cdf"

# --- 4. 런타임 데이터 (i18n catalog + 설치 템플릿) ---
#   locales 부재 시 hub UI 가 번역 키 그대로 노출되고 test_i18n_parity 가 깨진다.
#   hub_setting.yml(개인 환경값)은 반입 금지 — org 템플릿만.
if [ "$CHECK" -eq 1 ]; then
  n=$(rsync -an --itemize-changes "$REPO/data/locales/" "$BUNDLE/data/locales/" 2>/dev/null | grep -c '^[>c]')
  [ "$n" -gt 0 ] && { drift=$((drift + n)); say "DRIFT data/locales ($n)"; }
else
  mkdir -p "$BUNDLE/data/locales"
  n=$(rsync -a --itemize-changes "$REPO/data/locales/" "$BUNDLE/data/locales/" | grep -c '^[>c]')
  [ "$n" -gt 0 ] && { changed=$((changed + n)); say "data/locales $n 파일 갱신"; }
fi
sync_file "$BUNDLE/data/hub_setting_org.yml" "$REPO/data/hub_setting_org.yml"

# --- 5. 실행 권한 (cp 는 mode 를 보존하지 않음) ---
if [ "$CHECK" -eq 0 ]; then
  for f in "$BUNDLE"/hooks/*.sh "$BUNDLE"/agents/*.sh; do
    [ -f "$f" ] && [ ! -x "$f" ] && chmod +x "$f"
  done
fi

# --- 결과 ---
if [ "$CHECK" -eq 1 ]; then
  if [ "$drift" -gt 0 ]; then
    say "표류 $drift 건 — 'scripts/fpm-bundle-sync.sh' 실행 필요"
    exit 1
  fi
  say "표류 없음 (번들 = 라이브)"
  exit 0
fi

if [ "$changed" -gt 0 ]; then
  say "총 $changed 파일 동기 완료 — 커밋 전 테스트 권장:"
  say "  (cd plugins/fpm-core/services/hub && for t in test_*.py; do python3 \$t >/dev/null || echo FAIL \$t; done)"
else
  say "변경 없음 (이미 최신)"
fi
exit 0
