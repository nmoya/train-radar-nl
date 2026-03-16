# train-radar-nl

`train-radar-nl` watches Dutch railway GTFS-Realtime trip updates and renders a terminal dashboard for trains that pass near a configured target location.

The application:

- downloads and caches static GTFS data
- polls the realtime feed at a fixed interval
- estimates when each train will pass the configured target point
- groups trains into left/right directions
- renders a continuously refreshed dashboard with `Current` and `Upcoming` sections

The current default target is configured in [`src/config.py`](src/config.py).

## Requirements

- `uv`
- Python 3.13 or newer
- Internet access to fetch:
  - GTFS-Realtime trip updates
  - static GTFS data

Project dependencies are defined in [`pyproject.toml`](pyproject.toml) and locked in [`uv.lock`](uv.lock):

- `gtfs-realtime-bindings`
- `requests`
- `tqdm`

## Installation

From the repository root:

```powershell
uv sync
```

Create your local target configuration file:

```powershell
cp .env.example .env
```

## Target Configuration

The monitor target coordinates can be supplied in two ways:

1. environment variables loaded from `.env`
2. command line arguments passed to `src/main.py`

Environment variables:

- `TARGET_LATITUDE`
- `TARGET_LONGITUDE`

Files:

- [`.env.example`](.env.example): example values
- `.env`: your local values, loaded automatically at startup

The application loads `.env` itself. You do not need to export these variables in your shell first.
Command line arguments override `.env` values when both are provided.

## Functionality

At runtime, the application combines static GTFS shape and stop data with GTFS-Realtime trip updates to answer:

- which trains are relevant to the configured target point
- when each train is expected to pass that point
- which train is currently in range for each direction
- which train is next upcoming for each direction

The terminal dashboard shows, for both `Left` and `Right`:

- service label, for example `NS sprinter`
- full route, for example `Nijmegen -> Amsterdam Centraal`
- approximate trip progress at the monitored point
- local stop context around the target
- timing information such as `ETA`, `late by`, or `Expected`

## Running the Monitor

From the repository root:

```powershell
uv run python src/main.py
```

This uses the target coordinates from `.env`.

Use command line arguments only when you want to override the `.env` values for a specific run:

```powershell
uv run python src/main.py --lat <decimal_lat> --lon <decimal_longitude>
```

On startup, the application will:

- print the active config
- load static GTFS data
- print target stop-pair summary information
- start the live dashboard

## Building a Minimal GTFS Zip

The helper script can create a reduced GTFS archive containing only the files, columns, and rows needed near a target point.
By default it reads `TARGET_LATITUDE` and `TARGET_LONGITUDE` from `.env`. You can still override them with `--lat` and `--lon`.

General command:

```powershell
uv run python src\scripts\build_minimal_gtfs_zip.py --input <source-gtfs.zip> --output <reduced-gtfs.zip> --radius-meters <radius> [--route-type 2]
```

Example using the target from `.env`:

```powershell
uv run python src\scripts\build_minimal_gtfs_zip.py --input .cache\gtfs-nl.zip --output .cache\gtfs-nl-min.zip --radius-meters 200 --route-type 2
```

Arguments:

- `--input`: source GTFS zip
- `--output`: output zip to create
- `--lat`: optional target latitude override
- `--lon`: optional target longitude override
- `--radius-meters`: maximum distance from the target to a trip shape
- `--route-type`: GTFS `route_type` to keep, default `2` for rail

## Architecture

The codebase is split by responsibility.

- [`src/main.py`](src/main.py): startup entrypoint. Loads static GTFS, prints a short summary, then starts the monitor loop.
- [`src/monitor.py`](src/monitor.py): runtime loop and terminal renderer.
- [`src/monitor_models.py`](src/monitor_models.py): shared monitor domain types such as `DirectionId`, `TrainStatus`, and `MonitorSnapshot`.
- [`src/monitor_snapshot_builder.py`](src/monitor_snapshot_builder.py): transforms a realtime feed update into a `MonitorSnapshot`.
- [`src/target_passage.py`](src/target_passage.py): target passage estimation and alert-window timing calculations.
- [`src/static_gtfs.py`](src/static_gtfs.py): static GTFS loading, trimming, target-window construction, and vehicle detail resolution.
- [`src/feed.py`](src/feed.py): polling logic, conditional requests, feed caching, and update versioning.
- [`src/config.py`](src/config.py): application configuration.
- [`src/scripts/build_minimal_gtfs_zip.py`](src/scripts/build_minimal_gtfs_zip.py): helper script to create a reduced GTFS zip around a target location.

The main runtime flow is:

1. `FeedPoller` fetches realtime updates.
2. `MonitorSnapshotBuilder` converts the latest feed state into `TrainStatus` objects.
3. `MonitorRenderer` formats the current snapshot into dashboard lines.
4. The terminal is cleared and redrawn once per second.

## Notes

- Static GTFS is cached at the path configured by `static_gtfs_cache_path`.
- The monitor currently uses the configuration constant `VROLIKSTRAAT_CONFIG`.
- The dashboard is terminal-based and redraws continuously.
