from __future__ import annotations

import time
from dataclasses import dataclass

from src.api.presenter import build_monitor_api_response, build_train_response
from src.config import AppConfig
from src.feed import FeedPoller
from src.monitor_models import MonitorSnapshot, TrainStatus
from src.monitor_snapshot_builder import MonitorSnapshotBuilder
from src.static_gtfs import StaticGtfsRows, build_static_gtfs_data, read_static_gtfs_rows
from src.target_passage import TargetPassageEstimator
from src.api.ttl_cache import TtlCache

from .models import MonitorApiResponse, TrainStatusResponse


@dataclass(frozen=True)
class CachedMonitorStatus:
    snapshot: MonitorSnapshot | None
    feed_timestamp: int | None
    feed_error: str | None
    target_stop_pairs: list[str]
    cache_expires_at: int


class RadarApiService:
    def __init__(
        self,
        base_config: AppConfig,
        *,
        cache_ttl_seconds: int | None = None,
    ) -> None:
        self.base_config = base_config
        self.poller = FeedPoller(self.base_config)
        self.static_gtfs_rows: StaticGtfsRows | None = None
        self.response_cache = TtlCache[CachedMonitorStatus](
            cache_ttl_seconds or base_config.poll_interval_seconds
        )

    @property
    def cache_ttl_seconds(self) -> int:
        return self.response_cache.ttl_seconds

    @property
    def static_gtfs_cache_path(self) -> str:
        return str(self.base_config.static_gtfs_cache_path)

    @property
    def static_gtfs_ready(self) -> bool:
        return self.static_gtfs_rows is not None

    @property
    def config(self) -> AppConfig:
        return self.base_config

    def startup(self) -> None:
        zip_path = self.poller.ensure_static_gtfs_zip()
        self.static_gtfs_rows = read_static_gtfs_rows(zip_path)

    def shutdown(self) -> None:
        self.poller.close()

    def get_status(self) -> MonitorApiResponse:
        display_timestamp = int(time.time())
        cached_status = self.response_cache.get()
        if cached_status is None:
            cached_status = self.response_cache.set(self._build_cached_status(display_timestamp))

        return self._build_response(cached_status, display_timestamp)

    def _build_status(self) -> MonitorApiResponse:
        display_timestamp = int(time.time())
        cached_status = self._build_cached_status(display_timestamp)
        return self._build_response(cached_status, display_timestamp)

    def _build_cached_status(self, display_timestamp: int) -> CachedMonitorStatus:
        if self.static_gtfs_rows is None:
            raise RuntimeError("Static GTFS rows are not loaded.")

        config = self.base_config
        static_gtfs = build_static_gtfs_data(self.static_gtfs_rows, config)
        feed_update = self.poller.update()
        snapshot = MonitorSnapshotBuilder(
            static_gtfs,
            TargetPassageEstimator(config),
        ).build(feed_update)

        return CachedMonitorStatus(
            snapshot=snapshot,
            feed_timestamp=snapshot.feed_timestamp if snapshot is not None else None,
            feed_error=feed_update.error,
            target_stop_pairs=static_gtfs.summarize_target_stop_pairs(),
            cache_expires_at=display_timestamp + self.cache_ttl_seconds,
        )

    def _build_response(
        self,
        cached_status: CachedMonitorStatus,
        display_timestamp: int,
    ) -> MonitorApiResponse:
        return build_monitor_api_response(
            config=self.base_config,
            cached_status=cached_status,
            display_timestamp=display_timestamp,
            cache_ttl_seconds=self.cache_ttl_seconds,
        )

    def _build_train_response(
        self,
        train_status: TrainStatus | None,
        display_timestamp: int,
    ) -> TrainStatusResponse | None:
        return build_train_response(train_status, display_timestamp)
