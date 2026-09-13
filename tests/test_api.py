import json
from typing import Any

from fastapi.testclient import TestClient

from foundry_provider.app import create_app
from foundry_provider.azure_gateway import FoundryGateway
from foundry_provider.config import Settings
from foundry_provider.speech_gateway import SpeechGateway


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            if kwargs.get("tools"):
                tool_name = kwargs["tools"][0].get("name", "Write")
                return iter(
                    [
                        {"type": "response.created", "response": {"id": "resp_test"}},
                        {
                            "type": "response.output_item.added",
                            "item": {
                                "type": "function_call",
                                "call_id": "call_123",
                                "name": tool_name,
                            },
                        },
                        {
                            "type": "response.function_call_arguments.delta",
                            "delta": '{"file_path":"game.html"}',
                        },
                        {"type": "response.function_call_arguments.done"},
                        {"type": "response.output_item.done"},
                        {"type": "response.completed", "response": {"id": "resp_test"}},
                    ]
                )
            return iter(
                [
                    {"type": "response.created", "response": {"id": "resp_test"}},
                    {"type": "response.output_text.delta", "delta": "Hello"},
                    {"type": "response.output_text.delta", "delta": " there"},
                    {"type": "response.completed", "response": {"id": "resp_test"}},
                ]
            )
        if kwargs.get("tools"):
            tool_name = kwargs["tools"][0].get("name", "Write")
            return {
                "id": "resp_test",
                "object": "response",
                "model": "azure-internal-model",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_123",
                        "name": tool_name,
                        "arguments": json.dumps({"file_path": "game.html", "content": "<h1>Minecraft</h1>"}),
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
            }
        return {
            "id": "resp_test",
            "object": "response",
            "model": "azure-internal-model",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Hello there"}],
                }
            ],
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        }


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()

    def close(self) -> None:
        return None


class FakeSpeechGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def synthesize_speech(
        self,
        text: str,
        voice: str | None = None,
        response_format: str = "mp3",
        speed: float | None = 1.0,
    ) -> tuple[bytes, str]:
        self.calls.append(
            {
                "text": text,
                "voice": voice,
                "response_format": response_format,
                "speed": speed,
            }
        )
        media_type = "audio/mpeg" if response_format == "mp3" else f"audio/{response_format}"
        return b"FAKE_AUDIO_DATA_MP3", media_type


def make_client() -> tuple[TestClient, FakeOpenAIClient]:
    settings = Settings(
        provider_api_key="frly_provider_test",
        admin_api_key="frly_admin_test",
        app_environment="test",
        public_base_url="",
        foundry_agent_name="jarvis",
        foundry_agent_version="2",
        provider_model_id="jarvis-2",
    )
    fake = FakeOpenAIClient()
    gateway = FoundryGateway(settings, openai_client=fake)
    return TestClient(create_app(settings=settings, gateway=gateway)), fake


def make_speech_client() -> tuple[TestClient, FakeSpeechGateway]:
    settings = Settings(
        provider_api_key="frly_provider_test",
        admin_api_key="frly_admin_test",
        app_environment="test",
        public_base_url="",
        foundry_agent_name="jarvis",
        foundry_agent_version="2",
        provider_model_id="jarvis-2",
        azure_speech_key="fake-speech-key",
        azure_speech_endpoint="https://fake-speech.cognitiveservices.azure.com/",
    )
    fake_openai = FakeOpenAIClient()
    fake_speech = FakeSpeechGateway()
    gateway = FoundryGateway(settings, openai_client=fake_openai)
    return (
        TestClient(
            create_app(
                settings=settings,
                gateway=gateway,
                speech_gateway=fake_speech,
            )
        ),
        fake_speech,
    )


