from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from src.alerts import clear_terminal
from src.config import DEFAULT_CONFIG, AppConfig
from src.feed import FeedPoller
from src.monitor_models import DirectionId, MonitorSnapshot, TrainStatus
from src.monitor_snapshot_builder import MonitorSnapshotBuilder
from src.snapshot_view import MonitorSnapshotView
from src.static_gtfs import StaticGtfsData, TargetWindow
from src.target_passage import TargetPassageEstimator


@dataclass(frozen=True)
class MonitorRenderer:
    snapshot: MonitorSnapshot | None
    next_poll_in_seconds: int
    display_timestamp: int
    config: AppConfig
    static_gtfs: StaticGtfsData | None

    @property
    def view(self) -> MonitorSnapshotView:
        return MonitorSnapshotView(snapshot=self.snapshot, display_timestamp=self.display_timestamp)

    def build_lines(self) -> list[str]:
        """Build the terminal view as plain text lines for the current display tick."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.display_timestamp))
        lines = [
            f"[{timestamp}] Next poll in {self.next_poll_in_seconds}s",
            *self.build_header_lines(),
            "",
        ]

        lines.extend(
            self.build_section_lines(
                "Current",
                self.view.select_current_train(DirectionId.left),
                self.view.select_current_train(DirectionId.right),
                is_current=True,
            )
        )
        lines.append("")
        lines.extend(
            self.build_section_lines(
                "Upcoming",
                self.view.select_next_upcoming_train(DirectionId.left),
                self.view.select_next_upcoming_train(DirectionId.right),
                is_current=False,
            )
        )
        return lines

    def build_header_lines(self) -> list[str]:
        """Build the persistent dashboard header with config and GTFS summary."""
        lines = [
            (
                "Target  : "
                f"lat={self.config.target_lat:.6f} "
                f"lon={self.config.target_lon:.6f} "
                f"radius={self.config.radius_meters}m"
            )
        ]

        if self.static_gtfs is None:
            lines.append("Static  : unavailable")
            return lines

        lines.append(
            (
                "Static  : "
                f"routes={len(self.static_gtfs.routes)} "
                f"trips={len(self.static_gtfs.trips)} "
                f"stops={len(self.static_gtfs.stops)} "
                f"target_windows={len(self.static_gtfs.target_windows)}"
            )
        )

        stop_pairs = self.static_gtfs.summarize_target_stop_pairs()
        if stop_pairs:
            lines.append("Windows : " + " | ".join(stop_pairs))

        return lines

    def render(self) -> None:
        """Render the monitor dashboard to the terminal."""
        clear_terminal()
        print("\n".join(self.build_lines()))

    def format_duration(self, seconds: int) -> str:
        """Format a duration in seconds as a compact human-readable string."""
        total_seconds = max(seconds, 0)
        minutes, remaining_seconds = divmod(total_seconds, 60)
        hours, remaining_minutes = divmod(minutes, 60)

        if hours > 0:
            return f"{hours}h {remaining_minutes:02d}m {remaining_seconds:02d}s"
        if minutes > 0:
            return f"{minutes}m {remaining_seconds:02d}s"
        return f"{remaining_seconds}s"

    def format_unix_timestamp(self, timestamp: int) -> str:
        """Format a Unix timestamp as local HH:MM:SS."""
        return time.strftime("%H:%M:%S", time.localtime(timestamp))

    def format_trip_progress(self, target_window: TargetWindow) -> str:
        """Format trip progress through the monitored target as a percentage string."""
        progress_ratio = target_window.trip_progress_ratio()
        if progress_ratio is None:
            return "?%"
        return f"{round(progress_ratio * 100)}%"

    def build_section_lines(
        self,
        title: str,
        left_status: TrainStatus | None,
        right_status: TrainStatus | None,
        *,
        is_current: bool,
    ) -> list[str]:
        """Build one dashboard section with left and right directional train blocks."""
        return [
            title,
            *self.format_train_status("Right", right_status, is_current=is_current),
            "",
            *self.format_train_status("Left", left_status, is_current=is_current),
        ]

    def format_train_status(
        self,
        direction_label: str,
        status: TrainStatus | None,
        *,
        is_current: bool,
    ) -> list[str]:
        """Format one directional train block for either the current or upcoming section."""
        row_prefix = f"{direction_label:<5}: "
        detail_prefix = " " * len(row_prefix)

        if status is None:
            return [f"{row_prefix}{'no train in range' if is_current else 'no upcoming train'}"]

        if is_current:
            if self.display_timestamp > status.estimated_target_time:
                timing = f"late by {self.format_duration(self.display_timestamp - status.estimated_target_time)}"
            else:
                timing = f"ETA {self.format_unix_timestamp(status.estimated_target_time)}"
            context_suffix = f"{round(status.distance_m)}m to target"
        else:
            seconds_until_range = max(status.range_start_time - self.display_timestamp, 0)
            timing = f"in {self.format_duration(seconds_until_range)}"
            context_suffix = f"Expected {self.format_unix_timestamp(status.estimated_target_time)}"

        return [
            f"{row_prefix}{status.service_label()}  {timing}",
            f"{detail_prefix}{status.route_label()} ({self.format_trip_progress(status.target_window)} completed)",
            f"{detail_prefix}{status.stop_context_label()}  {context_suffix}",
        ]


def main(
    poller: FeedPoller,
    static_gtfs: StaticGtfsData | None,
    config: AppConfig = DEFAULT_CONFIG,
) -> int:
    """Run the monitor loop, polling, processing, and rendering once per second."""
    latest_snapshot: MonitorSnapshot | None = None
    latest_feed_version = -1
    snapshot_builder = MonitorSnapshotBuilder(static_gtfs, TargetPassageEstimator(config))

    while True:
        feed_update = poller.update()
        if feed_update.error:
            print(feed_update.error, file=sys.stderr)

        if feed_update.version != latest_feed_version:
            latest_snapshot = snapshot_builder.build(feed_update)
            latest_feed_version = feed_update.version

        MonitorRenderer(
            snapshot=latest_snapshot,
            next_poll_in_seconds=feed_update.next_poll_in_seconds,
            display_timestamp=int(time.time()),
            config=config,
            static_gtfs=static_gtfs,
        ).render()
        time.sleep(1)
