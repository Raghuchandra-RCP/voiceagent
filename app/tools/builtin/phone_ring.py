"""phone_ring — make the paired phone ring loudly."""
from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool
from app.tools.builtin._kdeconnect import cli_action


async def _handler(_args: dict[str, Any]) -> str:
    result = await cli_action("--ring")
    if result.startswith("[phone_error]"):
        return json.dumps({"error": result})
    return json.dumps({"ok": True, "detail": "phone is ringing"})


TOOL = Tool(
    name="phone_ring",
    description=(
        "Make the user's paired phone ring loudly, even if it's on silent. "
        "Use for 'ring my phone', 'find my phone', 'where's my phone', "
        "'make my phone ring'. Requires KDE Connect paired on Windows + Android."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_handler,
    preamble="Ringing your phone.",
    response_mode="brief",
    tags=("phone", "kdeconnect"),
)
