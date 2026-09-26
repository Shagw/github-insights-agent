#!/usr/bin/env python
"""
demo.py — drive the running GitHub Insights Agent API with example questions.

Start the server first (see README):
    uvicorn app.api:app --reload

Then run:
    python demo.py
    python demo.py "How many stars does fastapi/fastapi have?"

Reads API_KEY from the environment / .env so it can authenticate to /chat.
"""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"))

BASE_URL = os.getenv("DEMO_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "").strip()

EXAMPLE_QUESTIONS = [
    "How many stars does the fastapi/fastapi repository have?",
    "What languages is fastapi/fastapi written in?",
    "How many followers does the GitHub user torvalds have?",
    "Compare the star count of fastapi/fastapi with torvalds's follower count.",
    "What's the weather in Paris?",  # out of scope -> should decline
]


def ask(client: httpx.Client, question: str) -> None:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    print(f"\n\033[1mQ:\033[0m {question}")
    try:
        r = client.post(f"{BASE_URL}/chat", json={"question": question}, headers=headers, timeout=60)
    except httpx.HTTPError as e:
        print(f"  [request failed: {e}] — is the server running at {BASE_URL}?")
        return
    if r.status_code != 200:
        print(f"  [HTTP {r.status_code}] {r.text}")
        return
    body = r.json()
    tools = ", ".join(tc["name"] for tc in body["tool_calls"]) or "(none)"
    print(f"\033[1mA:\033[0m {body['answer']}")
    print(f"   tools used: {tools} | steps: {body['steps']} | request_id: {body['request_id']}")


def main() -> None:
    # health check first
    with httpx.Client() as client:
        try:
            h = client.get(f"{BASE_URL}/health", timeout=5)
            print(f"health: {h.json()} ({BASE_URL})")
        except httpx.HTTPError:
            print(f"Could not reach {BASE_URL}. Start it with: uvicorn app.api:app --reload")
            sys.exit(1)

        questions = sys.argv[1:] or EXAMPLE_QUESTIONS
        for q in questions:
            ask(client, q)


if __name__ == "__main__":
    main()
