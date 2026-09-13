---
name: info-files
description: 기록처 판정(무엇을 어디에 남기나) + ~/.claude 정보 파일 목록·관리 방식
date: 2026-04-14
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: passive** — 런타임 집행 없음. memory 저장 시 동반 append 도, 디버깅 후 `debug_TECH.md` 갱신도 검사하는 hook 이 없다. **영구 passive** — *"오진했는가"* 는 판단 영역이라 hook 이 판정할 수 없다([hook-rules](../_doc_arch/rules-ondemand/hook-rules.md) 규칙9) → maker-checker.
> 📚 **분류: 사실 + 관측된 실패** — 파일 목록은 **사실**(환경 정보). "기록처 판정" 절은 **관측된 실패**(Issue535 — 2026-09-05 prj16 fWarrange Issue277 진단이 저장소의 `debug_tech.md` 를 두고 memory 로 감)

# 기록처 판정 (무엇을 어디에 남기나)

**판정 한 줄: *"저장소가 담을 수 있으면 저장소에."*** 프로젝트에서 겪은 기술 진단의 **1차 기록처는 그 프로젝트의 `_doc_work/debug_TECH.md`** 이지 memory 가 아니다.

| 남길 것 | 기록처 |
| :--- | :--- |
| 특정 프로젝트의 기술 진단 — 증상·원인·**오진 경로**·해결·계측 함정 | 그 프로젝트 `_doc_work/debug_TECH.md` |
| 프로젝트 무관 재사용 팁 | [`knowledge_base.md`](../knowledge_base.md) (전역 지식은 Obsidian `~/_doc`) |
| 사용자 선호·지시·업무 방식 | memory `user`/`feedback` + [`learning_log.md`](../learning_log.md) |
| 세션 운영에서 반복되는 행동 패턴 | memory `instinct` |

* **memory 지침 자체가 이 경계를 이미 갖고 있다** — *"Don't save what the repo already records (code structure, **past fixes**, git history)"*. 디버깅으로 얻은 진단은 정확히 그 **past fixes** 이므로 memory 대상이 아니다
* 왜 어긋나는가: memory 지침은 **상시 로드**되고 문구가 강한 반면 `debug_TECH.md` 관행은 프로젝트 스킬(`/doc-work`) 안에만 있어 자동 발동하지 않는다. 이 **비대칭**이 판정을 memory 쪽으로 기울인다 (Issue535 실발생)
* 한 사건이 양쪽에 걸치면 **`debug_TECH.md` 가 본문, memory 는 포인터 한 줄**이다. 같은 내용을 두 벌 쓰지 않는다

## 기록 트리거 (하나라도 해당하면 `debug_TECH.md` 에 남긴다)

1. 해결 과정에서 **한 번이라도 오진**했다 — 버려진 가설이 다음 사람이 아낄 시간이다
2. 재현·계측에 **특별한 방법**이 필요했다 (전수 조회·형식 A/B 테스트·타이밍 의존)
3. 원인이 코드가 아니라 **환경·플랫폼·외부 도구**였다 (OS 캐시·권한·버전 불일치·프레임워크 특성)

* 트리거에 안 걸리는 평범한 수정은 커밋 메시지와 `Issue.md` 로 충분하다 — **전건 기록은 요구하지 않는다**
* 기록 시점은 **이슈 종결 전**이다. 종결 후로 미루면 진단 경로의 세부가 이미 날아간다

## 읽기 우선 (버그 신고를 받으면)

**코드 grep 보다 선행 사례가 먼저다.**

```bash
grep -rni "{핵심키워드}" Issue.md _doc_work/debug_TECH.md _doc_work/debug/ 2>/dev/null
```

* `-i` 는 필수 — 기존 표기가 `debug_TECH.md`·`debug_tech.md`·`DEBUG_tech.md` 로 갈려 있다(Issue535 에서 표준화 진행)
* graphify 가 있는 repo 라도 **선행 디버깅 사례 조회는 정확 키 lookup** 이라 [graphify-first](../_doc_arch/rules-ondemand/graphify-rules.md) 의 grep 예외에 해당한다

## 파일명·경로 표준

* 표준은 **`_doc_work/debug_TECH.md`** 하나다. 프로젝트 루트 직하 생성 금지([nptir-rules](../_doc_arch/rules-ondemand/nptir-rules.md))
* 항목이 불어나면 prj15 fSnippet 방식으로 `_doc_work/debug/{도메인}.md` 로 분기하고 `debug_TECH.md` 는 **허브**로 남긴다
* 신규 생성은 이 이름만 쓴다. 기존 갈림 표기는 발견 시 [rename 절차](../_doc_arch/rules-ondemand/rename-reference-rules.md) 로 정리

# 정보 파일 목록

| 파일 | 용도 | 관리 방식 |
| :--- | :--- | :--- |
| `~/.claude/past_prompts.md` | 의미 있는 프롬프트 기록 | Stop hook(save-prompt.sh) 자동 append — Claude 직접 쓰지 않음 |
| `~/.claude/knowledge_base.md` | 일반 지식·팁·요령 | auto-memory `reference` 타입 저장 시 함께 append |
| `~/.claude/learning_log.md` | 학습 내용·인사이트 | auto-memory `feedback` 타입 저장 시 함께 append |
| `~/.claude/instincts.md` | 행동 패턴 요약 | `/sync-instincts` 커맨드로 homunculus 동기화 — Claude 직접 쓰지 않음 |
| `{프로젝트}/_doc_work/debug_TECH.md` | 그 프로젝트의 기술 진단 사례 | Claude 가 디버깅 직후 직접 append (위 트리거) — prj3 본체는 [`_doc_work/debug_TECH.md`](../_doc_work/debug_TECH.md) |

# 저장 규칙

* `feedback` 타입 저장 시: memory 파일 저장 + `learning_log.md` 한 줄 append
    - 형식: `* YYYY-MM-DD: {규칙 요약}`
* `reference` 타입 저장 시: memory 파일 저장 + `knowledge_base.md` 한 줄 append
    - 형식: `* YYYY-MM-DD [{출처}]: {내용}`
* `past_prompts.md`, `instincts.md` 는 자동화로만 관리 (Claude가 직접 쓰지 않음)
* `debug_TECH.md` 는 **저장소 문서**라 memory·정보 파일과 달리 **git 커밋 대상**이다 — 이슈 종결 커밋에 함께 싣는다
