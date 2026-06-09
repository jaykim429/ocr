"""표시사항(한글표시사항) 표시항목 검토.

「식품등의 표시기준」및「전자상거래 등에서의 상품 등의 정보제공에 관한 고시」에 따른
의무 표시항목(부정·불량식품 신고, 알레르기 유발물질, 소비기한, 영업소 명칭·소재지,
품목보고번호, 원재료명, 내용량, 보관방법, 주의사항 등)이 라벨에 기재되어 있는지
라벨 OCR 텍스트를 근거로 Gemma 가 판정한다.

참고: 전자상거래 고시의 상품군별 세부 필수항목 별표는 이미지로 제공되어 직접 파싱이 어려우므로,
식품 표시사항의 표준 의무항목을 기준으로 검토한다(추후 별표 이미지를 VLM 으로 렌더해 세분화 가능).
판정값 산출은 Gemma 가 수행한다(자가 규칙엔진 아님).
"""

from __future__ import annotations

from typing import Any

from chandra.gemma_judge import judge_json

_LABEL_CHECK_SYSTEM = """당신은 식품 표시사항(한글표시사항) 검토 전문가입니다.
「전자상거래 등에서의 상품 등의 정보제공에 관한 고시」[별표]의 상품군별 표시사항과
「식품등의 표시기준」에 따라, 라벨에 의무 표시항목이 기재되어 있는지 라벨 텍스트로 점검합니다.

[가공식품] 의무 표시항목(전자상거래 정보제공 고시 별표 — 식품):
 1-1 제품명
 1-2 식품유형
 1-3 생산자(영업소)의 명칭·소재지 (수입품은 생산자/수입자/제조국)
 1-4 제조연월일 / 소비기한(또는 품질유지기한)
 1-5 포장단위별 내용물의 용량(중량)·수량
 1-6 원재료명(「농수산물의 원산지 표시」에 따른 원산지 포함) 및 함량(함량표시 대상)
 1-7 영양성분 (영양표시 대상 식품에 한함)
 1-8 유전자변형식품 표시 (해당 경우)
 1-9 소비자 안전을 위한 주의사항(표시·광고법 시행규칙 제5조 [별표2]) — 다음 포함:
     · 알레르기 유발물질 표시(원재료에 함유 시): 알류(가금류), 우유, 메밀, 땅콩, 대두, 밀,
       고등어, 게, 새우, 돼지고기, 복숭아, 토마토, 아황산류, 호두, 닭고기, 쇠고기, 오징어,
       조개류(굴·전복·홍합 포함), 잣
     · 부정·불량식품 신고 안내("국번없이 1399")
     · 기타 품목별 주의·경고 문구
 2  (수입식품) "수입식품안전관리 특별법에 따른 수입신고를 필함" 문구
 3  소비자 상담 관련 전화번호

[건강기능식품] 의무 표시항목(고시 별표 — 건강기능식품):
 제품명, 제조업소 명칭·소재지, 소비기한·보관방법, 포장단위 내용물 용량(중량)·수량,
 원재료명·함량, 영양정보, 기능정보, 섭취량·섭취방법·섭취 시 주의사항·부작용 가능성,
 "질병의 예방·치료를 위한 의약품이 아니라는 내용의 표현", 소비자 안전 주의사항,
 (수입) 수입신고 문구, 소비자 상담 전화번호.

판정 원칙:
- 라벨 이미지가 함께 제공되면 이미지를 우선 근거로 삼는다(OCR 텍스트는 보조). 이미지에서 직접
  읽히는 값(예: 내용량 '200 g')이 OCR 텍스트('240-' 등)와 다르면 이미지 값을 신뢰한다.
- 식품유형/상품군에 맞는 별표 항목으로 점검한다. 각 항목 기재 시 verdict="적합", 누락이면 "검토필요".
- ★표시사항은 '시안(인쇄 전 도안)'인 경우가 많다. 제조연월일·소비기한 칸이 'YYYY.MM.DD', 'yy-mm-dd',
  'Vvvv-vv-vv', '____', '○○○○.○○.○○' 같은 서식 자리표시(placeholder)이면 누락이 아니라
  '표기 위치 확보(실제 날짜는 제조 시 인쇄)'로 보고 verdict="적합"으로 둔다. 깨진 OCR과 혼동하지 말 것.
- 알레르기: 원재료명에 위 유발물질이 보이는데 알레르기 표시가 없으면 "검토필요"로 강하게 표시.
  원재료에 해당 물질이 없으면 알레르기 항목은 "적합"(해당없음).
- 영양성분·유전자변형 등 '해당 시' 항목은 대상이 아니면 "적합"(해당없음)으로 둔다.
- 라벨 OCR 이 불완전할 수 있으니 단정적 부적합보다 '검토필요'로 안내한다. 단, 이미지로 값이
  명확히 확인되면 그 값으로 '적합' 처리하고 'OCR 판독 불가'를 사유로 들지 않는다.
- ★표시 근거자료: 라벨에 기능성·효능 표현('뼈 건강', '○○에 도움' 등)이나 인증마크(HACCP·유기농·
  전통식품 등)가 있으면 items 에 name='표시 근거자료 확인'(verdict='검토필요')로 '기능성/인증 표현
  발견 — 근거자료 확인 필요'를 적는다. (특허번호 표기의 근거자료 제출·일치 여부는 시스템 교차대조가
  별도로 판정하므로, 특허번호만 있는 경우는 여기서 중복 보고하지 않는다.)
- 누락 의무항목이 하나라도 있으면 overall_verdict 는 '검토필요'(명백 누락이면 '부적합').

반드시 아래 JSON 만 출력(설명 금지):
{
  "items": [{"name": "표시항목", "verdict": "적합|검토필요|부적합", "reason": "근거(기재 위치/문구 또는 누락)"}],
  "allergens_in_ingredients": ["원재료에서 발견된 알레르기 유발물질"],
  "missing_required_items": ["누락된 의무 표시항목"],
  "overall_verdict": "적합|검토필요|부적합",
  "reasons": ["종합 사유"]
}"""


