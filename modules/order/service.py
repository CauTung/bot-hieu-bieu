import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.order import Order
from models.product import Product, normalize_sku


def add_order(
    session: Session,
    *,
    sku: str,
    quantity: int,
    order_date: date,
    telegram_user_id: int,
    source: str | None = None,
) -> Order:
    if quantity <= 0:
        raise ValueError("Số lượng phải lớn hơn 0")
    normalized = normalize_sku(sku)
    if session.get(Product, normalized) is None:
        raise ValueError(f"Không tìm thấy SKU {normalized}")
    order = Order(
        id=uuid.uuid4(),
        sku=normalized,
        quantity=quantity,
        order_date=order_date,
        telegram_user_id=telegram_user_id,
        source=source.strip() if source and source.strip() else None,
    )
    session.add(order)
    session.flush()
    return order


def total_orders(
    session: Session, *, telegram_user_id: int, start_date: date, end_date: date
) -> int:
    total = session.scalar(
        select(func.coalesce(func.sum(Order.quantity), 0)).where(
            Order.telegram_user_id == telegram_user_id,
            Order.order_date >= start_date,
            Order.order_date < end_date,
        )
    )
    return int(total or 0)


def list_orders(
    session: Session,
    *,
    telegram_user_id: int,
    start_date: date,
    end_date: date,
    limit: int = 10,
) -> list[Order]:
    statement = (
        select(Order)
        .where(
            Order.telegram_user_id == telegram_user_id,
            Order.order_date >= start_date,
            Order.order_date < end_date,
        )
        .order_by(Order.order_date.desc(), Order.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(statement))


def update_order(
    session: Session,
    *,
    order_id: uuid.UUID,
    telegram_user_id: int,
    sku: str | None = None,
    quantity: int | None = None,
    order_date: date | None = None,
    source: str | None = None,
) -> Order:
    order = session.get(Order, order_id)
    if order is None or order.telegram_user_id != telegram_user_id:
        raise ValueError("Không tìm thấy order")
    if quantity is not None and quantity <= 0:
        raise ValueError("Số lượng phải lớn hơn 0")
    if sku is not None:
        normalized = normalize_sku(sku)
        if session.get(Product, normalized) is None:
            raise ValueError(f"Không tìm thấy SKU {normalized}")
        order.sku = normalized
    if quantity is not None:
        order.quantity = quantity
    if order_date is not None:
        order.order_date = order_date
    if source is not None:
        order.source = source.strip() or None
    session.flush()
    return order


def delete_order(session: Session, *, order_id: uuid.UUID, telegram_user_id: int) -> bool:
    order = session.get(Order, order_id)
    if order is None or order.telegram_user_id != telegram_user_id:
        return False
    session.delete(order)
    session.flush()
    return True
