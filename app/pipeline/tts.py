"""
app/pipeline/tts.py
-------------------
Local Piper text-to-speech.

Uses the .onnx voice under models/en/en_US/amy/medium/ by default. Piper's
sample rate depends on the voice — Amy medium is 22050 Hz. We expose that
via `sample_rate` so the Speaker can start at the right rate.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class PiperTTS:
    """Thin wrapper around the piper-tts pypi package."""

    def __init__(self, voice_path: Optional[str] = None):
        s = get_settings()
        self._voice_path = Path(voice_path or s.piper_voice_path)
        self._voice = None
        self.sample_rate: int = 22050  # overwritten on load

    def load(self) -> None:
        if not self._voice_path.exists():
            raise FileNotFoundError(
                f"Piper voice not found: {self._voice_path}\n"
                "Point PIPER_VOICE_PATH in .env to a .onnx file."
            )
        try:
            from piper import PiperVoice  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "piper-tts is not installed. Run: pip install piper-tts"
            ) from e

        logger.info("[tts] loading %s …", self._voice_path.name)
        self._voice = PiperVoice.load(str(self._voice_path))
        try:
            self.sample_rate = int(self._voice.config.sample_rate)
        except Exception:
            # Some builds expose it differently; fall back to Amy default.
            self.sample_rate = 22050
        logger.info("[tts] loaded (%d Hz).", self.sample_rate)

    def synthesize_stream(self, text: str) -> Iterator[bytes]:
        """Yield PCM16 mono bytes chunks at `self.sample_rate`.

        piper-tts >= 1.3 replaced `synthesize_stream_raw()` with `synthesize()`
        which yields `AudioChunk` objects. Each chunk exposes `.audio_int16_bytes`.
        """
        if self._voice is None:
            raise RuntimeError("PiperTTS.load() must be called first.")
        if not text or not text.strip():
            return
        for chunk in self._voice.synthesize(text):
            data = getattr(chunk, "audio_int16_bytes", None)
            if data:
                yield data
