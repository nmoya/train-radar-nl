from __future__ import annotations

import src.monitor_snapshot_builder as builder_module
from src.monitor_snapshot_builder import MonitorSnapshotBuilder
from src.target_passage import TargetPassageEstimator

from .support import make_config, make_entity, make_feed, make_feed_update, make_static_gtfs_data, make_vehicle_details


def test_build_returns_none_without_feed_or_static_gtfs(tmp_path) -> None:
    estimator = TargetPassageEstimator(make_config(tmp_path / "cache.zip"))

    assert MonitorSnapshotBuilder(None, estimator).build(make_feed_update(feed=None)) is None


def test_latest_trip_updates_keep_newest_entity(tmp_path) -> None:
    builder = MonitorSnapshotBuilder(
        make_static_gtfs_data(),
        TargetPassageEstimator(make_config(tmp_path / "cache.zip")),
    )
    older = make_entity(entity_id="older", trip_id="trip-1", timestamp=100)
    newer = make_entity(entity_id="newer", trip_id="trip-1", timestamp=200)
    right = make_entity(entity_id="right", trip_id="trip-2", timestamp=150)
    feed = make_feed(entities=[older, newer, right])

    latest = builder.latest_trip_updates_by_trip_id(feed)

    assert {entity.id for entity in latest} == {"newer", "right"}
    assert builder.entity_sort_timestamp(newer, 0) == 200
    assert builder.build_entity_key(newer) == "trip-1"


def test_evaluate_train_entity_builds_status(tmp_path, monkeypatch) -> None:
    static_gtfs_data = make_static_gtfs_data()
    builder = MonitorSnapshotBuilder(
        static_gtfs_data,
        TargetPassageEstimator(make_config(tmp_path / "cache.zip")),
    )
    entity = make_entity(trip_id="trip-1")

    monkeypatch.setattr(builder_module, "is_train_vehicle", lambda entity, static_gtfs: True)
    monkeypatch.setattr(builder.estimator, "estimate_trip_target_time", lambda trip_update, target_window: 150)
    monkeypatch.setattr(builder.estimator, "estimate_target_tolerance_seconds", lambda trip_update, target_window: 20)
    monkeypatch.setattr(builder.estimator, "estimate_range_start_time", lambda estimated_target_time, tolerance: 115)
    monkeypatch.setattr(
        builder_module,
        "resolve_vehicle_details",
        lambda entity, static_gtfs, feed_timestamp: make_vehicle_details(direction_id="1"),
    )

    status = builder.evaluate_train_entity(entity, 100)

    assert status is not None
    assert status.direction_id == "1"
    assert status.estimated_target_time == 150
    assert status.range_start_time == 115
    assert status.range_end_time == 170


def test_evaluate_train_entity_skips_unusable_entities(tmp_path, monkeypatch) -> None:
    static_gtfs_data = make_static_gtfs_data()
    builder = MonitorSnapshotBuilder(
        static_gtfs_data,
        TargetPassageEstimator(make_config(tmp_path / "cache.zip")),
    )
    entity = make_entity(trip_id="missing-trip")

    monkeypatch.setattr(builder_module, "is_train_vehicle", lambda entity, static_gtfs: True)
    assert builder.evaluate_train_entity(entity, 100) is None

    entity = make_entity(trip_id="trip-1")
    monkeypatch.setattr(builder.estimator, "estimate_trip_target_time", lambda trip_update, target_window: None)
    assert builder.evaluate_train_entity(entity, 100) is None


def test_build_monitor_snapshot_groups_and_sorts(tmp_path) -> None:
    builder = MonitorSnapshotBuilder(
        make_static_gtfs_data(),
        TargetPassageEstimator(make_config(tmp_path / "cache.zip")),
    )
    left_late = builder_module.TrainStatus(
        entity_key="b",
        direction_id="0",
        vehicle_details=make_vehicle_details(direction_id="0"),
        target_window=make_static_gtfs_data().target_windows["trip-1"],
        distance_m=40.0,
        estimated_target_time=130,
        range_start_time=120,
        range_end_time=140,
    )
    left_early = builder_module.TrainStatus(
        entity_key="a",
        direction_id="0",
        vehicle_details=make_vehicle_details(direction_id="0"),
        target_window=make_static_gtfs_data().target_windows["trip-1"],
        distance_m=40.0,
        estimated_target_time=120,
        range_start_time=110,
        range_end_time=130,
    )
    right = builder_module.TrainStatus(
        entity_key="c",
        direction_id="1",
        vehicle_details=make_vehicle_details(direction_id="1"),
        target_window=make_static_gtfs_data().target_windows["trip-2"],
        distance_m=40.0,
        estimated_target_time=140,
        range_start_time=135,
        range_end_time=150,
    )

    snapshot = builder.build_monitor_snapshot(999, [left_late, right, left_early])

    assert [status.entity_key for status in snapshot.left_trains] == ["a", "b"]
    assert [status.entity_key for status in snapshot.right_trains] == ["c"]
