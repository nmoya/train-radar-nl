# train-radar-nl

`train-radar-nl` watches Dutch railway GTFS-Realtime trip updates and renders a terminal dashboard for trains that pass near a configured target location.

The application:

- downloads and caches static GTFS data
- polls the realtime feed at a fixed interval
- estimates when each train will pass the configured target point
- groups trains into left/right directions
- renders a continuously refreshed dashboard with `Current` and `Upcoming` sections
- can expose the same monitor data through a small HTTP API for the server-configured default target

The default target is whatever `TARGET_LATITUDE` and `TARGET_LONGITUDE` are set to in the server `.env`.

## Requirements

- `uv`
- Python 3.13 or newer
- Internet access to fetch:
  - GTFS-Realtime trip updates
  - static GTFS data

Project dependencies are defined in [`pyproject.toml`](pyproject.toml) and locked in [`uv.lock`](uv.lock):

- `fastapi`
- `gtfs-realtime-bindings`
- `pydantic`
- `requests`
- `tqdm`
- `uvicorn`

## Installation

From the repository root:

```powershell
uv sync
```

Create your local target configuration file:

```powershell
cp .env.example .env
```

## Entry Points

The project currently has three entry points:

- `uv run train-radar-dashboard`: terminal dashboard
- `uv run train-radar-minify`: GTFS minifier
- `uv run train-radar-api`: HTTP API

## Target Configuration

The monitor target coordinates can be supplied in two ways:

1. environment variables loaded from `.env`
2. command line arguments passed to the dashboard or minifier entry points

Environment variables:

- `TARGET_LATITUDE`
- `TARGET_LONGITUDE`
- `RUNTIME_STATIC_GTFS_URL`: optional public Tigris object URL for the minified GTFS zip used by the API runtime
- `RUNTIME_STATIC_GTFS_REFRESH_INTERVAL_MINUTES`: how often the API checks Tigris for an updated zip, default `1440` (once per day)

Files:

- [`.env.example`](.env.example): example values
- `.env`: local values, loaded automatically at startup

