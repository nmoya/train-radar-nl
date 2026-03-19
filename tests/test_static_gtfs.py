from __future__ import annotations

import io
import zipfile

import pytest
import requests
from google.transit import gtfs_realtime_pb2

import src.static_gtfs as static_gtfs
from src.static_gtfs import (
    StaticGtfsRows,
    StopTimeInfo,
    TargetWindow,
    build_shape_targets,
    build_static_gtfs_data,
    build_target_windows,
    ensure_static_gtfs_zip,
    find_bracketing_stops,
    get_content_length,
    infer_train_company,
    infer_train_type,
    is_train_vehicle,
    load_shapes,
    normalize_agency,
    read_static_gtfs_rows,
    resolve_direction_id,
    resolve_next_stop_name,
    resolve_previous_stop_name,
    resolve_stop_name,
    resolve_stop_time_update_time,
    resolve_trip_context,
    resolve_vehicle_details,
)

from .support import (
    make_config,
    make_entity,
    make_static_gtfs_data,
    make_static_gtfs_rows,
    make_stop_time_update,
    make_target_window,
)


def test_target_window_progress_and_time_estimation(sample_target_window: TargetWindow) -> None:
    assert sample_target_window.trip_progress_ratio() == 0.5
    assert sample_target_window.estimate_target_time(100, 200) == 150
    assert make_target_window(
        next_stop_shape_dist=100.0,
        previous_stop_shape_dist=100.0,
    ).estimate_target_time(100, 200) == 100


def test_read_static_gtfs_rows_reads_required_files(tmp_path) -> None:
    zip_path = tmp_path / "mini.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.writestr("routes.txt", "route_id,route_type\nroute-1,2\n")
        zip_file.writestr("trips.txt", "trip_id,route_id,shape_id\ntrip-1,route-1,shape-1\n")
        zip_file.writestr("stops.txt", "stop_id,stop_name\nstop-a,Alpha\n")
        zip_file.writestr(
            "stop_times.txt",
            "trip_id,stop_sequence,stop_id,shape_dist_traveled\ntrip-1,1,stop-a,0\n",
        )
        zip_file.writestr(
            "shapes.txt",
            "shape_id,shape_pt_lat,shape_pt_lon,shape_dist_traveled\nshape-1,52,4,0\n",
        )

    rows = read_static_gtfs_rows(zip_path)

    assert rows.routes[0]["route_id"] == "route-1"
    assert rows.trips[0]["shape_id"] == "shape-1"


def test_build_static_gtfs_data_filters_non_rail_and_builds_windows(app_config) -> None:
    rows = make_static_gtfs_rows()
    data = build_static_gtfs_data(rows, app_config)

    assert list(data.routes) == ["route-1"]
    assert set(data.trips) == {"trip-1", "trip-2"}
    assert data.endpoints["trip-1"].origin_stop_id == "stop-a"
    assert data.target_windows["trip-1"].previous_stop_name == "Beta"
    assert data.summarize_target_stop_pairs() == ["Beta -> Alpha", "Beta -> Gamma"]


def test_shape_and_stop_helpers(app_config) -> None:
    shapes = load_shapes(
        [
            {
                "shape_id": "shape-1",
                "shape_pt_lat": "52.0",
                "shape_pt_lon": "4.001",
                "shape_dist_traveled": "100",
            },
            {
                "shape_id": "shape-1",
                "shape_pt_lat": "52.0",
                "shape_pt_lon": "4.000",
                "shape_dist_traveled": "0",
            },
        ]
    )
    targets = build_shape_targets(app_config, shapes)
    previous_stop, next_stop = find_bracketing_stops(
        [
            StopTimeInfo(1, "a", 0.0),
            StopTimeInfo(2, "b", 100.0),
            StopTimeInfo(3, "c", 200.0),
        ],
        150.0,
    )

    assert shapes["shape-1"][0][0] == 0.0
    assert targets["shape-1"][1] == 100.0
    assert previous_stop.stop_id == "b"
    assert next_stop.stop_id == "c"


