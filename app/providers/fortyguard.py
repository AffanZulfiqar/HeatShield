"""FortyGuard Temperature API client.

Confirmed API behaviour from probe script:
  Submit:  POST /heatmap
           headers: {"api-key": KEY, "Content-Type": "application/json"}
           body:    {"polygon_aoi": <GeoJSON FeatureCollection>,
                     "date_time": {"start_date": "YYYY-MM-DD",
                                   "start_time": "HH:MM",
                                   "filter_type": 1},
                     "granularity": 100}
           returns: {"data": {"activity_id": "<uuid>"}}

  Poll:    GET /status/{activity_id}
           returns: {"data": {"status": "Processing"|"Completed",
                               "result": {"map_data": {"features": [...]}}}}

  Data window:
    - 1 day back  → Completed but 0 features (no data yet)
    - 3+ days back → Completed with features
    - filter_type=1 works for all historical dates
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List

import httpx

from app import config
from app.models import Reading, Site
from app.providers.base import bbox_polygon, c_to_f

log = logging.getLogger("scorched.fortyguard")

# Property names that carry a temperature. "value" is deliberately NOT here:
# it matches nothing in FortyGuard's real payload but does match the synthetic
# {"value": coordinates} wrapper the old code passed geometry through, which
# swept every lng/lat into the temperature pool.
TEMP_KEY_HINTS = ("temp", "temperature", "lst", "t2m", "air_temp", "land_surface_temp")

# Preferred property, in order, for the single representative value of a tile.
# Confirmed shape: properties = {tile_id, average_temperature,
#                                min_temperature, max_temperature}
PREFERRED_TEMP_KEYS = (
    "average_temperature", "avg_temperature", "mean_temperature",
    "temperature", "temp", "lst", "t2m",
)

# Minimum days back that returns features (1 day back = 0 features)
MIN_DAYS_BACK = 3


class FortyGuardError(RuntimeError):
    pass


def extract_temps(payload: Any) -> List[float]:
    """Recursively walk the response and collect plausible temperature values."""
    found: List[float] = []

    def walk(node: Any, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k.lower())
        elif isinstance(node, list):
            for item in node:
                walk(item, key_hint)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            if any(h in key_hint for h in TEMP_KEY_HINTS):
                found.append(float(node))

    walk(payload)
    return found


def extract_from_features(features: list) -> List[float]:
    """One temperature per tile, taken only from feature properties.

    Geometry is never read. A tile's coordinates are numbers in the same
    payload as its temperature, and any parser loose enough to hoover up both
    will average a Las Vegas summer afternoon down to below freezing.

    Taking one value per tile (not min AND max AND average) also keeps the
    spatial mean honest: each tile gets equal weight regardless of how many
    temperature fields the API happens to publish for it.
    """
    temps: List[float] = []
    for feat in features:
        props = feat.get("properties") or {}
        chosen = None

        for key in PREFERRED_TEMP_KEYS:
            v = props.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                chosen = float(v)
                break

        if chosen is None:
            # Unknown property naming: average whatever looks temperature-like
            # in THIS tile, so the tile still contributes exactly one value.
            candidates = [
                float(v) for k, v in props.items()
                if any(h in k.lower() for h in TEMP_KEY_HINTS)
                and isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            if candidates:
                chosen = sum(candidates) / len(candidates)

        if chosen is not None:
            temps.append(chosen)

    return temps


def temps_from_body(data: dict) -> List[float]:
    """Temperatures for one completed activity, features first, whole-body second."""
    features = ((data.get("result") or {}).get("map_data") or {}).get("features") or []
    temps = extract_from_features(features)
    if not temps:
        # Unknown response shape: fall back to a recursive walk. Safe now that
        # "value" is out of TEMP_KEY_HINTS, so geometry can't leak in.
        temps = extract_temps(data)
    return temps


def plausible_mean_f(values: List[float]) -> float:
    if not values:
        raise FortyGuardError("no temperature values found in API response")
    mean = sum(values) / len(values)
    # Try Celsius first; if result is implausible, assume already Fahrenheit
    f_if_c = c_to_f(mean)
    if config.FG_UNITS == "c" or (-30 <= mean <= 60 and not (60 <= mean <= 130)):
        f = f_if_c
    else:
        f = mean
    if not (-60.0 <= f <= 160.0):
        raise FortyGuardError(
            f"temperature {f:.1f}°F out of plausible range (raw mean {mean:.2f})"
        )
    return round(f, 2)


class FortyGuardProvider:
    name = "fortyguard"

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key or config._fg_key()
        self.base_url = (base_url or config.FG_BASE_URL).rstrip("/")
        if not self.api_key:
            raise FortyGuardError(
                "FORTYGUARD_API_KEY is not set. Add it to .env or set DATA_MODE=replay."
            )

    def _headers(self) -> dict:
        return {"api-key": self.api_key, "Content-Type": "application/json"}

    def _safe_date(self, days_back: int = MIN_DAYS_BACK) -> datetime:
        """Return a date guaranteed to have features (≥3 days back)."""
        return (datetime.now(timezone.utc) - timedelta(days=days_back)).replace(
            hour=14, minute=0, second=0, microsecond=0
        )

    def _build_payload(self, site: Site, when: datetime, side_m: int = 0) -> dict:
        return {
            "polygon_aoi": bbox_polygon(site.lat, site.lng, side_m or config.FG_AOI_SIDE_M),
            "date_time": {
                "start_date": when.strftime("%Y-%m-%d"),
                "start_time": when.strftime("%H:%M"),
                "filter_type": 1,  # Only type that returns data
            },
            "granularity": config.FG_GRANULARITY,
        }

    async def _submit(self, client: httpx.AsyncClient, payload: dict) -> str:
        url = f"{self.base_url}/heatmap"
        r = await client.post(url, headers=self._headers(), json=payload, timeout=30)
        r.raise_for_status()
        body = r.json()
        activity_id = (body.get("data") or {}).get("activity_id") or body.get("activity_id")
        if not activity_id:
            raise FortyGuardError(f"no activity_id in submit response: {body}")
        return activity_id

    async def _poll(self, client: httpx.AsyncClient, activity_id: str) -> dict:
        url = f"{self.base_url}/status/{activity_id}"
        deadline = datetime.now(timezone.utc) + timedelta(seconds=config.FG_POLL_TIMEOUT_S)
        attempt = 0
        last_status = None
        while datetime.now(timezone.utc) < deadline:
            attempt += 1
            r = await client.get(url, headers=self._headers(), timeout=30)
            r.raise_for_status()
            body = r.json()
            status = str(
                (body.get("data") or {}).get("status") or body.get("status") or ""
            ).lower()

            if attempt == 1:
                # Log the first body in full. Without this the only evidence a poll
                # loop leaves behind is httpx's "HTTP/1.1 200 OK" lines, which tell
                # you nothing about whether the job is running or the status field
                # is simply somewhere else in the payload.
                log.info(
                    "fortyguard %s first poll: status=%r top-level keys=%s body=%s",
                    activity_id, status, list(body.keys()), json.dumps(body)[:800],
                )
                if not status:
                    raise FortyGuardError(
                        f"activity {activity_id}: no recognisable status field in the poll "
                        f"response — the parser is looking for data.status or status. "
                        f"Body was: {json.dumps(body)[:600]}"
                    )
            elif status != last_status:
                log.info("fortyguard %s status -> %r (poll %d)", activity_id, status, attempt)
            last_status = status

            if status in ("completed", "complete", "success", "done", "finished"):
                log.info("fortyguard %s completed after %d polls", activity_id, attempt)
                return body
            if status in ("failed", "error"):
                raise FortyGuardError(f"activity {activity_id} failed: {body}")
            await asyncio.sleep(config.FG_POLL_INTERVAL_S)
        raise FortyGuardError(
            f"activity {activity_id} still {last_status!r} after "
            f"{config.FG_POLL_TIMEOUT_S}s ({attempt} polls)"
        )

    async def _fetch_reading(self, site: Site, when: datetime, provenance: str) -> Reading:
        """One reading, widening the area of interest once if the first try is empty.

        A completed activity with zero features is not an error — it means the
        requested box didn't line up with any tile FortyGuard has data for. A
        200 m box at 100 m granularity is a 2x2 grid, small enough to fall
        through the gaps at some locations. Widening costs one extra heatmap
        and only happens on the sites that need it.
        """
        attempts = [config.FG_AOI_SIDE_M]
        if config.FG_AOI_RETRY_M > config.FG_AOI_SIDE_M:
            attempts.append(config.FG_AOI_RETRY_M)

        last_features = 0
        async with httpx.AsyncClient() as client:
            for i, side_m in enumerate(attempts):
                payload = self._build_payload(site, when, side_m=side_m)
                activity_id = await self._submit(client, payload)
                body = await self._poll(client, activity_id)

                data = body.get("data") or body
                features = ((data.get("result") or {}).get("map_data") or {}).get("features") or []
                last_features = len(features)
                temps = temps_from_body(data)

                if temps:
                    if i > 0:
                        log.info(
                            "%s: %d m box was empty, %d m returned %d tiles",
                            site.id, attempts[0], side_m, len(features),
                        )
                    return Reading(
                        site_id=site.id,
                        ts_utc=when,
                        temp_f=plausible_mean_f(temps),
                        source="fortyguard",
                        provenance=provenance,
                        detail={
                            "features": len(features),
                            "granularity_m": config.FG_GRANULARITY,
                            "aoi_side_m": side_m,
                        },
                    )

                log.warning(
                    "%s: activity %s completed with %d features at %d m box (%s)",
                    site.id, activity_id, len(features), side_m,
                    when.strftime("%Y-%m-%d %H:%M UTC"),
                )

        raise FortyGuardError(
            f"{site.id}: FortyGuard returned no tile data for "
            f"{when:%Y-%m-%d %H:%M UTC} at ({site.lat}, {site.lng}); "
            f"tried boxes {attempts} m, last returned {last_features} features"
        )

    async def current(self, site: Site) -> Reading:
        """Most recent available reading (3 days back — 1 day back has no features)."""
        return await self._fetch_reading(site, self._safe_date(MIN_DAYS_BACK), "realtime")

    async def forecast(self, site: Site, hours: int) -> List[Reading]:
        """Fetch temperature readings for the site.

        QUOTA NOTE: FortyGuard allows 30 heatmaps/day. With hours=0 (default in
        live mode) we make exactly 1 API call per site per scan. Only increase
        LOOKAHEAD_HOURS if you have quota headroom — each extra hour = 1 more call.
        """
        # Always fetch the base reading (noon, 3 days back — guaranteed to have data)
        base_reading = await self._fetch_reading(site, self._safe_date(MIN_DAYS_BACK), "realtime")
        readings = [base_reading]

        if hours <= 0:
            # Quota-safe mode: single call only
            return readings

        # Optional hourly readings for shift window (costs 1 call each)
        base = self._safe_date(MIN_DAYS_BACK).replace(hour=6)
        async with httpx.AsyncClient() as client:
            for h in range(1, min(hours, 12) + 1):
                when = base + timedelta(hours=h)
                payload = self._build_payload(site, when)
                try:
                    activity_id = await self._submit(client, payload)
                    body = await self._poll(client, activity_id)
                    data = body.get("data") or body
                    features = ((data.get("result") or {}).get("map_data") or {}).get("features") or []
                    temp_f = plausible_mean_f(temps_from_body(data))
                    readings.append(Reading(
                        site_id=site.id,
                        ts_utc=when,
                        temp_f=temp_f,
                        source="fortyguard",
                        provenance="realtime",
                        detail={"features": len(features)},
                    ))
                except (FortyGuardError, httpx.HTTPError):
                    pass

        return readings

    async def historical(self, site: Site, start: datetime, end: datetime) -> List[Reading]:
        readings = []
        cursor = start.replace(minute=0, second=0, microsecond=0)
        async with httpx.AsyncClient() as client:
            while cursor <= end:
                payload = self._build_payload(site, cursor)
                try:
                    activity_id = await self._submit(client, payload)
                    body = await self._poll(client, activity_id)
                    data = body.get("data") or body
                    features = ((data.get("result") or {}).get("map_data") or {}).get("features") or []
                    temp_f = plausible_mean_f(temps_from_body(data))
                    readings.append(Reading(
                        site_id=site.id,
                        ts_utc=cursor,
                        temp_f=temp_f,
                        source="fortyguard",
                        provenance="historical",
                        detail={"features": len(features)},
                    ))
                except (FortyGuardError, httpx.HTTPError):
                    pass
                cursor += timedelta(hours=1)
        return readings
