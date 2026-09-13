from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

from .config import Settings
from .errors import ProviderError


def model_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "json"):
        return json.loads(value.json())
    raise TypeError(f"Unsupported Azure response type: {type(value).__name__}")


def extract_output_text(response: dict[str, Any]) -> str:
    text_parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
    return "".join(text_parts)


def normalize_content_part(part: Any) -> dict[str, Any]:
    """Normalize multimodal message content parts into Azure Foundry Responses API format."""
    if isinstance(part, str):
        return {"type": "input_text", "text": part}
    if not isinstance(part, dict):
        return {"type": "input_text", "text": str(part)}
    part_type = part.get("type")
    if part_type in {"text", "input_text"}:
        return {"type": "input_text", "text": part.get("text", "")}
    if part_type in {"image_url", "input_image"}:
        img = part.get("image_url") or part.get("url")
        if isinstance(img, dict):
            url = img.get("url", "")
        else:
            url = str(img or "")
        return {"type": "input_image", "image_url": url}
    return part


def normalize_input(input_val: Any) -> Any:
    """Normalize input payloads so both OpenAI and Azure multimodal structures work."""
    if isinstance(input_val, str):
        return input_val
    if isinstance(input_val, list):
        normalized_list: list[Any] = []
        for item in input_val:
            if isinstance(item, dict) and "content" in item:
                content = item["content"]
                if isinstance(content, list):
                    item_copy = dict(item)
                    item_copy["content"] = [normalize_content_part(p) for p in content]
                    normalized_list.append(item_copy)
                else:
                    normalized_list.append(item)
            elif isinstance(item, dict) and item.get("type") in {
                "text",
                "image_url",
                "input_text",
                "input_image",
            }:
                normalized_list.append(normalize_content_part(item))
            else:
                normalized_list.append(item)
        return normalized_list
    return input_val


class FoundryGateway:
    """Lazy, thread-safe adapter around the Azure AI Projects OpenAI client."""

    def __init__(self, settings: Settings, openai_client: Any | None = None) -> None:
        self.settings = settings
        self._openai_client = openai_client
        self._project_client: Any | None = None
        self._credential: Any | None = None
        self._client_lock = threading.Lock()

    def _client(self) -> Any:
        if self._openai_client is not None:
            return self._openai_client

        with self._client_lock:
            if self._openai_client is None:
                import os
                from azure.ai.projects import AIProjectClient
                from azure.identity import ClientSecretCredential, DefaultAzureCredential

                if (
                    self.settings.azure_tenant_id
                    and self.settings.azure_client_id
                    and self.settings.azure_client_secret
                ):
                    os.environ.setdefault("AZURE_TENANT_ID", self.settings.azure_tenant_id)
                    os.environ.setdefault("AZURE_CLIENT_ID", self.settings.azure_client_id)
                    os.environ.setdefault("AZURE_CLIENT_SECRET", self.settings.azure_client_secret)
                    self._credential = ClientSecretCredential(
                        tenant_id=self.settings.azure_tenant_id,
                        client_id=self.settings.azure_client_id,
                        client_secret=self.settings.azure_client_secret,
                    )
                else:
                    self._credential = DefaultAzureCredential(
                        exclude_interactive_browser_credential=True
                    )

                self._project_client = AIProjectClient(
                    endpoint=self.settings.foundry_project_endpoint,
                    credential=self._credential,
                )
                self._openai_client = self._project_client.get_openai_client()
        return self._openai_client

    def _prepare_payload(
        self, payload: dict[str, Any], *, stream: bool
    ) -> dict[str, Any]:
        prepared = dict(payload)
        requested_model = prepared.pop("model", None)
        if requested_model and requested_model not in self.settings.accepted_model_ids():
            raise ProviderError(
                f"Model '{requested_model}' is not available.",
                status_code=404,
                code="model_not_found",
                param="model",
            )

        supplied_extra = prepared.pop("extra_body", None)
        extra_body = dict(supplied_extra) if isinstance(supplied_extra, dict) else {}
        extra_body["agent_reference"] = {
            "name": self.settings.foundry_agent_name,
            "version": self.settings.foundry_agent_version,
            "type": "agent_reference",
        }
        prepared["extra_body"] = extra_body
        prepared["stream"] = stream
        prepared["timeout"] = self.settings.request_timeout_seconds
        if "input" in prepared:
            prepared["input"] = normalize_input(prepared["input"])
        return prepared

    def create_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client().responses.create(
                **self._prepare_payload(payload, stream=False)
            )
            result = model_to_dict(response)
            result["model"] = self.settings.provider_model_id
            return result
        except ProviderError:
            raise
        except Exception as exc:  # Azure/OpenAI SDK exceptions vary by version.
            raise self._upstream_error(exc) from exc

    def stream_events(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        stream: Any | None = None
        try:
            stream = self._client().responses.create(
                **self._prepare_payload(payload, stream=True)
            )
            for event in stream:
                data = model_to_dict(event)
                if "model" in data:
                    data["model"] = self.settings.provider_model_id
                yield data
        except ProviderError:
            raise
        except Exception as exc:
            raise self._upstream_error(exc) from exc
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

    def close(self) -> None:
        for client in (self._openai_client, self._project_client, self._credential):
            close = getattr(client, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _upstream_error(exc: Exception) -> ProviderError:
        status = int(getattr(exc, "status_code", 502) or 502)
        if status < 400 or status > 599:
            status = 502
        if status == 401 or status == 403:
            message = "Azure authentication or project access was rejected."
            code = "azure_authentication_failed"
        elif status == 404:
            message = "The configured Azure project or agent version was not found."
            code = "azure_agent_not_found"
        elif status == 429:
            message = "Azure Foundry rate limit reached. Try again shortly."
            code = "azure_rate_limit"
        else:
            raw_msg = str(getattr(exc, "message", "") or str(exc) or "").strip()
            message = f"The Azure Foundry request failed: {raw_msg}" if raw_msg else "The Azure Foundry request failed."
            code = "azure_upstream_error"
        return ProviderError(
            message,
            status_code=status,
            error_type="api_error",
            code=code,
        )
