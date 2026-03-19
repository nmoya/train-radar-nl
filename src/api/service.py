from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import requests

from src.config import (
    AppConfig,
    FULL_STATIC_GTFS_CACHE_PATH,
    with_static_gtfs_cache_path,
    with_target_coordinates,
)
from src.feed import FeedPoller
from src.monitor_models import DirectionId, TrainStatus
from src.monitor_snapshot_builder import MonitorSnapshotBuilder
from src.snapshot_view import MonitorSnapshotView
from src.static_gtfs import StaticGtfsRows, build_static_gtfs_data, ensure_static_gtfs_zip, read_static_gtfs_rows
from src.target_passage import TargetPassageEstimator

from .models import DirectionBoardResponse, MonitorApiResponse, TargetLocationResponse, TrainStatusResponse


@dataclass(frozen=True)
class CacheEntry:
    expires_at: float
    response: MonitorApiResponse


class RadarApiService:
    def __init__(
        self,
        base_config: AppConfig,
        *,
        cache_ttl_seconds: int = 30,
    ) -> None:
        self._base_config = with_static_gtfs_cache_path(base_config, FULL_STATIC_GTFS_CACHE_PATH)
        self._cache_ttl_seconds = cache_ttl_seconds
        self._session = requests.Session()
        self._poller = FeedPoller(self._base_config, session=self._session)
        self._static_gtfs_rows: StaticGtfsRows | None = None
        self._cache: dict[tuple[float, float], CacheEntry] = {}
        self._lock = threading.Lock()

    @property
    def cache_ttl_seconds(self) -> int:
        return self._cache_ttl_seconds

    @property
    def static_gtfs_cache_path(self) -> str:
        return str(self._base_config.static_gtfs_cache_path)

    @property
    def static_gtfs_ready(self) -> bool:
        return self._static_gtfs_rows is not None

    @property
    def config(self) -> AppConfig:
        return self._base_config

    def startup(self) -> None:
        zip_path = ensure_static_gtfs_zip(self._session, self._base_config)
        self._static_gtfs_rows = read_static_gtfs_rows(zip_path)

    def shutdown(self) -> None:
        self._poller.close()

    def get_status(self, latitude: float, longitude: float) -> MonitorApiResponse:
        normalized_key = (round(latitude, 6), round(longitude, 6))
        now = time.monotonic()

        with self._lock:
            cached_entry = self._cache.get(normalized_key)
            if cached_entry is not None and cached_entry.expires_at > now:
                return cached_entry.response

        response = self._build_status(*normalized_key)

        with self._lock:
            self._cache = {
                key: entry for key, entry in self._cache.items() if entry.expires_at > now
            }
            self._cache[normalized_key] = CacheEntry(
                expires_at=now + self._cache_ttl_seconds,
                response=response,
            )

        return response

    def _build_status(self, latitude: float, longitude: float) -> MonitorApiResponse:
        if self._static_gtfs_rows is None:
            raise RuntimeError("Static GTFS rows are not loaded.")

        request_config = with_target_coordinates(
            self._base_config,
            target_lat=latitude,
            target_lon=longitude,
        )
        static_gtfs = build_static_gtfs_data(self._static_gtfs_rows, request_config)
        feed_update = self._poller.update()
        display_timestamp = int(time.time())
        snapshot = MonitorSnapshotBuilder(
            static_gtfs,
            TargetPassageEstimator(request_config),
        ).build(feed_update)
        view = MonitorSnapshotView(snapshot=snapshot, display_timestamp=display_timestamp)

        return MonitorApiResponse(
            generated_at=display_timestamp,
            cache_ttl_seconds=self._cache_ttl_seconds,
            cache_expires_at=display_timestamp + self._cache_ttl_seconds,
            feed_timestamp=snapshot.feed_timestamp if snapshot is not None else None,
            feed_error=feed_update.error,
            target=TargetLocationResponse(
                latitude=latitude,
                longitude=longitude,
                radius_meters=request_config.radius_meters,
            ),
            current=DirectionBoardResponse(
                left=self._build_train_response(
                    view.select_current_train(DirectionId.left),
                    display_timestamp,
                ),
                right=self._build_train_response(
                    view.select_current_train(DirectionId.right),
                    display_timestamp,
                ),
            ),
            upcoming=DirectionBoardResponse(
                left=self._build_train_response(
                    view.select_next_upcoming_train(DirectionId.left),
                    display_timestamp,
                ),
                right=self._build_train_response(
                    view.select_next_upcoming_train(DirectionId.right),
                    display_timestamp,
                ),
            ),
            target_stop_pairs=static_gtfs.summarize_target_stop_pairs(),
        )

    def _build_train_response(
        self,
        train_status: TrainStatus | None,
        display_timestamp: int,
    ) -> TrainStatusResponse | None:
        if train_status is None:
            return None

        progress_ratio = train_status.target_window.trip_progress_ratio()
        return TrainStatusResponse(
            service=train_status.service_label(),
            company=train_status.vehicle_details.train_company,
            train_type=train_status.vehicle_details.train_type,
            agency=train_status.vehicle_details.agency,
            route=train_status.route_label(),
            origin=train_status.vehicle_details.origin,
            destination=train_status.vehicle_details.destination,
            stop_context=train_status.stop_context_label(),
            previous_stop=train_status.vehicle_details.previous_stop,
            next_stop=train_status.vehicle_details.next_stop,
            direction_id=train_status.direction_id,
            progress_percent=None if progress_ratio is None else round(progress_ratio * 100),
            distance_to_target_m=train_status.distance_m,
            estimated_target_timestamp=train_status.estimated_target_time,
            estimated_target_time=time.strftime("%H:%M:%S", time.localtime(train_status.estimated_target_time)),
            range_start_timestamp=train_status.range_start_time,
            range_end_timestamp=train_status.range_end_time,
            seconds_until_target=train_status.estimated_target_time - display_timestamp,
            seconds_until_range=train_status.range_start_time - display_timestamp,
            is_in_range=train_status.is_in_range_at(display_timestamp),
        )
