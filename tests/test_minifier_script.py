from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import pytest

import src.scripts.build_minimal_gtfs_zip as script
from src.scripts.build_minimal_gtfs_zip import (
    ShapePoint,
    StopTimePoint,
    build_minimal_gtfs_zip,
    ensure_source_gtfs_zip,
    has_bracketing_stops,
    trim_row,
    write_csv,
)


def write_source_gtfs_zip(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.writestr(
            "routes.txt",
            "\n".join(
                [
                    "route_id,agency_id,route_short_name,route_long_name,route_desc,route_type",
                    "route-1,IFF:NS,IC,Intercity,Amsterdam to Utrecht,2",
                    "route-bus,BUS,B,Bus,,3",
                ]
            ),
        )
        zip_file.writestr(
            "trips.txt",
            "\n".join(
                [
                    "trip_id,route_id,trip_headsign,trip_short_name,direction_id,shape_id",
                    "trip-1,route-1,Gamma,Intercity 123,0,shape-1",
                    "trip-bus,route-bus,Elsewhere,Bus 9,0,shape-bus",
                ]
            ),
        )
        zip_file.writestr(
            "stops.txt",
            "\n".join(
                [
                    "stop_id,stop_name",
                    "stop-a,Alpha",
                    "stop-b,Beta",
                    "stop-c,Gamma",
                ]
            ),
        )
        zip_file.writestr(
            "stop_times.txt",
            "\n".join(
                [
                    "trip_id,stop_sequence,stop_id,shape_dist_traveled",
                    "trip-1,1,stop-a,0",
                    "trip-1,2,stop-b,100",
                    "trip-1,3,stop-c,200",
                    "trip-bus,1,stop-a,0",
                ]
            ),
        )
        zip_file.writestr(
            "shapes.txt",
            "\n".join(
                [
                    "shape_id,shape_pt_lat,shape_pt_lon,shape_dist_traveled",
                    "shape-1,52.0,4.0000,0",
                    "shape-1,52.0,4.0010,100",
                    "shape-1,52.0,4.0020,200",
                    "shape-bus,53.0,5.0,0",
                ]
            ),
        )


def test_parse_args_uses_environment_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TARGET_LATITUDE", "52.1")
    monkeypatch.setenv("TARGET_LONGITUDE", "4.2")
    monkeypatch.setattr(script, "load_dotenv", lambda path: None)
    monkeypatch.setattr(
        script.argparse.ArgumentParser,
        "parse_args",
        lambda self: argparse.Namespace(
            input=tmp_path / "in.zip",
            output=tmp_path / "out.zip",
            lat=None,
            lon=None,
            radius_meters=200.0,
            route_type="2",
        ),
    )

    args = script.parse_args()

    assert args.lat == 52.1
    assert args.lon == 4.2


def test_parse_args_reports_missing_or_invalid_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TARGET_LATITUDE", raising=False)
    monkeypatch.delenv("TARGET_LONGITUDE", raising=False)
    monkeypatch.setattr(script, "load_dotenv", lambda path: None)

    class Parser:
        def __init__(self, *args, **kwargs):
            pass

        def add_argument(self, *args, **kwargs):
            return None

        def parse_args(self):
            return argparse.Namespace(
                input=tmp_path / "in.zip",
                output=tmp_path / "out.zip",
                lat=None,
                lon=4.2,
                radius_meters=200.0,
                route_type="2",
            )

        def error(self, message):
            raise RuntimeError(message)

    monkeypatch.setattr(script.argparse, "ArgumentParser", Parser)
    with pytest.raises(RuntimeError, match="TARGET_LATITUDE"):
        script.parse_args()

    monkeypatch.setenv("TARGET_LATITUDE", "bad")
    monkeypatch.setenv("TARGET_LONGITUDE", "4.2")
    monkeypatch.setattr(
        script.argparse.ArgumentParser,
        "parse_args",
        lambda self: argparse.Namespace(
            input=tmp_path / "in.zip",
            output=tmp_path / "out.zip",
            lat=None,
            lon=None,
            radius_meters=200.0,
            route_type="2",
        ),
    )
    with pytest.raises(ValueError, match="must be a float"):
        script.parse_args()


def test_row_helpers_and_write_csv(tmp_path: Path) -> None:
    assert trim_row({"a": "1", "b": "2"}, ("a", "c")) == {"a": "1", "c": ""}
    assert has_bracketing_stops(
        [
            StopTimePoint("trip-1", 1, "a", 0.0, {}),
            StopTimePoint("trip-1", 2, "b", 100.0, {}),
        ],
        50.0,
    ) is True

    zip_path = tmp_path / "out.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        write_csv(zip_file, "routes.txt", ("route_id",), [{"route_id": "route-1"}])

    with zipfile.ZipFile(zip_path) as zip_file:
        assert zip_file.read("routes.txt").decode("utf-8") == "route_id\nroute-1\n"


def test_build_minimal_gtfs_zip_filters_source_zip(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "source.zip"
    output_path = tmp_path / "minimal.zip"
    write_source_gtfs_zip(input_path)

    build_minimal_gtfs_zip(
        input_path=input_path,
        output_path=output_path,
        target_lat=52.0,
        target_lon=4.0014,
        radius_meters=200,
        route_type="2",
    )

    with zipfile.ZipFile(output_path) as zip_file:
        trips = zip_file.read("trips.txt").decode("utf-8")
        assert "trip-1" in trips
        assert "trip-bus" not in trips

    output = capsys.readouterr().out
    assert "routes=1" in output
    assert "trips=1" in output


def test_ensure_source_gtfs_zip_returns_existing_path(tmp_path: Path) -> None:
    input_path = tmp_path / "source.zip"
    write_source_gtfs_zip(input_path)

    assert ensure_source_gtfs_zip(input_path) == input_path


def test_build_minimal_gtfs_zip_downloads_missing_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    input_path = tmp_path / "gtfs-nl.zip"
    output_path = tmp_path / "minimal.zip"
    calls: list[Path] = []

    def fake_ensure_source_gtfs_zip(path: Path) -> Path:
        calls.append(path)
        write_source_gtfs_zip(path)
        return path

    monkeypatch.setattr(script, "ensure_source_gtfs_zip", fake_ensure_source_gtfs_zip)

    build_minimal_gtfs_zip(
        input_path=input_path,
        output_path=output_path,
        target_lat=52.0,
        target_lon=4.0014,
        radius_meters=200,
        route_type="2",
    )

    assert calls == [input_path]
    assert output_path.exists()
    output = capsys.readouterr().out
    assert "Reading source GTFS zip" in output


def test_minifier_main_calls_builder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr(
        script,
        "parse_args",
        lambda: argparse.Namespace(
            input=tmp_path / "in.zip",
            output=tmp_path / "out.zip",
            lat=52.0,
            lon=4.0,
            radius_meters=200.0,
            route_type="2",
        ),
    )
    monkeypatch.setattr(
        script,
        "build_minimal_gtfs_zip",
        lambda input_path, output_path, target_lat, target_lon, radius_meters, route_type: calls.append(
            (input_path, output_path, target_lat, target_lon, radius_meters, route_type)
        ),
    )

    assert script.main() == 0
    assert calls == [(tmp_path / "in.zip", tmp_path / "out.zip", 52.0, 4.0, 200.0, "2")]
