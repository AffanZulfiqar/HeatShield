"""Quick script to replace sites.json with Alabama test sites.

Run from the project root:
    python -m tools.seed_alabama
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES_FILE = ROOT / "data" / "sites.json"

ALABAMA = {
    "_note": "Alabama test sites for FortyGuard live mode verification.",
    "sites": [
        {
            "id": "al-birmingham-construct-01",
            "name": "Birmingham I-20 overpass crew",
            "operator": "Alabama DOT",
            "industry": "construction",
            "jurisdiction": "us-federal",
            "lat": 33.5186,
            "lng": -86.8104,
            "timezone": "America/Chicago",
            "shift_start": "06:00",
            "shift_end": "14:00",
            "supervisor": "super-bhm-01",
            "clothing": "standard",
            "notes": "Highway overpass construction. Full sun exposure.",
            "replay": {"base_f": 80.0, "amplitude_f": 22.0, "surface_offset_f": 6.0}
        },
        {
            "id": "al-mobile-port-02",
            "name": "Mobile port loading dock",
            "operator": "Port of Mobile Authority",
            "industry": "transportation",
            "jurisdiction": "us-federal",
            "lat": 30.6954,
            "lng": -88.0431,
            "timezone": "America/Chicago",
            "shift_start": "07:00",
            "shift_end": "15:00",
            "supervisor": "super-mob-02",
            "clothing": "standard",
            "notes": "Coastal Gulf humidity. High apparent temperature.",
            "replay": {"base_f": 78.0, "amplitude_f": 18.0, "surface_offset_f": 5.0}
        },
        {
            "id": "al-huntsville-ag-03",
            "name": "Huntsville soybean fields, north block",
            "operator": "Tennessee Valley Farms",
            "industry": "agriculture",
            "jurisdiction": "us-federal",
            "lat": 34.7304,
            "lng": -86.5861,
            "timezone": "America/Chicago",
            "shift_start": "05:30",
            "shift_end": "13:30",
            "supervisor": "crew-lead-hsv",
            "clothing": "standard",
            "notes": "Open field, no shade. Early start to beat afternoon peak.",
            "replay": {"base_f": 76.0, "amplitude_f": 24.0, "surface_offset_f": 4.5}
        }
    ]
}

SITES_FILE.write_text(json.dumps(ALABAMA, indent=2), encoding="utf-8")
print(f"Written {len(ALABAMA['sites'])} Alabama sites to {SITES_FILE}")
for s in ALABAMA["sites"]:
    print(f"  {s['id']:40s}  {s['lat']}, {s['lng']}")
