"""
tools.py — the functions the AGENT is allowed to call.

Each tool:
  * uses the GitHubClient (all I/O + resilience lives there),
  * returns a SMALL, clean dict with just the fields worth reasoning about
    (fewer tokens for the LLM, less chance of confusion),
  * is async, matching the async agent loop and client.

We keep the response shape tight on purpose: GitHub's raw JSON has ~100 fields;
the model only needs a handful to answer questions.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.github_client import GitHubClient


async def get_repo_info(
    owner: str, repo: str, *, http_client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Fetch summary facts about a public repository.

    Args:
        owner: the user or org that owns the repo (e.g. "tiangolo")
        repo:  the repository name (e.g. "fastapi")

    `http_client` is an optional injected httpx client used by tests to avoid
    real network calls; in production it is left as None and the tool owns its
    own client.
    """
    async with GitHubClient(client=http_client) as gh:
        data = await gh.get(f"/repos/{owner}/{repo}")
    return {
        "full_name": data.get("full_name"),
        "description": data.get("description"),
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "open_issues": data.get("open_issues_count"),
        "primary_language": data.get("language"),
        "topics": data.get("topics", []),
        "url": data.get("html_url"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


async def get_user_info(
    username: str, *, http_client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Fetch public profile facts about a GitHub user or organization.

    Args:
        username: the GitHub login (e.g. "torvalds")

    `http_client` is an optional injected httpx client for tests.
    """
    async with GitHubClient(client=http_client) as gh:
        data = await gh.get(f"/users/{username}")
    return {
        "login": data.get("login"),
        "name": data.get("name"),
        "bio": data.get("bio"),
        "company": data.get("company"),
        "location": data.get("location"),
        "public_repos": data.get("public_repos"),
        "followers": data.get("followers"),
        "following": data.get("following"),
        "url": data.get("html_url"),
        "created_at": data.get("created_at"),
    }
