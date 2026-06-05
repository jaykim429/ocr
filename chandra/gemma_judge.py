"""Gemma 기반 적합성 '판단' 호출 유틸.

품질검토의 최종 판정(적합/부적합/검토필요)은 규칙엔진이 아니라 Gemma 모델이 수행한다.
파이썬 측은 OCR 파싱·식품공전 규격 조회 등 '근거(evidence)'만 구조화해 제공하고,
판단은 Gemma 가 내린 JSON 결과를 그대로 사용한다.

설정은 chandra.settings 의 REVIEW_* (google/gemma-4-26B-A4B-it 엔드포인트)를 재사용한다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from PIL import Image

from chandra.review import image_to_data_url
from chandra.settings import settings


def _extract_json(text: str) -> dict[str, Any]:
    """모델 응답에서 JSON 오브젝트를 견고하게 추출한다."""
    if not text:
        raise ValueError("빈 응답")
    cleaned = text.strip()
    # 코드펜스 제거
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 본문 중 첫 번째 {...} 블록 탐색
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError(f"JSON 파싱 실패: {text[:200]}")


def judge_json(
    system_prompt: str,
    user_text: str,
    image: Image.Image | None = None,
    images: list[Image.Image] | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
    timeout_seconds: float | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Gemma 에 판정을 요청하고 JSON dict 를 반환한다.

    호출 실패 시 예외를 전파하므로, 호출부에서 try/except 로 '판정불가' 처리한다.
    """
    client = OpenAI(
        api_key=api_key or settings.REVIEW_API_KEY,
        base_url=api_base or settings.REVIEW_API_BASE,
        timeout=timeout_seconds or settings.REVIEW_TIMEOUT_SECONDS,
    )

    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    all_images = list(images or [])
    if image is not None:
        all_images.append(image)
    for img in all_images:
        content.append(
            {"type": "image_url", "image_url": {"url": image_to_data_url(img)}}
        )

    completion = client.chat.completions.create(
        model=model_name or settings.REVIEW_MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        max_tokens=max_output_tokens or settings.REVIEW_MAX_OUTPUT_TOKENS,
        temperature=temperature,
    )
    raw = completion.choices[0].message.content or ""
    data = _extract_json(raw)
    data.setdefault("_raw", raw)
    return data
