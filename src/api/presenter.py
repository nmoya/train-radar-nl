from __future__ import annotations

import time
from typing import Protocol

from src.config import AppConfig
from src.monitor_models import DirectionId, TrainStatus
from src.snapshot_view import MonitorSnapshotView

from .models import DirectionBoardResponse, MonitorApiResponse, TargetLocationResponse, TrainStatusResponse


class CachedMonitorStatusLike(Protocol):
    snapshot: object | None
    feed_timestamp: int | None
    feed_error: str | None
    target_stop_pairs: list[str]
    cache_expires_at: int


def build_train_response(
    train_status: TrainStatus | None,
    display_timestamp: int,
) -> TrainStatusResponse | None:
    if train_status is None:
        return None

    progress_ratio = train_status.estimated_trip_progress_ratio(display_timestamp)
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
        distance_to_target_m=train_status.estimated_distance_to_target_m(display_timestamp),
        estimated_target_timestamp=train_status.estimated_target_time,
        estimated_target_time=time.strftime("%H:%M:%S", time.localtime(train_status.estimated_target_time)),
        range_start_timestamp=train_status.range_start_time,
        range_end_timestamp=train_status.range_end_time,
        seconds_until_target=train_status.estimated_target_time - display_timestamp,
        seconds_until_range=train_status.range_start_time - display_timestamp,
        is_in_range=train_status.is_in_range_at(display_timestamp),
    )


def build_monitor_api_response(
    *,
    config: AppConfig,
    cached_status: CachedMonitorStatusLike,
    display_timestamp: int,
    cache_ttl_seconds: int,
) -> MonitorApiResponse:
    view = MonitorSnapshotView(snapshot=cached_status.snapshot, display_timestamp=display_timestamp)

    return MonitorApiResponse(
        generated_at=display_timestamp,
        cache_ttl_seconds=cache_ttl_seconds,
        cache_expires_at=cached_status.cache_expires_at,
        feed_timestamp=cached_status.feed_timestamp,
        feed_error=cached_status.feed_error,
        target=TargetLocationResponse(
            latitude=config.target_lat,
            longitude=config.target_lon,
            radius_meters=config.radius_meters,
        ),
        current=DirectionBoardResponse(
            left=build_train_response(
                view.select_current_train(DirectionId.left),
                display_timestamp,
            ),
            right=build_train_response(
                view.select_current_train(DirectionId.right),
                display_timestamp,
            ),
        ),
        upcoming=DirectionBoardResponse(
            left=build_train_response(
                view.select_next_upcoming_train(DirectionId.left),
                display_timestamp,
            ),
            right=build_train_response(
                view.select_next_upcoming_train(DirectionId.right),
                display_timestamp,
            ),
        ),
        target_stop_pairs=cached_status.target_stop_pairs,
    )
