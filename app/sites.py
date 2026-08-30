"""Site registry — loaded from data/sites.json, writable at runtime."""
import json
import re
import threading
from functools import lru_cache
from typing import List, Optional

from app.config import DATA_DIR
from app.models import Site

SITES_FILE = DATA_DIR / "sites.json"
_lock = threading.Lock()


def _load_raw() -> dict:
    return json.loads(SITES_FILE.read_text(encoding="utf-8"))


def _save_raw(raw: dict) -> None:
    SITES_FILE.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@lru_cache(maxsize=1)
def _load() -> List[Site]:
    raw = _load_raw()
    sites = []
    for entry in raw["sites"]:
        entry = dict(entry)
        replay = entry.pop("replay", None)
        entry.pop("_note", None)
        site = Site(**entry)
        object.__setattr__(site, "_replay", replay or {})
        sites.append(site)
    return sites


def _invalidate():
    _load.cache_clear()


def all_sites() -> List[Site]:
    return list(_load())


def get_site(site_id: str) -> Optional[Site]:
    for s in _load():
        if s.id == site_id:
            return s
    return None


def require_site(site_id: str) -> Site:
    site = get_site(site_id)
    if site is None:
        raise KeyError(f"unknown site '{site_id}'")
    return site


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    existing = {s.id for s in all_sites()}
    candidate = slug
    i = 2
    while candidate in existing:
        candidate = f"{slug}-{i}"
        i += 1
    return candidate


def add_site(data: dict) -> Site:
    """Add a new site, persist to sites.json, return the Site object."""
    with _lock:
        raw = _load_raw()
        site_id = data.get("id") or _slugify(data.get("name", "site"))

        # Derive jurisdiction/state/timezone from the pin unless explicitly
        # given. The location is the ground truth for which law applies, so a
        # caller that omits them should get the correct pack, not a default.
        from app.geo import resolve as _resolve
        loc = _resolve(float(data["lat"]), float(data["lng"]))
        data = {**data}
        data.setdefault("jurisdiction", loc["jurisdiction"])
        data.setdefault("state", loc["state"])
        data.setdefault("timezone", loc["timezone"])
        entry = {
            "id": site_id,
            "name": data["name"],
            "operator": data.get("operator", ""),
            "industry": data.get("industry", "construction"),
            "jurisdiction": data.get("jurisdiction", "us-federal"),
            "lat": float(data["lat"]),
            "lng": float(data["lng"]),
            "timezone": data.get("timezone", "America/New_York"),
            "shift_start": data.get("shift_start", "07:00"),
            "shift_end": data.get("shift_end", "17:00"),
            "supervisor": data.get("supervisor", ""),
            "clothing": data.get("clothing", "standard"),
            "notes": data.get("notes", ""),
            "source_url": data.get("source_url", ""),
            "source_name": data.get("source_name", ""),
            "state": (data.get("state") or "").upper()[:2],
            "verified": bool(data.get("verified", False)),
        }
        raw["sites"].append(entry)
        _save_raw(raw)
        _invalidate()
        return require_site(site_id)


def remove_site(site_id: str) -> bool:
    """Remove a site by id. Returns True if removed."""
    with _lock:
        raw = _load_raw()
        before = len(raw["sites"])
        raw["sites"] = [s for s in raw["sites"] if s["id"] != site_id]
        if len(raw["sites"]) == before:
            return False
        _save_raw(raw)
        _invalidate()
        return True
