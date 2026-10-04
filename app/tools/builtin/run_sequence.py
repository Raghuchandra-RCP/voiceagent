"""
run_sequence tool
-----------------
Execute a batched list of desktop actions in ONE tool call — no LLM
round-trip between steps. Massively cuts token/quota usage when the plan
is clear (e.g. click somewhere → type → press Enter).

Supported action names inside the sequence match the individual tool
names: `click_at`, `mouse_move`, `type_text`, `press_hotkey`,
`open_app`, `open_url`, `focus_window`, `write_clipboard`,
`system_control`, `read_clipboard`, `search_files`, `get_current_time`,
plus a special `wait_ms` for inserting a pause.

Nested sequences and vision calls (`read_screen`) are intentionally
NOT supported here — always call `read_screen` yourself first, then
plan the sequence.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from app.tools.base import Tool

# Tools that are legal inside a sequence (fast + local + non-LLM)
_ALLOWED = {
    "click_at",
    "mouse_move",
    "type_text",
    "press_hotkey",
    "open_app",
    "open_url",
    "focus_window",
    "write_clipboard",
    "system_control",
    "read_clipboard",
    "search_files",
    "get_current_time",
    "list_windows",
}

# After any of these actions, the visible UI is about to change (page
# loading, app launching, window swapping). We auto-insert a small wait
# before the NEXT step unless the LLM already scheduled one, so a fast
# `click_at` doesn't fire before the target element renders.
_NAVIGATION_ACTIONS = {"open_url", "open_app", "focus_window"}
_NAV_WAIT_MS = int(os.getenv("SEQUENCE_NAV_WAIT_MS", "900"))


async def _run_one(action: str, args: dict[str, Any]) -> Any:
    # Import lazily to avoid circular refs at module load time
    from app.tools import execute_tool
    raw = await execute_tool(action, args)
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}


async def _handler(args: dict[str, Any]) -> str:
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        return json.dumps({"error": "Missing or empty 'steps' array."})

    stop_on_error = bool(args.get("stop_on_error", True))
    results: list[dict[str, Any]] = []
    aborted = False

    i = 0
    while i < len(steps):
        step = steps[i]
        if not isinstance(step, dict):
            results.append({"index": i, "error": "step must be an object"})
            if stop_on_error:
                aborted = True
                break
            i += 1
            continue

        action = str(step.get("action", "")).strip()
        step_args = step.get("args") if isinstance(step.get("args"), dict) else {}

        if action == "wait_ms":
            ms = int(step_args.get("ms", 200))
            ms = max(0, min(ms, 5000))
            await asyncio.sleep(ms / 1000.0)
            results.append({"index": i, "action": "wait_ms", "ok": True, "ms": ms})
            i += 1
            continue

        if action not in _ALLOWED:
            results.append({"index": i, "action": action, "error": f"disallowed action {action!r}"})
            if stop_on_error:
                aborted = True
                break
            i += 1
            continue

        try:
            out = await _run_one(action, step_args)
            results.append({"index": i, "action": action, "result": out})
            if stop_on_error and isinstance(out, dict) and out.get("error"):
                aborted = True
                break
        except Exception as exc:
            results.append({"index": i, "action": action, "error": f"{type(exc).__name__}: {exc}"})
            if stop_on_error:
                aborted = True
                break

        # ── Auto-wait after navigation ────────────────────────────────────
        # If we just navigated somewhere AND the next step is a click/type
        # (not already a wait), insert a synthetic pause so the target UI
        # has time to render before we interact with it.
        if action in _NAVIGATION_ACTIONS and i + 1 < len(steps):
            next_step = steps[i + 1]
            next_action = ""
            if isinstance(next_step, dict):
                next_action = str(next_step.get("action", "")).strip()
            if next_action and next_action != "wait_ms":
                await asyncio.sleep(_NAV_WAIT_MS / 1000.0)
                results.append({
                    "index": i,
                    "action": "auto_wait_ms",
                    "ok": True,
                    "ms": _NAV_WAIT_MS,
                    "reason": f"post-{action} render grace",
                })

        i += 1

    return json.dumps({
        "ok": not aborted,
        "aborted": aborted,
        "ran": len(results),
        "results": results,
    })


TOOL = Tool(
    name="run_sequence",
    description=(
        "Execute an ordered batch of desktop actions in ONE call — much "
        "faster and cheaper than calling tools one at a time. Use this "
        "whenever the plan is clear from a single glance at the screen. "
        "\n\nEach step is {\"action\": <tool name>, \"args\": {...}}. "
        "Allowed actions: click_at, mouse_move, type_text, press_hotkey, "
        "open_app, open_url, focus_window, write_clipboard, "
        "system_control, read_clipboard, search_files, get_current_time, "
        "list_windows. Special: {\"action\":\"wait_ms\",\"args\":{\"ms\":300}} "
        "to pause between steps. \n\n"
        "NOTE: read_screen is NOT allowed inside a sequence — call it "
        "yourself first to gather info, then plan the sequence. Stops on "
        "first error unless `stop_on_error` is false."
    ),
    parameters={
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "description": "Ordered list of actions to execute.",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Tool name or 'wait_ms'.",
                        },
                        "args": {
                            "type": "object",
                            "description": "Arguments to pass to the tool.",
                        },
                    },
                    "required": ["action"],
                },
            },
            "stop_on_error": {
                "type": "boolean",
                "description": "Abort remaining steps on first failure (default true).",
                "default": True,
            },
        },
        "required": ["steps"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "batch"),
)
