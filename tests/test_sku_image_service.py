from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image

from models.sku_image_fingerprint import SkuImageFingerprint
from modules.sku.image_service import ImageFingerprint, find_sku_by_image, fingerprint_image


def make_image(size: tuple[int, int] = (80, 80), *, quality: int = 90) -> bytes:
    image = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            image.putpixel((x, y), ((x * 9) % 255, (y * 13) % 255, ((x + y) * 5) % 255))
    output = BytesIO()
    image.save(output, format="JPEG", quality=quality)
    return output.getvalue()


def resize_image(data: bytes, size: tuple[int, int], *, quality: int) -> bytes:
    with Image.open(BytesIO(data)) as image:
        resized = image.resize(size, Image.Resampling.LANCZOS)
        output = BytesIO()
        resized.save(output, format="JPEG", quality=quality)
        return output.getvalue()


def test_fingerprint_survives_resize_and_recompression() -> None:
    source = make_image(quality=95)
    original = fingerprint_image(source)
    resized = fingerprint_image(resize_image(source, (160, 160), quality=70))
    distance = (int(original.perceptual_hash, 16) ^ int(resized.perceptual_hash, 16)).bit_count()
    assert distance <= 6
    assert original.sha256 != resized.sha256


def test_find_sku_prefers_exact_file_identifier() -> None:
    mapping = SkuImageFingerprint(
        sku="VAY01",
        telegram_file_unique_id="unique-1",
        sha256="a" * 64,
        perceptual_hash="0" * 16,
        created_by_user_id=1,
        created_in_chat_id=2,
    )
    session = MagicMock()
    session.scalar.return_value = mapping

    sku, match_type = find_sku_by_image(
        session,
        telegram_file_unique_id="unique-1",
        fingerprint=ImageFingerprint("b" * 64, "f" * 16),
    )

    assert (sku, match_type) == ("VAY01", "exact")
