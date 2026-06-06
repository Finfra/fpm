---
name: Servers_org
title: Server Management (Example)
description: Example favorite SSH server list. install.sh가 Servers.md 부재 시 본 파일을 복사함.
date: 2026-06-06
---

# Favorite Servers

> 본 파일은 **예제 템플릿**. 실제 운영 파일 `Servers.md`는 개인정보라 `.gitignore` 처리됨.
> `install.sh` 실행 시 `Servers.md`가 없으면 본 파일이 복사됨. 복사 후 자신의 서버 정보로 교체할 것.
> Name 컬럼은 `~/.ssh/config`의 `# favorite` 섹션 Host alias와 일치해야 함.

| id   | Name    | ssh alias | Host              | Port | User    | Description           | check |
| :--- | :------ | :-------- | :---------------- | :--- | :------ | :-------------------- | ----- |
| 1    | local1  | sl1       | host1.example.com | 22   | youruser | 예시 macOS 서버      | O     |
| 2    | local2  | sl2       | host2.example.com | 22   | youruser | 예시 macOS 서버      | O     |
| 3    | gpu1    | sg        | host3.example.com | 9922 | youruser | 예시 GPU Ubuntu      | O     |
| 4    | web1    | sw        | example.com       | 22   | youruser | 예시 웹 호스팅       | O     |
| 5    | lanpc   | spc       | 192.168.0.10      | 22   | youruser | 예시 LAN PC          | X     |

> check 컬럼: `O` 인 행만 `/server-check` 점검 대상. 제외하려면 `X`(또는 공란)로 변경.

## Reference

`~/.ssh/config`의 `# favorite` 섹션에 위 Host alias를 정의할 것. 예:

```sshconfig
# favorite
Host sl1
    HostName host1.example.com
    Port 22
    User youruser
```
