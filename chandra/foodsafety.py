"""식품안전나라(식약처) 오픈API 클라이언트.

현재 발급 키는 인허가 업소 정보(I2500)에 인가되어 있다.
  http://openapi.foodsafetykorea.go.kr/api/{KEY}/{SERVICE}/json/{start}/{end}/{COND}
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from chandra.settings import settings


@dataclass
class LicenseRecord:
    business_name: str | None  # BSSH_NM 업소명
    representative: str | None  # PRSDNT_NM 대표자(마스킹)
    industry: str | None  # INDUTY_CD_NM 업종
    license_no: str | None  # LCNS_NO 인허가/영업등록번호
    permit_date: str | None  # PRMS_DT 허가일
    address: str | None  # ADDR 소재지
    tel: str | None  # TELNO

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _request(service: str, start: int, end: int, cond: str = "") -> dict[str, Any]:
    base = settings.FOODSAFETY_API_BASE.rstrip("/")
    key = settings.FOODSAFETY_API_KEY
    url = f"{base}/{key}/{service}/json/{start}/{end}"
    if cond:
        url += "/" + cond
    # 식품안전나라 API 는 동시·연속 호출 시 간헐적으로 타임아웃/HTML(비정상) 응답을 준다.
    # 영업등록번호 조회 등 핵심 호출이 일시적 오류로 '없음' 처리되지 않도록 짧게 재시도한다.
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=settings.FOODSAFETY_TIMEOUT_SECONDS) as r:
                text = r.read().decode("utf-8")
            if text.lstrip().startswith("<"):
                raise RuntimeError("API 인증 실패 또는 비정상 응답 (인증키/서비스 권한 확인)")
            return json.loads(text)
        except Exception as exc:  # noqa: BLE001 - 타임아웃/비정상응답 재시도
            last = exc
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))
    raise last  # type: ignore[misc]


def _rows_to_records(body: dict[str, Any]) -> list[LicenseRecord]:
    records = []
    for row in body.get("row", []) or []:
        records.append(
            LicenseRecord(
                business_name=row.get("BSSH_NM"),
                representative=row.get("PRSDNT_NM"),
                industry=row.get("INDUTY_CD_NM"),
                license_no=row.get("LCNS_NO"),
                permit_date=row.get("PRMS_DT"),
                address=row.get("ADDR"),
                tel=row.get("TELNO"),
            )
        )
    return records


from functools import lru_cache


@lru_cache(maxsize=256)
def search_food_spec(product_type: str, max_rows: int = 100) -> list[dict[str, Any]]:
    """식품공전(I0930) 품목명(식품유형)으로 시험항목·기준규격 조회.

    자가품질 성적서 결과를 식품공전 규격과 대조·인용하는 근거로 쓴다.
    동일 식품유형 반복조회는 캐시로 즉시 반환(속도). 반환: [{item, sub_item, spec, unit, ...}].
    """
    if not product_type:
        return []

    def _query(name: str) -> dict[str, Any]:
        cond = "PRDLST_NM=" + urllib.parse.quote(name)
        return _request("I0930", 1, max_rows, cond).get("I0930", {})

    body = _query(product_type)
    # 0건이면 공백 유무 변형으로 재시도(예: '기타수산물가공품' ↔ '기타 수산물가공품')
    if not (body.get("row") or []):
        alt = product_type.replace(" ", "") if " " in product_type else None
        if alt and alt != product_type:
            body = _query(alt)
    out = []
    for r in body.get("row", []) or []:
        out.append({
            "product_type": r.get("PRDLST_NM"),
            "item": r.get("T_KOR_NM"),          # 시험항목
            "sub_item": r.get("FNPRT_ITM_NM"),  # 세부항목
            "spec": r.get("SPEC_VAL_SUMUP") or r.get("SPEC_VAL"),  # 규격요약
            "unit": r.get("UNIT_NM"),
            "judge_type": r.get("JDGMNT_FNPRT_CD_NM"),
            "max": r.get("MXMM_VAL"),
            "min": r.get("MIMM_VAL"),
        })
    return out


# 시·도 약칭↔정식명(특별자치도 개편 포함) — 소재지 필터가 둘 다 인식하도록
_REGION_FORMS = {
    "서울": ["서울특별시", "서울"],
    "부산": ["부산광역시", "부산"],
    "대구": ["대구광역시", "대구"],
    "인천": ["인천광역시", "인천"],
    "광주": ["광주광역시", "광주"],
    "대전": ["대전광역시", "대전"],
    "울산": ["울산광역시", "울산"],
    "세종": ["세종특별자치시", "세종"],
    "경기": ["경기도", "경기"],
    "강원": ["강원특별자치도", "강원도", "강원"],
    "충북": ["충청북도", "충북"],
    "충남": ["충청남도", "충남"],
    "전북": ["전북특별자치도", "전라북도", "전북"],
    "전남": ["전라남도", "전남"],
    "경북": ["경상북도", "경북"],
    "경남": ["경상남도", "경남"],
    "제주": ["제주특별자치도", "제주도", "제주"],
}


def _address_matches(query: str, addr: str | None) -> bool:
    """소재지 필터 매칭. 시·도 단독 입력이면 약칭/정식명/특별자치도 변형을 모두 인정,
    그 외에는 공백 무시 부분일치."""
    if not addr:
        return False
    q = query.strip()
    # 입력이 어떤 시·도(약칭 또는 정식명)에 해당하면 그 시·도의 모든 표기형으로 매칭
    for forms in _REGION_FORMS.values():
        if q in forms:
            return any(addr.startswith(f) for f in forms)
    return q.replace(" ", "") in addr.replace(" ", "")


def search_license(
    business_name: str | None = None,
    license_no: str | None = None,
    industry: str | None = None,
    address: str | None = None,
    max_rows: int = 100,
) -> list[LicenseRecord]:
    """인허가 업소 정보(I2500) 검색. 업소명·영업등록번호·업종·소재지 조건 조합.

    주의: I2500 은 조건 두 개를 줘도 AND 로 묶지 않고 첫 조건만 적용한다
    (예: BSSH_NM=알찬푸드&ADDR=대구 → ADDR 무시, 전 지역 반환).
    따라서 가장 선택적인 조건 하나만 API 에 보내고 나머지는 파이썬에서 후처리 필터링한다.
    """
    service = settings.FOODSAFETY_LICENSE_SERVICE
    # 우선순위: 영업등록번호 > 업소명 > 업종 > 소재지
    if license_no:
        cond = "LCNS_NO=" + urllib.parse.quote(str(license_no))
    elif business_name:
        cond = "BSSH_NM=" + urllib.parse.quote(business_name)
    elif industry:
        cond = "INDUTY_CD_NM=" + urllib.parse.quote(industry)
    elif address:
        cond = "ADDR=" + urllib.parse.quote(address)
    else:
        return []
    body = _request(service, 1, max_rows, cond).get(service, {})
    records = _rows_to_records(body)

    # 나머지 조건은 API 가 무시하므로 결과에서 직접 걸러낸다
    def keep(r: LicenseRecord) -> bool:
        if business_name and business_name.replace(" ", "") not in (r.business_name or "").replace(" ", ""):
            return False
        if industry and industry.replace(" ", "") not in (r.industry or "").replace(" ", ""):
            return False
        if address and not _address_matches(address, r.address):
            return False
        return True

    return [r for r in records if keep(r)]
