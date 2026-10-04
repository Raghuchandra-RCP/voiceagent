"""phone_share — share a URL or a local file to the paired phone."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.base import Tool
from app.tools.builtin._kdeconnect import cli_action


def _looks_like_url(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("ftp://")


async def _handler(args: dict[str, Any]) -> str:
    target = str(args.get("target", "")).strip()
    if not target:
        return json.dumps({"error": "target (URL or file path) is required"})

    # Expand ~ and resolve for local files; leave URLs untouched.
    if not _looks_like_url(target):
        p = Path(target).expanduser()
        if not p.exists():
            return json.dumps({"error": f"file not found: {p}"})
        target = str(p.resolve())

    result = await cli_action("--share", target)
    if result.startswith("[phone_error]"):
        return json.dumps({"error": result})
    return json.dumps({"ok": True, "shared": target})


TOOL = Tool(
    name="phone_share",
    description=(
        "Share a URL or a local file to the user's phone. URLs open in the "
        "phone's browser; files land in the phone's Downloads. Use for "
        "'send this link to my phone', 'send this file to my phone', "
        "'share https://... to my phone'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": (
                    "A URL (http/https) or an absolute/relative local file path. "
                    "Local paths are expanded and must exist."
                ),
            },
        },
        "required": ["target"],
    },
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("phone", "kdeconnect"),
)
