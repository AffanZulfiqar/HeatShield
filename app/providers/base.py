"""Temperature provider interface.

Two implementations sit behind this: the live FortyGuard client and an offline
replay generator. The rest of the app never learns which one it is holding,
which is what keeps the demo runnable on a plane and the ledger honest about
where each number came from.
"""
from datetime import datetime
from typing import List, Protocol

from app.models import Reading, Site


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def bbox_polygon(lat: float, lng: float, side_m: int) -> dict:
    """A square GeoJSON polygon centred on the site, side_m across.

    FortyGuard's published sample takes a polygon area of interest rather than
    a point, so a worksite becomes a small box rather than a single coordinate.
    """
    import math

    half = side_m / 2.0
    dlat = half / 111_320.0
    dlng = half / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    ring = [
        [lng - dlng, lat - dlat],
        [lng + dlng, lat - dlat],
        [lng + dlng, lat + dlat],
        [lng - dlng, lat + dlat],
        [lng - dlng, lat - dlat],
    ]
    # FortyGuard requires a GeoJSON FeatureCollection, not a bare Polygon.
    # Confirmed from the working probe script — bare Polygon returns 0 features.
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }


class TemperatureProvider(Protocol):
    name: str

    async def current(self, site: Site) -> Reading: ...

    async def forecast(self, site: Site, hours: int) -> List[Reading]: ...

    async def historical(self, site: Site, start: datetime, end: datetime) -> List[Reading]: ...
