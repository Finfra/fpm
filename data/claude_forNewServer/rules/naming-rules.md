---
name: naming-rules
description: 스킬, 룰, 커맨드 등 Claude 관련 파일명과 폴더명에 대한 네이밍 컨벤션
date: 2026-03-26
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: advisory** — [`hooks/rule-guard.sh`](../hooks/rule-guard.sh) 가 `.claude/` 하위 파일명의 `_` 를 검출해 경고한다(F4-5, 정보 파일 4종·`_doc_*` 예외). 파일 생성 자체를 막지는 못한다
> 📚 **분류: 사실** — `_` vs `-`·날짜 형식 **컨벤션**. 사용자 선호이자 기존 자산과의 정합 기준

# Claude 파일·폴더 네이밍 규칙

## 기본 원칙

* Claude 관련 파일명·폴더명·명칭에는 `_` 대신 `-` 사용
* 대상: `.claude/` 하위 모든 파일·폴더 (commands, rules, skills 등)

## 적용 범위

| 대상                    | 잘못된 예                  | 올바른 예                  |
| ----------------------- | -------------------------- | -------------------------- |
| 커맨드 파일             | `web_design.md`            | `web-design.md`            |
| 룰 파일                 | `git_rules.md`             | `git-rules.md`             |
| 스킬 파일               | `wp_post.md`               | `wp-post.md`               |
| 폴더명                  | `issue_manager/`           | `issue-manager/`           |
| 슬래시 커맨드 명칭      | `/issue_fix`               | `/issue-fix`               |
| 스킬 명칭 (skill: 인자) | `skill: "wp_post"`         | `skill: "wp-post"`         |

## 날짜 파일명 형식 (기본값: `YYYY.MM.DD`)

파일명에 날짜가 들어가는 경우 **점(`.`) 구분 `YYYY.MM.DD`** 를 기본 형식으로 사용함. 사용자 선호 형식 (2026-07-28 지정).

| 대상                        | 잘못된 예                     | 올바른 예                    |
| :-------------------------- | :---------------------------- | :--------------------------- |
| 회의록                      | `2026-07-28.md`               | `2026.07.28.md`              |
| 날짜 접두·접미 문서         | `20260728_meeting.md`         | `2026.07.28_meeting.md`      |
| 날짜 폴더                   | `2026-07-28/`                 | `2026.07.28/`                |

* 적용 대상: 새로 만드는 문서·폴더의 **파일명·폴더명 + frontmatter `date:`** 양쪽
    - frontmatter 도 `date: 2026.07.28` (점 형식). YAML 은 이를 날짜가 아닌 **문자열**로 파싱하므로 날짜 연산이 필요한 도구는 별도 변환 필요
* 기존 파일의 `date: YYYY-MM-DD` 는 **소급 수정 의무 없음**. 해당 파일을 다시 손대는 시점에 함께 정리
* 기존 폴더에 다른 형식이 이미 정착해 있으면 **그 폴더의 형식을 따름** (일관성 우선). ex) `capture/{YYYYMMDD}_{SEQ}/` 는 [`capture-rules.md`](../_doc_arch/rules-ondemand/capture-rules.md) 형식 유지
* 로그·타임스탬프 등 기계 생성 파일명(`hub_htm_20260728_225409_*`)은 대상 아님

## 예외

* **정보 파일 4종** — `past_prompts.md`·`knowledge_base.md`·`learning_log.md`·`instincts.md`. hook·memory 배선이 이 이름을 참조하므로 바꾸면 깨진다([`info-files.md`](info-files.md))
* **`_doc_*` 문서 폴더** — `_doc_arch/`·`_doc_work/`·`_doc_base/`. 언더스코어 접두가 정렬·식별 기능을 한다
* 외부 도구·프레임워크가 강제하는 컨벤션이 있을 경우 해당 컨벤션 우선
* 기존 파일을 리네임할 때는 참조 경로도 함께 업데이트

## 도메인 접미사 (`-g`/`-m`/`-w`/`-v`)

SCAR 3-tier 레이어링에서 사용하는 도메인 접미사 체계의 정의·판정 기준·사례 카탈로그는 [`~/_git/___pm/_doc_arch/scar-layering-design.md`](~/_git/___pm/_doc_arch/scar-layering-design.md) 참조.

| 접미사 | 의미                          |
| :----- | :---------------------------- |
| `-g`   | global (공통 SSOT)            |
| `-m`   | macOS 앱 도메인               |
| `-w`   | web 도메인                    |
| `-v`   | game/Unity 도메인 (video game) — 정의만 편입, SCAR 구현 on-demand 🚧 |
