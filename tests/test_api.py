from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

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
    }
    assert payload["app_config"]["target_lat"] == 52.357019
    assert payload["app_config"]["target_lon"] == 4.921569
    assert Path(payload["app_config"]["static_gtfs_cache_path"]) == MINIFIED_STATIC_GTFS_CACHE_PATH
    assert any(dependency.startswith("fastapi==") for dependency in payload["dependencies"])


def test_train_radar_returns_payload_and_uses_cache(client: TestClient) -> None:
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
    radar_service._cache.clear()
    radar_service._poller.update = fake_update

    params = {"lat": 52.357019, "lon": 4.921569}

    first_response = client.get("/train/radar", params=params)
    second_response = client.get("/train/radar", params=params)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert poller_calls == 1

    payload = first_response.json()
    assert second_response.json() == payload
    assert payload["feed_timestamp"] is None
    assert payload["feed_error"] == "stubbed feed update"
    assert payload["cache_ttl_seconds"] == 30
    assert payload["cache_expires_at"] - payload["generated_at"] == 30
    assert payload["target"] == {
        "latitude": 52.357019,
        "longitude": 4.921569,
        "radius_meters": 200,
    }
    assert payload["current"] == {"left": None, "right": None}
    assert payload["upcoming"] == {"left": None, "right": None}
    assert payload["target_stop_pairs"]
    assert all(" -> " in stop_pair for stop_pair in payload["target_stop_pairs"])


def test_train_radar_returns_503_when_service_fails(client: TestClient) -> None:
    def raise_error(latitude: float, longitude: float) -> None:
        raise RuntimeError(f"cannot build status for {latitude},{longitude}")

    client.app.state.radar_service.get_status = raise_error

    response = client.get("/train/radar", params={"lat": 52.357019, "lon": 4.921569})

    assert response.status_code == 503
    assert response.json() == {"detail": "cannot build status for 52.357019,4.921569"}


def test_train_radar_requires_coordinates(client: TestClient) -> None:
    response = client.get("/train/radar")

    assert response.status_code == 422
