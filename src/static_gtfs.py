from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2
from tqdm import tqdm

from config import AppConfig
from geo import haversine_m


@dataclass(frozen=True)
class RouteInfo:
    route_id: str
    agency_id: str
    route_short_name: str
    route_long_name: str
    route_desc: str
    route_type: str


@dataclass(frozen=True)
class TripInfo:
    trip_id: str
    route_id: str
    trip_headsign: str
    trip_short_name: str
    direction_id: str
    shape_id: str


@dataclass(frozen=True)
class StopInfo:
    stop_id: str
    stop_name: str


@dataclass(frozen=True)
class TripEndpoints:
    origin_stop_id: str
    destination_stop_id: str


@dataclass(frozen=True)
class StopTimeInfo:
    stop_sequence: int
    stop_id: str
    shape_dist_traveled: float


@dataclass(frozen=True)
class TargetWindow:
    distance_to_target_m: float
    target_shape_dist: float
    trip_total_shape_dist: float
    previous_stop_sequence: int
    previous_stop_id: str
    previous_stop_name: str
    previous_stop_shape_dist: float
    next_stop_sequence: int
    next_stop_id: str
    next_stop_name: str
    next_stop_shape_dist: float

    def trip_progress_ratio(self) -> float | None:
        """Return target progress through the trip shape as a 0..1 ratio."""
        if self.trip_total_shape_dist <= 0:
            return None

        return min(max(self.target_shape_dist / self.trip_total_shape_dist, 0.0), 1.0)

    def estimate_target_time(self, previous_time: int, next_time: int) -> int:
        """Interpolate the target passage time between the surrounding stop timestamps."""
        distance_span = self.next_stop_shape_dist - self.previous_stop_shape_dist
        if distance_span <= 0:
            return previous_time

        # Local distance from the previous stop to the target point along the trip shape.
        # This is not the remaining distance to the final destination.
        target_offset = self.target_shape_dist - self.previous_stop_shape_dist
        interpolation_ratio = min(max(target_offset / distance_span, 0.0), 1.0)
        estimated_time = previous_time + ((next_time - previous_time) * interpolation_ratio)
        return round(estimated_time)


@dataclass(frozen=True)
class StaticGtfsData:
    routes: dict[str, RouteInfo]
    trips: dict[str, TripInfo]
    stops: dict[str, StopInfo]
    endpoints: dict[str, TripEndpoints]
    target_windows: dict[str, TargetWindow]

    def summarize_target_stop_pairs(self) -> list[str]:
        """Return the unique scheduled stop pairs that bracket the target across all trips."""
        stop_pairs = {
            f"{window.previous_stop_name} -> {window.next_stop_name}" for window in self.target_windows.values()
        }
        return sorted(stop_pairs)


@dataclass(frozen=True)
class StaticGtfsRows:
    routes: list[dict[str, str]]
    trips: list[dict[str, str]]
    stops: list[dict[str, str]]
    stop_times: list[dict[str, str]]
    shapes: list[dict[str, str]]


@dataclass(frozen=True)
class VehicleDetails:
    direction_id: str
    train_type: str
    train_company: str
    origin: str
    destination: str
    previous_stop: str
    next_stop: str
    headsign: str
    agency: str


def load_csv_from_zip(zf: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with zf.open(name) as csv_file:
        text_stream = io.TextIOWrapper(csv_file, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text_stream))


def load_static_gtfs(
    session: requests.Session,
    config: AppConfig,
) -> StaticGtfsData:
    zip_path = ensure_static_gtfs_zip(session, config)
    gtfs_rows = read_static_gtfs_rows(zip_path)
    return build_static_gtfs_data(gtfs_rows, config)


def read_static_gtfs_rows(zip_path: Path) -> StaticGtfsRows:
    with zipfile.ZipFile(zip_path) as zip_file:
        return StaticGtfsRows(
            routes=load_csv_from_zip(zip_file, "routes.txt"),
            trips=load_csv_from_zip(zip_file, "trips.txt"),
            stops=load_csv_from_zip(zip_file, "stops.txt"),
            stop_times=load_csv_from_zip(zip_file, "stop_times.txt"),
            shapes=load_csv_from_zip(zip_file, "shapes.txt"),
        )


