"""
scroll tool
-----------
Scroll the mouse wheel up or down in the current window (or at a
specified pixel location).

Uses pyautogui.scroll — positive clicks scroll UP, negative DOWN.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool


async def _handler(args: dict[str, Any]) -> str:
    direction = str(args.get("direction", "down")).lower().strip()
    if direction not in ("up", "down"):
        return json.dumps({"error": "'direction' must be 'up' or 'down'."})

    try:
        amount = int(args.get("amount", 5))
    except (TypeError, ValueError):
        return json.dumps({"error": "'amount' must be an integer."})
    amount = max(1, min(100, amount))

    x = args.get("x")
    y = args.get("y")

    try:
        import pyautogui  # lazy
    except ImportError:
        return json.dumps({"error": "pyautogui not installed."})

    try:
        clicks = amount if direction == "up" else -amount
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            pyautogui.scroll(clicks, x=int(x), y=int(y))
        else:
            pyautogui.scroll(clicks)
        return json.dumps({"ok": True, "direction": direction, "amount": amount})
    except Exception as exc:
        return json.dumps({"error": f"scroll failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="scroll",
    description=(
        "Scroll the mouse wheel up or down in the focused window. Use for "
        "'scroll down', 'scroll up', 'scroll down a lot', 'scroll to the "
        "bottom'. Optionally provide x,y pixel coordinates to scroll at a "
        "specific place (useful for panels that only scroll under the cursor)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "Which way to scroll.",
            },
            "amount": {
                "type": "integer",
                "description": (
                    "How many wheel clicks (1–100). Default 5. Roughly: "
                    "3 = small nudge, 5 = normal, 15 = big jump."
                ),
                "default": 5,
            },
            "x": {"type": "integer", "description": "Optional pixel x to scroll at."},
            "y": {"type": "integer", "description": "Optional pixel y to scroll at."},
        },
        "required": ["direction"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "input"),
)
