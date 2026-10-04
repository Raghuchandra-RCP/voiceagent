"""
write_clipboard tool
--------------------
Copy a string to the Windows clipboard.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool


async def _handler(args: dict[str, Any]) -> str:
    text = args.get("text")
    if not isinstance(text, str):
        return json.dumps({"error": "Missing 'text' argument."})
    try:
        import pyperclip
    except ImportError:
        return json.dumps({"error": "pyperclip not installed."})
    try:
        pyperclip.copy(text)
    except Exception as exc:
        return json.dumps({"error": f"Clipboard write failed: {exc}"})
    return json.dumps({"ok": True, "length": len(text)})


TOOL = Tool(
    name="write_clipboard",
    description=(
        "Copy a string to the Windows clipboard so the user can paste it "
        "anywhere. Call this when the user says 'copy this', 'put this on "
        "my clipboard', or dictates content they want to reuse later."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to copy."},
        },
        "required": ["text"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "clipboard"),
)
