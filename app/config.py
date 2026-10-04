"""
app/config.py
-------------
Central configuration for the local Jarvis pipeline.

Pipeline: local Whisper (STT) → Gemini 2.5 Flash (LLM+tools) → Piper (TTS)

Key env vars (see .env):
  - GEMINI_API_KEY:        needed for the LLM stage (Gemini 2.5 Flash)
  - LLM_MODEL:             default "gemini-2.5-flash"
  - LLM_THINKING_BUDGET:   Gemini 2.5 reasoning tokens (0 = disabled, faster)
  - WHISPER_MODEL:         faster-whisper model size ("tiny.en", "base.en", "small.en")
  - WHISPER_DEVICE:        "cpu" or "cuda" (auto-detected if unset)
  - WHISPER_COMPUTE_TYPE:  "int8" (cpu), "float16" (cuda)
  - PIPER_VOICE_PATH:      absolute or relative path to .onnx voice file
  - VAD_AGGRESSIVENESS:    webrtcvad 0–3 (higher = filters more non-speech)
  - VAD_SILENCE_MS:        silence after speech that ends an utterance (ms)
"""

from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings

_BASE_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BASE_DIR / ".env"
_DEFAULT_VOICE = _BASE_DIR / "models" / "en" / "en_US" / "amy" / "medium" / "en_US-amy-medium.onnx"


class Settings(BaseSettings):
    # ── API Keys ───────────────────────────────────────────────────────────────
    # Field names double as env-var names because Config.case_sensitive=False
    # maps `gemini_api_key` → env `GEMINI_API_KEY` automatically. No `env=`
    # kwarg needed (and Pydantic v2 dropped it from Field's public signature).
    #
    # Primary key. Additional keys (below) enable automatic failover when the
    # primary is rate-limited on the free tier (~5 req/min per key).
    gemini_api_key: str = Field(...)
    gemini_api_key_2: str = Field(default="")
    gemini_api_key_3: str = Field(default="")
    gemini_api_key_4: str = Field(default="")
    # Alternative: comma-separated list. Overrides the numbered slots if set.
    gemini_api_keys: str = Field(default="")

    def all_gemini_keys(self) -> list[tuple[str, str]]:
        """Return [(label, key), …] for every configured Gemini key, in priority order."""
        seen: set[str] = set()
        out: list[tuple[str, str]] = []

        def _add(label: str, key: str) -> None:
            key = (key or "").strip()
            if not key or key in seen:
                return
            seen.add(key)
            out.append((label, key))

        if self.gemini_api_keys.strip():
            for i, k in enumerate(self.gemini_api_keys.split(","), start=1):
                _add(f"GEMINI_API_KEYS[{i}]", k)

        _add("GEMINI_API_KEY", self.gemini_api_key)
        _add("GEMINI_API_KEY_2", self.gemini_api_key_2)
        _add("GEMINI_API_KEY_3", self.gemini_api_key_3)
        _add("GEMINI_API_KEY_4", self.gemini_api_key_4)
        return out

    # ── LLM (Google Gemini) ───────────────────────────────────────────────────
    llm_model: str = Field(default="gemini-flash-latest")
    llm_temperature: float = Field(default=0.2)
    llm_max_history: int = Field(default=20)
    # 0 disables Gemini 2.5 "thinking" for lowest latency (recommended for voice).
    llm_thinking_budget: int = Field(default=0)

    # ── STT (faster-whisper, local) ───────────────────────────────────────────
    # Router in app/pipeline/stt.py chooses primary:
    #   'auto'  → Groq if GROQ_API_KEY is set, else local
    #   'groq'  → Groq (with local fallback on error)
    #   'local' → local only
    stt_backend: str = Field(default="auto")
    # Optional ISO 639-1 language hint ("en", "hi", …). Empty = auto-detect.
    stt_language: str = Field(default="")

    # Groq-hosted Whisper (primary STT backend when key is present)
    groq_api_key: str = Field(default="")
    groq_stt_model: str = Field(default="whisper-large-v3-turbo")

    whisper_model: str = Field(default="base.en")
    whisper_device: str = Field(default="auto")
    whisper_compute_type: str = Field(default="int8")

    # ── TTS (Piper, local) ────────────────────────────────────────────────────
    piper_voice_path: str = Field(default=str(_DEFAULT_VOICE))

    # ── VAD (webrtcvad, turn detection) ───────────────────────────────────────
    vad_aggressiveness: int = Field(default=2)
    vad_silence_ms: int = Field(default=700)
    vad_min_speech_ms: int = Field(default=200)

    # ── Phone integration (KDE Connect) ───────────────────────────────────────
    # Leave device ID empty to auto-detect the first paired-and-reachable device
    # each call. Set explicitly to skip discovery latency (~200 ms).
    kde_device_id: str = Field(default="")
    # Binary name or absolute path. Default resolves via PATH.
    kde_cli_path: str = Field(default="kdeconnect-cli")

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton — safe to call anywhere."""
    return Settings()  # type: ignore[call-arg]  # env-populated by pydantic-settings


