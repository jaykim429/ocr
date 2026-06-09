"""신규 QA 기능 회귀테스트 — 순수 로직(네트워크/Gemma 불필요).

다제품 그룹핑, 식품유형 합의, 기본정보 출처우선, 자가품질 검사주기,
고시 첨부 파서 유틸, 잡 영속화(SQLite)를 검증한다.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from chandra.extraction import DOC_LABEL, DOC_NUTRITION_CERT, DOC_PRODUCT_REPORT, DOC_SELF_QUALITY


# ---------------------------------------------------------------------------
# 다제품 그룹핑 (_group_by_product)
# ---------------------------------------------------------------------------
def test_group_single_product_absorbs_unnamed_label():
    from chandra.pipeline import _group_by_product

    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "인생 촉촉 노가리", "manufacture_report_no": "20210488859"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "인생촉촉노가리"},
        {"doc_type": DOC_LABEL, "product_name": None},  # 이름 없는 표시사항
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 1
    assert len(cl[0]["docs"]) == 3


def test_group_by_report_no_when_names_differ():
    """OCR 로 제품명이 달라도 품목보고번호가 같으면 한 제품."""
    from chandra.pipeline import _group_by_product

    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "워커힐 폭립", "manufacture_report_no": "20200397042001"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "위커협 폭립", "manufacture_report_no": "20200397042001"},
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 1


def test_group_merged_two_products_split_by_report_no():
    """병합 PDF 다제품: 보고번호가 다르면 분리."""
    from chandra.pipeline import _group_by_product

    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "정읍쌍화차", "manufacture_report_no": "202206873501"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "정읍쌍화차", "manufacture_report_no": "202206873501"},
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "쌍화밤고명", "manufacture_report_no": "202206873507"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "쌍화밤고명", "manufacture_report_no": "202206873507"},
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 2


def test_merge_complementary_orphan_cert():
    """성적서(보고번호 ...831)가 보고서·라벨(...832)과 업체·주소 같고 문서종류 보완적이면
    1제품으로 병합 + 보고번호/제품명 불일치 기록(OCR 1자리 차이)."""
    from chandra.pipeline import _group_by_product

    addr = "충청남도 당진시 송악읍 농장길 336-66"
    ext = [
        {"doc_type": DOC_SELF_QUALITY, "product_name": "감단 민물장어 양념구이", "manufacture_report_no": "202406940831", "address": addr},
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "간장 양념 민물장어구이", "manufacture_report_no": "202406940832", "address": addr},
        {"doc_type": DOC_LABEL, "product_name": "간장 양념 민물장어구이", "manufacture_report_no": "202406940832", "address": "충남 당진시 송악읍 농장길 336-35"},
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 1
    assert cl[0].get("doc_mismatch")  # 보고번호 불일치 기록됨


def test_no_merge_two_complete_products_same_factory():
    """같은 공장의 진짜 다른 SKU(둘 다 보고서 보유)는 보고번호 인접해도 병합하지 않는다."""
    from chandra.pipeline import _group_by_product

    addr = "충청남도 당진시 송악읍 농장길 336-66"
    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "제품가", "manufacture_report_no": "202406940831", "address": addr},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "제품가", "manufacture_report_no": "202406940831", "address": addr},
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "제품나", "manufacture_report_no": "202406940832", "address": addr},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "제품나", "manufacture_report_no": "202406940832", "address": addr},
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 2


def test_group_floating_label_attaches_by_address():
    """제품명 없는 표시사항이 같은 공장주소의 '라벨 없는' 제품에 붙는다."""
    from chandra.pipeline import _group_by_product

    addr = "충청남도 아산시 음봉면 음봉로 829"
    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "호두아몬드", "manufacture_report_no": "19930461022270", "address": addr},
        {"doc_type": DOC_LABEL, "product_name": "호두아몬드", "address": addr},
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "검은콩", "manufacture_report_no": "19930461022269", "address": addr},
        {"doc_type": DOC_LABEL, "product_name": None, "address": addr},  # 깨진 라벨
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 2
    # 깨진 라벨은 라벨 없던 '검은콩'에 흡수 → (제품 미상) 클러스터 없음
    assert all(c["name"] != "(제품 미상)" for c in cl)
    geomeun = next(c for c in cl if "검은콩" in (c["key"] or ""))
    assert any(d["doc_type"] == DOC_LABEL for d in geomeun["docs"])


# ---------------------------------------------------------------------------
# 식품유형 합의 (_resolve_food_type)
# ---------------------------------------------------------------------------
def test_resolve_food_type_prefers_report_over_label(monkeypatch):
    import chandra.foodsafety as fs
    from chandra import pipeline

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])  # 네트워크 차단
    by_type = {
        DOC_PRODUCT_REPORT: {"food_type": "가공두유"},
        DOC_LABEL: {"food_type": "가공유"},  # 라벨 OCR 오인식
    }
    r = pipeline._resolve_food_type(by_type)
    assert r["value"] == "가공두유"
    assert r["source"] == DOC_PRODUCT_REPORT
    assert r["mismatch"] is True


def test_resolve_food_type_no_mismatch(monkeypatch):
    import chandra.foodsafety as fs
    from chandra import pipeline

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [{"product_type": "떡류"}])
    by_type = {DOC_PRODUCT_REPORT: {"food_type": "떡류"}, DOC_SELF_QUALITY: {"food_type": "떡류"}}
    r = pipeline._resolve_food_type(by_type)
    assert r["value"] == "떡류" and r["mismatch"] is False and r["registered"] is True


# ---------------------------------------------------------------------------
# 기본정보 출처 우선순위 (_basic_info)
# ---------------------------------------------------------------------------
def test_basic_info_source_priority(monkeypatch):
    import chandra.foodsafety as fs
    from chandra import pipeline

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])
    by_type = {
        DOC_PRODUCT_REPORT: {"product_name": "보고서명", "business_name": "제조사", "license_no": "12345678901"},
        DOC_LABEL: {"product_name": "라벨명"},
    }
    rows = {r["field"]: r for r in pipeline._basic_info(by_type)}
    assert rows["제품명"]["value"] == "보고서명"
    assert rows["제품명"]["source"] == DOC_PRODUCT_REPORT
    assert rows["영업등록번호"]["value"] == "12345678901"


# ---------------------------------------------------------------------------
# 자가품질 검사주기 (별표12)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ft,months", [("떡류", 3), ("가공두유", 2), ("양념육", 1), ("탁주", 6), ("조미건어포", 3), ("즉석판매제조가공", 9)])
def test_test_cycle_months(ft, months):
    from chandra.self_quality import test_cycle_months

    assert test_cycle_months(ft) == months


def test_validity_fixed_six_months(monkeypatch):
    """유효기간은 발급일+6개월 고정(현대홈쇼핑 기준) — 식품유형 주기와 무관."""
    import chandra.foodsafety as fs
    from datetime import date
    from chandra.self_quality import build_self_quality_evidence, QualityCertificate

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])
    cert = QualityCertificate(food_type="기타식물성유지", issue_date="2026-04-01")
    ev = build_self_quality_evidence(cert, None, None, today=date(2026, 6, 5))
    assert ev["유효기간"]["valid_months"] == 6
    assert ev["유효기간"]["valid"] is True  # 4/1 + 6개월 = 10/1, 6/5엔 유효
    # 발급 7개월 전이면 만료
    cert2 = QualityCertificate(food_type="기타식물성유지", issue_date="2025-11-01")
    ev2 = build_self_quality_evidence(cert2, None, None, today=date(2026, 6, 5))
    assert ev2["유효기간"]["valid"] is False


def test_self_tested_when_agency_is_manufacturer(monkeypatch):
    """검사기관=제조사 본인이면 영업자 직접 자가품질검사로 인정."""
    import chandra.foodsafety as fs
    from datetime import date
    from chandra.self_quality import build_self_quality_evidence, QualityCertificate

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])
    cert = QualityCertificate(
        food_type="기타식물성유지", issue_date="2026-05-20",
        test_agency="주식회사 노바렉스 2공장", manufacturer="주식회사 노바렉스 2공장",
    )
    ev = build_self_quality_evidence(cert, None, None, today=date(2026, 6, 5))
    assert ev["검사기관_제조사동일_자체검사"] is True


# ---------------------------------------------------------------------------
# 소재지 매칭 (시·도 약칭↔정식명)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 검사기관 검증 — 지정 만료(B3) · 식품/축산물 분야(B4)
# ---------------------------------------------------------------------------
def test_verify_agency_designation_expired():
    from datetime import date
    from chandra.test_agencies import TestAgency, verify_agency

    db = [TestAgency(name="한국기능식품연구원", designation_no="제38호", category="식품",
                     valid_until="26.5.20")]
    v = verify_agency("한국기능식품연구원", "식품 제38호", db=db, today=date(2026, 6, 5))
    assert v.found is True
    assert v.designation_expired is True  # 26.5.20 < 2026-06-05


def test_verify_agency_category_mismatch_blocks_designation_match():
    from datetime import date
    from chandra.test_agencies import TestAgency, verify_agency

    db = [TestAgency(name="식품연구원", designation_no="제26호", category="식품", valid_until="27.1.1")]
    # 성적서는 '축산물 제26호' — 같은 번호라도 분야가 달라 지정번호로 인정되면 안 됨
    v = verify_agency("전혀다른이름", "축산물 제26호", db=db, today=date(2026, 6, 5))
    assert v.match_basis != "designation_no"


# ---------------------------------------------------------------------------
# 자체검사 정확일치(B2) · 불검출 '0' 오판 제거(B5)
# ---------------------------------------------------------------------------
def test_self_tested_requires_exact_name(monkeypatch):
    import chandra.foodsafety as fs
    from datetime import date
    from chandra.self_quality import build_self_quality_evidence, QualityCertificate

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])
    # 검사기관이 제조사와 '유사하지만 다른' 외부기관 → 자체검사로 인정하면 안 됨
    cert = QualityCertificate(food_type="기타식물성유지", issue_date="2026-05-20",
                              test_agency="노바렉스분석센터", manufacturer="주식회사 노바렉스")
    ev = build_self_quality_evidence(cert, None, None, today=date(2026, 6, 5))
    assert ev["검사기관_제조사동일_자체검사"] is False


@pytest.mark.parametrize("result,verdict", [
    ("0.5", "판정불가"),          # 숫자만 → '0' 오판 방지
    ("불검출", "적합"),
    ("검출", "부적합"),
    ("0.5 검출", "부적합"),
    ("검출한계 미만", "적합"),     # 검출한계 미만 = 사실상 불검출(부적합 오판 방지)
    ("정량한계 미만", "적합"),
    ("초과 항목 없음", "판정불가"),  # '없음' 문맥은 양성 아님
])
def test_evaluate_absence(result, verdict):
    from chandra.self_quality import AbsenceCriteria, evaluate_absence

    assert evaluate_absence(AbsenceCriteria(), result)[0] == verdict


def test_nutrition_unit_conversion_and_tolerance():
    """성적서 100g당 → 표시 제공량(180g)당 환산 후 별지1 허용오차(120%/80%) 적용."""
    from chandra.nutrition import compare_nutrition, convert_to_label_basis, parse_basis

    assert parse_basis("100g당") == (100.0, "g")
    assert parse_basis("총 내용량(180mL)당") == (180.0, "ml")
    measured = {"열량": 100.0, "단백질": 7.0}  # 성적서 100g당
    conv, note = convert_to_label_basis(measured, "100g당", "총 내용량(180g)당")
    assert round(conv["열량"], 1) == 180.0 and round(conv["단백질"], 1) == 12.6  # ×1.8
    assert "×1.8" in note
    # 표시 열량 100(상한): 측정 환산 180이 120%(=120) 초과 → 부적합
    r = compare_nutrition({"열량": 100.0}, {"열량": 180.0})
    assert r.overall_verdict == "부적합"
    # 표시 단백질 15(하한): 측정 12.6이 80%(=12) 이상 → 적합
    assert compare_nutrition({"단백질": 15.0}, {"단백질": 12.6}).overall_verdict == "적합"


def test_cross_check_patent():
    """표시 특허번호 ↔ 제출 근거자료(특허등록증) 교차대조."""
    from chandra.pipeline import _cross_check

    ok = _cross_check([{"patent_no": "특허 1017597790000호"}], {"1017597790000"})
    assert ok["verdict"] == "안내" and ok["has_issue"] is False
    miss = _cross_check([{"patent_no": "1017597790000"}], set())
    assert miss["verdict"] == "검토필요" and miss["has_issue"] is True
    assert _cross_check([{}], set()) is None  # 특허 표기 없으면 플래그 없음


def test_verify_agency_category_guard_on_tel():
    """전화번호 접미가 우연히 일치해도 분야(식품/축산물)가 다르면 매칭하지 않는다."""
    from datetime import date
    from chandra.test_agencies import TestAgency, verify_agency

    db = [TestAgency(name="식품기관", designation_no="제50호", category="식품", tel="031-111-2222", valid_until="27.1.1")]
    v = verify_agency("축산검사소", "축산물 제50호", tel="031-111-2222", db=db, today=date(2026, 6, 8))
    assert v.found is False


@pytest.mark.parametrize("q,addr,ok", [
    ("경상북도", "경상북도 칠곡군 지천면", True),
    ("경북", "경상북도 칠곡군", True),
    ("전북특별자치도", "전라북도 전주시", True),
    ("서울특별시", "경기도 성남시", False),
    ("신동로7길", "경상북도 칠곡군 지천면 신동로7길 92", True),
])
def test_address_matches(q, addr, ok):
    from chandra.foodsafety import _address_matches

    assert _address_matches(q, addr) is ok


# ---------------------------------------------------------------------------
# 식품유형 합의 — 보고서 미등록 표기 vs 2개 서류 합의
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ft,purpose,desig,ok", [
    ("양념육", None, None, True),
    ("기타식물성유지", "축산물 | 자가품질위탁검사", None, True),
    (None, None, "축산물 제26호", True),
    ("떡류", None, None, False),
    ("기타식물성유지", "자가품질위탁검사", "식품 제099호", False),
])
def test_is_livestock_product(ft, purpose, desig, ok):
    from chandra.self_quality import _is_livestock_product

    assert _is_livestock_product(ft, purpose, desig) is ok


@pytest.mark.parametrize("label,official,flagged", [
    # 읍 이름 '전치'(수내↔내수, 같은 글자 순서만 바뀜) → 실제 오기 → 검토 대상
    ("충북 청주시 청원구 수내읍 청암로 192-21", "충청북도 청주시 청원구 내수읍 청암로 192-21", True),
    # 시도 약칭 차이만 → 동일(이상 없음)
    ("충북 청주시 청원구 내수읍 청암로 192-21", "충청북도 청주시 청원구 내수읍 청암로 192-21", False),
    # 괄호 건물명만 추가 → 동일
    ("경상북도 칠곡군 지천면 신동로7길 92(동명동)", "경상북도 칠곡군 지천면 신동로7길 92", False),
    # 명칭 '치환'(글자 자체가 다름: 송악읍↔승낙음, 철곡↔칠곡, 각리1길↔각리니길) = OCR → 비플래그(VLM 위임)
    ("충남 당진시 송악읍 농장길 100", "충남 당진시 승낙음 농장길 100", False),
    ("충북 청주시 청원구 오창읍 각리1길 60", "충북 청주시 청원구 오창읍 각리니길 60", False),
    # 번지(숫자) 차이는 실제 차이 → 검토 대상 (336-35↔336-66, 10↔12 등)
    ("충남 당진시 송악읍 농장길 336-35", "충남 당진시 송악읍 농장길 336-66", True),
    ("서울 강남구 테헤란로 10", "서울 강남구 테헤란로 12", True),
])
def test_label_address_discrepancy(label, official, flagged):
    from chandra.address import label_address_discrepancy

    assert (label_address_discrepancy(label, official) is not None) is flagged


def test_food_type_consensus_override(monkeypatch):
    """보고서='육식간조리세트'(미등록) vs 성적서·표시사항='양념육' → 합의값 채택."""
    import chandra.foodsafety as fs
    from chandra import pipeline

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])  # 둘 다 미등록
    by_type = {
        DOC_PRODUCT_REPORT: {"food_type": "육식간조리세트"},
        DOC_SELF_QUALITY: {"food_type": "양념육"},
        DOC_LABEL: {"food_type": "양념육"},
    }
    r = pipeline._resolve_food_type(by_type)
    assert r["value"] == "양념육"
    assert r["consensus_override"] is True


def test_food_type_consensus_override_even_if_report_registered(monkeypatch):
    """보고서 값이 식품공전 등록 표기여도(식육간편조리세트) 2개 서류 합의(양념육)가 이기게."""
    import chandra.foodsafety as fs
    from chandra import pipeline

    # '식육간편조리세트'는 등록된 것처럼, '양념육'은 미등록처럼 응답
    monkeypatch.setattr(fs, "search_food_spec",
                        lambda t, *a, **k: [{"product_type": "식육간편조리세트"}] if "간편" in t else [])
    by_type = {
        DOC_PRODUCT_REPORT: {"food_type": "식육간편조리세트"},
        DOC_SELF_QUALITY: {"food_type": "양념육"},
        DOC_LABEL: {"food_type": "양념육"},
    }
    r = pipeline._resolve_food_type(by_type)
    assert r["value"] == "양념육"
    assert r["consensus_override"] is True


# ---------------------------------------------------------------------------
# 고시 첨부 파서 유틸 (law_attachment)
# ---------------------------------------------------------------------------
def test_clean_part_name():
    from chandra.law_attachment import _clean_part_name

    assert _clean_part_name("(1) 제1~제5_개정.hwpx") == "(1) 제1~제5"
    assert _clean_part_name("dir/건강기능식품의 기준 및 규격_(제1~제3).hwpx") == "제1~제3"


def test_part_order():
    from chandra.law_attachment import _part_order

    assert _part_order("(1) 제1.hwpx") == (1, 0)
    assert _part_order("(3-2) 제8.4.hwp") == (3, 2)
    assert _part_order("이름없음.hwp") == (999, 0)


def test_demote_headings():
    from chandra.law_attachment import _demote_headings

    assert _demote_headings("# 제목\n본문\n## 소제목") == "## 제목\n본문\n### 소제목"


def test_is_hwpx_package_and_strip_images():
    from chandra.law_attachment import _is_hwpx_package, _strip_hwpx_images

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", "<x/>")
        z.writestr("BinData/image1.bmp", b"\x00" * 100)
    data = buf.getvalue()
    assert _is_hwpx_package(data) is True
    slim = _strip_hwpx_images(data)
    names = zipfile.ZipFile(io.BytesIO(slim)).namelist()
    assert "BinData/image1.bmp" not in names and "Contents/section0.xml" in names


# ---------------------------------------------------------------------------
# 잡 영속화 (SQLite) — 재시작에도 결과 유지
# ---------------------------------------------------------------------------
def test_jobs_persistence(monkeypatch, tmp_path):
    from chandra_api import jobs

    monkeypatch.setattr(jobs, "_WORK_ROOT", tmp_path)
    monkeypatch.setattr(jobs, "_DB_PATH", tmp_path / "jobs.db")

    jid = jobs.create_job("a.zip", "u1")
    jobs._set(jid, status="running", started=jobs._now())
    jobs._set(jid, status="done", finished=jobs._now(),
              result={"units": [{"products": [{"overall": "적합"}, {"overall": "부적합"}]}]})

    j = jobs.get_job(jid)
    assert j["status"] == "done"
    assert len(j["result"]["units"]) == 1

    lst = jobs.list_jobs("u1")
    assert len(lst) == 1
    assert lst[0]["overall"] == "부적합"  # units 전체 최악
    assert "result" not in lst[0]  # 목록에는 결과 본문 제외


# ---------------------------------------------------------------------------
# 감시목록 고시 → 표시사항 자동연결(프롬프트 그라운딩) 트리거 검증
# ---------------------------------------------------------------------------
def test_law_rules_gmo_trigger_on_crop_only():
    from chandra.law_rules import applicable_rules

    names = lambda ft, t: [r["name"] for r in applicable_rules(ft, t)]
    # 대두(GMO 작물) → GMO 표시기준 적용
    assert "유전자변형식품등의 표시기준" in names("가공두유", "원재료 대두, 정제수")
    # 수산물(천일염·명태) → GMO 작물 없음 → 미적용
    assert "유전자변형식품등의 표시기준" not in names("기타수산물가공품", "명태 천일염")


def test_law_rules_haccp_only_when_marked():
    from chandra.law_rules import applicable_rules

    names = lambda ft, t: [r["name"] for r in applicable_rules(ft, t)]
    assert "식품 및 축산물 안전관리인증기준" in names("과자", "HACCP 인증 제품")
    assert "식품 및 축산물 안전관리인증기준" not in names("과자", "밀 설탕")


def test_law_rules_haccp_check_keyword():
    """식품유형이 건강기능식품일 때만 건기식 표시기준 적용."""
    from chandra.law_rules import applicable_rules

    names = lambda ft, t: [r["name"] for r in applicable_rules(ft, t)]
    assert "건강기능식품의 표시기준" in names("건강기능식품", "홍삼농축액")
    assert "건강기능식품의 표시기준" not in names("가공두유", "대두")


def test_law_rules_grounding_block_contains_applied():
    from chandra.law_rules import grounding_block

    block = grounding_block("가공두유", "원재료 대두 / 포장재질 멸균팩 / HACCP")
    assert "유전자변형식품등의 표시기준" in block
    assert "분리배출" in block
    assert block.startswith("\n\n[적용 법령")


# ---------------------------------------------------------------------------
# 성적서 OCR 권위 교차대조 가드 + 조리법→그대로섭취 아님(대장균 면제)
# ---------------------------------------------------------------------------
def test_cross_check_ocr_authority_resolves_misread():
    """성적서 Gemma 추출이 오독(한돌/토마토)해도 OCR 원문에 보고서값이 있으면 일치 처리."""
    from chandra.self_quality import (
        ManufactureReport, QualityCertificate, cross_check_documents,
    )

    ocr = "제품명 한둘국산 도토리묵가루 전분 업체명 농업회사법인 한둘 주식회사"
    cert = QualityCertificate(product_name="한돌 국산 토마토가루 전분",
                              manufacturer="농업회사법인 한돌 주식회사",
                              food_type="전분가공품", ocr_text=ocr)
    mfr = ManufactureReport(product_name="한둘 국산 도토리묵가루 전분",
                            business_name="농업회사법인 한둘(주)", food_type="전분가공품")
    assert cross_check_documents(mfr, cert).consistent is True


def test_cross_check_real_mismatch_still_flagged():
    """OCR 원문에도 보고서값이 없으면(진짜 다른 서류) 불일치로 잡는다."""
    from chandra.self_quality import (
        ManufactureReport, QualityCertificate, cross_check_documents,
    )

    cert = QualityCertificate(product_name="완전 다른 제품", food_type="과자류",
                              ocr_text="완전 다른 제품 다른회사")
    mfr = ManufactureReport(product_name="한둘 국산 도토리묵가루 전분", food_type="전분가공품")
    assert cross_check_documents(mfr, cert).consistent is False


def test_requires_cooking_detection():
    from chandra.self_quality import _requires_cooking

    assert _requires_cooking("조리방법: 끓는 물에 풀어 끓여 드세요") is True
    assert _requires_cooking("냄비에 묵가루와 물을 넣고 저어주며 끓입니다") is True
    assert _requires_cooking("개봉 후 그대로 드시면 됩니다") is False


# ---------------------------------------------------------------------------
# 보편성(오버피팅 방지) 가드: 짧은 일반명 거짓일치 방지 / 발급일 우선순위
# ---------------------------------------------------------------------------
def test_cross_check_guard_ignores_short_generic_name():
    """짧고 일반적인 명칭(김치)은 다른 성적서에 우연히 포함돼도 일치로 보지 않는다."""
    from chandra.self_quality import (
        ManufactureReport, QualityCertificate, cross_check_documents,
    )

    # cert 추출(주스류)은 보고서(우유)와 불일치. 보고서값 '우유'(2자)가 cert OCR에 우연히
    # 포함('초코우유')돼도 변별력 부족(6자 미만)이라 가드 미적용 → 불일치 유지.
    cert = QualityCertificate(product_name="주스류",
                              ocr_text="초코우유 외 1종 시험성적서")
    mfr = ManufactureReport(product_name="우유")
    assert cross_check_documents(mfr, cert).consistent is False


def test_issue_date_prefers_issuance_over_completion():
    """발급일/발행일이 있으면 검사완료일보다 우선(검사완료가 더 이르면 거짓 만료 방지)."""
    from chandra.pipeline import _issue_date_from_ocr

    ocr = "검사완료일 2025-01-10 ... 발급일 2025-03-20"
    assert _issue_date_from_ocr(ocr) == "2025-03-20"
    # 발급/발행 라벨이 없으면 검사완료일을 차순위로 사용
    assert _issue_date_from_ocr("검사완료일 2025-10-31 접수 2025-10-28") == "2025-10-31"


# ---------------------------------------------------------------------------
# 클러스터2: 공식주소 단일화(L1) / 보고번호 OCR 폴백(A4) / 주소 중복표출 제거(L2)
# ---------------------------------------------------------------------------
def test_official_address_unified_with_permit_fallback():
    from chandra.pipeline import _official_address
    from chandra.extraction import DOC_PRODUCT_REPORT, DOC_LICENSE

    # 보고서 주소 우선
    assert _official_address({DOC_PRODUCT_REPORT: {"address": "경기도 여주시 가남읍"}}, None) == "경기도 여주시 가남읍"
    # 보고서 주소 결측 → 영업등록증 주소로 보완(과거 mfr.address 크래시 케이스)
    assert _official_address({}, [{"doc_type": DOC_LICENSE, "address": "서울시 강남구"}]) == "서울시 강남구"
    assert _official_address({}, None) is None


def test_report_no_from_ocr():
    from chandra.pipeline import _report_no_from_ocr

    assert _report_no_from_ocr("품목제조신고번호 20070375129311 / 식품유형") == "20070375129311"
    assert _report_no_from_ocr("품목보고번호: 1234567890123") == "1234567890123"
    assert _report_no_from_ocr("관련 번호 없음") is None


def test_collect_flags_dedup_address_across_step1_4():
    from chandra.pipeline import collect_flags

    steps = {
        "step1_license": {"verdict": {"overall_verdict": "검토필요",
                                      "reasons": ["소재지 표시 확인 필요", "대표자 정보 확인"]}},
        "step4_label": {"verdict": {"overall_verdict": "검토필요",
                                    "items": [{"name": "생산자 소재지 표시", "verdict": "검토필요", "reason": "가남읍 누락"}]}},
    }
    flags = collect_flags(steps)
    s1 = next(f for f in flags if f["step"].startswith("1"))
    # 1단계의 주소 사유는 4단계와 중복이라 제거, 다른 사유는 유지
    assert "대표자 정보 확인" in s1["items"]
    assert not any("소재지" in i or "주소" in i for i in s1["items"])


# ---------------------------------------------------------------------------
# 제품명: 공백변형 중복제거(불일치 오탐 방지) / OCR '제품명' 앵커 회수(환각 보정)
# ---------------------------------------------------------------------------
def test_product_name_mismatch_ignores_spacing_only():
    """'간장 양념 민물장어구이' ↔ '간장 양념민물장어구이'는 공백만 달라 같은 제품 → 불일치 미기록."""
    from chandra.pipeline import _group_by_product

    addr = "충남 당진시 송악읍 농장길 336-66"
    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "간장 양념 민물장어구이", "manufacture_report_no": "202406940832", "address": addr},
        {"doc_type": DOC_LABEL, "product_name": "간장 양념민물장어구이", "manufacture_report_no": "202406940832", "address": addr},
    ]
    cl = _group_by_product(ext)
    assert "제품명" not in (cl[0].get("doc_mismatch") or {})


def test_product_name_mismatch_lists_distinct_only():
    """공백변형은 하나로, 내용이 다른 제품명(감탄장어탕)만 별도 표출."""
    from chandra.pipeline import _group_by_product

    addr = "충남 당진시 송악읍 농장길 336-66"
    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "간장 양념 민물장어구이", "manufacture_report_no": "202406940832", "address": addr},
        {"doc_type": DOC_LABEL, "product_name": "간장 양념민물장어구이", "manufacture_report_no": "202406940832", "address": addr},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "감탄 민물장어탕", "manufacture_report_no": "202406940831", "address": addr},
    ]
    names = (_group_by_product(ext)[0].get("doc_mismatch") or {}).get("제품명") or []
    assert len([n for n in names if "간장" in n]) == 1  # 공백변형 1개로 축약
    assert any("감탄" in n for n in names)


def test_product_name_from_ocr_anchor():
    from chandra.extraction import _product_name_from_ocr

    ocr = "제품명 감탄민물장어 양념구이 품목제조신고번호 202406940831 유형 기타 수산물가공품"
    assert _product_name_from_ocr(ocr) == "감탄민물장어 양념구이"
    assert _product_name_from_ocr("관련 정보 없음") is None


def test_form_label_not_product_name():
    """품목제조보고서 필드 라벨('요청하는 품목제조보고번호' 등)이 제품명으로 새는 오추출 차단."""
    from chandra.extraction import _FORM_LABEL_RE

    assert _FORM_LABEL_RE.search("요청하는 품목제조보고")
    assert _FORM_LABEL_RE.search("품목제조보고번호")
    assert _FORM_LABEL_RE.search("식품의 유형: null")
    assert not _FORM_LABEL_RE.search("김소형 원방 맛있는 보양밥")
    assert not _FORM_LABEL_RE.search("간장 양념 민물장어구이")
