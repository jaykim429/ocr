"""3단계: 공인기관 자가품질검사성적서 검토.

수행 내용:
  1) 품목제조보고서 ↔ 자가품질성적서 교차대조 (제품명·식품유형·품목제조보고번호·영업자)
  2) 제품명/식품유형 확인 후 식품공전 규격 조회 (chandra.food_code)
  3) 식품공전 규격 ↔ 성적서 시험·검사 항목/결과 일치 여부 검토
     - 성적서에 인쇄된 기준으로 결과를 재계산해 적합/부적합 판정 (항상 수행 가능)
     - 식품공전 룰셋과 인쇄기준이 다르면 '검토필요'로 플래그(자동 부적합 아님)
  4) 식품공전 규격 대비 자가품질검사 항목 충분성(누락) 검토

성적서/보고서 입력은 OCR 마크다운 또는 구조화된 dict 모두 지원한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date as _date
from difflib import SequenceMatcher
from typing import Any

from chandra.food_code import (
    AbsenceCriteria,
    Criteria,
    FoodTypeStandard,
    LimitCriteria,
    MicroCriteria,
    QualitySpecItem,
    lookup_standard,
)
from chandra.gemma_judge import judge_json
from chandra.test_agencies import verify_agency
from chandra.text_match import collapse as _norm, strip_entity as _strip_entity
from chandra.validity import check_validity


# ---------------------------------------------------------------------------
# 입력 데이터 모델
# ---------------------------------------------------------------------------


@dataclass
class ReportTestItem:
    """성적서의 시험·검사 항목 한 줄."""

    name: str
    criteria_text: str = ""  # 인쇄된 시험·검사 기준 (원문)
    results_text: str = ""  # 인쇄된 결과 (원문)
    results: list[float] = field(default_factory=list)  # 파싱된 수치 결과
    judgement_text: str = ""  # 인쇄된 판정 (적합/부적합)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityCertificate:
    """자가품질검사성적서."""

    product_name: str | None = None
    food_type: str | None = None
    manufacture_report_no: str | None = None  # 품목제조보고번호
    report_no: str | None = None  # 성적서 발행번호
    test_agency: str | None = None
    test_agency_designation_no: str | None = None  # 검사기관 지정번호 (예: 식품 제099호)
    test_agency_tel: str | None = None  # 검사기관 전화번호 (성적서 하단)
    test_agency_address: str | None = None  # 검사기관 주소 (성적서 하단)
    manufacturer: str | None = None
    manufacturer_address: str | None = None  # 성적서상 제조원 소재지
    issue_date: str | None = None  # 발급일 (유효기간 기산점)
    test_completed_date: str | None = None  # 검사완료일
    test_purpose: str | None = None  # 시험검사목적 (자가품질위탁검사 / 참고용 등)
    ingredients: list[str] = field(default_factory=list)  # 원재료명(사용 첨가물 판단용)
    items: list[ReportTestItem] = field(default_factory=list)
    overall_text: str | None = None  # 종합판정

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


@dataclass
class ManufactureReport:
    """품목제조보고서 (교차대조에 필요한 핵심 필드만)."""

    product_name: str | None = None
    food_type: str | None = None
    manufacture_report_no: str | None = None
    business_name: str | None = None
    license_no: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 결과 모델
# ---------------------------------------------------------------------------


@dataclass
class FieldMatch:
    field: str
    manufacture_value: str | None
    certificate_value: str | None
    match: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CrossCheckResult:
    matches: list[FieldMatch]
    consistent: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "matches": [m.to_dict() for m in self.matches],
            "consistent": self.consistent,
            "reasons": self.reasons,
        }


@dataclass
class ItemEvaluation:
    name: str
    matched_spec: str | None  # 식품공전 규격 항목명
    computed_verdict: str  # 적합 / 부적합 / 판정불가
    detail: str
    printed_verdict: str | None = None
    verdict_mismatch: bool = False  # 인쇄 판정 ↔ 재계산 판정 불일치
    criteria_mismatch: bool = False  # 인쇄 기준 ↔ 식품공전 규격 불일치
    criteria_mismatch_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelfQualityReview:
    food_type: str | None
    matched_standard: str | None  # 매칭된 식품공전 식품유형명
    cross_check: CrossCheckResult | None
    item_evaluations: list[ItemEvaluation]
    missing_required_items: list[str]  # 식품공전 필수항목 중 성적서 누락
    extra_items: list[str]  # 성적서에 있으나 규격에 없는 항목
    overall_verdict: str  # 적합 / 부적합 / 검토필요
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "food_type": self.food_type,
            "matched_standard": self.matched_standard,
            "cross_check": self.cross_check.to_dict() if self.cross_check else None,
            "item_evaluations": [e.to_dict() for e in self.item_evaluations],
            "missing_required_items": self.missing_required_items,
            "extra_items": self.extra_items,
            "overall_verdict": self.overall_verdict,
            "reasons": self.reasons,
        }


# ---------------------------------------------------------------------------
# 파서: 숫자, 기준 텍스트, 결과 텍스트
# ---------------------------------------------------------------------------

_SCALE = {"만": 10_000, "억": 100_000_000}


def parse_number(token: str) -> float | None:
    """'1,000,000', '5×10^6', '1.8', '20 이하' 등에서 숫자 추출."""
    if token is None:
        return None
    t = token.strip()
    # a×10^b 형태
    m = re.search(r"([\d.]+)\s*[xX×]\s*10\^?(\d+)", t)
    if m:
        return float(m.group(1)) * (10 ** int(m.group(2)))
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", t)
    if not m:
        return None
    val = float(m.group(0).replace(",", ""))
    for suffix, scale in _SCALE.items():
        if suffix in t:
            val *= scale
    return val


def parse_results(results_text: str) -> list[float]:
    """결과 셀에서 측정값 목록 추출 (예: '340, 180, 260, 310, 490')."""
    if not results_text:
        return []
    values: list[float] = []
    for token in re.split(r"[,/、\s]+", results_text.strip()):
        token = token.strip()
        if not token:
            continue
        num = parse_number(token)
        if num is not None:
            values.append(num)
    return values


def parse_criteria_text(text: str) -> Criteria | None:
    """시험·검사 기준 원문을 Criteria 로 파싱."""
    if not text:
        return None
    t = text.strip()
    low = t.lower()

    # 1) 미생물 샘플링플랜 n / c / m / M
    if "n=" in low or re.search(r"\bn\s*=", low):
        def grab(key: str) -> float | None:
            m = re.search(rf"{key}\s*=\s*([\d.,]+(?:\s*[xX×]\s*10\^?\d+)?)", t)
            return parse_number(m.group(1)) if m else None

        n = grab("n")
        c = grab("c")
        m_val = grab("m")
        big_m = re.search(r"M\s*=\s*([\d.,]+(?:\s*[xX×]\s*10\^?\d+)?)", t)
        big_m_val = parse_number(big_m.group(1)) if big_m else None
        # n·c·m 이 모두 읽혀야 신뢰 가능한 샘플링플랜이다. c 를 못 읽었는데 0 으로 가정하면
        # 한계 허용수가 0 이 되어 한 건만 마진이어도 거짓 부적합이 난다 → c 없으면 플랜을 만들지
        # 않고(None) 상위에서 판정불가로 라우팅한다.
        if n is not None and m_val is not None and c is not None:
            return MicroCriteria(n=int(n), c=int(c), m=m_val, M=big_m_val)

    # 2) 불검출/음성 형태
    if any(kw in t for kw in ("불검출", "음성", "검출되어서는", "n.d", "N.D", "陰性")):
        return AbsenceCriteria(expected="불검출" if "음성" not in t else "음성")

    # 3) 수치 한계 (이하/이상/미만/초과). 복합기준(예: '15 이하(단, B1은 10 이하)')은
    #    가장 앞의 주 기준 수치를 사용한다.
    op_map = {"이하": "<=", "이상": ">=", "미만": "<", "초과": ">"}
    first_kw, first_pos, first_op = None, len(t), None
    for kw, op in op_map.items():
        p = t.find(kw)
        if p != -1 and p < first_pos:
            first_kw, first_pos, first_op = kw, p, op
    if first_kw:
        # 기준 키워드 바로 앞쪽의 수치를 한계값으로 사용
        head = t[: first_pos + len(first_kw)]
        nums = re.findall(r"[\d.,]+(?:\s*[xX×]\s*10\^?\d+)?", head)
        val = parse_number(nums[-1]) if nums else parse_number(t)
        if val is not None:
            unit_m = re.search(r"[\d.]\s*(㎎/㎏|㎍/㎏|mg/kg|ug/kg|µg/kg|ppm|mg%|㎎%|%|g|mg|㎎|㎍)", t)
            unit = unit_m.group(1) if unit_m else ""
            return LimitCriteria(op=first_op, value=val, unit=unit)

    return None


# ---------------------------------------------------------------------------
# 판정 엔진
# ---------------------------------------------------------------------------


def evaluate_micro(crit: MicroCriteria, results: list[float]) -> tuple[str, str]:
    """식품공전 샘플링플랜 판정.

    3-class: count > M 가 1개라도 있으면 부적합. m < count <= M 인 시료 수가 c 초과면 부적합.
    2-class(M=None): count > m 인 시료 수가 c 초과면 부적합.
    """
    if not results:
        return "판정불가", "측정 결과 없음"

    if crit.M is None:
        over = [x for x in results if x > crit.m]
        ok = len(over) <= crit.c
        detail = (
            f"기준 {crit.describe()} | 결과 {results} | "
            f"m({crit._fmt(crit.m)}) 초과 시료 {len(over)}개 (허용 c={crit.c})"
        )
        return ("적합" if ok else "부적합", detail)

    over_M = [x for x in results if x > crit.M]
    marginal = [x for x in results if crit.m < x <= crit.M]
    ok = len(over_M) == 0 and len(marginal) <= crit.c
    detail = (
        f"기준 {crit.describe()} | 결과 {results} | "
        f"M 초과 {len(over_M)}개, m~M 구간 {len(marginal)}개 (허용 c={crit.c})"
    )
    return ("적합" if ok else "부적합", detail)


def evaluate_limit(crit: LimitCriteria, value: float | None) -> tuple[str, str]:
    if value is None:
        return "판정불가", "측정값 없음"
    ops = {
        "<=": value <= crit.value,
        "<": value < crit.value,
        ">=": value >= crit.value,
        ">": value > crit.value,
    }
    ok = ops.get(crit.op, False)
    return ("적합" if ok else "부적합", f"기준 {crit.describe()} | 측정 {value}")


def evaluate_absence(crit: AbsenceCriteria, results_text: str) -> tuple[str, str]:
    text = (results_text or "").strip()
    if not text:
        return "판정불가", "결과 없음"
    low = text.lower()
    # 음성(불검출) 표현. '검출한계/정량한계 미만(이하)'는 사실상 불검출이다.
    negative = any(kw in low for kw in ("불검출", "미검출", "음성", "n.d", "검출되지", "검출 안", "검출안"))
    if ("검출한계" in text or "정량한계" in text) and ("미만" in text or "이하" in text):
        negative = True
    # 양성 신호. 단, 위 음성표현이나 '없음'(예: '초과 항목 없음')·'한계' 문맥은 양성에서 제외.
    # 주의: 단순 "0"을 음성으로 보면 "0.5 검출" 같은 양성 결과를 불검출로 오판하므로 "0"은 제외했다.
    has_pos = any(kw in text for kw in ("검출", "양성", "초과", "부적합"))
    positive = (
        has_pos and not negative and "없음" not in text
        and "검출한계" not in text and "정량한계" not in text
    )
    if negative and not positive:
        return "적합", f"기준 {crit.describe()} | 결과 {text}"
    if positive:
        return "부적합", f"기준 {crit.describe()} | 결과 {text}"
    return "판정불가", f"기준 {crit.describe()} | 결과 해석 불가: {text}"


def evaluate_item(spec: QualitySpecItem, item: ReportTestItem) -> tuple[str, str]:
    """성적서 항목을 식품공전 규격으로 재계산 판정.

    성적서에 기준이 인쇄돼 있으면 그 기준을 우선 사용(현장 적용 기준 검증),
    없으면 식품공전 규격 기준을 사용한다.
    """
    printed = parse_criteria_text(item.criteria_text)
    crit = printed or (spec.criteria if spec else None)
    if crit is None:
        return "판정불가", "적용할 기준 없음"

    if isinstance(crit, MicroCriteria):
        return evaluate_micro(crit, item.results)
    if isinstance(crit, LimitCriteria):
        value = item.results[0] if item.results else parse_number(item.results_text)
        return evaluate_limit(crit, value)
    if isinstance(crit, AbsenceCriteria):
        return evaluate_absence(crit, item.results_text)
    return "판정불가", "지원하지 않는 기준 형식"


# ---------------------------------------------------------------------------
# 항목 매칭 (성적서 항목명 ↔ 식품공전 규격 항목)
# ---------------------------------------------------------------------------


def match_spec_item(
    name: str, standard: FoodTypeStandard
) -> QualitySpecItem | None:
    target = _norm(name)
    if not target:
        return None
    for spec in standard.spec_items:
        if _norm(spec.name) == target:
            return spec
        for alias in spec.aliases:
            if _norm(alias) == target:
                return spec
    # 부분 포함
    for spec in standard.spec_items:
        keys = [spec.name, *spec.aliases]
        for key in keys:
            nk = _norm(key)
            if nk and (nk in target or target in nk):
                return spec
    return None


def _criteria_equal(a: Criteria | None, b: Criteria | None) -> bool:
    if a is None or b is None:
        return False
    if type(a) is not type(b):
        return False
    if isinstance(a, MicroCriteria) and isinstance(b, MicroCriteria):
        return (a.n, a.c, a.m, a.M) == (b.n, b.c, b.m, b.M)
    if isinstance(a, LimitCriteria) and isinstance(b, LimitCriteria):
        return (a.op, a.value) == (b.op, b.value)
    if isinstance(a, AbsenceCriteria) and isinstance(b, AbsenceCriteria):
        return True
    return False


# ---------------------------------------------------------------------------
# 1) 교차대조: 품목제조보고서 ↔ 자가품질성적서
# ---------------------------------------------------------------------------


def _values_match(a: str | None, b: str | None) -> bool:
    """OCR 오인식(예: 삼향↔삼황)·법인표기 차이를 흡수하도록 정확/부분/퍼지 매칭."""
    if not a or not b:
        return False
    na, nb = _strip_entity(a), _strip_entity(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.8


def cross_check_documents(
    manufacture: ManufactureReport, certificate: QualityCertificate
) -> CrossCheckResult:
    """품목제조보고서와 자가품질성적서의 핵심 식별정보 일치 여부."""
    pairs = [
        ("제품명", manufacture.product_name, certificate.product_name),
        ("식품유형", manufacture.food_type, certificate.food_type),
        (
            "품목제조보고번호",
            manufacture.manufacture_report_no,
            certificate.manufacture_report_no,
        ),
        ("영업자/제조원", manufacture.business_name, certificate.manufacturer),
    ]
    matches: list[FieldMatch] = []
    reasons: list[str] = []
    for field_name, mv, cv in pairs:
        if mv is None and cv is None:
            continue
        ok = _values_match(mv, cv)
        matches.append(FieldMatch(field_name, mv, cv, ok))
        if not ok:
            reasons.append(f"{field_name} 불일치: 보고서='{mv}' vs 성적서='{cv}'")
    # 비교 가능한 공통 필드가 하나도 없으면 '불일치(False)'가 아니라 '판정 불가(None)'다.
    # (양쪽 모두 OCR 누락 등) — False 로 두면 불필요한 검토필요 알람이 뜬다.
    consistent = (all(m.match for m in matches) if matches else None)
    if not matches:
        reasons.append("교차대조할 공통 필드 없음(판정 불가)")
    return CrossCheckResult(matches=matches, consistent=consistent, reasons=reasons)


# ---------------------------------------------------------------------------
# 종합 검토
# ---------------------------------------------------------------------------


def review_self_quality(
    certificate: QualityCertificate,
    manufacture: ManufactureReport | None = None,
    standard: FoodTypeStandard | None = None,
) -> SelfQualityReview:
    """3단계 종합 검토."""
    reasons: list[str] = []

    # 1) 교차대조
    cross = (
        cross_check_documents(manufacture, certificate) if manufacture else None
    )
    if cross and not cross.consistent:
        reasons.extend(cross.reasons)

    # 2) 식품유형 → 식품공전 규격 조회
    food_type = certificate.food_type or (
        manufacture.food_type if manufacture else None
    )
    std = standard or lookup_standard(food_type)
    matched_standard = std.food_type if std else None
    if std is None:
        reasons.append(f"식품공전 규격을 찾지 못함 (식품유형='{food_type}')")

    # 3) 항목별 결과 검토 + 식품공전 기준 대조
    evaluations: list[ItemEvaluation] = []
    matched_spec_names: set[str] = set()
    for item in certificate.items:
        spec = match_spec_item(item.name, std) if std else None
        verdict, detail = evaluate_item(spec, item) if spec else evaluate_item_no_spec(item)
        printed = (item.judgement_text or "").strip() or None

        verdict_mismatch = bool(
            printed and verdict in ("적합", "부적합") and _norm(printed) != _norm(verdict)
        )

        criteria_mismatch = False
        criteria_detail = None
        if spec and spec.criteria is not None:
            printed_crit = parse_criteria_text(item.criteria_text)
            if printed_crit is not None and not _criteria_equal(
                printed_crit, spec.criteria
            ):
                criteria_mismatch = True
                criteria_detail = (
                    f"성적서 기준 '{printed_crit.describe()}' ↔ "
                    f"식품공전 규격 '{spec.criteria.describe()}'"
                )

        if spec:
            matched_spec_names.add(spec.name)

        evaluations.append(
            ItemEvaluation(
                name=item.name,
                matched_spec=spec.name if spec else None,
                computed_verdict=verdict,
                detail=detail,
                printed_verdict=printed,
                verdict_mismatch=verdict_mismatch,
                criteria_mismatch=criteria_mismatch,
                criteria_mismatch_detail=criteria_detail,
            )
        )

    # 4) 항목 충분성(누락) 검토
    missing: list[str] = []
    extra: list[str] = []
    if std:
        for spec in std.required_items():
            if spec.name not in matched_spec_names:
                missing.append(spec.name)
        for ev in evaluations:
            if ev.matched_spec is None:
                extra.append(ev.name)

    # 사유 집계
    for ev in evaluations:
        if ev.computed_verdict == "부적합":
            reasons.append(f"항목 부적합: {ev.name} ({ev.detail})")
        if ev.verdict_mismatch:
            reasons.append(
                f"판정 불일치: {ev.name} 성적서='{ev.printed_verdict}' vs 재계산='{ev.computed_verdict}'"
            )
        if ev.criteria_mismatch:
            reasons.append(f"기준 불일치(식품공전 확인 필요): {ev.name} — {ev.criteria_mismatch_detail}")
    for name in missing:
        reasons.append(f"필수 검사항목 누락: {name}")

    # 종합 판정
    has_fail = any(ev.computed_verdict == "부적합" for ev in evaluations)
    has_review = (
        bool(missing)
        or any(ev.criteria_mismatch for ev in evaluations)
        or any(ev.verdict_mismatch for ev in evaluations)
        or any(ev.computed_verdict == "판정불가" for ev in evaluations)
        or std is None
        or (cross is not None and cross.consistent is False)
    )
    if has_fail:
        overall = "부적합"
    elif has_review:
        overall = "검토필요"
    else:
        overall = "적합"

    return SelfQualityReview(
        food_type=food_type,
        matched_standard=matched_standard,
        cross_check=cross,
        item_evaluations=evaluations,
        missing_required_items=missing,
        extra_items=extra,
        overall_verdict=overall,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Gemma 판정 경로 (최종 적합성 '판단'은 규칙엔진이 아니라 Gemma 가 수행)
# ---------------------------------------------------------------------------

_SELF_QUALITY_JUDGE_SYSTEM = """당신은 식품 품질검토 전문가입니다.
공인기관 자가품질검사성적서가 식품공전(식품의 기준 및 규격)에 적합한지 판단합니다.

