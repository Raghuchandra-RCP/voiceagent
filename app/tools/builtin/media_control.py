"""
media_control tool
------------------
Play / pause / next / previous / stop for whatever is playing media —
Spotify, YouTube (in browser), VLC, Windows Media Player, anything that
responds to standard Windows media keys.

Uses pyautogui to send the virtual media keys, which are dispatched to
whichever app currently owns media focus. No app-specific integration
needed.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool

# pyautogui key names → what they do
_ACTIONS: dict[str, str] = {
    "play_pause": "playpause",
    "play":       "playpause",   # single toggle key on Windows
    "pause":      "playpause",
    "next":       "nexttrack",
    "skip":       "nexttrack",
    "previous":   "prevtrack",
    "prev":       "prevtrack",
    "back":       "prevtrack",
    "stop":       "stop",
}


async def _handler(args: dict[str, Any]) -> str:
    action = str(args.get("action", "")).lower().strip()
    if not action:
        return json.dumps({"error": "Missing 'action'."})

    key = _ACTIONS.get(action)
    if key is None:
        return json.dumps({
            "error": f"Unknown action '{action}'. Supported: {sorted(_ACTIONS)}"
        })

    try:
        import pyautogui  # lazy
    except ImportError:
        return json.dumps({"error": "pyautogui not installed."})

    try:
        pyautogui.press(key)
        return json.dumps({"ok": True, "action": action})
    except Exception as exc:
        return json.dumps({"error": f"media_control failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="media_control",
    description=(
        "Control media playback (Spotify, YouTube, VLC, any app that "
        "responds to Windows media keys). Use for 'pause the music', "
        "'play', 'next song', 'skip', 'previous track', 'stop'. Works "
        "even when the media app is not the focused window."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(_ACTIONS.keys()),
                "description": "What to do: play_pause, next, previous, stop.",
            },
        },
        "required": ["action"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "media"),
)
