"""Tests for the tool functions (response shaping) and their arg schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import tools
from app.schemas import (
    ARG_SCHEMAS,
    GetRepoInfoArgs,
    ListRecentCommitsArgs,
    ListUserReposArgs,
    FUNCTION_DECLARATIONS,
)


# --- tool response shaping (via faked GitHub) ---
async def test_get_repo_info_shapes_response(make_fake_http):
    async with make_fake_http() as c:
        r = await tools.get_repo_info("fastapi", "fastapi", http_client=c)
    assert r["full_name"] == "fastapi/fastapi"
    assert r["stars"] == 102629
    assert r["primary_language"] == "Python"


async def test_get_user_info_shapes_response(make_fake_http):
    async with make_fake_http() as c:
        u = await tools.get_user_info("torvalds", http_client=c)
    assert u["login"] == "torvalds"
    assert u["followers"] == 325253


async def test_list_languages_percentages(make_fake_http):
    async with make_fake_http() as c:
        r = await tools.list_languages("fastapi", "fastapi", http_client=c)
    # 800000/1000000 = 80%, sorted descending
    assert r["languages"]["Python"] == 80.0
    assert r["languages"]["HTML"] == 15.0
    assert list(r["languages"])[0] == "Python"


async def test_list_recent_commits_shape(make_fake_http):
    async with make_fake_http() as c:
        r = await tools.list_recent_commits("fastapi", "fastapi", limit=2, http_client=c)
    assert r["count"] == 2
    first = r["commits"][0]
    assert first["sha"] == "abc1234"            # truncated to 7 chars
    assert first["message"] == "Fix bug"        # first line only
    assert first["author"] == "Alice"


# --- schema validation ---
def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        GetRepoInfoArgs.model_validate({"owner": "a", "repo": "b", "branch": "main"})


def test_missing_required_rejected():
    with pytest.raises(ValidationError):
        GetRepoInfoArgs.model_validate({"owner": "a"})


def test_empty_string_rejected():
    with pytest.raises(ValidationError):
        GetRepoInfoArgs.model_validate({"owner": " ", "repo": "b"})


@pytest.mark.parametrize("limit,ok", [(1, True), (5, True), (20, True), (0, False), (21, False)])
def test_commit_limit_bounds(limit, ok):
    payload = {"owner": "a", "repo": "b", "limit": limit}
    if ok:
        assert ListRecentCommitsArgs.model_validate(payload).limit == limit
    else:
        with pytest.raises(ValidationError):
            ListRecentCommitsArgs.model_validate(payload)


def test_commit_limit_default():
    assert ListRecentCommitsArgs.model_validate({"owner": "a", "repo": "b"}).limit == 5


async def test_list_user_repos_shape_async(make_fake_http):
    async with make_fake_http() as c:
        r = await tools.list_user_repos("torvalds", limit=2, http_client=c)
    assert r["user"] == "torvalds"
    assert r["count"] == 2
    assert r["repos"][0]["name"] == "linux"
    assert r["repos"][0]["stars"] == 180000
    assert r["repos"][0]["language"] == "C"


def test_user_repos_sort_validation():
    # valid sort accepted
    assert ListUserReposArgs.model_validate({"username": "x", "sort": "created"}).sort == "created"
    # invalid sort rejected
    with pytest.raises(ValidationError):
        ListUserReposArgs.model_validate({"username": "x", "sort": "bogus"})


@pytest.mark.parametrize("limit,ok", [(1, True), (30, True), (0, False), (31, False)])
def test_user_repos_limit_bounds(limit, ok):
    payload = {"username": "x", "limit": limit}
    if ok:
        assert ListUserReposArgs.model_validate(payload).limit == limit
    else:
        with pytest.raises(ValidationError):
            ListUserReposArgs.model_validate(payload)


def test_user_repos_defaults():
    m = ListUserReposArgs.model_validate({"username": "x"})
    assert m.limit == 10 and m.sort == "updated"


def test_arg_schemas_cover_all_tools():
    assert set(ARG_SCHEMAS) == {
        "get_repo_info", "get_user_info", "list_languages",
        "list_recent_commits", "list_user_repos",
    }


def test_function_declarations_names():
    names = [d.name for d in FUNCTION_DECLARATIONS]
    assert names == [
        "get_repo_info", "get_user_info", "list_languages",
        "list_recent_commits", "list_user_repos",
    ]
