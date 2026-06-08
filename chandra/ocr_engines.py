"""전용 OCR 엔진 래퍼 (하이브리드 판독용) — PaddleOCR(PP-OCRv5 한국어) 기반.

Gemma 비전 단독은 스캔본 한글 고유명사를 글자 단위로 오인식하는 경향이 있다.
전용 한글 OCR(PaddleOCR)로 문자 정확도가 높은 raw 텍스트를 먼저 뽑고, 이를 Gemma 에
'한글 표기 기준'으로 함께 전달하면 정확도가 올라간다.

벤치마크 결과(samples/): PaddleOCR ≫ EasyOCR(제조사명·주소 한글 판독). 저화질 스캔은
CLAHE 전처리가 크게 도움(원본 340 → CLAHE 754), 깨끗한 문서는 원본이 약간 우세 →
ocr_image_best 는 원본·CLAHE 를 모두 돌려 점수 높은 쪽을 채택(best-of-2)한다.

PaddleOCR 미설치/초기화 실패 시 None 을 반환해 Gemma 비전 단독으로 폴백한다.
폐쇄망: 첫 사용 시 다운로드되는 모델(~/.paddlex/official_models: korean rec + det)을 함께 번들.
"""

from __future__ import annotations

import threading

import numpy as np
from PIL import Image, ImageOps

_ocr = None
_ocr_failed = False
_ocr_lock = threading.Lock()  # 병렬 추출 시 엔진 중복 생성/경쟁 방지


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("paddleocr") is not None


def _get_ocr():
    global _ocr, _ocr_failed
    if _ocr is not None or _ocr_failed:
        return _ocr
    with _ocr_lock:  # 더블체크
        if _ocr is not None or _ocr_failed:
            return _ocr
        try:
            from paddleocr import PaddleOCR

            # 업라이트 인쇄 문서가 대부분이라 페이지 방향보정·왜곡보정(UVDoc, 느림)은 끈다.
            _ocr = PaddleOCR(
                lang="korean",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except Exception:  # noqa: BLE001 - 미설치/초기화 실패 시 폴백
            _ocr_failed = True
            _ocr = None
    return _ocr


def _clahe(image: Image.Image) -> Image.Image:
    """국소 대비 개선(CLAHE) — 저대비/저화질 스캔의 한글 판독률을 크게 높인다."""
    try:
        import cv2

        arr = np.array(image.convert("RGB"))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        cl = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        return Image.fromarray(cv2.cvtColor(cl, cv2.COLOR_GRAY2RGB))
    except Exception:  # noqa: BLE001 - cv2 미설치 등 → autocontrast 폴백
        return ImageOps.autocontrast(image.convert("RGB"), cutoff=2)


def _predict(image: Image.Image):
    """PaddleOCR 실행 → [(box, text, conf), ...] (없으면 None)."""
    ocr = _get_ocr()
    if ocr is None:
        return None
    try:
        res = ocr.predict(np.array(image.convert("RGB")))
    except Exception:  # noqa: BLE001
        return None
    out = []
    for r in res or []:
        try:
            d = dict(r)
        except Exception:  # noqa: BLE001
            d = getattr(r, "json", {}) or {}
        texts = d.get("rec_texts") or []
        scores = d.get("rec_scores") or [1.0] * len(texts)
        polys = d.get("rec_polys") or d.get("dt_polys") or [None] * len(texts)
        for box, text, conf in zip(polys, texts, scores):
            if text:
                out.append((box, str(text), float(conf)))
    return out


def _group_lines(results, y_tol: int = 12) -> str:
    """(box, text, conf) 목록을 위→아래, 좌→우 순으로 줄 단위 정렬해 합친다.

    box 가 없으면(좌표 미제공) 입력 순서(PaddleOCR 읽기순)를 그대로 줄바꿈으로 잇는다.
    """
    if results and results[0][0] is None:
        return "\n".join(t for _b, t, _c in results)
    items = []
    for box, text, _conf in results:
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


def _score(results) -> float:
    return sum(len(t) * c for _b, t, c in results) if results else 0.0


def ocr_image(image: Image.Image) -> str | None:
    """이미지를 한글 OCR 하여 레이아웃 순서 텍스트를 반환. 불가 시 None."""
    results = _predict(image)
    return _group_lines(results) if results else None


def ocr_image_best(image: Image.Image, variants: int = 0) -> tuple[str | None, str]:
    """원본·CLAHE 를 모두 OCR 해 점수가 높은 결과를 채택(best-of-2).

    저화질 스캔은 CLAHE 가, 깨끗한 문서는 원본이 우세 → 이미지별로 자동 적응.
    variants 인자는 하위호환용(무시). 반환: (best_text, 사용된 전처리명).
    """
    base = _predict(image)
    if not available():
        return None, "none"
    clahe = _predict(_clahe(image))
    cands = [("원본", base), ("clahe", clahe)]
    cands = [(n, r) for n, r in cands if r]
    if not cands:
        return None, "none"
    name, best = max(cands, key=lambda nr: _score(nr[1]))
    return _group_lines(best), name
