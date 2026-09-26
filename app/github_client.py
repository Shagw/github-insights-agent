"""
github_client.py — the ONLY place that talks to the GitHub REST API.

Design principle: isolate external I/O behind a client so that
  * authentication (optional token) lives in one place,
  * resilience (timeouts, retries, caching, rate-limit handling) lives in one
    place — every tool inherits it for free,
  * the tools that the agent calls stay pure and easy to test (we can fake this).

Resilience implemented here:
  1. Timeouts on every request (fail fast, don't hang).
  2. Transient vs. permanent error classification — we only retry transient ones
     (timeouts, connection errors, 5xx). Permanent errors (404, primary
     rate-limit 403, 4xx) are never retried because the answer won't change.
  3. Retry with exponential backoff + jitter to avoid a thundering herd.
  4. A small in-memory TTL cache so identical GETs within a short window don't
     re-hit GitHub — cuts latency AND conserves the 60 req/hr rate limit.
  5. Graceful degradation — failures become a structured GitHubError the agent
     can relay to the user instead of crashing.

Everything is async (httpx.AsyncClient) so the FastAPI server is never blocked
on an outbound GitHub call while serving concurrent requests.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Any

import httpx

GITHUB_API_BASE = "https://api.github.com"

# Timeout for a single GitHub call. Kept here so every request shares it.
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Retry policy for TRANSIENT failures only.
MAX_RETRIES = 3          # total attempts = 1 initial + (MAX_RETRIES - 1) retries
BASE_BACKOFF = 0.5       # seconds; grows exponentially: 0.5, 1.0, 2.0 ...

# In-memory cache time-to-live (seconds). GitHub facts don't change second-to-second.
CACHE_TTL = 60.0


class GitHubError(Exception):
    """A GitHub/HTTP failure surfaced to the tool/agent layer.

    `status`    — HTTP status code, or None for network-level failures.
    `transient` — True if retrying might succeed (timeout, connection, 5xx);
                  False for permanent errors (404, primary rate-limit, 4xx).
    """

    def __init__(self, message: str, status: int | None = None, transient: bool = False):
        super().__init__(message)
        self.status = status
        self.transient = transient


def _build_headers() -> dict[str, str]:
    """Standard GitHub headers, plus the token if one is configured.

    Without a token: 60 requests/hour. With one: 5000/hour.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-insights-agent",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# --------------------------------------------------------------------------
# Module-level TTL cache, shared across client instances.
# Keyed by (path, sorted-params). Value is (expires_at, json_payload).
# --------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_key(path: str, params: dict[str, Any] | None) -> str:
    if not params:
        return path
    items = sorted((str(k), str(v)) for k, v in params.items())
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


def clear_cache() -> None:
    """Clear the shared cache (used by tests)."""
    _CACHE.clear()


class GitHubClient:
    """Thin async wrapper over the GitHub REST API with built-in resilience.

    Usage:
        async with GitHubClient() as gh:
            data = await gh.get("/repos/fastapi/fastapi")

    Retry/backoff/cache knobs are constructor args so tests can disable sleeping.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_retries: int = MAX_RETRIES,
        base_backoff: float = BASE_BACKOFF,
        cache_ttl: float = CACHE_TTL,
        use_cache: bool = True,
        sleep: Any = asyncio.sleep,
    ):
        self._client = client
        self._owns_client = client is None
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._cache_ttl = cache_ttl
        self._use_cache = use_cache
        self._sleep = sleep  # injectable so tests run instantly

    async def __aenter__(self) -> "GitHubClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                headers=_build_headers(),
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,  # GitHub returns 301 for renamed/transferred repos
            )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def _classify(self, resp: httpx.Response, path: str) -> None:
        """Raise GitHubError for error responses, tagging transient vs permanent."""
        code = resp.status_code

        if code == 404:
            raise GitHubError(f"Not found: {path}", status=404, transient=False)

        # Primary rate limit: permanent for this window — retrying won't help.
        if code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubError(
                "GitHub API rate limit exceeded. Add a GITHUB_TOKEN to raise the limit.",
                status=403,
                transient=False,
            )

        # Server-side errors are transient — worth a retry.
        if code >= 500:
            raise GitHubError(
                f"GitHub server error {code} for {path}", status=code, transient=True
            )

        # Other 4xx are permanent client errors.
        if code >= 400:
            raise GitHubError(
                f"GitHub returned {code} for {path}", status=code, transient=False
            )

    async def _get_once(self, path: str, params: dict[str, Any] | None) -> Any:
        """A single attempt: perform the GET, classify errors, return JSON."""
        try:
            resp = await self._client.get(path, params=params)
        except httpx.TimeoutException as e:
            raise GitHubError(f"GitHub request timed out: {e}", status=None, transient=True) from e
        except httpx.HTTPError as e:
            # Connection errors etc. — transient at the network level.
            raise GitHubError(f"Network error talking to GitHub: {e}", status=None, transient=True) from e

        self._classify(resp, path)
        return resp.json()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a GitHub path with caching + retry-on-transient, returning JSON."""
        if self._client is None:
            raise RuntimeError("GitHubClient must be used as an async context manager")

        key = _cache_key(path, params)

        # --- cache read ---
        if self._use_cache:
            cached = _CACHE.get(key)
            if cached is not None:
                expires_at, payload = cached
                if time.time() < expires_at:
                    return payload
                _CACHE.pop(key, None)  # expired

        # --- attempt with retry on transient errors ---
        last_error: GitHubError | None = None
        for attempt in range(self._max_retries):
            try:
                payload = await self._get_once(path, params)
            except GitHubError as e:
                if not e.transient:
                    raise  # permanent — don't waste a retry
                last_error = e
                if attempt < self._max_retries - 1:
                    # exponential backoff + jitter
                    delay = self._base_backoff * (2 ** attempt)
                    delay += random.uniform(0, self._base_backoff)
                    await self._sleep(delay)
                    continue
                raise  # retries exhausted
            else:
                if self._use_cache:
                    _CACHE[key] = (time.time() + self._cache_ttl, payload)
                return payload

        # Defensive; loop always returns or raises above.
        assert last_error is not None
        raise last_error
