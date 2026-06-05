import base64
import io
from dataclasses import dataclass

from openai import OpenAI
from PIL import Image

from chandra.settings import settings


REVIEW_SYSTEM_PROMPT = """You are an expert OCR verification editor.
Your job is to improve OCR output while preserving the source document.
Return only the final Markdown.
Do not summarize, explain, translate, or add content that is not supported by the OCR text or image.
Preserve reading order, headings, tables, math, labels, checkboxes, line breaks where meaningful, and all visible values.
If a character or word cannot be verified, keep the OCR text or mark it as [unclear] instead of guessing."""

DIRECT_TRANSCRIPTION_SYSTEM_PROMPT = """You are a conservative OCR transcriber.
Read the supplied document image directly and return only the visible text.
Keep the original line breaks and reading order.
Do not use memory of famous poems, lyrics, templates, or likely phrases to complete the text.
Do not normalize style, summarize, translate, or add missing content.
Use [unclear] for characters or words you cannot verify from the image."""


@dataclass
class ReviewResult:
    markdown: str
    raw: str
    token_count: int = 0
    error: bool = False
    error_message: str | None = None
    used_image: bool = False


def image_to_data_url(image: Image.Image) -> str:
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    encoded = base64.b64encode(buffered.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def strip_markdown_fence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```") or not cleaned.endswith("```"):
        return cleaned

    lines = cleaned.splitlines()
    if len(lines) < 2:
        return cleaned

    first_line = lines[0].strip().lower()
    if first_line not in ("```", "```markdown", "```md"):
        return cleaned

    return "\n".join(lines[1:-1]).strip()


def trim_section(label: str, text: str | None, max_chars: int) -> str:
    if not text:
        return f"{label}:\n(empty)"

    if len(text) <= max_chars:
        return f"{label}:\n{text}"

    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    trimmed = (
        text[:head_chars]
        + "\n\n[... middle omitted because the OCR result exceeded the review input limit ...]\n\n"
        + text[-tail_chars:]
    )
    return f"{label}:\n{trimmed}"


def build_review_text(
    markdown: str,
    html: str | None = None,
    extra_context: str | None = None,
    file_name: str | None = None,
    page_num: int | None = None,
    max_input_chars: int = settings.REVIEW_MAX_INPUT_CHARS,
) -> str:
    context = []
    if file_name:
        context.append(f"File: {file_name}")
    if page_num is not None:
        context.append(f"Page: {page_num + 1}")

    prefix = "\n".join(context)
    if prefix:
        prefix += "\n\n"

    markdown_budget = max_input_chars
    html_budget = 0
    if html:
        markdown_budget = int(max_input_chars * 0.65)
        html_budget = max_input_chars - markdown_budget

    parts = [
        prefix
        + "Review and correct the OCR output below. Prefer preserving exact document content over making prose sound natural."
    ]
    parts.append(trim_section("OCR Markdown", markdown, markdown_budget))
    if html:
        parts.append(
            trim_section(
                "OCR HTML/layout reference",
                html,
                html_budget,
            )
        )
    if extra_context:
        parts.append(
            trim_section(
                "Additional OCR/VLM evidence",
                extra_context,
                max(2000, max_input_chars // 4),
            )
        )
    parts.append("Return only the corrected Markdown.")
    return "\n\n".join(parts)


def _call_reviewer(
    markdown: str,
    html: str | None = None,
    extra_context: str | None = None,
    image: Image.Image | None = None,
    file_name: str | None = None,
    page_num: int | None = None,
    api_base: str = settings.REVIEW_API_BASE,
    api_key: str = settings.REVIEW_API_KEY,
    model_name: str = settings.REVIEW_MODEL_NAME,
    max_output_tokens: int = settings.REVIEW_MAX_OUTPUT_TOKENS,
    timeout_seconds: float = settings.REVIEW_TIMEOUT_SECONDS,
    max_input_chars: int = settings.REVIEW_MAX_INPUT_CHARS,
    temperature: float = 0.0,
) -> ReviewResult:
    client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout_seconds)
    review_text = build_review_text(
        markdown,
        html=html,
        extra_context=extra_context,
        file_name=file_name,
        page_num=page_num,
        max_input_chars=max_input_chars,
    )

    user_content = [{"type": "text", "text": review_text}]
    if image is not None:
        user_content.append(
            {"type": "image_url", "image_url": {"url": image_to_data_url(image)}}
        )

    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_output_tokens,
        temperature=temperature,
    )

    raw = completion.choices[0].message.content or ""
    usage = completion.usage
    token_count = usage.completion_tokens if usage else 0
    return ReviewResult(
        markdown=strip_markdown_fence(raw),
        raw=raw,
        token_count=token_count,
        error=False,
        used_image=image is not None,
    )


