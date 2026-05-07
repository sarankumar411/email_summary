from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Email Context System"
    environment: str = "local"
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "dev-only-secret"
    access_token_expire_minutes: int = 60

    encryption_keys_json: dict[int, str] = Field(default_factory=dict)
    active_encryption_key_version: int = 1

    database_write_url: str = "postgresql+asyncpg://email_context:email_context@localhost:5432/email_context"
    database_read_url: str | None = None
    redis_url: str = "redis://:email_context@localhost:6379/0"
    celery_broker_url: str = "redis://:email_context@localhost:6379/1"
    celery_result_backend: str = "redis://:email_context@localhost:6379/2"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"
    use_mock_gemini: bool = True
    gemini_timeout_seconds: float = 30.0
    summary_chunk_threshold: int = 50

    cors_allow_origins: list[str] = Field(default_factory=list)
    login_rate_limit: str = "5/minute"
    cache_summary_ttl_seconds: int = 3600
    cache_report_ttl_seconds: int = 60
    job_ttl_hours: int = 24
    celery_task_always_eager: bool = False

    @field_validator("encryption_keys_json", mode="before")
    @classmethod
    def coerce_encryption_keys(cls, value: Any) -> dict[int, str]:
        if value in (None, ""):
            return {}
        if isinstance(value, dict):
            return {int(k): str(v) for k, v in value.items()}
        return value

    @property
    def database_read_effective_url(self) -> str:
        return self.database_read_url or self.database_write_url


SettingsDep = Annotated[Settings, Field()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

