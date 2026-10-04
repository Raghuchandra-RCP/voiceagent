"""phone_call — open the phone's dialer with a number pre-filled (one tap to call)."""
from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool
from app.tools.builtin._contacts import resolve
from app.tools.builtin._kdeconnect import cli_action


async def _handler(args: dict[str, Any]) -> str:
    contact = str(args.get("contact", "")).strip()
    if not contact:
        return json.dumps({"error": "contact (name or phone number) is required"})

    number, err = resolve(contact)
    if err or not number:
        return json.dumps({"error": err or "could not resolve contact"})

    # Android registers `tel:` URLs → the KDE Connect share opens the dialer.
    result = await cli_action("--share", f"tel:{number}")
    if result.startswith("[phone_error]"):
        return json.dumps({"error": result})

    return json.dumps({
        "ok": True,
        "number": number,
        "note": "dialer opened on phone; tap the call button to place the call",
    })


TOOL = Tool(
    name="phone_call",
    description=(
        "Open the phone's dialer with a specific number pre-filled, ready to "
        "call with one tap. Accepts a contact name from contacts.json OR a "
        "raw phone number (E.164 preferred, e.g. +919876543210). "
        "Use for 'call mom', 'call plus nine one …', 'dial dad'. "
        "IMPORTANT: Android does NOT allow silent auto-dial — the user must "
        "tap the green call button. Tell them 'dialer is open, tap to call'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "contact": {
                "type": "string",
                "description": (
                    "Either a name saved in contacts.json (case-insensitive) "
                    "or a phone number. Numbers are auto-normalized."
                ),
            },
        },
        "required": ["contact"],
    },
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("phone", "kdeconnect", "call"),
)
