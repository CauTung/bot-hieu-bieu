from core.config import Settings


def base_environment() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql+psycopg://user:pass@example.test/db",
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_WEBHOOK_SECRET": "a-secure-webhook-secret",
        "TELEGRAM_ALLOWED_USER_IDS": "123, 456",
        "REMINDER_CRON_SECRET": "a-secure-reminder-secret",
        "GEMINI_API_KEY": "key",
        "GEMINI_ROUTER_MODEL": "router-model",
        "GEMINI_QA_MODEL": "qa-model",
    }


def test_settings_parse_allowed_user_ids() -> None:
    settings = Settings(**base_environment())  # type: ignore[arg-type]
    assert settings.telegram_allowed_user_ids == frozenset({123, 456})
    assert settings.telegram_enforce_allowlist is False
    assert settings.app_timezone == "Asia/Ho_Chi_Minh"
    assert settings.gemini_fallback_models == (
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
    )


def test_settings_parse_fallback_models() -> None:
    environment = base_environment()
    environment["GEMINI_FALLBACK_MODELS"] = "model-a, model-b,model-a"
    settings = Settings(**environment)  # type: ignore[arg-type]
    assert settings.gemini_fallback_models == ("model-a", "model-b", "model-a")


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


def test_allowlist_can_be_empty_while_disabled() -> None:
    environment = base_environment()
    environment["TELEGRAM_ALLOWED_USER_IDS"] = ""
    settings = Settings(**environment)  # type: ignore[arg-type]
    assert settings.telegram_allowed_user_ids == frozenset()
    assert settings.telegram_enforce_allowlist is False


def test_supabase_postgres_url_uses_psycopg_driver() -> None:
    environment = base_environment()
    environment["DATABASE_URL"] = "postgresql://user:pass@pooler.supabase.test/db"
    settings = Settings(**environment)  # type: ignore[arg-type]
    assert settings.database_url.startswith("postgresql+psycopg://")
