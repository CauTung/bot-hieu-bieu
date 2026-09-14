from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import services.bot_service as bot_module
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
    session = MagicMock()
    session.get.return_value = None
    service = BotService(
        session=session,
        telegram=telegram,
        router=FakeRouter(decision),
        timezone_name="Asia/Ho_Chi_Minh",
        confidence_threshold=0.8,
        action_ttl_minutes=15,
        conversation_ttl_minutes=30,
        history_retention_days=30,
        history_max_exchanges=8,
        max_message_length=4000,
    )
    service.process(UpdateContext(1, 123, 456, "nhắc tôi", None, None, 10))
    assert "đã qua" in telegram.messages[0][1]
    assert "reply_markup" not in telegram.messages[0][2]


def test_event_time_defaults_to_reminder_two_hours_early(
    monkeypatch,
) -> None:
    event_at = datetime.now(timezone.utc) + timedelta(days=1)
    decision = IntentDecision(
        intent=Intent.CREATE_REMINDER,
        params=params(content="Đi nhậu", event_at=event_at.isoformat()),
        confidence=0.99,
        clarification_question=None,
    )
    telegram = FakeTelegram()
    session = MagicMock()
    session.get.return_value = None
    create_action = MagicMock(return_value=SimpleNamespace(id="action-id"))
    monkeypatch.setattr(bot_module, "create_pending_action", create_action)
    service = BotService(
        session=session,
        telegram=telegram,
        router=FakeRouter(decision),
        timezone_name="Asia/Ho_Chi_Minh",
        confidence_threshold=0.8,
        action_ttl_minutes=15,
        conversation_ttl_minutes=30,
        history_retention_days=30,
        history_max_exchanges=8,
        max_message_length=4000,
    )

    service.process(UpdateContext(2, 123, 456, "18h mai đi nhậu", None, None, 10))

    payload = create_action.call_args.kwargs["payload"]
    remind_at = datetime.fromisoformat(payload["remind_at"])
    assert remind_at == event_at - timedelta(hours=2)
    assert payload["event_at"] == event_at.isoformat()
    assert "XÁC NHẬN LỊCH HẸN" in telegram.messages[0][1]
    assert "trước 2 giờ" in telegram.messages[0][1]


def test_explicit_relative_reminder_is_not_shifted(monkeypatch) -> None:
    remind_at = datetime.now(timezone.utc) + timedelta(hours=2)
    decision = IntentDecision(
        intent=Intent.CREATE_REMINDER,
        params=params(content="Gọi khách", remind_at=remind_at.isoformat()),
        confidence=0.99,
        clarification_question=None,
    )
    telegram = FakeTelegram()
    session = MagicMock()
    session.get.return_value = None
    create_action = MagicMock(return_value=SimpleNamespace(id="action-id"))
    monkeypatch.setattr(bot_module, "create_pending_action", create_action)
    service = BotService(
        session=session,
        telegram=telegram,
        router=FakeRouter(decision),
        timezone_name="Asia/Ho_Chi_Minh",
        confidence_threshold=0.8,
        action_ttl_minutes=15,
        conversation_ttl_minutes=30,
        history_retention_days=30,
        history_max_exchanges=8,
        max_message_length=4000,
    )

    service.process(UpdateContext(3, 123, 456, "2 tiếng nữa nhắc tôi gọi khách", None, None, 10))

    payload = create_action.call_args.kwargs["payload"]
    assert payload["remind_at"] == remind_at.isoformat()
    assert payload["event_at"] is None


def test_common_dated_event_is_parsed_without_ai() -> None:
    decision = IntentDecision(
        intent=Intent.UNKNOWN,
        params=params(),
        confidence=1,
        clarification_question=None,
    )
    telegram = FakeTelegram()
    session = MagicMock()
    session.get.return_value = None
    service = BotService(
        session=session,
        telegram=telegram,
        router=FakeRouter(decision),
        timezone_name="Asia/Ho_Chi_Minh",
        confidence_threshold=0.8,
        action_ttl_minutes=15,
        conversation_ttl_minutes=30,
        history_retention_days=30,
        history_max_exchanges=8,
        max_message_length=4000,
    )
    service.router.classify = MagicMock()

    parsed = service._classify_locally("Hẹn 18h ngày 17/9/2027 đi nhậu")

    service.router.classify.assert_not_called()
    assert parsed is not None
    assert parsed.intent == Intent.CREATE_REMINDER
    assert parsed.params.content == "đi nhậu"
    assert parsed.params.event_at == "2027-09-17T18:00:00+07:00"
    assert parsed.params.remind_at is None
