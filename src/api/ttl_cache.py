from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class CacheEntry(Generic[T]):
    expires_at: float
    value: T


class TtlCache(Generic[T]):
    def __init__(
        self,
        ttl_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entry: CacheEntry[T] | None = None
        self._lock = threading.Lock()

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def get(self) -> T | None:
        now = self._clock()
        with self._lock:
            entry = self._entry
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entry = None
                return None
            return entry.value

    def set(self, value: T) -> T:
        with self._lock:
            self._entry = CacheEntry(
                expires_at=self._clock() + self._ttl_seconds,
                value=value,
            )
        return value

    def clear(self) -> None:
        with self._lock:
            self._entry = None
