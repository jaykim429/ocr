"""서류 유효기간 검사.

성적서 등 제출 서류는 발급일로부터 6개월간 유효하며, 항상 '오늘 날짜' 기준으로
유효 여부를 판단한다. 날짜 파싱은 한국 서류에서 흔한 표기들을 폭넓게 지원한다.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

DEFAULT_VALID_MONTHS = 6


def parse_date(value: str | date | None) -> date | None:
    """'2026-02-20', '2026.02.20', '20260220', '2026년 02월 20일' 등을 date 로."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # YYYY년 MM월 DD일
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # 구분자(., -, /) 포함
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # YYYYMMDD
    m = re.search(r"\b(\d{4})(\d{2})(\d{2})\b", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # 말일 보정 (예: 8/31 + ... )
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


@dataclass
class ValidityResult:
    label: str
    issue_date: str | None
    expiry_date: str | None
    today: str
    valid_months: int
    valid: bool | None  # None = 발급일 파싱 불가로 판정불가
    days_remaining: int | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_validity(
    issue_date: str | date | None,
    today: date | None = None,
    valid_months: int = DEFAULT_VALID_MONTHS,
    label: str = "서류",
) -> ValidityResult:
    """발급일 + valid_months 와 오늘 날짜를 비교한다."""
    ref = today or date.today()
    issued = parse_date(issue_date)

    if issued is None:
        return ValidityResult(
            label=label,
            issue_date=None,
            expiry_date=None,
            today=ref.isoformat(),
            valid_months=valid_months,
            valid=None,
            days_remaining=None,
            detail="발급일을 확인할 수 없어 유효기간 판정 불가",
        )

    expiry = _add_months(issued, valid_months)
    days_remaining = (expiry - ref).days
    valid = ref <= expiry
    detail = (
        f"발급일 {issued.isoformat()} + {valid_months}개월 = 만료 {expiry.isoformat()} | "
        f"오늘 {ref.isoformat()} → "
        + (f"유효 (만료까지 {days_remaining}일)" if valid else f"만료됨 ({-days_remaining}일 경과)")
    )
    return ValidityResult(
        label=label,
        issue_date=issued.isoformat(),
        expiry_date=expiry.isoformat(),
        today=ref.isoformat(),
        valid_months=valid_months,
        valid=valid,
        days_remaining=days_remaining,
        detail=detail,
    )
