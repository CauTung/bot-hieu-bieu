import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from models.order import Order
from models.product import Product
from models.reminder import Reminder
from modules.order.service import add_order, delete_order, list_orders, total_orders, update_order
from modules.reminder.service import cancel_reminder, create_reminder, list_pending_reminders
from modules.sku.service import create_product, delete_product, find_products, update_product
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


def test_update_product_fields_without_renaming() -> None:
    product = Product(sku="VAY01", name="Tên cũ", tags=["cũ"], notes=None)
    session = MagicMock()
    session.get.return_value = product

    result = update_product(
        session,
        sku="vay01",
        name=" Tên mới ",
        tags=[" mới ", ""],
        notes=" ghi chú ",
    )

    assert result is product
    assert result.name == "Tên mới"
    assert result.tags == ["mới"]
    assert result.notes == "ghi chú"


def test_update_product_renames_sku_and_moves_orders() -> None:
    product = Product(sku="OLD", name="Mẫu")
    session = MagicMock()
    session.get.side_effect = [product, None]

    result = update_product(session, sku="OLD", new_sku="new")

    assert result.sku == "NEW"
    session.execute.assert_called_once()
    session.delete.assert_called_once_with(product)


def test_delete_product_rejects_sku_with_orders() -> None:
    product = Product(sku="VAY01", name="Váy")
    session = MagicMock()
    session.get.return_value = product
    session.scalar.return_value = 2

    with pytest.raises(ValueError, match="đang có order"):
        delete_product(session, sku="VAY01")


def test_delete_product_without_orders() -> None:
    product = Product(sku="VAY01", name="Váy")
    session = MagicMock()
    session.get.return_value = product
    session.scalar.return_value = 0

    assert delete_product(session, sku="VAY01") is True
    session.delete.assert_called_once_with(product)


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


def test_list_update_and_delete_order_are_scoped_to_owner() -> None:
    order_id = uuid.uuid4()
    order = Order(
        id=order_id,
        sku="VAY01",
        quantity=2,
        order_date=date(2026, 9, 13),
        telegram_user_id=123,
    )
    session = MagicMock()
    session.scalars.return_value = [order]
    assert list_orders(
        session,
        telegram_user_id=123,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 10, 1),
    ) == [order]

    session.get.side_effect = [order, Product(sku="VAY02", name="Váy 2")]
    updated = update_order(
        session,
        order_id=order_id,
        telegram_user_id=123,
        sku="vay02",
        quantity=5,
        order_date=date(2026, 9, 14),
    )
    assert updated.sku == "VAY02"
    assert updated.quantity == 5
    assert updated.order_date == date(2026, 9, 14)

    session.get.side_effect = None
    session.get.return_value = order
    assert delete_order(session, order_id=order_id, telegram_user_id=456) is False
    assert delete_order(session, order_id=order_id, telegram_user_id=123) is True
    session.delete.assert_called_once_with(order)


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
