import pytest

from services.update_processor import parse_update


def test_parse_message_update() -> None:
    context = parse_update(
        {
            "update_id": 100,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 456},
                "text": "Xin chào",
            },
        }
    )
    assert context.update_id == 100
    assert context.user_id == 123
    assert context.chat_id == 456
    assert context.text == "Xin chào"
    assert context.callback_data is None


def test_parse_callback_update() -> None:
    context = parse_update(
        {
            "update_id": 101,
            "callback_query": {
                "id": "callback-1",
                "from": {"id": 123},
                "message": {"chat": {"id": 456}},
                "data": "confirm:action-id",
            },
        }
    )
    assert context.user_id == 123
    assert context.chat_id == 456
    assert context.callback_query_id == "callback-1"
    assert context.callback_data == "confirm:action-id"


def test_parse_photo_uses_largest_size_and_caption() -> None:
    context = parse_update(
        {
            "update_id": 102,
            "message": {
                "from": {"id": 123},
                "chat": {"id": 456},
                "caption": "đây là mã SKU VAY01",
                "photo": [
                    {"file_id": "small", "file_unique_id": "u-small", "width": 90, "height": 90},
                    {"file_id": "large", "file_unique_id": "u-large", "width": 800, "height": 600},
                ],
            },
        }
    )

    assert context.photo_file_id == "large"
    assert context.photo_file_unique_id == "u-large"
    assert context.caption == "đây là mã SKU VAY01"


def test_invalid_update_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="update_id"):
        parse_update({"message": {}})
