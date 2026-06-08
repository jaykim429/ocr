"""1단계: 인허가 적합성 검토.

  1) 식약처 식품안전나라 인허가 DB(I2500)에 해당 영업자가 실제로 존재하는지 확인
  2) 인허가서류(품목제조보고서 등)의 영업자명·주소가 표시사항에 동일하게 담겨있는지 대조

최종 적합성 '판단'은 Gemma 가 수행하며, 파이썬은 API 조회·근거 구성만 담당한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from PIL import Image

from chandra.foodsafety import LicenseRecord, search_license
from chandra.gemma_judge import judge_json


_LABEL_VERIFY_SYSTEM = """이미지에 특정 문자열이 표기되어 있는지 확인하는 검증기입니다.
표시사항(식품 라벨) 이미지가 저해상도라 글자가 작아도, 주어진 기준 문자열이 그 위치에
적혀 있는지 사람이 보듯 대조해 판단하세요. 법인 표기((유)/유한회사)·띄어쓰기 차이는
같은 것으로 봅니다. 근거 없이 true 로 하지 말 것.

반드시 아래 JSON 만 출력:
{"name_present": true/false, "address_present": true/false,
 "name_seen": "이미지에서 읽은 제조사명", "address_seen": "이미지에서 읽은 소재지",
 "confidence": "high|medium|low"}"""


def verify_label_against_reference(
    images: list[Image.Image],
    ref_name: str | None,
    ref_address: str | None,
    **gemma_opts: Any,
) -> dict[str, Any]:
    """표시사항 이미지에 기준 영업자명/소재지가 기재돼 있는지 Gemma 비전으로 검증.

    저해상도 라벨에서 블라인드 OCR(추출)은 오인식이 잦지만, 기준값 존재 여부 '검증'은
    훨씬 정확하다. 인허가서류/DB의 신뢰값을 기준으로 사용한다.
    """
    if not images or (not ref_name and not ref_address):
        return {"error": "기준값 또는 이미지 없음"}
    user = (
        "이 표시사항(식품 라벨) 이미지를 보고 아래 기준이 기재되어 있는지 확인하세요.\n"
        f"- 제조사명(기준): {ref_name}\n- 소재지(기준): {ref_address}\n"
        "비슷하면(법인표기/띄어쓰기 차이 포함) present=true."
    )
    try:
        return judge_json(_LABEL_VERIFY_SYSTEM, user, images=images, **gemma_opts)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@dataclass
class LicenseCheckInput:
    # 인허가서류/품목제조보고서에서 추출
    business_name: str | None = None
    license_no: str | None = None  # 영업등록번호
    address: str | None = None
    representative: str | None = None
    # 표시사항에서 추출 (대조 대상; 대표 1건)
    label_business_name: str | None = None
    label_address: str | None = None
    # 표시사항 이미지 비전 검증 결과 (저해상도 라벨 대조용, 블라인드 OCR보다 정확)
    label_verification: dict[str, Any] | None = None
    # 표시사항이 여러 개일 수 있음 — 각 라벨의 추출값/검증결과 목록
    labels: list[dict[str, Any]] = field(default_factory=list)
    # 제출된 제조사 인허가 서류(사업자등록증/영업등록증/공장등록증명서) — 제조사명·주소 교차대조용
    permit_docs: list[dict[str, Any]] = field(default_factory=list)


_LICENSE_JUDGE_SYSTEM = """당신은 식품 인허가 서류 적합성 검토 전문가입니다.
다음 두 가지를 판단합니다.
1) 영업자가 식약처 식품안전나라 인허가 DB 에 실제로 존재하는가
   - 영업등록번호(license_no)가 일치하면 가장 강한 근거.
   - 업소명/주소가 일치해도 됨. (대표자명은 DB 에서 마스킹되어 있으니 불일치로 보지 말 것)
2) 인허가서류의 영업자명·주소가 표시사항에 동일하게 기재되어 있는가
   - 법인 표기(유한회사/(유) 등) 차이나 띄어쓰기 차이는 동일한 것으로 본다.
   - 주소는 핵심 행정구역·도로명·번지가 일치하면 동일한 것으로 본다.
   - 표시사항은 저해상도라 블라인드 OCR(label 제조사명/소재지)이 오인식될 수 있다.
     '표시사항_검증'(이미지 비전 검증) 결과가 있으면 그것을 우선한다:
     name_present/address_present=true 이면 표시사항에 기재된 것으로 인정한다.
   - 단, 표시사항에는 제조원(영업자) 대신 브랜드명·상표·유통판매원명이 크게 표기되는 경우가
     많다(예: 영업자 '설성푸드'인데 라벨에는 'WALKERHILL GOURMET'). name_seen 이 영업자명이
     아니라 브랜드/영문 상표로 보이면, 이는 '영업자명 불일치'가 아니라 제조원이 작은 글씨로
     별도 표기됐거나 검증이 브랜드를 읽은 것일 수 있다.
   - 표시사항_목록(표시사항이 여러 개)이 있으면 각 라벨을 개별 검토한다. 영업자/소재지가
     어느 표시사항에든 기재돼 있으면(present=true) 기재된 것으로 인정하고, 표시사항별 결과를
     reasons 에 적는다(예: '표시사항1 일치, 표시사항2 제조원 미표기 — 확인 필요').

