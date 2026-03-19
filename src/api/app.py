from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request

from src.config import VROLIKSTRAAT_CONFIG

from .models import HealthResponse, MonitorApiResponse
from .service import RadarApiService


def create_app() -> FastAPI:
    service = RadarApiService(VROLIKSTRAAT_CONFIG)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.startup()
        try:
            yield
        finally:
            service.shutdown()

    app = FastAPI(
        title="train-radar-nl API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.radar_service = service

    @app.get("/healthz", response_model=HealthResponse)
    def healthz(request: Request) -> HealthResponse:
        radar_service: RadarApiService = request.app.state.radar_service
        return HealthResponse(
            status="ok" if radar_service.static_gtfs_ready else "starting",
            static_gtfs_ready=radar_service.static_gtfs_ready,
            static_gtfs_cache_path=radar_service.static_gtfs_cache_path,
            cache_ttl_seconds=radar_service.cache_ttl_seconds,
        )

    @app.get("/api/v1/radar", response_model=MonitorApiResponse)
    def radar_status(
        request: Request,
        lat: float = Query(..., description="Target latitude"),
        lon: float = Query(..., description="Target longitude"),
    ) -> MonitorApiResponse:
        radar_service: RadarApiService = request.app.state.radar_service

        try:
            return radar_service.get_status(lat, lon)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return app


app = create_app()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the train-radar-nl HTTP API.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    return parser.parse_args()


def cli() -> int:
    args = parse_args()
    uvicorn.run(
        "src.api.app:app",
        host=args.host,
        port=args.port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
