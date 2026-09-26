"""GitHub Insights Agent — evaluation harness.

Scores each case in eval_set.py on two axes:
  1. tools_ok  — did the agent call exactly the expected set of tools?
                 (order-agnostic; empty expected set means "no tools").
  2. answer_ok — does the final answer contain all `must_contain` substrings?

A case PASSES when both are true. We report per-category and overall pass rates.

Modes:
  --self-test : grade SCRIPTED agent results (offline, no Gemini). Proves the
                grader logic itself is correct without spending quota.
  (default)   : run each case through the REAL agent (needs Gemini keys + network).

Usage:
    python -m eval.run_eval --self-test
    python -m eval.run_eval            # live
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from eval.eval_set import EVAL_SET, counts


@dataclass
class CaseResult:
    id: str
    category: str
    tools_ok: bool
    answer_ok: bool
    called_tools: list[str]
    answer: str

    @property
    def passed(self) -> bool:
        return self.tools_ok and self.answer_ok


def grade(case: dict, called_tools: list[str], answer: str) -> CaseResult:
    """Grade one agent outcome against its expected behavior."""
    expected = set(case["expected_tools"])
    got = set(called_tools)
    tools_ok = expected == got

    ans_lower = (answer or "").lower()
    answer_ok = all(sub.lower() in ans_lower for sub in case["must_contain"])

    return CaseResult(
        id=case["id"],
        category=case["category"],
        tools_ok=tools_ok,
        answer_ok=answer_ok,
        called_tools=called_tools,
        answer=answer,
    )


def summarize(results: list[CaseResult]) -> None:
    """Print per-category and overall pass rates."""
    by_cat: dict[str, list[CaseResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)

    print("\n================ EVAL RESULTS ================")
    for cat, rs in by_cat.items():
        passed = sum(1 for r in rs if r.passed)
        print(f"  {cat:12s}: {passed}/{len(rs)} passed")
    total_pass = sum(1 for r in results if r.passed)
    print("----------------------------------------------")
    print(f"  OVERALL     : {total_pass}/{len(results)} passed")

    # show any failures with detail
    fails = [r for r in results if not r.passed]
    if fails:
        print("\n--- failures ---")
        for r in fails:
            reasons = []
            if not r.tools_ok:
                reasons.append(f"tools={r.called_tools}")
            if not r.answer_ok:
                reasons.append(f"answer={r.answer[:70]!r}")
            print(f"  [{r.id}] {r.category}: {'; '.join(reasons)}")
    print("==============================================\n")


# --------------------------------------------------------------------------
# Live mode: run each case through the real agent.
# --------------------------------------------------------------------------
async def run_live() -> list[CaseResult]:
    from app.agent import run_agent

    results: list[CaseResult] = []
    for case in EVAL_SET:
        try:
            res = await run_agent(case["question"])
            called = [tc["name"] for tc in res.tool_calls]
            results.append(grade(case, called, res.answer))
        except Exception as e:  # noqa: BLE001
            results.append(grade(case, ["<error>"], f"ERROR: {type(e).__name__}: {e}"))
    return results


# --------------------------------------------------------------------------
# Self-test: grade scripted (perfect) outcomes to prove the grader works.
# --------------------------------------------------------------------------
def _scripted_outcome(case: dict) -> tuple[list[str], str]:
    """Produce an IDEAL outcome for a case, so a correct grader scores 15/15."""
    tools = list(case["expected_tools"])
    # Build an answer that contains every required substring.
    answer = "Based on the GitHub data: " + " ".join(case["must_contain"])
    if case["category"] == "refuse":
        answer = "I can only help with GitHub repositories and users."
    if not answer.strip():
        answer = "Here is the GitHub information you asked for."
    return tools, answer


def run_self_test() -> list[CaseResult]:
    results = []
    for case in EVAL_SET:
        tools, answer = _scripted_outcome(case)
        results.append(grade(case, tools, answer))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GitHub agent eval.")
    parser.add_argument("--self-test", action="store_true",
                        help="Grade scripted ideal outcomes (offline, no Gemini).")
    args = parser.parse_args()

    print("Eval set composition:", counts())

    if args.self_test:
        print("Mode: SELF-TEST (offline, scripted ideal outcomes)")
        results = run_self_test()
    else:
        print("Mode: LIVE (real agent — needs Gemini keys + network)")
        results = asyncio.run(run_live())

    summarize(results)


if __name__ == "__main__":
    main()
