"""
read_clipboard tool
-------------------
Return whatever text is currently on the Windows clipboard.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool


async def _handler(_args: dict[str, Any]) -> str:
    try:
        import pyperclip
    except ImportError:
        return json.dumps({"error": "pyperclip not installed."})
    try:
        content = pyperclip.paste()
    except Exception as exc:
        return json.dumps({"error": f"Clipboard read failed: {exc}"})

    if not isinstance(content, str):
        content = str(content)

    preview = content if len(content) <= 2000 else content[:2000] + "…(truncated)"
    return json.dumps({"ok": True, "text": preview, "length": len(content)})


TOOL = Tool(
    name="read_clipboard",
    description=(
        "Return whatever text is currently on the Windows clipboard. Call "
        "this when the user says 'what's on my clipboard', 'read my "
        "clipboard', 'check what I just copied', or asks you to summarise / "
        "translate / act on their last copy."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_handler,
    preamble="",
    response_mode="full",
    tags=("desktop", "clipboard"),
)
