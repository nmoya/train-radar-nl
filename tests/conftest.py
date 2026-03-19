from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.api.service as service_module
from src.api.app import create_app
from src.config import MINIFIED_STATIC_GTFS_CACHE_PATH
from src.feed import FeedUpdate


@pytest.fixture
def api_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(
        service_module,
        "FULL_STATIC_GTFS_CACHE_PATH",
        MINIFIED_STATIC_GTFS_CACHE_PATH,
    )
    app = create_app()

    def fake_update() -> FeedUpdate:
        return FeedUpdate(
            feed=None,
            feed_timestamp=1_700_000_000,
            next_poll_in_seconds=app.state.radar_service.cache_ttl_seconds,
            version=0,
            error="stubbed feed update",
        )

    monkeypatch.setattr(app.state.radar_service._poller, "update", fake_update)
    return app


@pytest.fixture
def client(api_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(api_app) as test_client:
        yield test_client
