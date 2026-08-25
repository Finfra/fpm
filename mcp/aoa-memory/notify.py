#!/usr/bin/env python3
"""aoa-memory 완료 통지 — 가속 B (UserPromptSubmit hook 주입) · prj5 Issue68 B-3

⚠️ 설계 SSOT: ~/_git/___common/_doc_arch/aoa-memory-design.md "## 완료 통지 경로"

왜 hook 주입인가 (주체 제약)
  `SendMessage` 는 **Claude 세션의 도구**다. python worker·stdio MCP 서버는 그것을 부를 수
  없다(prj5#Issue64·65 확정 — `~/.bin/fpm-do` 가 zsh 에서 막힌 것과 동일 제약, 언어만 다르다).
  따라서 worker·서버가 끝낸 잡의 통지는 push 가 아니라 **세션의 다음 턴 진입 컨텍스트에
  실어 보내는 것**으로 성립시킨다. 이것이 가속 B 다.
  * 가속 A(`SendMessage`)는 **완료 주체가 Claude 세션인 잡**(위임 워커)에만 해당한다.
  * 영속 계층(`job` 테이블)은 지우지 않는다 — 세션이 죽으면 메시지도 hook 도 닿지 않는다.

동작
  종결(done/failed)됐고 아직 전달되지 않은 잡을 **한 번에 묶어** 출력하고, 전달 표식을
  `registry.kv(ns='notify')` 에 30일 TTL 로 남긴다(건당 발신 금지 — 수신 세션의 컨텍스트를
  소모한다). 표식이 있으므로 같은 잡이 매 턴 재고지되지 않는다.

fail-soft
  스토어가 없거나 읽기에 실패하면 **아무 것도 출력하지 않고 0 으로 끝난다**. 통지 실패가
  사용자 턴을 막아서는 안 된다. 단 표식 기록이 실패하면 다음 턴에 다시 고지된다(중복 고지
  > 유실 — 통지는 유실을 발신자가 감지할 수 없는 계층이다).

등록 (⚠️ 미등록 상태 — 본 위임 범위 밖)
  실제 주입은 `UserPromptSubmit` hook 등록이 있어야 발화한다. 그 등록 지점은
  `~/.claude/settings.json`(글로벌 SCAR)이라 prj3 이슈 절차를 탄다 — Issue68 이 넘긴 TODO.
      "hooks": { "UserPromptSubmit": [ { "hooks": [ { "type": "command",
        "command": "python3 ~/_git/___common/mcp/aoa-memory/notify.py" } ] } ] }
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TTL_SEC = 30 * 24 * 3600        # job 행 GC 30일과 같은 창 (에이징 표 정합)


def main() -> int:
    try:
        import store as S
        if not os.path.exists(S.REGISTRY_DB):
            return 0
        with S.connect(S.REGISTRY_DB) as c:
            now = S.now()
            rows = c.execute(
                "SELECT j.id, j.store, j.kind, j.status, j.result FROM job j "
                "LEFT JOIN kv k ON k.ns='notify' AND k.key=j.id "
                "  AND (k.expires_at IS NULL OR k.expires_at>?) "
                "WHERE j.status IN ('done','failed') AND k.key IS NULL "
                "ORDER BY j.created_at LIMIT 20",
                (now,),
            ).fetchall()
            if not rows:
                return 0

            lines = ["[aoa-memory] 종결된 배치 잡 %d건 — 결과 회수 가능" % len(rows)]
            for r in rows:
                head = (r["result"] or "").strip().splitlines()
                lines.append("* %s (%s/%s) → %s%s" % (
                    r["id"], r["store"], r["kind"], r["status"],
                    " — " + head[0][:120] if head else ""))
            lines.append("상세는 `job_get(id=...)` 으로 조회한다.")
            sys.stdout.write("\n".join(lines) + "\n")

            try:                     # 표식 기록 실패는 중복 고지로 흡수한다(유실보다 낫다)
                c.execute("BEGIN IMMEDIATE")
                c.executemany(
                    "INSERT INTO kv(ns, key, value, expires_at, updated_at, updated_by) "
                    "VALUES('notify', ?, 'delivered', ?, ?, 'notify.py') "
                    "ON CONFLICT(ns, key) DO UPDATE SET value='delivered', "
                    "expires_at=excluded.expires_at, updated_at=excluded.updated_at",
                    [(r["id"], now + TTL_SEC, now) for r in rows],
                )
                c.commit()
            except Exception:
                pass
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
