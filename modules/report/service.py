import hashlib
from datetime import date, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.report_schema import ReportDraft, person_key
from models.person_report import PersonReport


def scope_lock(session: Session, user_id: int, chat_id: int) -> None:
    """Serialize report previews and writes within one scope on PostgreSQL."""
    if session.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(
            hashlib.sha256(f"report:{user_id}:{chat_id}".encode()).digest()[:8],
            "big", signed=True,
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def existing_rows(
    session: Session, user_id: int, chat_id: int, report_date: date,
) -> dict[str, PersonReport]:
    rows = session.scalars(select(PersonReport).where(
        PersonReport.telegram_user_id == user_id,
        PersonReport.chat_id == chat_id,
        PersonReport.report_date == report_date,
    ).execution_options(populate_existing=True)).all()
    return {row.person_key: row for row in rows}


def snapshot(
    session: Session, draft: ReportDraft, user_id: int, chat_id: int,
) -> tuple[dict[str, object], list[str]]:
    assert draft.report_date is not None
    current = existing_rows(session, user_id, chat_id, draft.report_date)
    expected: dict[str, object] = {}
    changes = []
    for row in draft.rows:
        key = person_key(row.name)
        old = current.get(key)
        expected[key] = old.revision if old else None
        if old:
            changes.append(f"• {row.name}: {old.count} → {row.count}")
    return expected, changes


def save_report(
    session: Session, payload: dict[str, object], user_id: int, chat_id: int,
) -> str:
    draft = ReportDraft.model_validate(payload.get("draft"))
    problem = draft.problem()
    if problem:
        raise ValueError(problem)
    assert draft.report_date is not None
    expected = payload.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("Bản xác nhận không hợp lệ. Hãy gửi lại ảnh.")
    scope_lock(session, user_id, chat_id)
    current = existing_rows(session, user_id, chat_id, draft.report_date)
    for row in draft.rows:
        key = person_key(row.name)
        old = current.get(key)
        if key not in expected or expected[key] != (old.revision if old else None):
            raise ValueError("Số liệu đã thay đổi. Gửi /xacnhan để xem lại số cũ và số mới.")
    try:
        with session.begin_nested():
            for row in draft.rows:
                assert row.count is not None
                key = person_key(row.name)
                old = current.get(key)
                if old:
                    old.count = row.count
                    old.person_name = row.name
                    old.source = draft.source
                    old.revision += 1
                else:
                    session.add(PersonReport(
                        telegram_user_id=user_id, chat_id=chat_id,
                        report_date=draft.report_date, person_key=key, person_name=row.name,
                        count=row.count, source=draft.source,
                    ))
            session.flush()
    except IntegrityError as exc:
        raise ValueError("Số liệu vừa thay đổi. Gửi /xacnhan để xem lại trước khi lưu.") from exc
    total = sum(row.count or 0 for row in draft.rows)
    return (
        f"Đã lưu số đơn ngày {draft.report_date:%d/%m/%Y}: "
        f"{len(draft.rows)} người, tổng {total} đơn."
    )


def report_summary(
    session: Session, user_id: int, chat_id: int, start: date, end: date,
) -> str:
    rows = session.execute(select(
        PersonReport.person_key,
        func.min(PersonReport.person_name),
        func.sum(PersonReport.count),
        func.count(PersonReport.id),
        func.min(PersonReport.report_date),
        func.max(PersonReport.report_date),
    ).where(
        PersonReport.telegram_user_id == user_id,
        PersonReport.chat_id == chat_id,
        PersonReport.report_date >= start,
        PersonReport.report_date < end,
    ).group_by(PersonReport.person_key).order_by(
        func.sum(PersonReport.count).desc(), PersonReport.person_key,
    )).all()
    if not rows:
        return "Chưa có báo cáo số đơn theo người trong khoảng này."
    lines = [f"Số đơn {start:%d/%m/%Y} – {end - timedelta(days=1):%d/%m/%Y}:"]
    previous = None
    rank = 0
    for index, (_, name, total, days, first, last) in enumerate(rows, 1):
        if total != previous:
            rank = index
        previous = total
        lines.append(
            f"{rank}. {name}: {total} đơn ({days} ngày có dữ liệu, "
            f"{first:%d/%m}–{last:%d/%m})"
        )
    lines.append(f"Tổng: {sum(row[2] for row in rows)} đơn.")
    lines.append("Chỉ tính ngày đã nhập; ngày chưa nhập không được coi là 0.")
    return "\n".join(lines)
