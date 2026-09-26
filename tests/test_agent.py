"""Tests for the async agent loop (Reason -> Act -> Observe)."""

from __future__ import annotations

from app import agent
from tests.conftest import FakeChat, fc_response, text_response


async def test_single_tool_question(patch_client):
    patch_client()  # faked GitHub
    chat = FakeChat([
        fc_response("get_repo_info", {"owner": "fastapi", "repo": "fastapi"}),
        text_response("fastapi has 102,629 stars."),
    ])
    res = await agent.run_agent("How many stars does fastapi have?", chat=chat)
    assert res.steps == 2
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0]["name"] == "get_repo_info"
    assert res.tool_calls[0]["result"]["stars"] == 102629
    assert "102,629" in res.answer


async def test_chained_two_tools(patch_client):
    patch_client()
    chat = FakeChat([
        fc_response("get_repo_info", {"owner": "fastapi", "repo": "fastapi"}),
        fc_response("get_user_info", {"username": "torvalds"}),
        text_response("Compared them."),
    ])
    res = await agent.run_agent("Compare fastapi to torvalds", chat=chat)
    assert res.steps == 3
    assert [c["name"] for c in res.tool_calls] == ["get_repo_info", "get_user_info"]
    assert res.tool_calls[1]["result"]["followers"] == 325253


async def test_invalid_args_fed_back(patch_client):
    patch_client()
    chat = FakeChat([
        fc_response("get_repo_info", {"owner": "fastapi"}),  # missing repo
        text_response("I need both owner and repo."),
    ])
    res = await agent.run_agent("bad", chat=chat)
    assert "error" in res.tool_calls[0]["result"]
    assert "Invalid arguments" in res.tool_calls[0]["result"]["error"]


async def test_unknown_tool_refused(patch_client):
    patch_client()
    chat = FakeChat([
        fc_response("delete_repo", {"owner": "x", "repo": "y"}),
        text_response("Can't do that."),
    ])
    res = await agent.run_agent("delete", chat=chat)
    assert "Unknown tool" in res.tool_calls[0]["result"]["error"]


async def test_tool_error_surfaced(patch_client):
    patch_client()  # default handler returns 404 for unknown repos
    chat = FakeChat([
        fc_response("get_repo_info", {"owner": "nope", "repo": "nope"}),
        text_response("That repo wasn't found."),
    ])
    res = await agent.run_agent("info on nope/nope", chat=chat)
    assert "error" in res.tool_calls[0]["result"]


async def test_direct_text_answer_no_tool(patch_client):
    patch_client()
    chat = FakeChat([text_response("I only answer GitHub questions.")])
    res = await agent.run_agent("what's the weather?", chat=chat)
    assert res.steps == 1
    assert res.tool_calls == []
    assert "GitHub" in res.answer