class FakeVoiceLiveSession:
    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.received: list[dict[str, Any]] = []

    async def run(self) -> None:
        await self.ws.send_text(
            json.dumps({"type": "session.created", "session": {"id": "fake_session_123"}})
        )
        try:
            while True:
                msg = await self.ws.receive_text()
                payload = json.loads(msg)
                self.received.append(payload)
                if payload.get("type") == "input_audio_buffer.append":
                    await self.ws.send_text(
                        json.dumps({"type": "response.audio.delta", "delta": "FAKE_PCM16_DELTA"})
                    )
                elif payload.get("type") == "session.update":
                    await self.ws.send_text(
                        json.dumps({"type": "session.updated", "session": payload.get("session", {})})
                    )
        except Exception:
            pass


class FakeVoiceLiveGateway:
    def __init__(self) -> None:
        self.sessions: list[FakeVoiceLiveSession] = []

    def create_session(self, client_ws: Any, **kwargs: Any) -> FakeVoiceLiveSession:
        session = FakeVoiceLiveSession(client_ws)
        self.sessions.append(session)
        return session


def make_voicelive_client() -> tuple[TestClient, FakeVoiceLiveGateway]:
    settings = Settings(
        provider_api_key="frly_provider_test",
        admin_api_key="frly_admin_test",
        app_environment="test",
        public_base_url="",
        foundry_agent_name="jarvis",
        foundry_agent_version="2",
        provider_model_id="jarvis-2",
        azure_voicelive_endpoint="https://fake-voicelive.services.ai.azure.com/",
    )
    fake_openai = FakeOpenAIClient()
    fake_voicelive = FakeVoiceLiveGateway()
    gateway = FoundryGateway(settings, openai_client=fake_openai)
    return (
        TestClient(
            create_app(
                settings=settings,
                gateway=gateway,
                voicelive_gateway=fake_voicelive,
            )
        ),
        fake_voicelive,
    )


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer frly_provider_test"}


def test_dashboard_and_public_config_do_not_expose_secrets() -> None:
    client, _ = make_client()

    page = client.get("/")
    config = client.get("/api/config")

    assert page.status_code == 200
    assert "Foundry Relay" in page.text
    assert config.status_code == 200
    assert config.json()["modelId"] == "jarvis-2"
    assert config.json()["baseUrl"] == "http://testserver/v1"
    assert "frly_provider_test" not in config.text
    assert "frly_admin_test" not in config.text


def test_content_security_policy_headers() -> None:
    client, _ = make_client()

    response = client.get("/")
    assert response.status_code == 200
    csp = response.headers.get("content-security-policy", "")
    assert "font-src 'self' data: https:" in csp
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in csp
    assert "connect-src 'self' https: http: ws: wss:" in csp
    assert "media-src 'self' blob: data:" in csp


def test_health_and_readiness() -> None:
    client, _ = make_client()

    assert client.get("/healthz").json()["ready"] is True
    assert client.get("/readyz").status_code == 200


def test_provider_requires_a_valid_api_key() -> None:
    client, _ = make_client()

    missing = client.get("/v1/models")
    invalid = client.get("/v1/models", headers={"api-key": "wrong"})
    valid = client.get("/v1/models", headers={"api-key": "frly_provider_test"})

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200
    assert valid.json()["data"][0]["id"] == "jarvis-2"


def test_responses_route_injects_agent_reference_and_hides_internal_model() -> None:
    client, fake = make_client()

    response = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "jarvis-2", "input": "Hello"},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "jarvis-2"
    call = fake.responses.calls[-1]
    assert "model" not in call
    assert call["stream"] is False
    assert call["extra_body"]["agent_reference"] == {
        "name": "jarvis",
        "version": "2",
        "type": "agent_reference",
    }


def test_unknown_model_is_rejected() -> None:
    client, _ = make_client()

    response = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "other-model", "input": "Hello"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"


