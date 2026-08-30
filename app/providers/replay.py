"""Offline replay provider.

Generates deterministic synthetic temperatures so the whole system - agent
loop, rule engine, ledger, alerts, PDF - runs with no API key and no network.
Useful for development, CI, and a demo that cannot be broken by someone else's
rate limit five minutes before you present.

IMPORTANT, and stated everywhere this data surfaces: these numbers are
invented. Every reading is stamped provenance="replay-synthetic", every ledger
entry carries the same stamp, and the PDF prints a banner. The site-versus-
station gap in replay mode is a parameter declared in data/sites.json, not a
measurement, so it proves the plumbing works and proves nothing about the
world. The real gap only comes from live mode.
"""
import hashlib
import math
import os
from datetime import datetime, timedelta, timezone
from typing import List

from app.models import Reading, Site

DEFAULTS = {"base_f": 78.0, "amplitude_f": 16.0, "surface_offset_f": 4.0, "noise_f": 1.2}

# Pin the diurnal phase so a rehearsed demo behaves the same at 3pm and at 3am.
# REPLAY_PIN_HOUR=9 makes "now" sit at 09:00 local on the synthetic curve, which
# puts the afternoon threshold crossings ahead of you where the pre-breach
# advisories can be seen firing. Unset means follow the real clock.
_PIN_HOUR = os.getenv("REPLAY_PIN_HOUR", "").strip()
PIN_HOUR = float(_PIN_HOUR) if _PIN_HOUR else None
_REFERENCE = datetime.now(timezone.utc)
_pin_deltas: dict = {}


def _params(site: Site) -> dict:
    p = dict(DEFAULTS)
    p.update(getattr(site, "_replay", None) or {})
    return p


def _jitter(site_id: str, ts: datetime, scale: float) -> float:
    """Deterministic pseudo-noise: same site and hour always give the same value."""
    key = f"{site_id}:{ts.strftime('%Y-%m-%dT%H')}".encode()
    h = int(hashlib.sha256(key).hexdigest()[:8], 16)
    return ((h / 0xFFFFFFFF) * 2 - 1) * scale


def _raw_local_hour(site: Site, ts: datetime) -> float:
    """Approximate local solar hour from longitude. Good enough for a diurnal curve."""
    return ts.hour + ts.minute / 60.0 + site.lng / 15.0


def _local_hour(site: Site, ts: datetime) -> float:
    if PIN_HOUR is None:
        return _raw_local_hour(site, ts) % 24.0
    if site.id not in _pin_deltas:
        _pin_deltas[site.id] = PIN_HOUR - _raw_local_hour(site, _REFERENCE)
    return (_raw_local_hour(site, ts) + _pin_deltas[site.id]) % 24.0


def synth_f(site: Site, ts: datetime, *, include_surface: bool = True) -> float:
    """Diurnal curve peaking around 15:00 local, plus a seasonal term."""
    p = _params(site)
    hour = _local_hour(site, ts)
    diurnal = -math.cos((hour - 3.0) / 24.0 * 2 * math.pi)
    day_of_year = ts.timetuple().tm_yday
    seasonal = math.sin((day_of_year - 105) / 365.0 * 2 * math.pi) * 8.0
    value = p["base_f"] + seasonal + diurnal * p["amplitude_f"] / 2.0
    if include_surface:
        value += p["surface_offset_f"]
    return value + _jitter(site.id, ts, p["noise_f"])


class ReplayProvider:
    name = "replay"

    async def current(self, site: Site) -> Reading:
        now = datetime.now(timezone.utc)
        return Reading(
            site_id=site.id,
            ts_utc=now,
            temp_f=synth_f(site, now),
            source="replay",
            provenance="replay-synthetic",
            detail={"warning": "synthetic value, not a measurement"},
        )

    async def forecast(self, site: Site, hours: int) -> List[Reading]:
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        out = []
        for h in range(hours + 1):
            ts = now + timedelta(hours=h)
            out.append(
                Reading(
                    site_id=site.id,
                    ts_utc=ts,
                    temp_f=synth_f(site, ts),
                    source="replay",
                    provenance="replay-synthetic" if h == 0 else "replay-synthetic-forecast",
                    detail={"warning": "synthetic value, not a measurement"},
                )
            )
        return out

    async def historical(self, site: Site, start: datetime, end: datetime) -> List[Reading]:
        out = []
        cursor = start.replace(minute=0, second=0, microsecond=0)
        while cursor <= end:
            out.append(
                Reading(
                    site_id=site.id,
                    ts_utc=cursor,
                    temp_f=synth_f(site, cursor),
                    source="replay",
                    provenance="replay-synthetic",
                    detail={"warning": "synthetic value, not a measurement"},
                )
            )
            cursor += timedelta(hours=1)
        return out
