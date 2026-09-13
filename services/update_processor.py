from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.processed_update import ProcessedUpdate


class TelegramPort(Protocol):
    def send_message(self, chat_id: int, text: str, **extra: Any) -> dict[str, Any]: ...

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None: ...


@dataclass(frozen=True)
class UpdateContext:
    update_id: int
    user_id: int | None
    chat_id: int | None
    text: str | None
    callback_query_id: str | None


def parse_update(payload: dict[str, Any]) -> UpdateContext:
    update_id = payload.get("update_id")
    if not isinstance(update_id, int):
        raise ValueError("Missing or invalid update_id")

    message = payload.get("message")
    if isinstance(message, dict):
        sender = message.get("from")
        chat = message.get("chat")
        return UpdateContext(
            update_id=update_id,
            user_id=sender.get("id") if isinstance(sender, dict) else None,
            chat_id=chat.get("id") if isinstance(chat, dict) else None,
            text=message.get("text") if isinstance(message.get("text"), str) else None,
            callback_query_id=None,
        )

    callback = payload.get("callback_query")
    if isinstance(callback, dict):
        sender = callback.get("from")
        callback_message = callback.get("message")
        chat = callback_message.get("chat") if isinstance(callback_message, dict) else None
        return UpdateContext(
            update_id=update_id,
            user_id=sender.get("id") if isinstance(sender, dict) else None,
            chat_id=chat.get("id") if isinstance(chat, dict) else None,
            text=None,
            callback_query_id=callback.get("id") if isinstance(callback.get("id"), str) else None,
        )

    return UpdateContext(update_id, None, None, None, None)


def claim_update(session: Session, update_id: int) -> bool:
    session.add(ProcessedUpdate(update_id=update_id, status="processing"))
    try:
        session.flush()
        return True
    except IntegrityError:
        session.rollback()
        return False


def complete_update(session: Session, update_id: int) -> None:
    update = session.get(ProcessedUpdate, update_id)
    if update is None:
        raise RuntimeError("Claimed update no longer exists")
    update.status = "completed"
    update.processed_at = datetime.now(timezone.utc)


def process_placeholder_update(context: UpdateContext, telegram: TelegramPort) -> None:
    if context.callback_query_id:
        telegram.answer_callback_query(
            context.callback_query_id, "Tính năng xác nhận đang được hoàn thiện."
        )
        return
    if context.chat_id is not None and context.text:
        telegram.send_message(
            context.chat_id,
            "Bot đã kết nối an toàn. Bộ phân tích yêu cầu đang được triển khai.",
        )
