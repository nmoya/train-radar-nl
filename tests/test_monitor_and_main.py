from __future__ import annotations

import argparse
import builtins

import pytest

import src.main as main_module
import src.monitor as monitor_module
from src.feed import StaticGtfsLoadResult
from src.monitor import MonitorRenderer

from .support import make_config, make_feed_update, make_snapshot, make_static_gtfs_data, make_train_status, make_vehicle_details


def test_monitor_renderer_formats_lines(app_config, sample_static_gtfs_data) -> None:
    current = make_train_status(estimated_target_time=110, range_start_time=90, range_end_time=130)
    upcoming = make_train_status(
        entity_key="next",
        estimated_target_time=170,
        range_start_time=150,
        range_end_time=190,
    )
    snapshot = make_snapshot(left_trains=[current, upcoming], right_trains=[])
    renderer = MonitorRenderer(
        snapshot=snapshot,
        next_poll_in_seconds=7,
        display_timestamp=100,
        config=app_config,
        static_gtfs=sample_static_gtfs_data,
    )

    lines = renderer.build_lines()

    assert lines[0].endswith("Next poll in 7s")
    assert "Target  :" in lines[1]
    assert any(line.startswith("Windows : Beta -> Gamma") for line in lines)
    assert "Current" in lines
    assert any("ETA" in line for line in lines)
    assert any("in 50s" in line for line in lines)
    assert renderer.format_duration(3661) == "1h 01m 01s"
    assert renderer.format_duration(125) == "2m 05s"
    assert renderer.format_trip_progress(current.target_window) == "50%"


def test_monitor_renderer_handles_missing_static_gtfs_and_no_trains(app_config) -> None:
    renderer = MonitorRenderer(
        snapshot=None,
        next_poll_in_seconds=5,
        display_timestamp=100,
        config=app_config,
        static_gtfs=None,
    )

    header_lines = renderer.build_header_lines()
    current_lines = renderer.format_train_status("Left", None, is_current=True)
    upcoming_lines = renderer.format_train_status("Left", None, is_current=False)

    assert header_lines == [
        "Target  : lat=52.000000 lon=4.001400 radius=200m",
        "Static  : unavailable",
    ]
    assert current_lines == ["Left : no train in range"]
    assert upcoming_lines == ["Left : no upcoming train"]


def test_monitor_renderer_render_clears_terminal_and_prints(app_config, monkeypatch) -> None:
    renderer = MonitorRenderer(
        snapshot=None,
        next_poll_in_seconds=5,
        display_timestamp=100,
        config=app_config,
        static_gtfs=None,
    )
    cleared = []
    printed = []
    monkeypatch.setattr(monitor_module, "clear_terminal", lambda: cleared.append(True))
    monkeypatch.setattr(builtins, "print", printed.append)

    renderer.render()

    assert cleared == [True]
    assert len(printed) == 1
    assert "Static  : unavailable" in printed[0]


def test_monitor_main_rebuilds_snapshot_only_when_feed_version_changes(
    app_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    static_gtfs_data = make_static_gtfs_data()
    updates = iter(
        [
            make_feed_update(feed=None, next_poll_in_seconds=30, version=1, error="warn"),
            make_feed_update(feed=None, next_poll_in_seconds=29, version=1),
        ]
    )
    poller = type("Poller", (), {"update": lambda self: next(updates)})()
    build_calls: list[int] = []
    rendered_versions: list[int] = []

    class FakeBuilder:
        def __init__(self, static_gtfs, estimator):
            pass

        def build(self, feed_update):
            build_calls.append(feed_update.version)
            return f"snapshot-{feed_update.version}"

    class FakeRenderer:
        def __init__(self, snapshot, next_poll_in_seconds, display_timestamp, config, static_gtfs):
            rendered_versions.append((snapshot, next_poll_in_seconds))

        def render(self):
            if len(rendered_versions) == 2:
                raise RuntimeError("stop loop")

    monkeypatch.setattr(monitor_module, "MonitorSnapshotBuilder", FakeBuilder)
    monkeypatch.setattr(monitor_module, "MonitorRenderer", FakeRenderer)
    monkeypatch.setattr(monitor_module.time, "time", lambda: 100)
    monkeypatch.setattr(monitor_module.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="stop loop"):
        monitor_module.main(poller=poller, static_gtfs=static_gtfs_data, config=app_config)

    assert build_calls == [1]
    assert rendered_versions == [("snapshot-1", 30), ("snapshot-1", 29)]


def test_main_parse_args_reads_optional_coordinates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module.argparse.ArgumentParser, "parse_args", lambda self: argparse.Namespace(lat=1.2, lon=3.4))

    args = main_module.parse_args()

    assert args.lat == 1.2
    assert args.lon == 3.4


def test_main_cli_handles_success_and_error_paths(app_config, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    poller_close_calls = []

    class FakePoller:
        def __init__(self, config):
            self.config = config

        def load_static_gtfs(self):
            return StaticGtfsLoadResult(data="gtfs")

        def close(self):
            poller_close_calls.append(True)

    monkeypatch.setattr(main_module, "parse_args", lambda: argparse.Namespace(lat=1.0, lon=2.0))
    monkeypatch.setattr(main_module, "FeedPoller", FakePoller)
    monkeypatch.setattr(main_module, "main", lambda poller, static_gtfs, config: 9)

    assert main_module.cli() == 9
    assert poller_close_calls == [True]
    assert "Loading static GTFS..." in capsys.readouterr().out

    class ErrorPoller(FakePoller):
        def load_static_gtfs(self):
            return StaticGtfsLoadResult(data=None, error="bad gtfs")

    monkeypatch.setattr(main_module, "FeedPoller", ErrorPoller)
    with pytest.raises(SystemExit) as exc_info:
        main_module.cli()
    assert exc_info.value.code == 1


def test_main_cli_handles_none_keyboard_interrupt_and_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePoller:
        def __init__(self, config):
            pass

        def load_static_gtfs(self):
            return StaticGtfsLoadResult(data=None)

        def close(self):
            return None

    monkeypatch.setattr(main_module, "parse_args", lambda: argparse.Namespace(lat=None, lon=None))
    monkeypatch.setattr(main_module, "FeedPoller", FakePoller)
    assert main_module.cli() == 1

    class InterruptPoller(FakePoller):
        def load_static_gtfs(self):
            raise KeyboardInterrupt()

    monkeypatch.setattr(main_module, "FeedPoller", InterruptPoller)
    assert main_module.cli() == 0

    class BoomPoller(FakePoller):
        def load_static_gtfs(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "FeedPoller", BoomPoller)
    assert main_module.cli() == 1
