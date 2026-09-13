from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .auth import require_admin_key, require_provider_key
from .azure_gateway import FoundryGateway, extract_output_text, normalize_content_part
from .config import Settings, get_settings
from .errors import ProviderError, provider_error_handler
from .schemas import ChatCompletionsRequest, ResponsesRequest, SpeechRequest
from .speech_gateway import SpeechGateway
from .voicelive_gateway import VoiceLiveGateway

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = "no-cache, must-revalidate"
        return response


def _provider_base_url(request: Request, settings: Settings) -> str:
    origin = settings.public_base_url.strip() if settings.public_base_url else ""
    if not origin:
        origin = str(request.base_url).rstrip("/")
    return f"{origin.rstrip('/')}/v1"


def _json_sse(data: dict[str, Any], event_name: str | None = None) -> str:
    prefix = f"event: {event_name}\n" if event_name else ""
    return f"{prefix}data: {json.dumps(data, separators=(',', ':'))}\n\n"


def _chat_input_messages(body: ChatCompletionsRequest) -> list[dict[str, Any]]:
    """Translate Chat Completions messages for a Foundry agent reference.

    Foundry agent-reference calls reject system/developer input items because the
    agent version owns the native instructions. Preserve those client instructions
    by folding them into the first user message instead of forwarding an unsupported
    role to Azure.
    """
    instructions: list[str] = []
    messages: list[dict[str, Any]] = []

    for message in body.messages:
        dumped = message.model_dump(exclude_none=True)
        if message.role in {"system", "developer"}:
            content = message.content
            instructions.append(
                content if isinstance(content, str) else json.dumps(content, separators=(",", ":"))
            )
        else:
            if isinstance(dumped.get("content"), list):
                dumped["content"] = [normalize_content_part(p) for p in dumped["content"]]
            messages.append(dumped)

    if not instructions:
        return messages

    prefix = (
        "Client system instructions (follow these before the user request):\n"
        + "\n\n".join(instructions)
        + "\n\nUser request:\n"
    )
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = prefix + content
        elif isinstance(content, list):
            message["content"].insert(0, {"type": "input_text", "text": prefix.rstrip()})
        else:
            message["content"] = prefix + json.dumps(content, separators=(",", ":"))
        break
    else:
        messages.insert(0, {"role": "user", "content": prefix.rstrip()})

    return messages


def _chat_response_payload(body: ChatCompletionsRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": body.model,
        "input": _chat_input_messages(body),
    }
    # Agent-reference calls use the agent version's configured model settings and
    # reject per-request sampling controls such as temperature/top_p. Accept these
    # OpenAI-compatible fields at our boundary but do not forward them to Foundry.
    max_tokens = body.max_completion_tokens or body.max_tokens
    if max_tokens is not None:
        payload["max_output_tokens"] = max_tokens
    if body.metadata is not None:
        payload["metadata"] = body.metadata
    return payload


