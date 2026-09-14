import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from models.reminder import Reminder


def create_reminder(
    session: Session,
    *,
    user_id: int,
    chat_id: int,
    content: str,
    remind_at: datetime,
    event_at: datetime | None = None,
) -> Reminder:
    now = datetime.now(timezone.utc)
    if remind_at.tzinfo is None:
        raise ValueError("Thời gian nhắc phải có timezone")
    if event_at is not None and event_at.tzinfo is None:
        raise ValueError("Thời gian sự kiện phải có timezone")
    remind_at_utc = remind_at.astimezone(timezone.utc)
    if remind_at_utc <= now:
        raise ValueError("Thời gian nhắc phải ở tương lai")
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("Nội dung nhắc không được để trống")
    reminder = Reminder(
        id=uuid.uuid4(),
        telegram_user_id=user_id,
        chat_id=chat_id,
        content=clean_content,
        remind_at=remind_at_utc,
        event_at=event_at.astimezone(timezone.utc) if event_at is not None else None,
        status="pending",
    )
    session.add(reminder)
    session.flush()
    return reminder


def list_pending_reminders(session: Session, *, user_id: int, limit: int = 20) -> list[Reminder]:
    return list(
        session.scalars(
            select(Reminder)
            .where(Reminder.telegram_user_id == user_id, Reminder.status == "pending")
            .order_by(Reminder.remind_at)
            .limit(limit)
        )
    )


def cancel_reminder(session: Session, *, reminder_id: uuid.UUID, user_id: int) -> bool:
    result = session.execute(
        update(Reminder)
        .where(
            Reminder.id == reminder_id,
            Reminder.telegram_user_id == user_id,
            Reminder.status == "pending",
        )
        .values(status="cancelled")
    )
    return bool(result.rowcount)
