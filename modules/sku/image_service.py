import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.product import Product, normalize_sku
from models.sku_image_fingerprint import SkuImageFingerprint

MAX_IMAGE_PIXELS = 25_000_000
MAX_HASH_DISTANCE = 6


@dataclass(frozen=True)
class ImageFingerprint:
    sha256: str
    perceptual_hash: str


def fingerprint_image(data: bytes) -> ImageFingerprint:
    if not data:
        raise ValueError("Ảnh rỗng hoặc không đọc được.")
    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(BytesIO(data)) as source:
            source.verify()
        with Image.open(BytesIO(data)) as source:
            gray = (
                ImageOps.exif_transpose(source)
                .convert("L")
                .resize((9, 8), Image.Resampling.LANCZOS)
            )
            pixels = list(gray.getdata())
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Tệp gửi lên không phải ảnh hợp lệ.") from exc
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | int(
                pixels[row * 9 + column] > pixels[row * 9 + column + 1]
            )
    return ImageFingerprint(hashlib.sha256(data).hexdigest(), f"{bits:016x}")


def save_image_mapping(
    session: Session,
    *,
    sku: str,
    telegram_file_unique_id: str,
    sha256: str,
    perceptual_hash: str,
    user_id: int,
    chat_id: int,
) -> SkuImageFingerprint:
    normalized = normalize_sku(sku)
    if session.get(Product, normalized) is None:
        raise ValueError(f"Không tìm thấy SKU {normalized}. Hãy tạo SKU trước.")
    existing = session.scalar(
        select(SkuImageFingerprint).where(
            SkuImageFingerprint.telegram_file_unique_id == telegram_file_unique_id
        )
    )
    if existing is None:
        existing = SkuImageFingerprint(
            sku=normalized,
            telegram_file_unique_id=telegram_file_unique_id,
            sha256=sha256,
            perceptual_hash=perceptual_hash,
            created_by_user_id=user_id,
            created_in_chat_id=chat_id,
        )
        session.add(existing)
    else:
        existing.sku = normalized
        existing.sha256 = sha256
        existing.perceptual_hash = perceptual_hash
        existing.created_by_user_id = user_id
        existing.created_in_chat_id = chat_id
    session.flush()
    return existing


def find_sku_by_image(
    session: Session,
    *,
    telegram_file_unique_id: str,
    fingerprint: ImageFingerprint,
) -> tuple[str | None, str]:
    exact = session.scalar(
        select(SkuImageFingerprint).where(
            or_(
                SkuImageFingerprint.telegram_file_unique_id == telegram_file_unique_id,
                SkuImageFingerprint.sha256 == fingerprint.sha256,
            )
        )
    )
    if exact is not None:
        return exact.sku, "exact"
    candidates = list(session.scalars(select(SkuImageFingerprint)))
    ranked = sorted(
        [
            (
                (int(item.perceptual_hash, 16) ^ int(fingerprint.perceptual_hash, 16)).bit_count(),
                item,
            )
            for item in candidates
        ],
        key=lambda pair: pair[0],
    )
    if not ranked or ranked[0][0] > MAX_HASH_DISTANCE:
        return None, "none"
    best_distance = ranked[0][0]
    best_skus = {item.sku for distance, item in ranked if distance == best_distance}
    if len(best_skus) != 1:
        return None, "ambiguous"
    return ranked[0][1].sku, "similar"
