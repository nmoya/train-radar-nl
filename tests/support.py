from __future__ import annotations

from pathlib import Path

from google.transit import gtfs_realtime_pb2

from src.config import AppConfig
from src.feed import FeedUpdate
from src.monitor_models import MonitorSnapshot, TrainStatus
from src.static_gtfs import (
    RouteInfo,
    StaticGtfsData,
    StaticGtfsRows,
    StopInfo,
    TargetWindow,
    TripEndpoints,
    TripInfo,
    VehicleDetails,
)


def make_config(cache_path: Path, **overrides: object) -> AppConfig:
    values: dict[str, object] = {
        "feed_url": "https://example.test/feed.pb",
        "static_gtfs_url": "https://example.test/gtfs.zip",
        "runtime_static_gtfs_url": None,
        "static_gtfs_cache_path": cache_path,
        "runtime_static_gtfs_refresh_interval_minutes": 1440,
        "target_lat": 52.0,
        "target_lon": 4.0014,
        "radius_meters": 200,
        "poll_interval_seconds": 30,
        "target_passage_tolerance_ceiling_seconds": 60,
        "target_passage_tolerance_factor": 0.1,
        "target_passage_sparse_update_tolerance_factor": 0.5,
        "timezone_name": "Europe/Amsterdam",
        "user_agent": "train-radar-nl-tests",
        "startup_time": 1_700_000_000,
    }
    values.update(overrides)
    return AppConfig(**values)


def make_target_window(**overrides: object) -> TargetWindow:
    values: dict[str, object] = {
        "distance_to_target_m": 42.5,
        "target_shape_dist": 150.0,
        "trip_total_shape_dist": 300.0,
        "trip_total_path_m": 300.0,
        "previous_stop_sequence": 2,
        "previous_stop_id": "stop-b",
        "previous_stop_name": "Beta",
        "previous_stop_shape_dist": 100.0,
        "previous_stop_path_m": 100.0,
        "next_stop_sequence": 3,
        "next_stop_id": "stop-c",
        "next_stop_name": "Gamma",
        "next_stop_shape_dist": 200.0,
        "next_stop_path_m": 200.0,
        "target_path_m": 150.0,
    }
    values.update(overrides)
    return TargetWindow(**values)


def make_vehicle_details(**overrides: object) -> VehicleDetails:
    values: dict[str, object] = {
        "direction_id": "0",
        "train_type": "intercity",
        "train_company": "NS",
        "origin": "Alpha",
        "destination": "Gamma",
        "previous_stop": "Beta",
        "next_stop": "Gamma",
        "headsign": "Gamma",
        "agency": "NS",
    }
    values.update(overrides)
    return VehicleDetails(**values)


def make_train_status(**overrides: object) -> TrainStatus:
    values: dict[str, object] = {
        "entity_key": "trip-1",
        "direction_id": "0",
        "vehicle_details": make_vehicle_details(),
        "target_window": make_target_window(),
        "previous_stop_time": 1_700_000_050,
        "estimated_target_time": 1_700_000_100,
        "next_stop_time": 1_700_000_150,
        "range_start_time": 1_700_000_050,
        "range_end_time": 1_700_000_160,
    }
    values.update(overrides)
    return TrainStatus(**values)


def make_snapshot(**overrides: object) -> MonitorSnapshot:
    values: dict[str, object] = {
        "feed_timestamp": 1_700_000_000,
        "left_trains": [],
        "right_trains": [],
    }
    values.update(overrides)
    return MonitorSnapshot(**values)


