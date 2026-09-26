"""
key_manager.py — hand out Gemini API keys and rotate them when rate-limited.

Gemini's free tier limits requests per key. With several keys we rotate to
another when one is rate-limited so the agent keeps working. When every key is
cooling down we raise AllKeysCoolingDown so the caller can surface a friendly
"try again shortly" message instead of a hard crash.
"""

from __future__ import annotations

import time

from app.config import GEMINI_API_KEYS, GROQ_API_KEYS, LLM_PROVIDER

COOLDOWN_SECONDS = 60


class AllKeysCoolingDown(Exception):
    """Every API key is currently on cooldown (all rate-limited)."""


class NoKeysConfigured(Exception):
    """No API keys are configured for the active provider."""


class KeyManager:
    def __init__(self, keys: list[str]):
        self.keys = keys
        self.cooldown_until: dict[str, float] = {}
        self._cursor = 0  # round-robin position

    def get_key(self) -> str:
        """Return the next available key in round-robin order.

        Consecutive calls hand out different keys (spreading load across the
        pool so no single key is hammered against its per-minute limit). Keys
        currently on cooldown are skipped. Raises AllKeysCoolingDown if every
        key is cooling down.
        """
        if not self.keys:
            raise NoKeysConfigured(
                "No API keys configured for the active LLM provider. "
                "Set GROQ_API_KEY (or GEMINI_API_KEY_1) in your .env."
            )
        now = time.time()
        n = len(self.keys)
        for offset in range(n):
            idx = (self._cursor + offset) % n
            key = self.keys[idx]
            if now >= self.cooldown_until.get(key, 0.0):
                # advance the cursor past the key we're handing out
                self._cursor = (idx + 1) % n
                return key
        raise AllKeysCoolingDown()

    def mark_rate_limited(self, key: str) -> None:
        """Put a key on cooldown after a rate-limit error."""
        self.cooldown_until[key] = time.time() + COOLDOWN_SECONDS


# One shared instance for the whole app, using the ACTIVE provider's keys.
_ACTIVE_KEYS = GROQ_API_KEYS if LLM_PROVIDER == "groq" else GEMINI_API_KEYS
key_manager = KeyManager(_ACTIVE_KEYS)
