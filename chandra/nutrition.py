"""2단계: 영양성분성적서 ↔ 표시사항 영양성분 비교 (로직).

「식품등의 표시기준」(식약처 고시) 영양성분 표시 허용오차 적용:
  - 열량, 나트륨, 당류, 지방, 트랜스지방, 포화지방, 콜레스테롤:
        실제 측정값이 표시량의 120% 미만이어야 한다. (상한 관리 영양소)
  - 탄수화물, 식이섬유, 단백질, 비타민, 무기질:
        실제 측정값이 표시량의 80% 이상이어야 한다. (하한 관리 영양소)

표시사항 영양성분은 1단계 OCR로 확보되어 있고, 공인기관 영양성분성적서의 실측값은
추후 OCR 후 ``measured`` 로 주입한다. 이 모듈은 값이 들어오면 적합/부적합을 계산하는
순수 로직만 제공한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from chandra.text_match import collapse as _norm


# 허용오차 관리 구분
UPPER_BOUND = "<=120%"  # 측정값 ≤ 표시량 × 1.2
LOWER_BOUND = ">=80%"  # 측정값 ≥ 표시량 × 0.8

UPPER_BOUND_RATIO = 1.20
LOWER_BOUND_RATIO = 0.80


# 영양성분명(별칭 포함) → 관리 구분
_NUTRIENT_RULES: dict[str, str] = {
    "열량": UPPER_BOUND,
    "칼로리": UPPER_BOUND,
    "kcal": UPPER_BOUND,
    "나트륨": UPPER_BOUND,
    "당류": UPPER_BOUND,
    "지방": UPPER_BOUND,
    "트랜스지방": UPPER_BOUND,
    "트랜스지방산": UPPER_BOUND,
    "포화지방": UPPER_BOUND,
    "포화지방산": UPPER_BOUND,
    "콜레스테롤": UPPER_BOUND,
    "탄수화물": LOWER_BOUND,
    "식이섬유": LOWER_BOUND,
    "단백질": LOWER_BOUND,
    "비타민": LOWER_BOUND,
    "무기질": LOWER_BOUND,
    "칼슘": LOWER_BOUND,
    "철": LOWER_BOUND,
}

# 표시값이 0(또는 "0으로 표시")일 때 허용하는 절대 오차(상한 관리 영양소).
# 「표시기준」의 '0 표시 가능' 저값 규정에 대응 — 필요 시 내규로 조정.
_ZERO_LABEL_ABS_TOLERANCE: dict[str, float] = {
    "열량": 5.0,  # kcal
    "나트륨": 5.0,  # mg
    "당류": 0.5,  # g
    "지방": 0.5,  # g
    "트랜스지방": 0.5,  # g
    "포화지방": 0.1,  # g
    "콜레스테롤": 5.0,  # mg
}


def rule_for(name: str) -> str | None:
    target = _norm(name)
    for key, rule in _NUTRIENT_RULES.items():
        if _norm(key) == target:
            return rule
    for key, rule in _NUTRIENT_RULES.items():
        nk = _norm(key)
        if nk and (nk in target or target in nk):
            return rule
    return None


@dataclass
class NutrientComparison:
    name: str
    label_value: float | None  # 표시량
    measured_value: float | None  # 성적서 실측값
    unit: str
    rule: str | None  # UPPER_BOUND / LOWER_BOUND
    threshold: float | None  # 허용 한계값
    ratio: float | None  # 측정/표시
    verdict: str  # 적합 / 부적합 / 판정불가
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NutritionReview:
    comparisons: list[NutrientComparison]
    overall_verdict: str  # 적합 / 부적합 / 판정불가
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparisons": [c.to_dict() for c in self.comparisons],
            "overall_verdict": self.overall_verdict,
            "reasons": self.reasons,
        }


def compare_nutrient(
    name: str,
    label_value: float | None,
    measured_value: float | None,
    unit: str = "",
) -> NutrientComparison:
    rule = rule_for(name)

    if label_value is None or measured_value is None:
        return NutrientComparison(
            name=name,
            label_value=label_value,
            measured_value=measured_value,
            unit=unit,
            rule=rule,
            threshold=None,
            ratio=None,
            verdict="판정불가",
            detail="표시값 또는 측정값 누락",
        )

    if rule is None:
        return NutrientComparison(
            name=name,
            label_value=label_value,
            measured_value=measured_value,
            unit=unit,
            rule=None,
            threshold=None,
            ratio=(measured_value / label_value if label_value else None),
            verdict="판정불가",
            detail="허용오차 규정이 정의되지 않은 영양성분",
        )

    ratio = (measured_value / label_value) if label_value else None

    if rule == UPPER_BOUND:
        if label_value == 0:
            tol = _ZERO_LABEL_ABS_TOLERANCE.get(_match_zero_key(name), 0.0)
            ok = measured_value <= tol
            threshold = tol
            detail = f"표시 0 → 절대허용 {tol}{unit} 이하 | 측정 {measured_value}{unit}"
        else:
            threshold = label_value * UPPER_BOUND_RATIO
            ok = measured_value <= threshold
            detail = (
                f"표시 {label_value}{unit} × 120% = {threshold:.4g}{unit} 이하 | "
                f"측정 {measured_value}{unit} ({ratio*100:.1f}%)"
            )
    else:  # LOWER_BOUND
        threshold = label_value * LOWER_BOUND_RATIO
        ok = measured_value >= threshold
        detail = (
            f"표시 {label_value}{unit} × 80% = {threshold:.4g}{unit} 이상 | "
            f"측정 {measured_value}{unit} ({ratio*100:.1f}%)"
            if ratio is not None
            else f"표시 {label_value}{unit} × 80% = {threshold:.4g}{unit} 이상 | 측정 {measured_value}{unit}"
        )

    return NutrientComparison(
        name=name,
        label_value=label_value,
        measured_value=measured_value,
        unit=unit,
        rule=rule,
        threshold=threshold,
        ratio=ratio,
        verdict="적합" if ok else "부적합",
        detail=detail,
    )


def _match_zero_key(name: str) -> str:
    target = _norm(name)
    for key in _ZERO_LABEL_ABS_TOLERANCE:
        nk = _norm(key)
        if nk == target or nk in target or target in nk:
            return key
    return name


def compare_nutrition(
    label: dict[str, float | None],
    measured: dict[str, float | None],
    units: dict[str, str] | None = None,
) -> NutritionReview:
    """표시사항 영양성분(label)과 성적서 실측(measured)을 비교.

    두 dict 모두 {영양성분명: 값}. units 는 {영양성분명: 단위} (선택).
    """
    units = units or {}
    names: list[str] = list(label.keys())
    for name in measured:
        if name not in names:
            names.append(name)

    comparisons: list[NutrientComparison] = []
    reasons: list[str] = []
    for name in names:
        cmp = compare_nutrient(
            name,
            label.get(name),
            measured.get(name),
            unit=units.get(name, ""),
        )
        comparisons.append(cmp)
        if cmp.verdict == "부적합":
            reasons.append(f"{name} 부적합: {cmp.detail}")
        elif cmp.verdict == "판정불가":
            reasons.append(f"{name} 판정불가: {cmp.detail}")

    if any(c.verdict == "부적합" for c in comparisons):
        overall = "부적합"
    elif any(c.verdict == "판정불가" for c in comparisons):
        overall = "판정불가"
    else:
        overall = "적합"

    return NutritionReview(
        comparisons=comparisons, overall_verdict=overall, reasons=reasons
    )


def nutrition_reference(
    food_type: str | None,
    nutrition: dict[str, float | None],
    basis: str | None = None,
) -> str | None:
    """식품유형 대비 영양성분 수준을 한 줄로 요약(참고용, 판정 아님).

    같은 식품유형의 일반적 수준과 비교해 높음/평균/낮음 정도를 짧게 코멘트한다.
    Gemma 호출 실패 시 None.
    """
    nut = {k: v for k, v in (nutrition or {}).items() if v is not None}
    if not food_type or not nut:
        return None
    from chandra.gemma_judge import judge_json

    sys = (
        "당신은 식품 영양 전문가입니다. 주어진 식품유형 제품의 영양성분을 '같은 식품유형의 일반적인 수준'과"
        " 비교해 한 줄(60자 내외)로 참고 코멘트만 작성합니다. 적합/부적합 판정·권고는 하지 마세요."
        " 높음/다소 높음/평균 수준/다소 낮음/낮음 같은 표현으로 핵심 1~3개 성분만 언급."
        ' 반드시 JSON 만: {"note": "..."}'
    )
    user = (
        f"식품유형: {food_type}\n기준단위: {basis or '미상'}\n"
        f"영양성분: {', '.join(f'{k}={v}' for k, v in nut.items())}\n"
        "같은 식품유형 일반 수준과 비교한 한 줄 참고 코멘트."
    )
    try:
        out = judge_json(sys, user)
        note = (out or {}).get("note")
        return note.strip() if isinstance(note, str) and note.strip() else None
    except Exception:  # noqa: BLE001
        return None
