from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from src.api.presenter import build_monitor_api_response, build_train_response
from src.config import AppConfig
from src.feed import FeedPoller
from src.monitor_models import MonitorSnapshot, TrainStatus
from src.monitor_snapshot_builder import MonitorSnapshotBuilder
from src.static_gtfs import StaticGtfsRows, build_static_gtfs_data, read_static_gtfs_rows
from src.target_passage import TargetPassageEstimator
from src.api.ttl_cache import TtlCache

from .models import MonitorApiResponse, TrainStatusResponse


@dataclass(frozen=True)
class CachedMonitorStatus:
    snapshot: MonitorSnapshot | None
    feed_timestamp: int | None
    feed_error: str | None
    target_stop_pairs: list[str]
    cache_expires_at: int


@dataclass
class TigrisRefreshState:
    last_read_at: int | None = None
    last_file_updated_at: int | None = None
    last_reload_at: int | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class DownloadedZipMetadata:
    last_modified_at: int | None


def parse_http_datetime(value: str | None) -> int | None:
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


class RadarApiService:
    def __init__(
        self,
        base_config: AppConfig,
        *,
        cache_ttl_seconds: int | None = None,
    ) -> None:
        self.base_config = base_config
        self.poller = FeedPoller(self.base_config)
        self.static_gtfs_rows: StaticGtfsRows | None = None
        self.response_cache = TtlCache[CachedMonitorStatus](
            cache_ttl_seconds or base_config.poll_interval_seconds
        )
        self._static_gtfs_lock = threading.Lock()
        self._tigris_refresh_lock = threading.Lock()
        self._tigris_refresh_stop = threading.Event()
        self._tigris_refresh_thread: threading.Thread | None = None
        self._tigris_state = TigrisRefreshState()
        self._next_tigris_refresh_at = 0
        self._tigris_session = requests.Session()

    @property
    def cache_ttl_seconds(self) -> int:
        return self.response_cache.ttl_seconds

    @property
    def static_gtfs_cache_path(self) -> str:
        return str(self.base_config.static_gtfs_cache_path)

    @property
    def static_gtfs_ready(self) -> bool:
        with self._static_gtfs_lock:
            return self.static_gtfs_rows is not None

    @property
    def config(self) -> AppConfig:
        return self.base_config

    @property
    def tigris_refresh_enabled(self) -> bool:
        return self.base_config.runtime_static_gtfs_url is not None

    @property
    def tigris_refresh_interval_minutes(self) -> int:
        return self.base_config.runtime_static_gtfs_refresh_interval_minutes

    @property
    def tigris_last_read_at(self) -> int | None:
        with self._tigris_refresh_lock:
            return self._tigris_state.last_read_at

    @property
    def tigris_last_file_updated_at(self) -> int | None:
        with self._tigris_refresh_lock:
            return self._tigris_state.last_file_updated_at

    @property
    def tigris_last_reload_at(self) -> int | None:
        with self._tigris_refresh_lock:
            return self._tigris_state.last_reload_at

    @property
    def tigris_last_error(self) -> str | None:
        with self._tigris_refresh_lock:
            return self._tigris_state.last_error

    def startup(self) -> None:
        if self.tigris_refresh_enabled:
            local_path = self.base_config.static_gtfs_cache_path
            if local_path.exists():
                self._load_static_gtfs_from_path(local_path)
                self._schedule_next_tigris_refresh(int(time.time()))
            else:
                self.refresh_static_gtfs_if_due(force=True)
                if not self.static_gtfs_ready:
                    self._load_existing_static_gtfs_or_raise()
            if self.tigris_refresh_interval_minutes > 0:
                self._start_tigris_refresh_thread()
            return

        self._load_static_gtfs_from_path(self.poller.ensure_static_gtfs_zip())

    def shutdown(self) -> None:
        self._tigris_refresh_stop.set()
        if self._tigris_refresh_thread is not None:
            self._tigris_refresh_thread.join(timeout=2)
            self._tigris_refresh_thread = None
        self.poller.close()
        self._tigris_session.close()

    def get_status(self) -> MonitorApiResponse:
        display_timestamp = int(time.time())
        cached_status = self.response_cache.get()
        if cached_status is None:
            cached_status = self.response_cache.set(self._build_cached_status(display_timestamp))

        return self._build_response(cached_status, display_timestamp)

    def _build_status(self) -> MonitorApiResponse:
        display_timestamp = int(time.time())
        cached_status = self._build_cached_status(display_timestamp)
        return self._build_response(cached_status, display_timestamp)

    def _build_cached_status(self, display_timestamp: int) -> CachedMonitorStatus:
        with self._static_gtfs_lock:
            static_gtfs_rows = self.static_gtfs_rows

        if static_gtfs_rows is None:
            raise RuntimeError("Static GTFS rows are not loaded.")

        config = self.base_config
        static_gtfs = build_static_gtfs_data(static_gtfs_rows, config)
        feed_update = self.poller.update()
        snapshot = MonitorSnapshotBuilder(
            static_gtfs,
            TargetPassageEstimator(config),
        ).build(feed_update)

        return CachedMonitorStatus(
            snapshot=snapshot,
            feed_timestamp=snapshot.feed_timestamp if snapshot is not None else None,
            feed_error=feed_update.error,
            target_stop_pairs=static_gtfs.summarize_target_stop_pairs(),
            cache_expires_at=display_timestamp + self.cache_ttl_seconds,
        )

    def _build_response(
        self,
        cached_status: CachedMonitorStatus,
        display_timestamp: int,
    ) -> MonitorApiResponse:
        return build_monitor_api_response(
            config=self.base_config,
            cached_status=cached_status,
            display_timestamp=display_timestamp,
            cache_ttl_seconds=self.cache_ttl_seconds,
        )

    def _build_train_response(
        self,
        train_status: TrainStatus | None,
        display_timestamp: int,
    ) -> TrainStatusResponse | None:
        return build_train_response(train_status, display_timestamp, self.base_config)

    def refresh_static_gtfs_if_due(self, *, force: bool = False) -> bool:
        if not self.tigris_refresh_enabled:
            return False

        refresh_interval_seconds = max(0, self.tigris_refresh_interval_minutes * 60)
        if not force and refresh_interval_seconds <= 0:
            return False
        current_time = int(time.time())
        if not force and refresh_interval_seconds > 0 and current_time < self._next_tigris_refresh_at:
            return False

        with self._tigris_refresh_lock:
            current_time = int(time.time())
            if not force and refresh_interval_seconds > 0 and current_time < self._next_tigris_refresh_at:
                return False

            self._tigris_state.last_read_at = current_time
            try:
                refreshed = self._refresh_static_gtfs_locked(current_time=current_time)
            except Exception as exc:
                self._schedule_next_tigris_refresh(current_time)
                self._tigris_state.last_error = f"Tigris refresh failed: {exc}"
                return False

            self._schedule_next_tigris_refresh(current_time)
            return refreshed

    def _refresh_static_gtfs_locked(self, *, current_time: int) -> bool:
        local_path = self.base_config.static_gtfs_cache_path
        downloaded_path, downloaded_metadata = self._download_tigris_zip(local_path)
        try:
            rows = read_static_gtfs_rows(downloaded_path)
            downloaded_path.replace(local_path)
        except Exception:
            downloaded_path.unlink(missing_ok=True)
            raise
        self._set_static_gtfs_rows(rows)

        last_modified_at = downloaded_metadata.last_modified_at
        if last_modified_at is not None:
            self._tigris_state.last_file_updated_at = last_modified_at

        self._tigris_state.last_reload_at = current_time
        self._tigris_state.last_error = None
        self.response_cache.clear()
        return True

    def _download_tigris_zip(self, local_path: Path) -> tuple[Path, DownloadedZipMetadata]:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = local_path.with_suffix(f"{local_path.suffix}.download")

        try:
            with self._tigris_session.get(
                self.base_config.runtime_static_gtfs_url,
                headers={"User-Agent": self.base_config.user_agent},
                timeout=120,
                stream=True,
            ) as response:
                response.raise_for_status()
                metadata = DownloadedZipMetadata(
                    last_modified_at=parse_http_datetime(response.headers.get("Last-Modified")),
                )

                with temp_path.open("wb") as zip_file:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            zip_file.write(chunk)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return temp_path, metadata

    def _load_existing_static_gtfs_or_raise(self) -> None:
        local_path = self.base_config.static_gtfs_cache_path
        if local_path.exists():
            self._load_static_gtfs_from_path(local_path)
            return

        error = self.tigris_last_error or "Tigris refresh failed before any static GTFS file was available."
        raise RuntimeError(error)

    def _load_static_gtfs_from_path(self, zip_path: Path) -> None:
        self._set_static_gtfs_rows(read_static_gtfs_rows(zip_path))

    def _set_static_gtfs_rows(self, rows: StaticGtfsRows) -> None:
        with self._static_gtfs_lock:
            self.static_gtfs_rows = rows

    def _schedule_next_tigris_refresh(self, current_time: int) -> None:
        refresh_interval_seconds = max(0, self.tigris_refresh_interval_minutes * 60)
        if refresh_interval_seconds > 0:
            self._next_tigris_refresh_at = current_time + refresh_interval_seconds

    def _start_tigris_refresh_thread(self) -> None:
        if self._tigris_refresh_thread is not None:
            return

        self._tigris_refresh_stop.clear()
        self._tigris_refresh_thread = threading.Thread(
            target=self._run_tigris_refresh_loop,
            name="tigris-static-gtfs-refresh",
            daemon=True,
        )
        self._tigris_refresh_thread.start()

    def _run_tigris_refresh_loop(self) -> None:
        while not self._tigris_refresh_stop.wait(self._next_tigris_wait_seconds()):
            self.refresh_static_gtfs_if_due()

    def _next_tigris_wait_seconds(self) -> int:
        if self.tigris_refresh_interval_minutes <= 0:
            return 3600

        if self._next_tigris_refresh_at <= 0:
            return 5

        remaining_seconds = self._next_tigris_refresh_at - int(time.time())
        return max(5, min(remaining_seconds, 3600))
