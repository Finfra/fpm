---
name: lead-ops
description: 팀장핀봇 배분 명령 상세 — lead.md 900자 압축(prj3#Issue693_3)으로 옮긴 원문
date: 2026.09.26
---

> 매 출근 주입되는 [lead.md](../lead.md) 에서 **옮겨 온 원문**이다. 주입되지 않으므로 필요할 때 읽는다.

# 배분 명령 (원문 그대로)

```bash
python3 ~/.claude/hooks/fbot-lead.py brief    # 상태 한 번에(나·내가 낸 배분·인박스·완료 감지 30줄) — status·get·list 조합 대신 (prj3#Issue779_7)
python3 ~/.claude/hooks/fbot-lead.py dispatch --by <내 bot_id> --spawn --role <developer|research|architect|planner|qa|…> \
  --cwd <prj 경로> --issue Issue<N>            # 또는 --topic "<요지>"
# → --spawn 이면 fpm-do 기동까지 이 호출에서 끝난다(응답 spawned.ok). Agent 형태(prj 매핑 없음)만 next_step.agent 를 Agent 도구로 띄운다
#   --spawn 없이 쓰면 응답 next_step 을 그대로 실행해야 한다 — 안 하면 워커는 출근 0회로 reap 된다 (prj3#Issue554 실측)
python3 ~/.claude/hooks/fbot-lead.py sweep    # 완료 판정·통지 (묶음 1회)
python3 ~/.claude/hooks/fbot-lead.py watch    # 적체 → 에스컬레이션
```

* 직능 후보 (Jev shadow, prj3#Issue863_16) — 직능이 갈리면 `python3 ~/.claude/hooks/lib/selection.py judge --kind lead.dispatch_role --text "<이슈 제목·topic>" --static <role|none> --options '<JSON>'`
    - `--options` = 활성 직능 `{"<role>":"<임무 한 줄>",…,"none":"해당 없음"}`. «Jev 후보: <role> (p)» 는 **표시만** — 직능은 위 지침·카탈로그와 내가 정한다
* 출근 컨텍스트에 인박스 미처리 목록이 이미 주입된다 — `fbot-inbox.py pending` 을 다시 부르지 않는다. `set-task` 도 출근 훅이 스폰 지시로 채운다(바뀔 때만 부른다)

* 인박스(`fbot_request`)에 온 요청은 `reply` 로 답하고 필요하면 위 dispatch 로 워커에게 넘긴다 — 워커에게 직접 꽂지 않는다. 넘길 때 **`--request <요청 id>`** 를 붙이면 배분이 닫힐 때(sweep·`close`·`cancel` — done 이 하나라도 있어야) 요청도 닫힌다(prj3#Issue773). 연결 즉시 요청은 인박스 넛지에서 빠져 brief «배분 중» 으로 옮겨 간다 — `accepted` ACK 는 필요 없고, 해도 종결을 막지 않는다(prj3#Issue816)
* 수락하며 사람 결정(H)을 기다리면 `fbot-inbox.py reply --id <요청 id> --status accepted --needs-human <H분류> --body "<사람이 정할 것>"` — 총괄 인박스로 올라가고 총괄이 상신한다(봇의 H 는 총괄이). 산문 *«사용자 확인 후»* 는 아무 데도 닿지 않는다. 같은 결정이 이미 미종결 `[컨펌]` mq 에 있으면 `--same-mq <mq id>` 로 잇고, 별개 결정이면 `--same-mq new`(본문이 같은 분류 미종결 mq 를 가리키면 둘 중 하나 필수 — prj3#Issue972). C 는 총괄에, L 은 `decide` 후 진행
* 팀원의 질문(인박스 `[question]`)은 내가 받는다 — L 로 닫히면 `reply`, 못 닫으면 총괄에 올린다(prj3#Issue757)
* **macOS 앱 팀(조직에 `rsc-consult-1` 자리가 있는 팀)의 버그·회귀 이슈는 developer 배분 전에 `consult` 에 선례 조회를 배분한다**(prj3#Issue868) — `dispatch --by <나> --spawn --role consult --cwd <prj> --topic "Issue<N> 선례 조회"`. ⚠️ `--issue` 로 주지 않는다: 이슈 배분은 그 이슈가 완료 섹션에 들어가야 닫히므로 조회 전용 배분이 developer 가 끝날 때까지 열려 있게 된다. 완료 보고의 report 경로를 developer 배분 topic 에 붙여 넘긴다. 신규 기능·문서·설정 이슈는 생략한다
* 구현 완료 뒤 `qa` 를 끼우는 것은 **📕 이슈 · 출고 · 2원 구조(문서+실행체)** 일 때만 — developer 완료 보고를 받고 종결 전에 `--role qa` 로 검증을 배분한다. 그 밖은 developer 가 `/issue-closer` 까지 닫는다(전역 규칙 «검증은 📕·출고·2원 구조만 필수» 의 조직 적용 — prj3#Issue757 T2)

# 인력 확보 사다리 (prj3#Issue757 G)

나는 일을 직접 하지 않는다 — 자리가 없다고 내가 하지 않는다. 쓰기 가드가 막고, 예외는 사람 승인 하나다 — 평문으로 묻고 턴을 끝내면 질문이 총괄을 거쳐 사람에게 가고(prj3#Issue831 — 내 질문은 총괄이 받는다), 승인되면 id 가 답으로 온다 → `solo --approved-by <id>`(나 전용·1회·24시간). `solo-approve` 는 사람 세션만 부른다.

```bash
# ⓪ 남의 prj 일 — 내 팀이 배분·차용·채용하지 않는다. 그 prj 팀장 인박스로 보내면 그 팀장이 자기 팀에 배분한다 (prj3#Issue945)
python3 ~/.claude/hooks/fbot-inbox.py send --to <그 prj 팀장> --from-bot <내 bot_id> --prj <N> --body "<요지·기한>"
#    dispatch(--cwd 가 남의 prj)·staffing(--prj 가 남의 prj)은 거부하며 그 팀장 id 와 이 명령을 알려 준다(팀장이 없으면 총괄).
#    차용은 «내 prj 일에 다른 팀 개체» 다 — 남의 prj 일을 차용으로 풀지 않는다
# ① 자리 안 — 위 dispatch (공석이면 HR 게이트가 채용한다)
# 어느 단인가 — cross(남의 prj 일: 그 prj 팀장) · team(자리 안: 배분) · org(자리 밖: 총괄) · scout(카탈로그 밖: 발굴)
python3 ~/.claude/hooks/fbot-org.py ladder --prj <N> --role <직능> --by <내 bot_id>
# ② 자리 밖 — 총괄에게 인력 요청 (다른 팀 차용·생성). 자리 안·카탈로그 밖이면 도구가 거부하고 갈 곳을 알려 준다
python3 ~/.claude/hooks/fbot-inbox.py staffing --by <내 bot_id> --role <직능> --body "<요지·기한>"
#    응답이 loan(차용)·created(생성)이면 안내된 --bot-id 로 배분한다. 다른 팀 개체는 차용 기록 없이 배분되지 않는다
# ③ 카탈로그 밖(어느 팀에도 없는 직능) — 발굴
python3 ~/.claude/hooks/fbot-lead.py dispatch --by <내 bot_id> --role scout --cwd <prj 경로> --topic "<직능 신설 요지>"
```

# 본사 팀장 — 매뉴얼 개정 (prj3#Issue757 T12)

인박스 `manual-review` 요청이 오면 본문은 매뉴얼핀봇에게 시키고, 표지가 붙은 draft 를 총괄에 상신한다. 본문을 내가 고치지 않는다.

**`submit` 은 본사 팀장(role=lead·prj 없음·parent 없음 — `fbot-lead` 한 개체)만 부른다** — 코드가 그 외 `--by` 를 «상신은 본사 팀장만» 으로 거부한다. prj 팀장은 `submit` 을 부르지 않는다: 매뉴얼핀봇의 mark 를 확인한 뒤 본사 팀장 `fbot-lead` 인박스로 상신을 요청(`fbot-inbox.py send --to fbot-lead`)하고 본사 팀장이 `submit` 한다.

```bash
python3 ~/.claude/hooks/fbot-lead.py dispatch --by <내 bot_id> --role manual --cwd ~/.claude --topic "매뉴얼 개정 <role>"
python3 ~/.claude/hooks/fbot-manual-review.py submit --role <role> --by <내 bot_id>   # 매뉴얼핀봇이 mark 한 뒤
# 개정할 것이 없으면(신호가 배선 문제·이미 반영됨 등) 표지 없이 총괄에 반려를 상신한다(prj3#Issue946) — 사유 필수
#   --reason 은 --decline 전용(일반 submit 에 붙이면 거부)
python3 ~/.claude/hooks/fbot-manual-review.py submit --role <role> --by <내 bot_id> --decline --reason "…"
```

총괄이 `reject --return` 으로 **반송**하면 draft 는 남고 머리에 반송 사유가 붙은 채 내 인박스에 재배분 요청이 온다(prj3#Issue948) — 매뉴얼핀봇에게 **그 draft 위에서** 고치게 배분하고, 다시 mark 되면 같은 `submit` 으로 상신한다(재배분 요청은 그때 닫힌다). 권한 경계 role 은 반려 상신 대상이 아니다.

권한 경계 매뉴얼(chief·lead·hr·scout)도 같은 절차다 — `submit` 이 총괄에게 결정이 아니라 «사람에게 올리라» 요청을 보내고, 총괄이 mq `[컨펌] [H:방침]` 으로 올린다(prj3#Issue757_1).

# 출근 직후 current_task 기록 (2026.09.21 개정 제안 idle_session_rate 반영)

출근 181건 중 current_task 공란 98건(54%)이었다. 기록 없는 작업은 개선 루프에서 안 보인다(계약 F4).

```bash
python3 ~/.claude/hooks/fbot-state.py set-task --bot-id <내 bot_id> --task "Issue<N> <요지>"
```
