"""
agent.py — the async Reason -> Act -> Observe loop (the heart of the agent).

Flow per user question:
  1. Send the question + tool declarations to Gemini.
  2. Look at the reply:
       - if it's a TEXT answer -> we're done, return it.
       - if it's a FUNCTION CALL -> validate the args (Pydantic), run the async
         tool, send the result back to the model, and loop.
  3. A MAX_STEPS cap guarantees the loop always terminates.

Two things worth calling out for interviews:
  * The Gemini Python SDK is SYNChronous. To keep the async server responsive we
    run each blocking `send_message` inside `asyncio.to_thread(...)`.
  * When arg validation fails we hand the ERROR BACK to the model as the tool
    result, so it can self-correct instead of the request crashing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import google.generativeai as genai
from google.generativeai.types import RequestOptions
from pydantic import ValidationError

from app import tools
from app.config import (
    GEMINI_MODEL,
    GEMINI_TIMEOUT,
    GROQ_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT,
)
from app.key_manager import AllKeysCoolingDown, key_manager
from app.schemas import ARG_SCHEMAS, FUNCTION_DECLARATIONS, GROQ_TOOLS

# Hard cap on Reason->Act->Observe iterations so the loop can never run forever.
MAX_STEPS = 6

SYSTEM_INSTRUCTION = (
    "You are a GitHub Insights assistant. You answer questions about public "
    "GitHub repositories and users by calling the provided tools to fetch real "
    "data, then summarizing the results clearly and concisely. "
    "Only state facts returned by the tools — never invent numbers. "
    "If a repository or user cannot be found, say so plainly. "
    "If a question is not about GitHub, explain that you can only help with "
    "GitHub repositories and users."
)

# Allowlist mapping tool name -> the async python function that implements it.
TOOL_IMPLS: dict[str, Callable[..., Any]] = {
    "get_repo_info": tools.get_repo_info,
    "get_user_info": tools.get_user_info,
    "list_languages": tools.list_languages,
    "list_recent_commits": tools.list_recent_commits,
    "list_user_repos": tools.list_user_repos,
}


class AgentResult:
    """Small holder for the loop's outcome plus lightweight trace info."""

    def __init__(self, answer: str, steps: int, tool_calls: list[dict[str, Any]]):
        self.answer = answer
        self.steps = steps
        self.tool_calls = tool_calls  # [{name, args, result_summary}] for tracing/usage


def _extract_function_call(response: Any) -> Any | None:
    """Return the first function_call part in a Gemini response, or None."""
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", ""):
                return fc
    return None


def _extract_text(response: Any) -> str:
    """Concatenate any text parts in a Gemini response."""
    chunks: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", "")
            if text:
                chunks.append(text)
    return "".join(chunks).strip()


