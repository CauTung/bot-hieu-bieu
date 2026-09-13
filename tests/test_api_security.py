from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.index import app
from core.config import get_settings

client = TestClient(app)

def test_webhook_rejects_missing_secret() -> None:
    original_settings = get_settings()
    # Create an object matching expected settings
    settings = SimpleNamespace(**{k: getattr(original_settings, k) for k in original_settings.model_dump().keys()})
    settings.telegram_webhook_secret = "expected-secret-123"
    
    with patch("api.index.get_settings", return_value=settings):
        response = client.post("/api/webhook", headers={}, json={})
        assert response.status_code == 401
        assert response.json() == {"ok": False, "error": "Unauthorized"}


def test_reminder_endpoint_rejects_missing_secret() -> None:
    original_settings = get_settings()
    settings = SimpleNamespace(**{k: getattr(original_settings, k) for k in original_settings.model_dump().keys()})
    settings.reminder_cron_secret = "expected-secret-123"
    
    with patch("api.index.get_settings", return_value=settings):
        response = client.post("/api/check-reminders", headers={})
        assert response.status_code == 401
        assert response.json() == {"ok": False, "error": "Unauthorized"}
