from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

import src.api.app as app_module
import src.api.routes.health as health_module
import src.api.routes.train as train_module
import src.api.service as service_module
from src.api.models import (
    AppConfigResponse,
    DirectionBoardResponse,
    HealthResponse,
    MonitorApiResponse,
    RadarServiceResponse,
    TargetLocationResponse,
    TrainStatusResponse,
)
from src.api.service import RadarApiService
from src.api.ttl_cache import TtlCache

from .support import make_config, make_snapshot, make_static_gtfs_data, make_train_status, make_vehicle_details


def test_api_models_support_expected_defaults() -> None:
    response = MonitorApiResponse(
        generated_at=1,
        cache_ttl_seconds=30,
        cache_expires_at=31,
        feed_timestamp=None,
        target=TargetLocationResponse(latitude=1.0, longitude=2.0, radius_meters=200),
        current=DirectionBoardResponse(left=None, right=None),
        upcoming=DirectionBoardResponse(left=None, right=None),
    )
    health = HealthResponse(
        deployed_commit=None,
        radar_service=RadarServiceResponse(static_gtfs_ready=True, cache_ttl_seconds=30),
        app_config=AppConfigResponse(
            feed_url="feed",
            static_gtfs_url="zip",
            static_gtfs_cache_path="cache.zip",
            target_lat=1.0,
            target_lon=2.0,
            radius_meters=200,
            poll_interval_seconds=30,
            target_passage_tolerance_ceiling_seconds=60,
            target_passage_tolerance_floor_seconds=20,
            target_passage_tolerance_factor=0.1,
            target_passage_directional_tolerance_factor=0.5,
            target_passage_alert_lead_seconds=15,
            user_agent="ua",
            startup_time="now",
        ),
    )

    assert response.feed_error is None
    assert response.target_stop_pairs == []
    assert health.dependencies == []


def test_radar_api_service_startup_and_shutdown(app_config, monkeypatch: pytest.MonkeyPatch) -> None:
    service = RadarApiService(app_config)
    closed = []
    monkeypatch.setattr(service.poller, "ensure_static_gtfs_zip", lambda: Path("cache.zip"))
    monkeypatch.setattr(service_module, "read_static_gtfs_rows", lambda path: "rows")
    monkeypatch.setattr(service.poller, "close", lambda: closed.append(True))

    service.startup()
    service.shutdown()

    assert service.static_gtfs_ready is True
    assert service.static_gtfs_rows == "rows"
    assert closed == [True]


def test_radar_api_service_get_status_uses_cache_and_expires(app_config, monkeypatch: pytest.MonkeyPatch) -> None:
    service = RadarApiService(app_config, cache_ttl_seconds=30)
    built: list[str] = []
    times = iter([100.0, 100.0, 110.0, 140.0, 140.0])
    monkeypatch.setattr(service.response_cache, "_clock", lambda: next(times))
    monkeypatch.setattr(service, "_build_status", lambda: built.append("built") or "payload")

    first = service.get_status()
    second = service.get_status()
    third = service.get_status()

    assert first == "payload"
    assert second == first
    assert third == first
    assert built == ["built", "built"]


def test_ttl_cache_expires_entries() -> None:
    times = iter([10.0, 15.0, 41.0])
    cache = TtlCache[str](30, clock=lambda: next(times))

    cache.set("value")

    assert cache.get() == "value"
    assert cache.get() is None


def test_radar_api_service_build_status_and_train_response(app_config, monkeypatch: pytest.MonkeyPatch) -> None:
    service = RadarApiService(app_config, cache_ttl_seconds=30)
    service.static_gtfs_rows = "rows"
    static_gtfs_data = make_static_gtfs_data()
    train_status = make_train_status(
        vehicle_details=make_vehicle_details(direction_id="0"),
        estimated_target_time=170,
        range_start_time=120,
        range_end_time=190,
    )
    snapshot = make_snapshot(feed_timestamp=160, left_trains=[train_status], right_trains=[])

    monkeypatch.setattr(service_module, "build_static_gtfs_data", lambda rows, config: static_gtfs_data)
    monkeypatch.setattr(service.poller, "update", lambda: SimpleNamespace(error="warn"))
    monkeypatch.setattr(service_module.time, "time", lambda: 150)

    class FakeBuilder:
        def __init__(self, static_gtfs, estimator):
            pass

        def build(self, feed_update):
            return snapshot

    monkeypatch.setattr(service_module, "MonitorSnapshotBuilder", FakeBuilder)

    response = service._build_status()

    assert response.generated_at == 150
    assert response.feed_timestamp == 160
    assert response.feed_error == "warn"
    assert response.current.left.service == "NS intercity"
    assert response.current.left.progress_percent == 50
    assert response.current.left.seconds_until_target == 20
    assert response.target.latitude == app_config.target_lat
    assert response.target.longitude == app_config.target_lon
    assert response.target_stop_pairs == ["Beta -> Gamma", "Gamma -> Beta"]
    assert service._build_train_response(None, 150) is None


