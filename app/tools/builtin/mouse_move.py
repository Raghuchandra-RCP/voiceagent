"""
mouse_move tool
---------------
Move the cursor to absolute coordinates without clicking.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool


async def _handler(args: dict[str, Any]) -> str:
    try:
        x = int(args.get("x"))
        y = int(args.get("y"))
    except (TypeError, ValueError):
        return json.dumps({"error": "x and y must be integer pixel coordinates."})

    duration = float(args.get("duration", 0.15))
    duration = max(0.0, min(duration, 2.0))

    try:
        import pyautogui
    except ImportError:
        return json.dumps({"error": "pyautogui not installed."})

    try:
        pyautogui.moveTo(x, y, duration=duration)
    except Exception as exc:
        return json.dumps({"error": f"Move failed: {type(exc).__name__}: {exc}"})

    return json.dumps({"ok": True, "x": x, "y": y})


TOOL = Tool(
    name="mouse_move",
    description=(
        "Move the mouse cursor to absolute screen coordinates without "
        "clicking. Useful for hovering over UI elements to reveal tooltips "
        "or menus. Use `click_at` if you actually want to click."
    ),
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X pixel."},
            "y": {"type": "integer", "description": "Y pixel."},
            "duration": {
                "type": "number",
                "description": "Seconds to animate the move (0–2, default 0.15).",
                "default": 0.15,
            },
        },
        "required": ["x", "y"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "mouse"),
)
