"""
Contact-book lookup for phone_call / phone_whatsapp.

Underscore prefix — not a tool, not registered by the auto-discovery loader.

Contacts live in contacts.json at the workspace root:

    {
      "contacts": {
        "mom": "+919876543210",
        "alex": "+14155551234"
      }
    }

`resolve()` accepts either a name (case-insensitive) or an already-formatted
phone number and returns a clean E.164-style string (leading '+' + digits).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_DIGITS_RE = re.compile(r"\d")
_ALLOWED_INPUT_RE = re.compile(r"^[+\d\s\-()]+$")
_CONTACTS_FILE = Path(__file__).resolve().parents[3] / "contacts.json"


def _load() -> dict[str, str]:
    if not _CONTACTS_FILE.exists():
        return {}
    try:
        raw = json.loads(_CONTACTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    contacts = raw.get("contacts", {}) if isinstance(raw, dict) else {}
    if not isinstance(contacts, dict):
        return {}
    return {str(k).strip().lower(): str(v).strip() for k, v in contacts.items() if v}


def _normalize_number(raw: str) -> str:
    """Strip formatting; keep leading '+' if present."""
    raw = raw.strip()
    has_plus = raw.startswith("+")
    digits = "".join(_DIGITS_RE.findall(raw))
    if not digits:
        return ""
    return ("+" + digits) if has_plus else digits


def _looks_like_number(s: str) -> bool:
    s = s.strip()
    if not s or not _ALLOWED_INPUT_RE.match(s):
        return False
    return len(_DIGITS_RE.findall(s)) >= 5


def resolve(query: str) -> tuple[Optional[str], Optional[str]]:
    """Return (E.164-ish number, error_message). Exactly one is None."""
    q = (query or "").strip()
    if not q:
        return None, "empty contact/number"

    # Direct number match — accept and normalize.
    if _looks_like_number(q):
        num = _normalize_number(q)
        return (num, None) if num else (None, "invalid number")

    # Name lookup (case-insensitive).
    book = _load()
    if not book:
        return None, (
            f"contact '{q}' not found and no contacts.json entries exist. "
            f"Add it to {_CONTACTS_FILE} or say the full phone number."
        )
    hit = book.get(q.lower())
    if not hit:
        available = ", ".join(sorted(book.keys())) or "(none)"
        return None, f"contact '{q}' not found. Known: {available}"

    num = _normalize_number(hit)
    if not num:
        return None, f"contact '{q}' has an invalid number in contacts.json"
    return num, None


def known_names() -> list[str]:
    return sorted(_load().keys())
