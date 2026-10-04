"""
take_screenshot tool
--------------------
Capture the full desktop (all monitors merged) and save as PNG.

Distinct from `read_screen`, which is vision-QA over a screenshot.
This tool just saves the frame — useful when the user wants to keep
a copy, share it, or attach it to something.

Default save location: ~/Pictures/Screenshots/<timestamp>.png
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.tools.base import Tool


def _default_dir() -> Path:
    """Windows standard Screenshots folder under Pictures, with fallbacks."""
    home = Path.home()
    pictures = home / "Pictures"
    if pictures.is_dir():
        return pictures / "Screenshots"
    desktop = home / "Desktop"
    if desktop.is_dir():
        return desktop / "Screenshots"
    return home / "Screenshots"


async def _handler(args: dict[str, Any]) -> str:
    try:
        import mss           # lazy
        from PIL import Image  # noqa: F401  (mss returns raw pixels; PIL saves PNG)
    except ImportError:
        return json.dumps({"error": "mss/pillow not installed."})

    # Determine save path
    filename = args.get("filename")
    if isinstance(filename, str) and filename.strip():
        # User-provided (relative → dropped in default dir)
        p = Path(filename).expanduser()
        if not p.is_absolute():
            p = _default_dir() / p
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        p = _default_dir() / f"screenshot_{ts}.png"

    if p.suffix.lower() != ".png":
        p = p.with_suffix(".png")

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with mss.mss() as sct:
            # Monitor 0 = union of all monitors
            shot = sct.grab(sct.monitors[0])
            from PIL import Image
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.save(str(p), format="PNG", optimize=True)
        return json.dumps({"ok": True, "path": str(p)})
    except Exception as exc:
        return json.dumps({"error": f"take_screenshot failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="take_screenshot",
    description=(
        "Take a screenshot of the entire desktop and save it as a PNG file. "
        "Use for 'take a screenshot', 'grab a screenshot', 'save my screen'. "
        "Returns the saved file path. Default location: "
        "~/Pictures/Screenshots/. Distinct from read_screen — that "
        "one answers a question about what's on screen; this one saves a file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": (
                    "Optional file name or path. Relative paths are placed in "
                    "the default screenshots directory. '.png' is added if "
                    "missing. Omit for an auto-timestamped name."
                ),
            },
        },
        "required": [],
    },
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("desktop", "capture"),
)
