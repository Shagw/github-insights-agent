"""
sessions.py — conversation memory, so follow-up questions like
"what repos does the above user have?" resolve against earlier turns.

Storage: Redis (server-side), keyed by session id, value = JSON list of
{role, text} messages, with a TTL so idle conversations auto-expire (Redis
handles expiry natively — no cleanup code).

Resilience: if Redis is unreachable we FALL BACK to an in-memory dict and log a
warning, so the app still works locally / in tests. Same async interface either
way. (Production would rely on Redis for persistence + multi-instance sharing.)

Everything is async (redis.asyncio) to fit the async server.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import MAX_HISTORY_TURNS, REDIS_URL, SESSION_TTL

logger = logging.getLogger("github_agent.sessions")


class _MemoryBackend:
    """Fallback store: an in-process dict with manual TTL. Single-instance only."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}  # id -> (expires_at, json)

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.time() >= expires_at:
            self._data.pop(key, None)
            return None
        return value

    async def set_with_ttl(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = (time.time() + ttl, value)

    async def ping(self) -> bool:
        return True


class _RedisBackend:
    """Redis-backed store using redis.asyncio."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set_with_ttl(self, key: str, value: str, ttl: int) -> None:
        await self._client.set(key, value, ex=ttl)

    async def ping(self) -> bool:
        return bool(await self._client.ping())


class SessionStore:
    """Async conversation-history store with a Redis backend + memory fallback."""

    def __init__(self, backend: Any, *, ttl: int = SESSION_TTL,
                 max_turns: int = MAX_HISTORY_TURNS, kind: str = "memory"):
        self._backend = backend
        self._ttl = ttl
        self._max_turns = max_turns
        self.kind = kind  # "redis" or "memory" — for logging / introspection

    @staticmethod
    def _key(session_id: str) -> str:
        return f"session:{session_id}"

    async def get_history(self, session_id: str) -> list[dict[str, str]]:
        """Return the stored [{role, text}, ...] for a session (or [])."""
        raw = await self._backend.get(self._key(session_id))
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    async def append_turn(self, session_id: str, user_text: str, agent_text: str) -> None:
        """Append a user+agent exchange, trimmed to the last N turns, refresh TTL."""
        history = await self.get_history(session_id)
        history.append({"role": "user", "text": user_text})
        history.append({"role": "model", "text": agent_text})
        # keep only the most recent max_turns messages (each turn = 2 messages)
        if len(history) > self._max_turns:
            history = history[-self._max_turns:]
        await self._backend.set_with_ttl(
            self._key(session_id), json.dumps(history), self._ttl
        )


async def build_session_store() -> SessionStore:
    """Try Redis; fall back to in-memory if it's unreachable."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(REDIS_URL, decode_responses=True)
        backend = _RedisBackend(client)
        if await backend.ping():
            logger.info("Sessions: using Redis at %s", REDIS_URL)
            return SessionStore(backend, kind="redis")
    except Exception as e:  # noqa: BLE001 - any connection/import problem -> fallback
        logger.warning("Sessions: Redis unavailable (%s); using in-memory fallback", e)

    return SessionStore(_MemoryBackend(), kind="memory")
