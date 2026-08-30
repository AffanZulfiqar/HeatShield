"""Official observation station baseline.

This is the comparator, not the product. The argument Scorched makes is
that compliance is currently judged against the nearest official station, which
can be many kilometres from the worksite and sited over grass at an airfield.
To make that argument you need the station number next to the site number.

api.weather.gov is free, keyless and authoritative for US sites. It requires a
descriptive User-Agent; set NWS_USER_AGENT with a real contact address before
running this against the live service.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import httpx

from app import config
from app.models import Reading, Site
from app.providers.base import c_to_f
from app.providers.replay import synth_f


class StationProvider:
    name = "nws"

    def __init__(self):
        self._station_cache: dict = {}

    def _headers(self) -> dict:
        return {"User-Agent": config.NWS_USER_AGENT, "Accept": "application/geo+json"}

    async def nearest_station(self, site: Site) -> Tuple[str, str, float]:
        """Return (station_id, station_name, distance_km) for the site."""
        if site.id in self._station_cache:
            return self._station_cache[site.id]
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            pt = await client.get(f"{config.NWS_BASE}/points/{site.lat:.4f},{site.lng:.4f}")
            pt.raise_for_status()
            stations_url = pt.json()["properties"]["observationStations"]
            st = await client.get(stations_url)
            st.raise_for_status()
            features = st.json()["features"]
            if not features:
                raise RuntimeError(f"no observation stations near {site.name}")
            first = features[0]
            sid = first["properties"]["stationIdentifier"]
            sname = first["properties"].get("name", sid)
            slng, slat = first["geometry"]["coordinates"][:2]
            dist = _haversine_km(site.lat, site.lng, slat, slng)
        result = (sid, sname, dist)
        self._station_cache[site.id] = result
        return result

    async def historical(self, site: Site, start: datetime, end: datetime) -> List[Reading]:
        sid, sname, dist = await self.nearest_station(site)
        url = f"{config.NWS_BASE}/stations/{sid}/observations"
        params = {"start": _iso_z(start), "end": _iso_z(end)}
        async with httpx.AsyncClient(headers=self._headers(), timeout=60) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            features = r.json().get("features", [])

        out = []
        for f in features:
            props = f.get("properties", {})
            temp = (props.get("temperature") or {}).get("value")
            ts = props.get("timestamp")
            if temp is None or ts is None:
                continue
            out.append(
                Reading(
                    site_id=site.id,
                    ts_utc=datetime.fromisoformat(ts.replace("Z", "+00:00")),
                    temp_f=c_to_f(float(temp)),
                    source=f"station:{sid}",
                    provenance="measured",
                    detail={"station_name": sname, "distance_km": round(dist, 1)},
                )
            )
        out.sort(key=lambda r: r.ts_utc)
        return out


class ReplayStationProvider:
    """Offline stand-in: the same diurnal curve with the site's surface effect
    removed and the peak damped, which is what a regional station over grass
    tends to look like relative to asphalt or an open field.

    The resulting gap is a declared parameter, not evidence. Say so out loud.
    """

    name = "replay-station"

    async def nearest_station(self, site: Site) -> Tuple[str, str, float]:
        return ("SYNTH", "synthetic regional station", 14.6)

    async def historical(self, site: Site, start: datetime, end: datetime) -> List[Reading]:
        out = []
        cursor = start.replace(minute=0, second=0, microsecond=0)
        while cursor <= end:
            out.append(
                Reading(
                    site_id=site.id,
                    ts_utc=cursor,
                    temp_f=synth_f(site, cursor, include_surface=False),
                    source="station:SYNTH",
                    provenance="replay-synthetic",
                    detail={
                        "station_name": "synthetic regional station",
                        "distance_km": 14.6,
                        "warning": "synthetic value, not a measurement",
                    },
                )
            )
            cursor += timedelta(hours=1)
        return out


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def get_station_provider(force_replay: Optional[bool] = None):
    replay = config.is_replay() if force_replay is None else force_replay
    return ReplayStationProvider() if replay else StationProvider()
