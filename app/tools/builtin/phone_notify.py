"""phone_notify — push a notification/ping message to the paired phone."""
from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool
from app.tools.builtin._kdeconnect import cli_action


async def _handler(args: dict[str, Any]) -> str:
    message = str(args.get("message", "")).strip()
    if not message:
        return json.dumps({"error": "message is required"})
    result = await cli_action("--ping-msg", message)
    if result.startswith("[phone_error]"):
        return json.dumps({"error": result})
    return json.dumps({"ok": True})


TOOL = Tool(
    name="phone_notify",
    description=(
        "Push a short notification to the user's phone. Use for 'notify my phone', "
        "'send a note to my phone', 'remind me on my phone that…', "
        "'ping my phone with…'. The message appears as an Android notification."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The notification text to show on the phone. Keep short.",
            },
        },
        "required": ["message"],
    },
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("phone", "kdeconnect"),
)
