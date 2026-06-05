from datetime import date

from chandra.validity import check_validity, parse_date


def test_parse_date_formats():
    assert parse_date("2026-02-20") == date(2026, 2, 20)
    assert parse_date("2026.02.20") == date(2026, 2, 20)
    assert parse_date("20260220") == date(2026, 2, 20)
    assert parse_date("2026년 2월 20일") == date(2026, 2, 20)
    assert parse_date("없음") is None


def test_validity_valid_within_6_months():
    # 발급 2026-02-20 + 6개월 = 2026-08-20, 오늘 2026-06-02 → 유효
    r = check_validity("2026-02-20", today=date(2026, 6, 2))
    assert r.valid is True
    assert r.expiry_date == "2026-08-20"
    assert r.days_remaining > 0


def test_validity_expired():
    # 발급 2025-10-01 + 6개월 = 2026-04-01, 오늘 2026-06-02 → 만료
    r = check_validity("2025-10-01", today=date(2026, 6, 2))
    assert r.valid is False
    assert r.days_remaining < 0


def test_validity_indeterminate_when_unparseable():
    r = check_validity(None, today=date(2026, 6, 2))
    assert r.valid is None