def test_radar_api_service_build_status_requires_startup(app_config) -> None:
    service = RadarApiService(app_config)

    with pytest.raises(RuntimeError, match="not loaded"):
        service._build_status()


def test_health_route_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, app_config) -> None:
    distributions = [
        SimpleNamespace(metadata={"Name": "B"}, version="2"),
        SimpleNamespace(metadata={"Name": "a"}, version="1"),
        SimpleNamespace(metadata={"Name": "a"}, version="1"),
        SimpleNamespace(metadata={"Name": None}, version="3"),
    ]
    monkeypatch.setattr(health_module.importlib.metadata, "distributions", lambda: distributions)

    assert health_module.list_installed_dependencies() == ["a==1", "B==2"]
    assert health_module.format_unix_timestamp(0).startswith("1970-01-01")

    commit_path = tmp_path / ".build-commit"
    assert health_module.read_deployed_commit(commit_path) is None
    commit_path.write_text("abc123\n", encoding="utf-8")
    assert health_module.read_deployed_commit(commit_path) == "abc123"

    request = build_request_with_service(
        SimpleNamespace(
            config=app_config,
            static_gtfs_ready=True,
            cache_ttl_seconds=30,
        )
    )
    monkeypatch.setattr(health_module, "read_deployed_commit", lambda path=health_module.DEPLOYED_COMMIT_PATH: "sha")
    monkeypatch.setattr(health_module, "list_installed_dependencies", lambda: ["pytest==9"])

    response = health_module.health(request)

    assert response.deployed_commit == "sha"
    assert response.radar_service.static_gtfs_ready is True
    assert response.app_config.target_lat == app_config.target_lat


def test_train_route_returns_status_and_wraps_errors() -> None:
    service = SimpleNamespace(get_status=lambda: {"lat": 1.0, "lon": 2.0})
    request = build_request_with_service(service)

    assert train_module.train_radar(request) == {"lat": 1.0, "lon": 2.0}

    failing_request = build_request_with_service(
        SimpleNamespace(get_status=lambda: (_ for _ in ()).throw(RuntimeError("bad")))
    )
    with pytest.raises(HTTPException) as exc_info:
        train_module.train_radar(failing_request)
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "bad"


def test_api_app_create_app_parse_args_and_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    lifecycle_calls: list[str] = []

    class FakeService:
        def __init__(self, config):
            pass

        def startup(self):
            lifecycle_calls.append("startup")

        def shutdown(self):
            lifecycle_calls.append("shutdown")

    monkeypatch.setattr(app_module, "RadarApiService", FakeService)
    app = app_module.create_app()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("broken")

    @app.get("/ok")
    async def ok():
        return PlainTextResponse("ok")

    with TestClient(app) as client:
        ok_response = client.get("/ok")
        boom_response = client.get("/boom")

    assert lifecycle_calls == ["startup", "shutdown"]
    assert ok_response.status_code == 200
    assert boom_response.status_code == 500
    assert boom_response.json() == {"detail": "Internal Server Error"}

    monkeypatch.setattr(
        app_module.argparse.ArgumentParser, "parse_args", lambda self: argparse.Namespace(host="0.0.0.0", port=8080)
    )
    args = app_module.parse_args()
    assert args.host == "0.0.0.0"
    assert args.port == 8080

    calls = []
    monkeypatch.setattr(app_module, "parse_args", lambda: argparse.Namespace(host="127.0.0.1", port=9000))
    monkeypatch.setattr(
        app_module.uvicorn, "run", lambda target, host, port, reload: calls.append((target, host, port, reload))
    )
    assert app_module.cli() == 0
    assert calls == [("src.api.app:app", "127.0.0.1", 9000, False)]


def build_request_with_service(service) -> Request:
    app = FastAPI()
    app.state.radar_service = service
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "app": app,
    }
    return Request(scope)
