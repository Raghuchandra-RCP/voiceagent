"""
app/desktop/wake.py
-------------------
"Hey Jarvis" wake-word detector using openWakeWord.

openWakeWord is an optional dependency (~250 MB with tflite-runtime + onnxruntime).
If it isn't installed, WakeDetector.available() returns False and the CLI falls
back to hotkey or always-on mode.

Install:  pip install openwakeword

The pretrained `hey_jarvis` model ships with the package.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class WakeDetector:
    """Frame-by-frame wake-word inference. Feed it 80 ms PCM16 blocks at 16 kHz."""

    def __init__(self, keyword: str = "hey_jarvis", threshold: float = 0.5):
        self.keyword = keyword
        self.threshold = threshold
        self._model = None

        try:
            # Lazy import so the CLI can start without openwakeword installed.
            from openwakeword.model import Model  # type: ignore

            self._model = Model(
                wakeword_models=[keyword],
                inference_framework="onnx",
            )
            logger.info("[wake] loaded model %r (threshold=%.2f)", keyword, threshold)
        except ImportError:
            logger.warning(
                "[wake] openwakeword not installed. Wake mode disabled. "
                "Install: pip install openwakeword"
            )
        except Exception as e:
            logger.warning("[wake] failed to load %r: %s", keyword, e)

    def available(self) -> bool:
        return self._model is not None

    def detect(self, pcm_bytes: bytes) -> bool:
        """Return True if the wake word fires on this ~80 ms chunk."""
        if self._model is None:
            return False
        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16)
            scores = self._model.predict(samples)
            score = scores.get(self.keyword, 0.0)
            if score >= self.threshold:
                logger.info("[wake] detected %r (score=%.2f)", self.keyword, score)
                return True
        except Exception as e:
            logger.debug("[wake] predict error: %s", e)
        return False

    def reset(self) -> None:
        """Clear internal audio buffer — call after every activation."""
        if self._model is not None:
            try:
                self._model.reset()
            except Exception as e:
                logger.debug("[wake] reset error: %s", e)
