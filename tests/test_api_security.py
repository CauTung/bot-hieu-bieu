from types import SimpleNamespace
from unittest.mock import MagicMock

import api.check_reminders as reminder_api
import api.webhook as webhook_api


def test_webhook_rejects_missing_secret(monkeypatch: object) -> None:
    settings = SimpleNamespace(telegram_webhook_secret="expected-secret-123")
    original = webhook_api.get_settings
    webhook_api.get_settings = lambda: settings  # type: ignore[assignment]
    try:
        instance = webhook_api.handler.__new__(webhook_api.handler)
        instance.headers = {}  # type: ignore[assignment]
        instance._json_response = MagicMock()  # type: ignore[method-assign]
        instance.do_POST()
        instance._json_response.assert_called_once_with(  # type: ignore[attr-defined]
            401, {"ok": False, "error": "Unauthorized"}
        )
    finally:
        webhook_api.get_settings = original


def test_reminder_endpoint_rejects_missing_secret(monkeypatch: object) -> None:
    settings = SimpleNamespace(reminder_cron_secret="expected-secret-123")
    original = reminder_api.get_settings
    reminder_api.get_settings = lambda: settings  # type: ignore[assignment]
    try:
        instance = reminder_api.handler.__new__(reminder_api.handler)
        instance.headers = {}  # type: ignore[assignment]
        instance._json_response = MagicMock()  # type: ignore[method-assign]
        instance._run()
        instance._json_response.assert_called_once_with(  # type: ignore[attr-defined]
            401, {"ok": False, "error": "Unauthorized"}
        )
    finally:
        reminder_api.get_settings = original
