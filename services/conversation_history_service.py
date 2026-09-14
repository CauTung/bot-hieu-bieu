from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.conversation_exchange import ConversationExchange

MAX_STORED_TEXT_LENGTH = 2_000
MAX_CONTEXT_USER_TEXT_LENGTH = 500
MAX_CONTEXT_ASSISTANT_TEXT_LENGTH = 1_000


def record_exchange(
    session: Session,
    *,
    user_id: int,
    chat_id: int,
    user_text: str,
    assistant_text: str,
    retention_days: int,
    intent: str | None = None,
    details: dict[str, object] | None = None,
    now: datetime | None = None,
) -> ConversationExchange:
    current_time = now or datetime.now(timezone.utc)
    exchange = ConversationExchange(
        telegram_user_id=user_id,
        chat_id=chat_id,
        user_text=user_text.strip()[:MAX_STORED_TEXT_LENGTH],
        assistant_text=assistant_text.strip()[:MAX_STORED_TEXT_LENGTH],
        intent=intent,
        details=details,
        expires_at=current_time + timedelta(days=retention_days),
    )
    session.add(exchange)
    session.flush()
    return exchange


def recent_exchanges(
    session: Session,
    *,
    user_id: int,
    chat_id: int,
    limit: int,
    now: datetime | None = None,
) -> list[ConversationExchange]:
    current_time = now or datetime.now(timezone.utc)
    session.execute(
        delete(ConversationExchange).where(ConversationExchange.expires_at <= current_time)
    )
    statement = (
        select(ConversationExchange)
        .where(
            ConversationExchange.telegram_user_id == user_id,
            ConversationExchange.chat_id == chat_id,
            ConversationExchange.expires_at > current_time,
        )
        .order_by(ConversationExchange.created_at.desc())
        .limit(limit)
    )
    return list(reversed(list(session.scalars(statement))))


def history_context(exchanges: list[ConversationExchange]) -> list[dict[str, object]]:
    return [
        {
            "user": exchange.user_text[:MAX_CONTEXT_USER_TEXT_LENGTH],
            "assistant": exchange.assistant_text[:MAX_CONTEXT_ASSISTANT_TEXT_LENGTH],
            "intent": exchange.intent,
            "details": exchange.details,
        }
        for exchange in exchanges
    ]
