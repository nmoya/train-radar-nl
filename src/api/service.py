from __future__ import annotations

import time

from src.config import AppConfig
from src.feed import FeedPoller
from src.monitor_models import DirectionId, TrainStatus
from src.monitor_snapshot_builder import MonitorSnapshotBuilder
from src.snapshot_view import MonitorSnapshotView
from src.static_gtfs import StaticGtfsRows, build_static_gtfs_data, read_static_gtfs_rows
from src.target_passage import TargetPassageEstimator
from src.api.ttl_cache import TtlCache

from .models import DirectionBoardResponse, MonitorApiResponse, TargetLocationResponse, TrainStatusResponse


class RadarApiService:
    def __init__(
        self,
        base_config: AppConfig,
        *,
        cache_ttl_seconds: int = 30,
    ) -> None:
        self.base_config = base_config
        self.poller = FeedPoller(self.base_config)
        self.static_gtfs_rows: StaticGtfsRows | None = None
        self.response_cache = TtlCache[MonitorApiResponse](cache_ttl_seconds)

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
        cached_response = self.response_cache.get()
        if cached_response is not None:
            return cached_response

        response = self._build_status()
        return self.response_cache.set(response)

    def _build_status(self) -> MonitorApiResponse:
        if self.static_gtfs_rows is None:
            raise RuntimeError("Static GTFS rows are not loaded.")

        config = self.base_config
        static_gtfs = build_static_gtfs_data(self.static_gtfs_rows, config)
        feed_update = self.poller.update()
        display_timestamp = int(time.time())
        snapshot = MonitorSnapshotBuilder(
            static_gtfs,
            TargetPassageEstimator(config),
        ).build(feed_update)
        view = MonitorSnapshotView(snapshot=snapshot, display_timestamp=display_timestamp)

        return MonitorApiResponse(
            generated_at=display_timestamp,
            cache_ttl_seconds=self.cache_ttl_seconds,
            cache_expires_at=display_timestamp + self.cache_ttl_seconds,
            feed_timestamp=snapshot.feed_timestamp if snapshot is not None else None,
            feed_error=feed_update.error,
            target=TargetLocationResponse(
                latitude=config.target_lat,
                longitude=config.target_lon,
                radius_meters=config.radius_meters,
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
