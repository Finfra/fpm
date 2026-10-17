#!/usr/bin/env bash
# test-aoa-mq-subject.sh — 항목이 «무엇에 관한 것인지»(subject_prj) 기록 회귀 (prj3#Issue1060_1)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md
#
# 무엇을 지키나 — 총괄 봇이 올린 [컨펌] 은 target=봇 거처(prj3, Issue925 — «누가 처리하나»)·source=`봇@.claude` 라
#   hub /mq «프로젝트» 열이 `.claude` 로만 보였다(2026-10-10 실발생: prj60#Issue51·prj7#Issue63_1 두 건).
#   본문 머리의 `prjN IssueM`·`prjN#IssueM`·`prjN` 을 subject_prj 로 따로 남긴다 — target 은 건드리지 않는다.
# 실행: bash ~/.claude/mcp/aoa-mq/test-aoa-mq-subject.sh   (exit 0 = 전부 PASS)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ENQ="$HERE/aoa-mq-enqueue.sh"
JQ=$(command -v jq || echo /usr/bin/jq)
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/mq/queue" "$TMP/mq/queue_done" "$TMP/home/.claude" "$TMP/prj/p3" "$TMP/prj/p60" "$TMP/prj/p7" "$TMP/prj/p9t"
mkdir -p "$TMP/projects"
echo "$TMP/home/.claude" >"$TMP/projects/3"
echo "$TMP/prj/p60" >"$TMP/projects/60"
echo "$TMP/prj/p7" >"$TMP/projects/7"
echo "$TMP/prj/p9t" >"$TMP/projects/9t"
export AOA_MQ_DIR="$TMP/mq" AOA_MQ_PROJECTS_DIR="$TMP/projects"
cd "$TMP/home/.claude" || exit 1
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1"; }

enq() { "$ENQ" --json --due +0d "$@" >"$TMP/out" 2>"$TMP/err"; }
field() { local p; p=$("$JQ" -r .path "$TMP/out" 2>/dev/null); "$JQ" -r "$1" "$p" 2>/dev/null; }

# 픽스처의 «prjN IssueM» 공백 표기는 tagcheck(prj1#Issue325)가 이 repo 이슈 참조로 읽는다 — 변수로 조립한다
I=Issue
echo "== subject_prj (Issue1060_1) =="
enq --message "[컨펌] [H:비용] prj60 ${I}51 P5-1 — Gamma 크레딧 충전 여부" --source "fbot-chief-narae@.claude" \
    --from-bot fbot-chief-narae --target prj3
[ "$(field '.subject_prj // ""')" = prj60 ] && ok "🔑 [컨펌] 머리 «prj60 ${I}51» → subject_prj=prj60" \
  || bad "🔑 [컨펌] 머리 → subject_prj — '$(field '.subject_prj // ""')' $(head -c 200 "$TMP/err")"
[ "$(field '.target // ""')" = prj3 ] && ok "🔑 target 은 그대로 prj3(처리자 — Issue925 불변)" || bad "target 불변 — '$(field .target)'"

enq --message "prj7 ${I}63_1 강의 시나리오 사례 채택"
[ "$(field '.subject_prj // ""')" = prj7 ] && ok "일반 항목 머리 «prj7 ${I}63_1» → prj7" || bad "일반 머리 — '$(field '.subject_prj // ""')'"

enq --message "prj60#Issue52 kit 선언"
[ "$(field '.subject_prj // ""')" = prj60 ] && ok "«prj60#Issue52» 표기 → prj60" || bad "# 표기 — '$(field '.subject_prj // ""')'"

enq --message "prj9t fTyping 상세 설계 6건"
[ "$(field '.subject_prj // ""')" = prj9t ] && ok "이슈 없는 머리 «prj9t» → prj9t(접미 문자 허용)" || bad "prj9t — '$(field '.subject_prj // ""')'"

enq --message "fSnippet(prj15) App Store 심사 확인"
[ "$(field 'has("subject_prj")')" = false ] && ok "본문 중간 prjN 은 subject 아님(필드 미기록)" || bad "중간 언급 — $(field '.subject_prj')"

enq --message "prj999 ${I}1 번호 매핑 없음"; rc=$?
[ "$rc" = 0 ] && [ "$(field 'has("subject_prj")')" = false ] && ok "🔑 매핑 없는 prj 는 미기록 + 등록은 성공" \
  || bad "매핑 없음 — rc=$rc subj=$(field '.subject_prj') $(head -c 200 "$TMP/err")"

enq --message "prj60x 오타 머리"
[ "$(field 'has("subject_prj")')" = false ] && ok "매핑 없는 접미(prj60x) 미기록" || bad "prj60x — $(field '.subject_prj')"

enq --message "prj3 명시 키 항목" --key "explicit-key-1"
[ "$(field '.subject_prj // ""')" = prj3 ] && ok "명시 --key 여도 subject 는 기록(중복 키와 독립)" || bad "명시 키 — '$(field '.subject_prj // ""')'"

