from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import src
import src.alerts as alerts
import src.api
import src.api.routes
import src.config as config_module
import src.geo as geo
import src.scripts
from src.config import load_dotenv, read_float_env, with_static_gtfs_cache_path, with_target_coordinates
from src.monitor_models import DirectionId
from src.snapshot_view import MonitorSnapshotView
from src.target_passage import TargetPassageEstimator

from .support import make_snapshot, make_stop_time_update, make_target_window, make_train_status


def test_package_modules_import_cleanly() -> None:
    assert src.__doc__ == "Daemon Train monitoring package."
    assert importlib.import_module("src.api").__name__ == "src.api"
    assert importlib.import_module("src.api.routes").__name__ == "src.api.routes"
    assert src.scripts.__doc__ == "Utility scripts for the src package."


def test_clear_terminal_uses_platform_specific_command(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []
    monkeypatch.setattr(alerts.os, "system", commands.append)

    monkeypatch.setattr(alerts.os, "name", "nt")
    alerts.clear_terminal()

    monkeypatch.setattr(alerts.os, "name", "posix")
    alerts.clear_terminal()

    assert commands == ["cls", "clear"]


def test_haversine_m_is_zero_for_identical_points() -> None:
    assert geo.haversine_m(52.0, 4.0, 52.0, 4.0) == 0.0


def test_haversine_m_matches_expected_order_of_magnitude() -> None:
    distance = geo.haversine_m(52.0, 4.0, 52.0, 4.001)

    assert 60 < distance < 80


def test_load_dotenv_reads_values_without_overriding_existing_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                " TARGET_LATITUDE = 52.1 ",
                "TARGET_LONGITUDE='4.2'",
                "EMPTY=",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TARGET_LATITUDE", "99.0")
    monkeypatch.delenv("TARGET_LONGITUDE", raising=False)

    load_dotenv(env_file)

    assert config_module.os.environ["TARGET_LATITUDE"] == "99.0"
    assert config_module.os.environ["TARGET_LONGITUDE"] == "4.2"
    assert config_module.os.environ["EMPTY"] == ""


def test_read_float_env_supports_defaults_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_FLOAT", raising=False)
    assert read_float_env("MISSING_FLOAT", 1.25) == 1.25

    with pytest.raises(ValueError, match="MISSING_FLOAT"):
        read_float_env("MISSING_FLOAT")

    monkeypatch.setenv("BAD_FLOAT", "abc")
    with pytest.raises(ValueError, match="must be a float"):
        read_float_env("BAD_FLOAT")


def test_config_copy_helpers_replace_only_requested_fields(app_config) -> None:
    updated_target = with_target_coordinates(app_config, target_lat=1.0)
    updated_path = with_static_gtfs_cache_path(app_config, Path("other.zip"))

    assert updated_target.target_lat == 1.0
    assert updated_target.target_lon == app_config.target_lon
    assert updated_path.static_gtfs_cache_path == Path("other.zip")
    assert updated_path.target_lat == app_config.target_lat


def test_train_status_labels_and_range_checks(sample_train_status) -> None:
    assert sample_train_status.is_in_range_at(sample_train_status.estimated_target_time)
    assert not sample_train_status.is_in_range_at(sample_train_status.range_end_time + 1)
    assert sample_train_status.service_label() == "NS intercity"
    assert sample_train_status.route_label() == "Alpha -> Gamma"
    assert sample_train_status.stop_context_label() == "Beta -> Gamma"


def test_snapshot_view_selects_current_and_upcoming_trains() -> None:
    current = make_train_status(
        entity_key="current",
        estimated_target_time=100,
        range_start_time=90,
        range_end_time=110,
    )
    competing = make_train_status(
        entity_key="competing",
        estimated_target_time=98,
        range_start_time=70,
        range_end_time=130,
    )
    upcoming = make_train_status(
        entity_key="upcoming",
        estimated_target_time=150,
        range_start_time=140,
        range_end_time=170,
    )
    right = make_train_status(
        entity_key="right",
        direction_id=DirectionId.right,
        vehicle_details=make_train_status(direction_id=DirectionId.right).vehicle_details,
        estimated_target_time=160,
        range_start_time=150,
        range_end_time=180,
    )
    view = MonitorSnapshotView(
        snapshot=make_snapshot(
            left_trains=[upcoming, current, competing],
            right_trains=[right],
        ),
        display_timestamp=101,
    )

    assert view.select_current_train(DirectionId.left) is current
    assert view.select_next_upcoming_train(DirectionId.left) is upcoming
    assert view.trains_for_direction(DirectionId.right) == [right]


def test_snapshot_view_rejects_unknown_direction() -> None:
    view = MonitorSnapshotView(snapshot=make_snapshot(), display_timestamp=100)

    with pytest.raises(ValueError, match="Unsupported direction_id"):
        view.trains_for_direction("x")


def test_target_passage_estimator_derives_times_and_tolerances(app_config) -> None:
    estimator = TargetPassageEstimator(app_config)
    target_window = make_target_window(target_shape_dist=150.0, trip_total_shape_dist=200.0)
    trip_update = make_train_trip_update()

    assert estimator.estimate_trip_target_time(trip_update, target_window) == 150
    assert estimator.estimate_target_tolerance_seconds(trip_update, target_window) == 30
    assert estimator.estimate_range_start_time(150, 30) == 120
    assert estimator.estimate_sparse_update_tolerance_multiplier(30) == 1.0
    assert estimator.estimate_sparse_update_tolerance_multiplier(90) == 2.0


def test_target_passage_estimator_handles_missing_times(app_config) -> None:
    estimator = TargetPassageEstimator(app_config)
    target_window = make_target_window()
    trip_update = make_trip_update_missing_previous()

    assert estimator.estimate_trip_target_time(trip_update, target_window) is None
    assert estimator.estimate_target_tolerance_seconds(trip_update, target_window) == 60


def test_target_passage_resolve_event_time_prefers_requested_event(app_config) -> None:
    estimator = TargetPassageEstimator(app_config)
    stop_time_update = make_stop_time_update(2, "stop-b", arrival=120, departure=125)

    assert estimator.resolve_event_time(stop_time_update, prefer_departure=True) == 125
    assert estimator.resolve_event_time(stop_time_update, prefer_departure=False) == 120


def make_train_trip_update():
    from .support import make_trip_update

    return make_trip_update(
        stop_time_updates=[
            make_stop_time_update(2, "stop-b", departure=100),
            make_stop_time_update(3, "stop-c", arrival=200),
        ]
    )


def make_trip_update_missing_previous():
    from .support import make_trip_update

    return make_trip_update(
        stop_time_updates=[
            make_stop_time_update(3, "stop-c", arrival=200),
        ]
    )
