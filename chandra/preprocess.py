from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


@dataclass
class PreprocessReport:
    original_size: tuple[int, int]
    output_size: tuple[int, int]
    crop_bbox: list[int] | None = None
    rotation_angle: float = 0.0
    used_opencv: bool = False
    steps: list[str] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SealCandidate:
    label: str
    bbox: list[int]
    pixel_count: int
    area_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImageVariant:
    name: str
    image: Image.Image

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size": self.image.size}


def _get_cv2():
    try:
        import cv2

        return cv2
    except ImportError:
        return None


def _rotate(image: Image.Image, angle: float) -> Image.Image:
    if abs(angle) < 0.2:
        return image
    return image.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor="white",
    )


def _is_meaningful_crop(
    bbox: list[int],
    image_size: tuple[int, int],
    min_area_ratio: float = 0.08,
    max_area_ratio: float = 0.96,
) -> bool:
    x0, y0, x1, y1 = bbox
    width, height = image_size
    crop_width = max(0, x1 - x0)
    crop_height = max(0, y1 - y0)
    crop_area = crop_width * crop_height
    image_area = width * height
    if crop_width < 32 or crop_height < 32 or image_area == 0:
        return False

    area_ratio = crop_area / image_area
    return min_area_ratio <= area_ratio <= max_area_ratio


def _pad_bbox(
    bbox: list[int],
    image_size: tuple[int, int],
    padding_ratio: float = 0.06,
) -> list[int]:
    x0, y0, x1, y1 = bbox
    width, height = image_size
    pad_x = int((x1 - x0) * padding_ratio)
    pad_y = int((y1 - y0) * padding_ratio)
    return [
        max(0, x0 - pad_x),
        max(0, y0 - pad_y),
        min(width, x1 + pad_x),
        min(height, y1 + pad_y),
    ]


def _compose_crop_bbox(current_bbox: list[int], crop_bbox: list[int]) -> list[int]:
    return [
        current_bbox[0] + crop_bbox[0],
        current_bbox[1] + crop_bbox[1],
        current_bbox[0] + crop_bbox[2],
        current_bbox[1] + crop_bbox[3],
    ]


def _largest_true_run(mask: np.ndarray) -> tuple[int, int] | None:
    best_start = None
    best_end = None
    current_start = None

    for idx, value in enumerate(mask):
        if value and current_start is None:
            current_start = idx
        elif not value and current_start is not None:
            if best_start is None or idx - current_start > best_end - best_start:
                best_start, best_end = current_start, idx
            current_start = None

    if current_start is not None:
        idx = len(mask)
        if best_start is None or idx - current_start > best_end - best_start:
            best_start, best_end = current_start, idx

    if best_start is None:
        return None
    return best_start, best_end


def detect_document_bbox(image: Image.Image) -> list[int] | None:
    arr = np.array(image.convert("RGB")).astype(np.int16)
    gray = arr.mean(axis=2)
    saturation = arr.max(axis=2) - arr.min(axis=2)
    paper_mask = ((gray > 175) & (saturation < 55)) | (gray > 215)

    row_ratio = paper_mask.mean(axis=1)
    col_ratio = paper_mask.mean(axis=0)
    row_run = _largest_true_run(row_ratio > 0.42)
    col_run = _largest_true_run(col_ratio > 0.42)
    if row_run is None or col_run is None:
        return None

    bbox = [col_run[0], row_run[0], col_run[1], row_run[1]]
    bbox = _pad_bbox(bbox, image.size, padding_ratio=0.02)
    if not _is_meaningful_crop(bbox, image.size, min_area_ratio=0.25):
        return None
    return bbox


def detect_content_bbox(image: Image.Image) -> list[int] | None:
    gray = np.array(ImageOps.grayscale(image))
    threshold = min(205, max(120, int(np.percentile(gray, 35)) - 20))
    ink_mask = gray < threshold

    # Drop tiny isolated noise by requiring activity in row/column projections.
    row_has_ink = ink_mask.mean(axis=1) > 0.002
    col_has_ink = ink_mask.mean(axis=0) > 0.002

    ys = np.where(row_has_ink)[0]
    xs = np.where(col_has_ink)[0]
    if len(xs) == 0 or len(ys) == 0:
        return None

    bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    bbox = _pad_bbox(bbox, image.size, padding_ratio=0.18)
    if not _is_meaningful_crop(bbox, image.size, max_area_ratio=0.90):
        return None
    return bbox


def _deskew_with_opencv(image: Image.Image) -> tuple[Image.Image, float] | None:
    cv2 = _get_cv2()
    if cv2 is None:
        return None

    gray = np.array(ImageOps.grayscale(image))
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=max(80, min(image.size) // 4),
        maxLineGap=12,
    )
    if lines is None:
        return image, 0.0

    angles = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = line
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if -15 <= angle <= 15:
            angles.append(angle)

    if not angles:
        return image, 0.0

    angle = float(np.median(angles))
    return _rotate(image, -angle), angle


