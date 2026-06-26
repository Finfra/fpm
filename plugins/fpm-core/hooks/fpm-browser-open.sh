#!/usr/bin/env bash
# fpm-browser-open.sh — hub 렌더 브라우저 열기 + 탭 재사용 (Issue162)
#
# Keyboard Maestro 매크로 "fPm hub page Open" 의 AppleScript 탭-재사용 로직을
# CLI/hook 공용 helper 로 포팅. iTerm 등 터미널(fhub) + 3개 hook 자동 렌더가 공유.
#
#   Chrome/Edge(Chromium)·Safari = 기존 탭 탐색 → 있으면 URL 덮어쓰기+활성화, 없으면 새 탭
#   Firefox / reuse=false        = open 폴백 (Firefox 는 tab 제어 사전 부재 → 누적 감수)
#
# Usage: fpm-browser-open.sh [-a app] [-f focus] [-r reuse] [-m match] <url>
#   -a app    chrome|safari|edge|firefox | 앱명 | .app 경로   (기본: chrome)
#   -f focus  true=포커스 가져옴 | false=백그라운드            (기본: true)
#   -r reuse  true=탭 재사용 | false=항상 새 탭               (기본: true)
#   -m match  탭 매칭 URL prefix                              (기본: url 의 scheme://host:port)
#   <url>     열 URL (마지막 위치인자, 필수)
#
# url 을 마지막 위치인자로 둔 이유: hook instruction `{open_cmd} "url"` 패턴(url 후행)과
# 직접 호환 — HTM_OPEN_CMD="bash helper -a chrome -f false -r true" 뒤에 Claude 가 url 을 붙임.
#
# 순수 helper — hub_setting.yml 을 읽지 않음. default_browser/browser_open/browser_tab_reuse
# 해석은 호출자(hook 또는 fhub 함수) 책임. 그래야 인자만으로 단독 테스트 가능.
set -euo pipefail

app_raw="chrome"
focus="true"
reuse="true"
match=""

while getopts "a:f:r:m:" opt; do
  case "$opt" in
    a) app_raw="$OPTARG" ;;
    f) focus="$OPTARG" ;;
    r) reuse="$OPTARG" ;;
    m) match="$OPTARG" ;;
    *) echo "usage: $0 [-a app] [-f focus] [-r reuse] [-m match] <url>" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
url="${1:?url required (last positional arg)}"

# Issue173: focus 복원 가드 — Chrome/Chromium 은 open -g·AppleScript URL set 시 focus=false 여도
#   self-activate 함 (Firefox 는 open -g 존중). focus != true 면 open 직전 frontmost GUI 앱을 기억했다가
#   스크립트 종료 시(trap EXIT) 재활성 → 어느 경로(fallback open / osascript reuse / notfound)든 포커스 미탈취.
#   firefox 등 이미 백그라운드 유지하는 앱엔 무해(no-op). System Events 권한 부재·프로세스 부재 시 || true 로 무해 통과.
# Issue188: 캡처(name of first process)·복원 모두 System Events 프로세스 도메인으로 통일.
#   기존 `tell application "<name>" to activate` 는 앱명 기반이라 프로세스명↔앱명 불일치(ex: VSCode 프로세스 "Code")
#   시 복원 실패 → Chrome 포커스 잔류. process "<name>" set frontmost 는 캡처와 동일 도메인이라 mismatch 없음.
_prev_front=""
if [[ "$focus" != "true" ]]; then
  _prev_front=$(osascript -e 'tell application "System Events" to name of first process whose frontmost is true' 2>/dev/null || true)
fi
_restore_focus() {
  [[ -n "$_prev_front" ]] || return 0
  osascript -e "tell application \"System Events\" to tell process \"$_prev_front\" to set frontmost to true" 2>/dev/null || true
}
trap _restore_focus EXIT

# app 별칭 정규화 (3 hook 의 default_browser case 와 동일 매핑)
case "$app_raw" in
  ""|firefox|Firefox) app="Firefox" ;;
  chrome|Chrome)      app="Google Chrome" ;;
  edge|Edge)          app="Microsoft Edge" ;;
  safari|Safari)      app="Safari" ;;
  none|None|NONE|off) exit 0 ;;   # 브라우저 미존재 환경(서버) — open 생략, 무해 종료
  *)                  app="$app_raw" ;;
esac

# match 미지정 시 origin(scheme://host:port) 추출 → hub 의 모든 path(/hub·?path=…) 단일 탭 재사용
if [[ -z "$match" ]]; then
  match=$(printf '%s' "$url" | sed -E 's#^([a-z]+://[^/]+).*#\1#')
fi

# Issue166: Chrome/Edge AppleScript 구동 전면 제거 — macOS 26.6 + Chrome 149 에서
#   scripting bridge(make new tab / 탭순회 reuse)로 보낸 AppleEvent 를 Chrome main thread 가
#   서비스하다 EXC_BREAKPOINT(AX MIG CHECK 실패)로 크래시함(반복 재현). 모든 앱을 순수
#   `open -g`(LaunchServices, AppleEvent 미발생)로 통일. self-activate 깜빡임은 trap 포커스
#   복원으로 흡수. OS 탭 관리는 render_tab_mode:hub-internal(hub 쉘 iframe 탭)이 담당하므로
#   make new tab / 탭 재사용은 레거시 — 제거해도 기능 손실 없음.
_bg_open() {
  open -g -a "$app" "$url"   # 전 브라우저 공통 — AppleScript 미사용
}

# Firefox / reuse=false → open 폴백 (focus 에 따라 분기)
_fallback_open() {
  if [[ "$focus" == "true" ]]; then
    open -a "$app" "$url"
  else
    _bg_open
  fi
}

if [[ "$reuse" != "true" ]]; then
  _fallback_open
  exit 0
fi

case "$app" in
  "Google Chrome"|"Microsoft Edge")
    # Issue166: Chromium 탭 재사용 AppleScript(windows×tabs 순회 `URL of t`) 제거 —
    #   AppleEvent 폭탄이 Chrome 149/macOS 26.6 을 크래시시킴. 순수 open 폴백으로 강등.
    #   단일 탭 보장은 render_tab_mode:hub-internal(hub 쉘 단일창) + hub_single_window 가 담당.
    _fallback_open
    ;;
  "Safari")
    # Safari — Apple Events 자동화 허용(개발자 메뉴) 사전 설정 필요할 수 있음
    # Issue150: doFocus=false 면 current tab 전환 skip, notfound 는 shell 폴백
    osa_result=$(osascript - "$url" "$match" "$focus" <<'OSA'
on run argv
  set theURL to item 1 of argv
  set theMatch to item 2 of argv
  set doFocus to (item 3 of argv is "true")
  tell application "Safari"
    set found to false
    repeat with w in windows
      set i to 0
      repeat with t in tabs of w
        set i to i + 1
        if (URL of t) starts with theMatch then
          set URL of t to theURL
          -- Issue150: 현재 탭 전환은 focus 요청 시에만
          if doFocus then set current tab of w to t
          set found to true
          exit repeat
        end if
      end repeat
      if found then exit repeat
    end repeat
    if not found then return "notfound"
    if doFocus then activate
  end tell
  return "reused"
end run
OSA
)
    if [[ "$osa_result" == "notfound" ]]; then
      _fallback_open
    fi
    ;;
  *)
    # Firefox 등 tab 미제어 브라우저 — 폴백
    _fallback_open
    ;;
esac
