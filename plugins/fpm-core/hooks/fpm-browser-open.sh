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
# 순수 helper — hub_setting.yml 을 읽지 않음. default_browser/browser_focus/browser_tab_reuse
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

# app 별칭 정규화 (3 hook 의 default_browser case 와 동일 매핑)
case "$app_raw" in
  ""|firefox|Firefox) app="Firefox" ;;
  chrome|Chrome)      app="Google Chrome" ;;
  edge|Edge)          app="Microsoft Edge" ;;
  safari|Safari)      app="Safari" ;;
  *)                  app="$app_raw" ;;
esac

# match 미지정 시 origin(scheme://host:port) 추출 → hub 의 모든 path(/hub·?path=…) 단일 탭 재사용
if [[ -z "$match" ]]; then
  match=$(printf '%s' "$url" | sed -E 's#^([a-z]+://[^/]+).*#\1#')
fi

# Firefox / reuse=false → open 폴백 (focus 에 따라 -g)
_fallback_open() {
  if [[ "$focus" == "true" ]]; then
    open -a "$app" "$url"
  else
    open -g -a "$app" "$url"
  fi
}

if [[ "$reuse" != "true" ]]; then
  _fallback_open
  exit 0
fi

case "$app" in
  "Google Chrome"|"Microsoft Edge")
    # Chromium 계열 — KM 매크로와 동일 로직 + URL 덮어쓰기(htm-doc 단일 탭 재사용)
    osascript - "$url" "$match" "$focus" "$app" <<'OSA'
on run argv
  set theURL to item 1 of argv
  set theMatch to item 2 of argv
  set doFocus to (item 3 of argv is "true")
  set appName to item 4 of argv
  -- 동적 앱명(Chrome/Edge)은 Chrome 사전으로 컴파일 후 런타임 전달 (Chromium 공통 사전)
  using terms from application "Google Chrome"
    tell application appName
      set found to false
      repeat with w in windows
        set i to 0
        repeat with t in tabs of w
          set i to i + 1
          if (URL of t) starts with theMatch then
            set URL of t to theURL
            set active tab index of w to i
            set index of w to 1
            set found to true
            exit repeat
          end if
        end repeat
        if found then exit repeat
      end repeat
      if not found then open location theURL
      if doFocus then activate
    end tell
  end using terms from
end run
OSA
    ;;
  "Safari")
    # Safari — Apple Events 자동화 허용(개발자 메뉴) 사전 설정 필요할 수 있음
    osascript - "$url" "$match" "$focus" <<'OSA'
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
          set current tab of w to t
          set found to true
          exit repeat
        end if
      end repeat
      if found then exit repeat
    end repeat
    if not found then open location theURL
    if doFocus then activate
  end tell
end run
OSA
    ;;
  *)
    # Firefox 등 tab 미제어 브라우저 — 폴백
    _fallback_open
    ;;
esac
