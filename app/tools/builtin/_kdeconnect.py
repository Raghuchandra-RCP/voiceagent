"""
Shared KDE Connect helpers for the phone_* tools.

Not a tool itself — has no module-level TOOL attribute, so the auto-discovery
registry in app/tools/__init__.py imports it but skips registration.

Wraps `kdeconnect-cli.exe` (bundled with the KDE Connect Windows app). All
public functions are async and never raise: on failure they return a
"[phone_error] …" string suitable for direct JSON-embedding.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Qt on Windows spews a harmless line for every CLI call.
_QT_NOISE = b"QEventDispatcherWin32::wakeUp: Failed to post a message"

_cached_device_id: Optional[str] = None


def _cli_path() -> str:
    return get_settings().kde_cli_path or "kdeconnect-cli"


async def _run(*args: str, timeout: float = 15.0) -> tuple[int, str, str]:
    """Run kdeconnect-cli, strip Qt noise from stderr, return (rc, stdout, stderr)."""
    cmd = [_cli_path(), *args]
    logger.debug("[kde] exec %s", " ".join(shlex.quote(a) for a in cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", f"{_cli_path()} not found on PATH"
    except Exception as exc:  # pragma: no cover — defensive
        return 1, "", f"{type(exc).__name__}: {exc}"

    # Filter the Qt noise line from stderr.
    stderr = "\n".join(
        line.decode("utf-8", errors="replace")
        for line in stderr_b.splitlines()
        if _QT_NOISE not in line
    ).strip()
    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    return proc.returncode or 0, stdout, stderr


async def resolve_device_id() -> Optional[str]:
    """Return a paired-and-reachable device ID. Cached for the process lifetime.

    Priority:
      1. KDE_DEVICE_ID from .env, if set.
      2. First device from `--list-available --id-only`.
      3. None (returned so callers can format a friendly error).
    """
    global _cached_device_id
    if _cached_device_id:
        return _cached_device_id

    configured = (get_settings().kde_device_id or "").strip()
    if configured:
        _cached_device_id = configured
        return configured

    rc, out, _err = await _run("--list-available", "--id-only", timeout=5.0)
    if rc == 0 and out:
        # First non-empty line
        first = next((line.strip() for line in out.splitlines() if line.strip()), "")
        if first:
            _cached_device_id = first
            return first
    return None


async def cli_action(*extra_args: str, timeout: float = 15.0) -> str:
    """Run a device-scoped kdeconnect-cli command; return status string for JSON.

    Handles device resolution and stderr filtering. Returns a short human
    string; callers wrap it in the tool's JSON payload.
    """
    dev = await resolve_device_id()
    if not dev:
        return "[phone_error] no paired-and-reachable KDE Connect device found. Is your phone on the same WiFi and KDE Connect running?"

    rc, out, err = await _run("-d", dev, *extra_args, timeout=timeout)
    if rc == 127:
        return "[phone_error] kdeconnect-cli not installed or not on PATH. Install KDE Connect on Windows."
    if rc == 124:
        return "[phone_error] kdeconnect-cli timed out."
    if rc != 0:
        return f"[phone_error] rc={rc} {err or 'unknown failure'}"
    return out or "ok"


def clear_device_cache() -> None:
    """Force re-detection on next call — used if the phone reconnects."""
    global _cached_device_id
    _cached_device_id = None
