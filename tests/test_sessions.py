"""Tests for the conversation session store (memory + fakeredis backends)."""

from __future__ import annotations

import pytest

from app.sessions import SessionStore, _MemoryBackend, _RedisBackend


async def test_memory_store_roundtrip():
    s = SessionStore(_MemoryBackend(), ttl=100, max_turns=10, kind="memory")
    assert await s.get_history("sid") == []
    await s.append_turn("sid", "about torvalds", "torvalds has 325k followers")
    h = await s.get_history("sid")
    assert h == [
        {"role": "user", "text": "about torvalds"},
        {"role": "model", "text": "torvalds has 325k followers"},
    ]


async def test_history_trimmed_to_max_turns():
    s = SessionStore(_MemoryBackend(), ttl=100, max_turns=6, kind="memory")
    for i in range(10):
        await s.append_turn("sid", f"q{i}", f"a{i}")
    h = await s.get_history("sid")
    assert len(h) == 6           # capped at max_turns
    assert h[-1] == {"role": "model", "text": "a9"}  # keeps the most recent


async def test_sessions_are_isolated():
    s = SessionStore(_MemoryBackend(), kind="memory")
    await s.append_turn("a", "qa", "aa")
    await s.append_turn("b", "qb", "ab")
    assert (await s.get_history("a"))[0]["text"] == "qa"
    assert (await s.get_history("b"))[0]["text"] == "qb"


async def test_fakeredis_backend_roundtrip():
    fr = pytest.importorskip("fakeredis.aioredis")
    client = fr.FakeRedis(decode_responses=True)
    s = SessionStore(_RedisBackend(client), ttl=100, max_turns=12, kind="redis")
    await s.append_turn("x", "about Shagw", "Shagw has 23 repos")
    h = await s.get_history("x")
    assert h[-1]["text"] == "Shagw has 23 repos"


async def test_missing_session_returns_empty():
    s = SessionStore(_MemoryBackend(), kind="memory")
    assert await s.get_history("nope") == []