def make_static_gtfs_data() -> StaticGtfsData:
    target_window_left = make_target_window()
    target_window_right = make_target_window(
        previous_stop_id="stop-c",
        previous_stop_name="Gamma",
        previous_stop_shape_dist=100.0,
        previous_stop_path_m=100.0,
        next_stop_id="stop-b",
        next_stop_name="Beta",
        next_stop_shape_dist=200.0,
        next_stop_path_m=200.0,
        target_path_m=150.0,
    )
    return StaticGtfsData(
        routes={
            "route-1": RouteInfo(
                route_id="route-1",
                agency_id="IFF:NS",
                route_short_name="IC",
                route_long_name="Intercity",
                route_desc="Amsterdam to Utrecht",
                route_type="2",
            ),
        },
        trips={
            "trip-1": TripInfo(
                trip_id="trip-1",
                route_id="route-1",
                trip_headsign="Gamma",
                trip_short_name="Intercity 123",
                direction_id="0",
                shape_id="shape-1",
            ),
            "trip-2": TripInfo(
                trip_id="trip-2",
                route_id="route-1",
                trip_headsign="Alpha",
                trip_short_name="Intercity 456",
                direction_id="1",
                shape_id="shape-2",
            ),
        },
        stops={
            "stop-a": StopInfo(stop_id="stop-a", stop_name="Alpha"),
            "stop-b": StopInfo(stop_id="stop-b", stop_name="Beta"),
            "stop-c": StopInfo(stop_id="stop-c", stop_name="Gamma"),
        },
        endpoints={
            "trip-1": TripEndpoints(origin_stop_id="stop-a", destination_stop_id="stop-c"),
            "trip-2": TripEndpoints(origin_stop_id="stop-c", destination_stop_id="stop-a"),
        },
        target_windows={
            "trip-1": target_window_left,
            "trip-2": target_window_right,
        },
    )


def make_static_gtfs_rows() -> StaticGtfsRows:
    return StaticGtfsRows(
        routes=[
            {
                "route_id": "route-1",
                "agency_id": "IFF:NS",
                "route_short_name": "IC",
                "route_long_name": "Intercity",
                "route_desc": "Amsterdam to Utrecht",
                "route_type": "2",
            },
            {
                "route_id": "route-bus",
                "agency_id": "BUS",
                "route_short_name": "B",
                "route_long_name": "Bus",
                "route_desc": "",
                "route_type": "3",
            },
        ],
        trips=[
            {
                "trip_id": "trip-1",
                "route_id": "route-1",
                "trip_headsign": "Gamma",
                "trip_short_name": "Intercity 123",
                "direction_id": "0",
                "shape_id": "shape-1",
            },
            {
                "trip_id": "trip-2",
                "route_id": "route-1",
                "trip_headsign": "Alpha",
                "trip_short_name": "Intercity 456",
                "direction_id": "1",
                "shape_id": "shape-2",
            },
            {
                "trip_id": "trip-bus",
                "route_id": "route-bus",
                "trip_headsign": "Nowhere",
                "trip_short_name": "Bus 9",
                "direction_id": "0",
                "shape_id": "shape-bus",
            },
        ],
        stops=[
            {"stop_id": "stop-a", "stop_name": "Alpha"},
            {"stop_id": "stop-b", "stop_name": "Beta"},
            {"stop_id": "stop-c", "stop_name": "Gamma"},
        ],
        stop_times=[
            {
                "trip_id": "trip-1",
                "stop_sequence": "1",
                "stop_id": "stop-a",
                "shape_dist_traveled": "0",
            },
            {
                "trip_id": "trip-1",
                "stop_sequence": "2",
                "stop_id": "stop-b",
                "shape_dist_traveled": "100",
            },
            {
                "trip_id": "trip-1",
                "stop_sequence": "3",
                "stop_id": "stop-c",
                "shape_dist_traveled": "200",
            },
            {
                "trip_id": "trip-2",
                "stop_sequence": "1",
                "stop_id": "stop-c",
                "shape_dist_traveled": "0",
            },
            {
                "trip_id": "trip-2",
                "stop_sequence": "2",
                "stop_id": "stop-b",
                "shape_dist_traveled": "100",
            },
            {
                "trip_id": "trip-2",
                "stop_sequence": "3",
                "stop_id": "stop-a",
                "shape_dist_traveled": "200",
            },
        ],
        shapes=[
            {
                "shape_id": "shape-1",
                "shape_pt_lat": "52.0000",
                "shape_pt_lon": "4.0000",
                "shape_dist_traveled": "0",
            },
            {
                "shape_id": "shape-1",
                "shape_pt_lat": "52.0000",
                "shape_pt_lon": "4.0010",
                "shape_dist_traveled": "100",
            },
            {
                "shape_id": "shape-1",
                "shape_pt_lat": "52.0000",
                "shape_pt_lon": "4.0014",
                "shape_dist_traveled": "150",
            },
            {
                "shape_id": "shape-1",
                "shape_pt_lat": "52.0000",
                "shape_pt_lon": "4.0020",
                "shape_dist_traveled": "200",
            },
            {
                "shape_id": "shape-2",
                "shape_pt_lat": "52.0000",
                "shape_pt_lon": "4.0020",
                "shape_dist_traveled": "0",
            },
            {
                "shape_id": "shape-2",
                "shape_pt_lat": "52.0000",
                "shape_pt_lon": "4.0010",
                "shape_dist_traveled": "100",
            },
            {
                "shape_id": "shape-2",
                "shape_pt_lat": "52.0000",
                "shape_pt_lon": "4.0014",
                "shape_dist_traveled": "150",
            },
            {
                "shape_id": "shape-2",
                "shape_pt_lat": "52.0000",
                "shape_pt_lon": "4.0000",
                "shape_dist_traveled": "200",
            },
        ],
    )


