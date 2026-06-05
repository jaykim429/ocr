from chandra.food_code import (
    AbsenceCriteria,
    LimitCriteria,
    MicroCriteria,
    lookup_standard,
)
from chandra.self_quality import (
    ManufactureReport,
    QualityCertificate,
    ReportTestItem,
    cross_check_documents,
    evaluate_micro,
    parse_criteria_text,
    parse_number,
    parse_results,
    review_self_quality,
)


# --- 파서 -------------------------------------------------------------------


def test_parse_number_handles_scaling_and_scientific():
    assert parse_number("1,000,000") == 1_000_000
    assert parse_number("5×10^6") == 5_000_000
    assert parse_number("20 이하") == 20
    assert parse_number("1.8g") == 1.8


def test_parse_results_splits_list():
    assert parse_results("340, 180, 260, 310, 490") == [340, 180, 260, 310, 490]
    assert parse_results("0, 0, 0, 0, 0") == [0, 0, 0, 0, 0]


def test_parse_criteria_micro():
    crit = parse_criteria_text("n=5, c=2, m=0, M=10")
    assert isinstance(crit, MicroCriteria)
    assert (crit.n, crit.c, crit.m, crit.M) == (5, 2, 0, 10)


def test_parse_criteria_absence_and_limit():
    assert isinstance(parse_criteria_text("불검출"), AbsenceCriteria)
    assert isinstance(parse_criteria_text("음성"), AbsenceCriteria)
    limit = parse_criteria_text("20 mg% 이하")
    assert isinstance(limit, LimitCriteria)
    assert limit.op == "<=" and limit.value == 20


def test_parse_criteria_diverse_report_formats():
    # 곰팡이독소(아플라톡신) 복합기준 → 주 기준 수치 사용
    afla = parse_criteria_text("15.0 ug/kg 이하(B1, B2, G1, G2의 합으로서, 단 B1은 10.0 ug/kg 이하)")
    assert isinstance(afla, LimitCriteria)
    assert afla.op == "<=" and afla.value == 15.0
    # 중금속 mg/kg
    pb = parse_criteria_text("0.07 mg/kg 이하")
    assert isinstance(pb, LimitCriteria)
    assert pb.value == 0.07


# --- 미생물 판정 -------------------------------------------------------------


def test_evaluate_micro_pass_when_all_below_m():
    crit = MicroCriteria(n=5, c=2, m=0, M=10)
    verdict, _ = evaluate_micro(crit, [0, 0, 0, 0, 0])
    assert verdict == "적합"


def test_evaluate_micro_fail_when_over_M():
    crit = MicroCriteria(n=5, c=2, m=0, M=10)
    verdict, _ = evaluate_micro(crit, [0, 0, 0, 0, 20])
    assert verdict == "부적합"


def test_evaluate_micro_fail_when_marginal_exceeds_c():
    crit = MicroCriteria(n=5, c=2, m=0, M=10)
    # 3 samples in (m, M] but c=2 allows only 2
    verdict, _ = evaluate_micro(crit, [5, 5, 5, 0, 0])
    assert verdict == "부적합"


# --- 식품공전 룰셋 조회 ------------------------------------------------------


def test_lookup_standard_matches_alias():
    std = lookup_standard("기타수산물가공품(가열하여 섭취하는 냉동식품)")
    assert std is not None
    assert std.food_type == "기타수산물가공품"
    names = {s.name for s in std.required_items()}
    assert {"세균수", "대장균"} <= names


# --- 교차대조 ---------------------------------------------------------------


def test_cross_check_consistent():
    mfr = ManufactureReport(
        product_name="국내산 꼬마 박대",
        food_type="기타수산물가공품",
        manufacture_report_no="2020052926415",
        business_name="유한회사 알찬푸드",
    )
    cert = QualityCertificate(
        product_name="국내산 꼬마 박대",
        food_type="기타수산물가공품",
        manufacture_report_no="2020052926415",
        manufacturer="유한회사 알찬푸드",
    )
    result = cross_check_documents(mfr, cert)
    assert result.consistent is True


def test_cross_check_tolerates_ocr_and_entity_diff():
    # 삼향↔삼황 OCR 오인식, (유)↔유한회사 법인표기 차이는 일치로 본다
    mfr = ManufactureReport(
        product_name="국내산 꼬마 박대",
        food_type="기타수산물가공품",
        manufacture_report_no="2020052926415",
        business_name="유한회사 알찬푸드",
    )
    cert = QualityCertificate(
        product_name="국내산 꼬마 박대",
        food_type="기타수산물가공품",
        manufacture_report_no="2020052926415",
        manufacturer="(유)알찬푸드",
    )
    result = cross_check_documents(mfr, cert)
    assert result.consistent is True


def test_cross_check_flags_mismatch():
    mfr = ManufactureReport(
        product_name="국내산 꼬마 박대", manufacture_report_no="2020052926415"
    )
    cert = QualityCertificate(
        product_name="수입 박대", manufacture_report_no="9999999999999"
    )
    result = cross_check_documents(mfr, cert)
    assert result.consistent is False
    assert any("제품명" in r for r in result.reasons)


# --- 종합 검토 (실제 샘플 값) ------------------------------------------------


def _sample_certificate() -> QualityCertificate:
    return QualityCertificate(
        product_name="국내산 꼬마 박대",
        food_type="기타수산물가공품",
        manufacture_report_no="2020052926415",
        manufacturer="유한회사 알찬푸드",
        items=[
            ReportTestItem(
                name="대장균",
                criteria_text="n=5, c=2, m=0, M=10",
                results_text="0, 0, 0, 0, 0",
                results=parse_results("0, 0, 0, 0, 0"),
                judgement_text="적합",
            ),
            ReportTestItem(
                name="세균수",
                criteria_text="n=5, c=2, m=1000000, M=5000000",
                results_text="340, 180, 260, 310, 490",
                results=parse_results("340, 180, 260, 310, 490"),
                judgement_text="적합",
            ),
        ],
        overall_text="적합",
    )


def test_review_sample_results_all_pass_no_missing():
    review = review_self_quality(_sample_certificate())
    by_name = {e.name: e for e in review.item_evaluations}
    # 인쇄 기준으로 재계산 시 두 항목 모두 적합
    assert by_name["대장균"].computed_verdict == "적합"
    assert by_name["세균수"].computed_verdict == "적합"
    # 세균수/대장균 모두 존재 → 필수항목 누락 없음
    assert review.missing_required_items == []
    # 결과는 적합이나 세균수 기준이 룰셋과 달라 검토필요로 떨어질 수 있음
    assert review.overall_verdict in ("적합", "검토필요")


def test_review_detects_missing_required_item():
    cert = _sample_certificate()
    cert.items = [cert.items[1]]  # 세균수만 남기고 대장균 제거
    review = review_self_quality(cert)
    assert "대장균" in review.missing_required_items
    assert review.overall_verdict in ("검토필요", "부적합")


def test_review_marks_fail_when_result_exceeds_criteria():
    cert = _sample_certificate()
    cert.items[0] = ReportTestItem(
        name="대장균",
        criteria_text="n=5, c=2, m=0, M=10",
        results_text="0, 0, 0, 0, 50",
        results=parse_results("0, 0, 0, 0, 50"),
        judgement_text="적합",  # 성적서엔 적합이라 인쇄됐지만 재계산은 부적합
    )
    review = review_self_quality(cert)
    coli = next(e for e in review.item_evaluations if e.name == "대장균")
    assert coli.computed_verdict == "부적합"
    assert coli.verdict_mismatch is True
    assert review.overall_verdict == "부적합"
