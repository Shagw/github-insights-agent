"""
schemas.py — the CONTRACT between the LLM and the tools.

Two things live here, kept deliberately in sync:

1. Pydantic models (`*Args`) — the RUNTIME validation gate. The LLM's tool-call
   arguments are untrusted JSON; we validate them against these strict models
   (`extra="forbid"`) BEFORE executing anything. Malformed or hallucinated args
   become a catchable error we can hand back to the model instead of a crash.

2. Gemini FunctionDeclarations — the SPEC we hand to the model so it knows which
   tools exist, what each does, and how to fill the arguments. The descriptions
   are how the model decides *which* tool and *how* to fill args, so they matter.

Why declare tools explicitly (instead of letting the SDK infer them from the
Python functions)? Our real tool functions take an extra `http_client` kwarg for
testing that the model must never see. Declaring explicitly keeps the model's
view of each tool clean and under our control.
"""

from __future__ import annotations

from typing import Literal

import google.generativeai as genai
from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------
# 1. Pydantic argument schemas (runtime validation gate)
# --------------------------------------------------------------------------
class GetRepoInfoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject any field we didn't declare
    owner: str
    repo: str

    @field_validator("owner", "repo")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must be a nonempty string")
        return value


class GetUserInfoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str

    @field_validator("username")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("username must be a nonempty string")
        return value


class ListLanguagesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str
    repo: str

    @field_validator("owner", "repo")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must be a nonempty string")
        return value


class ListRecentCommitsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str
    repo: str
    # Bounded integer: the model may omit it (default 5) but never exceed 20.
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("owner", "repo")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must be a nonempty string")
        return value


class ListUserReposArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    limit: int = Field(default=10, ge=1, le=30)
    sort: Literal["updated", "created", "pushed", "full_name"] = "updated"

    @field_validator("username")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("username must be a nonempty string")
        return value


# Maps a tool name -> its Pydantic validator. The agent uses this to validate
# arguments before dispatching. Keeping it as a dict makes adding tools trivial.
ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "get_repo_info": GetRepoInfoArgs,
    "get_user_info": GetUserInfoArgs,
    "list_languages": ListLanguagesArgs,
    "list_recent_commits": ListRecentCommitsArgs,
    "list_user_repos": ListUserReposArgs,
}


# --------------------------------------------------------------------------
# 2. Gemini function declarations (what the model sees)
# --------------------------------------------------------------------------
# genai.protos.Schema uses OpenAPI-style types. STRING/OBJECT etc. come from
# genai.protos.Type. `required` lists the mandatory properties.
_Type = genai.protos.Type

get_repo_info_declaration = genai.protos.FunctionDeclaration(
    name="get_repo_info",
    description=(
        "Get summary facts about a public GitHub repository: stars, forks, open "
        "issues, primary language, topics, description, and timestamps. Use this "
        "when the user asks about a specific repository."
    ),
    parameters=genai.protos.Schema(
        type=_Type.OBJECT,
        properties={
            "owner": genai.protos.Schema(
                type=_Type.STRING,
                description="The user or organization that owns the repo, e.g. 'fastapi'.",
            ),
            "repo": genai.protos.Schema(
                type=_Type.STRING,
                description="The repository name, e.g. 'fastapi'.",
            ),
        },
        required=["owner", "repo"],
    ),
)

get_user_info_declaration = genai.protos.FunctionDeclaration(
    name="get_user_info",
    description=(
        "Get public profile facts about a GitHub user or organization: name, bio, "
        "company, location, number of public repos, followers, and following. Use "
        "this when the user asks about a person or organization on GitHub."
    ),
    parameters=genai.protos.Schema(
        type=_Type.OBJECT,
        properties={
            "username": genai.protos.Schema(
                type=_Type.STRING,
                description="The GitHub login/handle, e.g. 'torvalds'.",
            ),
        },
        required=["username"],
    ),
)

list_languages_declaration = genai.protos.FunctionDeclaration(
    name="list_languages",
    description=(
        "Get the programming-language breakdown of a public GitHub repository as "
        "percentages of code (e.g. Python 82%, HTML 12%). Use this when the user "
        "asks what languages a repository is written in or the language mix."
    ),
    parameters=genai.protos.Schema(
        type=_Type.OBJECT,
        properties={
            "owner": genai.protos.Schema(
                type=_Type.STRING,
                description="The user or organization that owns the repo, e.g. 'fastapi'.",
            ),
            "repo": genai.protos.Schema(
                type=_Type.STRING,
                description="The repository name, e.g. 'fastapi'.",
            ),
        },
        required=["owner", "repo"],
    ),
)

