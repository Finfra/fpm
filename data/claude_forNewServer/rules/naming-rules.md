---
name: naming-rules
description: 스킬, 룰, 커맨드 등 Claude 관련 파일명과 폴더명에 대한 네이밍 컨벤션
date: 2026-03-26
---

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

## 예외

* 외부 도구·프레임워크가 강제하는 컨벤션이 있을 경우 해당 컨벤션 우선
* 기존 파일을 리네임할 때는 참조 경로도 함께 업데이트
