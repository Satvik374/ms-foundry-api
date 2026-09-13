from __future__ import annotations

from functools import lru_cache
import os

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(override=True)


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Foundry Relay"
    app_environment: str = "development"
    app_debug: bool = False

    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    azure_voicelive_api_key: str = ""

    foundry_project_endpoint: str = (
        "https://satviksingh-resource.services.ai.azure.com/api/projects/satviksingh"
    )
    foundry_agent_name: str = "gpt-6"
    foundry_agent_version: str = "1"

    provider_model_id: str = "gpt-6"
    provider_api_key: str = ""
    admin_api_key: str = ""
    public_base_url: str = ""

    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    azure_speech_key: str = ""
    azure_speech_endpoint: str = ""
    azure_speech_voice: str = "en-US-OnyxTurboMultilingualNeural"

    azure_voicelive_endpoint: str = ""
    azure_voicelive_agent_id: str = ""
    azure_voicelive_project_name: str = ""
    azure_voicelive_api_version: str = "2025-10-01"
    azure_voicelive_model: str = "gpt-realtime"
    azure_voicelive_voice: str = "en-US-Ava:DragonHDLatestNeural"
    azure_voicelive_instructions: str = (
        "You are a helpful AI assistant. Respond naturally and conversationally. "
        "Keep your responses concise but engaging."
    )

    allowed_origins: str = ""
    request_timeout_seconds: float = Field(default=120.0, ge=1, le=600)
    max_request_bytes: int = Field(default=2_000_000, ge=1_024, le=20_000_000)

    @field_validator("foundry_project_endpoint")
    @classmethod
    def validate_project_endpoint(cls, value: str) -> str:
        endpoint = value.strip().rstrip("/")
        if not endpoint.startswith("https://"):
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT must use HTTPS")
        if "/api/projects/" not in endpoint:
            raise ValueError(
                "FOUNDRY_PROJECT_ENDPOINT must be a Foundry project endpoint"
            )
        return endpoint

    @field_validator(
        "foundry_agent_name",
        "foundry_agent_version",
        "provider_model_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This setting cannot be empty")
        return cleaned

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def provider_ready(self) -> bool:
        return bool(self.provider_api_key and self.foundry_project_endpoint)

    @property
    def speech_ready(self) -> bool:
        return bool(self.azure_speech_key and self.azure_speech_endpoint)

    @property
    def admin_unlock_enabled(self) -> bool:
        return bool(self.admin_api_key)

    @property
    def voicelive_ready(self) -> bool:
        return bool(self.azure_voicelive_endpoint)

    def accepted_model_ids(self) -> set[str]:
        return {
            self.provider_model_id,
            self.foundry_agent_name,
            f"{self.foundry_agent_name}:{self.foundry_agent_version}",
            f"{self.foundry_agent_name}@{self.foundry_agent_version}",
            "jarvis-2",
            "jarvis",
            "gpt-realtime",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
