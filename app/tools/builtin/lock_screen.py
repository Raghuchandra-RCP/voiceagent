"""
lock_screen tool
----------------
Lock the Windows session (equivalent to Win+L).

Uses user32.LockWorkStation via ctypes — no external deps.
"""

from __future__ import annotations

import ctypes
import json
from typing import Any

from app.tools.base import Tool


async def _handler(_args: dict[str, Any]) -> str:
    try:
        ok = bool(ctypes.windll.user32.LockWorkStation())
        if not ok:
            # LockWorkStation returns 0 on failure (e.g. Remote Desktop session)
            return json.dumps({"error": "LockWorkStation returned 0."})
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": f"lock_screen failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="lock_screen",
    description=(
        "Lock the Windows session (same as pressing Win+L). Use for 'lock "
        "my computer', 'lock the screen', 'lock it', 'I'm stepping away'."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "system"),
)
