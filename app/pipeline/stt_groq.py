"""
app/pipeline/stt_groq.py
------------------------
Speech-to-text via Groq's hosted Whisper (whisper-large-v3-turbo).

Why this backend
================
- Free tier is very generous (~14 400 sec/day of audio) and requires no card
- Same accuracy as OpenAI Whisper large-v3 — dramatically better than the
  local `base.en` model, especially with accents and mixed English/Hindi
- Round-trip is ~200–400 ms — often faster than local `small.en` on CPU
- Streaming isn't needed since we already send one buffered utterance per
  turn (VAD gates it)

Failure handling is done by `stt.py` — this class just raises on error.
"""

from __future__ import annotations

import io
import logging
import wave

from app.config import get_settings

logger = logging.getLogger(__name__)


class GroqSTT:
    """Blocking Groq Whisper client. Same shape as `WhisperSTT`."""

    def __init__(self):
        s = get_settings()
        self._api_key = s.groq_api_key.strip()
        self._model = s.groq_stt_model
        # None → let Groq auto-detect (best for bilingual users).
        # Set to "en" / "te" in .env to lock it and shave a bit of latency.
        # Invalid codes fall back to auto-detect so a bad env value can
        # never break the pipeline.
        from app.pipeline.stt import _sanitise_language
        self._language = _sanitise_language(s.stt_language, source="groq")
        self._client = None

    def load(self) -> None:
        """Instantiate the Groq client (no network — cheap)."""
        if not self._api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Get a free key at "
                "https://console.groq.com/keys and add it to your .env."
            )
        try:
            from groq import Groq  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "The `groq` package is not installed. Run: pip install groq"
            ) from e

        self._client = Groq(api_key=self._api_key)
        logger.info(
            "[stt] groq ready (model=%s, language=%s)",
            self._model, self._language or "auto",
        )

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16_000) -> str:
        """Transcribe raw PCM16 mono to text. Returns '' on empty audio."""
        if self._client is None:
            raise RuntimeError("GroqSTT.load() must be called first.")
        if not pcm_bytes:
            return ""

        # Groq's audio endpoint expects a real audio file. Wrap the PCM in a
        # minimal in-memory WAV — no disk write, no ffmpeg.
        wav_bytes = _pcm16_to_wav(pcm_bytes, sample_rate=sample_rate)

        kwargs = {
            "file": ("utterance.wav", wav_bytes),
            "model": self._model,
            "response_format": "text",
            # `temperature=0` is the deterministic default; explicit for clarity.
            "temperature": 0,
        }
        if self._language:
            kwargs["language"] = self._language

        # SDK returns a str when response_format="text".
        result = self._client.audio.transcriptions.create(**kwargs)
        text = (result if isinstance(result, str) else getattr(result, "text", "")).strip()
        logger.debug(
            "[stt] groq (%.2fs audio) → %r",
            len(pcm_bytes) / (2 * sample_rate), text,
        )
        return text


def _pcm16_to_wav(pcm_bytes: bytes, *, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap raw PCM16LE samples in a WAV header (in-memory)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)          # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()
