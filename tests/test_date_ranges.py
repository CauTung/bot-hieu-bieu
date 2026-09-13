from datetime import date, datetime, timezone

import pytest

from services.date_ranges import parse_order_period


def test_default_period_is_current_month_in_application_timezone() -> None:
    start, end = parse_order_period(
        None,
        now=datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc),
        timezone_name="Asia/Ho_Chi_Minh",
    )
    assert start == date(2026, 9, 1)
    assert end == date(2026, 10, 1)


def test_month_period_handles_year_boundary() -> None:
    start, end = parse_order_period(
        "2026-12", now=datetime.now(timezone.utc), timezone_name="Asia/Ho_Chi_Minh"
    )
    assert start == date(2026, 12, 1)
    assert end == date(2027, 1, 1)


def test_day_period_is_end_exclusive() -> None:
    start, end = parse_order_period(
        "2026-09-13", now=datetime.now(timezone.utc), timezone_name="Asia/Ho_Chi_Minh"
    )
    assert start == date(2026, 9, 13)
    assert end == date(2026, 9, 14)


def test_invalid_period_is_rejected() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        parse_order_period(
            "13/09/2026",
            now=datetime.now(timezone.utc),
            timezone_name="Asia/Ho_Chi_Minh",
        )
