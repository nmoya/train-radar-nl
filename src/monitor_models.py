from __future__ import annotations

from dataclasses import dataclass

from src.static_gtfs import TargetWindow, VehicleDetails


class DirectionId:
    left = "0"
    right = "1"


@dataclass(frozen=True)
class TrainStatus:
    entity_key: str
    direction_id: str
    vehicle_details: VehicleDetails
    target_window: TargetWindow
    previous_stop_time: int
    estimated_target_time: int
    next_stop_time: int
    range_start_time: int
    range_end_time: int

    def is_in_range_at(self, display_timestamp: int) -> bool:
        """Return whether a display timestamp falls inside this train's active window."""
        return self.range_start_time <= display_timestamp <= self.range_end_time

    def service_label(self) -> str:
        """Return a compact service label for the dashboard."""
        parts = [self.vehicle_details.train_company, self.vehicle_details.train_type]
        return " ".join(part for part in parts if part) or "Unknown service"

    def route_label(self) -> str:
        """Return the train's full route label."""
        return f"{self.vehicle_details.origin} -> {self.vehicle_details.destination}"

    def stop_context_label(self) -> str:
        """Return the local previous/next stop context around the target."""
        return f"{self.vehicle_details.previous_stop} -> {self.vehicle_details.next_stop}"

    def estimated_distance_to_target_m(self, display_timestamp: int) -> float:
        """Estimate the train's distance from the target along the trip path."""
        current_path_m = self.estimated_path_position_m(display_timestamp)
        return abs(self.target_window.target_path_m - current_path_m)

    def estimated_trip_progress_ratio(self, display_timestamp: int) -> float | None:
        """Estimate the train's current progress through the trip as a 0..1 ratio."""
        if self.target_window.trip_total_path_m <= 0:
            return None

        current_path_m = self.estimated_path_position_m(display_timestamp)
        return min(max(current_path_m / self.target_window.trip_total_path_m, 0.0), 1.0)

    def estimated_path_position_m(self, display_timestamp: int) -> float:
        """Estimate the train's current path position in meters along the trip shape."""
        if display_timestamp <= self.estimated_target_time:
            return self.interpolate_path_position(
                display_timestamp,
                self.previous_stop_time,
                self.estimated_target_time,
                self.target_window.previous_stop_path_m,
                self.target_window.target_path_m,
            )
        return self.interpolate_path_position(
            display_timestamp,
            self.estimated_target_time,
            self.next_stop_time,
            self.target_window.target_path_m,
            self.target_window.next_stop_path_m,
        )

    def interpolate_path_position(
        self,
        display_timestamp: int,
        start_time: int,
        end_time: int,
        start_path_m: float,
        end_path_m: float,
    ) -> float:
        if end_time <= start_time:
            return start_path_m

        progress_ratio = min(max((display_timestamp - start_time) / (end_time - start_time), 0.0), 1.0)
        return start_path_m + ((end_path_m - start_path_m) * progress_ratio)


@dataclass(frozen=True)
class MonitorSnapshot:
    feed_timestamp: int
    left_trains: list[TrainStatus]
    right_trains: list[TrainStatus]
