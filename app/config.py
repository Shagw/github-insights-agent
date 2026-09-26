"""
config.py — read all settings from the environment (.env) in one place.

Keeping config centralized means the rest of the code never touches os.getenv
directly, so there is a single source of truth for keys, model, and token.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env once, on import. Explicit path so it also works when the module is
# imported from scripts, tests, or a heredoc (find_dotenv() can fail there).
load_dotenv(os.path.join(os.getcwd(), ".env"))


def _collect_gemini_keys() -> list[str]:
    """Gather GEMINI_API_KEY_1..5 that are actually set (non-empty)."""
    keys = []
    for i in range(1, 6):
        val = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if val and val != "your-key-here":
            keys.append(val)
    return keys


def _collect_groq_keys() -> list[str]:
    """Gather GROQ_API_KEY and GROQ_API_KEY_1..5 that are set (non-empty)."""
    keys = []
    single = os.getenv("GROQ_API_KEY", "").strip()
    if single and single != "your-key-here":
        keys.append(single)
    for i in range(1, 6):
        val = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if val and val != "your-key-here":
            keys.append(val)
    return keys


# Which LLM backend to use: "groq" (default) or "gemini".
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq").strip().lower()

GEMINI_API_KEYS: list[str] = _collect_gemini_keys()
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip()

GROQ_API_KEYS: list[str] = _collect_groq_keys()
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()

GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "").strip()
# Per-call timeout (seconds) for a single LLM request, so a stalled/throttled
# call fails fast and we rotate to the next key instead of hanging.
GEMINI_TIMEOUT: float = float(os.getenv("GEMINI_TIMEOUT", "30"))
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "30"))

# --- Sessions ---
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0").strip()
# How long a conversation stays alive (seconds) since its last turn.
SESSION_TTL: int = int(os.getenv("SESSION_TTL", "3600"))
# Cap history length replayed to the model, to bound token cost.
MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "12"))
