"""Voice-agent pipelines.

Currently only the local pipeline exists:
    from app.pipeline.local import LocalPipeline

The Realtime WebSocket pipeline was removed in July 2026 in favour of
turn-based local Whisper + GPT-4o-mini + Piper.
"""
