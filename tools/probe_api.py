"""Probe the FortyGuard API and print exactly what comes back.

Run this the moment your key arrives, before writing anything else:

    python -m tools.probe_api                    # first site in the registry
    python -m tools.probe_api coachella-ag-05

It prints the submit response, the poll response, every key path that contains
a number, and the values the parser picked up. Use that to confirm or correct
four things in .env:

    FG_POLL_PATH          the path that returns a finished activity
    FG_UNITS              c or f, as actually returned
    FG_FILTER_CURRENT     filter_type for a current reading
    FG_FILTER_FORECAST    filter_type for a forecast reading

If the numbers look wrong, they are wrong here, not three layers up.
"""
import asyncio
import json
import sys

import httpx

from app import config
from app.providers.base import bbox_polygon
from app.providers.fortyguard import FortyGuardProvider, extract_temps
from app.sites import all_sites, get_site


def walk_numeric(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk_numeric(v, f"{path}.{k}")
    elif isinstance(node, list):
        if node and isinstance(node[0], (int, float)):
            yield f"{path}[]", f"{len(node)} numbers, first {node[0]}"
        else:
            for i, v in enumerate(node[:2]):
                yield from walk_numeric(v, f"{path}[{i}]")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield path, node


async def main() -> int:
    if not config.FG_API_KEY:
        print("FORTYGUARD_API_KEY is not set. Put it in .env and try again.")
        return 1

    site = get_site(sys.argv[1]) if len(sys.argv) > 1 else all_sites()[0]
    if site is None:
        print(f"unknown site '{sys.argv[1]}'")
        return 1

    provider = FortyGuardProvider()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    payload = {
        "polygon_aoi": bbox_polygon(site.lat, site.lng, config.FG_AOI_SIDE_M),
        "date_time": {
            "start_date": now.strftime("%Y-%m-%d"),
            "start_time": now.strftime("%H:%M"),
            "filter_type": config.FG_FILTER_CURRENT,
        },
        "granularity": config.FG_GRANULARITY,
    }

    print(f"site      : {site.name} ({site.lat}, {site.lng})")
    print(f"submit to : {config.FG_BASE_URL}{config.FG_SUBMIT_PATH}")
    print(f"payload   : {json.dumps(payload)[:400]}\n")

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{config.FG_BASE_URL}{config.FG_SUBMIT_PATH}",
            headers={config.FG_AUTH_HEADER: config.FG_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        print(f"submit status: {r.status_code}")
        print(json.dumps(r.json(), indent=2)[:1500])
        r.raise_for_status()
        activity_id = (r.json().get("data") or {}).get("activity_id") or r.json().get("activity_id")
        print(f"\nactivity_id: {activity_id}")

        body = await provider._poll(client, activity_id)

    print("\n--- poll response (first 3000 chars) ---")
    print(json.dumps(body, indent=2)[:3000])

    print("\n--- every numeric path ---")
    for path, value in list(walk_numeric(body))[:60]:
        print(f"  {path} = {value}")

    temps = extract_temps(body)
    print(f"\n--- parser picked up {len(temps)} values ---")
    if temps:
        mean = sum(temps) / len(temps)
        print(f"  raw mean      : {mean:.2f}")
        print(f"  as C -> F     : {mean * 9 / 5 + 32:.1f}F")
        print(f"  as F already  : {mean:.1f}F")
        print(f"  FG_UNITS is currently '{config.FG_UNITS}'. Pick whichever is plausible for")
        print(f"  {site.name} right now and set it in .env.")
    else:
        print("  none. Widen TEMP_KEY_HINTS in app/providers/fortyguard.py to match the keys above.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
