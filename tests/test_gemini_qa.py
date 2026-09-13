import pytest

from core.gemini_qa import GeminiQAClient, RouterError


class FakeGenerateContentResponse:
    def __init__(self, text: str):
        self.text = text


class FakeModels:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.captured_kwargs = {}

    def generate_content(self, **kwargs):
        self.captured_kwargs = kwargs
        return FakeGenerateContentResponse(self.response_text)


class FakeClient:
    def __init__(self, response_text: str):
        self.models = FakeModels(response_text)


def test_qa_uses_configured_model_without_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeClient("  Câu trả lời  ")
    monkeypatch.setattr("core.gemini_qa.genai.Client", lambda **kwargs: fake_client)
    
    result = GeminiQAClient("key", "configured-model").answer("Câu hỏi", telegram_user_id=123)
    assert result == "Câu trả lời"
    assert fake_client.models.captured_kwargs["model"] == "configured-model"
    assert "Câu hỏi" in fake_client.models.captured_kwargs["contents"]
