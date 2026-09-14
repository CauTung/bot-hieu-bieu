from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from models.conversation_exchange import ConversationExchange
from services.conversation_history_service import (
    history_context,
    recent_exchanges,
    record_exchange,
)


def test_record_exchange_has_bounded_text_and_retention() -> None:
    now = datetime.now(timezone.utc)
    session = MagicMock()
    exchange = record_exchange(
        session,
        user_id=1,
        chat_id=2,
        user_text="x" * 3_000,
        assistant_text="Đã hiểu",
        retention_days=30,
        intent="qa",
        now=now,
    )
    assert len(exchange.user_text) == 2_000
    assert exchange.expires_at == now + timedelta(days=30)
    session.add.assert_called_once_with(exchange)


def test_recent_history_is_returned_in_chronological_order() -> None:
    now = datetime.now(timezone.utc)
    older = ConversationExchange(
        telegram_user_id=1,
        chat_id=2,
        user_text="Câu trước",
        assistant_text="Trả lời trước",
        expires_at=now + timedelta(days=1),
    )
    newer = ConversationExchange(
        telegram_user_id=1,
        chat_id=2,
        user_text="Câu sau",
        assistant_text="Trả lời sau",
        expires_at=now + timedelta(days=1),
    )
    session = MagicMock()
    session.scalars.return_value = [newer, older]

    result = recent_exchanges(session, user_id=1, chat_id=2, limit=8, now=now)

    assert result == [older, newer]
    assert history_context(result)[0]["user"] == "Câu trước"
