"""
press_hotkey tool
-----------------
Press a keyboard shortcut in the currently focused window.

Accepts either:
  - A string like "ctrl+shift+i", "alt+tab", "win+d"
  - A list of key names like ["ctrl", "s"]

Uses pyautogui — imported lazily so a missing install fails with a helpful
message at call time rather than at server startup.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import Tool

# Aliases so the model can be sloppy about naming.
_KEY_ALIASES: dict[str, str] = {
    "control": "ctrl",
    "cmd": "ctrl",       # macOS-style → treat as ctrl on Windows
    "command": "ctrl",
    "option": "alt",
    "return": "enter",
    "esc": "escape",
    "windows": "win",
    "meta": "win",
    "super": "win",
    "space bar": "space",
    "spacebar": "space",
    "plus": "+",
    "minus": "-",
}


def _split_combo(combo: str) -> list[str]:
    # Support "+" or "-" separators; strip whitespace on each part.
    parts = [p.strip().lower() for p in combo.replace("-", "+").split("+") if p.strip()]
    return [_KEY_ALIASES.get(p, p) for p in parts]


async def _handler(args: dict[str, Any]) -> str:
    keys_raw = args.get("keys")
    if isinstance(keys_raw, str):
        keys = _split_combo(keys_raw)
    elif isinstance(keys_raw, list):
        keys = [_KEY_ALIASES.get(str(k).lower(), str(k).lower()) for k in keys_raw]
    else:
        return json.dumps({"error": "Missing 'keys' argument (string or list)."})

    if not keys:
        return json.dumps({"error": "No keys provided."})

    try:
        import pyautogui  # lazy import
    except ImportError:
        return json.dumps({
            "error": "pyautogui is not installed. Run: pip install pyautogui",
        })

    try:
        pyautogui.hotkey(*keys)
        return json.dumps({"ok": True, "pressed": "+".join(keys)})
    except Exception as exc:
        return json.dumps({"error": f"Hotkey failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="press_hotkey",
    description=(
        "Press a keyboard shortcut in the currently focused window on Windows. "
        "Use for actions like formatting a file (ctrl+shift+i), copying "
        "(ctrl+c), muting a Teams call (ctrl+shift+m), showing the desktop "
        "(win+d), switching windows (alt+tab), saving (ctrl+s)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "keys": {
                "type": "string",
                "description": (
                    "Key combination separated by '+', e.g. 'ctrl+shift+i', "
                    "'alt+tab', 'win+d'. Modifier keys: ctrl, alt, shift, win. "
                    "Case-insensitive."
                ),
            },
        },
        "required": ["keys"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",   # effect is immediately visible / audible
    tags=("desktop",),
)
