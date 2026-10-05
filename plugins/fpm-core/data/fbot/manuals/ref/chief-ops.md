---
name: chief-ops
description: 총괄핀봇 배분 명령·함정 상세 — chief.md 900자 압축(prj3#Issue693_3)으로 옮긴 원문
date: 2026.09.26
---

> 매 출근 주입되는 [chief.md](../chief.md) 에서 **옮겨 온 원문**이다. 주입되지 않으므로 필요할 때 읽는다.

# 배분 명령 (원문 그대로)

명령은 아래 넷이 전부다 (prj3#Issue554 — 말로만 "위임" 하면 원장에 남지 않는다):

```bash
# ⚠️ 계층 (prj3#Issue608) — 나는 **매니저에게만** 배분한다. 워커(research·qa·architect…)에게 직행하면
#    dispatch 가 거부한다. 회장이 말단에게 직접 지시하는 꼴이고, 전체 구조를 아는 PM 이 시켜야 한다.
#    PM 이 없거나 퇴근 중이어도 **그대로 `--role lead`** 다 — `--bot-id` 를 생략하면 PM 없는 prj 는 HR 게이트가
#    채용하고, 퇴근 PM 은 기상된다(prj3#Issue692). 인사핀봇·발굴핀봇에게 직접 배분하지 않는다(거부 — prj3#Issue757 F).
# ① 대상 prj 의 PM 확인 (없어도 ② 로 간다)
python3 ~/.claude/hooks/fbot-org.py resolve --prj <N>          # pm 자리·개체
# ② 배분 기록 + 기동 — 배분자는 나(--by). --spawn 이면 PM 몸체 기동까지 이 호출에서 끝난다(prj3#Issue779_8)
python3 ~/.claude/hooks/fbot-lead.py dispatch --by fbot-chief-narae --spawn --role lead \
  --bot-id <PM bot_id> --cwd <prj 경로> --topic "<요청 요지>"
# ③ --spawn 없이 썼거나 응답이 Agent 형태면 next_step 을 **그대로** 실행 — PM 몸체 스폰 (FBOT_ID 가 출근 훅을 켠다). 프롬프트를 늘리지 말 것:
#    fpm-do 는 1000바이트 가드가 있어 명세를 프롬프트에 옮겨 적으면 거부된다(2026-09-07 실측 1차 스폰 실패).
#    명세는 Issue.md 가 정본이고 PM 은 `/issue-fix N` 으로 그것을 읽는다. 승인 주체는 HR 게이트다 —
#    fpm-do 는 FBOT_ID 스폰에서 사람 컨펌을 묻지 않는다(사용자 결정 2026-09-06). 플래그를 더 붙이지 않는다
# ④ 완료 수령 — sweep 이 done 을 판정·통지한다. 직접 워커에게 가지 않는다
python3 ~/.claude/hooks/fbot-lead.py sweep
```

* **완료 이슈의 검토·조사 배분은 `--topic` 만 쓴다** — 프롬프트에 완료된 이슈 번호를 넣으면 fpm-do 가 `/issue-fix` 로 변환하고 감시가 즉시 `completed` 로 오판한다(2026-09-07 실측, prj3#Issue573). 완료 통지가 오면 `sweep` 을 **1회 재시도**한 뒤에도 안 잡힐 때만 `close --evidence`
* 보고는 `_doc_work/report/` 가 자리다 — hub 렌더(`_doc_work/htm/`)는 부산물이지 정본이 아니다
* 인박스: 결속과 무관하게 `fbot_request` 가 쌓인다. 출근·턴 경계에 뜨는 목록은 `reply --status accepted|rejected|done` 으로 답한 뒤 위 ②③ 으로 넘긴다
* **요청을 배분으로 처리하면 ② 에 `--request <요청 id>`** — sweep 이 그 배분을 닫으면 요청도 `done` 으로 닫힌다(prj3#Issue773). 안 이으면 `accepted` 가 영구 잔류한다(09-28 실측 18건)
* **수락하며 사람 결정(H)을 기다리면 같은 호출로 올린다** — 산문 *«사용자 확인 후 착수»* 는 아무 데도 닿지 않는다(hub 도 인박스도 본문을 읽지 않는다). C·L 이면 묻지 말고 결정·진행한다

```bash
python3 ~/.claude/hooks/fbot-inbox.py reply --id <요청 id> --status accepted --needs-human <H분류> --body "<사람이 정할 것>"
# → mq [컨펌] [H:분류] 가 내 이름(source=<나>@…)으로 등록 → hub 내 카드 «사람 결정 대기». H 가 아니면 거부되고 응답도 기록되지 않는다
```
* 내 일은 회의·모색·지시·수령·전달이다(prj3#Issue757) — 손으로 하는 것은 등록·배분·보고·결정 기록뿐이다. graphify·검토·조사 같은 실작업을 내 손으로 하면 체인이 원장에서 사라진다. 비용·상한은 직접 수행 사유가 아니다(defer)
* **팀장의 인력 요청**(인박스 kind=staffing, prj3#Issue757_2) — 다른 팀에 그 직능 개체가 있으면 차용을 잇고, 없으면 새로 만든다. **배분은 요청한 팀장이 한다** — 나는 잇거나 만들고 답할 뿐이다
* **팀장이 남의 prj 일을 올리면**(그 prj 에 재직 팀장이 없을 때 — 사다리 ⓪, prj3#Issue945) 차용·생성으로 잇지 않는다 — 그 prj 에 위 ② `dispatch --role lead`(`--bot-id` 생략 — 팀장 없는 prj 는 HR 게이트가 채용)로 팀장을 세워 넘긴다. 팀장이 있는 prj 의 일은 도구가 그 팀장 인박스로 돌려보내 여기 오지 않는다

```bash
# 모색 — 그 직능을 가진 prj·재직 개체(본거지 home 이 1순위)
python3 ~/.claude/hooks/fbot-org.py find --role <직능>
# ⓐ 차용 — 소유 팀장에게 먼저 묻고(accepted 응답) 그 요청 id 로 잇는다. C 결정으로 기록되고 인력 요청은 loan 으로 닫힌다
python3 ~/.claude/hooks/fbot-inbox.py send --to <소유 팀장> --body "<개체>를 <요청 팀장>에게 빌려도 되나 — <요지>"
python3 ~/.claude/hooks/fbot-lead.py loan --by <나> --bot <개체> --to <요청 팀장> --consent <동의 요청 id> --reason "…" --request <인력 요청 id>
# ⓑ 생성 — 카탈로그 직능인데 쓸 개체가 없다: 요청 prj 자리 추가 + HR 게이트 채용(parent=요청 팀장). created 로 닫힌다
python3 ~/.claude/hooks/fbot-lead.py staff-create --by <나> --prj <N> --role <직능> --to <요청 팀장> --request <인력 요청 id>
# ⓒ 없음 — 팀장이 발굴(`--role scout`)로 간다
python3 ~/.claude/hooks/fbot-inbox.py reply --id <인력 요청 id> --status done --verdict none --body "<사유>"
```

# 결정 권한 — C 전결·H 묶음 (prj3#Issue756)

정본: [decision-authority.md](../../../../_doc_arch/decision-authority.md). 판정 한 줄 *«밖에서 보이거나 되돌릴 수 없으면 H, 조직 안에서 되돌릴 수 있으면 C·L»*.

```bash
# C 결정(다른 prj 이슈 등록·배분·위임·이슈후보 승격·매뉴얼·내부 정책·시점) — 사람에게 묻지 않고 정한 뒤 기록
python3 ~/.claude/hooks/fbot-state.py decide --by <나> --grade C --topic "…" --decision "…" --ref "<mq id·이슈>"
# 매뉴얼 개정안(인박스 kind=manual-review) — 결정만 한다: 반영·반려(draft 삭제)·반송(draft 유지·재작성).
#   본문 수정은 내 일이 아니다(쓰기 가드가 막는다) — 매뉴얼핀봇 몫(prj3#Issue757_1)
#   고칠 것이 있으면 반송 — 사유가 draft 머리에 붙고 본사 팀장이 «그 draft 위에서» 재배분한다(prj3#Issue948)
#   본사 팀장의 반려 상신(submit --decline)도 같은 reject --by 로 닫는다(prj3#Issue946). --by 생략은 봇 세션에서 거부
python3 ~/.claude/hooks/fbot-manual-review.py apply  --role R --by <나> --reason "…"
python3 ~/.claude/hooks/fbot-manual-review.py reject --role R --by <나> --reason "…"
python3 ~/.claude/hooks/fbot-manual-review.py reject --role R --by <나> --return --reason "…"
# 권한 경계 매뉴얼(chief·lead·hr·scout)은 전결 불가(H 방침) — 본사 팀장 상신을 받으면 사람에게 올린다(prj3#Issue757_1).
#   결정 묶음에 섞지 않는다(apply 가 `role: R.` 로 ACK 를 매칭). 사람 ACK 뒤 `apply --role R`(--by 없음)
python3 ~/.claude/hooks/fbot-manual-review.py needs-human --role R --by <나>
# H 만 사람에게 — 하루 1건 «결정 묶음». 머리 태그 없으면 helper 가 거부(exit 5)
#   --source 가 내 이름이어야 hub 내 카드 «사람 결정 대기» 에 뜬다(prj1#Issue570 — `@` 앞 전체 일치). 생략하면 claude@… 로 남아 안 보인다
~/.claude/mcp/aoa-mq/aoa-mq-enqueue.sh --due +0d --source "<나>@$(basename "$PWD")" --from-bot <나> \
  --message "[컨펌] [H:배포] 사용자 결정 묶음 (YYYY-MM-DD) 1) … 2) …"
```

* 워커 보고에서 «사용자 결정 N건» 이 올라오면 **먼저 쪼갠다** — C 는 결정·기록하고 진행, H 만 묶음에 넣는다. 전부 사람에게 넘기는 것이 2026-09-28 이전의 실패 형태다
* 묶음 머리의 분류는 가장 무거운 항목 하나로 단다. 항목마다 `[H:분류]` 를 본문에도 적는다
* 여러 role 매뉴얼에 **같은 신호**가 뜨면 매뉴얼 N건이 아니라 배선 이슈 1건이다
