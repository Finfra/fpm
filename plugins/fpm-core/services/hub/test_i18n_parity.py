#!/usr/bin/env python3
# test_i18n_parity.py — i18n catalog 패리티 회귀 테스트 (Issue211 Phase 3 / 영역 D)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). data/locales/{en,ko}.json 의 키 대칭성,
#   en 값의 한글 혼입 부재, server.py 가 t() 로 참조하는 키의 catalog 존재를 검증한다.
#   Issue210(en 모드에 ko 키 누락 → 한글 fallback) 일회성 점검을 영속 회귀로 승격.
#
# 설계 SSOT: _doc_arch/localization.md / _doc_arch/fpm-release-test.md (D 영역)
# 실행: python3 services/hub/test_i18n_parity.py
# exit: 0=전부 PASS, 1=하나 이상 FAIL
"""i18n en↔ko catalog 패리티 + 코드 참조 무결성 + 한글 혼입 스캔."""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
LOCALES = os.path.join(REPO, "data", "locales")
SERVER = os.path.join(HERE, "server.py")

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


def load(lang):
    with open(os.path.join(LOCALES, f"{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


# 한글(가-힣 + 자모) 정규식
_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")


def main():
    en = load("en")
    ko = load("ko")
    en_keys = set(en)
    ko_keys = set(ko)

    # 1. 키 대칭성 (Issue210 회귀) — 한쪽 누락 키 0
    #    Issue292: `settings.label.*` 는 **의도적 ko 전용** 네임스페이스라 대칭 검사에서 면제한다.
    #    설정창은 ko 카탈로그에 라벨이 있으면 한국어로, 없으면 원본 키를 그대로 보여준다
    #    (server.py `koLbl = ttf('settings.label.' + s.key, '')` — en 뷰에서 원본 키 노출이 정상,
    #     `_` 숨김 + 복붙 시 실제 키 보존이 목적, Issue208). en 쪽에 같은 키를 채우면 오히려
    #    그 설계가 깨지므로, 여기서 FAIL 을 내는 것은 테스트의 오탐이다.
    ONLY_KO_OK = ("settings.label.",)
    only_en = en_keys - ko_keys
    only_ko = {k for k in ko_keys - en_keys if not k.startswith(ONLY_KO_OK)}
    check("en↔ko 키 대칭(en 전용 0)", not only_en, f"en 전용: {sorted(only_en)[:10]}")
    check(
        f"en↔ko 키 대칭(ko 전용 0, {'/'.join(ONLY_KO_OK)}* 면제)",
        not only_ko,
        f"ko 전용: {sorted(only_ko)[:10]}",
    )
    check("catalog 비어있지 않음", len(en_keys) > 0 and len(ko_keys) > 0)

    # 2. en 값에 한글 혼입 0 (Issue210 핵심 — en 모드 한글 fallback 방지)
    hangul_in_en = [k for k, v in en.items() if isinstance(v, str) and _HANGUL.search(v)]
    check("en 값 한글 혼입 0", not hangul_in_en, f"한글 포함 키: {hangul_in_en[:10]}")

    # 3. ko 값 빈 문자열 0 (번역 누락 가시화)
    empty_ko = [k for k, v in ko.items() if isinstance(v, str) and not v.strip()]
    check("ko 값 빈 문자열 0", not empty_ko, f"빈 값 키: {empty_ko[:10]}")

    # 4. 코드 참조 무결성 — server.py t('namespace.key') 호출 키가 catalog 에 존재.
    #    점(.) 포함 키만 i18n 키로 간주 (t('a')/t('div') 등 비-i18n 오탐 제외).
    #    Issue292: negative lookbehind 로 접미 오탐 차단 — `split("...")`·`closest("...")` 처럼
    #    식별자가 `t(` 로 끝나는 호출이 i18n 헬퍼로 오인되어 인자(ex: ".")를 키로 수집하던 버그.
    #    `i18n.t(` 는 앞이 `.` 이라 lookbehind 를 통과하므로 정상 수집됨.
    with open(SERVER, encoding="utf-8") as f:
        src = f.read()
    raw = set(re.findall(r"""(?<![A-Za-z0-9_])t\(\s*['"]([A-Za-z0-9_.]+)['"]""", src))
    referenced = {k for k in raw if "." in k}
    missing = sorted(k for k in referenced if k not in en_keys)
    check(
        f"server.py t() 참조 키 catalog 존재 ({len(referenced)}개 검사)",
        not missing,
        f"누락 키: {missing[:10]}",
    )

    # 5. DEFAULT_LANG 가 catalog 존재 (fallback 종착 보증)
    import i18n  # noqa: E402

    check(f"DEFAULT_LANG='{i18n.DEFAULT_LANG}' catalog 존재", i18n.DEFAULT_LANG in i18n.SUPPORTED)
    # 미지원 언어 → en fallback (크래시 없음)
    val = i18n.t("settings.title", "ja")
    check("미지원 언어(ja) → fallback 무크래시", isinstance(val, str) and val != "")

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
