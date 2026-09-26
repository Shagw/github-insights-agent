"""GitHub Insights Agent — evaluation set.

Unit tests check code correctness; this eval checks AGENT BEHAVIOR: given a
realistic question, does the agent (a) call the right tool(s), (b) ground its
answer in the returned data, or (c) correctly refuse when out of scope?

Each case:
  id             : stable identifier
  category       : single_tool | multi_tool | refuse
  question       : the user question
  expected_tools : the set of tool names we expect to be called (order-agnostic).
                   Empty list means "should call NO tools" (refuse / direct answer).
  must_contain   : substrings the final answer should contain (case-insensitive).
                   For refuse cases this is a word signalling the decline.
  notes          : grader guidance

The cases use two well-known public entities so live runs are stable:
  repo  fastapi/fastapi   (Python web framework)
  user  torvalds          (Linus Torvalds)
"""

EVAL_SET = [
    # ---------------- single_tool ----------------
    {"id": "s01", "category": "single_tool",
     "question": "How many stars does the fastapi/fastapi repository have?",
     "expected_tools": ["get_repo_info"], "must_contain": ["star"],
     "notes": "repo star count -> get_repo_info"},
    {"id": "s02", "category": "single_tool",
     "question": "What is the primary programming language of fastapi/fastapi?",
     "expected_tools": ["get_repo_info"], "must_contain": ["python"],
     "notes": "primary language field"},
    {"id": "s03", "category": "single_tool",
     "question": "Give me a summary of the fastapi/fastapi repo.",
     "expected_tools": ["get_repo_info"], "must_contain": ["fastapi"],
     "notes": "general repo summary"},
    {"id": "s04", "category": "single_tool",
     "question": "How many followers does the GitHub user torvalds have?",
     "expected_tools": ["get_user_info"], "must_contain": ["follower"],
     "notes": "user profile -> get_user_info"},
    {"id": "s05", "category": "single_tool",
     "question": "Where is the GitHub user torvalds located?",
     "expected_tools": ["get_user_info"], "must_contain": [],
     "notes": "user location field"},
    {"id": "s06", "category": "single_tool",
     "question": "What languages is fastapi/fastapi written in?",
     "expected_tools": ["list_languages"], "must_contain": ["python"],
     "notes": "language breakdown -> list_languages"},
    {"id": "s07", "category": "single_tool",
     "question": "Show me the most recent commits on fastapi/fastapi.",
     "expected_tools": ["list_recent_commits"], "must_contain": [],
     "notes": "recent activity -> list_recent_commits"},
    {"id": "s08", "category": "single_tool",
     "question": "How many open issues does fastapi/fastapi have?",
     "expected_tools": ["get_repo_info"], "must_contain": ["issue"],
     "notes": "open issues field"},

    # ---------------- multi_tool ----------------
    {"id": "m01", "category": "multi_tool",
     "question": "Compare the star count of fastapi/fastapi with the follower "
                 "count of the user torvalds.",
     "expected_tools": ["get_repo_info", "get_user_info"], "must_contain": [],
     "notes": "needs both a repo and a user lookup"},
    {"id": "m02", "category": "multi_tool",
     "question": "For fastapi/fastapi, tell me its star count and its language "
                 "breakdown.",
     "expected_tools": ["get_repo_info", "list_languages"], "must_contain": ["python"],
     "notes": "repo facts + language breakdown"},
    {"id": "m03", "category": "multi_tool",
     "question": "Summarize fastapi/fastapi and list its most recent commits.",
     "expected_tools": ["get_repo_info", "list_recent_commits"], "must_contain": [],
     "notes": "repo summary + recent commits"},

    # ---------------- refuse (out of scope) ----------------
    {"id": "r01", "category": "refuse",
     "question": "What's the weather in Paris today?",
     "expected_tools": [], "must_contain": ["github"],
     "notes": "not a GitHub question -> should decline, no tool call"},
    {"id": "r02", "category": "refuse",
     "question": "Write me a poem about the ocean.",
     "expected_tools": [], "must_contain": ["github"],
     "notes": "off-topic creative request -> decline"},
    {"id": "r03", "category": "refuse",
     "question": "What is 15 multiplied by 23?",
     "expected_tools": [], "must_contain": ["github"],
     "notes": "arithmetic, not GitHub -> decline"},
    {"id": "r04", "category": "refuse",
     "question": "Delete the fastapi/fastapi repository for me.",
     "expected_tools": [], "must_contain": [],
     "notes": "no such (write) tool exists -> cannot comply"},
]


def counts() -> dict[str, int]:
    """Category breakdown, handy for the harness summary."""
    out: dict[str, int] = {}
    for case in EVAL_SET:
        out[case["category"]] = out.get(case["category"], 0) + 1
    return out


if __name__ == "__main__":
    print(f"Total cases: {len(EVAL_SET)}")
    for cat, n in counts().items():
        print(f"  {cat}: {n}")
