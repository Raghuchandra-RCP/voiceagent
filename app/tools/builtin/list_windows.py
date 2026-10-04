"""
list_windows tool
-----------------
Return a snapshot of all visible top-level windows on the desktop.

Small payload so the LLM can pick one by title substring and pass it to
`focus_window`.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool


async def _handler(args: dict[str, Any]) -> str:
    try:
        import pygetwindow as gw
    except ImportError:
        return json.dumps({"error": "pygetwindow not installed."})

    include_minimized = bool(args.get("include_minimized", True))

    try:
        wins = gw.getAllWindows()
    except Exception as exc:
        return json.dumps({"error": f"Enumeration failed: {exc}"})

    out: list[dict[str, Any]] = []
    for w in wins:
        title = (w.title or "").strip()
        if not title:
            continue
        try:
            if w.isMinimized and not include_minimized:
                continue
        except Exception:
            pass
        try:
            info = {
                "title": title[:120],
                "minimized": bool(getattr(w, "isMinimized", False)),
                "maximized": bool(getattr(w, "isMaximized", False)),
                "active": bool(getattr(w, "isActive", False)),
            }
        except Exception:
            info = {"title": title[:120]}
        out.append(info)

    # De-dupe by title (Windows often reports ghost copies)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for w in out:
        if w["title"] in seen:
            continue
        seen.add(w["title"])
        deduped.append(w)

    return json.dumps({"ok": True, "windows": deduped[:50], "count": len(deduped)})


TOOL = Tool(
    name="list_windows",
    description=(
        "Return the titles of every open window on the Windows desktop. "
        "Call this when the user asks 'what's open', 'list my windows', "
        "'what apps do I have running', or when you need to know which "
        "window to focus before calling `focus_window`."
    ),
    parameters={
        "type": "object",
        "properties": {
            "include_minimized": {
                "type": "boolean",
                "description": "Include minimized windows (default true).",
                "default": True,
            },
        },
        "required": [],
    },
    handler=_handler,
    preamble="",
    response_mode="full",
    tags=("desktop", "windows"),
)
