"""주소 정규화 및 일치 검증.

같은 장소라도 서류마다 도로명주소(예: '전남 무안군 삼향읍 삼향공단길 56-30')와
지번주소(예: '전남 무안군 삼향읍 ○○리 123-4')로 다르게 적힐 수 있고, OCR 오인식
(삼향↔삼황)·시도 약칭(전라남도↔전남) 차이도 흔하다.

- 오프라인: 시도 약칭 통일 + 괄호/공백 정리 후 토큰 겹침·퍼지 유사도로 비교한다.
  (같은 형식의 OCR 노이즈·약칭 차이는 잡지만, 도로명↔지번 변환은 못 한다.)
- 선택: juso.go.kr 도로명주소 OpenAPI(JUSO_API_KEY 설정 시)로 도로명·지번을 함께 받아
  정규화 비교한다. postcodify(대용량 DB)를 대체하는 경량 방식.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from chandra.settings import settings

# 시도 정식명 ↔ 약칭 통일 (약칭으로 정규화)
_SIDO = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구",
    "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
    "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원",
    "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
    "전라북도": "전북", "전라남도": "전남", "경상북도": "경북",
    "경상남도": "경남", "제주특별자치도": "제주", "제주도": "제주",
}


def normalize_address(addr: str | None) -> str:
    """비교용 정규화: 괄호 내용·우편번호·전화 제거, 시도 약칭 통일, 공백 제거."""
    if not addr:
        return ""
    s = str(addr)
    s = re.sub(r"\([^)]*\)", " ", s)  # (동, 건물명) 제거
    s = re.sub(r"\(\d{5}\)|\b\d{5}\b", " ", s)  # 우편번호
    s = re.sub(r"☎[^\s]*|fax[^\s]*|T\d[\d\-]*|F\d[\d\-]*", " ", s, flags=re.I)
    for full, short in _SIDO.items():
        s = s.replace(full, short)
    return re.sub(r"\s+", "", s).lower()


def _tokens(addr: str | None) -> list[str]:
    if not addr:
        return []
    s = re.sub(r"\([^)]*\)", " ", str(addr))
    for full, short in _SIDO.items():
        s = s.replace(full, short)
    return [t for t in re.split(r"[\s,]+", s) if t]


@dataclass
class AddressMatch:
    a: str | None
    b: str | None
    match: bool
    score: float
    basis: str  # exact | contains | token | fuzzy | juso | mismatch

    def to_dict(self) -> dict[str, Any]:
        return {"a": self.a, "b": self.b, "match": self.match, "score": round(self.score, 3), "basis": self.basis}


def addresses_match(a: str | None, b: str | None, threshold: float = 0.72) -> AddressMatch:
    """주소 두 개가 같은 곳을 가리키는지(오프라인) 판단."""
    if not a or not b:
        return AddressMatch(a, b, False, 0.0, "mismatch")
    na, nb = normalize_address(a), normalize_address(b)
    if not na or not nb:
        return AddressMatch(a, b, False, 0.0, "mismatch")
    if na == nb:
        return AddressMatch(a, b, True, 1.0, "exact")
    if na in nb or nb in na:
        return AddressMatch(a, b, True, 0.95, "contains")
    # 핵심 토큰(시군구/도로명·동/번지) 겹침
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if ta and tb:
        overlap = len(ta & tb) / max(len(ta), len(tb))
        if overlap >= 0.6:
            return AddressMatch(a, b, True, overlap, "token")
    ratio = SequenceMatcher(None, na, nb).ratio()
    if ratio >= threshold:
        return AddressMatch(a, b, True, ratio, "fuzzy")
    return AddressMatch(a, b, False, ratio, "mismatch")


# ---------------------------------------------------------------------------
# 선택: juso.go.kr 도로명주소 OpenAPI (도로명↔지번 정규화)
# ---------------------------------------------------------------------------


def juso_search(keyword: str) -> dict[str, Any] | None:
    """도로명주소 API로 주소 검색. JUSO_API_KEY 미설정/실패 시 None.

    반환(첫 결과): {roadAddr, jibunAddr, zipNo, ...}
    """
    key = getattr(settings, "JUSO_API_KEY", "") or ""
    if not key or not keyword:
        return None
    params = urllib.parse.urlencode(
        {"confmKey": key, "currentPage": 1, "countPerPage": 1, "keyword": keyword, "resultType": "json"}
    )
    url = f"https://www.juso.go.kr/addrlink/addrLinkApi.do?{params}"
    try:
        with urllib.request.urlopen(url, timeout=getattr(settings, "FOODSAFETY_TIMEOUT_SECONDS", 20.0)) as r:
            data = json.loads(r.read().decode("utf-8"))
        jusos = data.get("results", {}).get("juso") or []
        return jusos[0] if jusos else None
    except Exception:  # noqa: BLE001
        return None


def addresses_match_via_juso(a: str | None, b: str | None) -> AddressMatch | None:
    """juso API로 두 주소를 정규화(도로명 기준)해 비교. 키 없으면 None."""
    if not a or not b:
        return None
    ra, rb = juso_search(a), juso_search(b)
    if not ra or not rb:
        return None
    road_a = normalize_address(ra.get("roadAddr"))
    road_b = normalize_address(rb.get("roadAddr"))
    if road_a and road_a == road_b:
        return AddressMatch(a, b, True, 1.0, "juso")
    # 도로명이 달라도 지번이 같으면 같은 곳
    jib_a = normalize_address(ra.get("jibunAddr"))
    jib_b = normalize_address(rb.get("jibunAddr"))
    if jib_a and jib_a == jib_b:
        return AddressMatch(a, b, True, 1.0, "juso")
    return AddressMatch(a, b, False, 0.0, "juso")


def verify_addresses(a: str | None, b: str | None) -> AddressMatch:
    """juso API 가능하면 우선 사용, 아니면 오프라인 매칭."""
    via = addresses_match_via_juso(a, b)
    return via if via is not None else addresses_match(a, b)


def label_address_discrepancy(
    label_addr: str | None, official_addr: str | None
) -> dict[str, Any] | None:
    """표시사항(라벨) 주소가 공식 주소(품목제조보고서/인허가)와 '정확히' 일치하는지 본다.

    라벨 주소는 소비자에게 인쇄되는 정보이므로, 시도 약칭·괄호·우편번호·공백 차이를 정리한
    뒤에도 행정구역/도로명/번지 토큰이 다르면(예: '내수읍'↔'수내읍') 단순 일치로 넘기지 않고
    검토 대상으로 반환한다. 차이가 없으면(또는 한쪽이 다른쪽을 포함하면) None.
    """
    if not label_addr or not official_addr:
        return None
    na, nb = normalize_address(label_addr), normalize_address(official_addr)
    if not na or not nb or na == nb or na in nb or nb in na:
        return None
    ta, tb = _tokens(label_addr), _tokens(official_addr)
    only_label = [t for t in ta if t not in tb]
    only_official = [t for t in tb if t not in ta]
    if not only_label and not only_official:
        return None
    detail = (
        "표시사항 주소가 공식(품목제조보고서) 주소와 다릅니다 — "
        f"표시사항 '{label_addr}' ↔ 공식 '{official_addr}'"
        + (f" (불일치 토큰: 표시사항={only_label} / 공식={only_official})" if (only_label or only_official) else "")
    )
    return {
        "label": label_addr,
        "official": official_addr,
        "label_only": only_label,
        "official_only": only_official,
        "detail": detail,
    }
