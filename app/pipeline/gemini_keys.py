"""
app/pipeline/gemini_keys.py
---------------------------
Rotating pool of Gemini API keys with automatic failover.

Motivation: the free Gemini tier is rate-limited per key (currently ~5 req/min
on the flash models). By registering multiple free keys we can transparently
fail over when one is exhausted or rejected.

Behaviour
=========
- Keys are tried in the order given.
- A key that returns 429 (RESOURCE_EXHAUSTED) or 503 is *cooled down* for
  `COOLDOWN_S` seconds before it's tried again.
- A key that returns 401/403 (auth / suspended) or 400 INVALID_ARGUMENT
  is marked *permanently bad* for this process.
- After all keys are exhausted, we sleep briefly and try the least-recently
  failed key one more time before raising.

The pool is a process-global singleton — every part of the app (LLM chat,
`read_screen` vision) shares the same rotation state so they cooperate.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, TypeVar

from google import genai

logger = logging.getLogger(__name__)

# How long a 429/503-ed key stays out of rotation before we retry it (seconds).
COOLDOWN_S = float(os.getenv("GEMINI_KEY_COOLDOWN_S", "60"))

# Max total attempts across all keys for a single logical call.
MAX_ATTEMPTS = int(os.getenv("GEMINI_MAX_ATTEMPTS", "6"))

# When every key is on cooldown, how long to wait before trying the "best" one.
ALL_EXHAUSTED_WAIT_S = float(os.getenv("GEMINI_ALL_EXHAUSTED_WAIT_S", "5"))

T = TypeVar("T")


@dataclass
class _KeyState:
    key: str
    label: str                     # "GEMINI_API_KEY", "GEMINI_API_KEY_2", …
    cooldown_until: float = 0.0    # monotonic timestamp
    permanently_bad: bool = False
    last_error: str = ""
    _client: genai.Client | None = field(default=None, repr=False)

    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self.key)
        return self._client

    def masked(self) -> str:
        k = self.key
        if len(k) <= 8:
            return "***"
        return f"{k[:4]}…{k[-4:]}"


class KeyPool:
    def __init__(self, keys: list[tuple[str, str]]):
        """keys: list of (label, api_key) tuples, tried in order."""
        if not keys:
            raise ValueError("KeyPool requires at least one API key")
        self._states: list[_KeyState] = [_KeyState(key=k, label=l) for l, k in keys]
        self._idx: int = 0  # index of currently-preferred key
        self._lock = asyncio.Lock()
        logger.info(
            "[gemini-keys] pool initialised with %d key(s): %s",
            len(self._states),
            ", ".join(f"{s.label}={s.masked()}" for s in self._states),
        )

    def _available(self) -> list[_KeyState]:
        now = time.monotonic()
        return [s for s in self._states if not s.permanently_bad and s.cooldown_until <= now]

    def _pick(self) -> _KeyState | None:
        avail = self._available()
        if not avail:
            return None
        # Prefer the current index if it's still available, otherwise the first.
        cur = self._states[self._idx]
        if cur in avail:
            return cur
        chosen = avail[0]
        self._idx = self._states.index(chosen)
        return chosen

    def _rotate_from(self, state: _KeyState) -> None:
        # Move idx to the next available key (round-robin).
        n = len(self._states)
        start = self._states.index(state)
        for step in range(1, n + 1):
            cand = self._states[(start + step) % n]
            if not cand.permanently_bad and cand.cooldown_until <= time.monotonic():
                self._idx = self._states.index(cand)
                return
        # None available — leave idx as-is; caller will handle wait.

    async def call(self, fn: Callable[[genai.Client], Awaitable[T]]) -> T:
        """Run `fn(client)` with automatic key rotation on quota/auth errors.

        `fn` must be an async function that takes a `genai.Client` and returns
        a result. It will be retried with a different key if the current one
        fails with a retriable error.
        """
        attempts = 0
        last_exc: Exception | None = None

        while attempts < MAX_ATTEMPTS:
            attempts += 1
            async with self._lock:
                state = self._pick()

            if state is None:
                # All keys cooling down. Wait briefly, then pick the one whose
                # cooldown expires soonest.
                soonest = min(
                    (s for s in self._states if not s.permanently_bad),
                    key=lambda s: s.cooldown_until,
                    default=None,
                )
                if soonest is None:
                    dead = ", ".join(s.label for s in self._states if s.permanently_bad) or "(none)"
                    raise RuntimeError(
                        f"All {len(self._states)} Gemini API key(s) are permanently disabled ({dead}). "
                        f"Add a working key to your .env as GEMINI_API_KEY / GEMINI_API_KEY_2 / … "
                        f"or a comma-separated GEMINI_API_KEYS list. Last error: {last_exc}"
                    )
                wait = max(0.5, min(ALL_EXHAUSTED_WAIT_S, soonest.cooldown_until - time.monotonic()))
                logger.warning(
                    "[gemini-keys] all keys on cooldown — waiting %.1fs for %s",
                    wait, soonest.label,
                )
                await asyncio.sleep(wait)
                async with self._lock:
                    soonest.cooldown_until = 0.0  # force it eligible
                    self._idx = self._states.index(soonest)
                continue

            try:
                return await fn(state.client())
            except Exception as exc:
                last_exc = exc
                kind = _classify(exc)
                state.last_error = f"{type(exc).__name__}: {exc}"[:200]

                if kind == "quota":
                    state.cooldown_until = time.monotonic() + COOLDOWN_S
                    logger.warning(
                        "[gemini-keys] %s hit quota (429) — cooling down %ds. Rotating.",
                        state.label, int(COOLDOWN_S),
                    )
                    async with self._lock:
                        self._rotate_from(state)
                    continue

                if kind == "auth":
                    state.permanently_bad = True
                    logger.error(
                        "[gemini-keys] %s permanently disabled (auth/invalid): %s",
                        state.label, state.last_error,
                    )
                    async with self._lock:
                        self._rotate_from(state)
                    continue

                if kind == "transient":
                    # 5xx / network — brief cooldown, try next key.
                    state.cooldown_until = time.monotonic() + 5.0
                    logger.warning(
                        "[gemini-keys] %s transient error — rotating. %s",
                        state.label, state.last_error,
                    )
                    async with self._lock:
                        self._rotate_from(state)
                    continue

                # Non-retriable (validation error in *our* request, etc.) — bubble up.
                raise

        raise RuntimeError(
            f"Gemini call failed after {MAX_ATTEMPTS} attempts. Last error: {last_exc}"
        )

    def status(self) -> list[dict]:
        now = time.monotonic()
        return [
            {
                "label": s.label,
                "key": s.masked(),
                "permanently_bad": s.permanently_bad,
                "cooldown_remaining_s": max(0.0, round(s.cooldown_until - now, 1)),
                "last_error": s.last_error,
                "current": (i == self._idx),
            }
            for i, s in enumerate(self._states)
        ]

    def usable_count(self) -> int:
        """Number of keys that are not permanently disabled."""
        return sum(1 for s in self._states if not s.permanently_bad)

    def total_count(self) -> int:
        return len(self._states)

    def health_summary(self) -> str:
        """Short one-line health string safe to print in a banner."""
        usable = self.usable_count()
        total = self.total_count()
        bad = [s.label for s in self._states if s.permanently_bad]
        parts = [f"{usable}/{total} usable"]
        if bad:
            parts.append(f"disabled: {', '.join(bad)}")
        return ", ".join(parts)


def _classify(exc: Exception) -> str:
    """Return 'quota' | 'auth' | 'transient' | 'fatal'."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    msg = str(exc).upper()

    if code == 429 or "RESOURCE_EXHAUSTED" in msg or "QUOTA" in msg or "RATE" in msg:
        return "quota"
    if code in (401, 403) or "PERMISSION_DENIED" in msg or "UNAUTHENTICATED" in msg or "API KEY NOT VALID" in msg or "API_KEY_INVALID" in msg:
        return "auth"
    if code == 400 and ("API KEY" in msg or "INVALID_ARGUMENT" in msg and "KEY" in msg):
        return "auth"
    if code and 500 <= int(code) < 600:
        return "transient"
    if "UNAVAILABLE" in msg or "DEADLINE_EXCEEDED" in msg or "INTERNAL" in msg:
        return "transient"
    return "fatal"


# ─── Singleton wiring ────────────────────────────────────────────────────────

_POOL: KeyPool | None = None


def get_pool() -> KeyPool:
    global _POOL
    if _POOL is None:
        from app.config import get_settings
        s = get_settings()
        _POOL = KeyPool(s.all_gemini_keys())
    return _POOL


async def call_with_rotation(fn: Callable[[genai.Client], Awaitable[T]]) -> T:
    """Convenience wrapper: `await call_with_rotation(lambda c: c.aio.models.generate_content(...))`."""
    return await get_pool().call(fn)
