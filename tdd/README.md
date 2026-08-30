---
name: tdd
description: "머신별 기능 테스트 목록 — 배포된 fpm 이 그 OS 에서 실제로 도는지 확인한다 (Issue430)"
date: 2026.08.30
---

# 왜 있나

배포 체인은 **저작 머신(macOS)에서만 성립하는 가정**을 그대로 실어 보낸다. 2026-08-30 하루에
셋이 나왔고 셋 다 **조용히 실패**했다 — nvm PATH(prj3#Issue475) · BSD `date`(prj3#Issue476) ·
홈 절대경로(Issue428). 코드를 읽어서는 안 보이고 **그 OS 에서 실행해 봐야** 드러난다.

`tdd/` 는 그 "실행해 보기" 를 **목록으로 고정**한 것이다. `_doc_*` 가 아니라 최상위에 두는 이유 —
`_doc_work/` 는 이슈 단위로 휘발하고 `_doc_arch/` 는 **공개 미러에서 제외**된다. 이 목록은
**모든 소비자 머신이 공유해야** 하므로 배포 대상에 들어가야 한다.

# 구조

| 경로 | 내용 |
| :--- | :--- |
| [`machines.yml`](machines.yml) | 머신 명부 — 이름·플랫폼·역할 |
| [`cases/core.yml`](cases/core.yml) | **전 플랫폼 공통** — 어디서든 통과해야 하는 것 |
| [`cases/macos.yml`](cases/macos.yml) · [`linux.yml`](cases/linux.yml) · [`windows.yml`](cases/windows.yml) | 플랫폼 전용 |
| [`cases/deploy.yml`](cases/deploy.yml) | **배포 체인 무결성** — 번들 동기·무결성 매니페스트·gitignore 앵커·i18n parity·tagcheck·버전 정합. 전부 실제로 사고가 났던 지점이다 |
| [`run-tdd.sh`](run-tdd.sh) | 러너 — `core` + 해당 플랫폼 + `deploy` 를 돈다 |

# 사용

```bash
bash tdd/run-tdd.sh              # 현재 머신에서 전체
bash tdd/run-tdd.sh --list       # 돌 목록만 표시(실행 안 함)
bash tdd/run-tdd.sh --only core  # 특정 묶음만
```

* 결과는 `tdd/results/` 에 남고 **gitignore** 다 — 개인 경로·호스트명이 섞이므로 공유하지 않는다.
  공유하는 것은 **무엇을 검사하는가**(목록)이지 그 머신에서 무슨 값이 나왔는가가 아니다.

# 케이스 작성 규약

```yaml
- id: date-parse                    # 고유 id (kebab)
  desc: ISO 시각을 epoch 로 파싱한다  # 무엇을 확인하는가 (한 줄)
  why: |                            # 왜 — 실패 이력이 있으면 이슈 번호
    prj3#Issue476 — date -j 는 BSD 전용이라 Linux 에서 0 을 반환하고,
    그 0 이 "1970년" 이라 due 판정이 조용히 성립하지 않았다.
  run: |                            # 실행 (0=통과)
    ...
  expect: nonzero-epoch             # 판정 방식 (아래 표)
```

| `expect` | 통과 조건 |
| :--- | :--- |
| `exit0` | 종료 코드 0 |
| `nonempty` | stdout 이 비어 있지 않음 |
| `nonzero-epoch` | stdout 이 0 보다 큰 정수 |
| `contains:<문자열>` | stdout 에 그 문자열 포함 |

⚠️ **`2>/dev/null || echo 0` 같은 삼킴을 케이스 안에 쓰지 말 것** — 그 패턴이야말로
이 폴더가 잡으려는 대상이다. 실패는 실패로 드러나야 한다.

