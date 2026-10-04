"""
app/desktop/jarvis_cli.py
-------------------------
Command-line "Jarvis" front-end for the Voice Agent (local pipeline).

  python jarvis.py --mode always    # (default) mic always on
  python jarvis.py --mode hotkey    # press Ctrl+Space to talk (needs pynput)
  python jarvis.py --mode wake      # say "Hey Jarvis" (needs openwakeword)

Turn-based loop:
    mic  →  VAD  →  utterance PCM  →  LocalPipeline  →  Speaker
                                       (Whisper → LLM+tools → Piper)

Wake / hotkey gates whether the utterance is passed to the pipeline. After
each response the CLI stays ACTIVE for `follow_up_seconds`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Optional

from app.config import get_settings
from app.desktop.audio_feedback import play_ding
from app.desktop.audio_io import MIC_BLOCK_BYTES, MicStream, Speaker
from app.desktop.hotkey import HotkeyListener
from app.desktop.wake import WakeDetector
from app.pipeline.local import LocalPipeline
from app.pipeline.vad import UtteranceDetector

logger = logging.getLogger(__name__)

_DEFAULT_FOLLOW_UP_SECONDS = 8


class JarvisCLI:
    """Coordinates mic → VAD → local pipeline → speaker with wake/hotkey gating."""

    def __init__(
        self,
        *,
        mode: str = "always",
        follow_up_seconds: int = _DEFAULT_FOLLOW_UP_SECONDS,
        wake_word: str = "hey_jarvis",
    ):
        self.mode = mode
        self.follow_up_seconds = follow_up_seconds

        s = get_settings()
        self.mic = MicStream()
        self.speaker = Speaker()
        self.pipeline = LocalPipeline()
        self.vad = UtteranceDetector(
            aggressiveness=s.vad_aggressiveness,
            silence_ms=s.vad_silence_ms,
            min_speech_ms=s.vad_min_speech_ms,
        )
        self.hotkey = HotkeyListener(on_press=self._request_activate)
        self.wake = WakeDetector(keyword=wake_word) if mode == "wake" else None

        # State: "IDLE" | "ACTIVE" | "PROCESSING"
        # `always` mode starts ACTIVE and never returns to IDLE.
        self.state = "ACTIVE" if mode == "always" else "IDLE"

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._follow_up_task: Optional[asyncio.Task] = None
        self._activation_requested = False
        self._active_turn: Optional[asyncio.Task] = None

    # ── Entry ────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._banner()

        # Load models before opening the mic — first load can take a few seconds.
        try:
            print("[jarvis] loading models…")
            await self.pipeline.load()
        except Exception as e:
            logger.error("Model load failed: %s", e)
            return

        self.mic.start(self._loop)
        self.speaker.start(sample_rate=self.pipeline.tts_sample_rate)
        if self.mode != "always":
            self.hotkey.start()

        print(f"[jarvis] ready — state={self.state}")

        try:
            await self._mic_loop()
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n[jarvis] shutting down…")
        finally:
            await self._shutdown()

    # ── Main mic loop ────────────────────────────────────────────────────────

    async def _mic_loop(self) -> None:
        buffer = b""
        while True:
            chunk = await self.mic.read()
            buffer += chunk

            while len(buffer) >= MIC_BLOCK_BYTES:
                block = buffer[:MIC_BLOCK_BYTES]
                buffer = buffer[MIC_BLOCK_BYTES:]
                await self._process_block(block)

    async def _process_block(self, block: bytes) -> None:
        # Hotkey handoff (fires on pynput thread; drained on the loop).
        if self._activation_requested:
            self._activation_requested = False
            if self.state == "IDLE":
                await self._activate(reason="hotkey")

        if self.state == "PROCESSING":
            # Drop mic while we're speaking/thinking so our own voice + tool
            # side-effects don't get captured as user input.
            return

        if self.state == "IDLE":
            if self.wake is not None and self.wake.available():
                if self.wake.detect(block):
                    await self._activate(reason="wake")
            return

        # ACTIVE — feed VAD and run a turn on utterance end.
        self.vad.feed(block)
        utterance = self.vad.take_utterance()
        if utterance is not None:
            self._active_turn = asyncio.create_task(self._run_turn(utterance))

    # ── Turn handling ────────────────────────────────────────────────────────

    async def _run_turn(self, utterance: bytes) -> None:
        self._cancel_follow_up_timer()
        self.state = "PROCESSING"
        # Fresh byte counter so pending_playback_seconds() reflects THIS reply.
        self.speaker.reset_position()
        try:
            await self.pipeline.process_turn(
                utterance,
                on_transcript=self._on_transcript,
                on_assistant_text=self._on_assistant_text,
                on_tool_call=self._on_tool_call,
                on_audio_chunk=self._on_audio_chunk,
                on_audio_end=self._on_audio_end,
            )
        except Exception as e:
            logger.exception("[pipeline] turn failed: %s", e)
            print(f"\n[jarvis] error: {e}")
        finally:
            # Wait for the speaker's OS buffer to actually drain — otherwise
            # the tail of Jarvis's own TTS leaks into the mic and gets
            # transcribed as user input on the next turn (echo loop).
            pending = self.speaker.pending_playback_seconds()
            grace = 0.5  # extra buffer for room echo dissipation
            wait_for = pending + grace
            if wait_for > 0:
                try:
                    await asyncio.sleep(wait_for)
                except asyncio.CancelledError:
                    pass
            self.vad.reset()
            # Always come back to ACTIVE. Follow-up timer moves us to IDLE
            # after `follow_up_seconds` in wake/hotkey modes.
            self.state = "ACTIVE"
            self._start_follow_up_timer()

    async def _on_transcript(self, text: str) -> None:
        print(f"\nyou › {text}")

    async def _on_assistant_text(self, text: str) -> None:
        if text:
            print(f"jarvis › {text}")

    async def _on_tool_call(self, name: str, args: dict) -> None:
        arg_preview = ", ".join(f"{k}={v!r}" for k, v in args.items())
        print(f"  ⚙  {name}({arg_preview})")

    async def _on_audio_chunk(self, pcm: bytes) -> None:
        self.speaker.play(pcm)

    async def _on_audio_end(self) -> None:
        self.speaker.silence_ms(60)

    # ── Wake / hotkey / follow-up ────────────────────────────────────────────

    def _request_activate(self) -> None:
        """Called from pynput hotkey thread. Sets a flag; drained on loop."""
        self._activation_requested = True

    async def _activate(self, *, reason: str) -> None:
        logger.info("[state] IDLE → ACTIVE (%s)", reason)
        self.state = "ACTIVE"
        play_ding()
        self._cancel_follow_up_timer()
        self.vad.reset()
        if self.wake is not None:
            self.wake.reset()

    def _go_idle(self) -> None:
        if self.mode == "always" or self.state == "IDLE":
            return
        logger.info("[state] ACTIVE → IDLE (follow-up expired)")
        self.state = "IDLE"
        self.vad.reset()
        if self.wake is not None:
            self.wake.reset()

    def _start_follow_up_timer(self) -> None:
        if self.mode == "always":
            return
        self._cancel_follow_up_timer()
        assert self._loop is not None

        async def _sleep_then_idle():
            try:
                await asyncio.sleep(self.follow_up_seconds)
                self._go_idle()
            except asyncio.CancelledError:
                pass

        self._follow_up_task = self._loop.create_task(_sleep_then_idle())

    def _cancel_follow_up_timer(self) -> None:
        if self._follow_up_task and not self._follow_up_task.done():
            self._follow_up_task.cancel()
        self._follow_up_task = None

    # ── UI / lifecycle ───────────────────────────────────────────────────────

    def _banner(self) -> None:
        s = get_settings()
        # Lazy import to avoid startup ordering issues.
        from app.pipeline.gemini_keys import get_pool
        try:
            pool_health = get_pool().health_summary()
        except Exception as exc:  # pragma: no cover — defensive
            pool_health = f"(unavailable: {exc})"

        print("=" * 60)
        print(" JARVIS CLI — local Whisper + " + s.llm_model + " + Piper")
        print("=" * 60)
        print(f"  llm              : {s.llm_model}")
        print(f"  gemini keys      : {pool_health}")
        print(f"  whisper          : {s.whisper_model} ({s.whisper_device}/{s.whisper_compute_type})")
        print(f"  piper voice      : {os.path.basename(s.piper_voice_path)}")
        print(f"  mode             : {self.mode}")
        if self.mode == "wake":
            available = self.wake is not None and self.wake.available()
            print(f"  wake word        : hey_jarvis  ({'ready' if available else 'openwakeword NOT installed'})")
        if self.mode != "always":
            print(f"  follow-up window : {self.follow_up_seconds}s")
            print("  hotkey           : Ctrl+Space")
        print("  Press Ctrl+C to quit.")
        print("=" * 60)

    async def _shutdown(self) -> None:
        self._cancel_follow_up_timer()
        if self._active_turn and not self._active_turn.done():
            self._active_turn.cancel()
        self.hotkey.stop()
        self.mic.stop()
        self.speaker.stop()


# ── Entry helpers ─────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="jarvis", description="CLI Jarvis voice agent")
    default_mode = os.getenv("JARVIS_MODE", "always").lower()
    parser.add_argument(
        "--mode",
        choices=["always", "hotkey", "wake"],
        default=default_mode,
        help="Activation mode (default from JARVIS_MODE env var, else 'always').",
    )
    parser.add_argument(
        "--follow-up-seconds",
        type=int,
        default=int(os.getenv("JARVIS_FOLLOW_UP_SECONDS", _DEFAULT_FOLLOW_UP_SECONDS)),
        help="Seconds to stay ACTIVE after a response before returning to IDLE.",
    )
    parser.add_argument(
        "--wake-word",
        default=os.getenv("JARVIS_WAKE_WORD", "hey_jarvis"),
        help="openwakeword model name (default: hey_jarvis).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    # On Windows, the default ProactorEventLoop leaks noisy SSL/socket
    # AttributeError + "Event loop is closed" tracebacks during shutdown
    # because httpx (used by google-genai) tears its transports down after
    # the loop has already begun closing. The SelectorEventLoop shuts down
    # cleanly and nothing we use requires subprocess support in the loop.
    import sys
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except AttributeError:
            pass

    args = _parse_args(argv)
    cli = JarvisCLI(
        mode=args.mode,
        follow_up_seconds=args.follow_up_seconds,
        wake_word=args.wake_word,
    )
    try:
        asyncio.run(cli.run())
    except KeyboardInterrupt:
        pass
    return 0
