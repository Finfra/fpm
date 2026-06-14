#!/usr/bin/env python3
# i18n.py — hub UI 다국어 로더 + t(key, lang) lookup (Issue169)
#
# 설계 SSOT: _doc_arch/localization.md
# 번역 catalog 는 data/locales/<lang>.json 분리 파일 — 다른 언어권 기여자가 코드 무관하게 번역 가능.
# prj15(fSnippet) catalog 패턴을 stdlib-only(json) 로 옮김. 외부 i18n 라이브러리 미사용.
# 언어 결정: hub_setting.yml 의 language 키 (en 기본 / ko). 페이지 서버 렌더 시점 반영.
"""hub UI 다국어 지원.

catalog 위치: data/locales/<lang>.json  (flat {"<영역>.<요소>": "문자열"})
fallback 체인: 요청언어 → en → 키문자열(누락 가시화)
언어 추가: data/locales/<코드>.json 추가 + DEFAULT_LANG/SUPPORTED 갱신만. 코드 변경 불필요.
mtime 캐시: 파일 수정 시 자동 재로드 (_load_hub_setting 패턴).
"""

import json
import os

DEFAULT_LANG = "en"
SUPPORTED = ("en", "ko")

# data/locales/ 경로 — 이 파일(services/hub/i18n.py) 기준 REPO_ROOT/data/locales.
_LOCALES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "locales")

# 언어별 catalog 캐시: {lang: {key: str}}, 파일 mtime 캐시.
_catalog_cache: dict = {}
_catalog_mtime: dict = {}


def _load_lang(lang: str) -> dict:
    """data/locales/<lang>.json 로드 (mtime 캐시). 파일 부재·파싱 실패 → 빈 dict."""
    path = os.path.join(_LOCALES_DIR, f"{lang}.json")
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return {}
    if _catalog_mtime.get(lang) == mtime and lang in _catalog_cache:
        return _catalog_cache[lang]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        return _catalog_cache.get(lang, {})
    _catalog_cache[lang] = data
    _catalog_mtime[lang] = mtime
    return data


def norm_lang(lang) -> str:
    """지원 언어로 정규화. 미지원·빈 값 → DEFAULT_LANG."""
    if isinstance(lang, str) and lang in SUPPORTED:
        return lang
    return DEFAULT_LANG


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """key 를 lang 언어 문자열로 변환.
    누락 시 en fallback, en 도 없으면 key 자체 반환(누락 가시화)."""
    val = _load_lang(lang).get(key)
    if val:
        return val
    if lang != DEFAULT_LANG:
        val = _load_lang(DEFAULT_LANG).get(key)
        if val:
            return val
    return key


def merged(lang: str) -> dict:
    """lang 사전을 en(base) 위에 덮어쓴 완전 dict 반환.
    클라이언트 JS i18n(`/api/i18n`·HUB_HTML 인라인 주입)용 — 미번역 키도 en 값으로 채워져 빈칸 없음."""
    out = dict(_load_lang(DEFAULT_LANG))
    if lang != DEFAULT_LANG:
        out.update({k: v for k, v in _load_lang(lang).items() if v})
    return out
