"""Minimal DataScope-to-Tier classifier for voice pre-serve gating."""

from __future__ import annotations

from typing import Literal

from artemis.manifest import DataScope

Tier = Literal["tier0", "tier1"]


def tier_for(data_scope: DataScope | None) -> Tier:
    """Return Tier-1 only for owner-private module data.

    In v1, modules marked ``OWNER_PRIVATE`` are the sensitive set
    (finance, health, journal, memory). The full provenance/sensitivity router
    can replace this narrow seam later.
    """
    if data_scope == DataScope.OWNER_PRIVATE:
        return "tier1"
    return "tier0"