def build_static_gtfs_data(
    gtfs_rows: StaticGtfsRows,
    config: AppConfig,
) -> StaticGtfsData:
    routes: dict[str, RouteInfo] = {}
    for row in gtfs_rows.routes:
        route_id = row.get("route_id")
        if not route_id:
            continue

        route_type = row.get("route_type", "")
        if route_type != "2":
            continue

        routes[route_id] = RouteInfo(
            route_id=route_id,
            agency_id=row.get("agency_id", ""),
            route_short_name=row.get("route_short_name", ""),
            route_long_name=row.get("route_long_name", ""),
            route_desc=row.get("route_desc", ""),
            route_type=route_type,
        )

    trips: dict[str, TripInfo] = {}
    for row in gtfs_rows.trips:
        trip_id = row.get("trip_id")
        route_id = row.get("route_id")
        if not trip_id or not route_id or route_id not in routes:
            continue

        trips[trip_id] = TripInfo(
            trip_id=trip_id,
            route_id=route_id,
            trip_headsign=row.get("trip_headsign", ""),
            trip_short_name=row.get("trip_short_name", ""),
            direction_id=row.get("direction_id", ""),
            shape_id=row.get("shape_id", ""),
        )

    stops = {
        stop_id: StopInfo(
            stop_id=stop_id,
            stop_name=row.get("stop_name", stop_id),
        )
        for row in gtfs_rows.stops
        if (stop_id := row.get("stop_id"))
    }

    stop_times: dict[str, list[StopTimeInfo]] = {}
    for row in gtfs_rows.stop_times:
        trip_id = row.get("trip_id")
        stop_id = row.get("stop_id")
        if not trip_id or not stop_id or trip_id not in trips:
            continue

        try:
            stop_sequence = int(row["stop_sequence"])
            shape_dist_traveled = float(row["shape_dist_traveled"])
        except (KeyError, ValueError):
            continue

        stop_times.setdefault(trip_id, []).append(
            StopTimeInfo(
                stop_sequence=stop_sequence,
                stop_id=stop_id,
                shape_dist_traveled=shape_dist_traveled,
            )
        )

    for trip_stop_times in stop_times.values():
        trip_stop_times.sort(key=lambda item: item.stop_sequence)

    endpoints = {
        trip_id: TripEndpoints(
            origin_stop_id=items[0].stop_id,
            destination_stop_id=items[-1].stop_id,
        )
        for trip_id, items in stop_times.items()
    }

    shapes = load_shapes(gtfs_rows.shapes)
    shape_targets = build_shape_targets(config, shapes)
    target_windows = build_target_windows(
        config=config,
        trips=trips,
        stops=stops,
        stop_times=stop_times,
        shape_targets=shape_targets,
    )

    return StaticGtfsData(
        routes=routes,
        trips=trips,
        stops=stops,
        endpoints=endpoints,
        target_windows=target_windows,
    )


def infer_train_type(route: RouteInfo | None, trip: TripInfo | None) -> str:
    if route is None:
        return "unknown"

    fields = " | ".join(
        value
        for value in (
            route.route_short_name,
            route.route_long_name,
            route.route_desc,
            trip.trip_short_name if trip else "",
        )
        if value
    ).lower()

    for label in (
        "intercity direct",
        "intercity",
        "sprinter",
        "sneltrein",
        "stoptrein",
        "ice",
        "eurostar",
    ):
        if label in fields:
            return label

    return route.route_long_name or route.route_short_name or "unknown"


def resolve_vehicle_details(
    entity: gtfs_realtime_pb2.FeedEntity,
    static_gtfs: StaticGtfsData,
    feed_timestamp: int,
) -> VehicleDetails:
    """Resolve the structured vehicle details used by the monitor presentation layer."""
    trip_id, trip, route = resolve_trip_context(entity.trip_update, static_gtfs)
    endpoints = static_gtfs.endpoints.get(trip_id)
    origin = resolve_stop_name(static_gtfs.stops, endpoints.origin_stop_id) if endpoints else "?"
    destination = resolve_stop_name(static_gtfs.stops, endpoints.destination_stop_id) if endpoints else "?"
    previous_stop = resolve_previous_stop_name(entity.trip_update, static_gtfs.stops, feed_timestamp) or origin
    next_stop = resolve_next_stop_name(entity.trip_update, static_gtfs.stops, feed_timestamp) or destination
    headsign = trip.trip_headsign if trip and trip.trip_headsign else destination
    direction_id = resolve_direction_id(entity.trip_update, trip)
    train_type = infer_train_type(route, trip)
    agency = normalize_agency(route.agency_id if route else "")

    return VehicleDetails(
        direction_id=direction_id,
        train_type=train_type,
        train_company=infer_train_company(agency, train_type),
        origin=origin,
        destination=destination,
        previous_stop=previous_stop,
        next_stop=next_stop,
        headsign=headsign,
        agency=agency,
    )


