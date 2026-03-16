from __future__ import annotations

import math


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two points in meters."""
    earth_radius_m = 6_371_000.0
    point1_lat = math.radians(lat1)
    point2_lat = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(point1_lat) * math.cos(point2_lat) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_m * math.asin(math.sqrt(haversine))
