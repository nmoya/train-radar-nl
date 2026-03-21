from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

from src.config import AppConfig
from src.static_gtfs import StaticGtfsData, ensure_static_gtfs_zip, load_static_gtfs


@dataclass(frozen=True)
class FeedFetchResult:
    feed: gtfs_realtime_pb2.FeedMessage | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class FeedUpdate:
    feed: gtfs_realtime_pb2.FeedMessage | None
    feed_timestamp: int
    next_poll_in_seconds: int
    version: int
    error: str | None = None


@dataclass(frozen=True)
class StaticGtfsLoadResult:
    data: StaticGtfsData | None
    error: str | None = None


class FeedPoller:
    def __init__(
        self,
        config: AppConfig,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._etag: str | None = None
        self._last_modified: str | None = None
        self._last_poll_started_at: float | None = None
        self._cached_feed: gtfs_realtime_pb2.FeedMessage | None = None
        self._cached_feed_timestamp: int | None = None
        self._version = 0

    def load_static_gtfs(self) -> StaticGtfsLoadResult:
        try:
            return StaticGtfsLoadResult(
                data=load_static_gtfs(self._session, self._config),
            )
        except requests.RequestException as exc:
            return StaticGtfsLoadResult(data=None, error=f"Static GTFS load failed: {exc}")
        except Exception as exc:
            return StaticGtfsLoadResult(data=None, error=f"Static GTFS parse failed: {exc}")

    def ensure_static_gtfs_zip(self) -> Path:
        return ensure_static_gtfs_zip(self._session, self._config)

    def update(self) -> FeedUpdate:
        if self._poll_interval_remaining_seconds() > 0:
            return self._build_update()

        self._last_poll_started_at = time.monotonic()

        try:
            fetch_result = fetch_feed(
                self._session,
                self._config,
                self._etag,
                self._last_modified,
            )
        except requests.RequestException as exc:
            return self._build_update(error=f"Feed update failed: {exc}")

        self._etag = fetch_result.etag
        self._last_modified = fetch_result.last_modified

        if fetch_result.feed is not None:
            self._cached_feed = fetch_result.feed
            self._cached_feed_timestamp = fetch_result.feed.header.timestamp or int(time.time())
            self._version += 1

        return self._build_update()

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def _build_update(
        self,
        error: str | None = None,
    ) -> FeedUpdate:
        feed_timestamp = self._cached_feed_timestamp or int(time.time())
        return FeedUpdate(
            feed=self._cached_feed,
            feed_timestamp=feed_timestamp,
            next_poll_in_seconds=self._poll_interval_remaining_seconds(),
            version=self._version,
            error=error,
        )

    def _poll_interval_remaining_seconds(self) -> int:
        if self._last_poll_started_at is None:
            return 0

        elapsed_seconds = time.monotonic() - self._last_poll_started_at
        remaining_seconds = self._config.poll_interval_seconds - elapsed_seconds
        return max(0, math.ceil(remaining_seconds))


def fetch_feed(
    session: requests.Session,
    config: AppConfig,
    etag: str | None,
    last_modified: str | None,
) -> FeedFetchResult:
    headers = {"User-Agent": config.user_agent}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    response = session.get(config.feed_url, headers=headers, timeout=30)
    if response.status_code == 304:
        return FeedFetchResult(feed=None, etag=etag, last_modified=last_modified)

    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    return FeedFetchResult(
        feed=feed,
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
    )
