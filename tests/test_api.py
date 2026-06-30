"""Tests for the brain HTTP API skeleton."""

from __future__ import annotations

from fastapi.testclient import TestClient

from artemis.api import create_app


def test_healthz() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_status_default_unconnected() -> None:
    client = TestClient(create_app())
    resp = client.get("/app/status")
    assert resp.status_code == 200
    assert resp.json() == {"connected": False, "vault_unlocked": False, "device_id": ""}
