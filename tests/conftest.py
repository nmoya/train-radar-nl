from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.app import create_app
from src.feed import FeedUpdate
from src.static_gtfs import StaticGtfsData, StaticGtfsRows, TargetWindow, VehicleDetails

from .support import (
    make_config,
    make_static_gtfs_data,
    make_static_gtfs_rows,
    make_target_window,
    make_train_status,
    make_vehicle_details,
)


@pytest.fixture
def app_config(tmp_path: Path):
    return make_config(tmp_path / "gtfs-test.zip")


@pytest.fixture
def sample_target_window() -> TargetWindow:
    return make_target_window()


@pytest.fixture
def sample_vehicle_details() -> VehicleDetails:
    return make_vehicle_details()


@pytest.fixture
def sample_train_status():
    return make_train_status()


@pytest.fixture
def sample_static_gtfs_data() -> StaticGtfsData:
    return make_static_gtfs_data()


@pytest.fixture
def sample_static_gtfs_rows() -> StaticGtfsRows:
    return make_static_gtfs_rows()


@pytest.fixture
def api_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = create_app()

    def fake_update() -> FeedUpdate:
        return FeedUpdate(
            feed=None,
            feed_timestamp=1_700_000_000,
            next_poll_in_seconds=app.state.radar_service.cache_ttl_seconds,
            version=0,
            error="stubbed feed update",
        )

    monkeypatch.setattr(app.state.radar_service.poller, "update", fake_update)
    return app


@pytest.fixture
def client(api_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(api_app) as test_client:
        yield test_client
