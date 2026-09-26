"""Tests for the Groq provider loop (faked Groq client + faked GitHub)."""

from __future__ import annotations

import json
import types

import pytest

from app import agent


# ---- fakes shaped like the Groq SDK response objects ----
def _msg_tool_call(tool_id, name, args: dict):
    fn = types.SimpleNamespace(name=name, arguments=json.dumps(args))
    tc = types.SimpleNamespace(id=tool_id, function=fn, type="function")
    message = types.SimpleNamespace(content="", tool_calls=[tc])
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _msg_text(text):
    message = types.SimpleNamespace(content=text, tool_calls=None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _FakeGroqClient:
    """Returns scripted completion responses; records the messages it received."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

        parent = self

        class _Completions:
            def create(self, **kwargs):
                parent.calls.append(kwargs["messages"])
                return parent._scripted.pop(0)

        self.chat = types.SimpleNamespace(completions=_Completions())


@pytest.fixture
def groq_env(monkeypatch, patch_client):
    """Force the Groq path, give it a key, and fake GitHub."""
    patch_client()  # faked GitHub transport
    # ensure key_manager hands out a key on the groq path
    from app import key_manager as km_mod
    monkeypatch.setattr(agent, "key_manager", km_mod.KeyManager(["GROQ_KEY_1"]))
    return monkeypatch


async def test_groq_single_tool(groq_env):
    fake = _FakeGroqClient([
        _msg_tool_call("call_1", "get_repo_info", {"owner": "fastapi", "repo": "fastapi"}),
        _msg_text("fastapi/fastapi has 102,629 stars."),
    ])
    groq_env.setattr(agent, "_groq_client", lambda key: fake)

    res = await agent._run_groq("stars of fastapi?")
    assert res.tool_calls[0]["name"] == "get_repo_info"
    assert res.tool_calls[0]["result"]["stars"] == 102629
    assert "102,629" in res.answer
    # the tool result was threaded back as a 'tool' message
    last_messages = fake.calls[-1]
    assert any(m.get("role") == "tool" for m in last_messages)


async def test_groq_chained_two_tools(groq_env):
    fake = _FakeGroqClient([
        _msg_tool_call("c1", "get_repo_info", {"owner": "fastapi", "repo": "fastapi"}),
        _msg_tool_call("c2", "get_user_info", {"username": "torvalds"}),
        _msg_text("compared."),
    ])
    groq_env.setattr(agent, "_groq_client", lambda key: fake)

    res = await agent._run_groq("compare fastapi and torvalds")
    assert [c["name"] for c in res.tool_calls] == ["get_repo_info", "get_user_info"]
    assert res.tool_calls[1]["result"]["followers"] == 325253


async def test_groq_invalid_args_fed_back(groq_env):
    fake = _FakeGroqClient([
        _msg_tool_call("c1", "get_repo_info", {"owner": "fastapi"}),  # missing repo
        _msg_text("need both owner and repo"),
    ])
    groq_env.setattr(agent, "_groq_client", lambda key: fake)

    res = await agent._run_groq("bad")
    assert "error" in res.tool_calls[0]["result"]


async def test_groq_history_seeded(groq_env):
    fake = _FakeGroqClient([_msg_text("ok")])
    groq_env.setattr(agent, "_groq_client", lambda key: fake)

    history = [
        {"role": "user", "text": "about torvalds"},
        {"role": "model", "text": "torvalds has 325k followers"},
    ]
    await agent._run_groq("how many repos does the above user have?", history=history)
    sent = fake.calls[0]
    # system + 2 history + 1 user
    roles = [m["role"] for m in sent]
    assert roles[0] == "system"
    assert "assistant" in roles and roles.count("user") >= 2
