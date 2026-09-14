from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from core.intent_schema import Intent, IntentDecision
from services.bot_service import BotService
from services.update_processor import UpdateContext
from tests.test_bot_service import FakeRouter, FakeTelegram, params


def test_past_reminder_is_not_sent_to_confirmation() -> None:
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    decision = IntentDecision(
        intent=Intent.CREATE_REMINDER,
        params=params(content="Gửi mẫu", remind_at=past),
        confidence=0.99,
        clarification_question=None,
    )
    telegram = FakeTelegram()
    service = BotService(
        session=MagicMock(),
        telegram=telegram,
        router=FakeRouter(decision),
        timezone_name="Asia/Ho_Chi_Minh",
        confidence_threshold=0.8,
        action_ttl_minutes=15,
        max_message_length=4000,
    )
    service.process(UpdateContext(1, 123, 456, "nhắc tôi", None, None, 10))
    assert "đã qua" in telegram.messages[0][1]
    assert "reply_markup" not in telegram.messages[0][2]
