from core.config import Settings


def base_environment() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql+psycopg://user:pass@example.test/db",
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_WEBHOOK_SECRET": "a-secure-webhook-secret",
        "TELEGRAM_ALLOWED_USER_IDS": "123, 456",
        "REMINDER_CRON_SECRET": "a-secure-reminder-secret",
        "OPENAI_API_KEY": "key",
        "OPENAI_ROUTER_MODEL": "router-model",
        "OPENAI_QA_MODEL": "qa-model",
    }


def test_settings_parse_allowed_user_ids() -> None:
    settings = Settings(**base_environment())  # type: ignore[arg-type]
    assert settings.telegram_allowed_user_ids == frozenset({123, 456})
    assert settings.app_timezone == "Asia/Ho_Chi_Minh"


def test_settings_parse_single_user_id_from_environment(monkeypatch: object) -> None:
    import os

    environment = base_environment()
    environment["TELEGRAM_ALLOWED_USER_IDS"] = "123"
    for key, value in environment.items():
        os.environ[key] = value
    try:
        settings = Settings()  # type: ignore[call-arg]
        assert settings.telegram_allowed_user_ids == frozenset({123})
    finally:
        for key in environment:
            os.environ.pop(key, None)
