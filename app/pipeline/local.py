"""
app/pipeline/local.py
---------------------
Local turn-based voice-agent pipeline:

    utterance PCM  →  Whisper (STT)  →  GPT-4o-mini (+tools)  →  Piper (TTS)  →  PCM

The CLI feeds one utterance at a time. This module owns Whisper, the LLM
client, and Piper — loads each once, then answers `process_turn()` calls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from app.pipeline.hallucination import is_whisper_hallucination
from app.pipeline.llm import LLM
from app.pipeline.stt import STT
from app.pipeline.tts import PiperTTS

logger = logging.getLogger(__name__)


# Event callbacks the CLI can plug in.
OnTranscript = Callable[[str], Awaitable[None]]              # user's transcribed text
OnAssistantText = Callable[[str], Awaitable[None]]           # final assistant reply
OnToolCall = Callable[[str, dict], Awaitable[None]]          # tool name + args
OnAudioChunk = Callable[[bytes], Awaitable[None]]            # streaming TTS PCM
OnAudioEnd = Callable[[], Awaitable[None]]                   # TTS finished


class LocalPipeline:
    """Owns Whisper + LLM + Piper. Call `.load()` once, then `.process_turn()`."""

    def __init__(self):
        self.stt = STT()
        self.llm = LLM()
        self.tts = PiperTTS()

    async def load(self) -> None:
        """Load models in a worker thread (blocking calls)."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.stt.load)
        await loop.run_in_executor(None, self.tts.load)

    @property
    def tts_sample_rate(self) -> int:
        return self.tts.sample_rate

    async def process_turn(
        self,
        utterance_pcm: bytes,
        *,
        on_transcript: Optional[OnTranscript] = None,
        on_assistant_text: Optional[OnAssistantText] = None,
        on_tool_call: Optional[OnToolCall] = None,
        on_audio_chunk: Optional[OnAudioChunk] = None,
        on_audio_end: Optional[OnAudioEnd] = None,
    ) -> None:
        """Full turn: transcribe → LLM (with tools) → synth → callback stream."""
        loop = asyncio.get_running_loop()

        # 1) STT — off the event loop (CPU-bound)
        text = await loop.run_in_executor(None, self.stt.transcribe, utterance_pcm)
        if not text:
            logger.debug("[pipeline] empty transcript — skipping turn.")
            return
        if is_whisper_hallucination(text):
            logger.info("[pipeline] dropping likely hallucination: %r", text)
            return
        if on_transcript:
            await on_transcript(text)

        # 2) LLM + tools
        reply = await self.llm.chat(text, on_tool_call=on_tool_call)
        if on_assistant_text:
            await on_assistant_text(reply)
        if not reply:
            return

        # 3) TTS — synthesize + stream chunks off-loop
        def _synth() -> list[bytes]:
            return list(self.tts.synthesize_stream(reply))

        chunks = await loop.run_in_executor(None, _synth)
        if on_audio_chunk:
            for chunk in chunks:
                await on_audio_chunk(chunk)
        if on_audio_end:
            await on_audio_end()

    def reset_conversation(self) -> None:
        self.llm.reset()
