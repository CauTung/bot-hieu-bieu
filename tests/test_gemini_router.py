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
