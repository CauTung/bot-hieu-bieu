from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from models.order import Order
from models.product import Product, normalize_sku


def create_product(
    session: Session,
    *,
    sku: str,
    name: str,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> tuple[Product, bool]:
    normalized = normalize_sku(sku)
    existing = session.get(Product, normalized)
    if existing is not None:
        return existing, False
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Tên mẫu không được để trống")
    product = Product(
        sku=normalized,
        name=clean_name,
        tags=[tag.strip() for tag in tags or [] if tag.strip()] or None,
        notes=notes.strip() if notes and notes.strip() else None,
    )
    session.add(product)
    session.flush()
    return product, True


def find_products(session: Session, query: str, *, limit: int = 5) -> list[Product]:
    clean_query = query.strip()
    if not clean_query:
        return []
    normalized = clean_query.upper() if len(clean_query) <= 100 else ""
    pattern = f"%{clean_query}%"
    statement = (
        select(Product)
        .where(or_(Product.sku == normalized, Product.name.ilike(pattern)))
        .order_by((Product.sku == normalized).desc(), Product.sku)
        .limit(limit)
    )
    return list(session.scalars(statement))


def update_product(
    session: Session,
    *,
    sku: str,
    new_sku: str | None = None,
    name: str | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> Product:
    normalized = normalize_sku(sku)
    product = session.get(Product, normalized)
    if product is None:
        raise ValueError(f"Không tìm thấy SKU {normalized}")

    target_sku = normalize_sku(new_sku) if new_sku else normalized
    clean_name = name.strip() if name is not None else product.name
    if not clean_name:
        raise ValueError("Tên mẫu không được để trống")
    clean_tags = (
        [tag.strip() for tag in tags or [] if tag.strip()]
        if tags is not None
        else product.tags
    )
    clean_notes = notes.strip() or None if notes is not None else product.notes

    if target_sku == normalized:
        product.name = clean_name
        product.tags = clean_tags or None
        product.notes = clean_notes
        session.flush()
        return product

    if session.get(Product, target_sku) is not None:
        raise ValueError(f"SKU {target_sku} đã tồn tại")
    replacement = Product(
        sku=target_sku,
        name=clean_name,
        tags=clean_tags or None,
        notes=clean_notes,
    )
    session.add(replacement)
    session.flush()
    session.execute(update(Order).where(Order.sku == normalized).values(sku=target_sku))
    session.delete(product)
    session.flush()
    return replacement


def delete_product(session: Session, *, sku: str) -> bool:
    normalized = normalize_sku(sku)
    product = session.get(Product, normalized)
    if product is None:
        return False
    order_count = session.scalar(
        select(func.count()).select_from(Order).where(Order.sku == normalized)
    )
    if int(order_count or 0) > 0:
        raise ValueError(f"SKU {normalized} đang có order; hãy xóa các order đó trước")
    session.delete(product)
    session.flush()
    return True
