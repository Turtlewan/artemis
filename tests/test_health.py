"""Tests for the brain health stub endpoints (M0-b)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from artemis.main import app

client = TestClient(app)


def test_healthz() -> None:
    """GET /healthz returns 200 with status ok."""
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "slot" in data


def test_readyz() -> None:
    """GET /readyz returns 200 with status ok."""
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "checks" in data
    assert data["checks"] == {}
