"""Lazy TTL + size-bounded eviction for the in-memory server-side gate stores.

`app.state.builds` and `app.state.invokes` hold server-side state between two
gated HTTP calls (propose -> build -> promote; propose -> confirm). Neither entry
is ever removed when the owner abandons a proposal, so without eviction the dicts
grow unbounded. Eviction runs lazily at each insert -- this is a single-user hub,
so no background sweeper is needed; a stale entry lingers only until the next
insert, which bounds total growth.
"""

from __future__ import annotations

import time
from typing import Protocol, TypeVar


class _HasCreatedAt(Protocol):
    created_at: float


_T = TypeVar("_T", bound=_HasCreatedAt)


def evict_expired(
    store: dict[str, _T],
    *,
    ttl_seconds: float,
    max_entries: int,
    now: float | None = None,
) -> None:
    """Drop entries older than `ttl_seconds`, then cap the store at `max_entries`
    (evicting the oldest by `created_at` first). Mutates `store` in place.

    `now` is a `time.monotonic()` reading; injectable for tests.
    """
    current = time.monotonic() if now is None else now
    for key in [k for k, v in store.items() if current - v.created_at >= ttl_seconds]:
        del store[key]
    if len(store) > max_entries:
        oldest = sorted(store.items(), key=lambda item: item[1].created_at)
        for key, _ in oldest[: len(store) - max_entries]:
            del store[key]
