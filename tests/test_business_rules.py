from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from models.product import normalize_sku
from models.reminder import Reminder
from services.reminder_worker import mark_reminder_error, retry_delay_seconds


def test_normalize_sku() -> None:
    assert normalize_sku("  vay01 ") == "VAY01"


def test_empty_sku_is_rejected() -> None:
    with pytest.raises(ValueError, match="SKU"):
        normalize_sku("   ")


def test_reminder_retry_uses_bounded_exponential_backoff() -> None:
    assert retry_delay_seconds(1) == 30
    assert retry_delay_seconds(2) == 60
    assert retry_delay_seconds(20) == 3600


def test_reminder_error_schedules_retry() -> None:
    now = datetime.now(timezone.utc)
    reminder = Reminder(
        telegram_user_id=1,
        chat_id=2,
        content="Test",
        remind_at=now - timedelta(minutes=1),
        status="processing",
        attempt_count=0,
    )
    session = MagicMock()
    session.get.return_value = reminder
    outcome = mark_reminder_error(
        session, reminder, RuntimeError("offline"), max_attempts=3, now=now
    )
    assert outcome == "retried"
    assert reminder.status == "pending"
    assert reminder.attempt_count == 1
    assert reminder.next_retry_at == now + timedelta(seconds=30)


def test_reminder_stops_after_max_attempts() -> None:
    now = datetime.now(timezone.utc)
    reminder = Reminder(
        telegram_user_id=1,
        chat_id=2,
        content="Test",
        remind_at=now,
        status="processing",
        attempt_count=2,
    )
    session = MagicMock()
    session.get.return_value = reminder
    outcome = mark_reminder_error(
        session, reminder, RuntimeError("offline"), max_attempts=3, now=now
    )
    assert outcome == "failed"
    assert reminder.status == "failed"
    assert reminder.next_retry_at is None