def make_stop_time_update(
    stop_sequence: int,
    stop_id: str,
    *,
    arrival: int | None = None,
    departure: int | None = None,
) -> gtfs_realtime_pb2.TripUpdate.StopTimeUpdate:
    update = gtfs_realtime_pb2.TripUpdate.StopTimeUpdate()
    update.stop_sequence = stop_sequence
    update.stop_id = stop_id
    if arrival is not None:
        update.arrival.time = arrival
    if departure is not None:
        update.departure.time = departure
    return update


def make_trip_update(
    *,
    trip_id: str = "trip-1",
    route_id: str = "route-1",
    direction_id: int | None = None,
    timestamp: int = 0,
    stop_time_updates: list[gtfs_realtime_pb2.TripUpdate.StopTimeUpdate] | None = None,
) -> gtfs_realtime_pb2.TripUpdate:
    trip_update = gtfs_realtime_pb2.TripUpdate()
    trip_update.trip.trip_id = trip_id
    trip_update.trip.route_id = route_id
    if direction_id is not None:
        trip_update.trip.direction_id = direction_id
    if timestamp:
        trip_update.timestamp = timestamp
    for stop_time_update in stop_time_updates or []:
        trip_update.stop_time_update.add().CopyFrom(stop_time_update)
    return trip_update


def make_entity(
    *,
    entity_id: str = "entity-1",
    trip_id: str = "trip-1",
    route_id: str = "route-1",
    direction_id: int | None = None,
    timestamp: int = 0,
    stop_time_updates: list[gtfs_realtime_pb2.TripUpdate.StopTimeUpdate] | None = None,
) -> gtfs_realtime_pb2.FeedEntity:
    entity = gtfs_realtime_pb2.FeedEntity()
    entity.id = entity_id
    entity.trip_update.CopyFrom(
        make_trip_update(
            trip_id=trip_id,
            route_id=route_id,
            direction_id=direction_id,
            timestamp=timestamp,
            stop_time_updates=stop_time_updates,
        )
    )
    return entity


def make_feed(
    *,
    timestamp: int = 1_700_000_000,
    entities: list[gtfs_realtime_pb2.FeedEntity] | None = None,
) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = timestamp
    for entity in entities or []:
        feed.entity.add().CopyFrom(entity)
    return feed


def make_feed_update(
    *,
    feed: gtfs_realtime_pb2.FeedMessage | None = None,
    feed_timestamp: int = 1_700_000_000,
    next_poll_in_seconds: int = 0,
    version: int = 1,
    error: str | None = None,
) -> FeedUpdate:
    return FeedUpdate(
        feed=feed,
        feed_timestamp=feed_timestamp,
        next_poll_in_seconds=next_poll_in_seconds,
        version=version,
        error=error,
    )
