"""phone_send_sms — send an SMS through the phone (requires SMS plugin enabled)."""
from __future__ import annotations

import json
import re
from typing import Any

from app.tools.base import Tool
from app.tools.builtin._kdeconnect import cli_action

_PHONE_RE = re.compile(r"^\+?[0-9\-\s()]{5,}$")


async def _handler(args: dict[str, Any]) -> str:
    message = str(args.get("message", "")).strip()
    destination = str(args.get("destination", "")).strip()
    if not message:
        return json.dumps({"error": "message is required"})
    if not destination or not _PHONE_RE.match(destination):
        return json.dumps({"error": "destination phone number is required (e.g. +911234567890)"})
    # KDE CLI expects +digits with no spaces; strip formatting characters.
    dest_clean = re.sub(r"[^\d+]", "", destination)
    result = await cli_action("--send-sms", message, "--destination", dest_clean)
    if result.startswith("[phone_error]"):
        return json.dumps({"error": result})
    return json.dumps({"ok": True, "to": dest_clean})


TOOL = Tool(
    name="phone_send_sms",
    description=(
        "Send an SMS through the user's phone. Requires the SMS plugin enabled "
        "on the Android KDE Connect app and default-SMS-app permission. "
        "Use for 'text mom that…', 'send an SMS to +91… saying…'. "
        "ALWAYS confirm the phone number with the user before sending."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The SMS body. Keep under 160 chars for single-message delivery.",
            },
            "destination": {
                "type": "string",
                "description": (
                    "Recipient phone number in E.164 or local format. Include country "
                    "code with a leading + when possible, e.g. '+919876543210'."
                ),
            },
        },
        "required": ["message", "destination"],
    },
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("phone", "kdeconnect", "sms"),
)
