"""Tests for round-robin key rotation and cooldown behavior."""

from __future__ import annotations

import pytest

from app.key_manager import AllKeysCoolingDown, KeyManager


def test_round_robin_spreads_across_all_keys():
    km = KeyManager(["A", "B", "C"])
    picks = [km.get_key() for _ in range(6)]
    # consecutive calls rotate: A B C A B C
    assert picks == ["A", "B", "C", "A", "B", "C"], picks
    # every key actually gets used
    assert set(picks) == {"A", "B", "C"}


def test_consecutive_calls_differ():
    km = KeyManager(["A", "B", "C", "D", "E"])
    first = km.get_key()
    second = km.get_key()
    assert first != second  # not sticky on one key


def test_cooldown_key_is_skipped():
    km = KeyManager(["A", "B", "C"])
    km.mark_rate_limited("B")
    # over a full cycle, B is skipped; A and C still served
    picks = [km.get_key() for _ in range(4)]
    assert "B" not in picks
    assert set(picks) == {"A", "C"}


def test_all_cooling_raises():
    km = KeyManager(["A", "B"])
    km.mark_rate_limited("A")
    km.mark_rate_limited("B")
    with pytest.raises(AllKeysCoolingDown):
        km.get_key()


def test_single_key_still_works():
    km = KeyManager(["only"])
    assert km.get_key() == "only"
    assert km.get_key() == "only"


def test_empty_keys_deferred_error():
    from app.key_manager import NoKeysConfigured
    km = KeyManager([])           # construction is fine (deferred)
    with pytest.raises(NoKeysConfigured):
        km.get_key()              # error only when a key is actually needed
