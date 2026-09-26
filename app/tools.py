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


async def list_languages(
    owner: str, repo: str, *, http_client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Language breakdown for a public repository, as percentages of code.

    GitHub returns {language: bytes_of_code}; we convert to rounded percentages
    because the model reasons more usefully about "80% Python" than raw bytes.

    Args:
        owner: the user or org that owns the repo (e.g. "fastapi")
        repo:  the repository name (e.g. "fastapi")
    """
    async with GitHubClient(client=http_client) as gh:
        data = await gh.get(f"/repos/{owner}/{repo}/languages")

    total = sum(data.values()) if data else 0
    if total == 0:
        return {"repo": f"{owner}/{repo}", "languages": {}, "note": "No language data."}

    percentages = {
        lang: round(byte_count / total * 100, 1)
        for lang, byte_count in sorted(data.items(), key=lambda kv: kv[1], reverse=True)
    }
    return {"repo": f"{owner}/{repo}", "languages": percentages}


async def list_recent_commits(
    owner: str,
    repo: str,
    limit: int = 5,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """The most recent commits on a public repository's default branch.

    Args:
        owner: the user or org that owns the repo (e.g. "fastapi")
        repo:  the repository name (e.g. "fastapi")
        limit: how many recent commits to return (1-20, default 5)
    """
    async with GitHubClient(client=http_client) as gh:
        data = await gh.get(f"/repos/{owner}/{repo}/commits", params={"per_page": limit})

    commits = []
    for item in data if isinstance(data, list) else []:
        commit = item.get("commit", {}) or {}
        author = commit.get("author", {}) or {}
        message = (commit.get("message") or "").split("\n", 1)[0]  # first line only
        commits.append(
            {
                "sha": (item.get("sha") or "")[:7],
                "message": message,
                "author": author.get("name"),
                "date": author.get("date"),
                "url": item.get("html_url"),
            }
        )
    return {"repo": f"{owner}/{repo}", "count": len(commits), "commits": commits}


async def list_user_repos(
    username: str,
    limit: int = 10,
    sort: str = "updated",
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """List a public GitHub user's or organization's repositories.

    Args:
        username: the GitHub login (e.g. "torvalds")
        limit:    how many repos to return (1-30, default 10)
        sort:     one of "updated" (recent activity), "created", "pushed",
                  "full_name" (default "updated")
    """
    async with GitHubClient(client=http_client) as gh:
        data = await gh.get(
            f"/users/{username}/repos",
            params={"per_page": limit, "sort": sort},
        )

    repos = []
    for item in data if isinstance(data, list) else []:
        repos.append(
            {
                "name": item.get("name"),
                "full_name": item.get("full_name"),
                "description": item.get("description"),
                "stars": item.get("stargazers_count"),
                "language": item.get("language"),
                "updated_at": item.get("updated_at"),
                "url": item.get("html_url"),
            }
        )
    return {"user": username, "count": len(repos), "sort": sort, "repos": repos}
