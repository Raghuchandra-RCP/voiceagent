"""
web_search tool
---------------
One-shot web search that opens the correct site-specific results URL
in the default browser. Replaces the "URL routing table" that used to
live in the LLM system prompt — the model just picks a site + query,
we build the URL deterministically here.

Why not just `open_url`? Because relying on the LLM to remember 7 URL
templates and URL-encode correctly wastes tokens and drifts. Keeping
the logic in Python is faster, cheaper, and 100% reliable.
"""

from __future__ import annotations

import json
import webbrowser
from typing import Any
from urllib.parse import quote_plus

from app.tools.base import Tool

# site alias → URL template with a single {q} placeholder for the URL-encoded query
_SEARCH_URLS: dict[str, str] = {
    "google":        "https://www.google.com/search?q={q}",
    "bing":          "https://www.bing.com/search?q={q}",
    "duckduckgo":    "https://duckduckgo.com/?q={q}",
    "youtube":       "https://www.youtube.com/results?search_query={q}",
    "amazon":        "https://www.amazon.com/s?k={q}",
    "wikipedia":     "https://en.wikipedia.org/wiki/Special:Search?search={q}",
    "github":        "https://github.com/search?q={q}",
    "stackoverflow": "https://stackoverflow.com/search?q={q}",
    "reddit":        "https://www.reddit.com/search/?q={q}",
    "maps":          "https://www.google.com/maps/search/{q}",
}

# Common aliases users say → canonical key above
_ALIASES: dict[str, str] = {
    "yt": "youtube",
    "google search": "google",
    "web": "google",
    "ddg": "duckduckgo",
    "so": "stackoverflow",
    "stack overflow": "stackoverflow",
    "wiki": "wikipedia",
    "gh": "github",
    "google maps": "maps",
}


def _resolve_site(raw: str) -> str:
    key = raw.strip().lower()
    key = _ALIASES.get(key, key)
    return key


async def _handler(args: dict[str, Any]) -> str:
    query = args.get("query")
    site = args.get("site", "google")

    if not isinstance(query, str) or not query.strip():
        return json.dumps({"error": "Missing 'query' argument."})
    if not isinstance(site, str):
        return json.dumps({"error": "'site' must be a string."})

    site_key = _resolve_site(site)
    template = _SEARCH_URLS.get(site_key)
    if template is None:
        return json.dumps({
            "error": f"Unknown site '{site}'. Supported: {sorted(_SEARCH_URLS)}"
        })

    url = template.format(q=quote_plus(query.strip()))
    try:
        ok = webbrowser.open(url, new=0)
        if not ok:
            return json.dumps({"error": f"Browser could not open {url}"})
        return json.dumps({"ok": True, "site": site_key, "url": url})
    except Exception as exc:
        return json.dumps({"error": f"web_search failed: {type(exc).__name__}: {exc}"})


TOOL = Tool(
    name="web_search",
    description=(
        "Search a website directly by opening its results page in the "
        "browser. USE THIS instead of open_url whenever the user wants to "
        "search for something on a specific site (YouTube, Google, Amazon, "
        "Wikipedia, GitHub, Stack Overflow, Reddit, Google Maps, Bing, "
        "DuckDuckGo). Also use this for generic web searches — it is far "
        "more reliable than opening a site and clicking the search bar. "
        "Examples: 'search YouTube for obsession trailer' → "
        "site='youtube', query='obsession trailer'. 'google how to fix "
        "python import error' → site='google', query='how to fix python "
        "import error'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search terms. Do NOT URL-encode — pass raw text.",
            },
            "site": {
                "type": "string",
                "enum": sorted(_SEARCH_URLS.keys()),
                "description": (
                    "Which site to search. Defaults to 'google' for generic "
                    "web searches. Pick the specific site when the user "
                    "names it ('search YouTube for…', 'find on Amazon…')."
                ),
                "default": "google",
            },
        },
        "required": ["query"],
    },
    handler=_handler,
    preamble="",
    response_mode="silent",
    tags=("desktop", "web"),
)
