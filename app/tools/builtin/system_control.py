"""
system_control tool
-------------------
Volume / brightness / mute / sleep control for Windows.

Skip shutdown/restart intentionally — sleep is the reversible choice.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
from typing import Any

from app.tools.base import Tool


# ── Volume via pycaw ─────────────────────────────────────────────────────────
def _get_volume():
    """Return an IAudioEndpointVolume interface (raises if pycaw unavailable)."""
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


def _volume_set(percent: int) -> dict[str, Any]:
    percent = max(0, min(100, int(percent)))
    v = _get_volume()
    v.SetMasterVolumeLevelScalar(percent / 100.0, None)
    return {"volume": percent}


def _volume_step(delta: int) -> dict[str, Any]:
    v = _get_volume()
    current = int(round(v.GetMasterVolumeLevelScalar() * 100))
    return _volume_set(current + delta)


def _mute_set(mute: bool) -> dict[str, Any]:
    v = _get_volume()
    v.SetMute(1 if mute else 0, None)
    return {"muted": mute}


def _mute_toggle() -> dict[str, Any]:
    v = _get_volume()
    new_state = not bool(v.GetMute())
    v.SetMute(1 if new_state else 0, None)
    return {"muted": new_state}


# ── Brightness via screen_brightness_control ─────────────────────────────────
def _brightness_set(percent: int) -> dict[str, Any]:
    import screen_brightness_control as sbc

    percent = max(0, min(100, int(percent)))
    sbc.set_brightness(percent)
    return {"brightness": percent}


def _brightness_step(delta: int) -> dict[str, Any]:
    import screen_brightness_control as sbc

    current_list = sbc.get_brightness()
    current = current_list[0] if isinstance(current_list, list) and current_list else 50
    return _brightness_set(current + delta)


# ── Sleep ────────────────────────────────────────────────────────────────────
def _sleep_now() -> dict[str, Any]:
    # SetSuspendState(hibernate=False, force=False, wakeup_disabled=False)
    try:
        ctypes.windll.powrprof.SetSuspendState(0, 0, 0)
        return {"sleeping": True}
    except Exception:
        # Fallback via rundll32
        subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            shell=False,
        )
        return {"sleeping": True}


# ── Handler dispatcher ───────────────────────────────────────────────────────
async def _handler(args: dict[str, Any]) -> str:
    action = str(args.get("action", "")).lower().strip()
    if not action:
        return json.dumps({"error": "Missing 'action'."})

    try:
        if action == "volume_up":
            step = int(args.get("step", 10))
            result = _volume_step(step)
        elif action == "volume_down":
            step = int(args.get("step", 10))
            result = _volume_step(-step)
        elif action == "volume_set":
            level = args.get("level")
            if not isinstance(level, (int, float)):
                return json.dumps({"error": "volume_set needs 'level' 0–100."})
            result = _volume_set(int(level))
        elif action == "mute":
            result = _mute_set(True)
        elif action == "unmute":
            result = _mute_set(False)
        elif action == "mute_toggle":
            result = _mute_toggle()
        elif action == "brightness_up":
            step = int(args.get("step", 10))
            result = _brightness_step(step)
        elif action == "brightness_down":
            step = int(args.get("step", 10))
            result = _brightness_step(-step)
        elif action == "brightness_set":
            level = args.get("level")
            if not isinstance(level, (int, float)):
                return json.dumps({"error": "brightness_set needs 'level' 0–100."})
            result = _brightness_set(int(level))
        elif action == "sleep":
            result = _sleep_now()
        else:
            return json.dumps({
                "error": f"Unknown action {action!r}.",
                "allowed": [
                    "volume_up", "volume_down", "volume_set",
                    "mute", "unmute", "mute_toggle",
                    "brightness_up", "brightness_down", "brightness_set",
                    "sleep",
                ],
            })
    except Exception as exc:
        return json.dumps({"error": f"{action} failed: {type(exc).__name__}: {exc}"})

    return json.dumps({"ok": True, "action": action, **result})


TOOL = Tool(
    name="system_control",
    description=(
        "Control Windows system settings: volume, mute, brightness, or put "
        "the laptop to sleep. Actions: 'volume_up'/'volume_down' (with "
        "optional 'step' 1–100, default 10), 'volume_set' (needs 'level' "
        "0–100), 'mute'/'unmute'/'mute_toggle', 'brightness_up'/"
        "'brightness_down' (with 'step'), 'brightness_set' (needs 'level'), "
        "and 'sleep'. NOTE: shutdown/restart are intentionally NOT "
        "supported — use sleep instead. Call this when the user says 'turn "
        "up the volume', 'mute', 'make it brighter', 'go to sleep', etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "volume_up", "volume_down", "volume_set",
                    "mute", "unmute", "mute_toggle",
                    "brightness_up", "brightness_down", "brightness_set",
                    "sleep",
                ],
                "description": "Which system control action to run.",
            },
            "level": {
                "type": "integer",
                "description": "0–100 target for *_set actions.",
            },
            "step": {
                "type": "integer",
                "description": "Amount to increment/decrement for *_up/*_down.",
                "default": 10,
            },
        },
        "required": ["action"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "system"),
)
