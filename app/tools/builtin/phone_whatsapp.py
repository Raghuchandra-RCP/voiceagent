"""phone_whatsapp — open WhatsApp on the phone, optionally to a specific chat with a pre-filled message."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from app.tools.base import Tool
from app.tools.builtin._contacts import resolve
from app.tools.builtin._kdeconnect import cli_action


async def _handler(args: dict[str, Any]) -> str:
    contact = str(args.get("contact", "")).strip()
    message = str(args.get("message", "")).strip()

    # No contact → just open WhatsApp to whatever state it was in.
    if not contact:
        # `whatsapp://` scheme without a target just opens the app.
        result = await cli_action("--share", "whatsapp://")
        if result.startswith("[phone_error]"):
            return json.dumps({"error": result})
        return json.dumps({"ok": True, "detail": "WhatsApp opened on phone"})

    number, err = resolve(contact)
    if err or not number:
        return json.dumps({"error": err or "could not resolve contact"})

    # wa.me expects digits only, no '+'.
    wa_num = number.lstrip("+")

    # wa.me is the official click-to-chat URL — works even if the contact
    # isn't saved on the phone. Falls through to Play Store if WhatsApp is
    # not installed (extremely unlikely for the target user).
    if message:
        url = f"https://wa.me/{wa_num}?text={quote(message)}"
    else:
        url = f"https://wa.me/{wa_num}"

    result = await cli_action("--share", url)
    if result.startswith("[phone_error]"):
        return json.dumps({"error": result})

    return json.dumps({
        "ok": True,
        "number": number,
        "message_prefilled": bool(message),
        "note": (
            "WhatsApp opened to the chat with the message pre-filled; user taps send"
            if message
            else "WhatsApp opened to the chat"
        ),
    })


TOOL = Tool(
    name="phone_whatsapp",
    description=(
        "Open WhatsApp on the user's phone. Three modes:\n"
        "  • no args → just open the WhatsApp app.\n"
        "  • contact only → open the chat with that person.\n"
        "  • contact + message → open the chat with the message pre-filled (user taps send).\n"
        "Contact accepts a name from contacts.json (case-insensitive) OR a phone "
        "number in E.164 form (e.g. +919876543210). "
        "Use for 'open WhatsApp', 'WhatsApp mom', 'send Alex a WhatsApp saying …'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "contact": {
                "type": "string",
                "description": (
                    "Optional. Name from contacts.json or phone number. Omit to "
                    "just launch WhatsApp with no target."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "Optional message to pre-fill in the chat. Requires contact."
                ),
            },
        },
        "required": [],
    },
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("phone", "kdeconnect", "whatsapp"),
)
