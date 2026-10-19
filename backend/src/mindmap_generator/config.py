"""Application configuration loaded from environment variables / ``.env``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings.

    All values can be supplied through environment variables using the uppercase
    field name (for example ``LLM_MODEL`` or ``MAX_UPLOAD_MB``) or through a
    ``.env`` file in the backend working directory.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        case_sensitive=False,
    )

    app_name: str = "Mind Map Generator"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Upload / document limits
    max_upload_mb: int = 25
    max_pages: int = 500
    min_extractable_chars: int = 40

    # Mind map shape
    default_max_depth: int = 3
    max_depth_limit: int = 3
    min_depth: int = 2
    default_max_branches: int = 6
    max_branches_limit: int = 12
    max_children: int = 6
    max_parent_branches: int = 8
    max_repair_attempts: int = 2

    # Chunking
    chunk_chars: int = 6000
    chunk_overlap_chars: int = 300
    single_call_char_limit: int = 12000
    max_input_chars: int = 48000

    # LLM
    llm_provider: Literal["openai", "mock"] = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("API_KEY", "LLM_API_KEY"),
    )
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.2
    llm_json_mode: Literal["json_schema", "json_object"] = "json_schema"
    llm_concurrency: int = 4
    llm_max_output_tokens: int = 4096

    # Jobs / cache
    job_ttl_minutes: int = 60
    cache_enabled: bool = True
    cache_max_entries: int = 64

    @field_validator("llm_concurrency")
    @classmethod
    def _positive_concurrency(cls, value: int) -> int:
        if value < 1:
            raise ValueError("LLM_CONCURRENCY must be >= 1")
        return value

    @field_validator("max_depth_limit")
    @classmethod
    def _valid_depth_limit(cls, value: int) -> int:
        if value < 1 or value > 3:
            raise ValueError("MAX_DEPTH_LIMIT must be between 1 and 3")
        return value

    @property
    def max_upload_bytes(self) -> int:
        """Upload limit expressed in bytes."""
        return self.max_upload_mb * 1024 * 1024

    def clamp_max_depth(self, value: int | None) -> int:
        """Clamp a requested depth to the supported structured-output depth."""
        requested = self.default_max_depth if value is None else value
        return max(self.min_depth, min(requested, self.max_depth_limit))

    def clamp_max_branches(self, value: int | None) -> int:
        """Clamp a requested branch count to a safe range."""
        requested = self.default_max_branches if value is None else value
        return max(2, min(requested, self.max_branches_limit))


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