def test_build_target_windows_skips_out_of_radius_or_missing_brackets(app_config) -> None:
    target_windows = build_target_windows(
        config=make_config(app_config.static_gtfs_cache_path, radius_meters=50),
        trips=make_static_gtfs_data().trips,
        stops=make_static_gtfs_data().stops,
        stop_times={
            "trip-1": [
                StopTimeInfo(1, "stop-a", 0.0),
                StopTimeInfo(2, "stop-b", 100.0),
                StopTimeInfo(3, "stop-c", 200.0),
            ]
        },
        shape_targets={"shape-1": (100.0, 150.0)},
    )

    assert target_windows == {}


def test_trip_and_stop_resolution_helpers(sample_static_gtfs_data) -> None:
    entity = make_entity(
        stop_time_updates=[
            make_stop_time_update(1, "stop-a", departure=90),
            make_stop_time_update(2, "stop-b", departure=100),
            make_stop_time_update(3, "stop-c", arrival=200),
        ]
    )
    trip_id, trip, route = resolve_trip_context(entity.trip_update, sample_static_gtfs_data)

    assert trip_id == "trip-1"
    assert trip.trip_id == "trip-1"
    assert route.route_id == "route-1"
    assert resolve_direction_id(entity.trip_update, trip) == "0"
    assert resolve_stop_name(sample_static_gtfs_data.stops, "stop-b") == "Beta"
    assert resolve_stop_time_update_time(entity.trip_update.stop_time_update[0]) == 90
    assert resolve_previous_stop_name(entity.trip_update, sample_static_gtfs_data.stops, 150) == "Beta"
    assert resolve_next_stop_name(entity.trip_update, sample_static_gtfs_data.stops, 150) == "Gamma"
    assert is_train_vehicle(entity, sample_static_gtfs_data) is True


def test_resolve_vehicle_details_and_train_labels(sample_static_gtfs_data) -> None:
    entity = make_entity(
        stop_time_updates=[
            make_stop_time_update(1, "stop-a", departure=90),
            make_stop_time_update(2, "stop-b", departure=100),
            make_stop_time_update(3, "stop-c", arrival=200),
        ]
    )
    details = resolve_vehicle_details(entity, sample_static_gtfs_data, 150)

    assert details.origin == "Alpha"
    assert details.destination == "Gamma"
    assert details.previous_stop == "Beta"
    assert details.next_stop == "Gamma"
    assert details.train_type == "intercity"
    assert details.train_company == "NS"
    assert normalize_agency("IFF:NS") == "NS"
    assert infer_train_company("NS_INT", "ICE") == "ICE"
    assert infer_train_type(sample_static_gtfs_data.routes["route-1"], sample_static_gtfs_data.trips["trip-1"]) == "intercity"


def test_is_train_vehicle_false_when_trip_context_is_missing(sample_static_gtfs_data) -> None:
    entity = gtfs_realtime_pb2.FeedEntity()
    entity.id = "plain"

    assert is_train_vehicle(entity, sample_static_gtfs_data) is False


def test_ensure_static_gtfs_zip_reuses_existing_file(app_config, tmp_path) -> None:
    existing_path = tmp_path / "existing.zip"
    existing_path.write_bytes(b"data")
    config = make_config(existing_path)

    assert ensure_static_gtfs_zip(object(), config) == existing_path


def test_ensure_static_gtfs_zip_downloads_and_cleans_up_on_failure(tmp_path) -> None:
    target_path = tmp_path / "download.zip"
    config = make_config(target_path)

    class Response:
        headers = {"Content-Length": "4"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"ab"
            yield b"cd"

    class Session:
        def get(self, url, headers, timeout, stream):
            assert headers["User-Agent"] == config.user_agent
            assert timeout == 120
            assert stream is True
            return Response()

    assert ensure_static_gtfs_zip(Session(), config).read_bytes() == b"abcd"

    class FailingResponse(Response):
        def iter_content(self, chunk_size):
            raise requests.RequestException("network")

    class FailingSession(Session):
        def get(self, url, headers, timeout, stream):
            return FailingResponse()

    broken_path = tmp_path / "broken.zip"
    broken_config = make_config(broken_path)
    with pytest.raises(requests.RequestException, match="network"):
        ensure_static_gtfs_zip(FailingSession(), broken_config)
    assert not broken_path.with_suffix(".zip.part").exists()


def test_get_content_length_parses_valid_values() -> None:
    class Response:
        def __init__(self, header):
            self.headers = {"Content-Length": header} if header is not None else {}

    assert get_content_length(Response("12")) == 12
    assert get_content_length(Response("bad")) is None
    assert get_content_length(Response(None)) is None
