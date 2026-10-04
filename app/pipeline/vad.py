"""
app/pipeline/vad.py
-------------------
Voice activity detection using webrtcvad.

Feed 20 ms PCM16 mono frames at 16 kHz; get back True/False per frame.
The `UtteranceDetector` on top of it turns those decisions into "recording"
and "utterance ended" events for turn-based STT.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

VAD_SAMPLE_RATE = 16_000
VAD_FRAME_MS = 20
VAD_FRAME_SAMPLES = int(VAD_SAMPLE_RATE * VAD_FRAME_MS / 1000)  # 320
VAD_FRAME_BYTES = VAD_FRAME_SAMPLES * 2                          # 640 (int16)


class _RmsFallback:
    """Zero-dependency VAD fallback (RMS threshold) if webrtcvad is missing."""

    def __init__(self, threshold: int = 500):
        self.threshold = threshold

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:  # noqa: ARG002
        import numpy as np
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.int32)
        if samples.size == 0:
            return False
        rms = int(np.sqrt(np.mean(samples * samples)))
        return rms > self.threshold


def _make_vad(aggressiveness: int):
    try:
        import webrtcvad  # type: ignore
        v = webrtcvad.Vad(int(aggressiveness))
        logger.info("[vad] using webrtcvad (aggressiveness=%d)", aggressiveness)
        return v
    except ImportError:
        logger.warning("[vad] webrtcvad not installed — using RMS fallback.")
        return _RmsFallback()


class UtteranceDetector:
    """Accumulates PCM chunks into a single utterance based on VAD.

    Feed audio (any block size) via `.feed(pcm_bytes)`. When the detector
    decides the user has finished speaking, `.take_utterance()` returns the
    full PCM16 buffer (16 kHz mono) — or None if nothing is ready yet.
    """

    def __init__(
        self,
        aggressiveness: int = 2,
        silence_ms: int = 700,
        min_speech_ms: int = 200,
    ):
        self._vad = _make_vad(aggressiveness)
        self._silence_frames_needed = max(1, silence_ms // VAD_FRAME_MS)
        self._min_speech_frames = max(1, min_speech_ms // VAD_FRAME_MS)

        # Rolling frame buffer (bytes not yet fed to VAD in exact 20ms frames)
        self._pending = b""

        # Current utterance state
        self._speech_frames: list[bytes] = []
        self._silence_run = 0
        self._in_speech = False

        # Ready-to-consume utterance
        self._ready: Optional[bytes] = None

    def feed(self, pcm_bytes: bytes) -> None:
        """Add raw PCM16 16 kHz mono audio (any length)."""
        self._pending += pcm_bytes

        while len(self._pending) >= VAD_FRAME_BYTES:
            frame = self._pending[:VAD_FRAME_BYTES]
            self._pending = self._pending[VAD_FRAME_BYTES:]
            self._process_frame(frame)

    def _process_frame(self, frame: bytes) -> None:
        speech = self._vad.is_speech(frame, VAD_SAMPLE_RATE)

        if speech:
            self._speech_frames.append(frame)
            self._silence_run = 0
            self._in_speech = True
        elif self._in_speech:
            # Silence following speech — count towards end-of-utterance
            self._speech_frames.append(frame)  # keep tail for natural feel
            self._silence_run += 1
            if self._silence_run >= self._silence_frames_needed:
                self._finalize()

    def _finalize(self) -> None:
        if len(self._speech_frames) >= self._min_speech_frames:
            self._ready = b"".join(self._speech_frames)
        # discard whether it was accepted or too short
        self._speech_frames = []
        self._silence_run = 0
        self._in_speech = False

    def take_utterance(self) -> Optional[bytes]:
        """Return the completed utterance buffer, or None if nothing ready."""
        out = self._ready
        self._ready = None
        return out

    def reset(self) -> None:
        self._pending = b""
        self._speech_frames = []
        self._silence_run = 0
        self._in_speech = False
        self._ready = None
