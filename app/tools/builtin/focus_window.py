"""
focus_window tool
-----------------
Bring a window matching a title substring to the foreground.
Case-insensitive substring match against every visible window title.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool


async def _handler(args: dict[str, Any]) -> str:
    query = args.get("title")
    if not isinstance(query, str) or not query.strip():
        return json.dumps({"error": "Missing 'title' argument."})
    query = query.strip().lower()

    try:
        import pygetwindow as gw
    except ImportError:
        return json.dumps({"error": "pygetwindow not installed."})

    try:
        wins = gw.getAllWindows()
    except Exception as exc:
        return json.dumps({"error": f"Enumeration failed: {exc}"})

    # Score: exact > startswith > substring
    candidates = []
    for w in wins:
        t = (w.title or "").strip()
        if not t:
            continue
        tl = t.lower()
        if tl == query:
            score = 3
        elif tl.startswith(query):
            score = 2
        elif query in tl:
            score = 1
        else:
            continue
        candidates.append((score, len(t), t, w))

    if not candidates:
        return json.dumps({"error": f"No window matched {query!r}."})

    candidates.sort(key=lambda x: (-x[0], x[1]))
    _, _, title, win = candidates[0]

    try:
        if getattr(win, "isMinimized", False):
            win.restore()
        win.activate()
    except Exception as exc:
        # activate() throws on some multi-monitor setups — try minimize+restore hack
        try:
            win.minimize()
            win.restore()
        except Exception:
            return json.dumps({"error": f"Could not focus {title!r}: {exc}"})

    return json.dumps({"ok": True, "focused": title})


TOOL = Tool(
    name="focus_window",
    description=(
        "Bring an existing Windows desktop window to the foreground by "
        "matching a substring of its title. Call this when the user says "
        "'switch to Chrome', 'bring VS Code to the front', 'go back to my "
        "browser', or wants to move between open apps. If the target app "
        "is NOT already open, use `open_app` instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": (
                    "Case-insensitive substring of the window title. Examples: "
                    "'chrome', 'vs code', 'notepad', 'settings'."
                ),
            },
        },
        "required": ["title"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "windows"),
)
