import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from models.pending_action import PendingAction


def create_pending_action(
    session: Session,
    *,
    user_id: int,
    chat_id: int,
    action_type: str,
    payload: dict[str, object],
    ttl_minutes: int,
) -> PendingAction:
    action = PendingAction(
        telegram_user_id=user_id,
        chat_id=chat_id,
        action_type=action_type,
        payload=payload,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    )
    session.add(action)
    session.flush()
    return action


def consume_pending_action(
    session: Session,
    *,
    action_id: uuid.UUID,
    user_id: int,
    chat_id: int,
    confirm: bool,
    now: datetime | None = None,
) -> PendingAction | None:
    current_time = now or datetime.now(timezone.utc)
    next_status = "confirmed" if confirm else "cancelled"
    result = session.execute(
        update(PendingAction)
        .where(
            PendingAction.id == action_id,
            PendingAction.telegram_user_id == user_id,
            PendingAction.chat_id == chat_id,
            PendingAction.status == "pending",
            PendingAction.expires_at > current_time,
        )
        .values(status=next_status, confirmed_at=current_time if confirm else None)
        .returning(PendingAction)
    )
    return result.scalar_one_or_none()


def expire_old_actions(session: Session, *, now: datetime | None = None) -> int:
    result = session.execute(
        update(PendingAction)
        .where(
            PendingAction.status == "pending",
            PendingAction.expires_at <= (now or datetime.now(timezone.utc)),
        )
        .values(status="expired")
    )
    return int(result.rowcount or 0)
