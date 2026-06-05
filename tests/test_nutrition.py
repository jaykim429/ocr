from chandra.nutrition import (
    compare_nutrient,
    compare_nutrition,
    rule_for,
    UPPER_BOUND,
    LOWER_BOUND,
)


def test_rule_for_classifies_nutrients():
    assert rule_for("나트륨") == UPPER_BOUND
    assert rule_for("포화지방") == UPPER_BOUND
    assert rule_for("단백질") == LOWER_BOUND
    assert rule_for("탄수화물") == LOWER_BOUND


def test_upper_bound_pass_within_120pct():
    # 표시 550, 측정 600 → 109% < 120% → 적합
    cmp = compare_nutrient("나트륨", 550, 600, "mg")
    assert cmp.verdict == "적합"


def test_upper_bound_fail_over_120pct():
    # 표시 550, 측정 700 → 127% → 부적합
    cmp = compare_nutrient("나트륨", 550, 700, "mg")
    assert cmp.verdict == "부적합"


def test_lower_bound_pass_at_or_above_80pct():
    # 표시 21, 측정 18 → 85% ≥ 80% → 적합
    cmp = compare_nutrient("단백질", 21, 18, "g")
    assert cmp.verdict == "적합"


def test_lower_bound_fail_below_80pct():
    # 표시 21, 측정 15 → 71% → 부적합
    cmp = compare_nutrient("단백질", 21, 15, "g")
    assert cmp.verdict == "부적합"


def test_zero_label_uses_absolute_tolerance():
    # 당류 표시 0 → 절대허용 0.5g 이하
    assert compare_nutrient("당류", 0, 0.3, "g").verdict == "적합"
    assert compare_nutrient("당류", 0, 0.9, "g").verdict == "부적합"


def test_missing_value_is_indeterminate():
    assert compare_nutrient("지방", 1.8, None, "g").verdict == "판정불가"


def test_compare_nutrition_overall():
    # 표시사항(1단계 OCR) 기준 + 가상의 성적서 실측값
    label = {
        "열량": 102,
        "나트륨": 550,
        "탄수화물": 1.0,
        "당류": 0,
        "지방": 1.8,
        "트랜스지방": 0,
        "포화지방": 0.4,
        "콜레스테롤": 132,
        "단백질": 21,
    }
    measured = {
        "열량": 110,
        "나트륨": 600,
        "탄수화물": 1.1,
        "당류": 0.2,
        "지방": 2.0,
        "트랜스지방": 0,
        "포화지방": 0.45,
        "콜레스테롤": 140,
        "단백질": 19,
    }
    review = compare_nutrition(label, measured)
    assert review.overall_verdict == "적합"
    assert len(review.comparisons) == len(label)


def test_compare_nutrition_flags_fail():
    label = {"나트륨": 550, "단백질": 21}
    measured = {"나트륨": 700, "단백질": 21}  # 나트륨 127% → 부적합
    review = compare_nutrition(label, measured)
    assert review.overall_verdict == "부적합"
    assert any("나트륨" in r for r in review.reasons)
