from __future__ import annotations

from google.transit import gtfs_realtime_pb2

from feed import FeedUpdate
from monitor_models import DirectionId, MonitorSnapshot, TrainStatus
from static_gtfs import StaticGtfsData, is_train_vehicle, resolve_vehicle_details
from target_passage import TargetPassageEstimator


class MonitorSnapshotBuilder:
    def __init__(self, static_gtfs: StaticGtfsData | None, estimator: TargetPassageEstimator):
        self.static_gtfs = static_gtfs
        self.estimator = estimator

    def build(self, feed_update: FeedUpdate) -> MonitorSnapshot | None:
        """Build the next monitor snapshot from one feed update."""
        if feed_update.feed is None or self.static_gtfs is None:
            return None

        latest_entities = self.latest_trip_updates_by_trip_id(feed_update.feed)
        evaluated_trains = self.build_evaluated_trains(
            latest_entities,
            feed_update.feed_timestamp,
        )

        return self.build_monitor_snapshot(
            feed_update.feed_timestamp,
            evaluated_trains,
        )

    def build_evaluated_trains(
        self,
        entities: list[gtfs_realtime_pb2.FeedEntity],
        feed_timestamp: int,
    ) -> list[TrainStatus]:
        """Evaluate all feed entities and keep only those that resolve to usable train data."""
        evaluated_trains: list[TrainStatus] = []

        for entity in entities:
            train_status = self.evaluate_train_entity(entity, feed_timestamp)
            if train_status is not None:
                evaluated_trains.append(train_status)

        return evaluated_trains

    def evaluate_train_entity(
        self,
        entity: gtfs_realtime_pb2.FeedEntity,
        feed_timestamp: int,
    ) -> TrainStatus | None:
        """Evaluate one trip-update entity into a derived train status."""
        if self.static_gtfs is None:
            return None
        if not entity.HasField("trip_update"):
            return None
        if not is_train_vehicle(entity, self.static_gtfs):
            return None

        trip_id = entity.trip_update.trip.trip_id if entity.trip_update.trip.trip_id else ""
        target_window = self.static_gtfs.target_windows.get(trip_id)
        if target_window is None:
            return None

        estimated_target_time = self.estimator.estimate_trip_target_time(
            entity.trip_update,
            target_window,
        )
        if estimated_target_time is None:
            return None

        tolerance_seconds = self.estimator.estimate_target_tolerance_seconds(
            entity.trip_update,
            target_window,
        )
        vehicle_details = resolve_vehicle_details(entity, self.static_gtfs, feed_timestamp)
        range_start_time = self.estimator.estimate_range_start_time(
            estimated_target_time,
            tolerance_seconds,
        )
        range_end_time = estimated_target_time + tolerance_seconds
        status = TrainStatus(
            entity_key=self.build_entity_key(entity),
            direction_id=vehicle_details.direction_id,
            vehicle_details=vehicle_details,
            target_window=target_window,
            distance_m=target_window.distance_to_target_m,
            estimated_target_time=estimated_target_time,
            range_start_time=range_start_time,
            range_end_time=range_end_time,
        )

        return status

    def build_monitor_snapshot(
        self,
        feed_timestamp: int,
        train_statuses: list[TrainStatus],
    ) -> MonitorSnapshot:
        """Group train statuses into the left and right direction buckets used by the UI."""
        return MonitorSnapshot(
            feed_timestamp=feed_timestamp,
            left_trains=self.sort_train_statuses(
                [status for status in train_statuses if status.direction_id == DirectionId.left]
            ),
            right_trains=self.sort_train_statuses(
                [status for status in train_statuses if status.direction_id == DirectionId.right]
            ),
        )

    def sort_train_statuses(self, train_statuses: list[TrainStatus]) -> list[TrainStatus]:
        """Sort train statuses by the earliest point they become relevant to the target."""
        return sorted(
            train_statuses,
            key=lambda status: (
                status.range_start_time,
                status.estimated_target_time,
                status.entity_key,
            ),
        )

    def latest_trip_updates_by_trip_id(
        self,
        feed: gtfs_realtime_pb2.FeedMessage,
    ) -> list[gtfs_realtime_pb2.FeedEntity]:
        """Return the latest trip-update entity for each non-empty trip_id."""
        latest_by_trip_id: dict[str, gtfs_realtime_pb2.FeedEntity] = {}
        feed_timestamp = feed.header.timestamp or 0

        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue

            trip_id = entity.trip_update.trip.trip_id if entity.trip_update.trip.trip_id else ""
            if not trip_id:
                continue

            current = latest_by_trip_id.get(trip_id)
            if current is None or self.entity_sort_timestamp(entity, feed_timestamp) >= self.entity_sort_timestamp(
                current,
                feed_timestamp,
            ):
                latest_by_trip_id[trip_id] = entity

        return list(latest_by_trip_id.values())

    def entity_sort_timestamp(
        self,
        entity: gtfs_realtime_pb2.FeedEntity,
        feed_timestamp: int,
    ) -> int:
        """Return the timestamp used to compare multiple entities for the same trip."""
        return entity.trip_update.timestamp or feed_timestamp

    def build_entity_key(self, entity: gtfs_realtime_pb2.FeedEntity) -> str:
        """Return the stable identifier used to track a train across updates."""
        return entity.trip_update.trip.trip_id or entity.id
