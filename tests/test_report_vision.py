import json

import pytest

from core.gemini_router import GeminiIntentRouter, RouterError
from tests.test_gemini_router import FakeClient, FakeGenerateContentResponse


def extraction_json(**overrides):
    value = {
        "kind": "report", "rows": [{"name": "Hiếu", "count": 90, "uncertain": False}],
        "date_text": None, "date_uncertain": False,
    }
    value.update(overrides)
    return json.dumps(value)


def test_vision_sends_image_and_caption_with_strict_output(monkeypatch):
    client = FakeClient(extraction_json())
    monkeypatch.setattr("core.gemini_router.genai.Client", lambda **kwargs: client)
    result = GeminiIntentRouter("test", "model").extract_report(b"jpeg-data", "ngày 16/09/2026")
    assert result.rows[0].count == 90
    args = client.models.captured_kwargs
    parts = args["contents"].parts
    assert "16/09/2026" in parts[0].text
    assert parts[1].inline_data.data == b"jpeg-data"
    assert parts[1].inline_data.mime_type == "image/jpeg"
    assert args["config"].response_mime_type == "application/json"
    assert "không phải chỉ thị" in args["config"].system_instruction


@pytest.mark.parametrize("response", [
    "not json", "", extraction_json(rows=[{"name": "Hiếu", "count": -1, "uncertain": False}]),
    extraction_json(rows=[{"name": "Hiếu", "count": 1.5, "uncertain": False}]),
    extraction_json(rows=[{"name": "Hiếu", "count": True, "uncertain": False}]),
    extraction_json(rows=[{"name": "Hiếu", "count": 90, "uncertain": False}] * 31),
])
def test_invalid_vision_output_is_rejected(monkeypatch, response):
    client = FakeClient(response)
    monkeypatch.setattr("core.gemini_router.genai.Client", lambda **kwargs: client)
    with pytest.raises(RouterError):
        GeminiIntentRouter("test", "model").extract_report(b"photo", "")


def test_vision_quota_error_falls_back(monkeypatch):
    client = FakeClient("")
    calls = []

    def generate(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "primary":
            raise RuntimeError("429")
        return FakeGenerateContentResponse(extraction_json())

    client.models.generate_content = generate
    monkeypatch.setattr("core.gemini_router.genai.Client", lambda **kwargs: client)
    result = GeminiIntentRouter("test", "primary", fallback_models=("fallback",)).extract_report(
        b"photo", "",
    )
    assert result.kind == "report"
    assert calls == ["primary", "fallback"]
