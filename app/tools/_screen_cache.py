"""
app/tools/_screen_cache.py
--------------------------
Tiny in-process cache for the last screenshot + vision answer.

Purpose: cut LLM calls when the model asks `read_screen` twice in the same
turn (or with the same question) without any intervening desktop mutation.

Cache invalidation:
- Automatic TTL (`SCREEN_CACHE_TTL_S`, default 15 s)
- Explicit `invalidate()` — called by every tool that changes desktop state
  (click, mouse move, type, hotkey, open_app, open_url, focus_window,
  system_control)

Not thread-safe — Jarvis runs a single asyncio pipeline so all tool calls
happen serially on the event loop.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

SCREEN_CACHE_TTL_S = float(os.getenv("SCREEN_CACHE_TTL_S", "15"))


@dataclass
class _Entry:
    answer: str
    query: str
    ts: float
    image_bytes: int


_CACHE: Optional[_Entry] = None


def get(query: str) -> Optional[_Entry]:
    """Return the cached answer if fresh AND the query matches (case-insensitive)."""
    entry = _CACHE
    if entry is None:
        return None
    if time.monotonic() - entry.ts > SCREEN_CACHE_TTL_S:
        return None
    if entry.query.strip().lower() != query.strip().lower():
        return None
    return entry


def put(query: str, answer: str, image_bytes: int) -> None:
    global _CACHE
    _CACHE = _Entry(answer=answer, query=query, ts=time.monotonic(), image_bytes=image_bytes)


def invalidate() -> None:
    """Drop the cached screenshot — call after any UI-mutating tool."""
    global _CACHE
    _CACHE = None
