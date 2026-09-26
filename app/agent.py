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
from typing import Any, Callable

import google.generativeai as genai
from pydantic import ValidationError

from app import tools
from app.config import GEMINI_MODEL
from app.key_manager import AllKeysCoolingDown, key_manager
from app.schemas import ARG_SCHEMAS, FUNCTION_DECLARATIONS

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


def _new_chat() -> Any:
    """Configure Gemini with the current key and start a tool-enabled chat."""
    genai.configure(api_key=key_manager.get_key())
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        tools=[genai.protos.Tool(function_declarations=FUNCTION_DECLARATIONS)],
        system_instruction=SYSTEM_INSTRUCTION,
    )
    return model.start_chat()


async def _send(chat: Any, message: Any) -> Any:
    """Send a message to Gemini with key rotation, off the event loop.

    The SDK is synchronous, so we run it in a thread. On a rate-limit error we
    mark the key cooling and retry with the next key.
    """
    last_error: Exception | None = None
    for _ in range(len(key_manager.keys)):
        current_key = key_manager.get_key()
        genai.configure(api_key=current_key)
        try:
            return await asyncio.to_thread(chat.send_message, message)
        except Exception as e:  # noqa: BLE001 - inspect message for rate-limit markers
            text = str(e).lower()
            if "429" in text or "quota" in text or "rate" in text or "resource" in text:
                key_manager.mark_rate_limited(current_key)
                last_error = e
                continue
            raise
    raise AllKeysCoolingDown() if last_error else RuntimeError("send failed")


async def run_agent(question: str, *, chat: Any | None = None) -> AgentResult:
    """Run the Reason->Act->Observe loop for a single question.

    `chat` can be injected (a FakeChat) for offline testing; otherwise a real
    Gemini chat is started.
    """
    if chat is None:
        chat = _new_chat()

    tool_calls: list[dict[str, Any]] = []
    message: Any = question

    for step in range(1, MAX_STEPS + 1):
        response = await _send(chat, message)

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
