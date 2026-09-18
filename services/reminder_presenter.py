from datetime import datetime
from zoneinfo import ZoneInfo

from models.reminder import Reminder

WEEKDAYS = (
    "Thứ Hai",
    "Thứ Ba",
    "Thứ Tư",
    "Thứ Năm",
    "Thứ Sáu",
    "Thứ Bảy",
    "Chủ Nhật",
)


def format_datetime(value: datetime, timezone_name: str) -> str:
    local = value.astimezone(ZoneInfo(timezone_name))
    return f"{local:%H:%M} • {WEEKDAYS[local.weekday()]}, {local:%d/%m/%Y}"


def format_confirmation(
    *, content: str, remind_at: datetime, event_at: datetime | None, recurrence: str | None = None, timezone_name: str
) -> str:
    if event_at is None:
        text = (
            "⏰ XÁC NHẬN NHẮC VIỆC\n\n"
            f"📝 {content}\n"
            f"🔔 {format_datetime(remind_at, timezone_name)}"
        )
        if recurrence:
            text += f"\n🔁 Lặp lại: {recurrence}"
        text += "\n\nĐúng thời gian này chứ?"
        return text
    lead_minutes = max(0, int((event_at - remind_at).total_seconds() // 60))
    if lead_minutes and lead_minutes % 60 == 0:
        lead_text = f"trước {lead_minutes // 60} giờ"
    elif lead_minutes:
        lead_text = f"trước {lead_minutes} phút"
    else:
        lead_text = "khi sự kiện bắt đầu"
    text = (
        "⏰ XÁC NHẬN LỊCH HẸN\n\n"
        f"📅 {content}\n"
        f"📌 Sự kiện: {format_datetime(event_at, timezone_name)}\n"
        f"🔔 Nhắc: {format_datetime(remind_at, timezone_name)} ({lead_text})"
    )
    if recurrence:
        text += f"\n🔁 Lặp lại: {recurrence}"
    text += "\n\nĐúng lịch này chứ?"
    return text


def format_created(reminder: Reminder, timezone_name: str) -> str:
    if reminder.event_at is None:
        text = (
            "✅ ĐÃ ĐẶT NHẮC\n\n"
            f"📝 {reminder.content}\n"
            f"🔔 {format_datetime(reminder.remind_at, timezone_name)}"
        )
        if reminder.recurrence:
            text += f"\n🔁 Lặp lại: {reminder.recurrence}"
        return text
    
    text = (
        "✅ ĐÃ LƯU LỊCH HẸN\n\n"
        f"📅 {reminder.content}\n"
        f"📌 Sự kiện: {format_datetime(reminder.event_at, timezone_name)}\n"
        f"🔔 Nhắc: {format_datetime(reminder.remind_at, timezone_name)}"
    )
    if reminder.recurrence:
        text += f"\n🔁 Lặp lại: {reminder.recurrence}"
    return text


def format_list(reminders: list[Reminder], timezone_name: str) -> str:
    blocks = [f"📋 LỊCH SẮP TỚI ({len(reminders)})"]
    for index, reminder in enumerate(reminders, start=1):
        lines = [f"{index}. {reminder.content}"]
        if reminder.event_at is not None:
            lines.append(f"   📌 {format_datetime(reminder.event_at, timezone_name)}")
        lines.append(f"   🔔 Nhắc: {format_datetime(reminder.remind_at, timezone_name)}")
        if reminder.recurrence:
            lines.append(f"   🔁 Lặp lại: {reminder.recurrence}")
        lines.append(f"   Mã hủy: {reminder.id}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_notification(reminder: Reminder, timezone_name: str) -> str:
    text = f"⏰ ĐẾN GIỜ NHẮC\n\n✨ {reminder.content}"
    if reminder.event_at is not None:
        text += f"\n📅 Sự kiện: {format_datetime(reminder.event_at, timezone_name)}"
    return text
