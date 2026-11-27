from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    demo_mode: bool = True
    database_url: str = "sqlite:///./data/insurance.db"
    business_timezone: str = "America/Chicago"
    llm_provider: Literal["mock", "openai", "gemini"] = "mock"
    llm_api_key: SecretStr = SecretStr("")
    demo_diagnostics_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_temperature: float = Field(0.2, ge=0, le=2)
    llm_max_tokens: int = Field(1200, ge=32, le=8192)
    llm_timeout_seconds: float = Field(30, gt=0, le=120)
    llm_max_retries: int = Field(2, ge=0, le=4)
    llm_extraction_temperature: float = Field(0, ge=0, le=2)
    llm_response_temperature: float = Field(0.3, ge=0, le=2)
    max_reasoning_iterations: int = Field(2, ge=1, le=4)
    max_tool_calls_per_turn: int = Field(3, ge=1, le=12)
    max_conversation_history_messages: int = Field(12, ge=0, le=50)
    max_input_length: int = Field(4000, ge=1, le=16000)
    min_verification_fields: int = Field(3, ge=3, le=5)
    max_verification_attempts: int = Field(3, ge=1)
    max_verification_refusals: int = Field(2, ge=1)
    max_out_of_scope_attempts: int = Field(2, ge=1)
    max_recovery_attempts: int = Field(3, ge=1)
    max_dependency_failures: int = Field(3, ge=1)
    verification_window_seconds: int = Field(900, ge=60)
    verification_window_attempts: int = Field(12, ge=1)
    consent_max_polls: int = Field(5, ge=1)
    session_ttl_minutes: int = Field(30, ge=1)
    email_mode: Literal["mock", "disabled"] = "mock"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    redact_pii: bool = True

    @field_validator("redact_pii")
    @classmethod
    def require_redaction(cls, value: bool) -> bool:
        if not value:
            raise ValueError("PII redaction cannot be disabled")
        return value

    @field_validator("database_url")
    @classmethod
    def sqlite_only(cls, value: str) -> str:
        prefix = "sqlite:///"
        if not value.startswith(prefix) or not value[len(prefix):].strip():
            raise ValueError("expected sqlite:/// followed by a database path")
        return value

    @field_validator("business_timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("expected an IANA business timezone") from error
        return value

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.removeprefix("sqlite:///"))
