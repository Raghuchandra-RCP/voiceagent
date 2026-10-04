"""
jarvis.py — CLI entry point for the desktop Jarvis voice agent.

    python jarvis.py                  # always-on (default, zero extra deps)
    python jarvis.py --mode hotkey    # press Ctrl+Space to talk (needs pynput)
    python jarvis.py --mode wake      # say "Hey Jarvis" (needs openwakeword)
"""

from app.desktop.jarvis_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
