"""
open_url tool
-------------
Open a URL in the user's default browser (or a specific one).

Kept separate from `open_app` because browser handling is finicky — this
lets the LLM pass any URL without worrying about the browser's alias.
"""

from __future__ import annotations

import json
import webbrowser
from typing import Any

from app.tools.base import Tool


def _normalize_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith(("http://", "https://", "file:", "mailto:")):
        return raw
    # Bare domain or search term → assume https
    if "." in raw and " " not in raw:
        return "https://" + raw
    # Fallback: treat as Google search
    from urllib.parse import quote_plus

    return "https://www.google.com/search?q=" + quote_plus(raw)


async def _handler(args: dict[str, Any]) -> str:
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        return json.dumps({"error": "Missing 'url' argument."})

    target = _normalize_url(url)
    new_window = bool(args.get("new_window", False))

    try:
        ok = webbrowser.open(target, new=(1 if new_window else 0))
        if not ok:
            return json.dumps({"error": f"Browser could not open {target}"})
        return json.dumps({"ok": True, "url": target})
    except Exception as exc:
        return json.dumps({"error": f"open_url failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="open_url",
    description=(
        "Open a URL, website, or search query in the default browser. "
        "Call this when the user says 'open <site>', 'go to <url>', 'search "
        "for <query>', 'pull up <site>', or asks to visit any web address. "
        "Accepts bare domains ('youtube.com'), full URLs, or free-text "
        "queries (which become a Google search)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": (
                    "URL, domain, or search query. Examples: "
                    "'https://github.com', 'youtube.com', 'weather in Hyderabad'."
                ),
            },
            "new_window": {
                "type": "boolean",
                "description": "If true, open in a new browser window.",
                "default": False,
            },
        },
        "required": ["url"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "web"),
)
