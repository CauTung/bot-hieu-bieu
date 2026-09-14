import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from models.reminder import Reminder
from services.reminder_presenter import format_created, format_list, format_notification


def reminder() -> Reminder:
    zone = ZoneInfo("Asia/Ho_Chi_Minh")
    return Reminder(
        id=uuid.UUID("0658599e-a346-4a7a-9490-659cc05785cd"),
        telegram_user_id=1,
        chat_id=2,
        content="Lịch nhậu",
        remind_at=datetime(2026, 9, 17, 16, tzinfo=zone),
        event_at=datetime(2026, 9, 17, 18, tzinfo=zone),
        status="pending",
    )


def test_created_message_is_human_readable() -> None:
    text = format_created(reminder(), "Asia/Ho_Chi_Minh")
    assert "✅ ĐÃ LƯU LỊCH HẸN" in text
    assert "18:00 • Thứ Năm, 17/09/2026" in text
    assert "T18:00:00" not in text


def test_list_keeps_technical_id_secondary() -> None:
    text = format_list([reminder()], "Asia/Ho_Chi_Minh")
    assert text.startswith("📌 LỊCH SẮP TỚI (1)\n\n1. Lịch nhậu")
    assert "Mã hủy: 0658599e-a346-4a7a-9490-659cc05785cd" in text


def test_notification_focuses_on_action() -> None:
    text = format_notification(reminder(), "Asia/Ho_Chi_Minh")
    assert text.startswith("⏰ ĐẾN GIỜ NHẮC\n\n✨ Lịch nhậu")
