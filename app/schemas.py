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

import google.generativeai as genai
from pydantic import BaseModel, ConfigDict, field_validator


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


# Maps a tool name -> its Pydantic validator. The agent uses this to validate
# arguments before dispatching. Keeping it as a dict makes adding tools trivial.
ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "get_repo_info": GetRepoInfoArgs,
    "get_user_info": GetUserInfoArgs,
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

# The full set of declarations handed to the model as `tools=[...]`.
FUNCTION_DECLARATIONS = [
    get_repo_info_declaration,
    get_user_info_declaration,
]