def review_label_disclosures(
    label: dict[str, Any] | None,
    food_type: str | None = None,
    official_address: str | None = None,
    official_ocr: str | None = None,
    **gemma_opts: Any,
) -> dict[str, Any]:
    """표시사항 의무 표시항목 충족 여부를 Gemma 로 판정한다.

    label: 한글표시사항 추출 dict(_ocr_text 포함). official_address: 품목제조보고서/인허가의
    공식 소재지(라벨 이미지와 대조용). 반환: {evidence, verdict, error}.
    """
    if not label:
        return {"status": "건너뜀 (표시사항 없음)"}
    ocr = label.get("_ocr_text") or ""
    fields = {
        "제품명": label.get("product_name"),
        "식품유형": food_type or label.get("food_type"),
        "영업자": label.get("business_name"),
        "소재지": label.get("address"),
        "품목보고번호": label.get("manufacture_report_no"),
    }
    evidence = {"식품유형": fields["식품유형"], "표시사항_추출필드": fields, "표시사항_텍스트": ocr[:9000],
                "공식_소재지(대조기준)": official_address}
    addr_check = (
        "\n\n[소재지 대조] 공식 소재지(품목제조보고서/인허가)는 "
        f"'{official_address}' 입니다. 라벨 '이미지'에서 인쇄된 생산자(영업소) 소재지를 직접 읽어 "
        "이 공식 소재지와 글자 단위로 대조하세요. 시·도 약칭(충북=충청북도)·괄호 건물명·우편번호 "
        "차이는 동일로 봅니다. 읍/면/동·리·도로명·번지가 다르면 '소재지 표시 확인 필요'로 보고하되, "
        "★중요: 저화질 스캔에서는 VLM 자신도 한글 1~2글자를 오독할 수 있으므로(예: 삼향↔삼항, "
        "송악↔승악) 그 차이가 'OCR 오인식'인지 '실제 표시 오기'인지 단정하지 마세요. reason 에는 "
        "'무엇이 다른지(예: 번지 56-3↔56-30)'와 '원본 이미지로 확인 필요'만 중립적으로 적습니다. "
        "다만 라벨 글자가 또렷하게 읽혀 명백히 다른 주소인 경우에 한해 그 사실을 적시할 수 있습니다."
        if official_address else ""
    )
    if official_ocr and official_address:
        # 공식 소재지 추출값이 보고서 작은 글씨를 오독했을 수 있으므로, 보고서 OCR 원문을
        # 권위 기준으로 함께 제공한다(추출 주소와 OCR이 다르면 OCR 신뢰 — 거짓 불일치 방지).
        addr_check += (
            "\n[공식 소재지 OCR 원문(권위 — 추출 주소와 다르면 이 원문을 신뢰)]\n"
            + official_ocr[:2000]
        )
    # 감시목록 고시 → 자동연결: 제품 속성(원재료·포장재·인증마크·식품유형)에 해당하는
    # 표시의무 요지만 골라 '적용 법령 근거'로 주입한다(판정은 Gemma 수행).
    from chandra.law_rules import applicable_rules, rules_to_block

    law_text = f"{fields}\n{ocr}"
    applied = applicable_rules(fields["식품유형"], law_text)  # 1회 평가 후 재사용
    # 적용 법령 근거(자동연결 고시) — 프런트 칩 클릭 시 법령 탭에서 본문 열람(kind=admrul 고시).
    evidence["적용_법령근거"] = [{"name": r["name"], "basis": r.get("basis") or r["name"], "kind": "admrul"} for r in applied]
    user = (
        "다음 표시사항(라벨)을 보고 의무 표시항목 충족 여부를 점검하세요. 라벨 이미지가 있으면 "
        "이미지를 우선 근거로 삼고, OCR 텍스트는 보조로만 활용하세요.\n\n"
        f"추출필드: {fields}\n\n표시사항 텍스트(OCR):\n{ocr[:9000]}" + addr_check
        + rules_to_block(applied)
    )
    # 선명한 시안 라벨은 OCR 보다 이미지(VLM) 판독이 정확하므로 라벨 이미지를 함께 전달한다.
    images = None
    if label.get("file"):
        try:
            from chandra.extraction import render_file

            images = list(render_file(label["file"], max_pages=1, target_long_side=2400))
        except Exception:  # noqa: BLE001
            images = None
    try:
        verdict = judge_json(_LABEL_CHECK_SYSTEM, user, images=images, **gemma_opts)
        return {"evidence": evidence, "verdict": verdict, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {
            "evidence": evidence,
            "verdict": {"overall_verdict": "검토필요", "reasons": [f"표시사항 판정 실패: {exc}"]},
            "error": str(exc),
        }
