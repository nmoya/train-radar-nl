from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.config import DOTENV_PATH, TARGET_LAT, TARGET_LON, load_dotenv
    from src.geo import haversine_m
else:
    from ..config import DOTENV_PATH, TARGET_LAT, TARGET_LON, load_dotenv
    from ..geo import haversine_m

ROUTES_COLUMNS = (
    "route_id",
    "agency_id",
    "route_short_name",
    "route_long_name",
    "route_desc",
    "route_type",
)
TRIPS_COLUMNS = (
    "trip_id",
    "route_id",
    "trip_headsign",
    "trip_short_name",
    "direction_id",
    "shape_id",
)
STOPS_COLUMNS = (
    "stop_id",
    "stop_name",
)
STOP_TIMES_COLUMNS = (
    "trip_id",
    "stop_sequence",
    "stop_id",
    "shape_dist_traveled",
)
SHAPES_COLUMNS = (
    "shape_id",
    "shape_pt_lat",
    "shape_pt_lon",
    "shape_dist_traveled",
)


@dataclass(frozen=True)
class ShapePoint:
    shape_id: str
    shape_dist_traveled: float
    lat: float
    lon: float
    row: dict[str, str]


@dataclass(frozen=True)
class StopTimePoint:
    trip_id: str
    stop_sequence: int
    stop_id: str
    shape_dist_traveled: float
    row: dict[str, str]


