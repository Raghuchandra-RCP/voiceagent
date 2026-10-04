# 🎙 Real-Time Voice Agent — v2.0

Low-latency, fully streaming voice assistant now powered by **OpenAI's new Realtime models** (May 2026).

| Layer | Technology | New? |
|---|---|---|
| **STT** | [gpt-realtime-whisper](https://openai.com/blog/realtime-voice-models) — streams transcript as you speak | ✅ New |
| **LLM** | [gpt-realtime-2](https://openai.com/blog/realtime-voice-models) — GPT-5-class reasoning, 128K context | ✅ New |
| **TTS** | gpt-realtime-2 built-in (alloy/nova/shimmer/echo/fable/onyx) | ✅ New |
| **Translation** | [gpt-realtime-translate](https://openai.com/blog/realtime-voice-models) — 70+ input → 13 output languages | ✅ New |
| **Backend** | FastAPI + WebSockets |  |
| **Frontend** | Vanilla HTML/JS (Web Audio API) |  |

---

## 🏗 Architecture

### Realtime Pipeline (Default — `PIPELINE_MODE=realtime`)

```
Mic (16kHz PCM)
 │
 ▼
WebSocket /ws  (FastAPI)
 │
 ▼
OpenAI Realtime WebSocket  ←──────────────────────────────────────┐
  │                                                                │
  │  Model: gpt-realtime-2  (or gpt-realtime-translate)           │
  │  • STT   — gpt-realtime-whisper (streaming live captions)     │
  │  • LLM   — GPT-5-class reasoning, 128K context window         │
  │  • TTS   — Built-in voices (nova, alloy, shimmer…)            │
  │  • Tools — Preambles + parallel tool calls                     │
  │  • VAD   — Server-side voice activity detection               │
  │  • Reasoning effort: minimal / low / medium / high / xhigh    │
  │                                                                │
  └──────────────────── audio delta (PCM16) ──────────────────────┘
 │
 ▼
WebSocket → Browser  (Web Audio API plays audio in real time)
```

### Translation Mode (`ENABLE_TRANSLATION=true`)

```
Speaker A (any of 70+ languages)
 │  PCM audio
 ▼
gpt-realtime-translate
 │  Live translated audio + transcript
 ▼
Speaker B (hears response in chosen language: en/es/fr/de/hi…)
```

**Pricing:** $0.034/minute (translate) | $0.017/minute (whisper)

### Legacy Pipeline (`PIPELINE_MODE=legacy`)

```
Mic (16kHz PCM)
 │
 ▼
faster-whisper  (local STT — HuggingFace model)
 │  STTChunkEvent + STTOutputEvent
 ▼
LangChain agent  (gpt-4o + InMemorySaver)
 │  AgentChunkEvent + AgentEndEvent
 ▼
OpenAI tts-1-hd  (cloud TTS)
 │  TTSChunkEvent (MP3)
 ▼
WebSocket → Browser
```

---

## ✨ New Features (May 2026)

### 🧠 GPT-Realtime-2 — GPT-5-class Reasoning
- **Preambles**: Model says "let me check that for you" before running tools
- **Parallel tool calls**: Multiple tools called simultaneously
- **Reasoning effort**: `REALTIME_REASONING_EFFORT=low` (default) → up to `xhigh`
  - `xhigh` scores **15.2% higher** on Big Bench Audio vs previous generation
- **128K context window**: Long, coherent multi-turn conversations
- **Tone control**: Calm when resolving, empathetic when frustrated, upbeat on success
- **Recovery**: "I'm having trouble with that" instead of silent failure

### 🌐 GPT-Realtime-Translate — Live Speech Translation
- 70+ input languages detected automatically
- 13 output languages: `en es fr de it pt nl pl hi ja ko zh ar`
- Keeps pace with the speaker — no waiting for full sentences

### 🎤 GPT-Realtime-Whisper — Streaming Transcription
- Transcribes word-by-word as the speaker talks
- Used inside `gpt-realtime-2` sessions for live caption display
- Standalone: `$0.017/minute`

---

## 🚀 Quick Start

```bash
cd "c:\Projects\Voice Agent"
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

Edit `.env` — fill in your OpenAI key:
```env
OPENAI_API_KEY=sk-...
PIPELINE_MODE=realtime      # or "legacy"
REALTIME_REASONING_EFFORT=low
```

Run the server:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open: **http://localhost:8000** — click **Connect & Start**, speak naturally.

---

## ⚙️ Key Environment Variables

```env
# ── Pipeline switch ────────────────────────────────────────────
PIPELINE_MODE=realtime          # "realtime" (new) or "legacy"

# ── GPT-Realtime-2 ────────────────────────────────────────────
REALTIME_MODEL=gpt-realtime-2
REALTIME_REASONING_EFFORT=low   # minimal | low | medium | high | xhigh
REALTIME_VOICE=nova             # alloy | nova | shimmer | echo | fable | onyx

# ── GPT-Realtime-Translate (set ENABLE_TRANSLATION=true) ──────
ENABLE_TRANSLATION=false
TRANSLATION_TARGET_LANG=en      # en | es | fr | de | it | pt | nl | pl | hi | ja | ko | zh | ar
TRANSLATION_SOURCE_LANG=auto    # auto = detect, or specify e.g. "hi"

# ── GPT-Realtime-Whisper ───────────────────────────────────────
WHISPER_API_MODEL=gpt-realtime-whisper
```

---

## 🧠 Reasoning Effort Guide

| Level | Latency | Best For |
|-------|---------|----------|
| `minimal` | Fastest | Simple FAQs, greetings |
| `low` ✅ | Very fast | **Default** — most voice apps |
| `medium` | Moderate | Complex multi-step requests |
| `high` | Slower | Strategic reasoning, analysis |
| `xhigh` | Slowest | Maximum intelligence (+15.2% Big Bench Audio) |

---

## 💰 Pricing Comparison

| | Realtime Pipeline | Legacy Pipeline |
|---|---|---|
| STT | gpt-realtime-whisper: $0.017/min | faster-whisper: free (local) |
| LLM | gpt-realtime-2: $32/1M audio in | gpt-4o: ~$0.005/1K tokens |
| TTS | gpt-realtime-2: $64/1M audio out | openai tts-1-hd: $0.030/1K chars |
| Translation | gpt-realtime-translate: $0.034/min | — |
| **Est. per 5-min call** | **~$0.10–$0.30** | **~$0.02–$0.05** |

---

## 📁 Project Structure

```
Voice Agent/
├── app/
│   ├── main.py               # FastAPI server — dual-pipeline support
│   ├── config.py             # Settings (all new model env vars)
│   ├── events.py             # Typed events + TranslationChunkEvent
│   └── pipeline/
│       ├── realtime.py       # ★ NEW — gpt-realtime-2/translate/whisper
│       ├── llm.py            # Legacy: LangChain gpt-4o agent
│       ├── stt.py            # Legacy: faster-whisper STT
│       └── tts.py            # Legacy: openai tts-1-hd
├── audio/
│   ├── silence_detector.py   # VAD (webrtcvad + RMS fallback)
│   └── player.py             # CLI audio player
├── frontend/
│   └── index.html            # Browser UI — live transcript, model badges, translation UI
├── client.py                 # CLI test client (mic → WebSocket)
├── .env                      # API keys + pipeline config
├── requirements.txt
└── README.md
```

---

## 🌐 WebSocket Protocol

**Endpoint:** `ws://localhost:8000/ws`

### Client → Server

| Frame | Content |
|---|---|
| Binary | Raw PCM16 audio (16-bit signed, mono, 16 kHz) |
| Text JSON | `{"type": "interrupt"}` |

### Server → Client (JSON events)

| Event | Fields | Description |
|---|---|---|
| `session_init` | `session_id`, `pipeline`, `model`, `translation` | Session ready |
| `stt_chunk` | `transcript` | Live partial transcript (gpt-realtime-whisper) |
| `stt_output` | `transcript` | Final utterance |
| `agent_chunk` | `text` | Streaming LLM token |
| `translation_chunk` | `text`, `source_lang`, `target_lang` | Live translation output |
| `agent_end` | — | Response complete |
| `tts_chunk` | `audio` (base64 PCM16/MP3) | Audio to play |
| `tts_end` | — | TTS complete |
| `error` | `message` | Pipeline error |

---

## ✅ Features

- ✅ **gpt-realtime-2** — GPT-5-class reasoning in real-time voice
- ✅ **gpt-realtime-whisper** — live streaming transcription as you speak  
- ✅ **gpt-realtime-translate** — 70+ language live translation
- ✅ **Adjustable reasoning effort** — `minimal` to `xhigh`
- ✅ **Preambles** — "let me check that" before tool calls
- ✅ **Parallel tool calls** — multiple tools at once
- ✅ **Tone control** — calm / empathetic / upbeat responses
- ✅ **Legacy fallback** — faster-whisper + gpt-4o + openai-tts
- ✅ **VAD interrupts** — server-side (realtime) or client-side (legacy)
- ✅ **Per-session conversation memory** — 128K context (realtime)
- ✅ **Browser frontend** — live transcript, streaming chat, audio visualiser
- ✅ **CLI client** — terminal testing