The application loads `.env` itself. You do not need to export these variables in your shell first.
For the HTTP API, the default configuration is whatever is defined in the server `.env` file, and `/train/radar` serves that single fixed target.
Command line arguments still override `.env` for the dashboard or minifier when both are provided.

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
uv run train-radar-dashboard
```

This uses the target coordinates from `.env`.

Use command line arguments only when you want to override the `.env` values for a specific run:

```powershell
uv run train-radar-dashboard --lat <decimal_lat> --lon <decimal_longitude>
```

On startup, the application will:

- load static GTFS data
- start the live dashboard

## Building a Minimal GTFS Zip

The helper script can create a reduced GTFS archive containing only the files, columns, and rows needed near a target point.
By default it reads `TARGET_LATITUDE` and `TARGET_LONGITUDE` from `.env`. You can still override them with `--lat` and `--lon`.

General command:

```powershell
uv run train-radar-minify --input <source-gtfs.zip> --output <reduced-gtfs.zip> --radius-meters <radius> [--route-type 2]
```

Example using the target from `.env`:

```powershell
uv run train-radar-minify --input .cache\gtfs-nl.zip --output .cache\gtfs-nl-min.zip --radius-meters 200 --route-type 2
```

Arguments:

- `--input`: source GTFS zip
- `--output`: output zip to create
- `--lat`: optional target latitude override
- `--lon`: optional target longitude override
- `--radius-meters`: maximum distance from the target to a trip shape
- `--route-type`: GTFS `route_type` to keep, default `2` for rail

## Running the HTTP API

From the repository root:

```powershell
uv run train-radar-api --host 127.0.0.1 --port 8000
```

Available endpoints:

- `GET /health`
- `GET /train/radar`

API behavior:

- the server loads static GTFS from `RUNTIME_STATIC_GTFS_URL` when configured, otherwise it falls back to the local cache path
- the runtime keeps a local `.cache/gtfs-nl-min.zip` copy on disk after a successful download
- the server downloads and fully replaces the local runtime GTFS zip every `RUNTIME_STATIC_GTFS_REFRESH_INTERVAL_MINUTES`
- responses are cached for the server-configured default target for 30 seconds
- the feed polling path is reused from the CLI implementation
- the health response includes the deployed commit, startup time, installed dependencies, and Tigris refresh metadata

Example request:

```text
http://127.0.0.1:8000/train/radar
```

## Fly.io Boilerplate

Deployment boilerplate files:

- [`fly.toml`](fly.toml)
- [`Procfile`](Procfile)
- [`Dockerfile`](Dockerfile)
- [`.dockerignore`](.dockerignore)

The current Fly setup assumes:

- one HTTP service on port `8080`
- automatic machine start/stop
- `RUNTIME_STATIC_GTFS_URL` points to the minified GTFS object stored in Tigris
- the API downloads and refreshes the minified GTFS zip at runtime instead of baking it into the image

Recommended Fly runtime configuration:

- set `RUNTIME_STATIC_GTFS_URL` to the public Tigris object URL for `gtfs/gtfs-nl-min.zip`
- optionally set `RUNTIME_STATIC_GTFS_REFRESH_INTERVAL_MINUTES` if you want something other than the default `1440`
- keep `TARGET_LATITUDE`, `TARGET_LONGITUDE`, and `APP_TIMEZONE` configured as before

How to get the public Tigris object URL:

1. create a public bucket with `fly storage create --public`
2. run the GTFS upload workflow once so `gtfs/gtfs-nl-min.zip` exists in the bucket
3. open the bucket dashboard with `fly storage dashboard <bucket-name>`
4. browse to the object `gtfs/gtfs-nl-min.zip`
5. copy the public object URL from the Tigris dashboard
6. set that copied value as `RUNTIME_STATIC_GTFS_URL` in Fly

Useful Fly commands:

- `fly storage list`
- `fly storage status <bucket-name>`
- `fly storage dashboard <bucket-name>`

## GTFS Upload Workflow

A scheduled GitHub Actions workflow is available at [`.github/workflows/upload-gtfs-to-tigris-daily.yml`](.github/workflows/upload-gtfs-to-tigris-daily.yml).
It runs every day at `02:15` UTC and can also be started manually from the GitHub Actions tab with `Run workflow`.

The workflow:

- downloads the latest full `gtfs-nl.zip`
- builds a fresh `.cache/gtfs-nl-min.zip`
- uploads the result to the stable Tigris object key `gtfs/gtfs-nl-min.zip`

Required GitHub secrets:

- `TIGRIS_AWS_ACCESS_KEY_ID`
- `TIGRIS_AWS_SECRET_ACCESS_KEY`
- `TIGRIS_AWS_REGION`
- `TIGRIS_AWS_ENDPOINT_URL_S3`
- `TIGRIS_BUCKET_NAME`

These values come from `fly storage create`, which provisions a Tigris bucket and prints the bucket name, endpoint, and AWS-compatible credentials.

Notes:

- GitHub scheduled workflows run on the latest commit on the default branch
- the cron expression uses UTC
- the same workflow handles both daily automation and manual uploads
- the workflow overwrites the same object key each run rather than creating a commit or triggering a deploy

## Architecture

The codebase is split by responsibility.

- [`src/main.py`](src/main.py): CLI dashboard entrypoint.
- [`src/api/app.py`](src/api/app.py): FastAPI application and API CLI entrypoint.
- [`src/api/service.py`](src/api/service.py): API runtime service, startup GTFS loading, and per-location TTL cache.
- [`src/api/models.py`](src/api/models.py): Pydantic response models.
- [`src/monitor.py`](src/monitor.py): runtime loop and terminal renderer.
- [`src/monitor_models.py`](src/monitor_models.py): shared monitor domain types such as `DirectionId`, `TrainStatus`, and `MonitorSnapshot`.
- [`src/monitor_snapshot_builder.py`](src/monitor_snapshot_builder.py): transforms a realtime feed update into a `MonitorSnapshot`.
- [`src/snapshot_view.py`](src/snapshot_view.py): shared snapshot selection logic used by the CLI and API.
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
- The monitor currently uses the configuration constant `DEFAULT_CONFIG`.
- The dashboard is terminal-based and redraws continuously.
- The API loads and retains the rows from the bundled minimal GTFS zip at startup.
