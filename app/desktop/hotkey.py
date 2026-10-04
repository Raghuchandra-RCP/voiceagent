"""
app/desktop/hotkey.py
---------------------
Global keyboard shortcut listener (Ctrl+Space by default) that forces Jarvis
into ACTIVE mode without needing a wake word.

pynput is a soft dependency — if it isn't installed, HotkeyListener silently
becomes a no-op so the CLI still runs in wake or always-on mode.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class HotkeyListener:
    """Cross-platform global hotkey. Invokes callback(loop) on the pynput thread."""

    def __init__(self, combo: str = "<ctrl>+<space>", on_press: Optional[Callable[[], None]] = None):
        self.combo = combo
        self._on_press = on_press
        self._listener = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """Start listening. Returns True on success, False if pynput unavailable."""
        try:
            from pynput import keyboard  # type: ignore
        except ImportError:
            logger.warning("[hotkey] pynput not installed — global hotkey disabled.")
            return False

        def _fire():
            if self._on_press is not None:
                try:
                    self._on_press()
                except Exception as e:
                    logger.error("[hotkey] callback error: %s", e)

        try:
            hotkeys = keyboard.GlobalHotKeys({self.combo: _fire})
            hotkeys.start()
            self._listener = hotkeys
            logger.info("[hotkey] listening for %s", self.combo)
            return True
        except Exception as e:
            logger.warning("[hotkey] failed to register %s: %s", self.combo, e)
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception as e:
                logger.debug("[hotkey] stop error: %s", e)
            self._listener = None
