---
name: opus-4-8-execution-rules
description: "실행 제약 — 승인 필수 지점·sudo 금지·종료조건·재시도·루프상한 (상세는 조건부 로드)"
date: 2026.08.08
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: passive** — 런타임 집행 없음. 승인 필수 지점은 **Claude Code 자체 권한 시스템**이 처리하며 본 룰이 집행하는 것이 아니다. 종료 조건·재시도 상한 등 나머지 조항은 집행 수단이 없다. ⚠️ **§5-1(`sudo` 직접 실행 금지)은 권한 시스템도 막지 않는다** — `bypassPermissions` 에서 통과되고 OS 가 뒤늦게 GUI 로 묻는다. hook 화 가능한 조항이므로 [`../_doc_arch/rules-ondemand/hook-rules.md`](../_doc_arch/rules-ondemand/hook-rules.md) 규칙9 기준 **enforce 승격 후보**다 🚧 [TODO] **영구 passive** — 판단 영역이라 hook 검증 불가([hook-rules](../_doc_arch/rules-ondemand/hook-rules.md) 규칙9) → maker-checker.
> 📚 **분류: 예방적** — 🔧 모델 특성 **대비** 규정(종료 조건·재시도 상한·리터럴 해석). 승인 필수 지점만 실제 근거가 있고 나머지는 예방적 → F4-2 에서 조항 단위 선별

> 📖 **상세는 조건부 로드** (Issue361) — OS 다이얼로그 3종 분류·프롬프트 캐싱 힌트·Task Budget·**Fable 5 옵트인 제약**은 [`_doc_arch/rules-ondemand/opus-execution-detail.md`](../_doc_arch/rules-ondemand/opus-execution-detail.md) 로 분리했다.

# 적용 대상

`~/.claude/skills/`·`~/.claude/agents/` 내 로컬 소유 스킬·에이전트 전체. 외부 플러그인(`superpowers.*`, `obsidian.*`) 제외.

# 공통 실행 제약 (Opus 4.8 대응)

## 1. 종료 조건 명시

- 모든 워크플로우는 **명확한 완료 기준** 보유. "작업 완료 시 중단"을 구체 조건으로 표현함.
  - 예: "모든 대상 파일 처리 + 결과 보고" / "빌드·테스트 통과 확인" / "사용자 승인 수령"
- 무한 루프·자가 판단 반복 금지.

## 2. 재시도 정책

- 외부 명령(npm, git, curl, docker 등) 실패 시 **기본 재시도 횟수: 1회**.
- 2회 연속 실패 시 즉시 사용자 보고 + 대기. 자동 우회·대체 명령 실행 금지.
- 재시도 시 동일 명령 반복이 아니라 **실패 원인 진단 후 수정된 명령** 사용.

## 3. 루프 상한

- 파일 대상 반복: **최대 50개**. 초과 시 분할 요청.
- 에이전트 호출 반복: **최대 3회**. 결과 수렴 안 되면 사용자 보고.
- 대화형 루프(Q&A): **최대 5 턴**. 초과 시 요약·정리 후 종료.

## 4. 리터럴 해석 대응

Opus 4.8은 애매 표현을 문자 그대로 해석함. 다음 금지 표현 사용 금지:

| 금지                     | 대체                                        |
| :----------------------- | :------------------------------------------ |
| "시도해봐", "시도합니다" | "1회 실행 후 결과 보고"                     |
| "필요 시"                | `if {조건}: {행동}` 조건문                  |
| "가능하면"               | 명시적 조건 + 대안 행동                     |
| "일반적으로 그렇듯"      | 규칙을 **명시 기술**                        |
| "적당히", "적절히"       | 수치·기준 명시 (ex: "5개 이하", "80% 이상") |
| "상황에 맞게"            | if-else 분기로 변환                         |

## 5. 사용자 승인 필수 지점

다음 행동은 반드시 사용자 승인 후 수행:

- 파일 삭제·디렉토리 제거 (`rm`, `rm -rf`)
- git 파괴 작업 (`git reset --hard`, `git push --force`, `git branch -D`)
- 외부 시스템 변경 (npm publish, docker push, API 쓰기 호출)
- 결제·요금 발생 가능 동작 (API 대량 호출, 유료 서비스 등록)
- 민감 정보 노출 위험 동작 (토큰 출력, 자격증명 파일 접근)
- **현재 프로젝트 밖 부작용** (Issue286): 타 prj Claude 세션 기동·tmux 윈도우 생성(`pm-do` 위임), 타 repo 파일 수정·커밋. 판정: [`input-interpretation-rules.md`](input-interpretation-rules.md)
    - **예외 (Issue423)**: 신규 브랜치 생성·첫 push·브랜치 checkout(clean 트리 한정)은 타 repo 라도 승인 없이 진행. 삭제·force·`checkout -- <path>`·태그는 승인 유지. 표: [`input-interpretation-rules.md`](input-interpretation-rules.md) "예외 — git 브랜치 생성·checkout"

## 5-1. OS 권한 다이얼로그를 유발하는 명령은 직접 실행하지 않는다 (Issue328)

**Claude 가 `sudo`·타앱 데이터 접근을 실행하지 않는다.** 명령을 제시하고 **사용자가 터미널에서 직접 실행**한다.

### 대신 이렇게

1. 실행할 명령을 **코드블록 하나로** 제시한다 (여러 줄이면 한 블록에 묶어 복붙 1회로 끝나게)
2. **무엇을·왜** 하는지 1줄 덧붙인다
3. 사용자가 실행한 뒤 결과를 받아 이어서 진행한다

```bash
# ex) 사용자에게 제시하는 형태
sudo ln -sfn "/Applications/_editor/Zed.app/Contents/MacOS/cli" /usr/local/bin/zed
```

* **예외**: 사용자가 "sudo 써서 해줘" 처럼 **명시적으로 직접 실행을 지시**한 경우. 이때도 다이얼로그가 뜰 수 있음을 1줄 고지한다
* 판정 한 줄: **"이 명령이 OS 다이얼로그를 띄울 수 있는가?"** — ① 비밀번호를 물을 수 있거나 ② **남의 앱 데이터**를 건드리면 Yes → 제시. 그 외 실행
* ⚠️ **진단·조사도 예외가 아니다** — "읽기만 하니까 괜찮다"는 성립하지 않는다. ②는 읽기에서 뜬다


## 6~8 · Fable 5 (상세편)

프롬프트 캐싱 힌트(500줄 이상은 `references/` 분리) · 파괴적 작업 dry-run(§5 승인과 함께 적용) · Task Budget(>10분 루프) · **Fable 5 옵트인 제약 4종**은 [상세편](../_doc_arch/rules-ondemand/opus-execution-detail.md) 참조.

# 참조

* 모델 티어 정책: [`_doc_arch/claude-model-rules.md`](../_doc_arch/claude-model-rules.md)
* 문체·리터럴 지시: [`language-rules.md`](language-rules.md)
