"""
note tool
---------
Append and read persistent voice notes.

Storage: a single markdown file at ~/Documents/jarvis-notes.md
(configurable via env var JARVIS_NOTES_PATH).

Each note is a bullet with an ISO-8601 timestamp — human-friendly to
open in any editor, and easy for the LLM to summarise later.

Actions:
  - add      → append a new note
  - list     → return the most recent N notes (default 10)
  - search   → substring match, return matching notes
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from app.tools.base import Tool


def _notes_path() -> Path:
    override = os.environ.get("JARVIS_NOTES_PATH")
    if override:
        return Path(override).expanduser()
    docs = Path.home() / "Documents"
    base = docs if docs.is_dir() else Path.home()
    return base / "jarvis-notes.md"


def _timestamp() -> str:
    # Local time, human-readable but sortable
    return time.strftime("%Y-%m-%d %H:%M:%S")


# Matches a note line: "- [YYYY-MM-DD HH:MM:SS] text"
_NOTE_LINE = re.compile(r"^-\s+\[(?P<ts>[\d\- :]+)\]\s+(?P<text>.*)$")


def _read_notes(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    out: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _NOTE_LINE.match(line)
        if m:
            out.append({"ts": m.group("ts"), "text": m.group("text").strip()})
    return out


async def _handler(args: dict[str, Any]) -> str:
    action = str(args.get("action", "add")).lower().strip()
    path = _notes_path()

    if action == "add":
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            return json.dumps({"error": "Missing 'text' for action 'add'."})
        line = f"- [{_timestamp()}] {text.strip()}\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            return json.dumps({"ok": True, "action": "add", "path": str(path)})
        except Exception as exc:
            return json.dumps({"error": f"note add failed: {type(exc).__name__}: {exc}"})

    if action == "list":
        try:
            limit = int(args.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(100, limit))
        try:
            notes = _read_notes(path)
        except Exception as exc:
            return json.dumps({"error": f"note list failed: {type(exc).__name__}: {exc}"})
        return json.dumps({
            "ok": True,
            "action": "list",
            "count": len(notes),
            "notes": notes[-limit:],
        })

    if action == "search":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return json.dumps({"error": "Missing 'query' for action 'search'."})
        q = query.strip().lower()
        try:
            notes = _read_notes(path)
        except Exception as exc:
            return json.dumps({"error": f"note search failed: {type(exc).__name__}: {exc}"})
        matches = [n for n in notes if q in n["text"].lower()]
        return json.dumps({
            "ok": True,
            "action": "search",
            "query": query,
            "count": len(matches),
            "notes": matches[-20:],  # cap for TTS sanity
        })

    return json.dumps({"error": f"Unknown action '{action}'. Use add | list | search."})


TOOL = Tool(
    name="note",
    description=(
        "Persistent voice notes stored in a single markdown file. Use for "
        "'take a note: <text>', 'remember that <text>', 'what did I note "
        "recently?', 'find my notes about <topic>'. Actions: add (default) "
        "saves a new note, list returns the most recent N, search finds "
        "notes matching a substring. Storage path is ~/Documents/"
        "jarvis-notes.md (override with JARVIS_NOTES_PATH env var)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "search"],
                "description": "Which operation to perform.",
                "default": "add",
            },
            "text": {
                "type": "string",
                "description": "The note body (required for action='add').",
            },
            "query": {
                "type": "string",
                "description": "Substring to match (required for action='search').",
            },
            "limit": {
                "type": "integer",
                "description": "Max notes returned by 'list' (1–100, default 10).",
                "default": 10,
            },
        },
        "required": ["action"],
    },
    handler=_handler,
    preamble="",
    response_mode="brief",
    tags=("notes", "memory"),
)