종합 판정 원칙:
- 영업등록번호가 DB와 일치(exists_in_db=true, db_match_basis=license_no)하면 영업자 존재가
  확정된 것이다. 이때 다음은 '부적합'으로 단정하지 말고 '검토필요'로 두고 사유를 reason 에 적는다:
  · 표시사항 영업자명이 브랜드/상표로 보여 영업자명과 다른 경우(브랜드≠제조원 가능성)
  · 표시사항의 제조사명/소재지가 null(라벨 저해상·미판독으로 추출 실패)인 경우
    → 이는 '불일치'가 아니라 '표시사항 확인 불가'다. 라벨 재확인 필요로만 표시한다.
- 주소 핵심 행정구역까지 일치하면 일치 근거로 본다.
- 영업자 존재가 확인되지 않거나(번호·업소명·주소 모두 불일치/누락) 명백히 다른 영업자면 부적합.
- ★제출_인허가서류(사업자등록증·영업등록증·공장등록증명서)가 있으면 제조사명·주소를 교차대조한다:
  · 제조사명(상호/법인명/영업소명칭/회사명)이 서류들·DB·표시사항에서 동일 영업자로 일치하는지 본다
    (법인표기·띄어쓰기·OCR 차이는 동일). 명백히 다른 회사면 검토필요/부적합.
  · 주소: '영업등록증·공장등록증명서의 소재지(=제조소)'를 표시사항 제조소 주소·DB 주소와 대조한다.
    단, '사업자등록증' 주소는 본점/사업장이라 제조소(공장)와 다를 수 있으므로 불일치해도 흠이 아니다
    (참고로만). 제조소 주소끼리 핵심 행정구역·번지가 일치하면 적합.
  · reasons 에 어느 서류가 제출됐고 무엇이 일치/불일치하는지 적는다.

반드시 아래 JSON 만 출력(설명 금지):
{
  "exists_in_db": true,
  "db_match_basis": "license_no|business_name|address|none",
  "label_matches_license_doc": true,
  "name_match": true,
  "address_match": true,
  "overall_verdict": "적합|부적합|검토필요",
  "reasons": ["근거"]
}"""


@dataclass
class LicenseCheckResult:
    evidence: dict[str, Any]
    verdict: dict[str, Any]
    db_records: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _record_matches_license_no(records: list[LicenseRecord], license_no: str | None):
    if not license_no:
        return None
    for rec in records:
        if rec.license_no and str(rec.license_no) == str(license_no):
            return rec
    return None


def check_license(
    data: LicenseCheckInput,
    **gemma_opts: Any,
) -> LicenseCheckResult:
    """1단계 인허가 적합성 검토."""
    # 1) API 조회: 영업등록번호 우선, 없으면 업소명
    records: list[LicenseRecord] = []
    api_error: str | None = None
    try:
        if data.license_no:
            records = search_license(license_no=data.license_no)
        if not records and data.business_name:
            records = search_license(business_name=data.business_name)
    except Exception as exc:  # noqa: BLE001
        api_error = str(exc)

    exact = _record_matches_license_no(records, data.license_no)

    # 주소 대조(도로명↔지번/약칭/OCR 노이즈 흡수): 인허가서류 vs DB, vs 표시사항
    from chandra.address import verify_addresses

    db_addr = (exact.address if exact else (records[0].address if records else None))
    addr_vs_db = verify_addresses(data.address, db_addr).to_dict() if data.address else None
    addr_vs_label = (
        verify_addresses(data.address, data.label_address).to_dict()
        if data.address and data.label_address
        else None
    )

    evidence = {
        "인허가서류": {
            "영업자명": data.business_name,
            "영업등록번호": data.license_no,
            "주소": data.address,
            "대표자": data.representative,
        },
        "표시사항": {
            "제조사명": data.label_business_name,
            "소재지": data.label_address,
        },
        "표시사항_검증": data.label_verification,
        "표시사항_목록": data.labels,  # 표시사항이 여러 개면 각 라벨의 추출값+이미지검증 결과
        "제출_인허가서류": data.permit_docs,  # 사업자등록증/영업등록증/공장등록증명서
        "안전나라_DB_조회결과": [r.to_dict() for r in records[:10]],
        "영업등록번호_정확매칭": exact.to_dict() if exact else None,
        "주소_대조": {"인허가서류_vs_DB": addr_vs_db, "인허가서류_vs_표시사항": addr_vs_label},
        "api_error": api_error,
    }

    user_text = (
        "다음 근거로 인허가 적합성을 판단하세요.\n\n"
        + json.dumps(evidence, ensure_ascii=False, indent=2)
    )
    try:
        verdict = judge_json(_LICENSE_JUDGE_SYSTEM, user_text, **gemma_opts)
    except Exception as exc:  # noqa: BLE001
        verdict = {"overall_verdict": "검토필요", "reasons": [f"Gemma 판정 실패: {exc}"]}

    return LicenseCheckResult(
        evidence=evidence,
        verdict=verdict,
        db_records=[r.to_dict() for r in records],
        error=api_error,
    )
