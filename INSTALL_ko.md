---
name: INSTALL_ko
description: fpm 설치 가이드 — cdf/sshf 셸 함수, hub 서버, Keyboard Maestro, 폐쇄망 설치
date: 2026-06-21
---

> 🌐 [English](INSTALL.md) | **한국어**

# 요구 사항

* macOS (cdf/sshf 의 iTerm2 분할·Finder·클립보드 기능). Linux 는 단일 `cd`/`ssh` 만 동작
* zsh
* (선택) iTerm2 — 다중 패널 분할
* (선택) VS Code + `code` CLI — `cdfv`
* (선택) Python 3 — hub 서버
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

## 4. Keyboard Maestro (선택)

`keyboard-maestro/README.md` 참조 — `.kmmacros` import + Accessibility 권한.

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
