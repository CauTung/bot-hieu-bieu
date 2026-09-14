import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import services.bot_service as bot_module
from core.intent_schema import Intent, IntentDecision, IntentParams
from services.bot_service import BotService
from services.update_processor import UpdateContext


def params(**overrides: object) -> IntentParams:
    values: dict[str, object] = {
        "sku": None,
        "new_sku": None,
        "order_id": None,
        "name": None,
        "tags": None,
        "notes": None,
        "quantity": None,
        "order_date": None,
        "source": None,
        "period": None,
        "content": None,
        "remind_at": None,
        "event_at": None,
        "reminder_id": None,
        "question": None,
    }
    values.update(overrides)
    return IntentParams.model_validate(values)


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict[str, Any]]] = []
        self.answers: list[tuple[str, str | None]] = []
        self.edits: list[tuple[int, int]] = []
        self.actions: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str, **extra: Any) -> dict[str, Any]:
        self.messages.append((chat_id, text, extra))
        return {}

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self.actions.append((chat_id, action))

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.answers.append((callback_query_id, text))

    def edit_message_reply_markup(self, chat_id: int, message_id: int) -> None:
        self.edits.append((chat_id, message_id))


class FakeRouter:
    def __init__(self, decision: IntentDecision) -> None:
        self.decision = decision
        self.calls: list[dict[str, Any]] = []

    def classify(self, *args: Any, **kwargs: Any) -> IntentDecision:
        self.calls.append(kwargs)
        return self.decision


def make_service(decision: IntentDecision) -> tuple[BotService, FakeTelegram]:
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
    return service, telegram


def message_context(text: str) -> UpdateContext:
    return UpdateContext(1, 123, 456, text, None, None, 10)


def test_low_confidence_asks_for_clarification() -> None:
    decision = IntentDecision(
        intent=Intent.UNKNOWN,
        params=params(),
        confidence=0.2,
        clarification_question="Bạn muốn làm gì?",
    )
    service, telegram = make_service(decision)
    service.process(message_context("không rõ"))
    assert telegram.messages[0][1] == "Bạn muốn làm gì?"


def test_write_intent_creates_confirmation_keyboard(monkeypatch: pytest.MonkeyPatch) -> None:
    action_id = uuid.uuid4()
    monkeypatch.setattr(
        bot_module,
        "create_pending_action",
        lambda *args, **kwargs: SimpleNamespace(id=action_id),
    )
    decision = IntentDecision(
        intent=Intent.CREATE_SKU,
        params=params(sku="VAY01", name="Váy xếp ly"),
        confidence=0.99,
        clarification_question=None,
    )
    service, telegram = make_service(decision)
    service.process(message_context("tạo sku"))
    markup = telegram.messages[0][2]["reply_markup"]
    assert markup["inline_keyboard"][0][0]["callback_data"] == f"confirm:{action_id}"
    assert markup["inline_keyboard"][0][1]["callback_data"] == f"cancel:{action_id}"


def test_confirm_callback_executes_action_once(monkeypatch: pytest.MonkeyPatch) -> None:
    action_id = uuid.uuid4()
    action = SimpleNamespace(action_type="create_sku", payload={"sku": "VAY01"})
    monkeypatch.setattr(bot_module, "consume_pending_action", lambda *args, **kwargs: action)
    decision = IntentDecision(
        intent=Intent.UNKNOWN,
        params=params(),
        confidence=1,
        clarification_question=None,
    )
    service, telegram = make_service(decision)
    monkeypatch.setattr(service, "_execute_action", lambda *args: "Đã lưu.")
    service.process(UpdateContext(2, 123, 456, None, "cb-1", f"confirm:{action_id}", 99))
    assert telegram.edits == [(456, 99)]
    assert telegram.answers == [("cb-1", "Đã xác nhận.")]
    assert telegram.messages[0][1] == "Đã lưu."


def test_invalid_callback_is_answered() -> None:
    decision = IntentDecision(
        intent=Intent.UNKNOWN,
        params=params(),
        confidence=1,
        clarification_question=None,
    )
    service, telegram = make_service(decision)
    service.process(UpdateContext(2, 123, 456, None, "cb-1", "bad", 99))
    assert telegram.answers == [("cb-1", "Callback không hợp lệ.")]