판정 원칙:
- 적합 기준은 '성적서의 시험·검사 결과값이 기준 범위 안에 드는가' 입니다.
  규격 우선순위: ①식품공전_규격_식품안전나라(I0930, 권위 규격) → ②식품공전_규격(내부) →
  ③성적서에 인쇄된 시험기준. 성적서 기준 표기가 식품공전 수치와 달라도 실제 결과값이
  (식품공전이 있으면 식품공전, 없으면 인쇄기준) 범위에 들면 적합.
- 식품공전_규격_식품안전나라에 해당 식품유형 규격이 있으면 이를 근거의 1순위로 삼고,
  각 항목 reason 에 '식품공전 규격값 ↔ 성적서 결과값'을 구체 수치로 인용하세요.
- 규격 정보(식품공전·내부·인쇄기준)가 모두 없으면 결과값만 보고 '안전/적합'으로 단정하지 말고,
  '규격 확인 불가 — 성적서 결과 참고(추가 확인 권장)'처럼 표현하고 해당 항목은 검토필요로 둡니다.
- 시험항목 유형별로 맞게 판정합니다:
  · 미생물 샘플링플랜(n·c·m·M): M 초과 시료 없고 m~M 구간 시료가 c 이하면 적합
  · 이물·타르색소·보존료 등: '불검출/음성'이면 적합, 검출이면 부적합
  · 중금속·곰팡이독소(아플라톡신 등)·수치한계(○○ 이하/이상): 결과가 한계 이내면 적합
