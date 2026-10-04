"""phone_send_clipboard — push the PC clipboard to the phone."""
from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool
from app.tools.builtin._kdeconnect import cli_action


async def _handler(_args: dict[str, Any]) -> str:
    result = await cli_action("--send-clipboard")
    if result.startswith("[phone_error]"):
        return json.dumps({"error": result})
    return json.dumps({"ok": True, "detail": "clipboard pushed to phone"})


TOOL = Tool(
    name="phone_send_clipboard",
    description=(
        "Push whatever is currently on the Windows clipboard to the phone's "
        "clipboard. Use for 'send my clipboard to my phone', 'copy this to my "
        "phone', 'sync my clipboard'. The user then pastes on the phone."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("phone", "kdeconnect"),
)
