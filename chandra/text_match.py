"""문자열 정규화·매칭 공용 유틸.

여러 모듈(test_agencies, self_quality, nutrition, extraction)에 흩어져 있던 동일한
정규화/퍼지 로직을 한 곳으로 모은다. 도메인 특화 정규화(주소 시도 약칭 등)는 각 모듈에 둔다.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# 법인 표기 마커 (이름 비교 전 제거) — 각 모듈에서 쓰던 표기들의 합집합
_ENTITY_RE = re.compile(
    r"(주식회사|유한회사|유한책임회사|합자회사|합명회사|\(주\)|\(유\)|㈜|주\)|유\))"
)


def collapse(text: str | None) -> str:
    """공백 제거 + 소문자화."""
    return "".join((text or "").split()).lower()


def strip_entity(text: str | None) -> str:
    """법인 표기 제거 후 collapse (업체/기관명 비교용)."""
    return collapse(_ENTITY_RE.sub("", text or ""))


def digits(text: str | None) -> str:
    """숫자만 추출 (전화번호 등 OCR 강건 비교용)."""
    return "".join(ch for ch in str(text or "") if ch.isdigit())


def ratio(a: str, b: str) -> float:
    """두 문자열의 유사도(0~1)."""
    return SequenceMatcher(None, a, b).ratio()


def best_window_ratio(needle: str, haystack: str) -> float:
    """needle 길이 창을 haystack 위로 슬라이딩하며 최대 유사도를 구한다."""
    if not needle or not haystack:
        return 0.0
    w = len(needle)
    if w >= len(haystack):
        return ratio(needle, haystack)
    return max(ratio(needle, haystack[i : i + w]) for i in range(len(haystack) - w + 1))