- 식품공전_규격이 evidence에 없으면(식품유형 미등록) 성적서 인쇄 기준으로만 판정하고,
  항목 충분성(누락)은 단정하지 말고 '검토필요'로 둡니다(규격 미등록 표시).
- ★자가품질검사 항목 = 「식품위생법 시행규칙 [별표 12]」 제4호에 따라 '식약처가 고시한 식품유형별
  검사항목'(=식품공전 식품유형별 규격)이다. 단, 같은 호 단서에 따라 '제조·가공 과정에서 특정
  식품첨가물을 사용하지 아니한 경우 그 항목 검사를 생략할 수 있다'. 따라서 항목 충분성(누락)은
  보수적으로 판정한다. 식품공전(I0930) 규격 목록에 있다고 모두 의무항목은 아니며, 다음은 성적서에
  없어도 '누락'으로 단정하지 말고(참고로만, overall 판정에 미반영):
    · 적용조건이 붙은 항목(예: 무기비소 "현미·미강·톳 등 사용 식품에 한함"처럼 특정 원료·제품에만 적용)
      — 원재료/제품이 그 조건에 해당하지 않으면 검사 대상이 아님
    · 보존료·타르색소·산화방지제·발색제·감미료 등 식품첨가물 규격 항목 — 해당 첨가물을 '사용한
      경우에만' 검사·표시 의무가 생긴다. evidence 의 '원재료' 목록에 그 첨가물이 없으면 미사용으로
      보고 검사 불필요 → 누락이 아니다(원재료에 없는 보존료를 누락이라 하지 말 것).
    · 그 식품유형에서 통상 자가품질 의무로 보지 않는 다수의 성분규격 항목
  반대로 미생물 안전성 핵심항목(세균수·대장균/대장균군, 해당 시 살모넬라·리스테리아 등)이
  명백히 빠졌을 때만 '누락'으로 보고 '검토필요'로 둡니다. 누락이 불확실하면 missing 에 넣지 말고
  reasons 에 '추가 확인 권장' 정도로만 적습니다. 누락만을 이유로 '부적합'으로 판정하지 않습니다.
    · 세균수와 대장균/대장균군은 제품의 살균 여부에 따라 '택일' 적용되는 경우가 많다(식품공전 통칙:
      살균제품 → 세균수 기준 / 비살균·가열하여 섭취하는 제품 → 대장균(군) 기준). 따라서 성적서에
      대장균(군)이 검사·적합으로 기재돼 있으면 세균수가 없어도 '세균수 누락'으로 단정하지 말 것
      (반대도 동일). 규격 항목의 적용조건('살균제품에 한함' 등)이나 제품 특성(비살균·가열섭취)이
      확인되면 그에 맞는 항목만 의무로 본다.
    · ★규격 항목 기준에 '(멸균제품은 제외한다)' 같은 단서가 붙어 있고, evidence '품목특성.살균구분'이
      '멸균'이면 그 항목(예: 대장균군)은 검사 의무가 없으므로 '누락'으로 보지 말 것. '살균구분'이
      '멸균'·'살균'이면 해당 면제·완화 단서를 그대로 적용한다(예: 멸균 가공두유의 대장균군 면제).
