"""문서 판독·분류·필드추출 (Gemma 비전 모델 사용).

zip/폴더에서 나온 파일 각각을 이미지로 렌더한 뒤, Gemma 가 직접:
  1) 문서 종류(doc_type)를 분류하고
  2) 다운스트림 단계가 필요로 하는 핵심 필드를 구조화(JSON)해 반환한다.

로컬 chandra OCR 모델 없이도(또는 vLLM 미가동 환경에서도) Gemma 엔드포인트만으로
판독이 가능하도록 한 경로다.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import filetype
import pypdfium2 as pdfium
from PIL import Image

from chandra.gemma_judge import judge_json
from chandra.text_match import best_window_ratio

# 파일 내용 해시 기준 추출 캐시 — 동일 파일 재검토 시 Gemma 재호출 생략(속도).
# 추출 프롬프트가 바뀌면 키의 prompt 버전이 달라져 자동 무효화된다.
_EXT_CACHE = Path(__file__).with_name("data") / "extraction_cache"


def _norm_ko(text: str | None) -> str:
    """비교용 정규화: 법인표기·괄호·공백·기호 제거, 소문자."""
    if not text:
        return ""
    s = re.sub(r"\([^)]*\)|（[^）]*）", "", str(text))
    s = re.sub(r"(주식회사|유한회사|합자회사|\(주\)|\(유\)|㈜|주\)|유\))", "", s)
    return re.sub(r"[\s\W_]", "", s).lower()


def _supported_by_ocr(value: str | None, ocr_text: str, threshold: float = 0.6) -> bool:
    """추출값이 OCR 텍스트에 근거가 있는지 슬라이딩-윈도우 퍼지로 확인.

    OCR이 글자를 약간 오인식해도(푸↔꾸) 유사 윈도우가 있으면 근거 있음으로 본다.
    아예 흔적이 없는 환각(예: '남도식품')은 근거 없음으로 걸러진다.
    """
    nv = _norm_ko(value)
    if len(nv) < 2:
        return True  # 너무 짧으면 판단 보류(통과)
    no = _norm_ko(ocr_text)
    if not no:
        return True  # OCR 근거 없음 → 검증 불가, 통과
    if nv in no:
        return True
    return best_window_ratio(nv, no) >= threshold


# 환각 검증 대상 고유명사 필드.
# test_agency 는 제외 — 검사기관 DB(전화/지정번호/이름/퍼지)로 더 견고하게 검증되므로
# OCR 근거가 약해도 폐기하지 않고 DB 검증에 맡긴다.
_GROUNDED_FIELDS = ("business_name", "manufacturer", "product_name")
# product_name 은 제품 그룹핑의 핵심 키라 null 로 지우면 그룹핑이 깨진다.
# OCR 근거가 약해도 값은 유지하고 '저신뢰'로만 표시한다.
_GROUNDED_KEEP = ("product_name",)


def _drop_hallucinations(result: dict[str, Any], ocr_text: str) -> dict[str, Any]:
    """OCR 근거 없는 고유명사 값을 폐기(또는 저신뢰 표시)하고 내역을 기록한다."""
    if not ocr_text:
        return result
    dropped, low_conf = {}, []
    for field_name in _GROUNDED_FIELDS:
        val = result.get(field_name)
        if val and not _supported_by_ocr(str(val), ocr_text):
            if field_name in _GROUNDED_KEEP:
                low_conf.append(field_name)  # 그룹핑 키는 보존, 신뢰도만 낮춤
            else:
                dropped[field_name] = val
                result[field_name] = None
    if dropped:
        result["_dropped_hallucinations"] = dropped
    if low_conf:
        result["_low_confidence_fields"] = low_conf
    return result


# 분류 라벨 (파이프라인 라우팅 키)
DOC_PRODUCT_REPORT = "품목제조보고서"
DOC_SELF_QUALITY = "자가품질검사성적서"
DOC_LABEL = "한글표시사항"
DOC_NUTRITION_CERT = "영양성분성적서"
DOC_LICENSE = "영업허가신고증"
DOC_AD_REVIEW = "광고심의필증"
DOC_WEB_SPEC = "웹기술서"
DOC_EVIDENCE = "근거자료"  # 특허등록증·기능성 입증자료·인증서 등 표시 근거자료
DOC_UNKNOWN = "기타"

KNOWN_DOC_TYPES = [
    DOC_PRODUCT_REPORT,
    DOC_SELF_QUALITY,
    DOC_LABEL,
    DOC_NUTRITION_CERT,
    DOC_LICENSE,
    DOC_AD_REVIEW,
    DOC_WEB_SPEC,
    DOC_EVIDENCE,
    DOC_UNKNOWN,
]


_EXTRACTION_SYSTEM = f"""당신은 식품 인허가/품질 서류를 판독하는 OCR·정보추출 전문가입니다.
주어진 문서 이미지를 읽고 (1) 문서 종류를 분류하고 (2) 핵심 정보를 정확히 추출합니다.

