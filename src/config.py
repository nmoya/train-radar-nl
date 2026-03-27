from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / ".env"
TARGET_LAT = "TARGET_LATITUDE"
TARGET_LON = "TARGET_LONGITUDE"
APP_TIMEZONE = "APP_TIMEZONE"
RUNTIME_STATIC_GTFS_URL = "RUNTIME_STATIC_GTFS_URL"
RUNTIME_STATIC_GTFS_REFRESH_INTERVAL_MINUTES = "RUNTIME_STATIC_GTFS_REFRESH_INTERVAL_MINUTES"
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


def read_str_env(name: str, default: str | None = None) -> str:
    """Read a string environment variable with a default fallback."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        if default is not None:
            return default
        raise ValueError(f"Environment variable {name} is not set and no default provided.")

    value = raw_value.strip()
    if value:
        return value
    if default is not None:
        return default
    raise ValueError(f"Environment variable {name} is empty and no default provided.")


def read_optional_str_env(name: str) -> str | None:
    """Read an optional string environment variable, returning None when unset or blank."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return None

    value = raw_value.strip()
    return value or None


def read_int_env(name: str, default: int | None = None) -> int:
    """Read an integer environment variable with a default fallback."""
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        if default is not None:
            return default
        raise ValueError(f"Environment variable {name} is not set and no default provided.")

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an int, got {raw_value!r}.") from exc


load_dotenv(DOTENV_PATH)


@dataclass(frozen=True)
class AppConfig:
    feed_url: str
    static_gtfs_url: str
    runtime_static_gtfs_url: str | None
    static_gtfs_cache_path: Path
    runtime_static_gtfs_refresh_interval_minutes: int
    target_lat: float
    target_lon: float
    radius_meters: int
    poll_interval_seconds: int
    target_passage_tolerance_ceiling_seconds: int
    target_passage_tolerance_factor: float
    target_passage_sparse_update_tolerance_factor: float
    timezone_name: str
    user_agent: str
    startup_time: int = field(default_factory=lambda: int(time.time()))


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


DEFAULT_CONFIG = AppConfig(
    feed_url="https://gtfs-rt.r-ov.nl/trainUpdates.pb",
    static_gtfs_url="https://gtfs.ovapi.nl/nl/gtfs-nl.zip",
    runtime_static_gtfs_url=read_optional_str_env(RUNTIME_STATIC_GTFS_URL),
    static_gtfs_cache_path=MINIFIED_STATIC_GTFS_CACHE_PATH,
    runtime_static_gtfs_refresh_interval_minutes=read_int_env(
        RUNTIME_STATIC_GTFS_REFRESH_INTERVAL_MINUTES,
        1440,
    ),
    target_lat=read_float_env(TARGET_LAT),
    target_lon=read_float_env(TARGET_LON),
    radius_meters=200,
    poll_interval_seconds=30,
    target_passage_tolerance_ceiling_seconds=60,
    target_passage_tolerance_factor=0.1,
    target_passage_sparse_update_tolerance_factor=0.5,
    timezone_name=read_str_env(APP_TIMEZONE, "UTC"),
    user_agent="train-radar-nl",
)