- ★evidence 의 '축산물가공품_여부'=true 이면(양념육·햄·소시지·유가공품·알가공품 등) 규격·자가품질
  검사항목은 「축산물의 가공기준 및 성분규격」및 축산물 위생관리법 기준이 적용된다. 이때:
    · 식품공전(I0930)에 규격이 없는 것이 정상이므로 '규격 못 찾음'을 흠으로 보지 말 것.
    · 식품 기준의 미생물 핵심항목(대장균군·살모넬라·리스테리아 등)을 임의로 '필수 누락'으로
      단정하지 말 것 — 축산물 자가품질검사 항목은 제품유형별로 다르며 성적서에 기재된 항목과
      그 종합판정을 우선 존중한다. 성적서 종합판정이 적합이고 기재 항목이 모두 기준 이내면 적합.
    · 항목 충분성에 의문이 있으면 missing 이 아니라 reasons 에 '축산물 고시 자가품질 항목 추가
      확인 권장' 정도로만 적는다.
- 서류 유효기간은 발급일 기준 6개월(현대홈쇼핑 입점 서류 기준)입니다(evidence.유효기간). 오늘
  날짜 기준으로 만료(valid=false)면 최신 검사가 아니므로 부적합 사유가 됩니다. reasons 에
  발급일·만료일·잔여일을 명시하세요.
