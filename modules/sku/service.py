from sqlalchemy import or_, select
from sqlalchemy.orm import Session

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
