import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from models.product import Product
from models.reminder import Reminder
from modules.order.service import add_order, total_orders
from modules.reminder.service import cancel_reminder, create_reminder, list_pending_reminders
from modules.sku.service import create_product, find_products
from services.confirmation_service import create_pending_action
from services.reminder_worker import claim_due_reminders, mark_reminder_sent


def test_create_product_normalizes_and_adds() -> None:
    session = MagicMock()
    session.get.return_value = None
    product, created = create_product(
        session, sku=" vay01 ", name=" Váy xếp ly ", tags=[" nữ ", ""]
    )
    assert created is True
    assert product.sku == "VAY01"
    assert product.name == "Váy xếp ly"
    assert product.tags == ["nữ"]
    session.add.assert_called_once_with(product)


def test_existing_product_is_not_duplicated() -> None:
    existing = Product(sku="VAY01", name="Váy")
    session = MagicMock()
    session.get.return_value = existing
    product, created = create_product(session, sku="vay01", name="Tên mới")
    assert product is existing
    assert created is False
    session.add.assert_not_called()


def test_find_products_returns_scalar_results() -> None:
    expected = [Product(sku="VAY01", name="Váy")]
    session = MagicMock()
    session.scalars.return_value = expected
    assert find_products(session, "váy") == expected


def test_add_order_requires_existing_product() -> None:
    session = MagicMock()
    session.get.return_value = None
    with pytest.raises(ValueError, match="Không tìm thấy SKU"):
        add_order(
            session,
            sku="VAY01",
            quantity=5,
            order_date=date(2026, 9, 13),
            telegram_user_id=123,
        )


def test_add_and_total_orders() -> None:
    session = MagicMock()
    session.get.return_value = Product(sku="VAY01", name="Váy")
    order = add_order(
        session,
        sku="vay01",
        quantity=5,
        order_date=date(2026, 9, 13),
        telegram_user_id=123,
    )
    assert order.sku == "VAY01"
    assert order.quantity == 5
    session.scalar.return_value = 8
    assert (
        total_orders(
            session,
            telegram_user_id=123,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 10, 1),
        )
        == 8
    )


def test_create_reminder_requires_future_aware_time() -> None:
    session = MagicMock()
    with pytest.raises(ValueError, match="timezone"):
        create_reminder(
            session,
            user_id=1,
            chat_id=2,
            content="Test",
            remind_at=datetime(2099, 1, 1),
        )


def test_create_list_and_cancel_reminder() -> None:
    session = MagicMock()
    reminder = create_reminder(
        session,
        user_id=1,
        chat_id=2,
        content=" Test ",
        remind_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert reminder.content == "Test"
    session.scalars.return_value = [reminder]
    assert list_pending_reminders(session, user_id=1) == [reminder]
    session.execute.return_value.rowcount = 1
    assert cancel_reminder(session, reminder_id=uuid.uuid4(), user_id=1) is True


def test_create_pending_action_has_expiry() -> None:
    session = MagicMock()
    action = create_pending_action(
        session,
        user_id=1,
        chat_id=2,
        action_type="create_sku",
        payload={"sku": "VAY01"},
        ttl_minutes=15,
    )
    assert action.status == "pending"
    assert action.expires_at > datetime.now(timezone.utc)


def test_claim_and_mark_reminder_sent() -> None:
    now = datetime.now(timezone.utc)
    reminder = Reminder(
        id=uuid.uuid4(),
        telegram_user_id=1,
        chat_id=2,
        content="Test",
        remind_at=now - timedelta(minutes=1),
        status="pending",
    )
    session = MagicMock()
    session.scalars.return_value = [reminder]
    claimed = claim_due_reminders(session, batch_size=10, lock_timeout_seconds=120, now=now)
    assert claimed == [reminder]
    assert reminder.status == "processing"
    assert reminder.locked_at == now
    session.get.return_value = reminder
    mark_reminder_sent(session, reminder, now=now)
    assert reminder.status == "sent"
    assert reminder.sent_at == now
