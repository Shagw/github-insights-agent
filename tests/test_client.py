"""Tests for the resilient GitHub client (retry, classification, caching)."""

from __future__ import annotations

import httpx
import pytest

from app.github_client import GitHubClient, GitHubError


async def _record_sleep():
    calls = []

    async def _sleep(d):
        calls.append(d)

    return calls, _sleep


async def test_permanent_404_not_retried(make_fake_http):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404, json={"message": "Not Found"})

    slept, fake_sleep = [], (lambda d: None)
    async with make_fake_http(handler) as c:
        gh = GitHubClient(client=c, use_cache=False, sleep=lambda d: _noop(slept, d))
        with pytest.raises(GitHubError) as ei:
            await gh.get("/repos/a/b")
    assert ei.value.status == 404 and ei.value.transient is False
    assert calls["n"] == 1  # not retried
    assert slept == []


async def _noop(store, d):
    store.append(d)


async def test_transient_500_recovers(make_fake_http):
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    slept = []
    async with make_fake_http(handler) as c:
        gh = GitHubClient(client=c, use_cache=False, max_retries=3,
                          sleep=lambda d: _noop(slept, d))
        result = await gh.get("/flaky")
    assert result == {"ok": True}
    assert state["n"] == 3          # failed twice, succeeded on third
    assert len(slept) == 2          # two backoff sleeps


async def test_transient_exhausts_and_raises(make_fake_http):
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        return httpx.Response(500)

    slept = []
    async with make_fake_http(handler) as c:
        gh = GitHubClient(client=c, use_cache=False, max_retries=3,
                          sleep=lambda d: _noop(slept, d))
        with pytest.raises(GitHubError) as ei:
            await gh.get("/always500")
    assert ei.value.transient is True and ei.value.status == 500
    assert state["n"] == 3          # exactly max_retries attempts


async def test_cache_serves_second_call(make_fake_http):
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        return httpx.Response(200, json={"v": state["n"]})

    async with make_fake_http(handler) as c:
        gh = GitHubClient(client=c, use_cache=True, sleep=lambda d: None)
        a = await gh.get("/cacheme")
        b = await gh.get("/cacheme")
    assert a == b == {"v": 1}
    assert state["n"] == 1          # second call served from cache


async def test_rate_limit_403_permanent(make_fake_http):
    def handler(request):
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0"}, json={"message": "limit"})

    async with make_fake_http(handler) as c:
        gh = GitHubClient(client=c, use_cache=False, sleep=lambda d: None)
        with pytest.raises(GitHubError) as ei:
            await gh.get("/repos/x/y")
    assert ei.value.status == 403 and ei.value.transient is False
