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
    distance_m: float
    estimated_target_time: int
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


@dataclass(frozen=True)
class MonitorSnapshot:
    feed_timestamp: int
    left_trains: list[TrainStatus]
    right_trains: list[TrainStatus]
