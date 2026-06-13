---
name: INSTALL
description: fpm 설치 가이드 — cdf/sshf 셸 함수, hub 서버, Keyboard Maestro
date: 2026-06-06
---

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
bash install.sh
source ~/.zshrc
```

`install.sh` 가 수행하는 일:

1. `~/.zshrc` 에 `FPM_BASE` export + `sh/fpm.sh` 부트스트랩 source 라인 추가 (마커 가드 — 멱등)
2. `~/.info/__pmBasePath.txt` 생성 → `<repo>/projects`
3. `projects/` 스캐폴드 생성 (`0`=home, `1`=repo)
4. `Servers.md`/`Projects.md` 부재 시 `*_org.md` 예제 복사
5. hub 서버·KM 안내 출력

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

`uninstall.sh` 가 설치 흔적을 백업한 뒤 제거합니다 (멱등):

```bash
bash uninstall.sh
```

제거 대상:

1. `~/.zshrc` / `~/.bashrc` 의 fpm 블록 (`# >>> fpm functions >>>` ~ `# <<<`)
2. `~/.info/__pmBasePath.txt`

백업 위치: `<repo>/_doc_work/z_done/fpm-uninstall-<날짜시각>/` (환경변수 `FPM_BACKUP_DIR` 로 변경 가능). `projects/`·`Projects.md`·`Servers.md` 등 사용자 데이터는 **보존**되며, 필요 시 백업 확인 후 직접 삭제하세요.

클린 재설치(백업·제거 후 재설치) 는 한 번에:

```bash
bash install.sh --clean
```