list_recent_commits_declaration = genai.protos.FunctionDeclaration(
    name="list_recent_commits",
    description=(
        "Get the most recent commits on a public GitHub repository's default "
        "branch, including short SHA, message, author, and date. Use this when the "
        "user asks about recent activity, latest changes, or recent commits."
    ),
    parameters=genai.protos.Schema(
        type=_Type.OBJECT,
        properties={
            "owner": genai.protos.Schema(
                type=_Type.STRING,
                description="The user or organization that owns the repo, e.g. 'fastapi'.",
            ),
            "repo": genai.protos.Schema(
                type=_Type.STRING,
                description="The repository name, e.g. 'fastapi'.",
            ),
            "limit": genai.protos.Schema(
                type=_Type.INTEGER,
                description="How many recent commits to return, 1-20 (default 5).",
            ),
        },
        required=["owner", "repo"],
    ),
)

list_user_repos_declaration = genai.protos.FunctionDeclaration(
    name="list_user_repos",
    description=(
        "List a public GitHub user's or organization's repositories, sorted by "
        "recent activity by default. Use this when the user asks what repos / "
        "projects someone has, or about their recent projects."
    ),
    parameters=genai.protos.Schema(
        type=_Type.OBJECT,
        properties={
            "username": genai.protos.Schema(
                type=_Type.STRING,
                description="The GitHub login/handle, e.g. 'torvalds'.",
            ),
            "limit": genai.protos.Schema(
                type=_Type.INTEGER,
                description="How many repositories to return, 1-30 (default 10).",
            ),
            "sort": genai.protos.Schema(
                type=_Type.STRING,
                description="Sort order: 'updated' (default), 'created', 'pushed', or 'full_name'.",
            ),
        },
        required=["username"],
    ),
)

# The full set of declarations handed to the model as `tools=[...]`.
FUNCTION_DECLARATIONS = [
    get_repo_info_declaration,
    get_user_info_declaration,
    list_languages_declaration,
    list_recent_commits_declaration,
    list_user_repos_declaration,
]


# --------------------------------------------------------------------------
# 3. Groq / OpenAI-style tool declarations (JSON-schema form)
# --------------------------------------------------------------------------
# Groq uses the OpenAI function-calling format: a list of
# {"type": "function", "function": {name, description, parameters(JSON schema)}}.
GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_repo_info",
            "description": (
                "Get summary facts about a public GitHub repository: stars, forks, "
                "open issues, primary language, topics, description, timestamps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Repo owner, e.g. 'fastapi'."},
                    "repo": {"type": "string", "description": "Repo name, e.g. 'fastapi'."},
                },
                "required": ["owner", "repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_info",
            "description": (
                "Get public profile facts about a GitHub user or organization: name, "
                "bio, company, location, public repos, followers, following."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "GitHub login, e.g. 'torvalds'."},
                },
                "required": ["username"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_languages",
            "description": (
                "Get the programming-language breakdown of a public GitHub repository "
                "as percentages of code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Repo owner, e.g. 'fastapi'."},
                    "repo": {"type": "string", "description": "Repo name, e.g. 'fastapi'."},
                },
                "required": ["owner", "repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_commits",
            "description": (
                "Get the most recent commits on a public repository's default branch "
                "(sha, message, author, date)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Repo owner, e.g. 'fastapi'."},
                    "repo": {"type": "string", "description": "Repo name, e.g. 'fastapi'."},
                    "limit": {"type": "integer", "description": "How many commits, 1-20 (default 5)."},
                },
                "required": ["owner", "repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_user_repos",
            "description": (
                "List a public GitHub user's or organization's repositories, sorted by "
                "recent activity by default. Use for 'what repos/projects does X have'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "GitHub login, e.g. 'torvalds'."},
                    "limit": {"type": "integer", "description": "How many repos, 1-30 (default 10)."},
                    "sort": {
                        "type": "string",
                        "enum": ["updated", "created", "pushed", "full_name"],
                        "description": "Sort order (default 'updated').",
                    },
                },
                "required": ["username"],
            },
        },
    },
]
