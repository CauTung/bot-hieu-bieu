from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field(min_length=16, alias="TELEGRAM_WEBHOOK_SECRET")
    telegram_allowed_user_ids: Annotated[frozenset[int], NoDecode] = Field(
        alias="TELEGRAM_ALLOWED_USER_IDS"
    )
    reminder_cron_secret: str = Field(min_length=16, alias="REMINDER_CRON_SECRET")
    gemini_api_key: str = Field(alias="GEMINI_API_KEY")
    gemini_router_model: str = Field(alias="GEMINI_ROUTER_MODEL")
    gemini_qa_model: str = Field(alias="GEMINI_QA_MODEL")
    app_timezone: str = Field(default="Asia/Ho_Chi_Minh", alias="APP_TIMEZONE")
    pending_action_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    reminder_max_attempts: int = Field(default=5, ge=1, le=20)
    reminder_lock_timeout_seconds: int = Field(default=120, ge=30, le=3600)
    intent_confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    max_message_length: int = Field(default=4000, ge=100, le=20_000)
    reminder_batch_size: int = Field(default=20, ge=1, le=100)

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, value: object) -> object:
        if isinstance(value, str):
            values = [part.strip() for part in value.split(",") if part.strip()]
            if not values:
                raise ValueError("TELEGRAM_ALLOWED_USER_IDS must not be empty")
            return frozenset(int(part) for part in values)
        return value

    @field_validator("database_url")
    @classmethod
    def normalize_database_driver(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
