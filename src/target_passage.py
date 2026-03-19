from __future__ import annotations

from google.transit import gtfs_realtime_pb2

from src.config import AppConfig
from src.static_gtfs import TargetWindow


class TargetPassageEstimator:
    def __init__(self, config: AppConfig):
        self.config = config

    def estimate_trip_target_time(
        self,
        trip_update: gtfs_realtime_pb2.TripUpdate,
        target_window: TargetWindow,
    ) -> int | None:
        """Estimate the target passage time from the realtime stop updates around the target."""
        previous_time, next_time = self.extract_target_window_event_times(trip_update, target_window)

        if previous_time is None or next_time is None:
            return None

        return target_window.estimate_target_time(previous_time, next_time)

    def estimate_target_tolerance_seconds(
        self,
        trip_update: gtfs_realtime_pb2.TripUpdate,
        target_window: TargetWindow,
    ) -> int:
        """Estimate the alert window around the target passage time."""
        previous_time, next_time = self.extract_target_window_event_times(trip_update, target_window)

        if previous_time is None or next_time is None:
            return self.config.target_passage_tolerance_ceiling_seconds

        segment_duration_seconds = max(next_time - previous_time, 1)
        dynamic_tolerance_seconds = round(
            segment_duration_seconds * self.config.target_passage_tolerance_factor
        )
        directional_tolerance_seconds = round(
            dynamic_tolerance_seconds * self.estimate_directional_tolerance_multiplier(target_window)
        )
        return max(
            max(
                self.config.target_passage_tolerance_floor_seconds,
                self.config.poll_interval_seconds,
            ),
            min(
                self.config.target_passage_tolerance_ceiling_seconds,
                directional_tolerance_seconds,
            ),
        )

    def estimate_range_start_time(
        self,
        estimated_target_time: int,
        tolerance_seconds: int,
    ) -> int:
        """Return the start of the alert window, including configured early lead time."""
        early_tolerance_seconds = tolerance_seconds + self.config.target_passage_alert_lead_seconds
        return estimated_target_time - early_tolerance_seconds

    def estimate_directional_tolerance_multiplier(
        self,
        target_window: TargetWindow,
    ) -> float:
        """Scale tolerance based on how far into the trip the target lies."""
        progress_ratio = target_window.trip_progress_ratio()
        if progress_ratio is None:
            return 1.0
        return 1.0 + (progress_ratio * self.config.target_passage_directional_tolerance_factor)

    def extract_target_window_event_times(
        self,
        trip_update: gtfs_realtime_pb2.TripUpdate,
        target_window: TargetWindow,
    ) -> tuple[int | None, int | None]:
        """Extract the realtime timestamps for the stop pair bracketing the target point."""
        previous_time = None
        next_time = None

        for stop_time_update in trip_update.stop_time_update:
            if stop_time_update.stop_sequence == target_window.previous_stop_sequence:
                previous_time = self.resolve_event_time(stop_time_update, prefer_departure=True)
            if stop_time_update.stop_sequence == target_window.next_stop_sequence:
                next_time = self.resolve_event_time(stop_time_update, prefer_departure=False)
            if previous_time is not None and next_time is not None:
                break

        return previous_time, next_time

    def resolve_event_time(
        self,
        stop_time_update: gtfs_realtime_pb2.TripUpdate.StopTimeUpdate,
        prefer_departure: bool,
    ) -> int | None:
        """Extract the preferred realtime event time from a stop update, with fallback."""
        primary_event = stop_time_update.departure if prefer_departure else stop_time_update.arrival
        fallback_event = stop_time_update.arrival if prefer_departure else stop_time_update.departure

        if primary_event.HasField("time"):
            return primary_event.time
        if fallback_event.HasField("time"):
            return fallback_event.time
        return None