- 품목제조보고서와 자가품질성적서의 교차대조(제품명/식품유형/보고번호/영업자) 결과를 반영합니다.
  단, 두 서류는 스캔본 OCR을 거쳐 한글 글자 오인식이 있을 수 있습니다. 품목제조보고번호 등
  숫자 식별자가 일치하거나 명칭이 유사(오인식 수준 차이)하면 '동일'로 보고, 명백히 다른
  경우에만 불일치로 판단합니다. 사소한 표기·오인식 차이만으로 부적합 처리하지 않습니다.
- 검사를 수행한 기관(검사기관_검증)이 공인 위생검사전문기관 목록에 존재하는지 반영합니다.
  found=true 면(퍼지 매칭 포함) 공인기관으로 인정합니다. 단, 검사기관_검증.designation_expired=true
  이면 그 기관의 지정 유효기간이 지난 것이므로 '공인'으로 인정하지 말고 '검사기관 지정 만료 — 확인
  필요'로 검토필요 처리하세요.
- ★자가품질검사는 시행규칙 [별표12] 제5호에 따라 '영업자가 직접' 수행할 수도, 위탁 시험검사기관에
  위탁할 수도 있습니다. '검사기관_제조사동일_자체검사'=true 이면 검사기관이 제조사(영업자) 본인이라
  '영업자 직접 자가품질검사'로 적법합니다. 이 경우 공인 위탁검사기관 목록에 없더라도(found=false)
  '검사기관 미확인'을 부적합/검토필요 사유로 삼지 말고 '영업자 직접 자가품질검사(적법)'로 인정하세요.
  검사기관이 제3의 외부기관인데 공인 목록에 없을 때만 '검토필요'로 둡니다.
