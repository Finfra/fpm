#!/usr/bin/env bash
# out-dir.sh — 렌더 산출물 폴더(OUT_DIR) 판정 단일 지점 (prj3#Issue802)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 모든 프로젝트 공유. cwd ≠ ~/.claude 면 즉시 수정 금지
#   → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT: ~/.claude/_doc_arch/hub-mode-arch.md
#
# 왜 분리했나 —
#   OUT_DIR 판정이 hub-context.sh(hub 렌더)와 ask-common.sh(`..ask` 폼 2종)에 각각 있었고,
#   Issue203/714 의 상향 탐색은 hub-context 쪽에만 들어가 **같은 cwd 에서 두 판정이 갈렸다** —
#   프로젝트 하위 폴더에서 hub 는 루트 `_doc_work/htm` 을, ask 는 `/tmp/___pm` 을 냈다(Issue802).
#   같은 판정이 두 곳에 있으면 반드시 갈라진다(Issue359·Issue424_2 와 같은 병) → 한 곳으로 접었다.
#
# ⚠️ source 전용 — `out_dir_resolve` 는 값을 호출자 전역 `OUT_DIR` 에 남긴다.
#   `$(...)` 커맨드 치환으로 부르면 서브셸이라 증발한다.
#   부수 효과: `_doc_work` 는 있는데 htm/·z_htm/ 둘 다 없으면 `htm/` 을 **만든다**(Issue289 신규 생성).

# Issue289: 렌더 산출물 쓰기 폴더 — 활성 `_doc_work/htm/`, legacy `_doc_work/z_htm/`.
#   프로젝트 단위 우선순위: 기존 htm/ → (없으면) 기존 z_htm/ 유지 → (둘 다 없으면) htm/ 신규 생성.
#   z_htm 만 있는 프로젝트를 강제로 htm/ 로 끌어올리지 않는 이유: P3 마이그레이션이
#   프로젝트별 전환 스위치 역할을 하고(htm/ 생성 = 그 프로젝트 전환 완료), 범위 밖 프로젝트
#   (prj2 볼트 등)를 하드코딩 없이 자동 제외할 수 있기 때문. 읽기는 서버가 HTM_DIRS 로 전부 커버.
#   설계 SSOT: ~/_git/___pm/_doc_arch/htm-lifecycle-design.md
_htm_dir_of() {  # $1=프로젝트 루트 → htm 출력 폴더 경로(없으면 빈 문자열)
  [ -d "$1/_doc_work/htm" ] && { printf '%s' "$1/_doc_work/htm"; return; }
  [ -d "$1/_doc_work/z_htm" ] && { printf '%s' "$1/_doc_work/z_htm"; return; }
  [ -d "$1/_doc_work" ] && { mkdir -p "$1/_doc_work/htm" && printf '%s' "$1/_doc_work/htm"; return; }
  printf ''
}