def create_app(
    settings: Settings | None = None,
    gateway: FoundryGateway | None = None,
    speech_gateway: SpeechGateway | None = None,
    voicelive_gateway: VoiceLiveGateway | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    runtime_gateway = gateway or FoundryGateway(runtime_settings)
    runtime_speech_gateway = speech_gateway or SpeechGateway(runtime_settings)
    runtime_voicelive_gateway = voicelive_gateway or VoiceLiveGateway(runtime_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await run_in_threadpool(runtime_gateway.close)

    app = FastAPI(
        title=runtime_settings.app_name,
        description="OpenAI-compatible gateway for a Microsoft Foundry agent.",
        version="1.0.0",
        docs_url="/reference",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.state.gateway = runtime_gateway
    app.state.speech_gateway = runtime_speech_gateway
    app.state.voicelive_gateway = runtime_voicelive_gateway
    app.add_exception_handler(ProviderError, provider_error_handler)

    cors_origins = runtime_settings.cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def enforce_request_size(request: Request, call_next):
        content_length = request.headers.get("content-length")
        try:
            request_size = int(content_length) if content_length else 0
        except ValueError:
            request_size = runtime_settings.max_request_bytes + 1
        if request_size > runtime_settings.max_request_bytes:
            return JSONResponse(
                status_code=413,
                content=ProviderError(
                    "Request body is too large.",
                    status_code=413,
                    code="request_too_large",
                ).as_dict(),
            )
        response = await call_next(request)
        if request.url.path.startswith(("/assets/", "/api/")) or request.url.path in {"/", "/index.html"}:
            response.headers["cache-control"] = "no-cache, no-store, must-revalidate"
            response.headers["pragma"] = "no-cache"
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        response.headers["permissions-policy"] = "camera=(), microphone=*, geolocation=()"
        connect_sources = ["'self'", "https:", "http:", "ws:", "wss:"]
        if runtime_settings.public_base_url:
            connect_sources.append(runtime_settings.public_base_url)
        connect_src = " ".join(dict.fromkeys(connect_sources))

        response.headers["content-security-policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https:; "
            "img-src 'self' data: https:; "
            f"connect-src {connect_src}; "
            "font-src 'self' data: https:; "
            "media-src 'self' blob: data:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = first.get("loc", [])
        param = str(location[-1]) if location else None
        error = ProviderError(
            first.get("msg", "Invalid request."),
            status_code=422,
            code="validation_error",
            param=param,
        )
        return JSONResponse(status_code=422, content=error.as_dict())

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "ready": runtime_settings.provider_ready,
            "service": runtime_settings.app_name,
        }

    @app.get("/readyz", include_in_schema=False)
    async def readiness() -> JSONResponse:
        ready = runtime_settings.provider_ready
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "configuration_required"},
        )

    @app.get("/api/config", include_in_schema=False)
    async def public_config(request: Request) -> dict[str, Any]:
        return {
            "appName": runtime_settings.app_name,
            "environment": runtime_settings.app_environment,
            "modelId": runtime_settings.provider_model_id,
            "baseUrl": _provider_base_url(request, runtime_settings),
            "projectEndpoint": runtime_settings.foundry_project_endpoint,
            "agentName": runtime_settings.foundry_agent_name,
            "agentVersion": runtime_settings.foundry_agent_version,
            "providerReady": runtime_settings.provider_ready,
            "providerKeyConfigured": bool(runtime_settings.provider_api_key),
            "adminUnlockEnabled": runtime_settings.admin_unlock_enabled,
            "authMode": "DefaultAzureCredential",
            "speechReady": runtime_settings.speech_ready,
            "speechVoice": runtime_settings.azure_speech_voice,
            "voiceliveReady": runtime_settings.voicelive_ready,
            "voiceliveModel": runtime_settings.azure_voicelive_model,
            "voiceliveVoice": runtime_settings.azure_voicelive_voice,
        }

    @app.post(
        "/api/admin/verify",
        dependencies=[Depends(require_admin_key)],
        include_in_schema=False,
    )
    async def verify_admin() -> dict[str, bool]:
        return {"ok": True}

    @app.get(
        "/api/admin/provider-key",
        dependencies=[Depends(require_admin_key)],
        include_in_schema=False,
    )
    async def provider_key() -> JSONResponse:
        if not runtime_settings.provider_api_key:
            raise ProviderError(
                "PROVIDER_API_KEY has not been configured.",
                status_code=503,
                error_type="server_error",
                code="provider_not_configured",
            )
        return JSONResponse(
            content={"apiKey": runtime_settings.provider_api_key},
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/v1/models", dependencies=[Depends(require_provider_key)])
    async def models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": runtime_settings.provider_model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "microsoft-foundry",
                },
                {
                    "id": "tts-1",
                    "object": "model",
                    "created": 0,
                    "owned_by": "azure-cognitive-services",
                },
                {
                    "id": "tts-1-hd",
                    "object": "model",
                    "created": 0,
                    "owned_by": "azure-cognitive-services",
                },
                {
                    "id": "gpt-realtime",
                    "object": "model",
                    "created": 0,
                    "owned_by": "azure-voicelive",
                },
            ],
        }

    @app.post("/v1/audio/speech", dependencies=[Depends(require_provider_key)])
    async def audio_speech(body: SpeechRequest):
        audio_bytes, media_type = await run_in_threadpool(
            runtime_speech_gateway.synthesize_speech,
            text=body.input,
            voice=body.voice,
            response_format=body.response_format,
            speed=body.speed,
        )
        return Response(
            content=audio_bytes,
            media_type=media_type,
            headers={
                "Content-Type": media_type,
                "Content-Length": str(len(audio_bytes)),
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-cache",
            },
        )

    async def _authenticate_ws(websocket: WebSocket) -> bool:
        if not runtime_settings.provider_api_key:
            return True
        token = websocket.query_params.get("api_key") or websocket.query_params.get("token")
        if not token:
            auth_header = websocket.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()
            else:
                token = websocket.headers.get("api-key") or websocket.headers.get("x-api-key")
        return token in {runtime_settings.provider_api_key, runtime_settings.admin_api_key}

    @app.websocket("/v1/realtime")
    @app.websocket("/api/realtime/ws")
    async def realtime_ws(websocket: WebSocket):
        await websocket.accept()
        if not await _authenticate_ws(websocket):
            await websocket.send_text(
                json.dumps({
                    "type": "error",
                    "error": {
                        "message": "Incorrect API key provided.",
                        "type": "authentication_error",
                        "code": "invalid_api_key",
                    },
                })
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        model = websocket.query_params.get("model")
        voice = websocket.query_params.get("voice")
        instructions = websocket.query_params.get("instructions")

        session = runtime_voicelive_gateway.create_session(
            client_ws=websocket,
            model=model,
            voice=voice,
            instructions=instructions,
        )
        await session.run()

    @app.post("/v1/responses", dependencies=[Depends(require_provider_key)])
    async def responses(body: ResponsesRequest):
        payload = body.model_dump(exclude_none=True)
        if not body.stream:
            return await run_in_threadpool(runtime_gateway.create_response, payload)

        events = await run_in_threadpool(runtime_gateway.stream_events, payload)

        def response_stream():
            try:
                for event in events:
                    yield _json_sse(event, event.get("type"))
                yield "data: [DONE]\n\n"
            except ProviderError as exc:
                yield _json_sse(exc.as_dict(), "error")

        return StreamingResponse(
            response_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/chat/completions", dependencies=[Depends(require_provider_key)])
    async def chat_completions(body: ChatCompletionsRequest):
        response_payload = _chat_response_payload(body)
        chat_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())

        if body.stream:
            events = await run_in_threadpool(
                runtime_gateway.stream_events, response_payload
            )

            def chat_stream():
                yield _json_sse(
                    {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": runtime_settings.provider_model_id,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": ""},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
                try:
                    for event in events:
                        if event.get("type") != "response.output_text.delta":
                            continue
                        delta = event.get("delta", "")
                        if not delta:
                            continue
                        yield _json_sse(
                            {
                                "id": chat_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": runtime_settings.provider_model_id,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": delta},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                        )
                    yield _json_sse(
                        {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": runtime_settings.provider_model_id,
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": "stop"}
                            ],
                        }
                    )
                    yield "data: [DONE]\n\n"
                except ProviderError as exc:
                    yield _json_sse(exc.as_dict())
                    yield "data: [DONE]\n\n"

            return StreamingResponse(
                chat_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        foundry_response = await run_in_threadpool(
            runtime_gateway.create_response, response_payload
        )
        usage = foundry_response.get("usage") or {}
        return {
            "id": chat_id,
            "object": "chat.completion",
            "created": created,
            "model": runtime_settings.provider_model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": extract_output_text(foundry_response),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }

    app.mount("/assets", NoCacheStaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    return app