def review_ocr_output(
    markdown: str,
    html: str | None = None,
    extra_context: str | None = None,
    image: Image.Image | None = None,
    file_name: str | None = None,
    page_num: int | None = None,
    api_base: str = settings.REVIEW_API_BASE,
    api_key: str = settings.REVIEW_API_KEY,
    model_name: str = settings.REVIEW_MODEL_NAME,
    max_output_tokens: int = settings.REVIEW_MAX_OUTPUT_TOKENS,
    timeout_seconds: float = settings.REVIEW_TIMEOUT_SECONDS,
    include_image: bool = settings.REVIEW_INCLUDE_IMAGE,
    max_input_chars: int = settings.REVIEW_MAX_INPUT_CHARS,
) -> ReviewResult:
    try:
        return _call_reviewer(
            markdown,
            html=html,
            extra_context=extra_context,
            image=image if include_image else None,
            file_name=file_name,
            page_num=page_num,
            api_base=api_base,
            api_key=api_key,
            model_name=model_name,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            max_input_chars=max_input_chars,
        )
    except Exception as image_error:
        if include_image:
            try:
                return _call_reviewer(
                    markdown,
                    html=html,
                    extra_context=extra_context,
                    image=None,
                    file_name=file_name,
                    page_num=page_num,
                    api_base=api_base,
                    api_key=api_key,
                    model_name=model_name,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=timeout_seconds,
                    max_input_chars=max_input_chars,
                )
            except Exception as text_error:
                return ReviewResult(
                    markdown=markdown,
                    raw="",
                    error=True,
                    error_message=(
                        f"Image review failed: {image_error}; text review failed: {text_error}"
                    ),
                )

        return ReviewResult(
            markdown=markdown,
            raw="",
            error=True,
            error_message=str(image_error),
        )


def direct_transcribe_image(
    image: Image.Image,
    file_name: str | None = None,
    page_num: int | None = None,
    variant_name: str | None = None,
    api_base: str = settings.REVIEW_API_BASE,
    api_key: str = settings.REVIEW_API_KEY,
    model_name: str = settings.REVIEW_MODEL_NAME,
    max_output_tokens: int = 2048,
    timeout_seconds: float = settings.REVIEW_TIMEOUT_SECONDS,
    temperature: float = 0.0,
) -> ReviewResult:
    context = []
    if file_name:
        context.append(f"File: {file_name}")
    if page_num is not None:
        context.append(f"Page: {page_num + 1}")
    if variant_name:
        context.append(f"Image variant: {variant_name}")

    user_text = "\n".join(context)
    if user_text:
        user_text += "\n\n"
    user_text += (
        "Transcribe the visible text in this image. "
        "For handwriting, preserve uncertainty with [unclear] instead of guessing."
    )

    try:
        client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout_seconds)
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": DIRECT_TRANSCRIPTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_to_data_url(image)},
                        },
                    ],
                },
            ],
            max_tokens=max_output_tokens,
            temperature=temperature,
        )
        raw = completion.choices[0].message.content or ""
        usage = completion.usage
        token_count = usage.completion_tokens if usage else 0
        return ReviewResult(
            markdown=strip_markdown_fence(raw),
            raw=raw,
            token_count=token_count,
            error=False,
            used_image=True,
        )
    except Exception as error:
        return ReviewResult(
            markdown="",
            raw="",
            token_count=0,
            error=True,
            error_message=str(error),
            used_image=True,
        )