문서 종류(doc_type)는 다음 중 하나로만 분류:
{", ".join(KNOWN_DOC_TYPES)}

추출 규칙:
- 이미지에 실제로 보이는 값만 추출합니다. 보이지 않으면 null.
- 날짜는 가능하면 YYYY-MM-DD 형식으로 정규화합니다.
- 시험·검사 결과의 숫자는 원문 그대로(쉼표 구분 목록 포함) 적습니다.
- ingredients = 원재료명 목록(품목제조보고서 배합비율 표 또는 표시사항 '원재료명' 칸의 원료들).
  식품첨가물(보존료·산화방지제·발색제·감미료 등)도 사용됐으면 포함. 사용 첨가물 판단에 쓰인다.
- nutrition_basis = 영양성분 표시의 '기준 단위'를 영양성분표 머리말에서 그대로 읽습니다.
  예: "100g당", "100mL당", "총 내용량(180mL)당", "1회 제공량(30g)당", "단위내용량당".
  영양성분 수치(nutrition)는 이 기준 단위에 대한 값입니다.
- 추측·창작 금지.
- test_agency = 성적서를 '발행한 시험·검사기관'(예: 주식회사 디아이분석센터). 의뢰자/제조원
  (예: 제품 영업자)과 혼동하지 말 것. 보통 성적서 상단 로고/발행기관 또는 하단 직인의 기관명.
- test_agency_designation_no = 그 검사기관의 식약처 지정번호(예: 식품 제099호).
- test_agency_tel / test_agency_address = 성적서 하단의 검사기관 전화번호/주소(있으면).
- test_purpose = 성적서의 '시험·검사목적' 칸 값(예: 자가품질위탁검사, 참고용, 수출용, 연구용).
  이 항목은 자가품질검사 성적서인지 단순 참고용인지 구분에 쓰이므로 보이는 그대로 적을 것.
- business_name = **제조원(제조사)** = 인허가 대상 영업자. 표시사항 정보표의 '제조원' 칸 값.
  ⚠️ 제품 **브랜드/상표명**(예: '자연을 두번 담다')·**제품명**(예: '마시는 하루견과')·
  **유통판매원/판매원**과 절대 혼동 금지. 큰 글씨 브랜드가 아니라 정보표의 '제조원'을 찾을 것.
- address = 제조원 소재지(제조원 칸의 주소). 유통판매원 주소와 구분.
- 품목제조보고서(별지 제43호서식)·변경보고서(별지 제45호서식)는 정부 표준서식이라 칸이 고정이다.
  아래 표준 칸을 그대로 읽는다(보고서/변경보고서에 있을 때):
    · shelf_life = '소비기한' 칸 값(예: '제조일로부터 8개월', '제조일로부터 24개월까지').
    · storage_method = '보관방법 및 포장재질'의 보관조건(예: '냉동(-18℃ 이하)', '실온보관', '냉장(0~10℃)').
    · package_unit = '포장방법 및 포장단위'의 단위/용량(예: '진공포장, 200g', '멸균팩 충전(180,190,200,1000mL)').
    · consignment = '위탁생산 여부'. 위탁이면 수탁 영업소 명칭(예: '○○식품'), 아니오/직접생산이면 null.
