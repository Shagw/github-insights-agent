"""Tests for the FastAPI wrapper (auth, endpoints, tracing, usage)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.agent import AgentResult
from app.key_manager import AllKeysCoolingDown


API_KEY = "test-secret"


@pytest.fixture
def client(monkeypatch):
    """A TestClient with auth enabled and the agent faked (no Gemini/network)."""
    monkeypatch.setenv("API_KEY", API_KEY)

    # inject an in-memory session store so tests never touch real Redis
    from app.sessions import SessionStore, _MemoryBackend
    api.set_session_store(SessionStore(_MemoryBackend(), kind="memory"))

    async def fake_run_agent(question, *, history=None, chat=None):
        return AgentResult(
            answer=f"Answer to: {question}",
            steps=2,
            tool_calls=[{
                "name": "get_repo_info",
                "args": {"owner": "fastapi", "repo": "fastapi"},
                "result": {"stars": 102629},
            }],
        )

    monkeypatch.setattr(api, "run_agent", fake_run_agent)
    return TestClient(api.app)


def _auth():
    return {"X-API-Key": API_KEY}


def test_health_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers.get("X-Request-ID")  # tracing id present


def test_chat_requires_key(client):
    r = client.post("/chat", json={"question": "hi"})
    assert r.status_code == 401


def test_chat_rejects_wrong_key(client):
    r = client.post("/chat", json={"question": "hi"}, headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_chat_success(client):
    r = client.post("/chat", json={"question": "stars of fastapi?"}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Answer to: stars of fastapi?"
    assert body["steps"] == 2
    assert body["tool_calls"][0]["name"] == "get_repo_info"
    assert body["tool_calls"][0]["result"]["stars"] == 102629
    assert body["request_id"]


def test_chat_empty_question_422(client):
    r = client.post("/chat", json={"question": ""}, headers=_auth())
    assert r.status_code == 422


def test_metrics_counts_usage(client):
    client.post("/chat", json={"question": "q1"}, headers=_auth())
    r = client.get("/metrics", headers=_auth())
    assert r.status_code == 200
    m = r.json()
    assert m["chat_requests"] >= 1
    assert m["tool_calls"] >= 1


def test_all_keys_cooling_returns_503(client, monkeypatch):
    async def boom(question, *, history=None, chat=None):
        raise AllKeysCoolingDown()

    monkeypatch.setattr(api, "run_agent", boom)
    r = client.post("/chat", json={"question": "hi"}, headers=_auth())
    assert r.status_code == 503


def test_agent_error_returns_500(client, monkeypatch):
    async def boom(question, *, history=None, chat=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(api, "run_agent", boom)
    r = client.post("/chat", json={"question": "hi"}, headers=_auth())
    assert r.status_code == 500
    assert "Agent error" in r.json()["detail"]


def test_cors_header_present(client):
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_chat_returns_session_id(client):
    r = client.post("/chat", json={"question": "hi"}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["session_id"]  # a new session id is minted


def test_session_memory_carries_history(client, monkeypatch):
    """Second turn with the same session_id should receive the prior turn as history."""
    seen = {}

    async def capture(question, *, history=None, chat=None):
        seen["len"] = len(history or [])
        return AgentResult(answer=f"echo {question}", steps=1, tool_calls=[])

    monkeypatch.setattr(api, "run_agent", capture)

    r1 = client.post("/chat", json={"question": "about torvalds"}, headers=_auth())
    sid = r1.json()["session_id"]
    assert seen["len"] == 0  # first turn: no history

    r2 = client.post(
        "/chat",
        json={"question": "how many repos does the above user have?", "session_id": sid},
        headers=_auth(),
    )
    assert r2.json()["session_id"] == sid
    assert seen["len"] == 2  # second turn sees the prior user+model messages
