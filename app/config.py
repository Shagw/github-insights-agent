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


GEMINI_API_KEYS: list[str] = _collect_gemini_keys()
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip()
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "").strip()

# --- Sessions ---
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0").strip()
# How long a conversation stays alive (seconds) since its last turn.
SESSION_TTL: int = int(os.getenv("SESSION_TTL", "3600"))
# Cap history length replayed to the model, to bound token cost.
MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "12"))