def is_train_vehicle(
    entity: gtfs_realtime_pb2.FeedEntity,
    static_gtfs: StaticGtfsData,
) -> bool:
    if not entity.HasField("trip_update"):
        return False

    _, _, route = resolve_trip_context(entity.trip_update, static_gtfs)
    return route is not None and route.route_type == "2"


def build_target_windows(
    config: AppConfig,
    trips: dict[str, TripInfo],
    stops: dict[str, StopInfo],
    stop_times: dict[str, list[StopTimeInfo]],
    shape_targets: dict[str, tuple[float, float]],
) -> dict[str, TargetWindow]:
    target_windows: dict[str, TargetWindow] = {}

    for trip_id, trip in trips.items():
        trip_stop_times = stop_times.get(trip_id)
        shape_target = shape_targets.get(trip.shape_id)
        if trip_stop_times is None or shape_target is None:
            continue

        distance_to_target_m, target_shape_dist = shape_target
        if distance_to_target_m > config.radius_meters:
            continue

        previous_stop, next_stop = find_bracketing_stops(trip_stop_times, target_shape_dist)
        if previous_stop is None or next_stop is None:
            continue

        target_windows[trip_id] = TargetWindow(
            distance_to_target_m=distance_to_target_m,
            target_shape_dist=target_shape_dist,
            trip_total_shape_dist=trip_stop_times[-1].shape_dist_traveled,
            previous_stop_sequence=previous_stop.stop_sequence,
            previous_stop_id=previous_stop.stop_id,
            previous_stop_name=resolve_stop_name(stops, previous_stop.stop_id),
            previous_stop_shape_dist=previous_stop.shape_dist_traveled,
            next_stop_sequence=next_stop.stop_sequence,
            next_stop_id=next_stop.stop_id,
            next_stop_name=resolve_stop_name(stops, next_stop.stop_id),
            next_stop_shape_dist=next_stop.shape_dist_traveled,
        )

    return target_windows


def load_shapes(shape_rows: list[dict[str, str]]) -> dict[str, list[tuple[float, float, float]]]:
    shapes: dict[str, list[tuple[float, float, float]]] = {}

    for row in shape_rows:
        shape_id = row.get("shape_id")
        if not shape_id:
            continue

        try:
            shape_dist = float(row["shape_dist_traveled"])
            lat = float(row["shape_pt_lat"])
            lon = float(row["shape_pt_lon"])
        except (KeyError, ValueError):
            continue

        shapes.setdefault(shape_id, []).append((shape_dist, lat, lon))

    for points in shapes.values():
        points.sort(key=lambda item: item[0])

    return shapes


def build_shape_targets(
    config: AppConfig,
    shapes: dict[str, list[tuple[float, float, float]]],
) -> dict[str, tuple[float, float]]:
    shape_targets: dict[str, tuple[float, float]] = {}

    for shape_id, points in shapes.items():
        nearest_distance = float("inf")
        nearest_shape_dist = 0.0

        for shape_dist, lat, lon in points:
            distance = haversine_m(config.target_lat, config.target_lon, lat, lon)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_shape_dist = shape_dist

        shape_targets[shape_id] = (nearest_distance, nearest_shape_dist)

    return shape_targets


def find_bracketing_stops(
    trip_stop_times: list[StopTimeInfo],
    target_shape_dist: float,
) -> tuple[StopTimeInfo | None, StopTimeInfo | None]:
    previous_stop: StopTimeInfo | None = None
    next_stop: StopTimeInfo | None = None

    for stop_time in trip_stop_times:
        if stop_time.shape_dist_traveled <= target_shape_dist:
            previous_stop = stop_time
        if stop_time.shape_dist_traveled >= target_shape_dist:
            next_stop = stop_time
            break

    return previous_stop, next_stop


