---
name: opus-4-8-execution-rules
description: "실행 제약 — 승인 필수 지점·sudo 금지·종료조건·재시도·루프상한 (상세는 조건부 로드)"
date: 2026.08.08
enforcement: |
  런타임 집행 없음. 승인 필수 지점은 **Claude Code 자체 권한 시스템**이 처리하며 본 룰이 집행하는 것이 아니다. 종료 조건·재시도 상한 등 나머지 조항은 집행 수단이 없다. ⚠️ **§5-1(`sudo` 직접 실행 금지)은 권한 시스템도 막지 않는다** — `bypassPermissions` 에서 통과되고 OS 가 뒤늦게 GUI 로 묻는다. hook 화 가능한 조항이므로 [`../_doc_arch/rules-ondemand/hook-rules.md`](../_doc_arch/rules-ondemand/hook-rules.md) 규칙9 기준 **enforce 승격 후보**다 🚧 [TODO] **영구 passive** — 판단 영역이라 hook 검증 불가([hook-rules](../_doc_arch/rules-ondemand/hook-rules.md) 규칙9) → maker-checker.
classification: |
  🔧 모델 특성 **대비** 규정(종료 조건·재시도 상한·리터럴 해석). 승인 필수 지점만 실제 근거가 있고 나머지는 예방적 → F4-2 에서 조항 단위 선별
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: passive**
> 📚 **분류: 예방적**

> 📖 **상세 조건부** — OS 다이얼로그 3종·리터럴 대체표·캐싱·Task Budget·Fable 5 제약: [opus-execution-detail.md](../_doc_arch/rules-ondemand/opus-execution-detail.md)

적용 대상: `~/.claude/skills/`·`agents/` 로컬 소유 스킬·에이전트 전체(외부 플러그인 제외).

# 공통 실행 제약

1. **종료 조건 명시** — 워크플로우마다 구체 완료 기준(ex) "대상 파일 전부 처리 + 결과 보고"). 무한 루프·자가 판단 반복 금지
2. **재시도** — 외부 명령 실패 시 1회만, 원인 진단 후 **수정한 명령**으로. 2회 연속 실패면 즉시 보고·대기(자동 우회 금지)
3. **루프 상한** — 파일 반복 50개 · 에이전트 호출 3회 · 대화형 Q&A 5턴. 넘으면 분할·보고
4. **리터럴 해석** — SCAR·프롬프트에 "시도해봐"·"필요 시"·"적당히" 같은 애매 표현 금지 → 횟수·조건·수치로 쓴다(대체표는 상세편 §4)

# 사용자 승인 필수 지점

* 파일·디렉토리 삭제(`rm`) · git 파괴(`reset --hard`·`push --force`·`branch -D`) · 외부 시스템 변경(publish·push·API 쓰기) · 과금 가능 동작 · 민감 정보 노출(토큰 출력·자격증명 접근)
* **현재 프로젝트 밖 부작용**(Issue286) — 타 prj 세션 기동·타 repo 수정·커밋. 판정과 예외(신규 브랜치·checkout — Issue423 · 이슈 등록·원장 경유 배분 — Issue756)는 [input-interpretation-rules.md](input-interpretation-rules.md)

## 5-1. OS 권한 다이얼로그를 유발하는 명령은 직접 실행하지 않는다 (Issue328)

**Claude 가 `sudo`·타앱 데이터 접근을 실행하지 않는다** — 명령을 **코드블록 하나로** 제시하고 무엇을·왜 1줄을 붙여 사용자가 터미널에서 실행하게 한 뒤 결과를 받아 잇는다.

* 판정 한 줄: **"이 명령이 OS 다이얼로그를 띄울 수 있는가?"** — ① 비밀번호를 물을 수 있거나 ② **남의 앱 데이터**를 건드리면 제시, 그 외 실행
* ⚠️ **진단·조사도 예외가 아니다** — ②는 읽기에서 뜬다
* 예외: 사용자가 "sudo 써서 해줘" 처럼 **명시 지시**한 경우 — 다이얼로그가 뜰 수 있음을 1줄 고지

참조: 모델 티어 [claude-model-rules.md](../_doc_arch/claude-model-rules.md) · 문체 [language-rules.md](language-rules.md)
