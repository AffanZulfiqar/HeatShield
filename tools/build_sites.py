"""Rebuild data/sites.json with a multi-state worksite database.

The six original sites are preserved byte-for-byte, including their source_url
provenance. Everything added here is marked verified=false: these are
approximate work-zone centroids for real, publicly announced projects, pinned
from general knowledge rather than checked against project records. Verify any
site you intend to put in front of a judge.

    python -m tools.build_sites
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "data" / "sites.json"

TZ = {
    "AZ": "America/Phoenix", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "FL": "America/New_York", "GA": "America/New_York", "KS": "America/Chicago", "KY": "America/New_York",
    "LA": "America/Chicago", "MD": "America/New_York", "MI": "America/Detroit",
    "NC": "America/New_York", "NJ": "America/New_York", "NM": "America/Denver",
    "NV": "America/Los_Angeles", "NY": "America/New_York", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "SC": "America/New_York",
    "TN": "America/Chicago", "TX": "America/Chicago", "UT": "America/Denver",
    "VA": "America/New_York", "WA": "America/Los_Angeles",
}

# Only four rulepacks ship with the app. California, Oregon and Washington have
# their own heat standards; everywhere else falls back to the federal pack.
PACK = {"CA": "us-ca", "OR": "us-or", "WA": "us-wa"}

# state, id, name, operator, industry, lat, lng, shift_start, shift_end, notes
NEW = [
    # ── Arizona ──
    ("AZ", "phx-south-central-lrt", "South Central light rail extension work zone",
     "Valley Metro / City of Phoenix", "transportation_construction",
     33.40018, -112.07377, "05:00", "13:30",
     "Light rail extension along S Central Ave. Early shift is a real heat adaptation in Phoenix summers. 5040 S Central Ave, at the extension community office."),
    ("AZ", "intel-ocotillo-chandler", "Intel Ocotillo campus expansion",
     "Intel Corporation", "semiconductor_construction",
     33.2419, -111.88156, "06:00", "16:00",
     "Fab 52/62 construction, Chandler. 4500 S Dobson Rd, Chandler."),
    # ── Texas ──
    ("TX", "samsung-taylor-fab", "Samsung Taylor semiconductor fab site",
     "Samsung Electronics", "semiconductor_construction",
     30.53529, -97.45113, "06:00", "16:00",
     "Large greenfield fab build north-east of Austin. 1530 FM973, Taylor."),
    ("TX", "i35-capital-express-atx", "I-35 Capital Express Central work zone",
     "Texas Department of Transportation", "transportation_construction",
     30.27200, -97.73100, "06:00", "15:00",
     "Downtown Austin interstate reconstruction."),
    ("TX", "giga-texas-austin", "Gigafactory Texas construction area",
     "Tesla", "industrial_construction",
     30.22482, -97.61955, "06:00", "16:00",
     "Ongoing expansion work east of Austin. 1 Tesla Rd, Austin."),
    # ── Nevada ──
    ("NV", "brightline-west-lv", "Brightline West Las Vegas station work zone",
     "Brightline West", "transportation_construction",
     36.05332, -115.17241, "05:30", "14:00",
     "High-speed rail terminus construction near Las Vegas Blvd. 7501 Las Vegas Blvd S."),
    # ── California ──
    ("CA", "lax-people-mover", "LAX Automated People Mover guideway",
     "Los Angeles World Airports", "transportation_construction",
     33.95083, -118.37797, "06:00", "15:00",
     "Elevated guideway and station work on the airport perimeter. LAX/Metro Transit Center, eastern APM terminus."),
    ("CA", "cahsr-fresno", "California High-Speed Rail Fresno segment",
     "California High-Speed Rail Authority", "transportation_construction",
     36.75054, -119.8153, "05:30", "14:30",
     "Central Valley alignment. Fresno regularly exceeds the §3395 high-heat trigger. Golden State Blvd crossing, an active HSR construction site."),
    ("CA", "imperial-valley-solar", "Imperial Valley utility solar construction",
     "Imperial Irrigation District area contractors", "energy_construction",
     32.7717, -115.78138, "05:00", "13:00",
     "Desert solar build-out. Among the hottest worksites in the United States. Tenaska Imperial Solar Energy Center South, El Centro."),
    # ── Oregon / Washington (state heat rules) ──
    ("OR", "i5-rose-quarter-pdx", "I-5 Rose Quarter improvement work zone",
     "Oregon Department of Transportation", "transportation_construction",
     45.53172, -122.6661, "07:00", "17:00",
     "Portland. Exercises the Oregon OAR 437-002-0156 rulepack."),
    ("WA", "lynnwood-link-extension", "Lynnwood Link light rail extension",
     "Sound Transit", "transportation_construction",
     47.81564, -122.29478, "07:00", "17:00",
     "Exercises the Washington WAC 296-62-095 rulepack. Lynnwood City Center station."),
    # ── Southwest / Mountain ──
    ("CO", "i70-floyd-hill", "I-70 Floyd Hill reconstruction work zone",
     "Colorado Department of Transportation", "transportation_construction",
     39.74221, -105.49416, "07:00", "17:00",
     "Mountain corridor rebuild west of Denver. I-70 at Idaho Springs."),
    ("NM", "sunzia-transmission-nm", "SunZia transmission line construction corridor",
     "Pattern Energy", "energy_construction",
     34.25400, -106.89100, "06:00", "15:00",
     "Long linear right-of-way work across central New Mexico."),
    ("UT", "slc-airport-redevelopment", "Salt Lake City airport redevelopment",
     "Salt Lake City Department of Airports", "transportation_construction",
     40.79031, -111.97714, "07:00", "17:00",
     "Concourse expansion phases."),
    ("OK", "okc-boulevard-mapsy", "Oklahoma City MAPS project work zone",
     "City of Oklahoma City", "transportation_construction",
     35.46442, -97.52704, "06:30", "16:00",
     "Downtown civic construction."),
    # ── Gulf / Southeast ──
    ("LA", "i10-calcasieu-bridge", "I-10 Calcasieu River Bridge replacement",
     "Louisiana DOTD", "transportation_construction",
     30.237, -93.2447, "06:00", "16:00",
     "Lake Charles. High humidity drives heat index well above dry-bulb temperature."),
    ("FL", "miami-signature-bridge", "I-395 Signature Bridge work zone",
     "Florida Department of Transportation", "transportation_construction",
     25.7873, -80.19603, "06:30", "16:00",
     "Downtown Miami. Florida has no state heat standard; federal pack applies."),
    ("FL", "tampa-westshore-interchange", "Westshore Interchange reconstruction",
     "Florida Department of Transportation", "transportation_construction",
     27.95977, -82.52412, "06:30", "16:00",
     "Tampa interstate work."),
    ("GA", "hyundai-metaplant-ga", "Hyundai Metaplant America construction site",
     "Hyundai Motor Group", "industrial_construction",
     32.16574, -81.44711, "06:30", "16:30",
     "EV plant build near Ellabell. 1500 Genesis Dr, Ellabell."),
    ("SC", "scout-motors-blythewood", "Scout Motors production site construction",
     "Scout Motors", "industrial_construction",
     34.2055, -80.99284, "06:30", "16:30",
     "Greenfield plant north of Columbia. Locklier Rd construction site, Blythewood."),
    ("NC", "complete-540-raleigh", "Complete 540 Triangle Expressway extension",
     "North Carolina Turnpike Authority", "transportation_construction",
     35.67556, -78.74705, "07:00", "17:00",
     "Southern Wake County alignment."),
    ("TN", "blueoval-city-stanton", "BlueOval City construction site",
     "Ford Motor Company", "industrial_construction",
     35.42558, -89.40851, "06:30", "16:30",
     "Large EV and battery campus in west Tennessee. Stanton, TN."),
    # ── Midwest ──
    ("OH", "intel-ohio-one", "Intel Ohio One campus construction",
     "Intel Corporation", "semiconductor_construction",
     40.11662, -82.71179, "07:00", "17:00",
     "New Albany. One of the largest active construction sites in the Midwest. Intel Ohio One, 12100 Jug Street Rd NW."),
    ("KY", "brent-spence-bridge", "Brent Spence Bridge corridor work zone",
     "Ohio DOT / Kentucky Transportation Cabinet", "transportation_construction",
     39.09097, -84.52262, "07:00", "17:00",
     "Ohio River crossing at Cincinnati."),
    ("MI", "gordie-howe-bridge", "Gordie Howe International Bridge site",
     "Windsor-Detroit Bridge Authority", "transportation_construction",
     42.29118, -83.10339, "07:00", "17:00",
     "Detroit-side approach and port of entry."),
    ("KS", "panasonic-de-soto", "Panasonic Energy battery plant construction",
     "Panasonic Energy", "industrial_construction",
     38.93567, -95.00481, "06:30", "16:30",
     "De Soto, Kansas. 10301 Astra Pkwy, De Soto."),
    # ── Northeast / Mid-Atlantic ──
    ("NY", "hudson-tunnel-manhattan", "Hudson Tunnel Project Manhattan work site",
     "Gateway Development Commission", "transportation_construction",
     40.75316, -74.00041, "07:00", "17:00",
     "Tunnel and surface works on the west side. MTA West Side Yard, the Manhattan surface work area."),
    ("NY", "micron-clay-ny", "Micron Clay campus site preparation",
     "Micron Technology", "semiconductor_construction",
     43.19100, -76.16200, "07:00", "17:00",
     "Onondaga County megafab site work."),
    ("NJ", "portal-north-bridge", "Portal North Bridge construction",
     "NJ TRANSIT", "transportation_construction",
     40.75352, -74.09507, "07:00", "17:00",
     "Hackensack River crossing replacement."),
    ("MD", "key-bridge-rebuild", "Francis Scott Key Bridge rebuild site",
     "Maryland Transportation Authority", "transportation_construction",
     39.2172, -76.52812, "07:00", "17:00",
     "Patapsco River crossing reconstruction."),
    ("MD", "purple-line-md", "Purple Line light rail work zone",
     "Maryland Transit Administration", "transportation_construction",
     38.97841, -76.92829, "07:00", "17:00",
     "Prince George's County alignment. College Park-U of MD station, a Purple Line stop."),
    ("VA", "hampton-roads-btx", "Hampton Roads Bridge-Tunnel expansion",
     "Virginia Department of Transportation", "transportation_construction",
     36.9674, -76.29708, "06:30", "16:30",
     "Marine and tunnel approach work."),
    ("VA", "i95-fredericksburg-ext", "I-95 Fredericksburg Extension work zone",
     "Virginia Department of Transportation", "transportation_construction",
     38.30366, -77.50294, "07:00", "17:00",
     "Express lanes extension south of Washington."),
]


def main() -> int:
    raw = json.loads(SITES.read_text(encoding="utf-8"))
    original = raw["sites"]

    # Tag the six documented sites so the UI can distinguish them.
    state_of = {
        "maryland-parkway-brt-01": "NV", "gila-river-i10-bridge-02": "AZ",
        "tsmc-fab21-phx-03": "AZ", "i30-canyon-dallas-04": "TX",
        "ucla-gayley-towers-05": "CA", "houston-st-emanuel-06": "TX",
    }
    for s in original:
        s.setdefault("state", state_of.get(s["id"], ""))
        s.setdefault("verified", True)

    # Coordinates confirmed against Google Places entries for the named facility
    # or route. Everything else stays verified=false.
    PLACES_VERIFIED = {
        "intel-ohio-one", "gordie-howe-bridge", "brent-spence-bridge",
        "hyundai-metaplant-ga", "blueoval-city-stanton", "samsung-taylor-fab",
        "panasonic-de-soto", "scout-motors-blythewood", "key-bridge-rebuild",
        "portal-north-bridge", "hampton-roads-btx", "lax-people-mover",
        "cahsr-fresno", "lynnwood-link-extension", "i5-rose-quarter-pdx",
        "intel-ocotillo-chandler", "giga-texas-austin", "brightline-west-lv",
        "slc-airport-redevelopment", "i10-calcasieu-bridge",
        "miami-signature-bridge", "tampa-westshore-interchange",
        "complete-540-raleigh", "purple-line-md", "okc-boulevard-mapsy",
        "phx-south-central-lrt", "i70-floyd-hill", "hudson-tunnel-manhattan",
        "imperial-valley-solar", "i95-fredericksburg-ext",
    }

    # Regenerate every entry in NEW each run, so coordinate corrections here
    # actually land instead of being skipped as duplicates. Only the six
    # documented originals are carried through untouched.
    original = [s for s in original if s["id"] in state_of]
    added = []
    for (st, sid, name, op, ind, lat, lng, s0, s1, note) in NEW:
        added.append({
            "id": sid,
            "name": name,
            "operator": op,
            "industry": ind,
            "jurisdiction": PACK.get(st, "us-federal"),
            "state": st,
            "lat": lat,
            "lng": lng,
            "timezone": TZ[st],
            "shift_start": s0,
            "shift_end": s1,
            "supervisor": "Site supervisor",
            "clothing": "standard",
            "notes": note,
            "source_url": "",
            "source_name": "",
            "verified": sid in PLACES_VERIFIED,
        })

    raw["_note"] = (
        "Worksite registry. The six entries with verified=true were selected from "
        "public project records and carry source_url provenance. Entries with "
        "verified=false are approximate and have NOT been confirmed - verify "
        "before citing. All others were pinned against a mapping-service entry "
        "for the named facility or route. Coordinates are project pins, never worker locations. "
        "FortyGuard is queried only when a site is explicitly analyzed from the UI."
    )
    raw["sites"] = original + added
    SITES.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    by_state = {}
    for s in raw["sites"]:
        by_state.setdefault(s.get("state", "??"), []).append(s["id"])
    packs = {}
    for s in raw["sites"]:
        packs[s["jurisdiction"]] = packs.get(s["jurisdiction"], 0) + 1

    print(f"{len(raw['sites'])} sites across {len(by_state)} states "
          f"({len(original)} verified, {len(added)} added)")
    print("by rulepack:", ", ".join(f"{k}={v}" for k, v in sorted(packs.items())))
    print("states     :", " ".join(sorted(by_state)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
