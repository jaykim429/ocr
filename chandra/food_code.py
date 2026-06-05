"""식품공전(식품의 기준 및 규격) 식품유형별 규격 룰셋.

식품공전에서 한 식품유형(예: 기타수산물가공품)을 찾으면 다음 구조가 나온다:
    1) 정의
    2) 원료 등의 구비요건
    3) 제조·가공기준
    4) 식품유형
    5) 규격            <- 자가품질검사의 판정 기준이 되는 항목/수치

이 모듈은 그 구조를 데이터로 인코딩한다. 식품안전나라 식품공전 API가 인가되면
``load_standard_from_api`` 로 동적 로딩으로 대체할 수 있으나, 현재 발급된 키는
인허가(I2500)에만 인가되어 있어 정적 룰셋을 기본값으로 사용한다.

규격의 미생물 수치(세균수/대장균 n·c·m·M)는 식품공전 개정에 따라 달라질 수 있으므로
출처(``source``)를 명시하고, 성적서에 인쇄된 기준과 다를 경우 자동 '부적합'으로
판정하지 않고 '검토필요'로 플래그한다(self_quality.review_self_quality 참고).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 규격 항목의 판정 기준 모델
# ---------------------------------------------------------------------------


@dataclass
class MicroCriteria:
    """미생물 샘플링플랜 기준.

    3-class plan: (n, c, m, M) 모두 사용.
    2-class plan: M 을 None 으로 두고 m 을 한계값으로 사용.
    """

    n: int
    c: int
    m: float
    M: float | None = None
    unit: str = "CFU/g"

    def describe(self) -> str:
        if self.M is None:
            return f"n={self.n}, c={self.c}, m={self._fmt(self.m)} ({self.unit})"
        return (
            f"n={self.n}, c={self.c}, m={self._fmt(self.m)}, "
            f"M={self._fmt(self.M)} ({self.unit})"
        )

    @staticmethod
    def _fmt(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return str(value)


@dataclass
class LimitCriteria:
    """수치 한계 기준 (예: 휘발성염기질소 20 mg% 이하, 산가 5.0 이하)."""

    op: str  # "<=", "<", ">=", ">"
    value: float
    unit: str = ""

    def describe(self) -> str:
        return f"{self.op} {self.value} {self.unit}".strip()


@dataclass
class AbsenceCriteria:
    """'검출되어서는 아니 된다' 형태 기준 (타르색소, 보존료, 이물 등)."""

    expected: str = "불검출"  # 또는 "음성"

    def describe(self) -> str:
        return self.expected


Criteria = MicroCriteria | LimitCriteria | AbsenceCriteria


@dataclass
class QualitySpecItem:
    """식품공전 '규격'의 한 항목 = 자가품질검사 대상 항목 후보."""

    name: str
    criteria: Criteria | None = None
    aliases: tuple[str, ...] = ()
    required: bool = True  # 자가품질검사 필수 항목 여부
    applies_when: str | None = None  # 적용 조건 (예: "살균제품에 한함")
    source: str = "식품공전"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["criteria_text"] = self.criteria.describe() if self.criteria else None
        data["criteria_kind"] = type(self.criteria).__name__ if self.criteria else None
        return data


@dataclass
class FoodTypeStandard:
    """식품공전 한 식품유형 항목 전체 (정의~규격)."""

    food_type: str  # 식품유형 (예: 기타수산물가공품)
    category: str  # 식품군/식품종 (예: 수산가공식품류)
    definition: str  # 1) 정의
    raw_material_requirements: str  # 2) 원료 등의 구비요건
    processing_standards: str  # 3) 제조·가공기준
    spec_items: list[QualitySpecItem] = field(default_factory=list)  # 5) 규격
    aliases: tuple[str, ...] = ()  # 식품유형 표기 변형 매칭용
    notes: str = ""

    def required_items(self) -> list[QualitySpecItem]:
        return [item for item in self.spec_items if item.required]

    def to_dict(self) -> dict[str, Any]:
        return {
            "food_type": self.food_type,
            "category": self.category,
            "definition": self.definition,
            "raw_material_requirements": self.raw_material_requirements,
            "processing_standards": self.processing_standards,
            "spec_items": [item.to_dict() for item in self.spec_items],
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# 정적 룰셋 (식품공전 baseline). 내규로 덮어쓰거나 API 로딩으로 대체 가능.
# 수치는 식품공전 개정 시 확인 필요 — 출처를 함께 기재한다.
# ---------------------------------------------------------------------------

_GITA_SUSAN = FoodTypeStandard(
    food_type="기타수산물가공품",
    category="수산가공식품류",
    definition=(
        "수산물을 주원료로 하여 식용에 적합하도록 가공한 것으로서 다른 식품유형에 "
        "속하지 않는 것을 말한다."
    ),
    raw_material_requirements=(
        "사용하는 원료 수산물은 선도가 양호하고 식용에 적합하여야 하며, 부패·변질되었거나 "
        "유독·유해물질에 오염되지 않은 것이어야 한다."
    ),
    processing_standards=(
        "원료의 전처리·세척 후 위생적으로 가공하여야 하며, 냉동제품은 가공 후 신속히 "
        "냉동하여 -18℃ 이하에서 보관·유통하여야 한다."
    ),
    aliases=(
        "기타 수산물가공품",
        "기타수산물 가공품",
        "수산물가공품",
        "국내산 수산물가공품",
        "기타수산물가공품(가열하여 섭취하는 냉동식품)",
    ),
    notes=(
        "냉동·가열하여 섭취하는 제품에는 냉동식품(가열하여 섭취하는 냉동식품) 미생물 규격이 "
        "함께 적용된다. 미생물 수치 기준은 식품공전 최신본으로 재확인할 것."
    ),
    spec_items=[
        QualitySpecItem(
            name="성상",
            criteria=AbsenceCriteria(expected="고유의 색택·향미, 이미·이취 없음"),
            aliases=("관능", "성상검사"),
            required=False,
            source="식품공전 규격",
        ),
        QualitySpecItem(
            name="세균수",
            # 냉동식품(가열하여 섭취하는 냉동식품) 기준 — 식품공전 확인 필요
            criteria=MicroCriteria(n=5, c=2, m=100000, M=1000000, unit="CFU/g"),
            aliases=("일반세균", "총균수", "생균수", "세균수(생균수)"),
            required=True,
            applies_when="가열하여 섭취하는 냉동식품",
            source="식품공전 냉동식품 규격(가열 섭취)",
        ),
        QualitySpecItem(
            name="대장균",
            criteria=MicroCriteria(n=5, c=2, m=0, M=10, unit="CFU/g"),
            aliases=("E.coli", "대장균(정량)"),
            required=True,
            applies_when="가열하여 섭취하는 냉동식품",
            source="식품공전 냉동식품 규격(가열 섭취)",
        ),
        QualitySpecItem(
            name="대장균군",
            criteria=MicroCriteria(n=5, c=2, m=0, M=10, unit="CFU/g"),
            aliases=("coliform",),
            required=False,
            applies_when="살균제품/비가열 섭취 냉동식품",
            source="식품공전 냉동식품 규격",
        ),
        QualitySpecItem(
            name="타르색소",
            criteria=AbsenceCriteria(expected="불검출"),
            aliases=("타르 색소", "합성착색료"),
            required=False,
            applies_when="착색 의심 시",
            source="식품공전 규격",
        ),
        QualitySpecItem(
            name="보존료",
            criteria=AbsenceCriteria(expected="불검출(사용기준 외)"),
            aliases=("방부제", "소르빈산", "데히드로초산", "안식향산"),
            required=False,
            source="식품공전 규격",
        ),
    ],
)


STANDARDS: dict[str, FoodTypeStandard] = {
    _GITA_SUSAN.food_type: _GITA_SUSAN,
}


def _normalize(text: str) -> str:
    return "".join(text.split()).lower()


def lookup_standard(food_type: str | None) -> FoodTypeStandard | None:
    """식품유형 문자열로 룰셋을 조회한다 (공백 무시 + 별칭 + 부분일치)."""

    if not food_type:
        return None

    target = _normalize(food_type)

    # 1) 정식 명칭 정확 매칭
    for std in STANDARDS.values():
        if _normalize(std.food_type) == target:
            return std

    # 2) 별칭 정확 매칭
    for std in STANDARDS.values():
        for alias in std.aliases:
            if _normalize(alias) == target:
                return std

    # 3) 부분 포함 매칭 (예: "기타수산물가공품(가열하여...)" 안에 정식명 포함)
    for std in STANDARDS.values():
        keys = [std.food_type, *std.aliases]
        for key in keys:
            nkey = _normalize(key)
            if nkey and (nkey in target or target in nkey):
                return std

    return None