- food_type = 품목제조보고서의 '품목의 유형'(또는 '식품의 유형') 칸 값, 표시사항이면 '식품유형' 칸 값
  (예: 양념육, 소스, 떡류). ⚠️ 보고서의 '주원료의 유형(식육간편조리세트의 경우만 해당합니다)'은
  조건부 안내문구(보통 비어 있음)이니, 괄호 속 '식육간편조리세트' 문구를 품목 유형으로 착각하지 말 것.
  실제 '품목의 유형' 칸에 적힌 값을 읽을 것.
- distributor = 유통판매원/판매원(있으면). distributor_address = 그 주소.
- product_traits = 품목제조보고서의 '품목의 특성' 칸 체크 결과(보고서에 있을 때만). 각 항목에 √ 표시된
  값을 읽는다(판정에 쓰임). 안 보이거나 해당 서류가 아니면 각 값 null:
    · 살균구분 = '살균·멸균 제품 여부'의 √ → '비살균'|'살균'|'멸균' (멸균제품은 대장균군 검사 면제 등)
    · 영양성분표시의무 = '영양성분 표시의무 식품 여부' → true('예')|false('아니오')
    · 영유아용 = '영유아용 표시 판매 식품 여부' → true|false
    · 고령친화식품 = '고령친화식품 표시 판매 여부' → true|false
    · 기능성표시식품 = '기능성표시식품 여부' → true|false (true면 기능성 표시·근거자료 필요)
    · 고열량저영양식품 = '고열량·저영양 식품 여부' → true|false
- is_amendment / amendment_date / amendment_changes = 이 서류가 '품목제조보고사항 변경보고서'
  (변경 전/변경 후 칸이 있는 서류)이면 is_amendment=true, amendment_date=변경보고 날짜(YYYY-MM-DD),
  amendment_changes=실제로 바뀐 항목 목록(변경 전≠변경 후인 행: 예 '제품명','원재료명·배합비율',
  '소비기한'). 일반 품목제조보고서면 is_amendment=false. (doc_type 은 그대로 품목제조보고서)
- patent_no = 특허번호(숫자/문자열). 표시사항(라벨)에 '특허 제○○호'/'특허 1017597790000호'가 적혀
  있거나, 문서가 '특허등록증'·'근거자료'이면 그 등록번호를 적는다. 없으면 null.
- 문서가 특허등록증·기능성 입증자료·각종 인증서(원료 근거자료)이면 doc_type='근거자료'로 분류하고
  patent_no(있으면)와 notes(어떤 원료/표현의 근거인지)를 적는다.
- 중요: 업체명/기관명/주소가 확대 타일에서도 또렷하게 보이지 않으면 그럴듯한 이름을
  지어내지 말고 반드시 null 로 두세요. (추측은 거짓 불일치를 유발함)

**다제품(병합 PDF) 처리**: 한 파일에 서로 다른 제품(제품명·품목제조보고번호가 다른)이 여러 개
함께 들어 있을 수 있습니다(예: 성적서 2페이지=2제품, 품목제조보고서가 제품별로 이어 붙음,
표시사항 여러 면). 이 경우 제품별로 분리하여 products 배열에 각각 한 객체로 담으세요.
단일 제품이면 원소 1개입니다. 같은 제품의 여러 페이지(보고서 본문+원재료표+영양성분 등)는
하나의 객체로 합칩니다. 박스/외포장 디자인 면은 제품 객체로 만들지 마세요.

