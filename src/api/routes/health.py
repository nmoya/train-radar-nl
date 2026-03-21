from __future__ import annotations

import importlib.metadata
from pathlib import Path

from fastapi import APIRouter, Request

from src.api.models import AppConfigResponse, HealthResponse, RadarServiceResponse
from src.api.service import RadarApiService
from src.config import PROJECT_ROOT
from src.time_utils import format_unix_timestamp as format_timestamp_in_timezone

router = APIRouter()
DEPLOYED_COMMIT_PATH = PROJECT_ROOT / ".build-commit"


def list_installed_dependencies() -> list[str]:
    dependencies: list[str] = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        dependencies.append(f"{name}=={distribution.version}")
    return sorted(set(dependencies), key=str.lower)


def format_unix_timestamp(timestamp: int, timezone_name: str) -> str:
    return format_timestamp_in_timezone(timestamp, timezone_name, "%Y-%m-%d %H:%M:%S %Z")


def read_deployed_commit(path: Path = DEPLOYED_COMMIT_PATH) -> str | None:
    if not path.exists():
        return None

    commit = path.read_text(encoding="utf-8").strip()
    return commit or None


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    radar_service: RadarApiService = request.app.state.radar_service
    config = radar_service.config
    return HealthResponse(
        deployed_commit=read_deployed_commit(),
        radar_service=RadarServiceResponse(
            static_gtfs_ready=radar_service.static_gtfs_ready,
            cache_ttl_seconds=radar_service.cache_ttl_seconds,
        ),
        app_config=AppConfigResponse(
            feed_url=config.feed_url,
            static_gtfs_url=config.static_gtfs_url,
            static_gtfs_cache_path=str(config.static_gtfs_cache_path),
            target_lat=config.target_lat,
            target_lon=config.target_lon,
            radius_meters=config.radius_meters,
            poll_interval_seconds=config.poll_interval_seconds,
            target_passage_tolerance_ceiling_seconds=config.target_passage_tolerance_ceiling_seconds,
            target_passage_tolerance_factor=config.target_passage_tolerance_factor,
            target_passage_sparse_update_tolerance_factor=config.target_passage_sparse_update_tolerance_factor,
            timezone_name=config.timezone_name,
            user_agent=config.user_agent,
            startup_time=format_unix_timestamp(config.startup_time, config.timezone_name),
        ),
        dependencies=list_installed_dependencies(),
    )