def test_qa_uses_separate_client() -> None:
    decision = IntentDecision(
        intent=Intent.QA,
        params=params(question="Kích thước ảnh Facebook?"),
        confidence=0.95,
        clarification_question=None,
        answer="Kích thước phù hợp là 1200 x 630 px.",
    )
    service, telegram = make_service(decision)
    service.process(message_context("Kích thước ảnh Facebook?"))
    assert telegram.messages[0][1] == "Kích thước phù hợp là 1200 x 630 px."
    assert telegram.actions == [(456, "typing")]


def test_fast_command_skips_gemini() -> None:
    decision = IntentDecision(
        intent=Intent.UNKNOWN,
        params=params(),
        confidence=1,
        clarification_question=None,
    )
    service, telegram = make_service(decision)
    service.router.classify = MagicMock()

    service.process(message_context("/reminders"))

    service.router.classify.assert_not_called()
    assert telegram.actions == [(456, "typing")]


def test_help_command_skips_gemini_and_typing() -> None:
    decision = IntentDecision(
        intent=Intent.UNKNOWN,
        params=params(),
        confidence=1,
        clarification_question=None,
    )
    service, telegram = make_service(decision)
    service.router.classify = MagicMock()

    service.process(message_context("/help"))

    service.router.classify.assert_not_called()
    assert telegram.actions == []
    assert "/sku" in telegram.messages[0][1]


def test_router_failure_returns_friendly_message() -> None:
    decision = IntentDecision(
        intent=Intent.UNKNOWN,
        params=params(),
        confidence=1,
        clarification_question=None,
    )
    service, telegram = make_service(decision)
    service.router.classify = MagicMock(side_effect=bot_module.RouterError("quota exceeded"))

    service.process(message_context("Xin chào"))

    assert telegram.actions == [(456, "typing")]
    assert "sự cố với dịch vụ AI" in telegram.messages[0][1]


def test_message_length_is_bounded() -> None:
    decision = IntentDecision(
        intent=Intent.UNKNOWN,
        params=params(),
        confidence=1,
        clarification_question=None,
    )
    service, telegram = make_service(decision)
    service.max_message_length = 3
    service.process(message_context("1234"))
    assert "quá dài" in telegram.messages[0][1]


def test_clarification_is_saved_for_the_next_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = IntentDecision(
        intent=Intent.CREATE_REMINDER,
        params=params(content="Lịch đi nhậu"),
        confidence=0.95,
        clarification_question="Bạn muốn đặt vào thời gian nào?",
    )
    service, telegram = make_service(decision)
    save = MagicMock()
    monkeypatch.setattr(bot_module, "save_conversation_state", save)

    service.process(message_context("Lịch đi nhậu"))

    save.assert_called_once()
    assert save.call_args.kwargs["decision"] is decision
    assert telegram.messages[0][1] == "Bạn muốn đặt vào thời gian nào?"


def test_followup_includes_saved_context(monkeypatch: pytest.MonkeyPatch) -> None:
    future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    decision = IntentDecision(
        intent=Intent.CREATE_REMINDER,
        params=params(content="Lịch đi nhậu", remind_at=future),
        confidence=0.99,
        clarification_question=None,
    )
    service, _ = make_service(decision)
    saved = SimpleNamespace(
        intent="create_reminder",
        params=params(content="Lịch đi nhậu").model_dump(mode="json"),
        clarification_question="Bạn muốn đặt vào thời gian nào?",
    )
    monkeypatch.setattr(bot_module, "get_conversation_state", lambda *args, **kwargs: saved)
    monkeypatch.setattr(
        bot_module,
        "create_pending_action",
        lambda *args, **kwargs: SimpleNamespace(id=uuid.uuid4()),
    )

    service.process(message_context("vào lúc 16h ngày 19/9/2026"))

    router = service.router
    assert isinstance(router, FakeRouter)
    context = router.calls[0]["conversation_context"]
    pending = context["pending_request"]
    assert pending["intent"] == "create_reminder"
    assert pending["params"]["content"] == "Lịch đi nhậu"
