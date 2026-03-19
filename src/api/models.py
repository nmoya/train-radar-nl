from __future__ import annotations

from pydantic import BaseModel, Field


class AppConfigResponse(BaseModel):
    feed_url: str
    static_gtfs_url: str
    static_gtfs_cache_path: str
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
    startup_time: str


class TargetLocationResponse(BaseModel):
    latitude: float
    longitude: float
    radius_meters: int


class TrainStatusResponse(BaseModel):
    service: str
    company: str
    train_type: str
    agency: str
    route: str
    origin: str
    destination: str
    stop_context: str
    previous_stop: str
    next_stop: str
    direction_id: str
    progress_percent: int | None
    distance_to_target_m: float
    estimated_target_timestamp: int
    estimated_target_time: str
    range_start_timestamp: int
    range_end_timestamp: int
    seconds_until_target: int
    seconds_until_range: int
    is_in_range: bool


class DirectionBoardResponse(BaseModel):
    left: TrainStatusResponse | None
    right: TrainStatusResponse | None


class MonitorApiResponse(BaseModel):
    generated_at: int
    cache_ttl_seconds: int
    cache_expires_at: int
    feed_timestamp: int | None
    feed_error: str | None = None
    target: TargetLocationResponse
    current: DirectionBoardResponse
    upcoming: DirectionBoardResponse
    target_stop_pairs: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    deployed_commit: str | None
    static_gtfs_ready: bool
    cache_ttl_seconds: int
    app_config: AppConfigResponse
    dependencies: list[str] = Field(default_factory=list)
