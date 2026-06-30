"""Provider error taxonomy. Failover-eligible errors signal the router to try the next backend."""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base for all model-provider failures."""


class FailoverEligibleError(ProviderError):
    """A backend-level failure the router should recover from by trying the next backend."""

    def __init__(self, provider: str, detail: str) -> None:
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider}: {detail}")


class QuotaExhaustedError(FailoverEligibleError):
    """The backend hit a rate / weekly-quota / usage limit."""


class ProviderUnavailableError(FailoverEligibleError):
    """The backend is unreachable or misconfigured (binary missing, connection refused, auth)."""


class AllBackendsExhaustedError(ProviderError):
    """Every backend in the router chain failed over."""

    def __init__(self, failures: list[tuple[str, ProviderError]]) -> None:
        self.failures = failures
        names = ", ".join(name for name, _ in failures) or "(none)"
        super().__init__(f"All backends exhausted: {names}")
