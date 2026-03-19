from __future__ import annotations

from dataclasses import dataclass

from src.monitor_models import DirectionId, MonitorSnapshot, TrainStatus


@dataclass(frozen=True)
class MonitorSnapshotView:
    snapshot: MonitorSnapshot | None
    display_timestamp: int

    def trains_for_direction(self, direction_id: str) -> list[TrainStatus]:
        """Return the train list for one direction bucket."""
        if self.snapshot is None:
            return []
        if direction_id == DirectionId.left:
            return self.snapshot.left_trains
        if direction_id == DirectionId.right:
            return self.snapshot.right_trains
        raise ValueError(f"Unsupported direction_id: {direction_id}")

    def select_current_train(self, direction_id: str) -> TrainStatus | None:
        """Return the most relevant in-range train for one direction."""
        in_range_statuses = [
            status
            for status in self.trains_for_direction(direction_id)
            if status.is_in_range_at(self.display_timestamp)
        ]
        if not in_range_statuses:
            return None

        return min(
            in_range_statuses,
            key=lambda status: (
                abs(status.estimated_target_time - self.display_timestamp),
                status.estimated_target_time,
                status.entity_key,
            ),
        )

    def select_next_upcoming_train(self, direction_id: str) -> TrainStatus | None:
        """Return the next train in a direction that has not yet entered its active window."""
        for status in self.trains_for_direction(direction_id):
            if status.range_start_time > self.display_timestamp:
                return status
        return None