def parse_args() -> argparse.Namespace:
    load_dotenv(DOTENV_PATH)

    parser = argparse.ArgumentParser(
        description=(
            "Build a reduced GTFS zip containing only the files, columns, and rows "
            "needed by the train-radar-nl runtime for a target lat/lon."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the source GTFS zip, for example .cache/gtfs-nl.zip",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to the reduced GTFS zip to create",
    )
    parser.add_argument(
        "--lat",
        type=float,
        help=f"Target latitude. Defaults to {TARGET_LAT} from .env if omitted.",
    )
    parser.add_argument(
        "--lon",
        type=float,
        help=f"Target longitude. Defaults to {TARGET_LON} from .env if omitted.",
    )
    parser.add_argument(
        "--radius-meters",
        type=float,
        required=True,
        help="Maximum allowed distance from target to a trip shape",
    )
    parser.add_argument(
        "--route-type",
        default="2",
        help="GTFS route_type to keep. Default: 2 (rail)",
    )
    args = parser.parse_args()

    if args.lat is None:
        raw_lat = os.environ.get(TARGET_LAT)
        if raw_lat is None or raw_lat.strip() == "":
            parser.error(f"--lat is required unless {TARGET_LAT} is set in .env or the environment.")
        try:
            args.lat = float(raw_lat)
        except ValueError as exc:
            raise ValueError(f"Environment variable {TARGET_LAT} must be a float, got {raw_lat!r}.") from exc

    if args.lon is None:
        raw_lon = os.environ.get(TARGET_LON)
        if raw_lon is None or raw_lon.strip() == "":
            parser.error(f"--lon is required unless {TARGET_LON} is set in .env or the environment.")
        try:
            args.lon = float(raw_lon)
        except ValueError as exc:
            raise ValueError(f"Environment variable {TARGET_LON} must be a float, got {raw_lon!r}.") from exc

    return args


def load_csv_rows(zip_file: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with zip_file.open(name) as csv_file:
        stream = io.TextIOWrapper(csv_file, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(stream))


def trim_row(row: dict[str, str], columns: tuple[str, ...]) -> dict[str, str]:
    return {column: row.get(column, "") for column in columns}


def build_minimal_gtfs_zip(
    input_path: Path,
    output_path: Path,
    target_lat: float,
    target_lon: float,
    radius_meters: float,
    route_type: str,
) -> None:
    print("Reading source GTFS zip and filtering for target location...")
    with zipfile.ZipFile(input_path) as source_zip:
        routes_rows = load_csv_rows(source_zip, "routes.txt")
        trips_rows = load_csv_rows(source_zip, "trips.txt")
        stop_times_rows = load_csv_rows(source_zip, "stop_times.txt")
        stops_rows = load_csv_rows(source_zip, "stops.txt")
        shapes_rows = load_csv_rows(source_zip, "shapes.txt")

    print("Done")
    routes = {
        row["route_id"]: trim_row(row, ROUTES_COLUMNS)
        for row in routes_rows
        if row.get("route_id") and row.get("route_type") == route_type
    }

    candidate_trips = {
        row["trip_id"]: trim_row(row, TRIPS_COLUMNS)
        for row in trips_rows
        if row.get("trip_id") and row.get("route_id") in routes and row.get("shape_id")
    }
    candidate_shape_ids = {row["shape_id"] for row in candidate_trips.values()}

    shapes_by_id: dict[str, list[ShapePoint]] = {}
    nearest_shape_targets: dict[str, tuple[float, float]] = {}
    for row in shapes_rows:
        shape_id = row.get("shape_id")
        if not shape_id or shape_id not in candidate_shape_ids:
            continue

        try:
            shape_dist_traveled = float(row["shape_dist_traveled"])
            lat = float(row["shape_pt_lat"])
            lon = float(row["shape_pt_lon"])
        except (KeyError, ValueError):
            continue

        point = ShapePoint(
            shape_id=shape_id,
            shape_dist_traveled=shape_dist_traveled,
            lat=lat,
            lon=lon,
            row=trim_row(row, SHAPES_COLUMNS),
        )
        shapes_by_id.setdefault(shape_id, []).append(point)

        distance_to_target = haversine_m(target_lat, target_lon, lat, lon)
        current_best = nearest_shape_targets.get(shape_id)
        if current_best is None or distance_to_target < current_best[0]:
            nearest_shape_targets[shape_id] = (
                distance_to_target,
                shape_dist_traveled,
            )

    for points in shapes_by_id.values():
        points.sort(key=lambda point: point.shape_dist_traveled)

    kept_shape_ids = {
        shape_id
        for shape_id, (distance_to_target, _) in nearest_shape_targets.items()
        if distance_to_target <= radius_meters
    }
    candidate_trips = {trip_id: trip for trip_id, trip in candidate_trips.items() if trip["shape_id"] in kept_shape_ids}

    stop_times_by_trip: dict[str, list[StopTimePoint]] = {}
    for row in stop_times_rows:
        trip_id = row.get("trip_id")
        if not trip_id or trip_id not in candidate_trips:
            continue

        try:
            stop_sequence = int(row["stop_sequence"])
            shape_dist_traveled = float(row["shape_dist_traveled"])
        except (KeyError, ValueError):
            continue

        stop_times_by_trip.setdefault(trip_id, []).append(
            StopTimePoint(
                trip_id=trip_id,
                stop_sequence=stop_sequence,
                stop_id=row.get("stop_id", ""),
                shape_dist_traveled=shape_dist_traveled,
                row=trim_row(row, STOP_TIMES_COLUMNS),
            )
        )

    for stop_times in stop_times_by_trip.values():
        stop_times.sort(key=lambda point: point.stop_sequence)

    valid_trip_ids: set[str] = set()
    for trip_id, trip in candidate_trips.items():
        target_info = nearest_shape_targets.get(trip["shape_id"])
        trip_stop_times = stop_times_by_trip.get(trip_id)
        if target_info is None or not trip_stop_times:
            continue

        _, target_shape_dist = target_info
        if has_bracketing_stops(trip_stop_times, target_shape_dist):
            valid_trip_ids.add(trip_id)

    trips = {trip_id: trip for trip_id, trip in candidate_trips.items() if trip_id in valid_trip_ids}
    route_ids = {trip["route_id"] for trip in trips.values()}
    shape_ids = {trip["shape_id"] for trip in trips.values()}
    routes = {route_id: route for route_id, route in routes.items() if route_id in route_ids}
    stop_times_by_trip = {
        trip_id: stop_times for trip_id, stop_times in stop_times_by_trip.items() if trip_id in valid_trip_ids
    }
    stop_ids = {
        stop_time.stop_id for stop_times in stop_times_by_trip.values() for stop_time in stop_times if stop_time.stop_id
    }
    stops = {row["stop_id"]: trim_row(row, STOPS_COLUMNS) for row in stops_rows if row.get("stop_id") in stop_ids}
    shapes_by_id = {shape_id: points for shape_id, points in shapes_by_id.items() if shape_id in shape_ids}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as output_zip:
        write_csv(
            output_zip,
            "routes.txt",
            ROUTES_COLUMNS,
            (routes[route_id] for route_id in sorted(routes)),
        )
        write_csv(
            output_zip,
            "trips.txt",
            TRIPS_COLUMNS,
            (trips[trip_id] for trip_id in sorted(trips)),
        )
        write_csv(
            output_zip,
            "stops.txt",
            STOPS_COLUMNS,
            (stops[stop_id] for stop_id in sorted(stops)),
        )
        write_csv(
            output_zip,
            "stop_times.txt",
            STOP_TIMES_COLUMNS,
            (stop_time.row for trip_id in sorted(stop_times_by_trip) for stop_time in stop_times_by_trip[trip_id]),
        )
        write_csv(
            output_zip,
            "shapes.txt",
            SHAPES_COLUMNS,
            (point.row for shape_id in sorted(shapes_by_id) for point in shapes_by_id[shape_id]),
        )

    report_summary(
        input_path=input_path,
        output_path=output_path,
        routes=routes,
        trips=trips,
        stops=stops,
        stop_times_by_trip=stop_times_by_trip,
        shapes_by_id=shapes_by_id,
    )


def has_bracketing_stops(
    stop_times: list[StopTimePoint],
    target_shape_dist: float,
) -> bool:
    previous_stop: StopTimePoint | None = None
    next_stop: StopTimePoint | None = None

    for stop_time in stop_times:
        if stop_time.shape_dist_traveled <= target_shape_dist:
            previous_stop = stop_time
        if stop_time.shape_dist_traveled >= target_shape_dist:
            next_stop = stop_time
            break

    return previous_stop is not None and next_stop is not None


def write_csv(
    zip_file: zipfile.ZipFile,
    name: str,
    columns: tuple[str, ...],
    rows: object,
) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    zip_file.writestr(name, buffer.getvalue().encode("utf-8"))


def report_summary(
    input_path: Path,
    output_path: Path,
    routes: dict[str, dict[str, str]],
    trips: dict[str, dict[str, str]],
    stops: dict[str, dict[str, str]],
    stop_times_by_trip: dict[str, list[StopTimePoint]],
    shapes_by_id: dict[str, list[ShapePoint]],
) -> None:
    input_size = input_path.stat().st_size
    output_size = output_path.stat().st_size
    reduction = 0.0 if input_size == 0 else (1 - (output_size / input_size)) * 100

    print(f"Input zip:  {input_path} ({input_size:,} bytes)")
    print(f"Output zip: {output_path} ({output_size:,} bytes)")
    print(f"Size reduction: {reduction:.1f}%")
    print(f"routes={len(routes)}")
    print(f"trips={len(trips)}")
    print(f"stops={len(stops)}")
    print("stop_times=" f"{sum(len(stop_times) for stop_times in stop_times_by_trip.values())}")
    print("shapes=" f"{sum(len(points) for points in shapes_by_id.values())}")


def main() -> int:
    args = parse_args()
    build_minimal_gtfs_zip(
        input_path=args.input,
        output_path=args.output,
        target_lat=args.lat,
        target_lon=args.lon,
        radius_meters=args.radius_meters,
        route_type=args.route_type,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
