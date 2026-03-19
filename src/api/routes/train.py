from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.models import MonitorApiResponse
from src.api.service import RadarApiService

router = APIRouter()


@router.get("/train/radar", response_model=MonitorApiResponse)
def train_radar(
    request: Request,
    lat: float = Query(..., description="Target latitude"),
    lon: float = Query(..., description="Target longitude"),
) -> MonitorApiResponse:
    radar_service: RadarApiService = request.app.state.radar_service

    return radar_service.get_status(lat, lon)
