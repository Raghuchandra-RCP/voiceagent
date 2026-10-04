"""
app/pipeline/hallucination.py
-----------------------------
Filter for common Whisper "silence hallucinations".

Whisper (and Groq's whisper-large-v3-turbo) is trained on huge amounts of
YouTube audio, so when it's fed silence, breathing, keyboard clicks, or the
tail of our own TTS leaking through the mic, it very often emits phrases
that dominate the training corpus's segment boundaries:

    "Thank you." / "Thanks for watching." / "You" / "Bye." / "Gracias." /
    "Amara.org" / "Subtitles by the Amara.org community." / "."

These are almost never a real user utterance for a desktop assistant, so
dropping them stops the echo/hallucination loop cold.

Rules (checked in order):
1. Exact match against a curated blacklist (case-insensitive, punctuation
   and whitespace ignored).
2. Very short transcript (< MIN_CHARS) is always junk.
3. "Fragment heuristic": a transcript with <= FRAGMENT_MAX_WORDS words that
   starts with a token from `_FRAGMENT_STARTERS` is almost never a real
   command. It's typically Whisper spitting out the tail of an unrelated
   sentence it half-heard.
"""

from __future__ import annotations

import re

MIN_CHARS = 3
FRAGMENT_MAX_WORDS = 4

# Everything below is compared after: lower(), strip punctuation, collapse spaces.
_BLACKLIST = frozenset({
    "",
    "you",
    "yeah",
    "ok",
    "okay",
    "hmm",
    "uh",
    "um",
    "mm",
    "bye",
    "thanks",
    "thank you",
    "thanks a lot",
    "thanks for watching",
    "thank you for watching",
    "thanks for watching everyone",
    "please subscribe",
    "please like and subscribe",
    "youre welcome",
    "you are welcome",
    "de nada",
    "gracias",
    "merci",
    "merci beaucoup",
    "arigato",
    "subtitles by the amaraorg community",
    "amaraorg",
    "captions by",
    "subtitles by",
    "peace",
    "goodbye",
    "see you",
    "see ya",
    "next time",
    "the end",
    "end of video",
    # Observed real-session Whisper mis-transcriptions of background noise:
    "so much",
    "much",
    "we did",
    "we did them",
    "we did them its absolutely",
    "its absolutely",
    "it is absolutely",
    "absolutely",
    "of course",
    "well",
    "oh",
    "oh well",
    "oh yeah",
    "wow",
    "hmm hmm",
})

# Short (<= FRAGMENT_MAX_WORDS) transcripts starting with any of these tokens
# are treated as sentence fragments and dropped. These tokens are almost
# never the FIRST word of a real desktop command — commands start with
# verbs ("open", "search", "click", "read", "type", "call", "ring", …).
_FRAGMENT_STARTERS = frozenset({
    "so",
    "we",
    "its",
    "and",
    "or",
    "but",
    "much",
    "well",
    "oh",
    "yeah",
    "actually",
    "anyway",
    "though",
    "because",
    "cause",
    "cuz",
})

_APOS_RE = re.compile(r"[\u2019'`]")  # curly + straight apostrophes, backtick
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    t = text.lower()
    # Drop apostrophes with NO replacement so "it's" → "its" (not "it s").
    t = _APOS_RE.sub("", t)
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def is_whisper_hallucination(text: str) -> bool:
    """Return True if the transcript looks like a Whisper silence hallucination."""
    if not text:
        return True
    norm = _normalise(text)
    if len(norm) < MIN_CHARS:
        return True
    if norm in _BLACKLIST:
        return True
    # Fragment heuristic: short + starts with a non-command token.
    words = norm.split()
    if 0 < len(words) <= FRAGMENT_MAX_WORDS and words[0] in _FRAGMENT_STARTERS:
        return True
    return False

