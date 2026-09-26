"""
key_manager.py — hand out Gemini API keys and rotate them when rate-limited.

Gemini's free tier limits requests per key. With several keys we rotate to
another when one is rate-limited so the agent keeps working. When every key is
cooling down we raise AllKeysCoolingDown so the caller can surface a friendly
"try again shortly" message instead of a hard crash.
"""

from __future__ import annotations

import time

from app.config import GEMINI_API_KEYS

COOLDOWN_SECONDS = 60


class AllKeysCoolingDown(Exception):
    """Every API key is currently on cooldown (all rate-limited)."""


class KeyManager:
    def __init__(self, keys: list[str]):
        self.keys = keys
        self.cooldown_until: dict[str, float] = {}
        if not self.keys:
            raise ValueError(
                "No Gemini API keys found. Set GEMINI_API_KEY_1 in your .env file."
            )

    def get_key(self) -> str:
        """Return the first key not currently cooling down."""
        now = time.time()
        for key in self.keys:
            if now >= self.cooldown_until.get(key, 0.0):
                return key
        raise AllKeysCoolingDown()

    def mark_rate_limited(self, key: str) -> None:
        """Put a key on cooldown after a rate-limit error."""
        self.cooldown_until[key] = time.time() + COOLDOWN_SECONDS


# One shared instance for the whole app.
key_manager = KeyManager(GEMINI_API_KEYS)