echo "-- 명시 --subject (prj3#Issue1092 ④) — 머리에 prjN 이 없는 총괄 상신도 주제를 잃지 않는다"
# 회귀 입력 = 20261010-212211-001 의 머리: «[컨펌] [H:스토어] 47회차 보고 …» (주제 prj9t 인데 머리에 토큰이 없다)
HEAD_MSG="[컨펌] [H:스토어] 47회차 보고 — 캡슐 제목 후보 2안 중 선택"
enq --message "$HEAD_MSG" --source "fbot-chief-narae@.claude" --from-bot fbot-chief-narae --target prj3
[ "$(field 'has("subject_prj")')" = false ] && ok "대조: 머리 토큰 없는 상신은 subject 미기록(이게 소실 원인)" || bad "대조 — $(field '.subject_prj')"
enq --message "$HEAD_MSG" --source "fbot-chief-narae@.claude" --from-bot fbot-chief-narae --target prj3 --subject prj9t
[ "$(field '.subject_prj // ""')" = prj9t ] && ok "🔑 --subject prj9t → subject_prj=prj9t" || bad "--subject — '$(field '.subject_prj // ""')' $(head -c 200 "$TMP/err")"
[ "$(field '.message')" = "$HEAD_MSG" ] && ok "🔑 본문 변조 없음(message 그대로)" || bad "본문 변조 — '$(field .message)'"
[ "$(field '.target // ""')" = prj3 ] && ok "target(처리자) 불변" || bad "target 불변 — '$(field .target)'"
enq --message "$HEAD_MSG" --subject 9t
[ "$(field '.subject_prj // ""')" = prj9t ] && ok "prj 접두 없는 값(9t)도 prj9t 로 정규화" || bad "접두 생략 — '$(field '.subject_prj // ""')'"
enq --message "$HEAD_MSG" --subject prj999; rc=$?
[ "$rc" != 0 ] && ok "🔑 매핑 없는 --subject 는 등록 거부(오타가 화면에 사실로 서지 않게)" || bad "매핑 없음 거부 — rc=$rc"
enq --message "$HEAD_MSG" --subject "prj9t x"; rc=$?
[ "$rc" != 0 ] && ok "형식 밖 --subject 거부" || bad "형식 거부 — rc=$rc"
enq --message "prj7 ${I}77 머리가 있는 항목" --subject prj9t
[ "$(field '.subject_prj // ""')" = prj9t ] && ok "명시 --subject 가 머리 추정보다 우선(호출자가 선언한 주제)" || bad "우선순위 — '$(field '.subject_prj // ""')'"

echo "-- 기존 항목 소급: progress helper «subject» (helper 경유 — 큐 직접 Write 금지)"
PROG="$HERE/aoa-mq-progress.sh"
mkfix() { # $1=id $2=dir $3=message — 필드 도입 전 형태(subject_prj 없음) 픽스처
  "$JQ" -n --arg id "$1" --arg m "$3" '{id:$id,type:"scheduled",status:"pending",message:$m,source:"fbot-chief-narae@.claude",target:"prj3"}' >"$TMP/mq/$2/$1.json"
}
mkfix 20261010-000001-001 queue "[컨펌] [H:방침] prj7 ${I}63_1 진로"
mkfix 20261010-000002-001 queue "본문 중간 prj7 언급만"
mkfix 20261010-000003-001 queue_done "prj60 ${I}51 종결분"
out=$("$PROG" subject 20261010-000001-001 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$("$JQ" -r '.subject_prj // ""' "$TMP/mq/queue/20261010-000001-001.json")" = prj7 ] \
  && ok "🔑 subject: 필드 없는 미종결 항목에 subject_prj=prj7 기록" || bad "subject 소급 — rc=$rc $out"
[ "$("$JQ" -r '.target' "$TMP/mq/queue/20261010-000001-001.json")" = prj3 ] && ok "소급해도 target 불변" || bad "소급 target 불변"
out=$("$PROG" subject 20261010-000001-001 2>&1); rc=$?
[ "$rc" = 0 ] && [[ $out == already:* ]] && ok "재실행은 no-op(already)" || bad "재실행 no-op — rc=$rc $out"
out=$("$PROG" subject 20261010-000002-001 2>&1); rc=$?
[ "$rc" = 0 ] && [[ $out == none:* ]] && [ "$("$JQ" -r 'has("subject_prj")' "$TMP/mq/queue/20261010-000002-001.json")" = false ] \
  && ok "머리에 prj 없으면 none · 미기록" || bad "none — rc=$rc $out"
out=$("$PROG" subject 20261010-000003-001 2>&1); rc=$?
[ "$rc" != 0 ] && [ "$("$JQ" -r 'has("subject_prj")' "$TMP/mq/queue_done/20261010-000003-001.json")" = false ] \
  && ok "종결분은 거부(기록 보존)" || bad "종결분 거부 — rc=$rc $out"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ]
