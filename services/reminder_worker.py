from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from models.reminder import Reminder


@dataclass(frozen=True)
class DeliveryResult:
    sent: int = 0
    retried: int = 0
    failed: int = 0


def claim_due_reminders(
    session: Session,
    *,
    batch_size: int,
    lock_timeout_seconds: int,
    now: datetime | None = None,
) -> list[Reminder]:
    current_time = now or datetime.now(timezone.utc)
    stale_before = current_time - timedelta(seconds=lock_timeout_seconds)
    session.execute(
        update(Reminder)
        .where(Reminder.status == "processing", Reminder.locked_at < stale_before)
        .values(status="pending", locked_at=None)
    )
    due = list(
        session.scalars(
            select(Reminder)
            .where(
                Reminder.status == "pending",
                Reminder.remind_at <= current_time,
                or_(Reminder.next_retry_at.is_(None), Reminder.next_retry_at <= current_time),
            )
            .order_by(Reminder.remind_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for reminder in due:
        reminder.status = "processing"
        reminder.locked_at = current_time
    session.flush()
    return due


def mark_reminder_sent(
    session: Session, reminder: Reminder, *, now: datetime | None = None
) -> None:
    stored = session.get(Reminder, reminder.id)
    if stored is None or stored.status != "processing":
        return
    current_time = now or datetime.now(timezone.utc)
    
    if stored.recurrence == "daily":
        stored.status = "pending"
        stored.remind_at = stored.remind_at + timedelta(days=1)
        if stored.event_at:
            stored.event_at = stored.event_at + timedelta(days=1)
        stored.locked_at = None
        stored.attempt_count = 0
        stored.next_retry_at = None
        stored.last_error = None
    elif stored.recurrence == "weekly":
        stored.status = "pending"
        stored.remind_at = stored.remind_at + timedelta(weeks=1)
        if stored.event_at:
            stored.event_at = stored.event_at + timedelta(weeks=1)
        stored.locked_at = None
        stored.attempt_count = 0
        stored.next_retry_at = None
        stored.last_error = None
    elif stored.recurrence == "monthly":
        # Simple approximation, better to use dateutil.relativedelta but timedelta(days=30) works for simple use case
        stored.status = "pending"
        stored.remind_at = stored.remind_at + timedelta(days=30)
        if stored.event_at:
            stored.event_at = stored.event_at + timedelta(days=30)
        stored.locked_at = None
        stored.attempt_count = 0
        stored.next_retry_at = None
        stored.last_error = None
    else:
        stored.status = "sent"
        stored.sent_at = current_time
        stored.locked_at = None
        stored.last_error = None


def mark_reminder_error(
    session: Session,
    reminder: Reminder,
    error: Exception,
    *,
    max_attempts: int,
    now: datetime | None = None,
) -> str:
    stored = session.get(Reminder, reminder.id)
    if stored is None or stored.status != "processing":
        return "ignored"
    current_time = now or datetime.now(timezone.utc)
    stored.attempt_count += 1
    stored.locked_at = None
    stored.last_error = f"{type(error).__name__}: {error}"[:500]
    if stored.attempt_count >= max_attempts:
        stored.status = "failed"
        stored.next_retry_at = None
        return "failed"
    stored.status = "pending"
    stored.next_retry_at = current_time + timedelta(
        seconds=retry_delay_seconds(stored.attempt_count)
    )
    return "retried"


def retry_delay_seconds(attempt_count: int) -> int:
    exponent: int = max(0, attempt_count - 1)
    delay: int = 30 * (2**exponent)
    return min(delay, 3600)
