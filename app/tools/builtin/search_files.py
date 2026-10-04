"""
search_files tool
-----------------
Case-insensitive filename search across the user's common folders
(Desktop, Documents, Downloads). Returns absolute paths.

Kept simple on purpose: no Windows Search COM (which is finicky) and no
full-drive walk (slow, spooky). If the user asks for a specific folder we
pass it through.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.tools.base import Tool


def _default_roots() -> list[Path]:
    home = Path.home()
    roots = [home / "Desktop", home / "Documents", home / "Downloads"]
    return [r for r in roots if r.exists()]


async def _handler(args: dict[str, Any]) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return json.dumps({"error": "Missing 'query' argument."})
    query_lower = query.strip().lower()

    max_results = int(args.get("max_results", 20))
    max_results = max(1, min(max_results, 100))

    roots_arg = args.get("root")
    if isinstance(roots_arg, str) and roots_arg.strip():
        expanded = os.path.expandvars(os.path.expanduser(roots_arg.strip()))
        p = Path(expanded)
        if not p.exists():
            return json.dumps({"error": f"Root path does not exist: {expanded}"})
        roots = [p]
    else:
        roots = _default_roots()

    if not roots:
        return json.dumps({"error": "No searchable folders exist under your user home."})

    # Extension filter (optional): 'pdf' or '.pdf'
    ext = args.get("extension")
    ext_filter: str | None = None
    if isinstance(ext, str) and ext.strip():
        ext_filter = ext.strip().lower().lstrip(".")

    matches: list[dict[str, Any]] = []
    walked = 0
    WALK_CAP = 20000  # hard cap on entries scanned so this stays snappy

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip noisy virtualenv / build folders
            dirnames[:] = [
                d for d in dirnames
                if d not in {"node_modules", ".git", ".venv", "__pycache__", "venv", "env"}
                and not d.startswith(".")
            ]
            for name in filenames:
                walked += 1
                if walked > WALK_CAP:
                    break
                if query_lower not in name.lower():
                    continue
                if ext_filter and not name.lower().endswith("." + ext_filter):
                    continue
                full = Path(dirpath) / name
                try:
                    stat = full.stat()
                    matches.append({
                        "path": str(full),
                        "name": name,
                        "size": stat.st_size,
                        "modified": int(stat.st_mtime),
                    })
                except OSError:
                    continue
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results or walked > WALK_CAP:
                break
        if len(matches) >= max_results or walked > WALK_CAP:
            break

    # Sort newest-modified first
    matches.sort(key=lambda m: m.get("modified", 0), reverse=True)

    return json.dumps({
        "ok": True,
        "query": query,
        "count": len(matches),
        "results": matches,
        "scanned": walked,
    })


TOOL = Tool(
    name="search_files",
    description=(
        "Search for files by name across the user's Desktop, Documents, and "
        "Downloads folders (or a specific folder you provide). Returns "
        "matching absolute paths sorted by newest modified. Call this when "
        "the user says 'find my resume', 'where is my project X pdf', 'look "
        "for files named …', 'find that report I wrote yesterday', etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Substring to search filenames for (case-insensitive).",
            },
            "extension": {
                "type": "string",
                "description": "Optional file extension filter, e.g. 'pdf', 'docx'.",
            },
            "root": {
                "type": "string",
                "description": (
                    "Optional folder to search inside. Defaults to Desktop + "
                    "Documents + Downloads. Supports %USERPROFILE% and ~."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Max results to return (1–100, default 20).",
                "default": 20,
            },
        },
        "required": ["query"],
    },
    handler=_handler,
    preamble="",
    response_mode="full",
    tags=("desktop", "files"),
)
