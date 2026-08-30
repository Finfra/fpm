---
name: INSTALL_ko
description: fpm 설치 가이드 — cdf/sshf 셸 함수, hub 서버, 갱신 경로, 선택 구성요소(fbot/MCP), 폐쇄망 설치
date: 2026.08.26
---

> 🌐 [English](INSTALL.md) | **한국어**

# 지원 환경

| OS | 상태 | 셸 | 비고 |
| :--- | :--- | :--- | :--- |
| **macOS** | ✅ 정본 | zsh | 전 기능. iTerm2 분할·Finder·클립보드 포함 |
| **Linux** | ✅ 검증됨 | bash·zsh | `cdf`/`sshf` 는 단일 `cd`/`ssh` 로 축소. hub·SCAR·MCP 는 동일 |
| **Windows 11** | 🚧 준비 중 | **Git Bash** | [아래 절](#windows-11-git-bash) 참조. 미실측 항목이 있다 |

**설치 후 확인은 OS 공통이다:**

```bash
bash tdd/run-tdd.sh      # 이 머신에서 기능이 실제로 도는지 (core + 플랫폼 + deploy)
bash sh/check.sh         # 설치 상태
```

⚠️ 두 검사는 역할이 다르다 — `check.sh` 는 *설치됐는가*, `tdd` 는 *이 OS 에서 실제로 도는가* 를 본다.
2026-08-30 에 나온 이식 함정 셋(nvm PATH·BSD `date`·홈 절대경로)은 **`check.sh` 로는 하나도 안 잡혔다**.

# 요구 사항

## 필수 — 없으면 설치가 조용히 반쪽이 된다

| 항목 | 최소 | 왜 필수인가 |
| :--- | :--- | :--- |
| **Claude Code** | 설치·로그인 완료 | `install.sh` 6·7단계가 `claude plugin`·`claude mcp` 를 호출해 SCAR·MCP 를 배선한다. **없으면 설치가 "성공" 하고 SCAR 만 통째로 빠진다** |
| **bash** | 4.x+ | 전 스크립트의 실행 셸 (Windows 는 Git Bash 동봉본) |
| **git** | 2.x+ | 배포 체인 전체가 git 위에 선다 |
| **python3** | 3.9+ | hub 서버·hook·빌더 다수 |
| **jq** | 1.6+ | aoa-mq 큐의 **원자 갱신** — 없으면 예약이 조용히 갱신 실패한다 |

⚠️ **Claude Code 를 nvm 으로 깔았다면** hook·cron 에서 `which claude` 가 실패할 수 있다
(셸 초기화가 PATH 를 채우는 구조). `bash tdd/run-tdd.sh` 의 `claude-cli-available` 이 이를 판정한다.

## 선택 — 없으면 해당 기능만 미동작

* zsh — bash 로도 동작(`install.sh` 가 `$SHELL` 을 보고 rc 를 고른다)
* iTerm2 — `cdf`/`sshf` 다중 패널 분할 (macOS 전용). 없으면 단일 `cd`/`ssh`
* VS Code + `code` CLI — `cdfv`
* Node.js 18+ / `npx` — `/fpm-issue-map` 다이어그램 렌더. **이 커맨드만** 영향
* (선택) iTerm2 — 다중 패널 분할
* (선택) VS Code + `code` CLI — `cdfv`
* (선택) Python 3 — hub 서버
* (선택) Node.js + `npx` — `/fpm-issue-map` 다이어그램 렌더. 없으면 이 커맨드만 미동작(다른 기능 무관)
* (선택) mermaid-cli(`mmdc`) 전역 설치 — 있으면 우선 사용, npx 다운로드 없이 즉시·오프라인 렌더. `npm i -g @mermaid-js/mermaid-cli`
* (선택) Keyboard Maestro (유료) — 매크로 연동

# 빠른 설치

```bash
git clone https://github.com/<you>/fpm.git ~/_git/fpm
cd ~/_git/fpm
bash sh/install.sh
source ~/.zshrc
```

`sh/install.sh` 가 수행하는 일:

1. `~/.zshrc` 에 `FPM_BASE` export + `sh/fpm.sh` 부트스트랩 source 라인 추가 (마커 가드 — 멱등)
2. `~/.info/__pmBasePath.txt` 생성 → `<repo>/projects`
3. `projects/` 스캐폴드 생성 (`0`=home, `1`=repo)
4. `Servers.md`/`Projects.md` 부재 시 `*_org.md` 예제 복사
5. hub 서버·KM 안내 출력
6. `fpm-core` 플러그인(SCAR — hub/dashboard 등) 을 `f-claude-plugins` 마켓 경유로 설치 (기본 ON, `--no-scar` 로 생략)

# 폐쇄망(air-gapped) 설치

인터넷이 차단된 환경에서는 `sh/install.sh` 가 기본으로 사용하는 GitHub 마켓(`f-claude-plugins`)에 접근할 수 없습니다. 이 경우 인터넷이 가능한 머신에서 마켓 저장소를 미리 받아 폐쇄망 머신으로 옮긴 뒤, `--local` 파라메터로 로컬 사본을 마켓 소스로 지정합니다.

```bash
# 1) 인터넷 가능 머신에서 마켓 저장소 clone
git clone https://github.com/finfra/f-claude-plugins ~/_git/__all/f-claude-plugins

# 2) f-claude-plugins 디렉토리를 폐쇄망 머신으로 복사 (USB·내부망 등)

# 3) 폐쇄망 머신에서 로컬 사본을 마켓 소스로 지정해 설치
bash sh/install.sh --local /path/to/f-claude-plugins
```

* 경로를 생략하면(`bash sh/install.sh --local`) 관례 위치(`~/_git/__all/f-claude-plugins`, `<repo>/../f-claude-plugins`, `./f-claude-plugins`)를 자동 탐색합니다.
* 지정 경로에 `marketplace.json`(또는 `.claude-plugin/marketplace.json`)이 없으면 설치를 중단하고 안내를 출력합니다.
* `--local` 은 환경변수 `FPM_MKT_REF` 보다 우선합니다. SCAR 가 불필요하면 `--no-scar` 로 셸 부트스트랩만 설치할 수 있습니다.

# 설치 후 설정

## 1. 프로젝트 매핑 (cdf)

`Projects.md` 의 `setting Script` 블록을 자신의 경로로 편집 후 실행하거나, `projects/<번호>` 파일에 경로를 한 줄씩 기록:

```bash
echo "~/_git/myproj-web" > ~/_git/fpm/projects/11
```

```bash
cdf            # 전체 목록
cdf 11         # projects/11 경로로 cd
cdf 11 12 13   # 첫 번째 cd, 나머지 iTerm2 분할
cdff 11        # Finder
cdfc 11        # 클립보드 복사
cdfv 11 12     # VS Code
```

## 2. 서버 매핑 (sshf)

`Servers.md` 의 표를 편집하고, `~/.ssh/config` 의 `# favorite` 섹션에 Host alias 정의:

```sshconfig
# favorite
Host sg
    HostName host3.example.com
    Port 9922
    User youruser
```

```bash
sshf           # 서버 목록
sshf 3         # id=3 서버 접속
sshf gpu1      # Name 으로 접속
sshf 1 2 3     # 다중 → iTerm2 분할
```

## 3. hub 서버 (선택)

HTML 렌더 + 멀티 프로젝트 대시보드:

```bash
cd ~/_git/fpm/services/hub
python3 server.py
# → http://127.0.0.1:9876/hub
```

`/projects-map` 상단의 메모 박스는 브라우저에서 바로 수정(온라인 편집)할 수 있고, 프로젝트 루트의 `_note.md` 에 자동 저장됩니다 (gitignore 대상 — 커밋되지 않음). 처음 설치 직후에는 파일이 없어 안내 문구만 표시되고, 첫 입력 시 생성됩니다.

# Windows 11 (Git Bash)

> 🚧 **미실측 구간이 있다.** 설계·판정 근거는 [`_doc_arch/windows-port-design.md`](_doc_arch/windows-port-design.md).
> 설치 후 `bash tdd/run-tdd.sh` 가 `windows` 케이스 8종을 돌려 무엇이 되고 안 되는지 알려준다.

## 왜 WSL2 가 아니라 Git Bash 인가

**Claude Code 가 어디에 있느냐**가 기준이다. `sh/install.sh` 는 `claude` CLI 를 호출해 플러그인과
MCP 서버를 배선하므로, fpm 은 **Claude Code 와 같은 파일시스템**에 있어야 한다.

* Claude Code 를 **Windows 네이티브**로 쓴다 → **Git Bash** (기본 권장)
* Claude Code 를 **WSL 안**에 설치했다 → WSL 에 설치하고 **Linux 절차**를 따른다

WSL 에 fpm 을 깔면서 Claude Code 는 Windows 에 두면, 설치는 "성공" 하는데 hook·MCP 가
**다른 쪽 Claude 를 못 본다** — 아무 오류 없이 그냥 연결되지 않는다.

## 1) 사전 준비

```bash
# 갱신

이미 설치한 뒤 최신으로 올릴 때. fpm 은 머신에 **두 계층**으로 도착하며, 한쪽만 갱신하면 반쪽 상태가 됨(`cdf` 는 최신인데 hub·hook 은 구버전, 혹은 그 반대). `sh/update.sh` 가 둘을 한 번에 처리함:

```bash
cd ~/_git/fpm
bash sh/update.sh
```

| 계층 | 위치 | 출처 | `update.sh` 가 실행하는 것 |
| :--- | :--- | :--- | :--- |
| **셸** (`cdf`·`sshf`·hub) | `~/_git/fpm` (`$FPM_BASE`) | 본 저장소 | `git pull --ff-only` |
| **SCAR** (hooks·commands·agents·skills) | Claude Code 플러그인 디렉토리 | `f-claude-plugins` 마켓 | `claude plugin marketplace update` + `claude plugin update fpm-core@f-claude-plugins` |

```bash
bash sh/update.sh --shell-only   # git pull 만
bash sh/update.sh --scar-only    # 플러그인만
```

* SCAR 갱신 후 **Claude Code 재시작** 필요 — 플러그인은 기동 시 로드됨
* `claude` CLI 가 `PATH` 에 없으면 SCAR 쪽만 경고 후 건너뜀(셸 전용 사용자는 정상). 비대화 ssh 에서는 앞에 `export PATH="$HOME/.local/bin:$PATH"` 를 붙일 것
* `git pull --ff-only` 실패 = 히스토리 분기(버전 스킴 리셋 시 발생). `Projects.md`·`Servers.md` 백업 → 재클론 → `bash sh/install.sh --clean`
* `bash sh/install.sh` 재실행도 멱등이며 플러그인을 함께 갱신하므로 갱신 경로로 쓸 수 있음. `sh/update.sh` 는 그 중 갱신만 떼어낸 빠른 쪽

# 선택 구성요소 (fbot / MCP)

저장소에는 `sh/install.sh` 가 **자동 배선하지 않는** 자산도 함께 실림. 설정 전까지는 비활성이라, 건너뛰어도 기본 설치에는 영향 없음.

| 구성요소 | 실리는 위치 | 상태 |
| :--- | :--- | :--- |
| fpm MCP 서버 | `mcp/server.py` | 수동 등록 — [mcp/README.md](mcp/README.md) 참조 |
| `aoa-mq`·`aoa-memory` MCP 서버 | `mcp/aoa-mq/`, `mcp/aoa-memory/` | 수동 등록 (`claude mcp add`) |
| fbot hook + 역할 매뉴얼 | `plugins/fpm-core/hooks/fbot-*`, `plugins/fpm-core/data/fbot/` | 플러그인과 함께 설치되나 **자립적이지 않음** — 아래 참조 |

⚠️ **fbot hook 은 아직 이식성이 없음.** 데이터 저장소와 MCP 소스를 `~/_git/___common/…` 에서 해소하는데 이 경로는 어떤 fpm 설치도 만들지 않으며, `fbot-tick.sh` 는 인터프리터 기본값이 `/opt/homebrew/bin/python3`(macOS Homebrew 전용 — Linux 에 없음)임. 활성화하려면 `AOA_MEMORY_DIR`·`AOA_MQ_DIR`·`FBOT_PYTHON` 을 실제 위치로 지정할 것. 지정하지 않으려면 fbot 을 켜지 말 것. 알려진 제약으로 추적 중.

# 제거 / 클린 재설치

`sh/uninstall.sh` 가 설치 흔적을 백업한 뒤 제거합니다 (멱등):

```bash
bash sh/uninstall.sh
```

제거 대상:

1. `~/.zshrc` / `~/.bashrc` 의 fpm 블록 (`# >>> fpm functions >>>` ~ `# <<<`)
2. `~/.info/__pmBasePath.txt`

백업 위치: `<repo>/_doc_work/z_done/fpm-uninstall-<날짜시각>/` (환경변수 `FPM_BACKUP_DIR` 로 변경 가능). `projects/`·`Projects.md`·`Servers.md` 등 사용자 데이터는 **보존**되며, 필요 시 백업 확인 후 직접 삭제하세요.

클린 재설치(백업·제거 후 재설치) 는 한 번에:

```bash
bash sh/install.sh --clean
```
