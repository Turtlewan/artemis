"""Provider error taxonomy. Failover-eligible errors signal the router to try the next backend."""

from __future__ import annotations

from artemis.errors import (
    AllBackendsExhaustedError,
    FailoverEligibleError,
    ProviderError,
    ProviderUnavailableError,
    QuotaExhaustedError,
)

__all__ = [
    "AllBackendsExhaustedError",
    "FailoverEligibleError",
    "ProviderError",
    "ProviderUnavailableError",
    "QuotaExhaustedError",
]
