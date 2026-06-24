"""Tier-aware model usage attribution."""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlparse

from artemis.config import Settings
from artemis.obs import get_logger


class Tier(StrEnum):
    """Usage accounting tiers for model roles."""

    LOCAL = "local"
    SUBSCRIPTION = "subscription"
    CLOUD = "cloud"


def tier_for(role: str, settings: Settings) -> Tier:
    """Classify a model role into its attribution tier."""

    model_role = settings.roles.get(role)
    if model_role is None:
        get_logger("obs.cost").warning("unknown_role", extra={"role": role[:64]})
        return Tier.LOCAL
    if model_role.adapter == "claude-cli":
        return Tier.SUBSCRIPTION
    host = urlparse(model_role.endpoint).hostname or ""
    if model_role.adapter == "openai" and "deepseek" in host:
        return Tier.CLOUD
    return Tier.LOCAL


class CostModel:
    """Convert token counts into attribution micros.

    ``cost_micros`` is an attribution unit, not a billed dollar amount.
    Subscription tokens are retained as a conservative quota signal; prompt-cache
    discounts are not subtracted in v1.
    """

    def __init__(
        self,
        settings: Settings,
        cloud_micros_per_1k: int = 0,
        subscription_micros_per_1k: int = 0,
    ) -> None:
        self._settings = settings
        self._cloud_micros_per_1k = cloud_micros_per_1k
        self._subscription_micros_per_1k = subscription_micros_per_1k

    def cost_micros(self, role: str, total_tokens: int) -> int:
        """Return attribution micros for ``role`` and ``total_tokens``."""

        tier = tier_for(role, self._settings)
        if tier == Tier.CLOUD:
            return total_tokens * self._cloud_micros_per_1k // 1000
        if tier == Tier.SUBSCRIPTION:
            return total_tokens * self._subscription_micros_per_1k // 1000
        return 0
