"""
app/tools/base.py
-----------------
Minimal Tool primitive used by the tool registry.

Every builtin tool defines a module-level `TOOL = Tool(...)`. The registry
in `app/tools/__init__.py` auto-discovers them at import time.

A Tool is intentionally a plain dataclass (no inheritance) so adding a new
tool is: create one file, drop a `TOOL = Tool(...)` at the bottom, done.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# Handler signature: async def handler(args: dict) -> str
# The return value is a JSON string sent back to the OpenAI Realtime API
# as the `function_call_output` payload. Keep it short — the model reads it.
ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]

# How Jarvis should acknowledge the tool's completion:
#   "silent" — no spoken reply, no text; play a local ding + rely on visible effect
#                 (best for actions like open_app, press_hotkey, type_text)
#   "toast"  — same as silent, but the frontend/CLI shows a text toast
#   "brief"  — tiny spoken ack ("done", "sent") — the default
#   "full"   — normal spoken reply, e.g. reading emails or answering a question
ResponseMode = str  # one of: "silent" | "toast" | "brief" | "full"


@dataclass(frozen=True)
class Tool:
    """A single voice-agent tool exposed to the LLM."""

    name: str
    description: str
    # JSON-Schema fragment for the OpenAI `function` tool `parameters` field.
    # Use {"type": "object", "properties": {}, "required": []} for no-args tools.
    parameters: dict[str, Any]
    handler: ToolHandler
    # Optional short phrase spoken *before* the tool runs so the user knows
    # something is happening. Empty string = no preamble.
    preamble: str = ""
    # How the agent should react after the tool completes. See ResponseMode above.
    # Default "brief" = tiny spoken ack. Use "silent" for actions with obvious
    # visible effect (open_app, type_text) — saves TTS spend and feels snappier.
    response_mode: ResponseMode = "brief"
    # Tags for future filtering (e.g. "desktop", "network"). Unused today.
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_function_declaration(self) -> dict[str, Any]:
        """Serialise as a Gemini `FunctionDeclaration` dict.

        Google's `google-genai` SDK accepts a plain dict via
        `types.FunctionDeclaration(**decl)` — no need for OpenAPI conversion,
        since our `parameters` are already valid JSON Schema.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
