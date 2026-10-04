"""
window_action tool
------------------
Close, minimize, maximize, or restore a window — the active window by
default, or one matched by title substring.

Complements `focus_window` (which brings a window to the foreground).
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool

_ACTIONS = frozenset({"close", "minimize", "maximize", "restore"})


def _find_window(query: str | None):
    import pygetwindow as gw
    if not query:
        return gw.getActiveWindow()
    q = query.strip().lower()
    best = None
    best_score = -1
    for w in gw.getAllWindows():
        t = (w.title or "").strip()
        if not t:
            continue
        tl = t.lower()
        if tl == q:
            score = 3
        elif tl.startswith(q):
            score = 2
        elif q in tl:
            score = 1
        else:
            continue
        if score > best_score:
            best, best_score = w, score
    return best


async def _handler(args: dict[str, Any]) -> str:
    action = str(args.get("action", "")).lower().strip()
    if action not in _ACTIONS:
        return json.dumps({
            "error": f"'action' must be one of {sorted(_ACTIONS)}."
        })

    title = args.get("title")
    if title is not None and not isinstance(title, str):
        return json.dumps({"error": "'title' must be a string."})

    try:
        import pygetwindow as gw  # noqa: F401  (imported by _find_window)
    except ImportError:
        return json.dumps({"error": "pygetwindow not installed."})

    try:
        win = _find_window(title)
    except Exception as exc:
        return json.dumps({"error": f"Window lookup failed: {exc}"})

    if win is None:
        which = f"matching {title!r}" if title else "in focus"
        return json.dumps({"error": f"No window {which}."})

    try:
        if action == "close":
            win.close()
        elif action == "minimize":
            win.minimize()
        elif action == "maximize":
            win.maximize()
        elif action == "restore":
            win.restore()
        return json.dumps({"ok": True, "action": action, "title": win.title})
    except Exception as exc:
        return json.dumps({"error": f"window_action failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="window_action",
    description=(
        "Close, minimize, maximize, or restore a window on Windows. If "
        "'title' is omitted, acts on the currently focused window. Use for "
        "'close this', 'minimize this window', 'maximize Chrome', 'close "
        "Notepad', 'restore the browser'. Use focus_window to switch to a "
        "window instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(_ACTIONS),
                "description": "What to do to the window.",
            },
            "title": {
                "type": "string",
                "description": (
                    "Optional substring of the target window title. If "
                    "omitted, the currently focused window is used."
                ),
            },
        },
        "required": ["action"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "window"),
)
