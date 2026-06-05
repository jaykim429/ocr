"""kordoc(Node CLI) 연계 — 한국 문서(HWP/HWPX/DOCX/XLS/XLSX/텍스트PDF) → Markdown.

우리 OCR 파이프라인(EasyOCR+Gemma)은 스캔본 PDF/이미지를 처리하지만 HWP/HWPX·오피스
문서는 못 읽는다. kordoc은 이들 형식을 텍스트 레이어 기반으로 정확히 마크다운으로 변환하므로
(스캔본은 '이미지 기반 0자'로 실패) 상호보완적이다. 추출 단계에서 텍스트 소스로 활용한다.

kordoc 미설치 시 None 을 반환해 OCR 단독으로 폴백한다.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

# kordoc 이 직접 파싱하는(스캔 OCR 아님) 형식
KORDOC_EXTS = {".hwp", ".hwpx", ".hwpml", ".docx", ".xls", ".xlsx", ".pdf"}


def available() -> bool:
    return shutil.which("kordoc") is not None


def to_markdown(path: str, pages: str | None = None, timeout: float = 180.0) -> str | None:
    """문서를 kordoc 으로 마크다운 변환. 실패/빈문서(스캔본 등)면 None."""
    if not available():
        return None
    if Path(path).suffix.lower() not in KORDOC_EXTS:
        return None
    exe = shutil.which("kordoc")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.md"
        cmd = [exe, path, "--format", "markdown", "--silent", "-o", str(out)]
        if pages:
            cmd += ["-p", pages]
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout)
        except Exception:  # noqa: BLE001 - 변환 실패 시 OCR 폴백
            return None
        if not out.exists():
            return None
        text = out.read_text(encoding="utf-8", errors="replace").strip()
        return text or None
