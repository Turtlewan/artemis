"""Unit tests for the lazy TTL + size-bounded eviction helper."""

from __future__ import annotations

from dataclasses import dataclass

from artemis.expiry import evict_expired


@dataclass
class _Entry:
    created_at: float


def test_drops_entries_older_than_ttl() -> None:
    store = {"old": _Entry(created_at=0.0), "fresh": _Entry(created_at=95.0)}

    evict_expired(store, ttl_seconds=10.0, max_entries=100, now=100.0)

    assert set(store) == {"fresh"}


def test_ttl_boundary_is_inclusive() -> None:
    store = {"exactly_ttl": _Entry(created_at=90.0)}

    evict_expired(store, ttl_seconds=10.0, max_entries=100, now=100.0)

    assert store == {}


def test_caps_to_max_entries_evicting_oldest_first() -> None:
    store = {
        "a": _Entry(created_at=1.0),
        "b": _Entry(created_at=2.0),
        "c": _Entry(created_at=3.0),
    }

    evict_expired(store, ttl_seconds=1000.0, max_entries=2, now=3.0)

    assert set(store) == {"b", "c"}


def test_noop_when_within_ttl_and_cap() -> None:
    store = {"a": _Entry(created_at=99.0), "b": _Entry(created_at=100.0)}

    evict_expired(store, ttl_seconds=10.0, max_entries=10, now=100.0)

    assert set(store) == {"a", "b"}
