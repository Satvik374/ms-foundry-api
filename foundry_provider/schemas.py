from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    input: str | list[Any]
    stream: bool = False

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["developer", "system", "user", "assistant", "tool"]
    content: Any


class ChatCompletionsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    metadata: dict[str, str] | None = None


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = "tts-1"
    input: str
    voice: str = "onyx"
    response_format: str = "mp3"
    speed: float | None = 1.0