반드시 아래 JSON 만 출력(설명 금지):
{{
  "products": [
    {{
      "doc_type": "위 목록 중 하나",
      "product_name": null,
      "food_type": null,
      "manufacture_report_no": null,
      "business_name": null,
      "distributor": null,
      "distributor_address": null,
      "license_no": null,
      "address": null,
      "representative": null,
      "shelf_life": null,
      "storage_method": null,
      "package_unit": null,
      "consignment": null,
      "product_traits": {{"살균구분": null, "영양성분표시의무": null, "영유아용": null, "고령친화식품": null, "기능성표시식품": null, "고열량저영양식품": null}},
      "is_amendment": null,
      "amendment_date": null,
      "amendment_changes": [],
      "patent_no": null,
      "issue_date": null,
      "test_completed_date": null,
      "test_agency": null,
      "test_agency_designation_no": null,
      "test_agency_tel": null,
      "test_agency_address": null,
      "test_purpose": null,
      "ingredients": [],
      "test_items": [{{"name": "항목명", "criteria": "기준", "results": "결과", "judgement": "적합/부적합"}}],
      "nutrition_basis": null,
      "nutrition": {{"열량": null, "나트륨": null, "탄수화물": null, "당류": null, "지방": null, "트랜스지방": null, "포화지방": null, "콜레스테롤": null, "단백질": null}},
      "overall": null,
      "notes": null
    }}
  ]
}}"""


# 타깃 재추출 대상 핵심 필드(누락/저신뢰 시 다시 찾는다)
_REFIND_FIELDS = {
    "product_name": "제품명",
    "food_type": "식품유형(예: 가공두유, 조미건어포)",
    "business_name": "제조원(영업자) 명칭",
    "address": "제조원 소재지(주소)",
    "license_no": "영업등록번호(숫자)",
    "manufacture_report_no": "품목제조보고번호(숫자)",
}

_REFIND_SYSTEM = """당신은 식품 서류에서 특정 항목만 정밀 판독하는 검증기입니다.
1차 판독에서 비었거나 불확실한 항목만, 부분 확대(타일) 이미지를 사람이 보듯 자세히 보고 다시 찾습니다.
작은 글씨(정보표의 '제조원'·'식품유형'·'품목보고번호' 등)를 끝까지 확인하세요.
실제로 보이는 값만 적고, 확대해도 안 보이면 null. 브랜드/상표를 제조원으로 혼동 금지.
반드시 요청된 키만 담은 JSON 으로 출력(설명 금지)."""


def refind_missing_fields(
    result: dict[str, Any],
    images: list[Image.Image],
    fields: list[str] | None = None,
    extra: list[str] | None = None,
    context: str | None = None,
    **gemma_opts: Any,
) -> dict[str, Any]:
    """핵심 필드를 더 촘촘한 타일로 Gemma 가 다시 찾는다.

    대상 = (null 인 핵심 필드) + extra(값이 있어도 부정확 의심되는 필드).
    대상이 없으면 추가 호출 없이 그대로 반환(속도). 채운/교정한 필드는 _refound 에 기록.
    context: 병합 PDF 다제품일 때 어느 제품을 읽을지 지정(제품명) — 교차오염 방지.
    """
    targets = [f for f in (fields or _REFIND_FIELDS) if f in _REFIND_FIELDS and not result.get(f)]
    for f in extra or []:
        if f in _REFIND_FIELDS and f not in targets:
            targets.append(f)
    if not targets or not images:
        return result

    # 더 촘촘한 확대 타일(3x3)로 작은 글씨 판독률↑
    tiles: list[Image.Image] = []
    for img in images[:2]:
        tiles.extend(render_tiles(img, grid=(3, 3), upscale=2.0))
    send = list(images) + tiles[:9]

    want = "\n".join(f"- {k}: {_REFIND_FIELDS[k]}" for k in targets)
    keys_json = ", ".join(f'"{k}": null' for k in targets)
    ctx_line = (
        f"이 문서에는 여러 제품이 섞여 있을 수 있습니다. '{context}' 제품에 해당하는 값만 읽으세요.\n"
        if context else ""
    )
    user = (
        ctx_line
        + "아래 항목만 이미지(부분 확대 포함)에서 다시 정밀하게 찾아 읽으세요.\n"
        f"{want}\n\n반드시 이 JSON 만: {{{keys_json}}}"
    )
    try:
        found = judge_json(_REFIND_SYSTEM, user, images=send, **gemma_opts)
    except Exception:  # noqa: BLE001 - 재추출 실패는 무시(원본 유지)
        return result

    refound = []
    for k in targets:
        v = found.get(k)
        if v not in (None, "", "null"):
            result[k] = v
            refound.append(k)
    if refound:
        result["_refound"] = refound
    return result


def render_file(
    path: str,
    max_pages: int = 4,
    target_long_side: int = 2400,
    pages: list[int] | None = None,
) -> list[Image.Image]:
    """파일(PDF/이미지)을 고해상도 PIL 이미지 목록으로 렌더한다.

    한글 밀집 서류의 고유명사(업체명 등) 판독 정확도를 위해 긴 변 기준
    target_long_side(기본 2400px)까지 렌더/업스케일한다.
    pages 가 주어지면 해당 0-기준 페이지 인덱스만 렌더한다(없으면 앞에서 max_pages).
    """
    kind = filetype.guess(path)
    images: list[Image.Image] = []

    if kind and kind.extension == "pdf":
        doc = pdfium.PdfDocument(path)
        try:
            doc.init_forms()
        except Exception:  # noqa: BLE001 - 폼 없는 PDF
            pass
        if pages is None:
            page_indices = range(min(len(doc), max_pages))
        else:
            page_indices = [i for i in pages if 0 <= i < len(doc)]
        for page_index in page_indices:
            page = doc[page_index]
            long_side = max(page.get_width(), page.get_height())
            scale = max(1.0, target_long_side / long_side) if long_side else 2.0
            pil = page.render(scale=scale).to_pil().convert("RGB")
            images.append(pil)
        doc.close()
    else:
        try:
            img = Image.open(path).convert("RGB")
        except Exception:  # noqa: BLE001 - HWP/DOCX/XLSX 등 비이미지 → 렌더 없음(kordoc 텍스트 사용)
            return []
        long_side = max(img.size)
        # 작으면 업스케일(판독↑), 너무 크면(목표의 1.5배 초과) 다운스케일(전송량/토큰 폭증 방지).
        factor = None
        if long_side and long_side < target_long_side:
            factor = target_long_side / long_side
        elif long_side > target_long_side * 1.5:
            factor = target_long_side / long_side
        if factor:
            img = img.resize(
                (max(1, int(img.width * factor)), max(1, int(img.height * factor))),
                Image.Resampling.LANCZOS,
            )
        images.append(img)

    return images


def render_tiles(
    image: Image.Image,
    grid: tuple[int, int] = (2, 2),
    overlap: float = 0.14,
    upscale: float = 2.0,
) -> list[Image.Image]:
    """이미지를 겹침 격자로 잘라 각 타일을 확대한다.

    각 타일이 곧 '줌'이라 전체 이미지에선 묻히던 작은 글씨(제조사명/소재지 등)를
    VLM 단독으로도 읽을 수 있게 한다.
    """
    rows, cols = grid
    W, H = image.size
    tw, th = W / cols, H / rows
    ox, oy = tw * overlap, th * overlap
    tiles: list[Image.Image] = []
    for r in range(rows):
        for c in range(cols):
            box = (
                max(0, int(c * tw - ox)),
                max(0, int(r * th - oy)),
                min(W, int((c + 1) * tw + ox)),
                min(H, int((r + 1) * th + oy)),
            )
            tile = image.crop(box)
            if upscale and upscale != 1.0:
                tile = tile.resize(
                    (int(tile.width * upscale), int(tile.height * upscale)),
                    Image.LANCZOS,
                )
            tiles.append(tile)
    return tiles


def classify_and_extract(
    path: str,
    max_pages: int = 8,
    use_ocr: bool = True,
    tile: bool = False,
    tile_grid: tuple[int, int] = (2, 2),
    **gemma_opts: Any,
) -> list[dict[str, Any]]:
    """한 파일을 판독해 제품별 추출 결과 목록을 반환한다.

    한 파일에 여러 제품(병합 PDF)이 있으면 제품마다 한 dict 로 분리해 리스트로 반환한다.
    텍스트 소스 우선순위: 1) kordoc(텍스트레이어/오피스) 2) EasyOCR(스캔). 이미지는 Gemma 비전과 함께.
    """
    from chandra import kordoc

    # --- 추출 캐시 조회: 파일내용 해시 + 추출옵션 + 프롬프트버전 ---
    cache_file = None
    try:
        h = hashlib.md5(Path(path).read_bytes()).hexdigest()
        # 프롬프트 버전: 1차 추출 + 재추출(refind) 프롬프트/대상필드를 모두 반영해
        # 프롬프트가 바뀌면 캐시가 자동 무효화되도록 한다.
        pv_src = _EXTRACTION_SYSTEM + _REFIND_SYSTEM + repr(sorted(_REFIND_FIELDS)) + "v2-textlayer-priority"
        pv = hashlib.md5(pv_src.encode("utf-8")).hexdigest()[:8]
        _EXT_CACHE.mkdir(parents=True, exist_ok=True)
        cache_file = _EXT_CACHE / f"{h}_{int(tile)}{tile_grid[0]}{tile_grid[1]}_{int(use_ocr)}_{max_pages}_{pv}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            for r in cached:
                r["file"] = path  # 압축해제 경로는 매번 달라지므로 현재 경로로 갱신
            return cached
    except Exception:  # noqa: BLE001 - 캐시 실패는 무시하고 정상 추출
        cache_file = None

    kordoc_md = kordoc.to_markdown(path)  # 비지원/스캔본이면 None
    # 스캔/라벨(tile)은 작은 글씨가 많아 더 고해상으로 렌더(판독 정확도↑).
    # 텍스트레이어 PDF 는 텍스트를 kordoc 에서 정확히 얻으므로 보조 이미지는 저해상으로 충분(전송량↓).
    if tile:
        long_side = 3200
    elif kordoc_md:
        long_side = 1800
    else:
        long_side = 2400
    images = render_file(path, max_pages=max_pages, target_long_side=long_side)
    if not images and not kordoc_md:
        return [{"doc_type": DOC_UNKNOWN, "error": "렌더/파싱 불가", "file": path}]

    # kordoc 마크다운이 있으면 그것을 최우선 텍스트로 쓰므로 EasyOCR 는 생략(순수 낭비 제거).
    # kordoc 이 없는 스캔본/이미지에서만 EasyOCR 를 돌린다.
    ocr_blocks: list[str] = []
    if use_ocr and images and not kordoc_md:
        from chandra.ocr_engines import ocr_image, ocr_image_best

        for idx, img in enumerate(images):
            # 스캔 문서의 고유명사(제조사·주소·기관명)는 첫 페이지에 밀집하므로, 첫 페이지만
            # 전처리 3변형(원본·대비·샤픈) best-pick 으로 정확도↑. 나머지 페이지는 단일 OCR(속도).
            if tile and idx == 0:
                text, _variant = ocr_image_best(img, variants=3)
            else:
                text = ocr_image(img)
            if text:
                ocr_blocks.append(f"[페이지 {idx + 1} OCR]\n{text}")
    if kordoc_md:
        ocr_text = "[kordoc 문서 텍스트]\n" + kordoc_md[:60000]
    else:
        ocr_text = "\n\n".join(ocr_blocks)

    # 타일(부분 확대) 이미지 추가 — 저해상 라벨의 작은 글씨를 VLM 단독으로 읽기 위함.
    send_images = list(images)
    if tile:
        # 라벨은 가로로 정보가 많아 3x2 격자로 더 촘촘히 확대(작은 글씨 판독률↑)
        grid = (3, 2) if tile_grid == (2, 2) else tile_grid
        tiles: list[Image.Image] = []
        for img in images[:2]:  # 페이지 폭증 방지(최대 2페이지까지만 타일링)
            tiles.extend(render_tiles(img, grid=grid))
        send_images = list(images) + tiles[:6]

    user_text = (
        "다음 문서 이미지를 판독하여 종류를 분류하고 핵심 정보를 JSON 으로 추출하세요. "
        f"이미지는 {len(images)} 페이지입니다."
    )
    if tile:
        user_text += (
            " 이어지는 추가 이미지들은 같은 문서의 '부분 확대(타일)'입니다. "
            "전체에서 묻혀 작게 보이는 글씨(제조사명/소재지/영양성분 등)는 확대 타일로 정확히 읽으세요."
        )
    if ocr_text and kordoc_md:
        # 텍스트 레이어(문서 원본 텍스트)는 글자 단위로 가장 정확하다 → 제품명 등 고유명사는
        # 이 텍스트를 그대로 따르고(예: '뼈를'을 이미지 보고 '뼈클'로 바꾸지 말 것), 이미지는
        # 표 구조·체크박스·숫자 확인용으로만 쓴다.
        user_text += (
            "\n\n아래는 이 문서에 내장된 '문서 원본 텍스트'입니다(가장 정확). 제품명·업체명·기관명·"
            "주소 등 모든 한글 표기는 이 텍스트를 글자 그대로 따르고, 이미지를 보고 임의로 글자를 "
            "바꾸지 마세요(특히 받침 '를/클/름' 등 혼동 주의). 표 구조·숫자·체크박스만 이미지로 확인.\n\n"
            + ocr_text
        )
    elif ocr_text:
        user_text += (
            "\n\n아래는 전용 한글 OCR 엔진이 추출한 텍스트입니다. "
            "한글 명칭(제품명/업체명/기관명/주소 등)의 표기는 이 OCR 텍스트를 우선 기준으로 삼고, "
            "표 구조·숫자·결과값은 이미지로 확인해 보정하세요.\n\n" + ocr_text
        )
    try:
        raw = judge_json(_EXTRACTION_SYSTEM, user_text, images=send_images, **gemma_opts)
    except Exception as exc:  # noqa: BLE001
        return [{"doc_type": DOC_UNKNOWN, "error": str(exc), "file": path}]

    # 다제품 배열(products) 또는 단일 객체(구버전 응답) 모두 수용
    products = raw.get("products") if isinstance(raw, dict) else None
    if not isinstance(products, list) or not products:
        products = [raw if isinstance(raw, dict) else {}]
    single = len(products) == 1

    out: list[dict[str, Any]] = []
    for result in products:
        if not isinstance(result, dict):
            continue
        if ocr_text:
            result = _drop_hallucinations(result, ocr_text)  # 환각 고유명사 폐기
            result["_ocr_text"] = ocr_text
        result.setdefault("doc_type", DOC_UNKNOWN)
        if result["doc_type"] not in KNOWN_DOC_TYPES:
            result["doc_type"] = DOC_UNKNOWN

        # 누락/오인식 핵심 필드 재추출. 단일 제품은 전체 핵심필드, 병합 PDF 다제품은
        # 그룹핑·판정에 직결되는 필드만(비용 절감) + 제품명 컨텍스트로 교차오염 방지.
        if result["doc_type"] in (DOC_PRODUCT_REPORT, DOC_SELF_QUALITY, DOC_LABEL, DOC_NUTRITION_CERT):
            suspect: list[str] = []
            ft = result.get("food_type")
            if ft:
                try:
                    from chandra.foodsafety import search_food_spec

                    if not search_food_spec(str(ft).strip()):
                        suspect.append("food_type")  # 식품공전 미등록 → '가공유' 같은 오인식 의심
                except Exception:  # noqa: BLE001
                    pass
            if single:
                result = refind_missing_fields(result, images, extra=suspect, **gemma_opts)
            else:
                result = refind_missing_fields(
                    result, images,
                    fields=["manufacture_report_no", "business_name", "food_type"],
                    extra=suspect, context=result.get("product_name"), **gemma_opts,
                )

        result["file"] = path
        result["num_pages"] = len(images)
        out.append(result)

    # 성공 결과만 캐시(오류 결과는 캐시하지 않음 — 일시적 실패 재시도 가능하게)
    if cache_file and out and not any(r.get("error") for r in out):
        try:
            cache_file.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return out or [{"doc_type": DOC_UNKNOWN, "error": "추출 결과 없음", "file": path}]
