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
from src.api.service import RadarApiService, parse_http_datetime
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
        radar_service=RadarServiceResponse(
            static_gtfs_ready=True,
            cache_ttl_seconds=30,
            tigris_refresh_enabled=False,
            tigris_refresh_interval_minutes=1440,
            tigris_last_read_at=None,
            tigris_last_file_updated_at=None,
            tigris_last_reload_at=None,
        ),
        app_config=AppConfigResponse(
            feed_url="feed",
            static_gtfs_url="zip",
            runtime_static_gtfs_url=None,
            static_gtfs_cache_path="cache.zip",
            runtime_static_gtfs_refresh_interval_minutes=1440,
            target_lat=1.0,
            target_lon=2.0,
            radius_meters=200,
            poll_interval_seconds=30,
            target_passage_tolerance_ceiling_seconds=60,
            target_passage_tolerance_factor=0.1,
            target_passage_sparse_update_tolerance_factor=0.5,
            timezone_name="Europe/Amsterdam",
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
    monkeypatch.setattr(service, "_load_static_gtfs_data_from_path", lambda path: "gtfs-data")
    monkeypatch.setattr(service.poller, "close", lambda: closed.append(True))

    service.startup()
    service.shutdown()

    assert service.static_gtfs_ready is True
    assert service.static_gtfs_data == "gtfs-data"
    assert closed == [True]


def test_radar_api_service_get_status_uses_cache_and_expires(app_config, monkeypatch: pytest.MonkeyPatch) -> None:
    service = RadarApiService(app_config, cache_ttl_seconds=30)
    built: list[int] = []
    rendered: list[tuple[str, int]] = []
    times = iter([100.0, 100.0, 100.0, 110.0, 140.0, 140.0, 140.0])
    monkeypatch.setattr(service.response_cache, "_clock", lambda: next(times))
    wall_times = iter([1000, 1010, 1040])
    monkeypatch.setattr(service_module.time, "time", lambda: next(wall_times))
    monkeypatch.setattr(
        service,
        "_build_cached_status",
        lambda display_timestamp: built.append(display_timestamp) or f"cached@{display_timestamp}",
    )
    monkeypatch.setattr(
        service,
        "_build_response",
        lambda cached_status, display_timestamp: rendered.append((cached_status, display_timestamp))
        or f"{cached_status}:{display_timestamp}",
    )

    first = service.get_status()
    second = service.get_status()
    third = service.get_status()

    assert first == "cached@1000:1000"
    assert second == "cached@1000:1010"
    assert third == "cached@1040:1040"
    assert built == [1000, 1040]
    assert rendered == [
        ("cached@1000", 1000),
        ("cached@1000", 1010),
        ("cached@1040", 1040),
    ]


def test_ttl_cache_expires_entries() -> None:
    times = iter([10.0, 15.0, 41.0])
    cache = TtlCache[str](30, clock=lambda: next(times))

    cache.set("value")

    assert cache.get() == "value"
    assert cache.get() is None


def test_radar_api_service_build_status_and_train_response(app_config, monkeypatch: pytest.MonkeyPatch) -> None:
    service = RadarApiService(app_config, cache_ttl_seconds=30)
    static_gtfs_data = make_static_gtfs_data()
    service.static_gtfs_data = static_gtfs_data
    train_status = make_train_status(
        vehicle_details=make_vehicle_details(direction_id="0"),
        estimated_target_time=170,
        previous_stop_time=1_700_000_050,
        next_stop_time=1_700_000_150,
        range_start_time=120,
        range_end_time=190,
    )
    snapshot = make_snapshot(feed_timestamp=160, left_trains=[train_status], right_trains=[])

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
    assert response.current.left.progress_percent == 33
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
    assert health_module.format_unix_timestamp(0, "UTC") == "1970-01-01 00:00:00 UTC"
    assert health_module.format_optional_unix_timestamp(None, "UTC") is None
    assert (
        health_module.format_unix_timestamp(0, "Europe/Amsterdam")
        == "1970-01-01 01:00:00 CET"
    )

    commit_path = tmp_path / ".build-commit"
    assert health_module.read_deployed_commit(commit_path) is None
    commit_path.write_text("abc123\n", encoding="utf-8")
    assert health_module.read_deployed_commit(commit_path) == "abc123"

    request = build_request_with_service(
        SimpleNamespace(
            config=app_config,
            static_gtfs_ready=True,
            cache_ttl_seconds=30,
            tigris_refresh_enabled=True,
            tigris_refresh_interval_minutes=1440,
            tigris_last_read_at=60,
            tigris_last_file_updated_at=120,
            tigris_last_reload_at=180,
            tigris_last_error=None,
        )
    )
    monkeypatch.setattr(health_module, "read_deployed_commit", lambda path=health_module.DEPLOYED_COMMIT_PATH: "sha")
    monkeypatch.setattr(health_module, "list_installed_dependencies", lambda: ["pytest==9"])

    response = health_module.health(request)

    assert response.deployed_commit == "sha"
    assert response.radar_service.static_gtfs_ready is True
    assert response.radar_service.tigris_refresh_enabled is True
    assert response.radar_service.tigris_refresh_interval_minutes == 1440
    assert response.radar_service.tigris_last_read_at == "1970-01-01 01:01:00 CET"
    assert response.radar_service.tigris_last_file_updated_at == "1970-01-01 01:02:00 CET"
    assert response.radar_service.tigris_last_reload_at == "1970-01-01 01:03:00 CET"
    assert response.app_config.target_lat == app_config.target_lat
    assert response.app_config.timezone_name == app_config.timezone_name
    assert response.app_config.runtime_static_gtfs_refresh_interval_minutes == 1440


def test_parse_http_datetime_handles_missing_and_invalid_values() -> None:
    assert parse_http_datetime(None) is None
    assert parse_http_datetime("not-a-date") is None
    assert parse_http_datetime("Thu, 01 Jan 1970 00:00:00 GMT") == 0


def test_radar_api_service_refreshes_from_tigris_and_clears_cache(
    app_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "gtfs-min.zip"
    service = RadarApiService(
        make_config(
            cache_path,
            runtime_static_gtfs_url="https://example.test/gtfs-min.zip",
            runtime_static_gtfs_refresh_interval_minutes=5,
        )
    )
    cleared: list[bool] = []
    monkeypatch.setattr(service.response_cache, "clear", lambda: cleared.append(True))
    monkeypatch.setattr(service_module.time, "time", lambda: 1_700_000_300)

    downloaded_path = cache_path.with_suffix(".zip.download")
    downloaded_path.write_bytes(b"zip")
    monkeypatch.setattr(
        service,
        "_download_tigris_zip",
        lambda local_path: (
            downloaded_path,
            service_module.DownloadedZipMetadata(
                last_modified_at=1_700_000_200,
            ),
        ),
    )
    monkeypatch.setattr(service, "_load_static_gtfs_data_from_path", lambda path: "gtfs-data")

    assert service.refresh_static_gtfs_if_due(force=True) is True
    assert service.static_gtfs_data == "gtfs-data"
    assert service.tigris_last_read_at == 1_700_000_300
    assert service.tigris_last_file_updated_at == 1_700_000_200
    assert service.tigris_last_reload_at == 1_700_000_300
    assert service.tigris_last_error is None
    assert cleared == [True]


def test_radar_api_service_skips_tigris_download_until_due(
    app_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "gtfs-min.zip"
    cache_path.write_bytes(b"existing")
    service = RadarApiService(
        make_config(
            cache_path,
            runtime_static_gtfs_url="https://example.test/gtfs-min.zip",
            runtime_static_gtfs_refresh_interval_minutes=5,
        )
    )
    service.static_gtfs_data = "gtfs-data"
    service._next_tigris_refresh_at = 1_700_000_500
    monkeypatch.setattr(service_module.time, "time", lambda: 1_700_000_300)
    download_attempts: list[bool] = []
    monkeypatch.setattr(
        service,
        "_download_tigris_zip",
        lambda local_path: download_attempts.append(True),
    )

    assert service.refresh_static_gtfs_if_due() is False
    assert download_attempts == []


def test_radar_api_service_startup_loads_local_tigris_cache_without_immediate_download(
    app_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "gtfs-min.zip"
    cache_path.write_bytes(b"existing")
    service = RadarApiService(
        make_config(
            cache_path,
            runtime_static_gtfs_url="https://example.test/gtfs-min.zip",
            runtime_static_gtfs_refresh_interval_minutes=5,
        )
    )
    monkeypatch.setattr(service_module.time, "time", lambda: 1_700_000_300)
    monkeypatch.setattr(service, "_load_static_gtfs_data_from_path", lambda path: "gtfs-data")
    download_attempts: list[Path] = []
    monkeypatch.setattr(service, "_download_tigris_zip", lambda local_path: download_attempts.append(local_path))

    service.startup()

    assert service.static_gtfs_data == "gtfs-data"
    assert service._next_tigris_refresh_at == 1_700_000_600
    assert download_attempts == []
    service.shutdown()


def test_radar_api_service_get_status_uses_single_flight_on_cache_miss(
    app_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RadarApiService(app_config, cache_ttl_seconds=30)
    service.static_gtfs_data = make_static_gtfs_data()
    build_calls: list[int] = []
    rendered: list[tuple[str, int]] = []

    monkeypatch.setattr(service_module.time, "time", lambda: 1000)

    def fake_build(display_timestamp: int) -> str:
        build_calls.append(display_timestamp)
        service.response_cache.set("cached-status")
        return "cached-status"

    monkeypatch.setattr(service, "_build_cached_status", fake_build)
    monkeypatch.setattr(
        service,
        "_build_response",
        lambda cached_status, display_timestamp: rendered.append((cached_status, display_timestamp))
        or f"{cached_status}:{display_timestamp}",
    )

    first = service.get_status()
    second = service.get_status()

    assert first == "cached-status:1000"
    assert second == "cached-status:1000"
    assert build_calls == [1000]
    assert rendered == [
        ("cached-status", 1000),
        ("cached-status", 1000),
    ]


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
