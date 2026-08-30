"""Submit ONE heatmap and print the raw body of every status poll.

This is the tool probe_api.py should have been: probe_api calls
provider._poll(), which swallows every intermediate response and returns
nothing until the job completes — so when the job never completes it hangs
exactly like the app does, and you learn nothing.

    python -m tools.poll_raw                       # first site
    python -m tools.poll_raw ucla-gayley-towers-05
    python -m tools.poll_raw ucla-gayley-towers-05 --days 5 --polls 6

What to look at in the output:
  * the top-level keys of the status body
  * where the word Processing / Completed actually lives, and its exact spelling
  * whether "result" ever appears, and whether map_data.features is non-empty
"""
import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx

from app import config
from app.providers.base import bbox_polygon
from app.sites import all_sites, get_site


def find_status_like(node, path="$", out=None):
    """Report every key whose name or value smells like a job status."""
    out = [] if out is None else out
    words = ("processing", "completed", "complete", "pending", "queued",
             "running", "failed", "error", "success", "done", "finished")
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and (
                "status" in k.lower() or "state" in k.lower() or v.lower() in words
            ):
                out.append((f"{path}.{k}", v))
            find_status_like(v, f"{path}.{k}", out)
    elif isinstance(node, list):
        for i, v in enumerate(node[:3]):
            find_status_like(v, f"{path}[{i}]", out)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("site_id", nargs="?")
    ap.add_argument("--days", type=int, default=3, help="days back to request")
    ap.add_argument("--polls", type=int, default=5, help="how many status calls to print")
    ap.add_argument("--interval", type=float, default=4.0)
    args = ap.parse_args()

    key = config._fg_key()
    if not key:
        print("FORTYGUARD_API_KEY is not set in .env")
        return 1

    site = get_site(args.site_id) if args.site_id else all_sites()[0]
    if site is None:
        print(f"unknown site '{args.site_id}'")
        return 1

    when = (datetime.now(timezone.utc) - timedelta(days=args.days)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    payload = {
        "polygon_aoi": bbox_polygon(site.lat, site.lng, config.FG_AOI_SIDE_M),
        "date_time": {
            "start_date": when.strftime("%Y-%m-%d"),
            "start_time": when.strftime("%H:%M"),
            "filter_type": 1,
        },
        "granularity": config.FG_GRANULARITY,
    }
    headers = {"api-key": key, "Content-Type": "application/json"}

    print(f"site        : {site.name} ({site.lat}, {site.lng})")
    print(f"requested   : {when:%Y-%m-%d %H:%M} UTC  ({args.days} days back)")
    print(f"aoi side    : {config.FG_AOI_SIDE_M} m   granularity: {config.FG_GRANULARITY} m")
    print(f"submit      : {config.FG_BASE_URL}/heatmap\n")

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{config.FG_BASE_URL}/heatmap", headers=headers, json=payload)
        print(f"--- submit  HTTP {r.status_code} ---")
        try:
            body = r.json()
        except ValueError:
            print(r.text[:1000])
            return 1
        print(json.dumps(body, indent=2)[:1200])
        r.raise_for_status()

        activity_id = (body.get("data") or {}).get("activity_id") or body.get("activity_id")
        if not activity_id:
            print("\nno activity_id in the submit response — nothing to poll")
            return 1

        url = f"{config.FG_BASE_URL}/status/{activity_id}"
        print(f"\npoll        : {url}")

        for i in range(1, args.polls + 1):
            await asyncio.sleep(args.interval)
            r = await client.get(url, headers=headers)
            print(f"\n--- poll {i}  HTTP {r.status_code}  ({datetime.now():%H:%M:%S}) ---")
            try:
                sbody = r.json()
            except ValueError:
                print(r.text[:1500])
                continue

            data = sbody.get("data") or {}
            print(f"top-level keys : {list(sbody.keys())}")
            print(f"data keys      : {list(data.keys()) if isinstance(data, dict) else type(data)}")

            hits = find_status_like(sbody)
            if hits:
                print("status-like fields:")
                for path, val in hits[:10]:
                    print(f"    {path} = {val!r}")
            else:
                print("status-like fields: NONE FOUND  <-- this is why the loop never exits")

            # What the current parser sees:
            parsed = str((sbody.get("data") or {}).get("status") or sbody.get("status") or "").lower()
            print(f"parser reads status as: {parsed!r}")

            feats = ((data.get("result") or {}).get("map_data") or {}).get("features") or []
            print(f"features       : {len(feats)}")

            blob = json.dumps(sbody, indent=2)
            print(f"body ({len(blob)} chars):")
            print(blob[:2000])

            if parsed in ("completed", "complete", "success", "done", "finished"):
                print("\n>>> job completed. Stopping.")
                break

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
