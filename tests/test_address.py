from chandra.address import addresses_match, normalize_address


def test_normalize_unifies_sido_and_strips_parens():
    n = normalize_address("전라남도 무안군 삼향읍 삼향공단길 56-30 (삼향리, 알찬빌딩)")
    assert n.startswith("전남무안군")
    assert "(" not in n


def test_match_sido_abbreviation():
    r = addresses_match("전라남도 무안군 삼향읍 삼향공단길 56-30", "전남 무안군 삼향읍 삼향공단길 56-30")
    assert r.match is True


def test_match_ocr_noise():
    # 삼향 ↔ 삼황 OCR 오인식 흡수
    r = addresses_match("전남 무안군 삼향읍 삼향공단길 56-30", "전남 무안군 삼황읍 삼황공단길 56-30")
    assert r.match is True


def test_different_address_not_matched():
    r = addresses_match("전남 무안군 삼향읍 삼향공단길 56-30", "서울특별시 강남구 테헤란로 1")
    assert r.match is False
