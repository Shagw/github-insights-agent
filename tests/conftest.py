"""
conftest.py — shared fixtures and fakes so every test runs OFFLINE.

Two fakes make the whole system deterministic without network or Gemini:
  * a faked GitHub API via httpx.MockTransport (fixture: `gh_handler` / `fake_http`),
  * a scripted FakeChat plus helpers to build Gemini-shaped proto responses.
"""

from __future__ import annotations

import httpx
import pytest
import google.generativeai as genai

from app.github_client import clear_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the client's TTL cache before each test so tests don't leak state."""
    clear_cache()
    yield
    clear_cache()


# --------------------------------------------------------------------------
# Faked GitHub
# --------------------------------------------------------------------------
def default_gh_handler(request: httpx.Request) -> httpx.Response:
    """A stable set of canned GitHub responses used across tool/agent tests."""
    p = request.url.path
    if p == "/repos/fastapi/fastapi":
        return httpx.Response(200, json={
            "full_name": "fastapi/fastapi", "description": "FastAPI framework",
            "stargazers_count": 102629, "forks_count": 8500, "open_issues_count": 40,
            "language": "Python", "topics": ["api", "async"],
            "html_url": "https://github.com/fastapi/fastapi",
            "created_at": "2018-12-08T08:21:47Z", "updated_at": "2024-01-01T00:00:00Z",
        })
    if p == "/repos/fastapi/fastapi/languages":
        return httpx.Response(200, json={"Python": 800000, "HTML": 150000, "CSS": 50000})
    if p == "/repos/fastapi/fastapi/commits":
        return httpx.Response(200, json=[
            {"sha": "abc1234def", "html_url": "u1",
             "commit": {"message": "Fix bug\n\nbody", "author": {"name": "Alice", "date": "2024-01-02T00:00:00Z"}}},
            {"sha": "beef5678aa", "html_url": "u2",
             "commit": {"message": "Add feature", "author": {"name": "Bob", "date": "2024-01-01T00:00:00Z"}}},
        ])
    if p == "/users/torvalds":
        return httpx.Response(200, json={
            "login": "torvalds", "name": "Linus Torvalds", "bio": None, "company": None,
            "location": "Portland", "public_repos": 8, "followers": 325253, "following": 0,
            "html_url": "https://github.com/torvalds", "created_at": "2011-09-03T15:26:22Z",
        })
    if p == "/users/torvalds/repos":
        return httpx.Response(200, json=[
            {"name": "linux", "full_name": "torvalds/linux", "description": "Linux kernel",
             "stargazers_count": 180000, "language": "C", "updated_at": "2024-01-02T00:00:00Z",
             "html_url": "https://github.com/torvalds/linux"},
            {"name": "subsurface", "full_name": "torvalds/subsurface", "description": "Dive log",
             "stargazers_count": 3000, "language": "C++", "updated_at": "2023-06-01T00:00:00Z",
             "html_url": "https://github.com/torvalds/subsurface"},
        ])
    if p == "/repos/nope/nope":
        return httpx.Response(404, json={"message": "Not Found"})
    return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def make_fake_http():
    """Return a factory that builds an httpx.AsyncClient over a MockTransport.

    Pass a custom handler for special cases; defaults to `default_gh_handler`.
    """
    def _factory(handler=default_gh_handler):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.com",
        )
    return _factory


@pytest.fixture
def patch_client(monkeypatch):
    """Patch GitHubClient.__aenter__ so tools/agent use a faked transport.

    Returns a function you call with a handler to activate the patch.
    """
    import app.github_client as gc

    def _activate(handler=default_gh_handler):
        real_async_client = httpx.AsyncClient

        def _aenter(self):
            async def _a():
                if self._client is None:
                    self._client = real_async_client(
                        transport=httpx.MockTransport(handler),
                        base_url="https://api.github.com",
                    )
                return self
            return _a()

        monkeypatch.setattr(gc.GitHubClient, "__aenter__", _aenter)

    return _activate


# --------------------------------------------------------------------------
# Faked Gemini
# --------------------------------------------------------------------------
def fc_response(name: str, args: dict):
    """Build a Gemini response containing a single function call."""
    part = genai.protos.Part(function_call=genai.protos.FunctionCall(name=name, args=args))
    content = genai.protos.Content(role="model", parts=[part])
    return genai.protos.GenerateContentResponse(candidates=[genai.protos.Candidate(content=content)])


def text_response(text: str):
    """Build a Gemini response containing a final text answer."""
    part = genai.protos.Part(text=text)
    content = genai.protos.Content(role="model", parts=[part])
    return genai.protos.GenerateContentResponse(candidates=[genai.protos.Candidate(content=content)])


class FakeChat:
    """A scripted stand-in for a Gemini chat session."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.sent = []

    def send_message(self, message):
        self.sent.append(message)
        return self._scripted.pop(0)
