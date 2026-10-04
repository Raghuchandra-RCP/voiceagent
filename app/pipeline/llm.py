"""
app/pipeline/llm.py
-------------------
Gemini 2.5 Flash chat + tool-calling — implemented as a LangGraph state machine.

Public API is unchanged: callers still do `LLM().chat(text, on_tool_call=...)`
and `.reset()`. Internally, we now compile a `StateGraph` with two nodes:

        ┌────────┐   function_call?    ┌────────┐
   ──▶  │  llm   │ ──── yes ─────────▶ │ tools  │ ──┐
        └────────┘                     └────────┘   │
             ▲                                      │
             └──────────────────────────────────────┘
             │
             └── no ──▶ END (final text)

Why keep google-genai directly (vs LangChain's ChatGoogleGenerativeAI)?
  • Preserves the multi-key rotation in `gemini_keys.KeyPool` unchanged.
  • Preserves the vision path used by `read_screen` (same client, same
    quota accounting).
  • LangGraph doesn't require LangChain chat models — a node is just a
    function. We get the graph, conditional edges, and future features
    (checkpointing, HITL, streaming) without giving up rotation.

Conversation memory is owned by a LangGraph `InMemorySaver` checkpointer,
keyed by a per-instance `thread_id` — not a hand-rolled list on `self`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Awaitable, Callable, Optional, TypedDict

from google import genai  # noqa: F401  (re-exported implicitly by types)
from google.genai import types
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from app.config import get_settings
from app.pipeline.gemini_keys import call_with_rotation
from app.tools import execute_tool, get_tool_declarations

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Jarvis, a fast, friendly voice-controlled assistant for a "
    "Windows desktop. You have tools to control apps, windows, mouse, "
    "keyboard, clipboard, the browser, screen vision, files, and system "
    "settings — use them whenever the user asks you to do something. "
    "Don't describe what you're about to do; just do it.\n\n"
    "Turn scope (STRICT):\n"
    "- Do ONLY what the user asked in THIS turn. Never re-run a previous "
    "  action just because it's still in history. Every turn is fresh.\n"
    "- 'find', 'locate', 'where is', 'show me' → call `read_screen` and "
    "  REPORT the answer verbatim. Do NOT click or type anything unless "
    "  the user explicitly asks (e.g. 'click the Save button', "
    "  'type X in the search bar').\n"
    "- If the transcript is ambiguous, incomplete, or 1–3 vague words "
    "  (e.g. 'so much', 'we did', 'much'), ask ONE short clarifying "
    "  question instead of guessing or acting.\n\n"
    "Coordinate rules (STRICT — wrong clicks waste turns):\n"
    "- NEVER invent x/y pixel coordinates. Only use coordinates that were "
    "  returned by `read_screen` IN THE CURRENT TURN.\n"
    "- If the user asks you to click something and you don't have fresh "
    "  coordinates, call `read_screen` FIRST (this turn), then click.\n"
    "- If `read_screen` returns 'not found: …', report that back — don't "
    "  fall back to an old cached position.\n\n"
    "Tool-use policy:\n"
    "- Prefer `web_search` over `open_url` for anything the user wants to "
    "  search for (YouTube, Google, Amazon, Wikipedia, GitHub, etc.).\n"
    "- Use `open_app` for desktop apps and `open_url` only for a specific "
    "  known URL or bare domain.\n"
    "- When replacing text in an existing input field (search bar with "
    "  stale text, address bar, etc.), use `type_text` with "
    "  `clear_first: true` — do not chain ctrl+a + type manually.\n"
    "- Batch actions with `run_sequence` whenever possible. Prefer one "
    "  `read_screen` + one `run_sequence` over many single tool calls.\n\n"
    "Speaking style:\n"
    "- Keep replies to 1–2 short sentences. No markdown, no bullets, no "
    "  code fences.\n"
    "- After a silent action succeeds, reply with a single short word: "
    "  'done', 'ok', 'opening'.\n"
    "- After `read_screen` or `read_clipboard`, relay the result verbatim "
    "  (trimmed to 1–2 sentences).\n"
    "- If a tool errors, apologise briefly and suggest an alternative.\n"
    "- Match the user's language: reply in Telugu if they speak Telugu, "
    "  English if English."
)

# ToolNotify hooks so the CLI can print/log tool activity
ToolNotify = Callable[[str, dict], Awaitable[None]]

# Hard cap on tool-call iterations per user turn to avoid runaway loops.
_MAX_TOOL_ITERATIONS = 6


def _build_tools() -> list[types.Tool]:
    """Wrap every registered tool as a Gemini `types.Tool`."""
    decls = get_tool_declarations()
    fn_decls = [
        types.FunctionDeclaration(
            name=d["name"],
            description=d["description"],
            parameters_json_schema=d["parameters"],
        )
        for d in decls
    ]
    return [types.Tool(function_declarations=fn_decls)] if fn_decls else []


# ── Graph state ──────────────────────────────────────────────────────────────
# `history` is persisted by the checkpointer across turns. The reducer below
# both appends new content AND trims — so the checkpoint itself never grows
# past `llm_max_history`, instead of trimming a separately-tracked list on
# `self` after every call. `iterations` counts LLM turns per invocation so we
# can enforce the tool-loop cap in the conditional edge.

def _is_function_response(content: types.Content) -> bool:
    if not content or not content.parts:
        return False
    return any(getattr(p, "function_response", None) for p in content.parts)


def _trim_contents(history: list[types.Content], max_history: int) -> list[types.Content]:
    """Keep only the last N messages so context stays cheap.

    Gemini enforces strict role rules on the FIRST turn we send:
      - it must be role="user"
      - it must NOT be a function_response (function calls must come
        after a real user turn or another function_response)
      - it must NOT be a model turn (definitely not one containing a
        function_call)

    Without this care, a naive tail-slice can leave a leading model
    function_call at position 0 and Gemini responds:
      400 INVALID_ARGUMENT "function call turn comes immediately after
      a user turn or after a function response turn"
    — which then permanently poisons the session.
    """
    if len(history) <= max_history:
        return history
    trimmed = history[-max_history:]
    while trimmed:
        head = trimmed[0]
        if head.role != "user" or _is_function_response(head):
            trimmed.pop(0)
            continue
        break
    return trimmed


def _history_reducer(
    left: list[types.Content] | None, right: list[types.Content] | None
) -> list[types.Content]:
    merged = (left or []) + (right or [])
    return _trim_contents(merged, get_settings().llm_max_history)


class _GraphState(TypedDict, total=False):
    history: Annotated[list[types.Content], _history_reducer]
    iterations: int


class LLM:
    """Gemini 2.5 Flash with function-calling and rolling conversation history.

    Backed by a compiled LangGraph `StateGraph`. The public surface — `chat`
    and `reset` — is intentionally the same as the previous hand-rolled loop,
    so `LocalPipeline` and every caller stays untouched.
    """

    def __init__(self):
        s = get_settings()
        # Client is managed by the shared KeyPool (see gemini_keys.py) so
        # every call transparently fails over to a backup key on 429/auth.
        self._model = s.llm_model
        self._temperature = s.llm_temperature
        self._thinking_budget = s.llm_thinking_budget
        self._tools = _build_tools()

        # Conversation memory lives in the checkpointer, keyed by thread_id —
        # not on `self`. In-process only: cleared on restart, same as before.
        self._checkpointer = InMemorySaver()
        self._thread_id = str(uuid.uuid4())

        self._graph = self._build_graph()

    def reset(self) -> None:
        """Wipe conversation memory (e.g. new session)."""
        self._checkpointer.delete_thread(self._thread_id)

    def _make_config(self) -> types.GenerateContentConfig:
        cfg_kwargs: dict[str, Any] = {
            "system_instruction": SYSTEM_PROMPT,
            "temperature": self._temperature,
            "tools": self._tools,
        }
        # thinking_config is only accepted by 2.5-series *thinking* models.
        # Flash-Lite and older 1.5 models return 400 INVALID_ARGUMENT if it's
        # present. Detect from the model name and skip.
        model_l = (self._model or "").lower()
        supports_thinking = (
            "2.5" in model_l or model_l.startswith("gemini-flash-latest")
        ) and "lite" not in model_l
        if supports_thinking:
            try:
                cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                    thinking_budget=self._thinking_budget,
                )
            except Exception:
                pass
        return types.GenerateContentConfig(**cfg_kwargs)

    # ── Graph construction ──────────────────────────────────────────────────

    def _build_graph(self):
        async def llm_node(state: _GraphState) -> dict[str, Any]:
            history = state.get("history") or []
            resp = await call_with_rotation(
                lambda c: c.aio.models.generate_content(
                    model=self._model,
                    contents=history,  # type: ignore[arg-type]  # SDK accepts list[Content]
                    config=self._make_config(),
                )
            )
            candidate = resp.candidates[0] if resp.candidates else None
            content = candidate.content if candidate else None
            parts = list(content.parts) if content and content.parts else []
            model_content = types.Content(
                role="model",
                parts=parts or [types.Part.from_text(text="")],
            )
            return {
                "history": [model_content],
                "iterations": state.get("iterations", 0) + 1,
            }

        async def tools_node(state: _GraphState, config: RunnableConfig) -> dict[str, Any]:
            history = state.get("history") or []
            last = history[-1] if history else None
            fn_calls = []
            if last and last.parts:
                for p in last.parts:
                    fc = getattr(p, "function_call", None)
                    if fc is not None:
                        fn_calls.append(fc)

            configurable = (config or {}).get("configurable", {}) or {}
            on_tool_call: Optional[ToolNotify] = configurable.get("on_tool_call")

            fn_response_parts: list[types.Part] = []
            for fc in fn_calls:
                name = getattr(fc, "name", None) or ""
                raw_args = getattr(fc, "args", None)
                args = dict(raw_args) if raw_args else {}
                if on_tool_call:
                    try:
                        await on_tool_call(name, args)
                    except Exception:  # never break the loop on notify
                        pass
                result_json = await execute_tool(name, args)
                # Gemini requires the response value to be a mapping.
                fn_response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": result_json},
                    )
                )

            tool_content = types.Content(role="user", parts=fn_response_parts)
            return {"history": [tool_content]}

        def route(state: _GraphState) -> str:
            # Hard cap on tool iterations to avoid runaway loops.
            if state.get("iterations", 0) >= _MAX_TOOL_ITERATIONS:
                return END
            history = state.get("history") or []
            if not history:
                return END
            last = history[-1]
            if not last.parts:
                return END
            has_fn_call = any(getattr(p, "function_call", None) for p in last.parts)
            return "tools" if has_fn_call else END

        g: StateGraph = StateGraph(_GraphState)
        g.add_node("llm", llm_node)
        g.add_node("tools", tools_node)
        g.set_entry_point("llm")
        g.add_conditional_edges("llm", route, {"tools": "tools", END: END})
        g.add_edge("tools", "llm")
        return g.compile(checkpointer=self._checkpointer)

    # ── Public turn entry point ─────────────────────────────────────────────

    async def chat(
        self,
        user_text: str,
        on_tool_call: Optional[ToolNotify] = None,
    ) -> str:
        """Send a user turn, resolve any tool calls, return final assistant text.

        Only the new user message is passed in — the checkpointer already
        holds prior turns under `self._thread_id`, and `_history_reducer`
        appends + trims automatically. On any error mid-turn we wipe the
        thread: the checkpointer gives no cheap partial-rollback, so a full
        reset is the safe way to avoid leaving Gemini-rejected state behind
        (e.g. two consecutive user turns, or a dangling model function_call
        with no matching function_response).
        """
        if not user_text.strip():
            return ""

        user_content = types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
        config: RunnableConfig = {
            "configurable": {"thread_id": self._thread_id, "on_tool_call": on_tool_call}
        }

        try:
            result = await self._graph.ainvoke(
                {"history": [user_content], "iterations": 0},
                config=config,
            )
            final_text = self._extract_final_text(result.get("history") or [])
            iterations = int(result.get("iterations", 0))

            if not final_text and iterations >= _MAX_TOOL_ITERATIONS:
                logger.warning("[llm] tool loop hit cap — returning fallback text")
                return "Sorry, I got stuck. Try again?"
            return final_text
        except Exception as exc:
            logger.warning(
                "[llm] turn failed (%s) — resetting conversation thread to avoid "
                "corrupted state.", exc,
            )
            self.reset()
            raise

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_final_text(history: list[types.Content]) -> str:
        """Return the text of the most recent model turn, if any."""
        for content in reversed(history):
            if content.role != "model":
                continue
            chunks: list[str] = []
            for p in content.parts or []:
                t = getattr(p, "text", None)
                if t:
                    chunks.append(t)
            return "".join(chunks).strip()
        return ""
