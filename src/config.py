from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / ".env"
TARGET_LAT = "TARGET_LATITUDE"
TARGET_LON = "TARGET_LONGITUDE"
FULL_STATIC_GTFS_CACHE_PATH = PROJECT_ROOT / ".cache" / "gtfs-nl.zip"
MINIFIED_STATIC_GTFS_CACHE_PATH = PROJECT_ROOT / ".cache" / "gtfs-nl-min.zip"


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE pairs from a .env file without overriding real env vars."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_float_env(name: str, default: float | None = None) -> float:
    """Read a float environment variable with a default fallback."""
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        if default is not None:
            return default
        raise ValueError(f"Environment variable {name} is not set and no default provided.")

    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a float, got {raw_value!r}.") from exc


load_dotenv(DOTENV_PATH)


@dataclass(frozen=True)
class AppConfig:
    feed_url: str
    static_gtfs_url: str
    static_gtfs_cache_path: Path
    target_lat: float
    target_lon: float
    radius_meters: int
    poll_interval_seconds: int
    target_passage_tolerance_ceiling_seconds: int
    target_passage_tolerance_floor_seconds: int
    target_passage_tolerance_factor: float
    target_passage_directional_tolerance_factor: float
    target_passage_alert_lead_seconds: int
    user_agent: str


def with_target_coordinates(
    config: AppConfig,
    *,
    target_lat: float | None = None,
    target_lon: float | None = None,
) -> AppConfig:
    """Return a config copy with optional target coordinate overrides."""
    return replace(
        config,
        target_lat=config.target_lat if target_lat is None else target_lat,
        target_lon=config.target_lon if target_lon is None else target_lon,
    )


def with_static_gtfs_cache_path(
    config: AppConfig,
    static_gtfs_cache_path: Path,
) -> AppConfig:
    """Return a config copy with a different static GTFS cache path."""
    return replace(config, static_gtfs_cache_path=static_gtfs_cache_path)


VROLIKSTRAAT_CONFIG = AppConfig(
    feed_url="https://gtfs-rt.r-ov.nl/trainUpdates.pb",
    static_gtfs_url="https://gtfs.ovapi.nl/nl/gtfs-nl.zip",
    static_gtfs_cache_path=MINIFIED_STATIC_GTFS_CACHE_PATH,
    target_lat=read_float_env(TARGET_LAT),
    target_lon=read_float_env(TARGET_LON),
    radius_meters=200,
    poll_interval_seconds=30,
    target_passage_tolerance_ceiling_seconds=60,
    target_passage_tolerance_floor_seconds=20,
    target_passage_tolerance_factor=0.1,
    target_passage_directional_tolerance_factor=0.5,
    target_passage_alert_lead_seconds=15,
    user_agent="train-radar-nl",
)