# OUT_DIR 결정: 프로젝트 로컬 우선 (Issue203 — 상향 탐색 추가)
#   입력: $1=cwd → 출력변수: OUT_DIR (항상 비어 있지 않다)
# 1) $cwd/_doc_work                  (cwd 직하 — 단일 레포)
# 2) git root / 부모 순회 _doc_work  (cwd 가 프로젝트 하위폴더일 때 루트 채택)
# 3) $cwd/*/_doc_work                (mono-repo / sub-package 하향 스캔 — ex: cli/_doc_work)
# 4) /tmp fallback
out_dir_resolve() {
local cwd="$1" up_root _git_top _near_doc dir _sub_any _sd sub_found
OUT_DIR=""
if [ -n "$cwd" ] && [ -d "$cwd/_doc_work" ]; then
  OUT_DIR=$(_htm_dir_of "$cwd")
elif [ -n "$cwd" ]; then
  # Issue203: cwd 가 프로젝트 하위폴더(ex: unity_base/Assets)면 루트 _doc_work 를 놓쳐
  #   /tmp fallback → 등록 스킵 → hub 403. 하향 find 이전에 상향 탐색으로 루트 채택.
  # Issue714: 매 프롬프트 지출이던 `git rev-parse`(11.6ms)·단계마다 `dirname`(2.8ms × 깊이)을
  #   걷었다 — 판정은 그대로 두고 **한 번의 bash 상향 순회**로 두 값을 함께 뽑는다.
  #     · git 루트 = 가장 가까운 `.git`(디렉토리 또는 파일 — worktree·submodule) 조상.
  #       git 과 같게 **물리 경로**로 돌려준다(`cd -P` — git 은 toplevel 을 realpath 로 준다.
  #       ~/_shared·iCloud 같은 심링크 경로에서 OUT_DIR 문자열이 바뀌지 않게 한다)
  #     · 부모 순회 = 가장 가까운 `_doc_work` 조상(논리 경로 — 종전 dirname 순회와 같다)
  #   git 이 루트를 못 주던 경우(.git 내부·dubious ownership)는 그 루트에 _doc_work 가 없거나
  #   부모 순회가 같은 답을 내므로 결과가 갈리지 않는다(Issue714 동등성 표 참조).
  up_root=""
  _git_top=""; _near_doc=""
  dir="$cwd"
  while [ -n "$dir" ] && [ "$dir" != "/" ]; do
    [ -z "$_near_doc" ] && [ -d "$dir/_doc_work" ] && _near_doc="$dir"
    if [ -z "$_git_top" ] && [ -e "$dir/.git" ]; then _git_top="$dir"; break; fi
    # 진행 없음(상대경로 `foo` → `${…%/*}` 가 그대로) 이면 끊는다 — 종전 dirname 도 `.` 에서 무한 루프였다
    [ "${dir%/*}" = "$dir" ] && break
    dir="${dir%/*}"
  done
  # git 루트에서 멈췄으면 그 위 _doc_work 는 부모 순회용으로 마저 찾는다(루트에 _doc_work 가 없을 때만 쓰인다)
  if [ -n "$_git_top" ] && [ ! -d "$_git_top/_doc_work" ] && [ -z "$_near_doc" ]; then
    dir="${_git_top%/*}"
    while [ -n "$dir" ] && [ "$dir" != "/" ]; do
      [ -d "$dir/_doc_work" ] && { _near_doc="$dir"; break; }
      [ "${dir%/*}" = "$dir" ] && break
      dir="${dir%/*}"
    done
  fi
  if [ -n "$_git_top" ] && [ -d "$_git_top/_doc_work" ]; then
    up_root=$(cd -P "$_git_top" 2>/dev/null && pwd -P)
    [ -n "$up_root" ] || up_root="$_git_top"
  else
    # git 미사용 대비 cwd 부모 순회 — 첫 발견 _doc_work 채택
    up_root="$_near_doc"
  fi
  if [ -n "$up_root" ]; then
    OUT_DIR=$(_htm_dir_of "$up_root")
  else
    # 하향 1단계 스캔 (mono-repo / sub-package)
    # Issue714: 대부분의 cwd 에는 후보가 **하나도 없다** — 그때 `find | head`(2 fork)를 띄우지 않는다.
    #   glob 으로 후보 존재만 먼저 본다. glob+`-d` 는 심링크를 따라가므로 find(-P) 매칭의 **상위집합**이다
    #   → glob 이 0건이면 find 도 0건. 1건이라도 있으면 종전 find 를 그대로 돌린다 — 후보가 여럿일 때
    #   find 는 readdir 순으로 첫 것을 고르는데 glob 은 이름순이라, 선택 자체를 옮기면 결과가 갈린다(실측).
    _sub_any=0
    for _sd in "$cwd"/*/_doc_work "$cwd"/.[!.]*/_doc_work "$cwd"/..?*/_doc_work; do
      [ -d "$_sd" ] && { _sub_any=1; break; }
    done
    if [ "$_sub_any" = 1 ]; then
      sub_found=$(find "$cwd" -mindepth 2 -maxdepth 2 -type d -name "_doc_work" 2>/dev/null | head -1)
      [ -n "$sub_found" ] && OUT_DIR=$(_htm_dir_of "${sub_found%/*}")
    fi
  fi
fi
if [ -z "$OUT_DIR" ]; then
  OUT_DIR="/tmp/___pm"
  [ -d "$OUT_DIR" ] || mkdir -p "$OUT_DIR"   # Issue714: 있으면 fork 하지 않는다
fi
}
