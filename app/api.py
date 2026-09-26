"""
api.py — the FastAPI service that exposes the agent over HTTP.

Endpoints:
  GET  /health   liveness probe (no auth) — for load balancers / monitors.
  POST /chat      run the agent on a question (auth required).
  GET  /docs      interactive Swagger UI (FastAPI auto-generates it).
  GET  /metrics   simple in-process usage counters (auth required).

Cross-cutting concerns:
  * Tracing middleware — tags every request with an id and logs method/path/
    status/latency, so requests are traceable end to end.
  * Usage counters — total requests and tool calls, for a lightweight cost/usage story.
  * API-key auth — an X-API-Key header gate so /chat isn't open to the world.
  * CORS — lets a browser frontend (the future React UI) call this API.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextvars import ContextVar

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent import run_agent
from app.key_manager import AllKeysCoolingDown
from app.sessions import SessionStore, build_session_store

logger = logging.getLogger("github_agent.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Per-request id, set by the tracing middleware, readable anywhere in the request.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")

# --- simple in-process usage counters (reset on restart) ---
USAGE = {"requests": 0, "chat_requests": 0, "tool_calls": 0, "errors": 0}

# --- conversation session store (Redis, with in-memory fallback) ---
# Built on startup; tests may replace it via set_session_store().
_session_store: SessionStore | None = None


def set_session_store(store: SessionStore) -> None:
    """Inject a session store (used by tests)."""
    global _session_store
    _session_store = store


async def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = await build_session_store()
    return _session_store


# --------------------------------------------------------------------------
# Request / response models
# --------------------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(
        default=None,
        description="Opaque conversation id. Omit to start a new conversation; "
        "reuse the value returned in the response to continue it.",
    )


class ToolCallInfo(BaseModel):
    name: str
    args: dict
    result: dict


class ChatResponse(BaseModel):
    answer: str
    steps: int
    tool_calls: list[ToolCallInfo]
    request_id: str
    session_id: str


# --------------------------------------------------------------------------
# Auth dependency
# --------------------------------------------------------------------------
def _expected_api_key() -> str:
    """The API key clients must present. Configured via API_KEY in the env."""
    return os.getenv("API_KEY", "").strip()


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject requests without a valid X-API-Key header.

    If no API_KEY is configured server-side, auth is effectively open (useful
    for local dev) but we log a warning so it's never a silent surprise.
    """
    expected = _expected_api_key()
    if not expected:
        logger.warning("[%s] API_KEY not set — /chat is unprotected", _request_id.get())
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


# --------------------------------------------------------------------------
# App + middleware
# --------------------------------------------------------------------------
app = FastAPI(
    title="GitHub Insights Agent",
    description="Ask questions about public GitHub repos and users; an AI agent "
    "calls the GitHub API as tools to answer.",
    version="1.0.0",
)

# CORS — allow the future React dev server (and configurable extra origins).
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def tracing_middleware(request: Request, call_next):
    """Assign a request id, time the request, and log the outcome."""
    rid = uuid.uuid4().hex[:8]
    _request_id.set(rid)
    USAGE["requests"] += 1
    start = time.perf_counter()
    logger.info("[%s] --> %s %s", rid, request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        USAGE["errors"] += 1
        elapsed = (time.perf_counter() - start) * 1000
        logger.exception("[%s] <-- 500 %s (%.1f ms)", rid, request.url.path, elapsed)
        raise
    elapsed = (time.perf_counter() - start) * 1000
    logger.info("[%s] <-- %d %s (%.1f ms)", rid, response.status_code, request.url.path, elapsed)
    response.headers["X-Request-ID"] = rid
    return response


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Liveness probe — no auth."""
    return {"status": "ok"}


@app.get("/metrics")
async def metrics(_: None = Depends(require_api_key)) -> dict:
    """Lightweight in-process usage counters."""
    return dict(USAGE)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, _: None = Depends(require_api_key)) -> ChatResponse:
    """Run the agent on a question and return the answer + trace.

    If a session_id is supplied (or generated), prior conversation history is
    loaded and replayed so follow-up questions resolve references; the new turn
    is then saved back to the session store.
    """
    rid = _request_id.get()
    USAGE["chat_requests"] += 1

    store = await get_session_store()
    session_id = req.session_id or uuid.uuid4().hex
    history = await store.get_history(session_id)

    try:
        result = await run_agent(req.question, history=history)
    except AllKeysCoolingDown:
        USAGE["errors"] += 1
        raise HTTPException(
            status_code=503,
            detail="All model API keys are rate-limited right now. Please retry shortly.",
        )
    except Exception as e:  # noqa: BLE001 - surface as a clean 500
        USAGE["errors"] += 1
        logger.exception("[%s] agent failed", rid)
        raise HTTPException(status_code=500, detail=f"Agent error: {type(e).__name__}")

    # persist this turn so the next request in the session remembers it
    await store.append_turn(session_id, req.question, result.answer)

    USAGE["tool_calls"] += len(result.tool_calls)
    return ChatResponse(
        answer=result.answer,
        steps=result.steps,
        tool_calls=[ToolCallInfo(**tc) for tc in result.tool_calls],
        request_id=rid,
        session_id=session_id,
    )
