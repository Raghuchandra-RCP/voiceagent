"""
app/tools/__init__.py
---------------------
Tool registry with auto-discovery.

At import time we walk every module under `app.tools.builtin`, import it,
and register any module-level attribute named `TOOL` (an instance of
`app.tools.base.Tool`).

Public API:
    get_tool_declarations() -> list[dict]     # feed into Gemini Tool(...)
    get_preamble(name)      -> str            # optional pre-tool utterance
    execute_tool(name, args) -> Awaitable[str] # invoke a tool by name
    list_tools()            -> list[str]      # for logging/debug
"""

from __future__ import annotations

import importlib
import json
import logging
import pkgutil
from typing import Any

from app.tools.base import Tool

logger = logging.getLogger(__name__)

# ── Registry state ────────────────────────────────────────────────────────────
_REGISTRY: dict[str, Tool] = {}


def _discover() -> None:
    """Import every submodule of `app.tools.builtin` and register its TOOL."""
    from app.tools import builtin  # local import — avoids circular refs

    for mod_info in pkgutil.iter_modules(builtin.__path__):
        full_name = f"{builtin.__name__}.{mod_info.name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:
            logger.error("[tools] Failed to import %s: %s", full_name, exc)
            continue

        tool = getattr(module, "TOOL", None)
        if tool is None:
            logger.debug("[tools] %s has no TOOL attribute — skipped.", full_name)
            continue
        if not isinstance(tool, Tool):
            logger.warning(
                "[tools] %s.TOOL is %s, expected Tool — skipped.",
                full_name, type(tool).__name__,
            )
            continue
        if tool.name in _REGISTRY:
            logger.warning("[tools] Duplicate tool name %r — overwriting.", tool.name)
        _REGISTRY[tool.name] = tool
        logger.info("[tools] Registered %r from %s", tool.name, full_name)


_discover()


# ── Public API ────────────────────────────────────────────────────────────────

def get_tool_declarations() -> list[dict[str, Any]]:
    """Return every registered tool as a Gemini FunctionDeclaration dict."""
    return [t.to_function_declaration() for t in _REGISTRY.values()]


def get_preamble(name: str) -> str:
    """Return the optional preamble utterance for a tool (empty if none)."""
    tool = _REGISTRY.get(name)
    return tool.preamble if tool else ""


def get_response_mode(name: str) -> str:
    """Return the response mode for a tool ('silent'|'toast'|'brief'|'full').

    Unknown tools default to 'brief' so the agent still acknowledges.
    """
    tool = _REGISTRY.get(name)
    return tool.response_mode if tool else "brief"


# Tools that mutate the desktop → screenshot cache must be dropped after they run.
_UI_MUTATING = frozenset({
    "click_at",
    "mouse_move",
    "type_text",
    "press_hotkey",
    "open_app",
    "open_url",
    "web_search",
    "focus_window",
    "system_control",
    "write_clipboard",
    "scroll",
    "window_action",
    "run_sequence",  # itself may run any of the above
})


async def execute_tool(name: str, args: dict[str, Any]) -> str:
    """
    Run a registered tool. Always returns a JSON string suitable for a
    Gemini `function_response` payload. Never raises — errors are
    packaged into the JSON payload so the model can speak them.

    Side effect: invalidates the screen cache after any tool that
    mutates desktop state (see `_UI_MUTATING`).
    """
    tool = _REGISTRY.get(name)
    if tool is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = await tool.handler(args or {})
    except Exception as exc:
        logger.exception("[tools] %s raised: %s", name, exc)
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    if name in _UI_MUTATING:
        # Import here to avoid a circular import at module load time.
        from app.tools import _screen_cache
        _screen_cache.invalidate()

    return result


def list_tools() -> list[str]:
    """Return sorted list of registered tool names (for logging/debug)."""
    return sorted(_REGISTRY.keys())