- 시험검사목적(성적서.시험검사목적)을 확인합니다. '자가품질위탁검사'/'자가품질검사'이면 정상이나,
  '참고용'·'수출용'·'연구용' 등 자가품질이 아니면 reasons 에 '⚠ 이 성적서는 자가품질검사 목적이
  아님(참고용 등) — 자가품질 검토용으로 부적절'을 명시하고 overall 을 최소 '검토필요'로 둡니다.
- 표시사항(라벨)이 제공되면(여러 개일 수 있음) 각 표시사항의 제품명·제조사명·소재지가 성적서의
  제품명·제조원·소재지와 일치하는지 각각 대조합니다. 표시사항이 2개 이상이면 모두 검토해
  reasons 에 표시사항별 결과를 적습니다. 명백히 다른 영업자/제품이면 '검토필요'(또는 부적합)
  근거로, 사소한 OCR 표기차이는 동일로 봅니다.
- 근거 없이 추정하지 말고, 정보가 부족하면 해당 항목은 "검토필요"로 둡니다.
- 핵심 적합요건(결과의 식품공전 범위 내, 필수항목 충족, 유효기간, 검사기관 공인)이 모두
  충족되면, 사소한 OCR 표기차이는 종합 '적합'을 막지 않습니다.

기술(reason) 작성 지침 — 담당자가 바로 이해하도록 풍부하고 구체적으로:
- 각 항목 reason 에는 '적용 규격(출처 포함)·성적서 결과값·판정 근거(여유 또는 초과 정도)'를
  한 문장 이상으로 구체 수치와 함께 기술합니다.
  예) "식품공전(I0930) 대장균 규격 n=5,c=2,m=0,M=10 기준, 결과 0,0,0,0,0 → 전 시료 m 이하로
       여유 있게 적합" / "납 규격 0.1 mg/kg 이하, 결과 0.02 mg/kg(기준의 20%)로 적합".
- reasons(종합)에는 ①결과의 규격 내 적합 여부 ②필수항목 충족/누락 ③유효기간(발급일·만료일·잔여일)
  ④검사기관 공인 여부 ⑤교차대조 결과를 각각 한 줄씩, 근거 수치를 포함해 기술합니다.

