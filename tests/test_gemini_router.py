import json
from datetime import datetime, timezone

import pytest

from core.gemini_router import GeminiIntentRouter, RouterError


class FakeGenerateContentResponse:
    def __init__(self, text: str):
        self.text = text


class FakeModels:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.captured_kwargs = {}

    def generate_content(self, **kwargs):
        self.captured_kwargs = kwargs
        if self.response_text == "not json":
            return FakeGenerateContentResponse("not json")
        return FakeGenerateContentResponse(self.response_text)


class FakeClient:
    def __init__(self, response_text: str):
        self.models = FakeModels(response_text)


def decision_json() -> str:
    return json.dumps(
        {
            "intent": "create_sku",
            "params": {
                "sku": "VAY01",
                "new_sku": None,
                "order_id": None,
                "name": "Váy xếp ly",
                "tags": None,
                "notes": None,
                "quantity": None,
                "order_date": None,
                "source": None,
                "period": None,
                "content": None,
                "remind_at": None,
                "reminder_id": None,
                "question": None,
            },
            "confidence": 0.98,
            "clarification_question": None,
            "answer": None,
        }
    )


def test_router_uses_responses_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeClient(decision_json())
    
    # We patch the client creation in GeminiIntentRouter
    monkeypatch.setattr("core.gemini_router.genai.Client", lambda **kwargs: fake_client)
    
    decision = GeminiIntentRouter("test-key", "configured-model").classify(
        "Lưu mã VAY01 cho Váy xếp ly",
        now=datetime(2026, 9, 13, tzinfo=timezone.utc),
        timezone_name="Asia/Ho_Chi_Minh",
        telegram_user_id=123,
    )
    assert decision.intent.value == "create_sku"
    assert fake_client.models.captured_kwargs["model"] == "configured-model"
    assert fake_client.models.captured_kwargs["config"].response_mime_type == "application/json"
    assert fake_client.models.captured_kwargs["config"].temperature == 0.0


def test_router_includes_pending_conversation_context(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeClient(decision_json())
    monkeypatch.setattr("core.gemini_router.genai.Client", lambda **kwargs: fake_client)

    GeminiIntentRouter("test-key", "configured-model").classify(
        "vào lúc 16h ngày 19/9/2026",
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
        timezone_name="Asia/Ho_Chi_Minh",
        telegram_user_id=123,
        conversation_context={
            "intent": "create_reminder",
            "params": {"content": "Lịch đi nhậu", "remind_at": None},
            "clarification_question": "Bạn muốn đặt vào thời gian nào?",
        },
    )

    contents = fake_client.models.captured_kwargs["contents"]
    assert "TRẠNG THÁI HỘI THOẠI" in contents
    assert "Lịch đi nhậu" in contents
    assert "vào lúc 16h ngày 19/9/2026" in contents


def test_router_falls_back_to_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class FallbackModels:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs["model"])
            if kwargs["model"] == "primary-model":
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return FakeGenerateContentResponse(decision_json())

    fake_client = FakeClient(decision_json())
    fake_client.models = FallbackModels()
    monkeypatch.setattr("core.gemini_router.genai.Client", lambda **kwargs: fake_client)

    decision = GeminiIntentRouter(
        "test-key",
        "primary-model",
        fallback_models=("fallback-model",),
    ).classify(
        "Lưu mã VAY01 cho Váy xếp ly",
        now=datetime(2026, 9, 13, tzinfo=timezone.utc),
        timezone_name="Asia/Ho_Chi_Minh",
        telegram_user_id=123,
    )

    assert decision.intent.value == "create_sku"
    assert fake_client.models.calls == ["primary-model", "fallback-model"]


def test_router_rejects_missing_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeClient("not json")
    monkeypatch.setattr("core.gemini_router.genai.Client", lambda **kwargs: fake_client)
    
    with pytest.raises(RouterError, match="invalid structured response"):
        GeminiIntentRouter("test-key", "configured-model").classify(
            "hello",
            now=datetime.now(timezone.utc),
            timezone_name="Asia/Ho_Chi_Minh",
            telegram_user_id=123,
        )
