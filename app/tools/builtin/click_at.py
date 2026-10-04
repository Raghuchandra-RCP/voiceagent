"""
click_at tool
-------------
Click at absolute screen coordinates. Almost always paired with `read_screen`
which returns coordinates of UI elements.
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

    button = str(args.get("button", "left")).lower()
    if button not in ("left", "right", "middle"):
        return json.dumps({"error": "button must be 'left', 'right', or 'middle'."})

    clicks = int(args.get("clicks", 1))
    if clicks < 1 or clicks > 3:
        return json.dumps({"error": "clicks must be 1, 2, or 3."})

    try:
        import pyautogui
    except ImportError:
        return json.dumps({"error": "pyautogui not installed."})

    try:
        pyautogui.click(x=x, y=y, clicks=clicks, button=button, interval=0.05)
    except Exception as exc:
        return json.dumps({"error": f"Click failed: {type(exc).__name__}: {exc}"})

    return json.dumps({"ok": True, "x": x, "y": y, "button": button, "clicks": clicks})


TOOL = Tool(
    name="click_at",
    description=(
        "Click the mouse at absolute screen pixel coordinates. Use this "
        "AFTER calling `read_screen` to locate a button or link — pass the "
        "coordinates that `read_screen` returned. Supports left/right/middle "
        "button and single/double/triple click."
    ),
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X pixel (0 = left edge)."},
            "y": {"type": "integer", "description": "Y pixel (0 = top edge)."},
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "default": "left",
            },
            "clicks": {
                "type": "integer",
                "description": "1=single, 2=double, 3=triple.",
                "default": 1,
            },
        },
        "required": ["x", "y"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "mouse"),
)
