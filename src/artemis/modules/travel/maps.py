"""Maps travel-time connector with dev fake and fixed-buffer degrade path.

The real Distance Matrix connector is Mac-gated by composition: the owner-present
``MAPS_API_KEY`` is read from the environment/secrets layer before constructing
``GoogleMapsConnector``. This module never requires a key at import time, never
logs a key, and the dev path can use ``FakeMapsConnector`` or the X3 fixed-buffer
fallback without network access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from math import ceil
from typing import Literal, Protocol, cast

import httpx

from artemis.runtime_config import get_runtime_config

GOOGLE_DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"


@dataclass(frozen=True)
class Duration:
    """Travel duration and its provenance."""

    minutes: int
    source: Literal["maps", "fixed_buffer"]


class RouteClass(StrEnum):
    """Caller-supplied route classification for fixed airport buffers."""

    INTERNATIONAL = "international"
    DOMESTIC = "domestic"


class MapsConnectorError(Exception):
    """Raised when a Maps connector cannot return a usable duration."""


class MapsConnector(Protocol):
    """Port for travel-time lookups."""

    async def travel_time(
        self,
        origin: str,
        dest: str,
        *,
        mode: str = "driving",
        depart_at: str | None = None,
    ) -> Duration:
        """Return the estimated travel time between two locations."""
        ...


class GoogleMapsConnector:
    """Google Distance Matrix adapter.

    API keys are supplied by the caller, typically from ``MAPS_API_KEY`` injected
    into the environment on the Mac. Absence of a key is handled in composition by
    not constructing this connector and using ``travel_time_or_buffer(None, ...)``.
    """

    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def travel_time(
        self,
        origin: str,
        dest: str,
        *,
        mode: str = "driving",
        depart_at: str | None = None,
    ) -> Duration:
        """Fetch a Distance Matrix duration from Google Maps."""

        params: dict[str, str] = {
            "origins": origin,
            "destinations": dest,
            "mode": mode,
            "key": self._api_key,
        }
        if depart_at is not None:
            params["departure_time"] = depart_at

        try:
            response = await self._http().get(GOOGLE_DISTANCE_MATRIX_URL, params=params)
            if not 200 <= response.status_code < 300:
                raise MapsConnectorError(
                    f"Google Maps lookup failed with HTTP {response.status_code}"
                )
            return Duration(minutes=_duration_minutes(response.json()), source="maps")
        except MapsConnectorError:
            raise
        except Exception as exc:
            raise MapsConnectorError("Google Maps lookup returned an unusable response") from exc

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient()
        return self._client


class FakeMapsConnector:
    """Deterministic dev/test connector: no key, no network."""

    def __init__(self, fixed_minutes: int = 35) -> None:
        self.fixed_minutes = fixed_minutes

    async def travel_time(
        self,
        origin: str,
        dest: str,
        *,
        mode: str = "driving",
        depart_at: str | None = None,
    ) -> Duration:
        """Return the configured fixed duration."""

        del origin, dest, mode, depart_at
        return Duration(minutes=self.fixed_minutes, source="maps")


class FixedBufferFallback:
    """Yields the X3-configured airport buffer when Maps is unavailable or fails."""

    def buffer(self, route_class: RouteClass) -> Duration:
        """Return the configured fixed buffer for the caller's route class."""

        cfg = get_runtime_config().reaction
        minutes = (
            cfg.maps_intl_buffer_minutes
            if route_class is RouteClass.INTERNATIONAL
            else cfg.maps_domestic_buffer_minutes
        )
        return Duration(minutes=minutes, source="fixed_buffer")


async def travel_time_or_buffer(
    connector: MapsConnector | None,
    origin: str,
    dest: str,
    *,
    route_class: RouteClass,
    mode: str = "driving",
    depart_at: str | None = None,
) -> Duration:
    """Try Maps, then degrade to the X3 fixed buffer without raising."""

    fallback = FixedBufferFallback()
    if connector is None:
        return fallback.buffer(route_class)
    try:
        return await connector.travel_time(origin, dest, mode=mode, depart_at=depart_at)
    except Exception:
        logging.getLogger("travel.maps").warning(
            "Maps lookup failed; using fixed buffer (%s)",
            route_class.value,
        )
        return fallback.buffer(route_class)


def _duration_minutes(payload: object) -> int:
    if not isinstance(payload, dict):
        raise MapsConnectorError("Google Maps response must be an object")

    status = payload.get("status")
    if status != "OK":
        raise MapsConnectorError("Google Maps response status was not OK")

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise MapsConnectorError("Google Maps response missing rows")

    first_row = rows[0]
    if not isinstance(first_row, dict):
        raise MapsConnectorError("Google Maps row must be an object")

    elements = first_row.get("elements")
    if not isinstance(elements, list) or not elements:
        raise MapsConnectorError("Google Maps response missing elements")

    first_element = elements[0]
    if not isinstance(first_element, dict):
        raise MapsConnectorError("Google Maps element must be an object")
    if first_element.get("status") != "OK":
        raise MapsConnectorError("Google Maps element status was not OK")

    duration = first_element.get("duration_in_traffic") or first_element.get("duration")
    if not isinstance(duration, dict):
        raise MapsConnectorError("Google Maps response missing duration")

    seconds = duration.get("value")
    if not isinstance(seconds, int):
        raise MapsConnectorError("Google Maps duration value must be an integer")
    if seconds < 0:
        raise MapsConnectorError("Google Maps duration value must be non-negative")

    return ceil(cast(float, seconds) / 60)
