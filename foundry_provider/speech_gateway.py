from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .errors import ProviderError

VOICE_MAP = {
    "onyx": "en-US-OnyxTurboMultilingualNeural",
    "alloy": "en-US-AlloyTurboMultilingualNeural",
    "echo": "en-US-EchoTurboMultilingualNeural",
    "nova": "en-US-NovaTurboMultilingualNeural",
    "shimmer": "en-US-ShimmerTurboMultilingualNeural",
    "fable": "en-US-FableTurboMultilingualNeural",
}


class SpeechGateway:
    """Adapter around Azure Cognitive Services Speech SDK for text-to-speech synthesis."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve_voice(self, voice: str | None) -> str:
        if not voice:
            return self.settings.azure_speech_voice
        cleaned = voice.strip()
        lower = cleaned.lower()
        if lower in VOICE_MAP:
            return VOICE_MAP[lower]
        return cleaned

    def synthesize_speech(
        self,
        text: str,
        voice: str | None = None,
        response_format: str = "mp3",
        speed: float | None = 1.0,
    ) -> tuple[bytes, str]:
        if not self.settings.speech_ready:
            raise ProviderError(
                "Azure Speech service is not configured on this server.",
                status_code=503,
                code="speech_not_configured",
            )

        if not text or not text.strip():
            raise ProviderError(
                "The 'input' parameter cannot be empty.",
                status_code=400,
                code="invalid_request_error",
                param="input",
            )

        import azure.cognitiveservices.speech as speechsdk

        parsed = urlparse(self.settings.azure_speech_endpoint)
        base_endpoint = f"{parsed.scheme}://{parsed.netloc}"

        speech_config = speechsdk.SpeechConfig(
            subscription=self.settings.azure_speech_key,
            endpoint=base_endpoint,
        )

        resolved_voice = self.resolve_voice(voice)
        speech_config.speech_synthesis_voice_name = resolved_voice

        format_lower = (response_format or "mp3").lower().strip()
        if format_lower in {"wav", "wave"}:
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
            )
            media_type = "audio/wav"
        elif format_lower in {"ogg", "opus"}:
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Ogg24Khz16BitMonoOpus
            )
            media_type = "audio/ogg"
        elif format_lower in {"pcm", "raw"}:
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
            )
            media_type = "audio/pcm"
        else:
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio24Khz160KBitRateMonoMp3
            )
            media_type = "audio/mpeg"

        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=None,
        )

        # Apply speed adjustment if specified
        if speed and abs(speed - 1.0) > 0.05:
            rate_pct = f"{int((speed - 1.0) * 100):+d}%"
            escaped_text = (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            ssml = (
                f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xml:lang="en-US">'
                f'<voice name="{resolved_voice}">'
                f'<prosody rate="{rate_pct}">{escaped_text}</prosody>'
                f'</voice></speak>'
            )
            result = synthesizer.speak_ssml_async(ssml).get()
        else:
            result = synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            return bytes(result.audio_data), media_type
        elif result.reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            error_msg = details.error_details or str(details.reason)
            raise ProviderError(
                f"Azure Speech synthesis failed: {error_msg}",
                status_code=502,
                code="speech_synthesis_failed",
            )
        else:
            raise ProviderError(
                f"Azure Speech synthesis returned unexpected status: {result.reason}",
                status_code=502,
                code="speech_synthesis_failed",
            )