def resolve_direction_id(
    trip_update: gtfs_realtime_pb2.TripUpdate,
    trip: TripInfo | None,
) -> str:
    if trip_update.trip.HasField("direction_id"):
        return str(trip_update.trip.direction_id)
    if trip and trip.direction_id:
        return trip.direction_id
    return "?"


def resolve_stop_name(stops: dict[str, StopInfo], stop_id: str) -> str:
    stop = stops.get(stop_id)
    return stop.stop_name if stop else "?"


def normalize_agency(agency_id: str) -> str:
    """Normalize agency identifiers such as IFF:NS into a display-friendly agency code."""
    if not agency_id:
        return "?"
    if ":" in agency_id:
        return agency_id.split(":")[-1]
    return agency_id


def infer_train_company(
    agency: str,
    train_type: str,
) -> str:
    """Infer a train-company label from the GTFS agency, with an NS_INT to ICE special case."""
    normalized_train_type = train_type.lower()

    if agency == "NS_INT" and normalized_train_type == "ice":
        return "ICE"
    if agency in {"NS", "NS_INT"} and normalized_train_type in {
        "sprinter",
        "intercity",
        "intercity direct",
    }:
        return "NS"
    return agency


def resolve_next_stop_name(
    trip_update: gtfs_realtime_pb2.TripUpdate,
    stops: dict[str, StopInfo],
    feed_timestamp: int,
) -> str | None:
    """Return the next upcoming stop name from realtime stop updates, if one can be resolved."""
    for stop_time_update in trip_update.stop_time_update:
        event_time = resolve_stop_time_update_time(stop_time_update)
        if event_time is None or event_time < feed_timestamp:
            continue

        stop_id = stop_time_update.stop_id
        if stop_id:
            return resolve_stop_name(stops, stop_id)

    return None


def resolve_previous_stop_name(
    trip_update: gtfs_realtime_pb2.TripUpdate,
    stops: dict[str, StopInfo],
    feed_timestamp: int,
) -> str | None:
    """Return the most recent stop name from realtime stop updates, if one can be resolved."""
    previous_stop_name: str | None = None

    for stop_time_update in trip_update.stop_time_update:
        event_time = resolve_stop_time_update_time(stop_time_update)
        if event_time is None or event_time > feed_timestamp:
            continue

        stop_id = stop_time_update.stop_id
        if stop_id:
            previous_stop_name = resolve_stop_name(stops, stop_id)

    return previous_stop_name


def resolve_stop_time_update_time(
    stop_time_update: gtfs_realtime_pb2.TripUpdate.StopTimeUpdate,
) -> int | None:
    """Extract the most useful absolute time from a stop update for next-stop selection."""
    if stop_time_update.arrival.HasField("time"):
        return stop_time_update.arrival.time
    if stop_time_update.departure.HasField("time"):
        return stop_time_update.departure.time
    return None


def resolve_trip_context(
    trip_update: gtfs_realtime_pb2.TripUpdate,
    static_gtfs: StaticGtfsData,
) -> tuple[str, TripInfo | None, RouteInfo | None]:
    trip_id = trip_update.trip.trip_id if trip_update.trip.trip_id else ""
    route_id = trip_update.trip.route_id if trip_update.trip.route_id else ""

    trip = static_gtfs.trips.get(trip_id)
    resolved_route_id = trip.route_id if trip is not None else route_id
    route = static_gtfs.routes.get(resolved_route_id)
    return trip_id, trip, route


def ensure_static_gtfs_zip(
    session: requests.Session,
    config: AppConfig,
) -> Path:
    zip_path = config.static_gtfs_cache_path
    if zip_path.exists():
        return zip_path

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = zip_path.with_suffix(f"{zip_path.suffix}.part")

    try:
        with session.get(
            config.static_gtfs_url,
            headers={"User-Agent": config.user_agent},
            timeout=120,
            stream=True,
        ) as response:
            response.raise_for_status()
            total_bytes = get_content_length(response)

            with (
                temp_path.open("wb") as zip_file,
                tqdm(
                    total=total_bytes,
                    desc="Downloading GTFS",
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                ) as progress,
            ):
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue

                    zip_file.write(chunk)
                    progress.update(len(chunk))
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    temp_path.replace(zip_path)
    return zip_path


def get_content_length(response: requests.Response) -> int | None:
    content_length = response.headers.get("Content-Length")
    if content_length is None:
        return None

    try:
        return int(content_length)
    except ValueError:
        return None
