from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import src.api.service as service_module
from src.config import MINIFIED_STATIC_GTFS_CACHE_PATH
from src.feed import FeedUpdate


def test_health_reports_ready_state_and_minified_gtfs(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200

    payload = response.json()
    assert payload["deployed_commit"] is None
    assert payload["radar_service"] == {
        "static_gtfs_ready": True,
        "cache_ttl_seconds": 30,
        "tigris_refresh_enabled": False,
        "tigris_refresh_interval_minutes": 15,
        "tigris_last_read_at": None,
        "tigris_last_file_updated_at": None,
        "tigris_last_reload_at": None,
        "tigris_last_error": None,
    }
    assert payload["app_config"]["target_lat"] == 52.379028
    assert payload["app_config"]["target_lon"] == 4.90125
    assert Path(payload["app_config"]["static_gtfs_cache_path"]) == MINIFIED_STATIC_GTFS_CACHE_PATH
    assert payload["app_config"]["runtime_static_gtfs_url"] is None
    assert payload["app_config"]["runtime_static_gtfs_refresh_interval_minutes"] == 15
    assert any(dependency.startswith("fastapi==") for dependency in payload["dependencies"])


def test_train_radar_returns_payload_and_uses_cache(
    client: TestClient,
    monkeypatch,
) -> None:
    poller_calls = 0

    def fake_update() -> FeedUpdate:
        nonlocal poller_calls
        poller_calls += 1
        return FeedUpdate(
            feed=None,
            feed_timestamp=1_700_000_123,
            next_poll_in_seconds=30,
            version=1,
            error="stubbed feed update",
        )

    radar_service = client.app.state.radar_service
    radar_service.response_cache.clear()
    radar_service.poller.update = fake_update
    monkeypatch.setattr(service_module.time, "time", lambda: 100)

    first_response = client.get("/train/radar")
    monkeypatch.setattr(service_module.time, "time", lambda: 105)
    second_response = client.get("/train/radar", params={"lat": 0, "lon": 0})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert poller_calls == 1

    first_payload = first_response.json()
    second_payload = second_response.json()
    assert first_payload["feed_timestamp"] is None
    assert first_payload["feed_error"] == "stubbed feed update"
    assert first_payload["cache_ttl_seconds"] == 30
    assert first_payload["cache_expires_at"] == 130
    assert second_payload["cache_expires_at"] == 130
    assert first_payload["generated_at"] == 100
    assert second_payload["generated_at"] == 105
    assert second_payload["cache_expires_at"] - second_payload["generated_at"] == 25
    assert second_payload["target"] == {
        "latitude": 52.379028,
        "longitude": 4.90125,
        "radius_meters": 200,
    }
    assert second_payload["current"] == {"left": None, "right": None}
    assert second_payload["upcoming"] == {"left": None, "right": None}
    assert second_payload["target_stop_pairs"]
    assert all(" -> " in stop_pair for stop_pair in second_payload["target_stop_pairs"])


def test_train_radar_returns_503_when_service_fails(client: TestClient) -> None:
    def raise_error() -> None:
        raise RuntimeError("cannot build status for default target")

    client.app.state.radar_service.get_status = raise_error

    response = client.get("/train/radar")

    assert response.status_code == 503
    assert response.json() == {"detail": "cannot build status for default target"}


def test_train_radar_ignores_query_coordinates(client: TestClient) -> None:
    response = client.get("/train/radar", params={"lat": 1.23, "lon": 4.56})

    assert response.status_code == 200
    assert response.json()["target"] == {
        "latitude": 52.379028,
        "longitude": 4.90125,
        "radius_meters": 200,
    }
