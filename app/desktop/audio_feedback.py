"""
app/desktop/audio_feedback.py
-----------------------------
Local, non-blocking audio cues so silent tools still feel responsive.

`play_ding()` synthesises a short two-tone chime in-memory (no wav file to
ship) and plays it on the default output device. Fire-and-forget: if the
audio device is missing or `sounddevice`/`numpy` aren't installed, the
function silently no-ops so it never breaks the agent loop.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
_SAMPLE_RATE = 44_100
_DING_DURATION_S = 0.18         # total chime length
_DING_FREQS_HZ = (880.0, 1320.0)  # A5 + E6 \u2014 pleasant two-tone
_DING_VOLUME = 0.15             # 0.0-1.0; keep quiet so it doesn't startle


def _synth_ding() -> "any":
    """Return an int16 numpy array holding the ding waveform, or None on failure."""
    try:
        import numpy as np  # lazy
    except ImportError:
        return None

    t = np.linspace(0, _DING_DURATION_S, int(_SAMPLE_RATE * _DING_DURATION_S), endpoint=False)
    # Two overlapping sine tones with a short exponential decay envelope.
    envelope = np.exp(-t * 18.0)
    wave = np.zeros_like(t)
    for f in _DING_FREQS_HZ:
        wave += np.sin(2 * np.pi * f * t)
    wave = (wave / len(_DING_FREQS_HZ)) * envelope * _DING_VOLUME
    return (wave * 32767).astype(np.int16)


def _play_blocking(samples) -> None:
    try:
        import sounddevice as sd  # lazy
        sd.play(samples, samplerate=_SAMPLE_RATE, blocking=True)
    except Exception as exc:
        logger.debug("[audio_feedback] play failed: %s", exc)


def play_ding() -> None:
    """Play a short chime on the default output device. Never blocks, never raises."""
    samples = _synth_ding()
    if samples is None:
        return
    threading.Thread(target=_play_blocking, args=(samples,), daemon=True).start()


def notify(message: str) -> None:
    """Best-effort desktop toast. Falls back to stderr when no toast lib is present."""
    try:
        from plyer import notification  # lazy \u2014 optional dep
        notification.notify(title="Jarvis", message=message, timeout=3)
    except Exception:
        # Silent fallback so a missing plyer never breaks the agent.
        logger.info("[toast] %s", message)
