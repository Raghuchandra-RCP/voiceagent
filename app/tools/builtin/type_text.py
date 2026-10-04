"""
type_text tool
--------------
Type a string into the currently focused window.

Uses pyautogui.write (fast, ASCII) with a fallback to the clipboard +
paste for non-ASCII text (unicode, emoji, non-Latin scripts) since
pyautogui.write cannot emit those characters directly.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool


def _is_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


async def _handler(args: dict[str, Any]) -> str:
    text = args.get("text")
    if not isinstance(text, str) or not text:
        return json.dumps({"error": "Missing 'text' argument."})

    press_enter = bool(args.get("press_enter", False))
    clear_first = bool(args.get("clear_first", False))
    interval = float(args.get("interval", 0.01))

    try:
        import pyautogui  # lazy import
    except ImportError:
        return json.dumps({
            "error": "pyautogui is not installed. Run: pip install pyautogui",
        })

    try:
        # Optionally clear the focused input (Ctrl+A → Delete) before typing.
        # Use for search bars / address bars that already contain stale text.
        if clear_first:
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("delete")

        if _is_ascii(text):
            pyautogui.write(text, interval=interval)
        else:
            # Unicode fallback: clipboard + paste
            try:
                import pyperclip  # lazy import
            except ImportError:
                return json.dumps({
                    "error": (
                        "Non-ASCII text requires pyperclip. "
                        "Run: pip install pyperclip"
                    ),
                })
            previous = ""
            try:
                previous = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            # Best-effort clipboard restore (fire-and-forget)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass

        if press_enter:
            pyautogui.press("enter")

        preview = text if len(text) <= 60 else text[:57] + "..."
        return json.dumps({
            "ok": True,
            "typed": preview,
            "length": len(text),
            "cleared": clear_first,
        })
    except Exception as exc:
        return json.dumps({"error": f"Type failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="type_text",
    description=(
        "Type a string into whichever window is currently focused on Windows. "
        "Use after opening an app or clicking a text field. Supports optional "
        "Enter press at the end (useful for search bars, chat inputs). "
        "Set `clear_first: true` when refilling an input that already has "
        "text (search bar with a stale query, address bar, etc.) — this "
        "does Ctrl+A + Delete before typing, replacing what was there. "
        "Prefer this over chaining a separate press_hotkey step."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to type into the focused input.",
            },
            "press_enter": {
                "type": "boolean",
                "description": "If true, presses Enter after typing.",
                "default": False,
            },
            "clear_first": {
                "type": "boolean",
                "description": (
                    "If true, presses Ctrl+A then Delete before typing so "
                    "the new text REPLACES whatever was already in the "
                    "focused input. Use for stale search bars / address bars."
                ),
                "default": False,
            },
        },
        "required": ["text"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",   # typed text is visible in the target window
    tags=("desktop",),
)
