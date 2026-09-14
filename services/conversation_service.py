from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from core.intent_schema import IntentDecision
from models.conversation_state import ConversationState


def get_conversation_state(
    session: Session,
    *,
    user_id: int,
    chat_id: int,
    now: datetime | None = None,
) -> ConversationState | None:
    state = session.get(ConversationState, (user_id, chat_id))
    if state is None:
        return None
    if state.expires_at <= (now or datetime.now(timezone.utc)):
        session.delete(state)
        session.flush()
        return None
    return state


def save_conversation_state(
    session: Session,
    *,
    user_id: int,
    chat_id: int,
    decision: IntentDecision,
    ttl_minutes: int,
    now: datetime | None = None,
) -> ConversationState:
    current_time = now or datetime.now(timezone.utc)
    state = session.get(ConversationState, (user_id, chat_id))
    if state is None:
        state = ConversationState(
            telegram_user_id=user_id,
            chat_id=chat_id,
            intent=decision.intent.value,
            params=decision.params.model_dump(mode="json"),
            clarification_question=decision.clarification_question or "",
            expires_at=current_time + timedelta(minutes=ttl_minutes),
        )
        session.add(state)
    else:
        state.intent = decision.intent.value
        state.params = decision.params.model_dump(mode="json")
        state.clarification_question = decision.clarification_question or ""
        state.expires_at = current_time + timedelta(minutes=ttl_minutes)
    session.flush()
    return state


def clear_conversation_state(session: Session, *, user_id: int, chat_id: int) -> None:
    state = session.get(ConversationState, (user_id, chat_id))
    if state is not None:
        session.delete(state)
        session.flush()
