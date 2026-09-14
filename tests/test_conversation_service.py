from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from core.intent_schema import Intent, IntentDecision
from models.conversation_state import ConversationState
from services.conversation_service import (
    clear_conversation_state,
    get_conversation_state,
    save_conversation_state,
)
from tests.test_bot_service import params


def test_expired_conversation_state_is_deleted() -> None:
    now = datetime.now(timezone.utc)
    state = ConversationState(
        telegram_user_id=1,
        chat_id=2,
        intent="create_reminder",
        params={},
        clarification_question="Khi nào?",
        expires_at=now - timedelta(seconds=1),
    )
    session = MagicMock()
    session.get.return_value = state

    assert get_conversation_state(session, user_id=1, chat_id=2, now=now) is None
    session.delete.assert_called_once_with(state)


def test_save_and_clear_conversation_state() -> None:
    now = datetime.now(timezone.utc)
    decision = IntentDecision(
        intent=Intent.CREATE_REMINDER,
        params=params(content="Lịch đi nhậu"),
        confidence=0.9,
        clarification_question="Bạn muốn đặt lúc nào?",
    )
    session = MagicMock()
    session.get.return_value = None

    state = save_conversation_state(
        session,
        user_id=1,
        chat_id=2,
        decision=decision,
        ttl_minutes=30,
        now=now,
    )

    assert state.intent == "create_reminder"
    assert state.params["content"] == "Lịch đi nhậu"
    assert state.expires_at == now + timedelta(minutes=30)

    session.get.return_value = state
    clear_conversation_state(session, user_id=1, chat_id=2)
    session.delete.assert_called_with(state)
