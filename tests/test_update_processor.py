from typing import Any

import pytest

from services.update_processor import parse_update, process_placeholder_update


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.answered_callbacks: list[tuple[str, str | None]] = []

    def send_message(self, chat_id: int, text: str, **extra: Any) -> dict[str, Any]:
        self.messages.append((chat_id, text))
        return {}

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.answered_callbacks.append((callback_query_id, text))


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


def test_invalid_update_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="update_id"):
        parse_update({"message": {}})


def test_placeholder_message_sends_response() -> None:
    telegram = FakeTelegram()
    context = parse_update(
        {
            "update_id": 100,
            "message": {"from": {"id": 123}, "chat": {"id": 456}, "text": "Hi"},
        }
    )
    process_placeholder_update(context, telegram)
    assert telegram.messages == [
        (456, "Bot đã kết nối an toàn. Bộ phân tích yêu cầu đang được triển khai.")
    ]


def test_placeholder_callback_is_always_answered() -> None:
    telegram = FakeTelegram()
    context = parse_update(
        {
            "update_id": 101,
            "callback_query": {
                "id": "callback-1",
                "from": {"id": 123},
                "message": {"chat": {"id": 456}},
            },
        }
    )
    process_placeholder_update(context, telegram)
    assert telegram.answered_callbacks == [
        ("callback-1", "Tính năng xác nhận đang được hoàn thiện.")
    ]
