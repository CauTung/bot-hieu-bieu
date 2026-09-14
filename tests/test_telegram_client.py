from typing import Any

import httpx
import pytest

from core.telegram_client import TelegramAPIError, TelegramClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None) -> None:
        self.status_code = status_code
        self._payload = payload

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_send_message_returns_telegram_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args: Any, **kwargs: Any) -> FakeResponse:
        assert kwargs["json"] == {"chat_id": 123, "text": "Hello"}
        return FakeResponse(200, {"ok": True, "result": {"message_id": 10}})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = TelegramClient("test-token").send_message(123, "Hello")
    assert result == {"message_id": 10}


def test_send_chat_action_posts_typing_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args: Any, **kwargs: Any) -> FakeResponse:
        assert args[0].endswith("/sendChatAction")
        assert kwargs["json"] == {"chat_id": 123, "action": "typing"}
        return FakeResponse(200, {"ok": True, "result": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    TelegramClient("test-token").send_chat_action(123)


def test_rate_limit_error_exposes_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            429,
            {
                "ok": False,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 7},
            },
        ),
    )
    with pytest.raises(TelegramAPIError) as caught:
        TelegramClient("test-token").send_message(123, "Hello")
    assert caught.value.retryable is True
    assert caught.value.retry_after == 7


def test_network_error_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> FakeResponse:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(TelegramAPIError) as caught:
        TelegramClient("test-token").send_message(123, "Hello")
    assert caught.value.retryable is True


def test_invalid_server_response_is_retryable_for_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(502, None))
    with pytest.raises(TelegramAPIError) as caught:
        TelegramClient("test-token").send_message(123, "Hello")
    assert caught.value.retryable is True
