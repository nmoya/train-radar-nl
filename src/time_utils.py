from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (datetime(year, month + 1, 1) - timedelta(days=1)).day


def _last_sunday(year: int, month: int) -> datetime:
    day = _last_day_of_month(year, month)
    candidate = datetime(year, month, day)
    return candidate - timedelta(days=(candidate.weekday() + 1) % 7)


def _format_without_zoneinfo(timestamp: int, timezone_name: str, fmt: str) -> str:
    utc_datetime = datetime.fromtimestamp(timestamp, timezone.utc)

    if timezone_name == "UTC":
        return utc_datetime.strftime(fmt)

    if timezone_name != "Europe/Amsterdam":
        raise ZoneInfoNotFoundError(f"No time zone found with key {timezone_name}")

    dst_start = _last_sunday(utc_datetime.year, 3).replace(hour=1, tzinfo=timezone.utc)
    dst_end = _last_sunday(utc_datetime.year, 10).replace(hour=1, tzinfo=timezone.utc)
    is_dst = dst_start <= utc_datetime < dst_end
    offset_hours = 2 if is_dst else 1
    tz_name = "CEST" if is_dst else "CET"
    amsterdam_tz = timezone(timedelta(hours=offset_hours), tz_name)
    return utc_datetime.astimezone(amsterdam_tz).strftime(fmt)


def format_unix_timestamp(timestamp: int, timezone_name: str, fmt: str) -> str:
    """Format a Unix timestamp using an explicit IANA timezone name."""
    try:
        return datetime.fromtimestamp(timestamp, ZoneInfo(timezone_name)).strftime(fmt)
    except ZoneInfoNotFoundError:
        return _format_without_zoneinfo(timestamp, timezone_name, fmt)
