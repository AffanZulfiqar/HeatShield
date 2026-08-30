"""Resolve a map pin to a state, a rulepack, and a timezone — offline.

A worksite's legal duties follow from where it is, so the jurisdiction should
be derived from the pin rather than chosen from a dropdown. Picking the wrong
rulepack by hand is silent: the app still produces a confident status card,
just against the wrong law.

State boundaries are bundled (data/us_states.geojson, ~72 KB) so this needs no
geocoding service, no API key, and no network. Coordinates are rounded to four
decimal places, roughly 11 m, which is well inside the accuracy a state-level
answer needs.
"""
import json
from functools import lru_cache
from typing import Optional

from app.config import DATA_DIR

STATES_FILE = DATA_DIR / "us_states.geojson"

NAME_TO_CODE = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
    "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Puerto Rico": "PR", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY",
}

# States with their own heat-illness standard AND a rulepack shipped in this app.
# Everything else falls back to the federal pack (OSHA general duty clause).
STATE_RULEPACK = {"CA": "us-ca", "OR": "us-or", "WA": "us-wa"}

# States that have adopted or proposed their own heat rule but for which this
# app has no pack yet. Surfaced as a warning so the gap is visible rather than
# silently papered over with the federal pack.
KNOWN_GAPS = {
    "NV": "Nevada adopted a heat illness regulation in 2024",
    "MD": "Maryland adopted a heat stress standard in 2024",
    "CO": "Colorado has rules covering agricultural workers",
    "MN": "Minnesota has an indoor heat standard",
}

STATE_TZ = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
    "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis",
    "IA": "America/Chicago", "KS": "America/Chicago", "KY": "America/New_York",
    "LA": "America/Chicago", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
    "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver",
    "NE": "America/Chicago", "NV": "America/Los_Angeles", "NH": "America/New_York",
    "NJ": "America/New_York", "NM": "America/Denver", "NY": "America/New_York",
    "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York",
    "PR": "America/Puerto_Rico", "RI": "America/New_York", "SC": "America/New_York",
    "SD": "America/Chicago", "TN": "America/Chicago", "TX": "America/Chicago",
    "UT": "America/Denver", "VT": "America/New_York", "VA": "America/New_York",
    "WA": "America/Los_Angeles", "WV": "America/New_York", "WI": "America/Chicago",
    "WY": "America/Denver",
}


@lru_cache(maxsize=1)
def _states() -> list:
    """[(code, name, bbox, [rings...]), ...] with a bounding box per state."""
    raw = json.loads(STATES_FILE.read_text(encoding="utf-8"))
    out = []
    for feat in raw.get("features", []):
        name = (feat.get("properties") or {}).get("name")
        code = NAME_TO_CODE.get(name)
        if not code:
            continue
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        polys = coords if gtype == "Polygon" else [p for mp in coords for p in mp] \
            if gtype == "MultiPolygon" else []
        # For MultiPolygon each element is a polygon (list of rings); flatten to
        # outer rings only. Holes are rare at state level and never decide a
        # worksite's jurisdiction.
        rings = []
        if gtype == "Polygon":
            rings = [coords[0]] if coords else []
        elif gtype == "MultiPolygon":
            rings = [poly[0] for poly in coords if poly]
        if not rings:
            continue
        xs = [pt[0] for r in rings for pt in r]
        ys = [pt[1] for r in rings for pt in r]
        out.append((code, name, (min(xs), min(ys), max(xs), max(ys)), rings))
    return out


def _in_ring(lng: float, lat: float, ring: list) -> bool:
    """Ray casting. True if the point is inside this ring."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            if lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
                inside = not inside
        j = i
    return inside


def state_for(lat: float, lng: float) -> Optional[str]:
    """Two-letter state code for a point, or None if outside the dataset."""
    for code, _name, (x0, y0, x1, y1), rings in _states():
        if not (x0 <= lng <= x1 and y0 <= lat <= y1):
            continue                      # bbox reject first, it's much cheaper
        for ring in rings:
            if _in_ring(lng, lat, ring):
                return code
    return None


def nearest_state(lat: float, lng: float, max_km: float = 60.0):
    """Closest state to a point that falls in no polygon, or None if far out.

    Bridges, tunnels, piers and port work sit over water, outside every land
    boundary. Those are exactly the worksites this app is for, so an offshore
    pin should get a proposed answer rather than a shrug.
    """
    best, best_d = None, float("inf")
    for code, _name, (x0, y0, x1, y1), rings in _states():
        # Cheap bbox distance first; only measure vertices for plausible states.
        dx = max(x0 - lng, 0, lng - x1)
        dy = max(y0 - lat, 0, lat - y1)
        if (dx * dx + dy * dy) ** 0.5 > 2.0:      # ~220 km, generous prefilter
            continue
        for ring in rings:
            for px, py in ring:
                # Equirectangular approximation; fine at these distances.
                ddx = (px - lng) * 111.32 * max(0.05, abs(_cos_deg(lat)))
                ddy = (py - lat) * 110.57
                d = (ddx * ddx + ddy * ddy) ** 0.5
                if d < best_d:
                    best_d, best = d, code
    if best is None or best_d > max_km:
        return None, None
    return best, best_d


def _cos_deg(deg: float) -> float:
    import math
    return math.cos(math.radians(deg))


def resolve(lat: float, lng: float) -> dict:
    """Everything derivable from a pin: state, rulepack, timezone, caveats."""
    code = state_for(lat, lng)
    over_water = False
    water_km = 0.0

    if code is None:
        code, water_km = nearest_state(lat, lng)
        over_water = code is not None

    if code is None:
        return {
            "lat": lat, "lng": lng,
            "state": "", "state_name": "",
            "jurisdiction": "us-federal",
            "timezone": "UTC",
            "resolved": False,
            "over_water": False,
            "reason": "Point is outside the bundled U.S. state boundaries. "
                      "Falling back to the federal rulepack — confirm manually.",
            "warning": "",
        }

    name = next((n for c, n, _b, _r in _states() if c == code), code)
    pack = STATE_RULEPACK.get(code, "us-federal")
    if pack == "us-federal":
        reason = (f"{name} has no state heat standard packaged in this app, "
                  f"so federal OSHA rules apply.")
    else:
        reason = f"{name} has its own heat-illness standard; the {pack} pack applies."

    if over_water:
        reason = (f"Pin is over water, {water_km:.1f} km from the nearest land "
                  f"boundary ({name}). {reason}")

    return {
        "lat": lat, "lng": lng,
        "state": code,
        "state_name": name,
        "jurisdiction": pack,
        "timezone": STATE_TZ.get(code, "UTC"),
        "resolved": True,
        "over_water": over_water,
        "reason": reason,
        # Non-empty when the state regulates heat but this app has no pack for it.
        "warning": (f"{KNOWN_GAPS[code]}, but no rulepack ships for it — "
                    f"the federal pack is being used instead.")
                   if code in KNOWN_GAPS else "",
    }
