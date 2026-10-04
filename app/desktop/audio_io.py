"""
app/desktop/audio_io.py
-----------------------
Cross-platform microphone input + speaker output for the CLI Jarvis.

MicStream   — asyncio-friendly async iterator of PCM16 chunks from the default mic.
Speaker     — persistent output stream at OpenAI-Realtime's 24 kHz PCM16 format.

We capture the mic at 16 kHz mono because:
  * OpenAI Realtime accepts 16 kHz PCM16 mono without resampling.
  * openWakeWord expects exactly 16 kHz mono PCM16.

Playback is at 24 kHz because OpenAI Realtime emits audio at 24 kHz.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

MIC_SAMPLE_RATE = 16_000
SPEAKER_SAMPLE_RATE = 24_000
CHANNELS = 1
DTYPE = "int16"

# 80 ms mic chunks (1280 samples at 16 kHz) — matches openWakeWord's block size.
MIC_BLOCK_SAMPLES = 1280
MIC_BLOCK_BYTES = MIC_BLOCK_SAMPLES * 2  # int16 = 2 bytes/sample


class MicStream:
    """Async iterator yielding raw PCM16 bytes chunks from the default input device."""

    def __init__(self, blocksize: int = MIC_BLOCK_SAMPLES):
        self._blocksize = blocksize
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stream: Optional[sd.RawInputStream] = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

        def _callback(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                logger.debug("[mic] status=%s", status)
            data = bytes(indata)
            if self._loop is not None:
                asyncio.run_coroutine_threadsafe(self._queue.put(data), self._loop)

        self._stream = sd.RawInputStream(
            samplerate=MIC_SAMPLE_RATE,
            blocksize=self._blocksize,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=_callback,
        )
        self._stream.start()
        logger.info(
            "[mic] listening — %d Hz, %d samples/block (%d ms)",
            MIC_SAMPLE_RATE, self._blocksize,
            int(self._blocksize * 1000 / MIC_SAMPLE_RATE),
        )

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.debug("[mic] stop error: %s", e)
            self._stream = None

    async def read(self) -> bytes:
        """Await the next PCM16 chunk from the mic."""
        return await self._queue.get()


class Speaker:
    """Persistent output stream for streaming PCM16 mono audio.

    Sample rate is set when `start(sample_rate)` is called so we can match
    whatever TTS voice is loaded (Piper Amy medium = 22050 Hz, etc.).

    Also tracks how many bytes we've fed since `reset_position()` and how
    long ago the first byte was written, so callers can wait for playback
    to actually drain (needed to prevent our own TTS from feeding back into
    the mic and being transcribed as user input).
    """

    def __init__(self):
        self._stream: Optional[sd.RawOutputStream] = None
        self._sample_rate: int = SPEAKER_SAMPLE_RATE
        self._bytes_written: int = 0
        self._first_write_monotonic: Optional[float] = None

    def start(self, sample_rate: int = SPEAKER_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=CHANNELS,
            dtype=DTYPE,
        )
        self._stream.start()
        logger.info("[speaker] output ready — %d Hz PCM16", sample_rate)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.debug("[speaker] stop error: %s", e)
            self._stream = None

    def play(self, pcm_bytes: bytes) -> None:
        """Push PCM16 mono bytes to the output device (rate = start(...) rate)."""
        if self._stream is None or not pcm_bytes:
            return
        try:
            import time
            if self._first_write_monotonic is None:
                self._first_write_monotonic = time.monotonic()
            self._bytes_written += len(pcm_bytes)
            self._stream.write(pcm_bytes)
        except Exception as e:
            logger.debug("[speaker] write error: %s", e)

    def silence_ms(self, ms: int) -> None:
        """Play `ms` milliseconds of silence — useful as a soft flush marker."""
        if self._stream is None or ms <= 0:
            return
        samples = int(self._sample_rate * ms / 1000)
        silence = np.zeros(samples, dtype=np.int16).tobytes()
        self.play(silence)

    def reset_position(self) -> None:
        """Zero the byte counter — call at the start of each TTS response."""
        self._bytes_written = 0
        self._first_write_monotonic = None

    def pending_playback_seconds(self) -> float:
        """How much longer the OS output buffer will be playing, in seconds.

        Returns 0 if nothing was written since the last `reset_position()`.
        """
        if self._bytes_written == 0 or self._first_write_monotonic is None:
            return 0.0
        import time
        # int16 mono → 2 bytes per sample.
        total_duration = self._bytes_written / (self._sample_rate * 2)
        elapsed = time.monotonic() - self._first_write_monotonic
        return max(0.0, total_duration - elapsed)
