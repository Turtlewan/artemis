from __future__ import annotations

import logging

import pytest

from artemis.modules.travel import (
    Duration,
    FakeMapsConnector,
    FixedBufferFallback,
    MapsConnector,
    RouteClass,
    maps,
    travel_time_or_buffer,
)
from artemis.runtime_config import ReactionConfig, RuntimeConfig


async def test_fake_maps_connector_returns_configured_duration() -> None:
    result = await FakeMapsConnector(fixed_minutes=42).travel_time("h", "a")

    assert result == Duration(42, "maps")


def test_fixed_buffer_fallback_uses_x3_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(maps, "get_runtime_config", RuntimeConfig)

    intl = FixedBufferFallback().buffer(RouteClass.INTERNATIONAL)
    domestic = FixedBufferFallback().buffer(RouteClass.DOMESTIC)

    assert intl == Duration(180, "fixed_buffer")
    assert domestic == Duration(90, "fixed_buffer")


async def test_travel_time_or_buffer_without_connector_needs_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(maps, "get_runtime_config", RuntimeConfig)

    result = await travel_time_or_buffer(
        None,
        "home",
        "airport",
        route_class=RouteClass.INTERNATIONAL,
    )

    assert result == Duration(180, "fixed_buffer")


async def test_travel_time_or_buffer_uses_successful_connector() -> None:
    result = await travel_time_or_buffer(
        FakeMapsConnector(30),
        "home",
        "airport",
        route_class=RouteClass.INTERNATIONAL,
    )

    assert result == Duration(30, "maps")


async def test_travel_time_or_buffer_degrades_on_connector_failure(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingMapsConnector:
        async def travel_time(
            self,
            origin: str,
            dest: str,
            *,
            mode: str = "driving",
            depart_at: str | None = None,
        ) -> Duration:
            del origin, dest, mode, depart_at
            raise RuntimeError("lookup failed without secret material")

    connector: MapsConnector = FailingMapsConnector()
    monkeypatch.setattr(maps, "get_runtime_config", RuntimeConfig)

    with caplog.at_level(logging.WARNING, logger="travel.maps"):
        result = await travel_time_or_buffer(
            connector,
            "home",
            "airport",
            route_class=RouteClass.DOMESTIC,
        )

    assert result == Duration(90, "fixed_buffer")
    assert len(caplog.records) == 1
    assert "MAPS_API_KEY" not in caplog.text


def test_fixed_buffer_fallback_uses_x3_override(monkeypatch: pytest.MonkeyPatch) -> None:
    def runtime_config() -> RuntimeConfig:
        return RuntimeConfig(reaction=ReactionConfig(maps_intl_buffer_minutes=200))

    monkeypatch.setattr(maps, "get_runtime_config", runtime_config)

    result = FixedBufferFallback().buffer(RouteClass.INTERNATIONAL)

    assert result == Duration(200, "fixed_buffer")
