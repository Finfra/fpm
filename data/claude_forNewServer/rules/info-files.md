---
name: info-files
description: 기록처 판정(무엇을 어디에 남기나) + ~/.claude 정보 파일 목록·관리 방식
date: 2026-04-14
enforcement: |
  런타임 집행 없음. memory 저장 시 동반 append 도, 디버깅 후 `debug_TECH.md` 갱신도 검사하는 hook 이 없다. **영구 passive** — *"오진했는가"* 는 판단 영역이라 hook 이 판정할 수 없다([hook-rules](../_doc_arch/rules-ondemand/hook-rules.md) 규칙9) → maker-checker.
classification: |
  파일 목록은 **사실**(환경 정보). "기록처 판정" 절은 **관측된 실패**(Issue535 — 2026-09-05 prj16 fWarrange Issue277 진단이 저장소의 `debug_tech.md` 를 두고 memory 로 감)
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: passive**
> 📚 **분류: 사실 + 관측된 실패**

# 기록처 판정 — «저장소가 담을 수 있으면 저장소에»

| 남길 것                                                            | 기록처                                                                    |
| :----------------------------------------------------------------- | :------------------------------------------------------------------------ |
| 특정 프로젝트의 기술 진단 — 증상·원인·**오진 경로**·해결·계측 함정 | 그 프로젝트 `_doc_work/debug_TECH.md`                                     |
| 프로젝트 무관 재사용 팁                                            | [knowledge_base.md](../knowledge_base.md) (전역 지식은 Obsidian `~/_doc`) |
| 사용자 선호·지시·업무 방식                                         | memory `user`/`feedback` + [learning_log.md](../learning_log.md)          |
| 세션 운영에서 반복되는 행동 패턴                                   | memory `instinct`                                                         |

* 디버깅 진단은 memory 지침의 *"past fixes"* 라 memory 대상이 아니다. 양쪽에 걸치면 `debug_TECH.md` 가 본문, memory 는 포인터 한 줄 (Issue535)
* **기록 트리거** — 하나라도 해당하면 **이슈 종결 전에** `debug_TECH.md` 에 남긴다: ① 한 번이라도 오진 ② 재현·계측에 특별한 방법 ③ 원인이 환경·플랫폼·외부 도구. 평범한 수정은 커밋·`Issue.md` 로 충분
* **버그 신고를 받으면 선행 사례부터**: `grep -rni "{키워드}" Issue.md _doc_work/debug_TECH.md _doc_work/debug/` (`-i` 필수 — 표기가 갈려 있다 · graphify-first 의 정확 키 예외)
* 경로는 `_doc_work/debug_TECH.md` 하나(루트 직하 금지). 불어나면 `_doc_work/debug/{도메인}.md` 로 나누고 `debug_TECH.md` 는 허브

# 정보 파일

| 파일                                 | 관리                                                                    |
| :----------------------------------- | :---------------------------------------------------------------------- |
| `~/.claude/past_prompts.md`          | Stop hook 자동 — 직접 쓰지 않음                                         |
| `~/.claude/instincts.md`             | `/sync-instincts` 동기화 — 직접 쓰지 않음                               |
| `~/.claude/learning_log.md`          | memory `feedback` 저장 시 `* YYYY-MM-DD: {규칙 요약}` 한 줄 append      |
| `~/.claude/knowledge_base.md`        | memory `reference` 저장 시 `* YYYY-MM-DD [{출처}]: {내용}` 한 줄 append |
| `{프로젝트}/_doc_work/debug_TECH.md` | 디버깅 직후 직접 append — 저장소 문서라 이슈 종결 커밋에 함께 싣는다    |
