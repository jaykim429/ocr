"""전용 OCR 엔진 래퍼 (하이브리드 판독용).

Gemma 비전 단독은 스캔본 한글 고유명사를 글자 단위로 오인식하는 경향이 있다.
전용 한글 OCR(EasyOCR)로 문자 정확도가 높은 raw 텍스트를 먼저 뽑고, 이를 Gemma 에
'한글 표기 기준'으로 함께 전달하면 정확도가 올라간다.

EasyOCR 미설치 환경에서는 None 을 반환해 Gemma 비전 단독으로 폴백한다.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

_reader = None
_reader_failed = False


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("easyocr") is not None


def _get_reader():
    global _reader, _reader_failed
    if _reader is not None or _reader_failed:
        return _reader
    try:
        import easyocr

        _reader = easyocr.Reader(["ko", "en"], gpu=False)
    except Exception:  # noqa: BLE001 - 미설치/초기화 실패 시 폴백
        _reader_failed = True
        _reader = None
    return _reader


def _group_lines(results, y_tol: int = 12) -> str:
    """(bbox, text, conf) 목록을 위→아래, 좌→우 순으로 줄 단위 정렬해 합친다."""
    items = []
    for box, text, conf in results:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), min(xs), text))
    items.sort(key=lambda t: (round(t[0] / y_tol), t[1]))
    lines: list[list[str]] = []
    last_y = None
    for y, _x, text in items:
        if last_y is None or abs(y - last_y) > y_tol:
            lines.append([text])
            last_y = y
        else:
            lines[-1].append(text)
    return "\n".join(" ".join(line) for line in lines)


def _readtext(image: Image.Image):
    reader = _get_reader()
    if reader is None:
        return None
    try:
        return reader.readtext(np.array(image.convert("RGB")), detail=1, paragraph=False)
    except Exception:  # noqa: BLE001
        return None


def ocr_image(image: Image.Image) -> str | None:
    """이미지를 한글 OCR 하여 레이아웃 순서 텍스트를 반환. 불가 시 None."""
    results = _readtext(image)
    return _group_lines(results) if results is not None else None


def _cv_variants(rgb: Image.Image):
    """OpenCV/skimage 기반 전처리 (CLAHE, Adaptive/Otsu/Sauvola 이진화). 미설치 시 생략."""
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return
    arr = np.array(rgb)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # CLAHE (국소 대비 개선) — 문서 OCR에 특히 유용
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    yield "clahe", Image.fromarray(cv2.cvtColor(clahe, cv2.COLOR_GRAY2RGB))

    # Otsu (배경 균일 문서)
    _t, otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "otsu", Image.fromarray(cv2.cvtColor(otsu, cv2.COLOR_GRAY2RGB))

    # Adaptive (조명 편차 문서)
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    yield "adaptive", Image.fromarray(cv2.cvtColor(adaptive, cv2.COLOR_GRAY2RGB))

    # Sauvola (오래된/얼룩 문서) — skimage 있을 때만
    try:
        from skimage.filters import threshold_sauvola

        th = threshold_sauvola(gray, window_size=25)
        sau = ((gray > th) * 255).astype("uint8")
        yield "sauvola", Image.fromarray(cv2.cvtColor(sau, cv2.COLOR_GRAY2RGB))
    except Exception:  # noqa: BLE001
        pass


def _preprocess_variants(image: Image.Image):
    """OCR 정확도 향상을 위한 전처리 변형들.

    원본·그레이/대비·밝기·샤픈·단순이진화 + (OpenCV) CLAHE·Otsu·Adaptive·Sauvola.
    원본/그레이/이진화를 함께 비교하는 것이 안정적이라는 권장에 따른 구성.
    """
    rgb = image.convert("RGB")
    yield "original", rgb
    yield "autocontrast", ImageOps.autocontrast(rgb, cutoff=2)
    yield "bright+", ImageEnhance.Brightness(rgb).enhance(1.35)
    yield "contrast+", ImageEnhance.Contrast(rgb).enhance(1.6)
    yield "sharpen", ImageEnhance.Sharpness(rgb).enhance(2.2)
    gray = ImageOps.grayscale(ImageOps.autocontrast(rgb, cutoff=2))
    yield "binarize", gray.point(lambda p: 255 if p > 160 else 0).convert("RGB")
    yield from _cv_variants(rgb)


def _score(results) -> tuple[float, int]:
    """OCR 결과 점수: (신뢰도 가중 글자수, 박스수). 높을수록 좋음."""
    if not results:
        return 0.0, 0
    score = sum(len(str(text)) * float(conf) for _box, text, conf in results)
    return score, len(results)


def ocr_image_best(
    image: Image.Image, variants: int = 0
) -> tuple[str | None, str]:
    """여러 전처리 변형으로 OCR 해보고 가장 잘 읽힌 결과를 고른다.

    variants=0 이면 전체 시도. 반환: (best_text, 사용된 변형명).
    """
    reader = _get_reader()
    if reader is None:
        return None, "none"
    best_text, best_name, best_score = None, "none", -1.0
    for i, (name, img) in enumerate(_preprocess_variants(image)):
        if variants and i >= variants:
            break
        results = _readtext(img)
        if results is None:
            continue
        sc, _n = _score(results)
        if sc > best_score:
            best_score, best_text, best_name = sc, _group_lines(results), name
    return best_text, best_name
