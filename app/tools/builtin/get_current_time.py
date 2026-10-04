"""Return the current UTC time — migrated from the legacy inline registry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.tools.base import Tool


async def _handler(_args: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    return json.dumps({"time": now.strftime("%I:%M %p UTC").lstrip("0")})


TOOL = Tool(
    name="get_current_time",
    description="Return the current UTC time when the user asks what time it is.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_handler,
    preamble="Let me check the time for you.",
    response_mode="full",   # user actually wants to hear the time
    tags=("utility",),
)
