"""OCR 래퍼(PaddleOCR 기반) 순수 유닛 — 엔진 모델 없이 동작하는 부분만 검증."""
from PIL import Image

from chandra.ocr_engines import _clahe, _group_lines


def test_clahe_returns_rgb_same_size():
    img = Image.new("RGB", (120, 80), "white")
    out = _clahe(img)
    assert out.mode == "RGB" and out.size == img.size


def test_group_lines_orders_top_to_bottom_left_to_right():
    # box=[(x,y)x4] 형식. 아래 두 줄(좌→우)로 정렬돼야 한다.
    results = [
        ([(200, 5), (260, 5), (260, 20), (200, 20)], "우", 0.9),
        ([(10, 5), (60, 5), (60, 20), (10, 20)], "좌", 0.9),
        ([(10, 60), (60, 60), (60, 75), (10, 75)], "아래", 0.9),
    ]
    assert _group_lines(results) == "좌 우\n아래"


def test_group_lines_no_box_keeps_reading_order():
    results = [(None, "첫줄", 0.9), (None, "둘째줄", 0.9)]
    assert _group_lines(results) == "첫줄\n둘째줄"