반드시 아래 JSON 만 출력하세요(설명 문장 금지):
{
  "items": [{"name": "항목명", "verdict": "적합|부적합|검토필요", "reason": "규격값·결과값·근거를 포함한 구체적 기술"}],
  "missing_required_items": ["누락된 필수항목"],
  "validity_ok": true,
  "cross_check_ok": true,
  "overall_verdict": "적합|부적합|검토필요",
  "reasons": ["종합 사유(항목별 한 줄, 수치 근거 포함)"]
}"""


import functools


@functools.lru_cache(maxsize=1)
def _self_quality_rules() -> dict[str, Any]:
    import json
    from pathlib import Path

    try:
        return json.loads((Path(__file__).with_name("data") / "self_quality_required.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def test_cycle_months(food_type: str | None) -> int | None:
    """식품유형의 자가품질검사 주기(개월) — 시행규칙 [별표 12] 제6호 기준(근사 매칭)."""
    if not food_type:
        return None
    cm = (_self_quality_rules().get("cycle_months") or {})
    ft = _norm(food_type)
    if any(_norm(k) in ft for k in cm.get("주류_keywords", ["주류"])):
        return cm.get("주류", 6)
    for kw in cm.get("9_즉석판매제조가공업", []):
        if _norm(kw) and _norm(kw) in ft:
            return 9
    for months in ("2", "3"):
        for kw in cm.get(months, []):
            if _norm(kw) and _norm(kw) in ft:
                return int(months)
    return cm.get("default", 1)


# 축산물가공품(식육·유·알 가공품) 식품유형 키워드 — 식품공전(I0930)이 아니라 축산물 고시 적용
_LIVESTOCK_FOOD_TYPE_KW = (
    "양념육", "분쇄가공육", "갈비가공품", "햄", "소시지", "베이컨", "건조저장육",
    "식육추출가공품", "식육함유가공품", "포장육", "식육간편조리세트", "식육가공품",
    "발효유", "치즈", "버터", "아이스크림", "유가공품", "가공유", "농축유", "유크림",
    "알가공품", "알함유가공품", "식용란",
)


def _is_livestock_product(food_type: str | None, *signals: str | None) -> bool:
    """축산물가공품 여부. 시험검사목적·검사기관 지정번호에 '축산물'이 있거나
    식품유형이 축산물 가공품 키워드면 True."""
    for s in signals:
        if s and "축산물" in s:
            return True
    if food_type:
        ft = _norm(food_type)
        if any(_norm(k) in ft for k in _LIVESTOCK_FOOD_TYPE_KW):
            return True
    return False


def _live_food_spec(food_type: str | None) -> list[dict[str, Any]]:
    """식품안전나라 식품공전(I0930)에서 식품유형 규격을 조회(네트워크 실패는 무시)."""
    if not food_type:
        return []
    try:
        from chandra.foodsafety import search_food_spec

        rows = search_food_spec(food_type.strip())
        return [
            {
                "항목": r.get("item"),
                "세부항목": r.get("sub_item"),
                "규격": r.get("spec"),
                "단위": r.get("unit"),
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001 - 라이브 조회 실패는 로컬 규격으로 폴백
        return []


def build_self_quality_evidence(
    certificate: QualityCertificate,
    manufacture: ManufactureReport | None = None,
    standard: FoodTypeStandard | None = None,
    today: _date | None = None,
    labels: list[dict[str, Any]] | None = None,
    ingredients: list[str] | None = None,
    product_traits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gemma 판정을 위한 구조화 근거(facts)를 만든다. 판정값은 포함하지 않는다."""
    food_type = certificate.food_type or (
        manufacture.food_type if manufacture else None
    )
    std = standard or lookup_standard(food_type)
    live_spec = _live_food_spec(food_type)  # 식품안전나라 식품공전(I0930) — 권위 규격

    spec_payload = []
    if std:
        for spec in std.spec_items:
            spec_payload.append(
                {
                    "name": spec.name,
                    "기준": spec.criteria.describe() if spec.criteria else None,
                    "필수": spec.required,
                    "적용조건": spec.applies_when,
                    "출처": spec.source,
                }
            )

    items_payload = [
        {
            "name": it.name,
            "성적서_기준": it.criteria_text,
            "결과": it.results or it.results_text,
            "성적서_판정": it.judgement_text,
        }
        for it in certificate.items
    ]

    # 축산물가공품이면 식품공전(I0930)·시행규칙 별표12(식품위생법)가 아니라 축산물 고시·축산물
    # 위생관리법이 적용되므로 별도 신호로 표기한다.
    is_livestock = _is_livestock_product(
        food_type, certificate.test_purpose, certificate.test_agency_designation_no
    )

    cross = cross_check_documents(manufacture, certificate) if manufacture else None
    # 유효기간: 발급일 기준 6개월(현대홈쇼핑 입점 서류 기준). 식품유형별 법정 검사주기는
    # 참고 정보(자가품질검사주기_개월)로만 제공하고 유효기간 판정엔 쓰지 않는다.
    validity = check_validity(
        certificate.issue_date, today=today, valid_months=6,
        label="자가품질검사성적서(발급일+6개월)",
    )
    agency = verify_agency(
        certificate.test_agency,
        certificate.test_agency_designation_no,
        tel=certificate.test_agency_tel,
        address=certificate.test_agency_address,
        today=today,
    )
    # 검사기관이 제조사(영업자) 본인이면 영업자 직접 자가품질검사(시행규칙 별표12 제5호).
    # 면제(공인목록 없어도 적법) 신호이므로 퍼지매칭이 아니라 '정확 일치'만 인정한다
    # (외부기관 이름이 제조사명과 유사하다는 이유로 자체검사로 오인하지 않도록).
    mfr_name = certificate.manufacturer or (manufacture.business_name if manufacture else None)
    _ta, _mn = _strip_entity(certificate.test_agency or ""), _strip_entity(mfr_name or "")
    self_tested = bool(_ta and _mn and _ta == _mn)

    return {
        "식품유형": food_type,
        "축산물가공품_여부": is_livestock,
        "규격적용_안내": (
            "축산물가공품 — 규격·자가품질검사 항목은 「축산물의 가공기준 및 성분규격」 및 "
            "축산물 위생관리법 기준 적용. 식품공전(I0930)에 규격이 없는 것이 정상이며, "
            "성적서에 기재된 검사항목 외 미생물 등을 임의로 '필수 누락'으로 단정하지 말 것."
            if is_livestock else None
        ),
        "품목특성": product_traits or None,  # 품목제조보고서 '품목의 특성'(살균구분·영양표시의무 등)
        "식품공전_규격_식품안전나라": {
            "출처": "식품안전나라 식품공전 OpenAPI(I0930)",
            "항목수": len(live_spec),
            "규격항목": live_spec,
        },
        "식품공전_규격": {
            "식품유형": std.food_type if std else None,
            "정의": std.definition if std else None,
            "규격항목": spec_payload,
            "필수항목": [s.name for s in std.required_items()] if std else [],
        },
        "성적서": {
            "제품명": certificate.product_name,
            "품목제조보고번호": certificate.manufacture_report_no,
            "제조원": certificate.manufacturer,
            "제조원_소재지": certificate.manufacturer_address,
            "검사기관": certificate.test_agency,
            "발급일": certificate.issue_date,
            "시험검사목적": certificate.test_purpose,
            "시험항목": items_payload,
            "종합판정_인쇄": certificate.overall_text,
        },
        "표시사항": [
            {"제품명": l.get("product_name"), "제조사명": l.get("business_name"), "소재지": l.get("address")}
            for l in (labels or [])
        ] or None,
        "원재료": ingredients or (certificate.ingredients or None),
        "자가품질검사주기_개월": test_cycle_months(food_type),  # 시행규칙 별표12 제6호(참고)
        "교차대조": cross.to_dict() if cross else None,
        "유효기간": validity.to_dict(),
        "검사기관_검증": agency.to_dict(),
        "검사기관_제조사동일_자체검사": self_tested,  # True 면 영업자 직접 자가품질검사(별표12 제5호)
        "법적근거": [
            "식품위생법 제31조(자가품질검사 의무) — ①영업자는 제7조·제9조 기준·규격 적합 여부를 검사, ②자가품질위탁 시험·검사기관에 위탁 가능",
            "식품위생법 시행규칙 제31조 및 [별표 12](자가품질검사기준) — 제4호 식품유형별 검사항목(첨가물 미사용 시 생략 가능), 제5호 직접/위탁, 제6호 검사주기",
            "식품위생법 시행령 제21조(영업의 종류) — 식품제조·가공업 등 영업 구분",
        ],
    }


