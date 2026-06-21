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
  *)                  app="$app_raw" ;;
esac

# match 미지정 시 origin(scheme://host:port) 추출 → hub 의 모든 path(/hub·?path=…) 단일 탭 재사용
if [[ -z "$match" ]]; then
  match=$(printf '%s' "$url" | sed -E 's#^([a-z]+://[^/]+).*#\1#')
fi

# Issue: 진짜 백그라운드 열기 (깜빡임 0). Chromium(Chrome/Edge)은 open -g 를 무시하고
#   self-activate 하므로(→ Issue173 trap 복원 = "전면화 후 복구" 깜빡임), open 대신
#   AppleScript make new tab(activate 미호출)로 탭만 생성 → 전면화 자체를 회피.
#   미실행 시엔 launch 가 activate 를 동반하므로 open -g 폴백(어차피 한 번은 떠야 함).
#   창 0개면 make new tab 대상 부재 → open -g 로 새 창(이 경우만 1회 전면화 감수).
_bg_open() {
  case "$app" in
    "Google Chrome"|"Microsoft Edge")
      if ! pgrep -xq "$app" || [[ "$(osascript -e "tell application \"$app\" to count windows" 2>/dev/null || echo 0)" == "0" ]]; then
        open -g -a "$app" "$url"
        return
      fi
      osascript - "$url" "$app" <<'OSA' >/dev/null 2>&1 || open -g -a "$app" "$url"
on run argv
  set theURL to item 1 of argv
  set appName to item 2 of argv
  -- 동적 앱명(Chrome/Edge)은 Chrome 사전으로 컴파일 후 런타임 전달 (Chromium 공통 사전)
  using terms from application "Google Chrome"
    tell application appName
      tell front window to make new tab with properties {URL:theURL}
      -- activate 미호출 → 전면화 안 됨 → 포커스 미탈취 (Firefox 의 open -g 동등)
    end tell
  end using terms from
end run
OSA
      ;;
    *)
      open -g -a "$app" "$url"  # Firefox 등은 open -g 존중
      ;;
  esac
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
    # Chromium 계열 — KM 매크로와 동일 로직 + URL 덮어쓰기(htm-doc 단일 탭 재사용)
    # Issue150: doFocus=false 면 윈도우 raise/탭 전환 skip (URL 만 덮어씀 → 포커스 미탈취).
    #           탭 미발견(notfound)은 osascript 가 반환 → shell 이 _fallback_open(-g) 처리.
    osa_result=$(osascript - "$url" "$match" "$focus" "$app" <<'OSA'
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
            -- Issue150: 전면화(탭 활성·윈도우 raise)는 focus 요청 시에만
            if doFocus then
              set active tab index of w to i
              set index of w to 1
            end if
            set found to true
            exit repeat
          end if
        end repeat
        if found then exit repeat
      end repeat
      if not found then return "notfound"
      if doFocus then activate
    end tell
  end using terms from
  return "reused"
end run
OSA
)
    # 탭 미발견 → focus 정책 존중하는 폴백 열기 (doFocus=false 면 open -g 백그라운드)
    if [[ "$osa_result" == "notfound" ]]; then
      _fallback_open
    fi
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
