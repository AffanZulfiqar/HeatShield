"""Run the worksite-versus-station comparison across every site.

    python -m tools.run_comparison            # 7 days, all sites
    python -m tools.run_comparison 14         # 14 days

Writes out/comparison-<date>.csv and prints the summary table. The
blind-hours column is the number to put on a slide.
"""
import asyncio
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import comparison, config
from app.sites import all_sites

OUT = Path(__file__).resolve().parent.parent / "out"


async def main() -> int:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    OUT.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    csv_path = OUT / f"comparison-{stamp}.csv"

    print(f"mode: {config.resolved_mode()}   window: {days} days\n")
    if config.is_replay():
        print("REPLAY MODE. The gap below is a parameter, not a measurement.\n")

    results = []
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["site_id", "site_name", "hour_utc", "site_f", "station_f", "delta_f", "blind_for"])
        for site in all_sites():
            try:
                r = await comparison.compare(site, days=days)
            except Exception as exc:
                print(f"  {site.id}: failed ({exc})")
                continue
            for row in r["rows"]:
                writer.writerow([site.id, site.name, row["hour_utc"], row["site_f"],
                                 row["station_f"], row["delta_f"], "|".join(row["blind_for"])])
            results.append(r)

    header = f"{'site':<24} {'station':<10} {'km':>5} {'peak d':>7} {'mean d':>7} {'blind h':>8}"
    print(header)
    print("-" * len(header))
    total_blind = 0
    for r in results:
        total_blind += r["blind_hours_total"]
        print(
            f"{r['site']['id']:<24} {r['station']['id']:<10} {r['station']['distance_km']:>5} "
            f"{r['peak_delta_f']:>7} {r['mean_delta_f']:>7} {r['blind_hours_total']:>8}"
        )
    print("-" * len(header))
    print(f"{'TOTAL':<24} {'':<10} {'':>5} {'':>7} {'':>7} {total_blind:>8}")
    print(f"\nHours where a worksite was over a statutory threshold and the nearest official")
    print(f"station was not, across {len(results)} sites over {days} days: {total_blind}")
    print(f"\nper-hour detail written to {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
