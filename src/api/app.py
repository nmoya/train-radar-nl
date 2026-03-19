from __future__ import annotations

import argparse
import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.config import VROLIKSTRAAT_CONFIG

from .routes.health import router as health_router
from .routes.train import router as train_router
from .service import RadarApiService

logger = logging.getLogger(__name__)


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

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception("Unhandled request error for %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
        logger.info(
            "%s %s -> %s in %sms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    app.include_router(health_router)
    app.include_router(train_router)

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
