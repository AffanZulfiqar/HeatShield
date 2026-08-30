"""Worksite temperature versus the nearest official station.

This produces the single number the whole pitch rests on: blind hours. An hour
is blind when the worksite was above a statutory threshold and the station a
compliance officer would have consulted was not. Those are hours where an
employer following standard practice was out of compliance and had no way to
know.

Run this first, before building anything else on top. If the blind-hour count
comes back near zero for real sites on real days, the premise is wrong and you
want to find that out on day one rather than day nine.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app import config
from app.models import Reading, Site
from app.providers import get_provider
from app.providers.station import get_station_provider
from app.rules import engine


def _bucket(readings: List[Reading]) -> dict:
    """Average readings into hourly buckets keyed by ISO hour."""
    buckets: dict = {}
    for r in readings:
        key = r.ts_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
        buckets.setdefault(key, []).append(r.temp_f)
    return {k: sum(v) / len(v) for k, v in buckets.items()}


def _thresholds_for(site: Site) -> List[dict]:
    pack = engine.load_pack(site.jurisdiction)
    out = []
    for t in pack["thresholds"]:
        if t["severity"] == "baseline":
            continue
        if t.get("industries") != "all" and site.industry not in t.get("industries", []):
            continue
        if t.get("clothing", "any") not in ("any", site.clothing):
            continue
        out.append(t)
    return out


async def compare(site: Site, days: int = 7, end: Optional[datetime] = None) -> dict:
    from app import config as _cfg
    # FortyGuard only serves data >= 3 days old; clamp end accordingly in live mode
    if end is None:
        if not _cfg.is_replay():
            end = datetime.now(timezone.utc) - timedelta(days=3)
        else:
            end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    provider = get_provider()
    station = get_station_provider()

    site_readings = await provider.historical(site, start, end)
    station_readings = await station.historical(site, start, end)
    station_id, station_name, distance_km = await station.nearest_station(site)

    site_h = _bucket(site_readings)
    station_h = _bucket(station_readings)
    shared = sorted(set(site_h) & set(station_h))

    thresholds = _thresholds_for(site)
    blind = {t["id"]: 0 for t in thresholds}
    over_both = {t["id"]: 0 for t in thresholds}
    rows = []
    peak_delta = 0.0
    peak_hour = None
    deltas = []

    for hour in shared:
        s, w = site_h[hour], station_h[hour]
        delta = s - w
        deltas.append(delta)
        if abs(delta) > abs(peak_delta):
            peak_delta, peak_hour = delta, hour
        flags = []
        for t in thresholds:
            if s >= t["value_f"]:
                if w < t["value_f"]:
                    blind[t["id"]] += 1
                    flags.append(t["id"])
                else:
                    over_both[t["id"]] += 1
        rows.append(
            {
                "hour_utc": hour,
                "site_f": round(s, 1),
                "station_f": round(w, 1),
                "delta_f": round(delta, 1),
                "blind_for": flags,
            }
        )

    total_blind = sum(blind.values())
    return {
        "site": {"id": site.id, "name": site.name, "industry": site.industry,
                 "jurisdiction": site.jurisdiction, "clothing": site.clothing},
        "station": {"id": station_id, "name": station_name, "distance_km": round(distance_km, 1)},
        "window": {"start_utc": start.isoformat(), "end_utc": end.isoformat(), "days": days},
        "hours_compared": len(shared),
        "peak_delta_f": round(peak_delta, 1),
        "peak_delta_hour_utc": peak_hour,
        "mean_delta_f": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        "blind_hours_total": total_blind,
        "blind_hours_by_threshold": [
            {
                "threshold_id": t["id"],
                "name": t["name"],
                "trigger_f": t["value_f"],
                "citation": t.get("citation"),
                "blind_hours": blind[t["id"]],
                "hours_both_over": over_both[t["id"]],
            }
            for t in thresholds
        ],
        "mode": config.resolved_mode(),
        "caveat": (
            "REPLAY MODE: the site-station gap here is a declared parameter in "
            "data/sites.json, not a measurement. It demonstrates the calculation and "
            "proves nothing about the world. Re-run with a FortyGuard key for a real figure."
            if config.is_replay()
            else "Live comparison: FortyGuard worksite values against NWS station observations."
        ),
        "rows": rows,
    }
