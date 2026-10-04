"""
open_app tool
-------------
Launch a desktop application by friendly name, optionally with a URL / file
path passed as the first argument.

Resolution order for `name`:
  1. Alias table          — "vs code" → "vscode", "the browser" → "chrome" …
  2. Known-paths table    — fast, deterministic paths for common apps
  3. Start Menu scan      — glob %APPDATA%/…/Start Menu/Programs/**/*.lnk
                            so ANY installed app works (Cursor, Notion, Discord…)
  4. shutil.which(name)   — anything on PATH
  5. os.startfile(name)   — Windows App Paths registry, URI schemes, files

Never raises — always returns a JSON string the model can read aloud.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.tools.base import Tool

logger = logging.getLogger(__name__)

# ── Known apps ────────────────────────────────────────────────────────────────
# Values may include environment variables (%LOCALAPPDATA% etc.) — they're
# expanded via os.path.expandvars() before use. First existing path wins.
_KNOWN_APPS: dict[str, list[str]] = {
    "vscode": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%PROGRAMFILES%\Microsoft VS Code\Code.exe",
        "code",
    ],
    "chrome": [
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
    ],
    "opera": [
        r"%LOCALAPPDATA%\Programs\Opera\launcher.exe",
        r"%LOCALAPPDATA%\Programs\Opera\opera.exe",
        r"%PROGRAMFILES%\Opera\launcher.exe",
    ],
    "firefox": [
        r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe",
        r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe",
    ],
    "teams": [
        "ms-teams.exe",  # New Teams (WinUI) app alias
        r"%LOCALAPPDATA%\Microsoft\Teams\current\Teams.exe",  # classic Teams
        "msteams:",      # URI fallback via os.startfile
    ],
    "spotify": [
        r"%APPDATA%\Spotify\Spotify.exe",
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe",
    ],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe", "pwsh.exe"],
    "terminal": ["wt.exe", "powershell.exe"],
    "settings": ["ms-settings:"],
}

# Common speech / natural-language variants → canonical key.
# Kept lower-case; matched after .strip().lower().
_ALIASES: dict[str, str] = {
    # editors
    "visual studio code": "vscode",
    "vs code": "vscode",
    "code": "vscode",
    "code editor": "vscode",
    "the editor": "vscode",
    "my editor": "vscode",
    "my ide": "vscode",

    # browsers
    "google chrome": "chrome",
    "the browser": "chrome",
    "my browser": "chrome",
    "microsoft edge": "edge",
    "ms edge": "edge",
    "opera browser": "opera",
    "mozilla firefox": "firefox",

    # comms
    "microsoft teams": "teams",
    "ms teams": "teams",
    "teams call": "teams",

    # music
    "spotify music": "spotify",

    # Windows built-ins
    "windows terminal": "terminal",
    "the terminal": "terminal",
    "file explorer": "explorer",
    "windows explorer": "explorer",
    "note pad": "notepad",
    "windows settings": "settings",
    "system settings": "settings",
}


def _normalise(name: str) -> str:
    key = name.strip().lower()
    return _ALIASES.get(key, key)


def _resolve_known(name: str) -> str | None:
    """Return the first existing path/URI for a KNOWN app key, else None."""
    for candidate in _KNOWN_APPS.get(name, []):
        expanded = os.path.expandvars(candidate)
        # URI scheme (msteams:, ms-settings:) — hand to os.startfile
        if ":" in expanded and not Path(expanded).drive:
            if expanded.endswith(":") or "://" in expanded or expanded.count(":") == 1:
                return expanded
        if Path(expanded).is_file():
            return expanded
        which = shutil.which(expanded)
        if which:
            return which
    return None


# ── Start Menu fallback ───────────────────────────────────────────────────────
# Glob every .lnk under the user's & the system's Start Menu Programs folders
# so ANY installed app becomes reachable without pre-registration.

_START_MENU_DIRS = [
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
    os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
]


@lru_cache(maxsize=1)
def _index_start_menu() -> dict[str, str]:
    """Return {normalised_name: shortcut_path} for every .lnk in Start Menu.

    Cached — first call is slow, subsequent calls are free.
    """
    index: dict[str, str] = {}
    for root in _START_MENU_DIRS:
        if not os.path.isdir(root):
            continue
        try:
            for path in Path(root).rglob("*.lnk"):
                key = path.stem.strip().lower()
                # Keep the first hit; user shortcuts win over ProgramData
                index.setdefault(key, str(path))
        except Exception as exc:
            logger.debug("[open_app] start-menu scan skipped for %s: %s", root, exc)
    logger.debug("[open_app] indexed %d start-menu shortcuts", len(index))
    return index


def _resolve_start_menu(name: str) -> str | None:
    """Fuzzy-match `name` against Start Menu shortcut file names."""
    key = name.strip().lower()
    if not key:
        return None
    index = _index_start_menu()

    # 1) exact filename match
    if key in index:
        return index[key]
    # 2) prefix match (e.g. "cursor" → "Cursor.lnk", "vs code" → …)
    for k, v in index.items():
        if k.startswith(key) or key in k.split():
            return v
    # 3) substring match (last-resort, may pick "Uninstall Foo" — avoid those)
    for k, v in index.items():
        if key in k and "uninstall" not in k and "readme" not in k:
            return v
    return None


# ── Handler ───────────────────────────────────────────────────────────────────

async def _handler(args: dict[str, Any]) -> str:
    raw_name = str(args.get("name", "")).strip()
    url = args.get("url")
    if not raw_name:
        return json.dumps({"error": "Missing 'name' argument."})

    canonical = _normalise(raw_name)

    # 1) known-paths table
    resolved = _resolve_known(canonical)
    # 2) Start Menu fallback (both canonical and raw name)
    if resolved is None:
        resolved = _resolve_start_menu(canonical) or _resolve_start_menu(raw_name)
    # 3) PATH fallback
    if resolved is None:
        resolved = shutil.which(canonical) or shutil.which(raw_name)

    try:
        if resolved:
            # URI-style targets (msteams:, ms-settings:) — use os.startfile
            is_uri = ":" in resolved and not Path(resolved).drive and not resolved.lower().endswith(".exe")
            is_lnk = resolved.lower().endswith(".lnk")
            if is_uri or is_lnk:
                # os.startfile handles both URIs and .lnk correctly
                os.startfile(resolved)  # type: ignore[attr-defined]
                # For browsers via .lnk we can't pass the URL — fall through below.
                if url and is_lnk:
                    logger.info("[open_app] URL ignored for .lnk launch: %s", url)
                launched = resolved
            else:
                cmd: list[str] = [resolved]
                if url:
                    cmd.append(str(url))
                subprocess.Popen(cmd, close_fds=True)
                launched = resolved
        else:
            # Final fallback: hand raw name to Windows (App Paths, URIs, files)
            target = url if url else raw_name
            os.startfile(target)  # type: ignore[attr-defined]
            launched = target

        msg = f"Opened {raw_name}" + (f" at {url}" if url else "")
        return json.dumps({"ok": True, "launched": launched, "message": msg})
    except FileNotFoundError:
        return json.dumps({"error": f"Could not find application: {raw_name}"})
    except OSError as exc:
        return json.dumps({"error": f"Failed to open {raw_name}: {exc}"})


TOOL = Tool(
    name="open_app",
    description=(
        "Launch a desktop application on the user's Windows machine. Call this "
        "whenever the user expresses ANY intent to open, start, launch, run, use, "
        "work in, or switch to an app — phrased as a command ('open Chrome'), a "
        "request ('can you launch VS Code'), or an intention ('I need to do some "
        "changes in VS Code', 'I want to send a message on Teams'). "
        "Handles common apps (vscode, chrome, edge, opera, firefox, teams, spotify, "
        "notepad, calculator, explorer, terminal, settings) plus anything present "
        "in the user's Start Menu (Cursor, Notion, Discord, Slack, etc.). "
        "For browsers, optionally pass a `url` to open a specific site."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Application name. Use natural names — 'vscode', 'chrome', "
                    "'teams', 'notion', 'cursor', 'discord' all work."
                ),
            },
            "url": {
                "type": "string",
                "description": (
                    "Optional URL or file path to open with the app. Best used "
                    "with browsers (e.g. https://mail.google.com)."
                ),
            },
        },
        "required": ["name"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",   # you SEE the app open — no need to narrate
    tags=("desktop",),
)
