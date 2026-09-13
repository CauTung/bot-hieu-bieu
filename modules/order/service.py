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
