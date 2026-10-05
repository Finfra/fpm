#!/usr/bin/env bash
# fake-worker.sh — board L2 합성 worker (Issue544 M2-2). claude TUI 의 대역이다.
#
# supervisor 는 worker pane 을 두 가지로만 본다 — 이 스크립트는 그 둘만 흉내 낸다:
#   ① 화면: idle = 입력창 박스(╭ ❯ ╰) 만 있음 · busy = busy 마커(esc to interrupt) 있음
#      (fpm-board-supervisor.sh IDLE_BOX_RE·BUSY_RE — capture-pane 은 보이는 화면만 잡으므로
#       상태를 바꿀 때마다 화면을 지운다. 지우지 않으면 지난 busy 줄이 남아 영구 busy 가 된다)
#   ② 완료: send_prompt 가 알려 준 sentinel 파일 경로에 'DONE\t<rc>\t<result>' 기록
#
# 동작 지시는 큐 item 의 prompt 에 `FAKE:` 줄로 싣는다 (없으면 즉시 성공):
#   FAKE: sleep=<초> rc=<종료코드> mode=ok|hang|manual result=<요약>
#     hang   — busy 화면을 유지한 채 sentinel 을 쓰지 않는다 (stuck 판정용)
#     manual — idle 로 돌아가되 sentinel 을 쓰지 않는다 (테스트가 직접 sentinel 을 쓴다)
# 추적: FAKE_TRACE 파일에 '<epoch> start|end <id>' 를 남긴다 — 순서·동시성 단언의 근거
#
# ⚠️ 이 파일은 tdd 픽스처다. 실 worker 동작을 바꾸려면 supervisor 쪽이 아니라 여기를 고친다.

stty -echo 2>/dev/null   # 주입된 프롬프트가 화면에 되비치면 마커 판정이 오염된다
TRACE="${FAKE_TRACE:-/dev/null}"

now() { printf '%s' "${EPOCHREALTIME:-$(date +%s)}"; }
idle() { printf '\033[2J\033[H╭────────╮\n│ ❯      │\n╰────────╯\n'; }
busy() { printf '\033[2J\033[H✻ working %s… (esc to interrupt)\n' "$1"; }

idle
id=""; secs=0; rc=0; mode=ok; result=""; done_file=""
while IFS= read -r line; do
  case "$line" in
    *'[dashboard 큐 작업 — item '*)
      id="${line#*— item }"; id="${id%%]*}"; id="${id%% *}"
      secs=0; rc=0; mode=ok; result="ok-$id"; done_file=""
      busy "$id"
      ;;
    *'FAKE:'*)
      for kv in ${line#*FAKE:}; do
        case "$kv" in
          sleep=*)  secs="${kv#sleep=}" ;;
          rc=*)     rc="${kv#rc=}" ;;
          mode=*)   mode="${kv#mode=}" ;;
          result=*) result="${kv#result=}" ;;
        esac
      done
      ;;
    *"성공 시: printf 'DONE"*"> '"*)
      done_file="${line##*> \'}"; done_file="${done_file%\'}"
      ;;
    *'큐 supervisor 는 이 sentinel 파일'*)
      # 프롬프트 마지막 줄 — 여기서 작업을 «수행»한다
      [ -n "$id" ] || continue
      printf '%s start %s\n' "$(now)" "$id" >> "$TRACE"
      [ "$secs" != 0 ] && sleep "$secs"
      case "$mode" in
        hang)   continue ;;                       # busy 화면 유지, sentinel 없음
        manual) printf '%s end %s\n' "$(now)" "$id" >> "$TRACE"; idle; continue ;;
      esac
      printf '%s end %s\n' "$(now)" "$id" >> "$TRACE"
      [ -n "$done_file" ] && printf 'DONE\t%s\t%s\n' "$rc" "$result" > "$done_file"
      idle
      ;;
  esac
done