async def _validate_and_run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Validate model-supplied args, then dispatch to the async tool.

    Returns a dict that always becomes the tool result sent back to the model.
    On invalid args or tool errors we return {"error": ...} so the model can
    see what went wrong and self-correct.
    """
    if name not in TOOL_IMPLS:
        return {"error": f"Unknown tool: {name}"}

    validator = ARG_SCHEMAS.get(name)
    try:
        parsed = validator.model_validate(args)  # strict: extra fields rejected
    except (ValidationError, ValueError) as e:
        return {"error": f"Invalid arguments for {name}: {e}"}

    try:
        return await TOOL_IMPLS[name](**parsed.model_dump())
    except Exception as e:  # tool/network error -> report, don't crash the loop
        return {"error": f"{name} failed: {type(e).__name__}: {e}"}


def _new_chat(history: list[dict[str, str]] | None = None) -> Any:
    """Configure Gemini with the current key and start a tool-enabled chat.

    `history` is prior conversation as [{role, text}, ...] (role in
    {"user","model"}); it is replayed so follow-up questions can resolve
    references like "the above user".
    """
    genai.configure(api_key=key_manager.get_key())
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        tools=[genai.protos.Tool(function_declarations=FUNCTION_DECLARATIONS)],
        system_instruction=SYSTEM_INSTRUCTION,
    )
    seeded = None
    if history:
        seeded = [
            {"role": h["role"], "parts": [{"text": h["text"]}]}
            for h in history
            if h.get("text")
        ]
    return model.start_chat(history=seeded)


async def _send(chat: Any, message: Any, *, rebuild=None) -> tuple[Any, Any]:
    """Send a message to Gemini with real key rotation, off the event loop.

    The Gemini SDK is synchronous (run in a thread) and binds a chat to the key
    that was configured when the chat was created. So to *actually* switch keys
    on a rate-limit we reconfigure with the next key AND rebuild the chat via the
    `rebuild` callback (which replays history). Returns (response, chat) because
    the chat object may have been replaced.

    If `rebuild` is None (e.g. an injected FakeChat in tests), we just retry the
    same chat object after reconfiguring.
    """
    last_error: Exception | None = None
    for _ in range(len(key_manager.keys)):
        current_key = key_manager.get_key()
        genai.configure(api_key=current_key)
        try:
            response = await asyncio.to_thread(
                chat.send_message,
                message,
                request_options=RequestOptions(timeout=GEMINI_TIMEOUT),
            )
            return response, chat
        except Exception as e:  # noqa: BLE001 - inspect message for rate-limit/timeout markers
            text = str(e).lower()
            retryable = (
                "429" in text or "quota" in text or "rate" in text
                or "resource" in text or "timeout" in text or "deadline" in text
            )
            if retryable:
                key_manager.mark_rate_limited(current_key)
                last_error = e
                if rebuild is not None:
                    # rebuild the chat so the *next* key actually takes effect
                    chat = rebuild()
                continue
            raise
    raise AllKeysCoolingDown() if last_error else RuntimeError("send failed")


async def run_agent(
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
    chat: Any | None = None,
) -> AgentResult:
    """Run the agent for one question using the configured LLM provider.

    Routes to Groq or Gemini based on LLM_PROVIDER. `history` seeds conversation
    memory; `chat` injects a FakeChat for offline Gemini-path tests.
    """
    if chat is None and LLM_PROVIDER == "groq":
        return await _run_groq(question, history=history)
    return await _run_gemini(question, history=history, chat=chat)


async def _run_gemini(
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
    chat: Any | None = None,
) -> AgentResult:
    """Run the Reason->Act->Observe loop against Gemini.

    `history` is prior conversation ([{role, text}, ...]) used to seed memory so
    follow-up references resolve. `chat` can be injected (a FakeChat) for offline
    testing; otherwise a real Gemini chat is started (seeded with `history`).
    """
    injected = chat is not None  # tests inject a FakeChat; don't rebuild those
    if chat is None:
        chat = _new_chat(history)

    # Running transcript for this request, used to rebuild the chat if we have to
    # rotate keys mid-flight (the rebuilt chat replays everything so far).
    running: list[dict[str, str]] = list(history or [])

    def _rebuild() -> Any:
        return _new_chat(running)

    tool_calls: list[dict[str, Any]] = []
    message: Any = question
    running.append({"role": "user", "text": question})

    for step in range(1, MAX_STEPS + 1):
        # FakeChat (tests) has no rebuild need; only pass rebuild for real chats.
        response, chat = await _send(
            chat, message, rebuild=None if injected else _rebuild
        )

        fc = _extract_function_call(response)
        if fc is None:
            # No tool call -> the model produced its final text answer.
            return AgentResult(_extract_text(response), step, tool_calls)

        # Convert the proto arg map into a plain dict.
        args = {k: v for k, v in dict(fc.args).items()}
        result = await _validate_and_run_tool(fc.name, args)
        tool_calls.append({"name": fc.name, "args": args, "result": result})

        # Feed the tool result back so the model can observe and continue.
        message = genai.protos.Content(
            role="user",
            parts=[
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                )
            ],
        )

    # Ran out of steps without a final answer.
    return AgentResult(
        "I couldn't complete this within the allowed number of steps.",
        MAX_STEPS,
        tool_calls,
    )


# ==========================================================================
# Groq provider (OpenAI-style tool calling)
# ==========================================================================
def _groq_client(api_key: str) -> Any:
    """Build a Groq client for the given key (imported lazily)."""
    from groq import Groq

    return Groq(api_key=api_key, timeout=LLM_TIMEOUT)


async def _groq_complete(messages: list[dict[str, Any]]) -> Any:
    """Call Groq chat.completions with tools + key rotation, off the event loop.

    Rotates keys on rate-limit/timeout errors, mirroring the Gemini path.
    """
    last_error: Exception | None = None
    for _ in range(max(len(key_manager.keys), 1)):
        current_key = key_manager.get_key()
        client = _groq_client(current_key)

        def _call() -> Any:
            return client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                tools=GROQ_TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )

        try:
            return await asyncio.to_thread(_call)
        except Exception as e:  # noqa: BLE001
            text = str(e).lower()
            retryable = (
                "429" in text or "rate" in text or "quota" in text
                or "timeout" in text or "503" in text or "overloaded" in text
            )
            if retryable:
                key_manager.mark_rate_limited(current_key)
                last_error = e
                continue
            raise
    raise AllKeysCoolingDown() if last_error else RuntimeError("groq send failed")


async def _run_groq(
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
) -> AgentResult:
    """Run the Reason->Act->Observe loop against Groq (OpenAI-style tools)."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    # replay prior conversation ({role: user|model, text} -> OpenAI roles)
    for h in history or []:
        if not h.get("text"):
            continue
        role = "assistant" if h["role"] == "model" else "user"
        messages.append({"role": role, "content": h["text"]})
    messages.append({"role": "user", "content": question})

    tool_calls: list[dict[str, Any]] = []

    for step in range(1, MAX_STEPS + 1):
        response = await _groq_complete(messages)
        choice = response.choices[0].message

        if not getattr(choice, "tool_calls", None):
            # Final text answer.
            return AgentResult(choice.content or "", step, tool_calls)

        # Record the assistant turn (with its tool_calls) in the transcript.
        messages.append(
            {
                "role": "assistant",
                "content": choice.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in choice.tool_calls
                ],
            }
        )

        # Execute each requested tool and append a tool-result message.
        for tc in choice.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await _validate_and_run_tool(name, args)
            tool_calls.append({"name": name, "args": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(result),
                }
            )

    return AgentResult(
        "I couldn't complete this within the allowed number of steps.",
        MAX_STEPS,
        tool_calls,
    )
