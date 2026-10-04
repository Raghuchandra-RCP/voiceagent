"""
app/pipeline/stt.py
-------------------
Speech-to-text with automatic failover.

Two backends are available:
  • `GroqSTT`     — hosted Whisper-large-v3-turbo (highest accuracy, ~200 ms)
  • `WhisperSTT`  — local faster-whisper (offline, works with no network)

The `STT` class picks a primary based on `settings.stt_backend`:
  - "auto"  (default): Groq if `GROQ_API_KEY` is set, else local
  - "groq" : Groq, fall back to local on error
  - "local": local only

Any failure from the primary (network, rate-limit, malformed response) causes
one automatic fallback to the local model for that utterance, so a lost Wi-Fi
signal or a Groq outage never crashes a turn.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

# ISO 639-1 codes accepted by Whisper (both Groq's large-v3-turbo and
# faster-whisper's tokenizer). Kept in sync with the tokenizer's own list.
_WHISPER_LANGS = frozenset({
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi",
    "fo", "fr", "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy",
    "id", "is", "it", "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb",
    "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
    "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
    "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi",
    "yi", "yo", "zh", "yue",
})


def _sanitise_language(raw: str, *, source: str) -> Optional[str]:
    """Return a valid Whisper language code, or None to auto-detect.

    Silently rejects anything not in the Whisper vocabulary (which is what
    happens when Whisper accidentally transcribes a language name into
    STT_LANGUAGE via a stray command — e.g. STT_LANGUAGE=caviar).
    """
    code = (raw or "").strip().lower()
    if not code:
        return None
    if code in _WHISPER_LANGS:
        return code
    logger.warning(
        "[stt] ignoring invalid STT_LANGUAGE=%r (%s) — using auto-detect. "
        "Valid codes: en, te, hi, es, fr, de, …",
        raw, source,
    )
    return None


class WhisperSTT:
    """Thin wrapper around faster-whisper for turn-based transcription."""

    def __init__(self):
        self._model = None
        s = get_settings()
        self._model_name = s.whisper_model
        self._device = self._resolve_device(s.whisper_device)
        self._compute_type = s.whisper_compute_type

    @staticmethod
    def _resolve_device(pref: str) -> str:
        if pref != "auto":
            return pref
        try:
            import torch  # type: ignore
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def load(self) -> None:
        """Load the Whisper model (blocking, ~1–3 s + one-time download)."""
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            ) from e

        logger.info(
            "[stt] loading local whisper %s (device=%s, compute=%s) …",
            self._model_name, self._device, self._compute_type,
        )
        self._model = WhisperModel(
            self._model_name,
            device=self._device,
            compute_type=self._compute_type,
        )
        logger.info("[stt] local whisper loaded.")

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16_000) -> str:
        """Transcribe raw PCM16 mono to text. Returns '' on empty audio."""
        if self._model is None:
            raise RuntimeError("WhisperSTT.load() must be called first.")
        if not pcm_bytes:
            return ""

        # faster-whisper expects float32 mono in [-1, 1]
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Respect an explicit STT_LANGUAGE if the user set one; else derive
        # from the model name (e.g. base.en → English-only). Invalid codes
        # (e.g. stray dictated words) fall back to auto-detect.
        s = get_settings()
        forced_lang = _sanitise_language(s.stt_language, source="local whisper")
        language = forced_lang or ("en" if self._model_name.endswith(".en") else None)

        segments, info = self._model.transcribe(
            audio,
            language=language,
            vad_filter=False,   # our own VAD already gated this utterance
            beam_size=1,        # greedy — fastest, plenty good for short commands
            no_speech_threshold=0.6,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.debug("[stt] local (%.2fs audio) → %r", len(audio) / sample_rate, text)
        return text


class STT:
    """Router: primary backend + automatic single-shot fallback to local."""

    def __init__(self):
        s = get_settings()
        mode = (s.stt_backend or "auto").strip().lower()
        has_groq = bool(s.groq_api_key.strip())

        if mode == "local":
            self._use_groq = False
        elif mode == "groq":
            if not has_groq:
                logger.warning(
                    "[stt] STT_BACKEND=groq but GROQ_API_KEY is empty — using local only."
                )
                self._use_groq = False
            else:
                self._use_groq = True
        else:  # "auto"
            self._use_groq = has_groq

        self._groq: Optional["GroqSTT"] = None
        self._local: Optional[WhisperSTT] = None

        if self._use_groq:
            from app.pipeline.stt_groq import GroqSTT
            self._groq = GroqSTT()

        # Local is loaded either as primary or as a fallback safety net.
        self._local = WhisperSTT()

    def load(self) -> None:
        # Order matters: Groq is cheap to init, but we want the local model
        # ready before we start taking traffic so the fallback path is warm.
        if self._groq is not None:
            try:
                self._groq.load()
            except Exception as exc:
                logger.error("[stt] groq init failed (%s) — dropping to local only.", exc)
                self._groq = None
                self._use_groq = False

        assert self._local is not None
        self._local.load()

        logger.info(
            "[stt] router ready (primary=%s, fallback=%s)",
            "groq" if self._use_groq else "local",
            "local" if self._use_groq else "(none)",
        )

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16_000) -> str:
        if not pcm_bytes:
            return ""

        if self._use_groq and self._groq is not None:
            try:
                return self._groq.transcribe(pcm_bytes, sample_rate=sample_rate)
            except Exception as exc:
                logger.warning(
                    "[stt] groq failed (%s: %s) — falling back to local whisper.",
                    type(exc).__name__, exc,
                )
                # Fall through to local for THIS utterance only. Groq stays
                # armed for the next turn — most failures (429, transient net)
                # clear quickly.

        assert self._local is not None
        return self._local.transcribe(pcm_bytes, sample_rate=sample_rate)

