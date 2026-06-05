from PIL import Image

from chandra.ocr_engines import _preprocess_variants


def test_preprocess_variants_include_opencv_methods():
    img = Image.new("RGB", (120, 80), "white")
    names = [n for n, _ in _preprocess_variants(img)]
    # 기본 변형
    assert "original" in names
    assert "autocontrast" in names
    assert "binarize" in names
    # OpenCV 기반 (설치되어 있으면 포함)
    try:
        import cv2  # noqa: F401

        assert "clahe" in names
        assert "otsu" in names
        assert "adaptive" in names
    except ImportError:
        pass


def test_preprocess_variants_are_rgb_same_size():
    img = Image.new("RGB", (100, 60), "white")
    for _name, variant in _preprocess_variants(img):
        assert variant.mode == "RGB"
        assert variant.size == img.size
