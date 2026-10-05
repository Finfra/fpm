#!/usr/bin/env python3
"""aoa-memory 정책 값 로더 — 사람 편집 파일(`data/aoa/policy.yml`)이 정본 (prj5 Issue69)

⚠️ 설계 SSOT: ~/_git/___common/_doc_arch/aoa-memory-design.md "데이터 에이징 정책"
   > "정책 값은 사람 편집 파일로 — `data/aoa/policy.yml` 에 위 수치를 두고 서버가 읽는다
   >  (aoa-mq policy.yml·sleep_mode.yml 관례). **코드에 하드코딩하지 않는다**"

왜 YAML 파서를 안 쓰나
  이 계열(aoa-mq helper·homunculus 스크립트)의 조건이 **의존성 0** 이다. prj5 에 venv 를
  들이지 않는다는 결정(설계 §MCP 서버)의 연장선이라, 읽을 형태를 `key: value` 평면으로
  한정하고 그만큼만 파싱한다. 중첩·리스트가 필요해지면 그때 형태를 바꾸는 게 아니라
  **키를 평평하게 푼다**(aoa-mq policy.yml 17키가 그렇게 유지되고 있다).

기본값의 지위
  아래 `DEFAULTS` 는 **파일이 없을 때의 폴백**이지 정본이 아니다. 운영 값을 바꾸려면
  `policy.yml` 을 고친다. 폴백을 둔 이유는 하나 — 정책 파일 부재가 도구 전체를 죽이면
  안 되기 때문이다(회귀 검증은 격리 디렉토리라 policy.yml 이 없다).
"""

import os

import store as S

POLICY_PATH = os.path.join(S.AOA_DIR, "policy.yml")


def _resolve_path():
    """정책 파일 해소 — fbot 계열 로더(fbot-state `_policy_path` 등)와 **같은 순서** (prj3#Issue757 · Issue626).

    ① `AOA_DIR/policy.yml`(테스트 픽스처가 계속 이긴다) ② prj3 정본 `~/.claude/data/aoa/policy.yml`
    ③ 배포 기본값 `policy_org.yml` ④ 없으면 ① 경로(→ 기본값). 종전엔 ①만 봐서, 운영 aoa 폴더의 그림자 사본이
    prj3 정본을 가리거나(Issue755 관측) 사본을 걷으면 값이 조용히 기본값으로 바뀌었다."""
    if os.path.exists(POLICY_PATH):
        return POLICY_PATH
    for name in ("policy.yml", "policy_org.yml"):
        p3 = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa", name)
        if os.path.exists(p3):
            return p3
    return POLICY_PATH

# 값의 근거는 설계 §데이터 에이징 표. 여기 주석은 그 표를 가리키기만 한다(복제 금지).
DEFAULTS = {
    # --- 에이징 (설계 §데이터 에이징 표) ---
    "observation_retention_days": 90,   # raw 관측 — watermark 성공 게이트 뒤에만
    "job_retention_days": 30,           # 종결 job 행
    # --- consolidation ---
    "learn_consolidation_enabled": True,
    "consolidation_strategy": "stats",  # stats(무과금 집계) | llm(Batch API 요약 — Issue70, 예산 한도 필수)
    "consolidation_model": "",          # 🔴 빈 값이 정상. 모델 ID 하드코딩 금지(prj3#Issue415)
    # --- 학습 3단 모델 티어 (prj3#Issue850 — 관찰·정리·결정). 값은 **별칭**(opus·sonnet·haiku).
    #     정본은 policy.yml 이고 빈 값이 코드 기본값이다 — 셸 해석 지점(learn-model.sh)이 단계별 폴백을 가진다.
    "learn_observe_model": "",          # 관찰 — observer-loop 분석 호출 (learn-model.sh observe)
    "learn_consolidate_model": "",      # 정리 — consolidation(worker.resolve_model)·매뉴얼핀봇 (learn-model.sh consolidate)
    "learn_decide_model": "",           # 결정 — 총괄 apply/reject 몸체 (learn-model.sh decide)
    "consolidation_budget_monthly_tokens": 0,  # 🔴 0 = 미지정 — llm 전략은 fail-loud (한도 명시 강제, Issue70)
    "consolidation_grace_days": 90,     # 늦은 도착 유예 — 실측 근거는 worker.py docstring
    # --- consolidation llm 백엔드 (prj3#Issue852 — 사용자 결정 ⓓ 2026-10-02: 구독 CLI 로 sonnet) ---
    "consolidation_backend": "api",     # api(Batch — ANTHROPIC_API_KEY 필수) | cli(`claude -p` 구독 인증 · 버킷당 1회)
    "consolidation_cli_max_projects": 10,        # 버킷 1회 호출에 싣는 프로젝트 상한(행 많은 순)
    "consolidation_cli_chars_per_project": 20000, # 프로젝트별 관측 텍스트 상한(문자)
    "consolidation_cli_timeout_secs": 600,       # 호출 1회 timeout — 잡 lease 도 이만큼 늘린다
    "consolidation_cli_overhead_tokens": 60000,  # 호출당 시스템 프롬프트 오버헤드 추정(2026-10-02 실측 56k) — 예산 2단 게이트용
    # --- job 실행 (설계 §실행 토폴로지) ---
    "lease_ttl_secs": 300,              # 초기값 — 실측 재산정 대상(설계 미해결 표)
    "job_max_attempts": 2,              # 재시도 상한 1회 = attempts 2 (§2 정합)
}

_TRUE = ("true", "yes", "on", "1")
_FALSE = ("false", "no", "off", "0")


def _coerce(raw, default):
    """기본값의 타입으로 맞춘다 — 타입 표를 따로 두지 않기 위한 장치."""
    s = raw.strip()
    if isinstance(default, bool):
        low = s.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        return default
    if isinstance(default, int):
        try:
            return int(s)
        except ValueError:
            return default
    return s


def load(path=None):
    """policy.yml 을 읽어 DEFAULTS 위에 덮어쓴 dict 를 돌려준다.

    파일 부재·읽기 실패는 **기본값으로 계속 간다**(fail-soft). 정책 파일이 없다고
    적재·조회가 멈추면 안 된다 — 다만 값을 조용히 바꾸지는 않으므로 위험이 없다.
    알 수 없는 키는 **그대로 실어 보낸다**(운영자가 추가한 값을 지우지 않는다).
    """
    out = dict(DEFAULTS)
    p = path or _resolve_path()
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k = k.strip()
                if not v.strip():
                    continue
                out[k] = _coerce(v, DEFAULTS.get(k, ""))
    except OSError:
        pass
    return out


if __name__ == "__main__":
    for k, v in sorted(load().items()):
        print("%-32s %r" % (k, v))
