from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Optional, Union
from urllib.parse import urlparse

from fastapi import WebSocket, WebSocketDisconnect

from .config import Settings
from .errors import ProviderError

logger = logging.getLogger(__name__)


class VoiceLiveSession:
    """Manages a bidirectional real-time audio/text bridge between a client WebSocket
    and Azure VoiceLive API.
    """

    def __init__(
        self,
        client_ws: WebSocket,
        settings: Settings,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> None:
        self.client_ws = client_ws
        self.settings = settings
        self.model = model or settings.azure_voicelive_model
        self.voice = voice or settings.azure_voicelive_voice
        self.instructions = instructions or settings.azure_voicelive_instructions
        self._closed = False
        self._active_response = False
        self._conn: Any = None

    async def run(self) -> None:
        from azure.core.credentials import AzureKeyCredential
        from azure.identity.aio import (
            ClientSecretCredential,
            DefaultAzureCredential,
        )
        from azure.ai.voicelive.aio import connect
        from azure.ai.voicelive.models import (
            AudioEchoCancellation,
            AudioNoiseReduction,
            AzureStandardVoice,
            InputAudioFormat,
            Modality,
            OutputAudioFormat,
            RequestSession,
            ServerVad,
        )

        credential: Any
        if self.settings.azure_voicelive_api_key.strip():
            credential = AzureKeyCredential(self.settings.azure_voicelive_api_key.strip())
        elif (
            self.settings.azure_tenant_id.strip()
            and self.settings.azure_client_id.strip()
            and self.settings.azure_client_secret.strip()
        ):
            credential = ClientSecretCredential(
                tenant_id=self.settings.azure_tenant_id.strip(),
                client_id=self.settings.azure_client_id.strip(),
                client_secret=self.settings.azure_client_secret.strip(),
            )
        else:
            credential = DefaultAzureCredential()

        endpoint = self.settings.azure_voicelive_endpoint
        agent_name = self.settings.azure_voicelive_agent_id.strip() or None
        project_name = self.settings.azure_voicelive_project_name.strip() or None

        connect_kwargs: dict[str, Any] = {
            "endpoint": endpoint,
            "credential": credential,
            "model": self.model,
        }

        # If an agent name is configured, both agent_name and project_name are passed
        if agent_name and project_name:
            connect_kwargs["agent_name"] = agent_name
            connect_kwargs["project_name"] = project_name

        try:
            async with connect(**connect_kwargs) as connection:
                self._conn = connection
                logger.info("VoiceLive session connected to %s", endpoint)

                # Configure initial session
                voice_config: Union[AzureStandardVoice, str]
                if "-" in self.voice or ":" in self.voice:
                    voice_config = AzureStandardVoice(name=self.voice)
                else:
                    voice_config = self.voice

                turn_detection = ServerVad(
                    threshold=0.5,
                    prefix_padding_ms=300,
                    silence_duration_ms=500,
                )

                session_config = RequestSession(
                    modalities=[Modality.TEXT, Modality.AUDIO],
                    instructions=self.instructions,
                    voice=voice_config,
                    input_audio_format=InputAudioFormat.PCM16,
                    output_audio_format=OutputAudioFormat.PCM16,
                    turn_detection=turn_detection,
                    input_audio_echo_cancellation=AudioEchoCancellation(),
                    input_audio_noise_reduction=AudioNoiseReduction(
                        type="azure_deep_noise_suppression"
                    ),
                )

                await connection.session.update(session=session_config)

                # Run both directions concurrently
                voicelive_to_client = asyncio.create_task(
                    self._forward_voicelive_to_client(connection)
                )
                client_to_voicelive = asyncio.create_task(
                    self._forward_client_to_voicelive(connection)
                )

                done, pending = await asyncio.wait(
                    [voicelive_to_client, client_to_voicelive],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        except Exception as exc:
            logger.exception("VoiceLive session error: %s", exc)
            if not self._closed:
                try:
                    await self.client_ws.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "error": {
                                    "message": f"Azure VoiceLive connection error: {exc}",
                                    "type": "server_error",
                                },
                            }
                        )
                    )
                except Exception:
                    pass
        finally:
            self._closed = True
            await credential.close()

    async def _forward_voicelive_to_client(self, connection: Any) -> None:
        try:
            async for event in connection:
                if self._closed:
                    break

                event_dict = event.as_dict() if hasattr(event, "as_dict") else {}
                event_type = event_dict.get("type") or getattr(event, "type", "")

                if event_type == "response.created":
                    self._active_response = True
                elif event_type in {"response.done", "response.cancelled"}:
                    self._active_response = False
                elif event_type == "input_audio_buffer.speech_started":
                    # User interrupted the AI
                    if self._active_response:
                        try:
                            await connection.response.cancel()
                        except Exception:
                            pass

                # Forward event payload to client
                text_payload = json.dumps(event_dict, separators=(",", ":"))
                await self.client_ws.send_text(text_payload)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.debug("Error forwarding from VoiceLive: %s", exc)

    async def _forward_client_to_voicelive(self, connection: Any) -> None:
        try:
            while not self._closed:
                message = await self.client_ws.receive()

                if message.get("type") == "websocket.disconnect":
                    break

                # Binary audio frames: PCM16 chunks
                if "bytes" in message and message["bytes"]:
                    raw_bytes = message["bytes"]
                    base64_audio = base64.b64encode(raw_bytes).decode("utf-8")
                    await connection.input_audio_buffer.append(audio=base64_audio)
                    continue

                # Text frames: JSON Realtime events
                text = message.get("text")
                if not text:
                    continue

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "input_audio_buffer.append":
                    audio = data.get("audio", "")
                    if audio:
                        await connection.input_audio_buffer.append(audio=audio)
                elif msg_type == "input_audio_buffer.commit":
                    await connection.input_audio_buffer.commit()
                elif msg_type == "input_audio_buffer.clear":
                    await connection.input_audio_buffer.clear()
                elif msg_type == "response.create":
                    response_kwargs = {}
                    if "response" in data:
                        response_kwargs = data["response"]
                    await connection.response.create(**response_kwargs)
                elif msg_type == "response.cancel":
                    await connection.response.cancel()
                elif msg_type == "conversation.item.create":
                    item = data.get("item", {})
                    await connection.conversation_item.create(item=item)
                elif msg_type == "session.update":
                    session = data.get("session", {})
                    await connection.session.update(session=session)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.debug("Error forwarding from client: %s", exc)


class VoiceLiveGateway:
    """Manages VoiceLive sessions for WebSocket endpoints."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_session(
        self,
        client_ws: WebSocket,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> VoiceLiveSession:
        return VoiceLiveSession(
            client_ws=client_ws,
            settings=self.settings,
            model=model,
            voice=voice,
            instructions=instructions,
        )
