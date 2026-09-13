from __future__ import annotations

import secrets

from fastapi import Header, Request

from .config import Settings
from .errors import ProviderError


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def _matches(presented: str, expected: str) -> bool:
    return bool(presented and expected) and secrets.compare_digest(presented, expected)


async def require_provider_key(
    request: Request,
    authorization: str | None = Header(default=None),
    api_key: str | None = Header(default=None, alias="api-key"),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> None:
    settings: Settings = request.app.state.settings
    if not settings.provider_api_key:
        raise ProviderError(
            "The provider API key has not been configured on this server.",
            status_code=503,
            error_type="server_error",
            code="provider_not_configured",
        )

    presented = _bearer_token(authorization) or api_key or x_api_key or ""
    if not _matches(presented, settings.provider_api_key):
        raise ProviderError(
            "Invalid API key.",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )


async def require_admin_key(
    request: Request,
    x_admin_key: str | None = Header(default=None, alias="x-admin-key"),
) -> None:
    settings: Settings = request.app.state.settings
    if not settings.admin_api_key:
        raise ProviderError(
            "Dashboard unlock is disabled until ADMIN_API_KEY is configured.",
            status_code=503,
            error_type="server_error",
            code="admin_unlock_disabled",
        )
    if not _matches(x_admin_key or "", settings.admin_api_key):
        raise ProviderError(
            "Invalid administrator key.",
            status_code=401,
            error_type="authentication_error",
            code="invalid_admin_key",
        )
