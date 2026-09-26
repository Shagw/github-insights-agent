"""
github_client.py — the ONLY place that talks to the GitHub REST API.

Design principle: isolate external I/O behind a client so that
  * authentication (optional token) lives in one place,
  * resilience (timeouts, retries, rate-limit handling) can be added in one place later,
  * the tools that the agent calls stay pure and easy to test (we can fake this client).

Everything here is async (httpx.AsyncClient) so the FastAPI server is never blocked
on an outbound GitHub call while serving concurrent requests.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

GITHUB_API_BASE = "https://api.github.com"

# Timeout for a single GitHub call. Kept here so every request shares it.
# (We tune/extend this in the resilience task.)
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class GitHubError(Exception):
    """Raised when GitHub returns an error we want the agent/tool layer to see.

    `status` is the HTTP status code (or None for network-level failures) so
    callers can distinguish 404 (not found) from 403 (rate limit) from timeouts.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _build_headers() -> dict[str, str]:
    """Standard GitHub headers, plus the token if one is configured.

    Without a token: 60 requests/hour. With one: 5000/hour.
    The token is optional — the client works either way.
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


class GitHubClient:
    """Thin async wrapper over the GitHub REST API.

    Usage:
        async with GitHubClient() as gh:
            data = await gh.get("/repos/tiangolo/fastapi")
    """

    def __init__(self, client: httpx.AsyncClient | None = None):
        # Allow injecting a client (real or fake) for testing. If none is given,
        # we create and own one.
        self._client = client
        self._owns_client = client is None

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

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a GitHub path and return parsed JSON.

        Translates GitHub/HTTP failures into GitHubError with a status code so
        the tool layer can respond helpfully instead of crashing.
        """
        if self._client is None:
            raise RuntimeError("GitHubClient must be used as an async context manager")

        try:
            resp = await self._client.get(path, params=params)
        except httpx.TimeoutException as e:
            raise GitHubError(f"GitHub request timed out: {e}", status=None) from e
        except httpx.HTTPError as e:
            raise GitHubError(f"Network error talking to GitHub: {e}", status=None) from e

        if resp.status_code == 404:
            raise GitHubError(f"Not found: {path}", status=404)

        # 403 with the rate-limit marker means we've exhausted the quota.
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubError(
                "GitHub API rate limit exceeded. Add a GITHUB_TOKEN to raise the limit.",
                status=403,
            )

        if resp.status_code >= 400:
            raise GitHubError(
                f"GitHub returned {resp.status_code} for {path}", status=resp.status_code
            )

        return resp.json()
