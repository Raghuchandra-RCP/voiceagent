"""phone_send_text — send a text snippet to the phone (appears as shared text)."""
from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool
from app.tools.builtin._kdeconnect import cli_action


async def _handler(args: dict[str, Any]) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        return json.dumps({"error": "text is required"})
    result = await cli_action("--share-text", text)
    if result.startswith("[phone_error]"):
        return json.dumps({"error": result})
    return json.dumps({"ok": True})


TOOL = Tool(
    name="phone_send_text",
    description=(
        "Send a text snippet to the phone. Android shows an app picker so the "
        "user can paste it into a chat, note, or search. Use for "
        "'send this text to my phone', 'push these notes to my phone'. "
        "For copy-to-clipboard behavior use phone_send_clipboard instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text content to send.",
            },
        },
        "required": ["text"],
    },
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("phone", "kdeconnect"),
)
