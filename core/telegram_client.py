from typing import Any

import httpx


class TelegramAPIError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


class TelegramClient:
    def __init__(self, token: str, *, timeout_seconds: float = 10.0) -> None:
        self._token = token
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._timeout = httpx.Timeout(timeout_seconds, connect=5.0)

    def send_message(self, chat_id: int, text: str, **extra: Any) -> dict[str, Any]:
        return self._post("sendMessage", {"chat_id": chat_id, "text": text, **extra})

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self._post("sendChatAction", {"chat_id": chat_id, "action": action})

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self._post("answerCallbackQuery", payload)

    def edit_message_reply_markup(self, chat_id: int, message_id: int) -> None:
        self._post(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )

    def download_file(self, file_id: str, *, max_bytes: int = 10_000_000) -> bytes:
        file_info = self._post("getFile", {"file_id": file_id})
        file_path = file_info.get("file_path")
        file_size = file_info.get("file_size")
        if not isinstance(file_path, str):
            raise TelegramAPIError("Telegram did not return a file path", retryable=False)
        if isinstance(file_size, int) and file_size > max_bytes:
            raise TelegramAPIError("Image is too large", retryable=False)
        try:
            response = httpx.get(
                f"https://api.telegram.org/file/bot{self._token}/{file_path}",
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            raise TelegramAPIError("Telegram file download failed", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            raise TelegramAPIError(
                "Telegram file download failed", retryable=exc.response.status_code >= 500
            ) from exc
        if len(response.content) > max_bytes:
            raise TelegramAPIError("Image is too large", retryable=False)
        return response.content

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(f"{self._base_url}/{method}", json=payload, timeout=self._timeout)
        except httpx.RequestError as exc:
            raise TelegramAPIError("Telegram network error", retryable=True) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramAPIError(
                "Telegram returned an invalid response",
                retryable=response.status_code >= 500,
            ) from exc
        if response.is_success and data.get("ok") is True:
            result = data.get("result")
            return result if isinstance(result, dict) else {}

        parameters = data.get("parameters") if isinstance(data, dict) else None
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        retryable = response.status_code == 429 or response.status_code >= 500
        description = (
            data.get("description", "Telegram API error")
            if isinstance(data, dict)
            else "Telegram API error"
        )
        raise TelegramAPIError(description, retryable=retryable, retry_after=retry_after)
