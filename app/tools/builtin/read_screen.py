"""
read_screen tool
----------------
Take a screenshot of the primary monitor (or a specific region), send it to
the vision-capable Gemini model configured in `settings.llm_model`, and
return the model's textual description / answer.

Runs its own one-shot vision call (the image can't be handed back into the
outer text-only conversation) and returns just the text it produced.
"""

from __future__ import annotations

import io
import json
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings
from app.pipeline.gemini_keys import call_with_rotation
from app.tools import _screen_cache
from app.tools.base import Tool


def _capture(region: dict[str, Any] | None) -> bytes:
    """Return PNG bytes of the full screen or a sub-region."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        if region:
            bbox = {
                "left": int(region.get("left", 0)),
                "top": int(region.get("top", 0)),
                "width": int(region.get("width", 0)),
                "height": int(region.get("height", 0)),
            }
            if bbox["width"] <= 0 or bbox["height"] <= 0:
                raise ValueError("region.width and region.height must be positive.")
            raw = sct.grab(bbox)
        else:
            monitor = sct.monitors[1]  # primary monitor
            raw = sct.grab(monitor)

        img = Image.frombytes("RGB", raw.size, raw.rgb)

        # Downscale wide screens to keep tokens cheap (max 1600px wide).
        max_w = 1600
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


async def _handler(args: dict[str, Any]) -> str:
    question = str(args.get("query") or "").strip()
    if not question:
        question = "Describe what is on the screen in one or two short sentences."

    region = args.get("region") if isinstance(args.get("region"), dict) else None

    # ── Cache hit? Skip both screenshot + vision call. ───────────────────────
    # Only cache full-screen captures (region=None) to avoid stale crops.
    if region is None:
        cached = _screen_cache.get(question)
        if cached is not None:
            return json.dumps({
                "ok": True,
                "answer": cached.answer,
                "image_bytes": cached.image_bytes,
                "cached": True,
            })

    try:
        png_bytes = _capture(region)
    except Exception as exc:
        return json.dumps({"error": f"Screenshot failed: {type(exc).__name__}: {exc}"})

    s = get_settings()

    system = (
        "You are a screen-reader for a voice assistant. Answer the user's "
        "question about the screenshot in ONE or TWO short spoken sentences. "
        "No markdown, no bullet points, no code fences.\n\n"
        "When the user asks for the coordinates of a UI element, ALWAYS "
        "reply in this exact format on one line:\n"
        "  <short label>: x=<int>, y=<int>\n"
        "where <short label> is 2–6 words describing WHAT you found "
        "(e.g. 'YouTube search bar at top', 'Save button in dialog'). "
        "Coordinates are pixels from the top-left of the screenshot.\n\n"
        "If you cannot confidently locate the requested element, reply "
        "'not found: <reason>' instead of guessing. Never invent "
        "coordinates — wrong coordinates cause the agent to click the "
        "wrong thing and waste a turn."
    )

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=question),
                types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
            ],
        )
    ]

    try:
        resp = await call_with_rotation(
            lambda c: c.aio.models.generate_content(
                model=s.llm_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.1,
                ),
            )
        )
        # Extract text from candidates
        text = ""
        if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
            for part in resp.candidates[0].content.parts:
                t = getattr(part, "text", None)
                if t:
                    text += t
        text = text.strip()
    except Exception as exc:
        return json.dumps({"error": f"Vision call failed: {type(exc).__name__}: {exc}"})

    # Populate cache (full-screen only) so a repeat question this turn is free.
    if region is None and text:
        _screen_cache.put(question, text, len(png_bytes))

    return json.dumps({
        "ok": True,
        "answer": text,
        "image_bytes": len(png_bytes),
    })


TOOL = Tool(
    name="read_screen",
    description=(
        "Take a screenshot of the user's screen and answer a question about "
        "it using vision. Call this when the user says 'what's on my "
        "screen', 'read this to me', 'summarise the error', 'what does that "
        "dialog say', 'find the Save button', etc. Pass a specific `query` "
        "for what to look for. Optionally pass a `region` "
        "{left,top,width,height} to crop before analysis. The tool returns "
        "a short spoken description you should relay verbatim to the user."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "What to answer about the screen. Examples: 'summarise "
                    "the article', 'read the error dialog', 'where is the "
                    "Send button?'. If omitted, gives a general description."
                ),
            },
            "region": {
                "type": "object",
                "description": (
                    "Optional bounding box in pixels from the top-left. "
                    "Omit to capture the full primary monitor."
                ),
                "properties": {
                    "left": {"type": "integer"},
                    "top": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
                "required": ["left", "top", "width", "height"],
            },
        },
        "required": [],
    },
    handler=_handler,
    preamble="",
    response_mode="full",
    tags=("desktop", "vision"),
)