def normalize_document_image(
    image: Image.Image,
    auto_crop: bool = False,
    deskew: bool = True,
    enhance: bool = True,
    sharpen: bool = True,
) -> tuple[Image.Image, PreprocessReport]:
    report = PreprocessReport(
        original_size=image.size,
        output_size=image.size,
        steps=[],
        warnings=[],
    )
    out = image.convert("RGB")
    crop_bbox = [0, 0, out.width, out.height]

    if auto_crop:
        document_bbox = detect_document_bbox(out)
        if document_bbox is not None:
            out = out.crop(document_bbox)
            crop_bbox = _compose_crop_bbox(crop_bbox, document_bbox)
            report.steps.append("document_crop")

        content_bbox = detect_content_bbox(out)
        if content_bbox is not None:
            out = out.crop(content_bbox)
            crop_bbox = _compose_crop_bbox(crop_bbox, content_bbox)
            report.steps.append("content_crop")

    if deskew:
        deskewed = _deskew_with_opencv(out)
        if deskewed is None:
            report.warnings.append("opencv_not_available_for_deskew")
        else:
            out, angle = deskewed
            report.rotation_angle = angle
            report.used_opencv = True
            if abs(angle) >= 0.2:
                report.steps.append("deskew")

    if enhance:
        out = ImageOps.autocontrast(out)
        out = ImageEnhance.Contrast(out).enhance(1.15)
        report.steps.append("autocontrast")

    if sharpen:
        out = out.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
        report.steps.append("sharpen")

    report.output_size = out.size
    if crop_bbox != [0, 0, image.width, image.height]:
        report.crop_bbox = crop_bbox
    return out, report


def upscale_for_ocr(
    image: Image.Image,
    min_short_side: int = 1024,
    max_long_side: int = 2200,
) -> Image.Image:
    out = image.convert("RGB")
    short_side = min(out.size)
    long_side = max(out.size)
    if short_side >= min_short_side:
        return out

    scale = min_short_side / max(1, short_side)
    if long_side * scale > max_long_side:
        scale = max_long_side / max(1, long_side)
    if scale <= 1.0:
        return out

    new_size = (int(out.width * scale), int(out.height * scale))
    return out.resize(new_size, Image.Resampling.LANCZOS)


def create_image_variants(
    image: Image.Image,
    max_variants: int = 3,
) -> list[ImageVariant]:
    base = upscale_for_ocr(image)
    variants = [ImageVariant("upscaled", base)]

    high_contrast = ImageOps.autocontrast(base)
    high_contrast = ImageEnhance.Contrast(high_contrast).enhance(1.45)
    high_contrast = high_contrast.filter(
        ImageFilter.UnsharpMask(radius=1.0, percent=140, threshold=2)
    )
    variants.append(ImageVariant("high_contrast", high_contrast.convert("RGB")))

    gray = ImageOps.grayscale(base)
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.0, percent=160, threshold=2))
    variants.append(ImageVariant("grayscale_sharp", gray.convert("RGB")))

    arr = np.array(gray)
    threshold = int(np.percentile(arr, 62))
    threshold = min(220, max(120, threshold))
    binary_arr = np.where(arr < threshold, 0, 255).astype(np.uint8)
    binary = Image.fromarray(binary_arr, mode="L").convert("RGB")
    variants.append(ImageVariant("binary_threshold", binary))

    return variants[: max(1, max_variants)]


def _color_mask(image: Image.Image, color: str) -> np.ndarray:
    arr = np.array(image.convert("RGB")).astype(np.int16)
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    if color == "red":
        return (r > 120) & (r > g + 35) & (r > b + 35)
    if color == "blue":
        return (b > 110) & (b > r + 25) & (b > g + 20)
    raise ValueError(f"Unsupported color mask: {color}")


def _bbox_from_mask(mask: np.ndarray) -> list[int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def detect_seal_candidates(
    image: Image.Image,
    min_area_ratio: float = 0.00025,
) -> list[SealCandidate]:
    candidates = []
    total_pixels = image.width * image.height

    for color in ("red", "blue"):
        mask = _color_mask(image, color)
        pixel_count = int(mask.sum())
        area_ratio = pixel_count / total_pixels if total_pixels else 0.0
        if area_ratio < min_area_ratio:
            continue

        bbox = _bbox_from_mask(mask)
        if bbox is None:
            continue

        candidates.append(
            SealCandidate(
                label=f"{color}_seal_candidate",
                bbox=bbox,
                pixel_count=pixel_count,
                area_ratio=area_ratio,
            )
        )

    return candidates