def review_self_quality_gemma(
    certificate: QualityCertificate,
    manufacture: ManufactureReport | None = None,
    standard: FoodTypeStandard | None = None,
    today: _date | None = None,
    labels: list[dict[str, Any]] | None = None,
    ingredients: list[str] | None = None,
    product_traits: dict[str, Any] | None = None,
    **gemma_opts: Any,
) -> dict[str, Any]:
    """3단계 검토를 Gemma 판정으로 수행한다.

    반환값: {"evidence": {...}, "verdict": {Gemma JSON}, "error": str|None}
    """
    evidence = build_self_quality_evidence(
        certificate, manufacture=manufacture, standard=standard, today=today,
        labels=labels, ingredients=ingredients, product_traits=product_traits,
    )
    user_text = (
        "다음 근거(식품공전 규격, 자가품질검사성적서 결과, 교차대조, 유효기간)를 바탕으로 "
        "적합성을 판정하세요.\n\n"
        + json.dumps(evidence, ensure_ascii=False, indent=2)
    )
    try:
        verdict = judge_json(_SELF_QUALITY_JUDGE_SYSTEM, user_text, **gemma_opts)
        return {"evidence": evidence, "verdict": verdict, "error": None}
    except Exception as exc:  # noqa: BLE001 - 판정 실패는 검토필요로 처리
        return {
            "evidence": evidence,
            "verdict": {"overall_verdict": "검토필요", "reasons": [f"Gemma 판정 실패: {exc}"]},
            "error": str(exc),
        }


def evaluate_item_no_spec(item: ReportTestItem) -> tuple[str, str]:
    """식품공전 규격 매칭이 안 될 때: 성적서 인쇄 기준만으로 재계산."""
    printed = parse_criteria_text(item.criteria_text)
    if printed is None:
        # 기준을 못 읽으면 독립 검증이 불가하므로 인쇄 판정을 그대로 신뢰하지 않고 '판정불가'로
        # 둔다(검토필요로 라우팅). 인쇄 판정은 참고로만 detail 에 남긴다.
        if item.judgement_text:
            return "판정불가", f"기준 파싱 불가 — 독립 검증 불가(성적서 인쇄 판정: {item.judgement_text.strip()})"
        return "판정불가", "기준/판정 정보 없음"
    if isinstance(printed, MicroCriteria):
        return evaluate_micro(printed, item.results)
    if isinstance(printed, LimitCriteria):
        value = item.results[0] if item.results else parse_number(item.results_text)
        return evaluate_limit(printed, value)
    if isinstance(printed, AbsenceCriteria):
        return evaluate_absence(printed, item.results_text)
    return "판정불가", "지원하지 않는 기준 형식"