def test_responses_stream_passes_through_foundry_events() -> None:
    client, fake = make_client()

    with client.stream(
        "POST",
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "jarvis-2", "input": "Hello", "stream": True},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: response.output_text.delta" in body
    assert '"delta":"Hello"' in body
    assert '"delta":" there"' in body
    assert "data: [DONE]" in body
    call = fake.responses.calls[-1]
    assert call["stream"] is True
    assert call["extra_body"]["agent_reference"]["name"] == "jarvis"


def test_chat_completions_adapter() -> None:
    client, fake = make_client()

    response = client.post(
        "/v1/chat/completions",
        headers=auth_headers(),
        json={
            "model": "jarvis-2",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Hello"},
            ],
            "temperature": 0.3,
            "top_p": 0.9,
            "max_tokens": 256,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"] == "Hello there"
    assert payload["usage"]["total_tokens"] == 5
    call = fake.responses.calls[-1]
    assert call["input"] == [
        {
            "role": "user",
            "content": (
                "Client system instructions (follow these before the user request):\n"
                "Be concise.\n\nUser request:\nHello"
            ),
        }
    ]
    assert call["max_output_tokens"] == 256
    assert "temperature" not in call
    assert "top_p" not in call


def test_chat_completions_streaming_adapter() -> None:
    client, fake = make_client()

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=auth_headers(),
        json={
            "model": "jarvis-2",
            "messages": [
                {"role": "developer", "content": "Be concise."},
                {"role": "user", "content": "Hello"},
            ],
            "temperature": 0.3,
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"content":"Hello"' in body
    assert '"content":" there"' in body
    assert "data: [DONE]" in body
    call = fake.responses.calls[-1]
    assert call["input"][0]["role"] == "user"
    assert call["input"][0]["content"].endswith("User request:\nHello")
    assert "temperature" not in call


def test_admin_key_reveal_is_protected() -> None:
    client, _ = make_client()

    rejected = client.get("/api/admin/provider-key", headers={"x-admin-key": "wrong"})
    accepted = client.get(
        "/api/admin/provider-key", headers={"x-admin-key": "frly_admin_test"}
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["apiKey"] == "frly_provider_test"


def test_multimodal_image_input_handling() -> None:
    client, fake = make_client()

    response = client.post(
        "/v1/chat/completions",
        headers=auth_headers(),
        json={
            "model": "jarvis-2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is this?"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    call = fake.responses.calls[-1]
    user_content = call["input"][0]["content"]
    assert user_content[0]["type"] == "input_text"
    assert user_content[0]["text"] == "What is this?"
    assert user_content[1]["type"] == "input_image"
    assert user_content[1]["image_url"] == "data:image/png;base64,AAA"


def test_models_endpoint_includes_tts() -> None:
    client, _ = make_client()

    response = client.get("/v1/models", headers=auth_headers())
    assert response.status_code == 200
    data = response.json().get("data", [])
    model_ids = {m["id"] for m in data}
    assert "tts-1" in model_ids
    assert "tts-1-hd" in model_ids
    assert "jarvis-2" in model_ids


def test_audio_speech_endpoint_success() -> None:
    client, fake_speech = make_speech_client()

    response = client.post(
        "/v1/audio/speech",
        headers=auth_headers(),
        json={
            "model": "tts-1",
            "input": "Hello from Foundry Relay!",
            "voice": "onyx",
            "response_format": "mp3",
            "speed": 1.0,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"FAKE_AUDIO_DATA_MP3"
    assert len(fake_speech.calls) == 1
    call = fake_speech.calls[0]
    assert call["text"] == "Hello from Foundry Relay!"
    assert call["voice"] == "onyx"
    assert call["response_format"] == "mp3"


def test_audio_speech_endpoint_unauthorized() -> None:
    client, _ = make_speech_client()

    response = client.post(
        "/v1/audio/speech",
        json={
            "model": "tts-1",
            "input": "Hello",
            "voice": "onyx",
        },
    )
    assert response.status_code == 401


def test_audio_speech_formats() -> None:
    client, fake_speech = make_speech_client()

    response = client.post(
        "/v1/audio/speech",
        headers=auth_headers(),
        json={
            "model": "tts-1",
            "input": "Testing WAV format",
            "voice": "alloy",
            "response_format": "wav",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert fake_speech.calls[-1]["response_format"] == "wav"


def test_speech_gateway_voice_resolution() -> None:
    settings = Settings(
        provider_api_key="frly_test",
        azure_speech_voice="en-US-OnyxTurboMultilingualNeural",
    )
    gateway = SpeechGateway(settings)

    assert gateway.resolve_voice("onyx") == "en-US-OnyxTurboMultilingualNeural"
    assert gateway.resolve_voice("ALLOY") == "en-US-AlloyTurboMultilingualNeural"
    assert gateway.resolve_voice("fable") == "en-US-FableTurboMultilingualNeural"
    assert gateway.resolve_voice("custom-voice-name") == "custom-voice-name"
    assert gateway.resolve_voice(None) == "en-US-OnyxTurboMultilingualNeural"


def test_models_endpoint_includes_gpt_realtime() -> None:
    client, _ = make_client()

    response = client.get("/v1/models", headers=auth_headers())
    assert response.status_code == 200
    model_ids = {m["id"] for m in response.json().get("data", [])}
    assert "gpt-realtime" in model_ids


def test_public_config_includes_voicelive() -> None:
    client, _ = make_voicelive_client()

    response = client.get("/api/config")
    assert response.status_code == 200
    config = response.json()
    assert config["voiceliveReady"] is True
    assert config["voiceliveModel"] == "gpt-realtime"


def test_realtime_ws_unauthorized() -> None:
    client, _ = make_voicelive_client()

    with client.websocket_connect("/v1/realtime?api_key=wrong_key") as ws:
        data = ws.receive_json()
        assert data["type"] == "error"
        assert data["error"]["code"] == "invalid_api_key"


def test_realtime_ws_authorized() -> None:
    client, fake_vl = make_voicelive_client()

    with client.websocket_connect("/v1/realtime?api_key=frly_provider_test") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "session.created"
        assert msg["session"]["id"] == "fake_session_123"
        assert len(fake_vl.sessions) == 1


def test_realtime_ws_audio_exchange() -> None:
    client, fake_vl = make_voicelive_client()

    with client.websocket_connect("/v1/realtime?api_key=frly_provider_test") as ws:
        created = ws.receive_json()
        assert created["type"] == "session.created"

        # Send audio buffer chunk
        ws.send_json({"type": "input_audio_buffer.append", "audio": "BASE64_PCM16_CHUNK"})
        resp = ws.receive_json()
        assert resp["type"] == "response.audio.delta"
        assert resp["delta"] == "FAKE_PCM16_DELTA"

        # Send session update
        ws.send_json({"type": "session.update", "session": {"voice": "en-US-Ava:DragonHDLatestNeural"}})
        updated = ws.receive_json()
        assert updated["type"] == "session.updated"
        assert updated["session"]["voice"] == "en-US-Ava:DragonHDLatestNeural"


def test_anthropic_messages_non_streaming() -> None:
    client, fake_gateway = make_client()
    res = client.post(
        "/v1/messages",
        headers={"x-api-key": "frly_provider_test"},
        json={
            "model": "gpt-6",
            "messages": [{"role": "user", "content": "Hello from Claude Code"}],
            "stream": False,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["content"][0]["text"] == "Hello there"
    assert data["model"] == "gpt-6"
    assert data["stop_reason"] == "end_turn"


def test_anthropic_messages_streaming() -> None:
    client, fake_gateway = make_client()
    res = client.post(
        "/v1/messages",
        headers={"x-api-key": "frly_provider_test"},
        json={
            "model": "gpt-6",
            "system": "You are a code assistant.",
            "messages": [{"role": "user", "content": "Count to two"}],
            "stream": True,
        },
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    text = res.text
    assert "event: message_start" in text
    assert "event: content_block_start" in text
    assert "event: content_block_delta" in text
    assert "event: content_block_stop" in text
    assert "event: message_delta" in text
    assert "event: message_stop" in text


def test_anthropic_messages_route_aliases() -> None:
    client, fake_gateway = make_client()
    for route in ("/messages", "/v1/v1/messages"):
        res = client.post(
            route,
            headers={"anthropic-auth-token": "frly_provider_test"},
            json={
                "model": "claude-3-7-sonnet-20250219",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            },
        )
        assert res.status_code == 200
        assert res.json()["role"] == "assistant"


def test_models_endpoint_has_claude_and_can_get_single_model() -> None:
    client, _ = make_client()
    res = client.get("/v1/models", headers={"Authorization": "Bearer frly_provider_test"})
    assert res.status_code == 200
    ids = [m["id"] for m in res.json()["data"]]
    assert "gpt-6" in ids
    assert "claude-3-7-sonnet-20250219" in ids
    assert "claude-3-5-sonnet-20241022" in ids

    # Check single model query
    res_single = client.get("/v1/models/gpt-6", headers={"x-api-key": "frly_provider_test"})
    assert res_single.status_code == 200
    assert res_single.json()["id"] == "gpt-6"


def test_anthropic_messages_tool_use_non_streaming() -> None:
    client, fake = make_client()
    res = client.post(
        "/v1/messages",
        headers={"x-api-key": "frly_provider_test"},
        json={
            "model": "claude-3-7-sonnet-20250219",
            "messages": [{"role": "user", "content": "Create game.html"}],
            "tools": [
                {
                    "name": "Write",
                    "description": "Write a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["file_path", "content"],
                    },
                }
            ],
            "stream": False,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["stop_reason"] == "tool_use"
    assert len(data["content"]) == 1
    assert data["content"][0]["type"] == "tool_use"
    assert data["content"][0]["name"] == "Write"
    assert data["content"][0]["input"] == {
        "file_path": "game.html",
        "content": "<h1>Minecraft</h1>",
    }


def test_anthropic_messages_tool_use_streaming() -> None:
    client, fake = make_client()
    res = client.post(
        "/v1/messages",
        headers={"x-api-key": "frly_provider_test"},
        json={
            "model": "claude-3-7-sonnet-20250219",
            "messages": [{"role": "user", "content": "Create game.html"}],
            "tools": [
                {
                    "name": "Write",
                    "description": "Write a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                    },
                }
            ],
            "stream": True,
        },
    )
    assert res.status_code == 200
    text = res.text
    assert "event: content_block_start" in text
    assert '"type":"tool_use"' in text
    assert '"name":"Write"' in text
    assert "event: content_block_delta" in text
    assert '"type":"input_json_delta"' in text
    assert "event: content_block_stop" in text
    assert '"stop_reason":"tool_use"' in text
    assert "event: message_stop" in text


def test_anthropic_messages_tool_result_in_history() -> None:
    client, fake = make_client()
    res = client.post(
        "/v1/messages",
        headers={"x-api-key": "frly_provider_test"},
        json={
            "model": "claude-3-7-sonnet-20250219",
            "messages": [
                {"role": "user", "content": "Create game.html"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_123",
                            "name": "Write",
                            "input": {"file_path": "game.html", "content": "test"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_123",
                            "content": "File created successfully",
                        }
                    ],
                },
            ],
            "stream": False,
        },
    )
    assert res.status_code == 200
    call = fake.responses.calls[-1]
    # Check that input contains function_call and function_call_output
    input_items = call["input"]
    call_items = [item for item in input_items if item.get("type") == "function_call"]
    output_items = [item for item in input_items if item.get("type") == "function_call_output"]
    assert len(call_items) == 1
    assert call_items[0]["name"] == "Write"
    assert len(output_items) == 1
    assert output_items[0]["output"] == "File created successfully"

