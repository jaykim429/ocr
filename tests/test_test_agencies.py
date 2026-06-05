from chandra.test_agencies import TestAgency, parse_agency_text, verify_agency


_SAMPLE_LIST = """연번 지정번호 기 관 명 소 재 지 분야 시험·검사항목 유효기간
32 제099호 ㈜디아이분석센터
경기도 의정부시 가능로 9, 2,3,4층
(가능동, 수신빌딩)
☎031-836-5123 fax031-836-5124
식품 이화학, 미생물 2019.1.3.
6 제033호 (재)전라북도 생물산업 진흥원
전북 전주시 덕진구 원장동길 111-18
☎063-210-6555 fax063-210-6559
식품 이화학, 미생물 2019.6.4.
"""


def test_parse_agency_text_extracts_fields():
    rows = {r["designation_no"]: r for r in parse_agency_text(_SAMPLE_LIST)}
    di = rows["제099호"]
    assert "디아이분석센터" in di["name"]
    assert di["tel"] == "031-836-5123"
    assert di["valid_until"] == "2019.1.3."
    assert "의정부시" in di["address"]


def test_parse_agency_text_name_with_region_word():
    # 기관명에 '전라북도'가 있어도 주소(전북 전주시)와 올바르게 분리
    rows = {r["designation_no"]: r for r in parse_agency_text(_SAMPLE_LIST)}
    jb = rows["제033호"]
    assert "전라북도 생물산업" in jb["name"]
    assert jb["address"].startswith("전북 전주시")


def _db():
    return [
        TestAgency(
            name="주식회사 디아이분석센터",
            designation_no="식품 제099호",
            category="식품",
            address="경기도 의정부시 가능로 9",
            tel="031-836-5123",
            aliases=["디아이분석센터", "DI LAB"],
        )
    ]


def test_verify_by_tel_even_with_garbled_name():
    # 이름이 OCR로 깨져도 성적서 하단 전화번호로 매칭
    r = verify_agency("주식회사 다이아몬드센터", tel="031-836-5123", db=_db())
    assert r.found is True
    assert r.match_basis == "tel"


def test_verify_fuzzy_name_ocr_noise():
    # 디아이→다이아이 수준 오인식은 퍼지로 매칭
    r = verify_agency("주식회사 다이아이분석센터", db=_db())
    assert r.found is True
    assert r.match_basis in ("fuzzy", "fuzzy+addr")


def test_verify_by_designation_no():
    r = verify_agency("아무이름", designation_no="식품 제099호", db=_db())
    assert r.found is True
    assert r.match_basis == "designation_no"


def test_verify_by_name_with_company_prefix_difference():
    # (주) 접두 차이/별칭이어도 매칭
    r = verify_agency("디아이분석센터", db=_db())
    assert r.found is True


def test_verify_designation_mismatch_flagged():
    r = verify_agency("디아이분석센터", designation_no="식품 제100호", db=_db())
    assert r.found is True
    assert r.designation_no_match is False


def test_verify_designation_with_category_prefix():
    # 성적서는 '식품 제145호', DB는 '제145호'로 표기돼도 숫자(145)로 매칭
    db = [TestAgency(name="(주)휴먼바이오", designation_no="제145호", category="식품", tel="041-881-9200")]
    r = verify_agency("아무이름", designation_no="식품 제145호", db=db)
    assert r.found is True
    assert r.match_basis == "designation_no"


def test_verify_ocr_garbled_name_fuzzy_to_real_lab():
    # OCR '휴번바이오' → 실제 '휴먼바이오' 퍼지 매칭
    db = [TestAgency(name="(주)휴먼바이오", designation_no="제145호", category="식품", tel="041-881-9200")]
    r = verify_agency("주식회사 휴번바이오", db=db)
    assert r.found is True


def test_verify_not_found():
    r = verify_agency("없는검사소", designation_no="식품 제500호", db=_db())
    assert r.found is False
