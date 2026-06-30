"""Tests for layout persistence."""

from __future__ import annotations

from fastapi.testclient import TestClient

from artemis.api.app import create_app
from artemis.api.auth import Principal, require_session


def _client(tmp_path: object) -> TestClient:
    app = create_app(data_dir=str(tmp_path))
    app.dependency_overrides[require_session] = lambda: Principal(device_id="d", person_id="owner")
    return TestClient(app)


def test_get_returns_empty_default_layout(tmp_path: object) -> None:
    # The brain ships NO default cards; the client uses its own canonical seed for an empty list.
    resp = _client(tmp_path).get("/app/layout")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 1
    assert body["cards"] == []


def test_put_then_get_roundtrips(tmp_path: object) -> None:
    client = _client(tmp_path)
    layout = {
        "version": 2,
        "updated_at": "2030-01-01T00:00:00Z",
        "cards": [
            {"id": "email", "domain": "email", "cluster": "Comms", "x": 5, "y": 6, "w": 2, "h": 2}
        ],
    }
    put = client.put("/app/layout", json=layout)
    assert put.status_code == 200
    got = client.get("/app/layout").json()
    assert len(got["cards"]) == 1
    assert got["cards"][0]["x"] == 5


def test_lww_rejects_stale(tmp_path: object) -> None:
    client = _client(tmp_path)
    newer = {
        "version": 3,
        "updated_at": "2030-06-01T00:00:00Z",
        "cards": [
            {
                "id": "tasks",
                "domain": "tasks",
                "cluster": "Planning",
                "x": 1,
                "y": 1,
                "w": 2,
                "h": 2,
            }
        ],
    }
    client.put("/app/layout", json=newer)
    stale = {
        "version": 4,
        "updated_at": "2020-01-01T00:00:00Z",
        "cards": [
            {"id": "email", "domain": "email", "cluster": "Comms", "x": 9, "y": 9, "w": 2, "h": 2}
        ],
    }
    client.put("/app/layout", json=stale)
    got = client.get("/app/layout").json()
    assert got["cards"][0]["id"] == "tasks"  # stale put rejected


def test_layout_requires_session(tmp_path: object) -> None:
    app = create_app(data_dir=str(tmp_path))
    assert TestClient(app).get("/app/layout").status_code == 401
